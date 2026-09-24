import asyncio
import os
import shutil
import subprocess
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from queue import Empty, Queue
from time import monotonic
from typing import TypedDict

import chess

DEFAULT_NODES = 100_000
DEFAULT_MULTIPV = 3
MAX_NODES = 2_000_000
MAX_MULTIPV = 5
ENGINE_RESPONSE_TIMEOUT_SECONDS = 30
ENGINE_THREADS = 1
ENGINE_HASH_MB = 16
ENGINE_REQUEST_EXECUTOR = ThreadPoolExecutor(
    max_workers=4, thread_name_prefix="gambit-analysis"
)


async def execute_engine_request[Result, **Parameters](
    operation: Callable[Parameters, Result],
    *args: Parameters.args,
    **kwargs: Parameters.kwargs,
) -> Result:
    """Keep MCP responsive despite broken thread wakeups in the supported runtime.

    Poll the bounded worker pool instead of relying on thread completion to wake
    the event loop (also avoided by Gambit's stdio adapter). Engine locking is
    per position, so independent requests can share the warm process safely.
    """
    future = ENGINE_REQUEST_EXECUTOR.submit(operation, *args, **kwargs)
    try:
        while not future.done():
            await asyncio.sleep(0.01)
        return future.result()
    finally:
        future.cancel()


class EngineLine(TypedDict):
    centipawns: int | None
    mate_in: int | None
    pv: list[chess.Move]


def get_stockfish_path() -> str:
    configured_path = os.environ.get("STOCKFISH_PATH")
    if configured_path:
        return configured_path

    discovered_path = shutil.which("stockfish")
    if discovered_path:
        return discovered_path

    raise RuntimeError(
        "Stockfish was not found. Install it or set STOCKFISH_PATH to its executable."
    )


@dataclass(frozen=True)
class Evaluation:
    centipawns: int | None
    pawns: float | None
    mate_in: int | None


class StockfishClient:
    def __init__(self) -> None:
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.cache: OrderedDict[tuple[str, int, int], list[EngineLine]] = OrderedDict()
        self.multipv: int | None = None
        self.output: Queue[str | None] = Queue()
        self.reader: threading.Thread | None = None
        self.name = "Stockfish"
        self.version: str | None = None

    def close(self) -> None:
        with self.lock:
            self.stop()

    def stop(self) -> None:
        """Dispose of a failed or finished process while holding the client lock."""
        process = self.process
        self.process = None
        self.multipv = None
        if process is None:
            return
        if process.poll() is None:
            process.kill()
        process.wait(timeout=ENGINE_RESPONSE_TIMEOUT_SECONDS)
        if self.reader is not None:
            self.reader.join(timeout=ENGINE_RESPONSE_TIMEOUT_SECONDS)
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                stream.close()

    @staticmethod
    def collect_output(
        process: subprocess.Popen[str], output: Queue[str | None]
    ) -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    output.put(line.strip())
        finally:
            output.put(None)

    def start(self) -> None:
        self.process = subprocess.Popen(
            [get_stockfish_path()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self.output = Queue()
        self.reader = threading.Thread(
            target=self.collect_output,
            args=(self.process, self.output),
            daemon=True,
        )
        self.reader.start()
        self.send("uci")
        self.read_until("uciok")
        self.send(f"setoption name Threads value {ENGINE_THREADS}")
        self.send(f"setoption name Hash value {ENGINE_HASH_MB}")
        self.send("isready")
        self.read_until("readyok")

    def send(self, command: str) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Stockfish is not running.")
        self.process.stdin.write(f"{command}\n")
        self.process.stdin.flush()

    def read_line(self, deadline: float) -> str:
        remaining_seconds = deadline - monotonic()
        if remaining_seconds <= 0:
            raise RuntimeError("Stockfish timed out waiting for a response.")
        try:
            line = self.output.get(timeout=remaining_seconds)
        except Empty as exception:
            raise RuntimeError(
                "Stockfish timed out waiting for a response."
            ) from exception
        if line is None:
            raise RuntimeError("Stockfish stopped before returning a response.")
        return line

    def read_until(self, expected_line: str) -> None:
        deadline = monotonic() + ENGINE_RESPONSE_TIMEOUT_SECONDS
        while True:
            line = self.read_line(deadline)
            if line.startswith("id name "):
                self.name = line.removeprefix("id name ")
                self.version = (
                    self.name.removeprefix("Stockfish ")
                    if self.name.startswith("Stockfish ")
                    else None
                )
            if line == expected_line:
                return

    def analyze(self, board: chess.Board, multipv: int, nodes: int) -> list[EngineLine]:
        with self.lock:
            cache_key = (board.fen(), multipv, nodes)
            if cache_key in self.cache:
                analysis = self.cache.pop(cache_key)
                self.cache[cache_key] = analysis
                return analysis
            try:
                if self.process is None:
                    self.start()
                if multipv != self.multipv:
                    self.send(f"setoption name MultiPV value {multipv}")
                    self.multipv = multipv
                # Fixed settings and a fresh search hash make results independent
                # of earlier requests while retaining the warm engine process.
                self.send("ucinewgame")
                self.send("isready")
                self.read_until("readyok")
                self.send(f"position fen {board.fen()}")
                self.send(f"go nodes {nodes}")
                analysis = self.read_analysis(board)
            except (OSError, ValueError, RuntimeError) as exception:
                self.stop()
                raise RuntimeError(
                    f"Stockfish analysis failed: {exception}"
                ) from exception
            self.cache[cache_key] = analysis
            while len(self.cache) > 128:
                self.cache.popitem(last=False)
            return analysis

    def read_analysis(self, board: chess.Board) -> list[EngineLine]:
        lines_by_rank: dict[int, EngineLine] = {}
        deadline = monotonic() + ENGINE_RESPONSE_TIMEOUT_SECONDS
        while True:
            line = self.read_line(deadline)
            if line.startswith("bestmove "):
                best_move = chess.Move.from_uci(line.split()[1])
                if best_move not in board.legal_moves:
                    raise RuntimeError("Stockfish returned an invalid best move.")
                return [lines_by_rank[rank] for rank in sorted(lines_by_rank)]
            if not line.startswith("info ") or " pv " not in line:
                continue
            tokens = line.split()
            rank = get_uci_integer(tokens, "multipv", default=1)
            score_index = get_uci_token_index(tokens, "score")
            pv_index = get_uci_token_index(tokens, "pv")
            if (
                score_index is None
                or pv_index is None
                or score_index + 2 >= len(tokens)
            ):
                continue
            if "lowerbound" in tokens or "upperbound" in tokens:
                continue
            score_type = tokens[score_index + 1]
            if score_type not in ("cp", "mate"):
                continue
            score_value = int(tokens[score_index + 2])
            moves: list[chess.Move] = []
            for token in tokens[pv_index + 1 :]:
                try:
                    moves.append(chess.Move.from_uci(token))
                except ValueError:
                    break
            lines_by_rank[rank] = {
                "centipawns": score_value if score_type == "cp" else None,
                "mate_in": score_value if score_type == "mate" else None,
                "pv": moves,
            }


def get_uci_token_index(tokens: list[str], token: str) -> int | None:
    try:
        return tokens.index(token)
    except ValueError:
        return None


def get_uci_integer(tokens: list[str], token: str, default: int) -> int:
    token_index = get_uci_token_index(tokens, token)
    if token_index is None or token_index + 1 >= len(tokens):
        return default

    try:
        return int(tokens[token_index + 1])
    except ValueError:
        return default


def validate_nodes(nodes: int) -> int:
    if isinstance(nodes, bool) or not isinstance(nodes, int):
        raise TypeError("nodes must be an integer.")

    if not 1 <= nodes <= MAX_NODES:
        raise ValueError(f"nodes must be between 1 and {MAX_NODES:,}.")

    return nodes


def validate_multipv(multipv: int) -> int:
    if isinstance(multipv, bool) or not isinstance(multipv, int):
        raise TypeError("multipv must be an integer.")

    if not 1 <= multipv <= MAX_MULTIPV:
        raise ValueError(f"multipv must be between 1 and {MAX_MULTIPV}.")

    return multipv


def parse_board(fen: str) -> chess.Board:
    try:
        board = chess.Board(fen)
    except ValueError as exception:
        raise ValueError(
            "fen must be a valid Forsyth-Edwards Notation position."
        ) from exception

    if not board.is_valid():
        raise ValueError("fen does not describe a valid chess position.")

    return board


def parse_move(board: chess.Board, move_text: str) -> chess.Move:
    try:
        move = board.parse_san(move_text)
    except ValueError:
        try:
            move = chess.Move.from_uci(move_text)
        except ValueError as exception:
            raise ValueError(
                f"{move_text!r} is neither SAN nor UCI notation."
            ) from exception

    if move not in board.legal_moves:
        raise ValueError(f"{move_text!r} is not legal in this position.")

    return move


def get_evaluation(information: EngineLine) -> Evaluation:
    mate_in = information["mate_in"]
    if mate_in is not None:
        return Evaluation(centipawns=None, pawns=None, mate_in=mate_in)

    centipawns = information["centipawns"]
    if centipawns is None:
        return Evaluation(centipawns=None, pawns=None, mate_in=None)

    return Evaluation(
        centipawns=centipawns,
        pawns=round(centipawns / 100, 2),
        mate_in=None,
    )


def get_variation(board: chess.Board, moves: list[chess.Move]) -> list[dict[str, str]]:
    variation_board = board.copy()
    variation: list[dict[str, str]] = []

    for move in moves:
        if move not in variation_board.legal_moves:
            break

        variation.append({"san": variation_board.san(move), "uci": move.uci()})
        variation_board.push(move)

    return variation
