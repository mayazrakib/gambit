from __future__ import annotations

import asyncio
import atexit
import os
import shutil
import subprocess
import sys
import threading
from collections import OrderedDict
from dataclasses import asdict, dataclass
from typing import Any, Literal

import chess
from mcp.server import MCPServer
from mcp.server.stdio import stdio_server

DEFAULT_NODES = 100_000
DEFAULT_MULTIPV = 3
MAX_NODES = 2_000_000
MAX_MULTIPV = 5
ENGINE_RESPONSE_TIMEOUT_SECONDS = 30
Orientation = Literal["auto", "white", "black"]


class AsyncStdin:
    """Read stdin without AnyIO's worker-thread based AsyncFile adapter."""

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._transport: asyncio.ReadTransport | None = None

    def __aiter__(self) -> AsyncStdin:
        return self

    async def __anext__(self) -> str:
        if self._reader is None:
            self._reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(self._reader)
            transport, _ = await asyncio.get_running_loop().connect_read_pipe(
                lambda: protocol,
                sys.stdin,
            )
            self._transport = transport

        line = await self._reader.readline()
        if not line:
            raise StopAsyncIteration

        return line.decode("utf-8", errors="replace")


class AsyncStdout:
    """Expose stdout with the small async interface expected by stdio_server."""

    async def write(self, data: str) -> None:
        sys.stdout.write(data)

    async def flush(self) -> None:
        sys.stdout.flush()


class GambitMCPServer(MCPServer):
    async def run_stdio_async(self) -> None:
        if sys.platform == "win32":
            await super().run_stdio_async()
            return

        # The default MCP stdio adapter delegates every read and write to an
        # AnyIO worker thread. Thread completion notifications are unreliable
        # in the Python 3.14 runtime used by Gambit, leaving every request hung.
        async with stdio_server(
            stdin=AsyncStdin(),  # type: ignore[arg-type]
            stdout=AsyncStdout(),  # type: ignore[arg-type]
        ) as (read_stream, write_stream):
            await self._lowlevel_server.run(
                read_stream,
                write_stream,
                self._lowlevel_server.create_initialization_options(),
            )


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
        self._process: subprocess.Popen[str] | None = None
        self._lock = threading.Lock()
        self._cache: OrderedDict[tuple[str, int, int], list[dict[str, Any]]] = (
            OrderedDict()
        )
        self._multipv: int | None = None

    def close(self) -> None:
        with self._lock:
            if self._process is None:
                return

            if self._process.stdin is not None:
                self._process.stdin.write("quit\n")
                self._process.stdin.flush()

            self._process.terminate()
            self._process.wait(timeout=ENGINE_RESPONSE_TIMEOUT_SECONDS)
            self._process = None
            self._multipv = None

    def _start(self) -> None:
        self._process = subprocess.Popen(
            [get_stockfish_path()],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            bufsize=1,
        )
        self._send("uci")
        self._read_until("uciok")
        self._send("isready")
        self._read_until("readyok")

    def _send(self, command: str) -> None:
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Stockfish is not running.")

        self._process.stdin.write(f"{command}\n")
        self._process.stdin.flush()

    def _read_until(self, expected_line: str) -> None:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Stockfish is not running.")

        while True:
            line = self._process.stdout.readline()
            if not line:
                raise RuntimeError("Stockfish stopped before it became ready.")

            if line.strip() == expected_line:
                return

    def analyze(
        self,
        board: chess.Board,
        multipv: int,
        nodes: int,
    ) -> list[dict[str, Any]]:
        with self._lock:
            cache_key = (board.fen(), multipv, nodes)
            if cache_key in self._cache:
                analysis = self._cache.pop(cache_key)
                self._cache[cache_key] = analysis
                return analysis

            if self._process is None:
                self._start()

            if multipv != self._multipv:
                self._send(f"setoption name MultiPV value {multipv}")
                self._multipv = multipv
            self._send(f"position fen {board.fen()}")
            self._send(f"go nodes {nodes}")

            analysis = self._read_analysis()
            self._cache[cache_key] = analysis
            while len(self._cache) > 128:
                self._cache.popitem(last=False)
            return analysis

    def _read_analysis(self) -> list[dict[str, Any]]:
        if self._process is None or self._process.stdout is None:
            raise RuntimeError("Stockfish is not running.")

        lines_by_rank: dict[int, dict[str, Any]] = {}

        while True:
            line = self._process.stdout.readline().strip()
            if not line:
                raise RuntimeError("Stockfish stopped before returning an analysis.")

            if line.startswith("bestmove "):
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

            score_type = tokens[score_index + 1]
            score_value = int(tokens[score_index + 2])
            lines_by_rank[rank] = {
                "centipawns": score_value if score_type == "cp" else None,
                "mate_in": score_value if score_type == "mate" else None,
                "pv": [chess.Move.from_uci(move) for move in tokens[pv_index + 1 :]],
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


def get_evaluation(information: dict[str, Any]) -> Evaluation:
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


def get_position_summary(board: chess.Board) -> dict[str, Any]:
    outcome = board.outcome(claim_draw=True)

    return {
        "fen": board.fen(),
        "side_to_move": "white" if board.turn else "black",
        "legal_move_count": board.legal_moves.count(),
        "in_check": board.is_check(),
        "game_over": outcome is not None,
        "result": outcome.result() if outcome is not None else None,
        "termination": outcome.termination.name.lower()
        if outcome is not None
        else None,
    }


def get_position_analysis(
    board: chess.Board,
    multipv: int,
    nodes: int,
) -> dict[str, Any]:
    if board.is_game_over(claim_draw=True):
        return {**get_position_summary(board), "nodes": 0, "lines": []}

    analysis = stockfish.analyze(board, multipv, nodes)
    lines: list[dict[str, Any]] = []

    for rank, information in enumerate(analysis, start=1):
        principal_variation = information.get("pv", [])
        if not principal_variation:
            continue

        lines.append(
            {
                "rank": rank,
                "evaluation": asdict(get_evaluation(information)),
                "principal_variation": get_variation(board, principal_variation),
            }
        )

    return {**get_position_summary(board), "nodes": nodes, "lines": lines}


stockfish = StockfishClient()
atexit.register(stockfish.close)

mcp = GambitMCPServer(
    name="gambit",
    title="Gambit Chess Tutor",
    description="Analyze chess positions and provide move-by-move tutoring support.",
)


@mcp.tool(description="Inspect a FEN position without engine analysis.")
async def inspect_position(fen: str) -> dict[str, Any]:
    return get_position_summary(parse_board(fen))


@mcp.tool(description="List legal moves from a FEN position in SAN and UCI notation.")
async def list_legal_moves(fen: str) -> dict[str, Any]:
    board = parse_board(fen)
    return {
        **get_position_summary(board),
        "moves": [
            {"san": board.san(move), "uci": move.uci()} for move in board.legal_moves
        ],
    }


@mcp.tool(
    description=(
        "Analyze a FEN position with Stockfish. Evaluations are from the "
        "side-to-move perspective."
    )
)
async def analyze_position(
    fen: str,
    multipv: int = DEFAULT_MULTIPV,
    nodes: int = DEFAULT_NODES,
) -> dict[str, Any]:
    validate_multipv(multipv)
    validate_nodes(nodes)
    board = parse_board(fen)
    return get_position_analysis(board, multipv, nodes)


@mcp.tool(
    description=(
        "Convert an axis-aligned 2D chessboard screenshot or book diagram to FEN "
        "locally. Pass image as a local path, file URL, raw base64, or base64 data "
        "URL. Returns confidence and reliability; do not silently trust a result "
        "whose reliable or plausible field is false."
    )
)
async def recognize_chessboard(
    image: str,
    side_to_move: str = "white",
    orientation: Orientation = "auto",
    infer_castling_rights: bool = False,
) -> dict[str, object]:
    from gambit.ocr import recognize_chessboard_image

    return recognize_chessboard_image(
        image,
        side_to_move,
        orientation,
        infer_castling_rights,
    )


@mcp.tool(
    description=(
        "Recognize a chessboard image and analyze it with Stockfish in one fast "
        "call. Intended for axis-aligned screenshots and diagrams. Unreliable OCR "
        "is rejected by default so analysis is not based on a silently wrong board."
    )
)
async def analyze_chessboard(
    image: str,
    side_to_move: str = "white",
    orientation: Orientation = "auto",
    infer_castling_rights: bool = False,
    multipv: int = DEFAULT_MULTIPV,
    nodes: int = DEFAULT_NODES,
    allow_unreliable: bool = False,
) -> dict[str, Any]:
    from gambit.ocr import recognize_chessboard_image

    validate_multipv(multipv)
    validate_nodes(nodes)
    recognition = recognize_chessboard_image(
        image,
        side_to_move,
        orientation,
        infer_castling_rights,
    )
    if not allow_unreliable and (
        not recognition["reliable"] or not recognition["plausible"]
    ):
        raise ValueError(
            "chessboard OCR was not reliable enough to analyze automatically; "
            "inspect uncertain_squares or set allow_unreliable=true explicitly."
        )

    board = parse_board(str(recognition["fen"]))
    return {
        "recognition": recognition,
        "analysis": get_position_analysis(board, multipv, nodes),
    }


@mcp.tool(
    description=(
        "Assess a proposed legal SAN or UCI move. Returns the resulting position "
        "and Stockfish's best replies, for move-by-move tutoring."
    )
)
async def tutor_move(
    fen: str,
    move: str,
    multipv: int = DEFAULT_MULTIPV,
    nodes: int = DEFAULT_NODES,
) -> dict[str, Any]:
    validate_multipv(multipv)
    validate_nodes(nodes)
    board = parse_board(fen)
    candidate_move = parse_move(board, move)
    move_details = {"san": board.san(candidate_move), "uci": candidate_move.uci()}
    board.push(candidate_move)

    result: dict[str, Any] = {
        "move": move_details,
        "resulting_position": get_position_summary(board),
    }

    if board.is_game_over(claim_draw=True):
        result["best_replies"] = []
        return result

    analysis = stockfish.analyze(board, multipv, nodes)
    result["best_replies"] = [
        {
            "rank": rank,
            "evaluation": asdict(get_evaluation(information)),
            "principal_variation": get_variation(board, information.get("pv", [])),
        }
        for rank, information in enumerate(analysis, start=1)
        if information.get("pv")
    ]

    return result


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
