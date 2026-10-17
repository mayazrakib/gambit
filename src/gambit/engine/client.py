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
from contextvars import ContextVar
from dataclasses import dataclass
from queue import Empty, Queue
from time import monotonic

import chess

from gambit.engine.uci import EngineLine, get_uci_integer, parse_analysis_line
from gambit.infrastructure.configuration import Configuration

DEFAULT_NODES = 12_000
DEFAULT_MULTIPV = 1
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

@dataclass(frozen=True,)
class RequestContext:
    cancellation: threading.Event
    deadline: float | None = None
    is_background: bool = False
    parent: "RequestContext | None" = None

    def is_set(self,) -> bool:
        return self.cancellation.is_set() or (self.deadline is not None and monotonic() >= self.deadline) or (self.parent is not None and self.parent.is_set())

REQUEST_CONTEXT: ContextVar[RequestContext | None] = ContextVar(
    "gambit_request_context",
    default=None,
)

@dataclass(frozen=True,)
class RequestCancellation:
    cancellation: threading.Event | None
    context: RequestContext | None

    def is_set(self,) -> bool:
        return (self.cancellation is not None and self.cancellation.is_set()) or (self.context is not None and self.context.is_set())

def get_request_cancellation(cancellation: threading.Event | None = None,) -> RequestCancellation:
    return RequestCancellation(
        cancellation,
        REQUEST_CONTEXT.get(),
    )

def check_request_active(cancellation: threading.Event | None = None,) -> None:
    context = REQUEST_CONTEXT.get()

    if context is not None and context.deadline is not None and monotonic() >= context.deadline:
        raise TimeoutError("The analysis request deadline expired.",)

    if (cancellation is not None and cancellation.is_set()) or (context is not None and context.is_set()):
        raise InterruptedError("Analysis was cancelled.",)

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

    submitted = monotonic()
    inherited_context = REQUEST_CONTEXT.get()

    context = RequestContext(
        threading.Event(),
        inherited_context.deadline if inherited_context is not None else None,
        inherited_context.is_background if inherited_context is not None else False,
        inherited_context,
    )

    def run_operation() -> Result:
        started = monotonic()
        context_token = REQUEST_CONTEXT.set(context,)

        try:
            check_request_active()

            return operation(
                *args,
                **kwargs,
            )
        finally:
            REQUEST_CONTEXT.reset(context_token,)

            logging.getLogger(__name__,).info(
                "MCP operation %s completed. Queue: %.2f ms. Execution: %.2f ms.",
                getattr(
                    operation,
                    "__qualname__",
                    type(operation,).__name__,
                ),
                (started - submitted) * 1000,
                (monotonic() - started) * 1000,
            )

    try:
        future = ENGINE_REQUEST_EXECUTOR.submit(run_operation,)
    except RuntimeError:
        ENGINE_REQUEST_SLOTS.release()

        raise

    future.add_done_callback(lambda completed: ENGINE_REQUEST_SLOTS.release(),)

    try:
        return await asyncio.wrap_future(future,)
    finally:
        context.cancellation.set()
        future.cancel()

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
        cancellation = get_request_cancellation(cancellation,)

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
                search_time_ms = self.configuration.get_search_time_ms(nodes,)
                search_command = f"go nodes {nodes} movetime {search_time_ms} depth {self.configuration.search_depth}"

                if root_moves:
                    search_command += " searchmoves " + " ".join(root_moves,)

                self.send(search_command,)

                analysis = self.read_analysis(
                    board,
                    cancellation,
                )

                if root_moves and any((line["pv"][0].uci() not in root_moves for line in analysis),):
                    raise RuntimeError("Stockfish returned a move outside the requested candidates.",)
            except (InterruptedError, TimeoutError):
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
        cancellation = get_request_cancellation(cancellation,)
        self.last_metrics = {}

        if board.is_game_over():
            raise ValueError("A terminal position cannot have a new engine variation.",)

        lines_by_rank: dict[
            int,
            EngineLine,
        ] = {}

        lines_by_move: dict[
            chess.Move,
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
                if was_cancelled or cancellation.is_set():
                    check_request_active()

                    raise InterruptedError("Analysis was cancelled.",)

                best_move = chess.Move.from_uci(line.split()[1],)

                if best_move not in board.legal_moves:
                    raise RuntimeError("Stockfish returned an invalid best move.",)

                principal = lines_by_rank.get(1,)

                if principal is None or not principal["pv"] or principal["pv"][0] != best_move:
                    principal = lines_by_move.get(best_move,)

                if principal is None:
                    raise RuntimeError("Stockfish's best move does not match its scored principal variation.",)

                lines = [principal,]
                roots = {best_move,}

                for rank in range(
                    2,
                    len(lines_by_rank,) + 1,
                ):
                    variation = lines_by_rank.get(rank,)

                    if variation is None or variation.get("depth",) != principal.get("depth",) or variation["pv"][0] in roots:
                        break

                    roots.add(variation["pv"][0],)
                    lines.append(variation,)

                for information in lines:
                    replay = board.copy()
                    moves = []

                    for move in information["pv"]:
                        if replay.is_game_over():
                            break

                        if move not in replay.legal_moves:
                            raise RuntimeError("Stockfish returned an illegal principal variation.",)

                        moves.append(move,)
                        replay.push(move,)

                    information["pv"] = moves

                return lines

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

            parsed_line = parse_analysis_line(
                tokens,
                self.last_metrics,
            )

            if parsed_line is not None:
                rank, information = parsed_line

                if rank < 1 or not information["pv"]:
                    raise RuntimeError("Stockfish returned an empty or invalid ranked variation.",)

                lines_by_rank[rank] = information
                lines_by_move[information["pv"][0]] = information

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
        if variation_board.is_game_over() or move not in variation_board.legal_moves:
            raise RuntimeError("The variation is illegal or continues beyond an automatic terminal state.",)

        variation.append({"san": variation_board.san(move,), "uci": move.uci(),},)
        variation_board.push(move,)

    return variation
