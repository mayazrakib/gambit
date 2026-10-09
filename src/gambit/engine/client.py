import asyncio
import hashlib
import logging
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
from typing import NotRequired, TypedDict

import chess

from gambit.infrastructure.configuration import Configuration

DEFAULT_NODES = 100_000
DEFAULT_MULTIPV = 3
MAX_NODES = 2_000_000
MAX_MULTIPV = 5
ENGINE_RESPONSE_TIMEOUT_SECONDS = 30
ENGINE_THREADS = 1
ENGINE_HASH_MB = 16
ENGINE_REQUEST_EXECUTOR = ThreadPoolExecutor(
    max_workers=4,
    thread_name_prefix="gambit-analysis",
)
ENGINE_REQUEST_SLOTS = threading.BoundedSemaphore(32,)

async def execute_engine_request[
    Result,
    **Parameters,
](
    operation: Callable[
        Parameters,
        Result,
    ],
    *args: Parameters.args,
    **kwargs: Parameters.kwargs,
) -> Result:
    if not ENGINE_REQUEST_SLOTS.acquire(blocking=False,):
        raise RuntimeError("The MCP operation queue is full. Retry after active work completes.",)

    try:
        future = ENGINE_REQUEST_EXECUTOR.submit(
            operation,
            *args,
            **kwargs,
        )
    except RuntimeError:
        ENGINE_REQUEST_SLOTS.release()

        raise

    future.add_done_callback(lambda completed: ENGINE_REQUEST_SLOTS.release(),)

    try:
        while not future.done():
            await asyncio.sleep(0.01,)

        return future.result()
    finally:
        future.cancel()

class EngineLine(TypedDict):
    centipawns: int | None
    mate_in: int | None
    pv: list[chess.Move]
    depth: NotRequired[int]
    actual_nodes: NotRequired[int]
    engine_time_ms: NotRequired[int]

def get_stockfish_path() -> str:
    configured_path = os.environ.get("STOCKFISH_PATH",)

    if configured_path:
        return configured_path

    discovered_path = shutil.which("stockfish",)

    if discovered_path:
        return discovered_path

    raise RuntimeError("Stockfish was not found. Install it or set STOCKFISH_PATH to its executable.",)

@dataclass(frozen=True,)
class Evaluation:
    centipawns: int | None
    pawns: float | None
    mate_in: int | None

class StockfishClient:
    def __init__(
        self,
        configuration: Configuration | None = None,
    ) -> None:
        self.configuration = configuration or Configuration()
        self.has_explicit_configuration = configuration is not None
        self.binary_digest: str | None = None
        self.last_metrics: dict[
            str,
            int,
        ] = {}
        self.process: subprocess.Popen[str] | None = None
        self.lock = threading.Lock()
        self.cache: OrderedDict[
            tuple,
            list[EngineLine],
        ] = OrderedDict()
        self.multipv: int | None = None
        self.output: Queue[str | None] = Queue()
        self.reader: threading.Thread | None = None
        self.name = "Stockfish"
        self.version: str | None = None

    def close(self,) -> None:
        with self.lock:
            self.stop()

    def stop(self,) -> None:
        process = self.process
        self.process = None
        self.multipv = None

        if process is None:
            return

        if process.poll() is None:
            process.kill()

        process.wait(timeout=ENGINE_RESPONSE_TIMEOUT_SECONDS,)

        if self.reader is not None:
            self.reader.join(timeout=ENGINE_RESPONSE_TIMEOUT_SECONDS,)

        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except BrokenPipeError:
                    logging.getLogger(__name__,).debug("The terminated engine pipe was already broken during cleanup.",)

    @staticmethod
    def collect_output(
        process: subprocess.Popen[str],
        output: Queue[str | None],
    ) -> None:
        try:
            if process.stdout is not None:
                for line in process.stdout:
                    output.put(line.strip(),)
        finally:
            output.put(None,)

    def start(self,) -> None:
        engine_path = (
            self.configuration.engine_path
            if self.has_explicit_configuration
            else get_stockfish_path()
        )
        self.process = subprocess.Popen(
            [engine_path,],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
            env={name: setting for name, setting in os.environ.items() if not name.startswith(("OPENAI_", "CONTROL_PLANE_"),)},
        )
        self.output = Queue()
        self.reader = threading.Thread(
            target=self.collect_output,
            args=(self.process, self.output),
            daemon=True,
        )
        self.reader.start()
        self.send("uci",)
        self.read_until("uciok",)
        self.send(f"setoption name Threads value {self.configuration.threads_per_worker}",)
        self.send(f"setoption name Hash value {self.configuration.hash_mb_per_worker}",)
        self.send("setoption name UCI_ShowWDL value true",)

        if self.configuration.syzygy_path:
            from pathlib import Path

            directories = os.pathsep.join((str(Path(path,).expanduser().resolve(),) for path in self.configuration.syzygy_path.split(os.pathsep,) if path),)
            self.send(f"setoption name SyzygyPath value {directories}",)

        executable = shutil.which(engine_path,)

        if executable:
            with open(
                executable,
                "rb",
            ) as binary_file:
                self.binary_digest = hashlib.file_digest(
                    binary_file,
                    "sha256",
                ).hexdigest()

        self.send("isready",)
        self.read_until("readyok",)

    def send(
        self,
        command: str,
    ) -> None:
        if self.process is None or self.process.stdin is None:
            raise RuntimeError("Stockfish is not running.",)

        self.process.stdin.write(f"{command}\n",)
        self.process.stdin.flush()

    def read_line(
        self,
        deadline: float,
    ) -> str:
        remaining_seconds = deadline - monotonic()

        if remaining_seconds <= 0:
            raise RuntimeError("Stockfish timed out waiting for a response.",)

        try:
            line = self.output.get(timeout=remaining_seconds,)
        except Empty as exception:
            raise RuntimeError("Stockfish timed out waiting for a response.",) from exception

        if line is None:
            raise RuntimeError("Stockfish stopped before returning a response.",)

        return line

    def read_until(
        self,
        expected_line: str,
    ) -> None:
        deadline = monotonic() + ENGINE_RESPONSE_TIMEOUT_SECONDS

        while True:
            line = self.read_line(deadline,)

            if line.startswith("id name ",):
                self.name = line.removeprefix("id name ",)
                self.version = (
                    self.name.removeprefix("Stockfish ",)
                    if self.name.startswith("Stockfish ",)
                    else None
                )

            if line == expected_line:
                return

    def analyze(
        self,
        board: chess.Board,
        multipv: int,
        nodes: int,
        *,
        root_moves: tuple[
            str,
            ...,
        ] = (),
        cancellation: threading.Event | None = None,
    ) -> list[EngineLine]:
        with self.lock:
            if cancellation is not None and cancellation.is_set():
                raise InterruptedError("Analysis was cancelled.",)

            for notation in root_moves:
                parse_move(
                    board,
                    notation,
                )

            cache_key = (
                board.fen(),
                multipv,
                nodes,
                tuple((move.uci() for move in board.move_stack),),
                root_moves,
                board.root().fen(),
            )

            if cache_key in self.cache:
                analysis = self.cache.pop(cache_key,)
                self.cache[cache_key] = analysis

                return analysis

            try:
                if self.process is None:
                    self.start()

                if multipv != self.multipv:
                    self.send(f"setoption name MultiPV value {multipv}",)
                    self.multipv = multipv

                if self.configuration.is_reproducible:
                    self.send("ucinewgame",)

                self.send("isready",)
                self.read_until("readyok",)
                root = board.root()
                history = " ".join((move.uci() for move in board.move_stack),)
                self.send(f"position fen {root.fen()} moves {history}",)
                search_command = f"go nodes {nodes} movetime {self.configuration.search_time_ms} depth {self.configuration.search_depth}"

                if root_moves:
                    search_command += " searchmoves " + " ".join(root_moves,)

                self.send(search_command,)
                analysis = self.read_analysis(
                    board,
                    cancellation,
                )
            except InterruptedError:
                raise
            except (OSError, ValueError, RuntimeError) as exception:
                self.stop()
                raise RuntimeError(f"Stockfish analysis failed: {exception}.",) from exception

            self.cache[cache_key] = analysis

            while len(self.cache,) > self.configuration.cache_capacity:
                self.cache.popitem(last=False,)

            return analysis

    def read_analysis(
        self,
        board: chess.Board,
        cancellation: threading.Event | None = None,
    ) -> list[EngineLine]:
        lines_by_rank: dict[
            int,
            EngineLine,
        ] = {}
        deadline = monotonic() + ENGINE_RESPONSE_TIMEOUT_SECONDS
        was_cancelled = False

        while True:
            if cancellation is not None and cancellation.is_set() and not was_cancelled:
                self.send("stop",)
                was_cancelled = True

            if monotonic() >= deadline:
                raise RuntimeError("Stockfish timed out waiting for a response.",)

            try:
                line = self.output.get(timeout=0.05,)
            except Empty:
                continue

            if line is None:
                raise RuntimeError("Stockfish stopped before returning a response.",)

            if line.startswith("bestmove ",):
                if was_cancelled:
                    raise InterruptedError("Analysis was cancelled.",)

                best_move = chess.Move.from_uci(line.split()[1],)

                if best_move not in board.legal_moves:
                    raise RuntimeError("Stockfish returned an invalid best move.",)

                return [lines_by_rank[rank] for rank in sorted(lines_by_rank,)]

            if not line.startswith("info ",) or " pv " not in line:
                continue

            tokens = line.split()

            for field in ("depth", "seldepth", "nodes", "time", "nps"):
                metric = get_uci_integer(
                    tokens,
                    field,
                    default=0,
                )
                self.last_metrics[field] = metric

            rank = get_uci_integer(
                tokens,
                "multipv",
                default=1,
            )
            score_index = get_uci_token_index(
                tokens,
                "score",
            )
            pv_index = get_uci_token_index(
                tokens,
                "pv",
            )

            if score_index is None or pv_index is None or score_index + 2 >= len(tokens,):
                continue

            if "lowerbound" in tokens or "upperbound" in tokens:
                continue

            score_type = tokens[score_index + 1]

            if score_type not in ("cp", "mate"):
                continue

            score_value = int(tokens[score_index + 2],)
            moves: list[chess.Move] = []

            for token in tokens[pv_index + 1 :]:
                try:
                    moves.append(chess.Move.from_uci(token,),)
                except ValueError:
                    break

            lines_by_rank[rank] = {
                "centipawns": score_value if score_type == "cp" else None,
                "mate_in": score_value if score_type == "mate" else None,
                "pv": moves,
                "depth": self.last_metrics.get(
                    "depth",
                    0,
                ),
                "actual_nodes": self.last_metrics.get(
                    "nodes",
                    0,
                ),
                "engine_time_ms": self.last_metrics.get(
                    "time",
                    0,
                ),
            }

def get_uci_token_index(
    tokens: list[str],
    token: str,
) -> int | None:
    try:
        return tokens.index(token,)
    except ValueError:
        return None

def get_uci_integer(
    tokens: list[str],
    token: str,
    default: int,
) -> int:
    token_index = get_uci_token_index(
        tokens,
        token,
    )

    if token_index is None or token_index + 1 >= len(tokens,):
        return default

    try:
        return int(tokens[token_index + 1],)
    except ValueError:
        return default

def validate_nodes(nodes: int,) -> int:
    if isinstance(
        nodes,
        bool,
    ) or not isinstance(
        nodes,
        int,
    ):
        raise TypeError("Nodes must be an integer.",)

    if not 1 <= nodes <= MAX_NODES:
        raise ValueError(f"Nodes must be between 1 and {MAX_NODES:,}.",)

    return nodes

def validate_multipv(multipv: int,) -> int:
    if isinstance(
        multipv,
        bool,
    ) or not isinstance(
        multipv,
        int,
    ):
        raise TypeError("MultiPV must be an integer.",)

    if not 1 <= multipv <= MAX_MULTIPV:
        raise ValueError(f"MultiPV must be between 1 and {MAX_MULTIPV}.",)

    return multipv

def parse_board(fen: str,) -> chess.Board:
    try:
        board = chess.Board(fen,)
    except ValueError as exception:
        raise ValueError("FEN must be a valid Forsyth-Edwards Notation position.",) from exception

    if not board.is_valid():
        raise ValueError("FEN does not describe a valid chess position.",)

    return board

def parse_move(
    board: chess.Board,
    move_text: str,
) -> chess.Move:
    try:
        move = board.parse_san(move_text,)
    except ValueError:
        try:
            move = chess.Move.from_uci(move_text,)
        except ValueError as exception:
            raise ValueError(f"Move {move_text!r} is neither SAN nor UCI notation.",) from exception

    if move not in board.legal_moves:
        raise ValueError(f"Move {move_text!r} is not legal in this position.",)

    return move

def get_evaluation(information: EngineLine,) -> Evaluation:
    mate_in = information["mate_in"]

    if mate_in is not None:
        return Evaluation(
            centipawns=None,
            pawns=None,
            mate_in=mate_in,
        )

    centipawns = information["centipawns"]

    if centipawns is None:
        return Evaluation(
            centipawns=None,
            pawns=None,
            mate_in=None,
        )

    return Evaluation(
        centipawns=centipawns,
        pawns=round(
            centipawns / 100,
            2,
        ),
        mate_in=None,
    )

def get_variation(
    board: chess.Board,
    moves: list[chess.Move],
) -> list[dict[
    str,
    str,
]]:
    variation_board = board.copy()
    variation: list[dict[
        str,
        str,
    ]] = []

    for move in moves:
        if move not in variation_board.legal_moves:
            break

        variation.append({"san": variation_board.san(move,), "uci": move.uci(),},)
        variation_board.push(move,)

    return variation
