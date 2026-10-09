import argparse
import asyncio
import atexit
import json
import os
import sys
from dataclasses import asdict
from typing import Any, Literal

import chess
from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.stdio import stdio_server

from gambit.engine.analysis import EnginePool
from gambit.engine.client import (
    DEFAULT_MULTIPV,
    DEFAULT_NODES,
    execute_engine_request,
    get_evaluation,
    get_variation,
    parse_board,
    parse_move,
    validate_multipv,
    validate_nodes,
)
from gambit.game import service as games
from gambit.infrastructure.configuration import load_configuration
from gambit.server.tools import register_tools

Orientation = Literal[
    "auto",
    "white",
    "black",
]

class AsyncStdin:
    def __init__(self,) -> None:
        self.reader: asyncio.StreamReader | None = None
        self.transport: asyncio.ReadTransport | None = None

    def __aiter__(self,) -> AsyncStdin:
        return self

    async def __anext__(self,) -> str:
        if self.reader is None:
            self.reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(self.reader,)
            transport, _ = await asyncio.get_running_loop().connect_read_pipe(
                lambda: protocol,
                sys.stdin,
            )
            self.transport = transport

        line = await self.reader.readline()

        if not line:
            raise StopAsyncIteration

        return line.decode(
            "utf-8",
            errors="replace",
        )

class AsyncStdout:
    async def write(
        self,
        data: str,
    ) -> None:
        sys.stdout.write(data,)

    async def flush(self,) -> None:
        sys.stdout.flush()

class GambitMcpServer(MCPServer):
    async def run_stdio_async(self,) -> None:
        if sys.platform == "win32":
            await super().run_stdio_async()

            return

        async with stdio_server(
            stdin=AsyncStdin(),
            stdout=AsyncStdout(),
        ) as (read_stream, write_stream):
            await self._lowlevel_server.run(
                read_stream,
                write_stream,
                self._lowlevel_server.create_initialization_options(),
            )

def get_position_summary(board: chess.Board,) -> dict[
    str,
    Any,
]:
    outcome = board.outcome(claim_draw=True,)

    return {
        "fen": board.fen(),
        "side_to_move": "white" if board.turn else "black",
        "legal_move_count": board.legal_moves.count(),
        "in_check": board.is_check(),
        "game_over": outcome is not None,
        "result": outcome.result() if outcome is not None else None,
        "termination": outcome.termination.name.lower() if outcome is not None else None,
    }

def get_position_analysis(
    board: chess.Board,
    multipv: int,
    nodes: int,
) -> dict[
    str,
    Any,
]:
    if board.is_game_over(claim_draw=True,):
        return {**get_position_summary(board,), "nodes": 0, "lines": [],}

    analysis = stockfish.analyze(
        board,
        multipv,
        nodes,
    )
    lines: list[dict[
        str,
        Any,
    ]] = []

    for rank, information in enumerate(
        analysis,
        start=1,
    ):
        principal_variation = information.get(
            "pv",
            [],
        )

        if not principal_variation:
            continue

        lines.append({
            "rank": rank,
            "evaluation": asdict(get_evaluation(information,),),
            "principal_variation": get_variation(
                board,
                principal_variation,
            ),
        },)

    return {**get_position_summary(board,), "nodes": nodes, "lines": lines,}

stockfish = EnginePool(load_configuration(),)
atexit.register(stockfish.close,)

mcp = GambitMcpServer(
    name="gambit",
    title="Gambit Chess Tutor",
    description="Analyze chess positions and provide move-by-move tutoring support.",
)

@mcp.tool(description="Inspect a FEN position without engine analysis.",)
async def inspect_position(fen: str,) -> dict[
    str,
    Any,
]:
    return get_position_summary(parse_board(fen,),)

@mcp.tool(description="List legal moves from a FEN position in SAN and UCI notation.",)
async def list_legal_moves(fen: str,) -> dict[
    str,
    Any,
]:
    board = parse_board(fen,)

    return {
        **get_position_summary(board,),
        "moves": [{"san": board.san(move,), "uci": move.uci(),} for move in board.legal_moves],
    }

@mcp.tool(description=(
        "Analyze a FEN position with Stockfish. Evaluations are from the side-to-move perspective."
    ),)
async def analyze_position(
    fen: str,
    multipv: int = DEFAULT_MULTIPV,
    nodes: int = DEFAULT_NODES,
) -> dict[
    str,
    Any,
]:
    validate_multipv(multipv,)
    validate_nodes(nodes,)
    board = parse_board(fen,)

    return await execute_engine_request(
        get_position_analysis,
        board,
        multipv,
        nodes,
    )

@mcp.tool(description=(
        "Convert an axis-aligned 2D chessboard screenshot or book diagram to FEN "
        "locally. Pass image as a local path, file URL, raw base64, or base64 data "
        "URL. Returns confidence and reliability; do not silently trust a result "
        "whose reliable or plausible field is false."
    ),)
async def recognize_chessboard(
    image: str,
    side_to_move: str = "white",
    orientation: Orientation = "auto",
    infer_castling_rights: bool = False,
) -> dict[
    str,
    object,
]:
    from gambit.vision.recognizer import recognize_chessboard_image

    return await execute_engine_request(
        recognize_chessboard_image,
        image,
        side_to_move,
        orientation,
        infer_castling_rights,
    )

@mcp.tool(description=(
        "Recognize a chessboard image and analyze it with Stockfish in one fast "
        "call. Intended for axis-aligned screenshots and diagrams. Unreliable OCR "
        "is rejected by default so analysis is not based on a silently wrong board."
    ),)
async def analyze_chessboard(
    image: str,
    side_to_move: str = "white",
    orientation: Orientation = "auto",
    infer_castling_rights: bool = False,
    multipv: int = DEFAULT_MULTIPV,
    nodes: int = DEFAULT_NODES,
    allow_unreliable: bool = False,
) -> dict[
    str,
    Any,
]:
    from gambit.vision.recognizer import recognize_chessboard_image
    validate_multipv(multipv,)
    validate_nodes(nodes,)
    recognition = await execute_engine_request(
        recognize_chessboard_image,
        image,
        side_to_move,
        orientation,
        infer_castling_rights,
    )

    if not allow_unreliable and (not recognition["reliable"] or not recognition["plausible"]):
        raise ValueError("Chessboard OCR was not reliable enough to analyze automatically; "
            "inspect uncertain_squares or set allow_unreliable=true explicitly.",)

    board = parse_board(str(recognition["fen"],),)

    return {
        "recognition": recognition,
        "analysis": await execute_engine_request(
            get_position_analysis,
            board,
            multipv,
            nodes,
        ),
    }

@mcp.tool(description=(
        "Assess a proposed legal SAN or UCI move. Returns the resulting position "
        "and Stockfish's best replies, for move-by-move tutoring."
    ),)
async def tutor_move(
    fen: str,
    move: str,
    multipv: int = DEFAULT_MULTIPV,
    nodes: int = DEFAULT_NODES,
) -> dict[
    str,
    Any,
]:
    validate_multipv(multipv,)
    validate_nodes(nodes,)
    board = parse_board(fen,)
    candidate_move = parse_move(
        board,
        move,
    )
    move_details = {"san": board.san(candidate_move,), "uci": candidate_move.uci(),}
    board.push(candidate_move,)
    result: dict[
        str,
        Any,
    ] = {
        "move": move_details,
        "resulting_position": get_position_summary(board,),
    }

    if board.is_game_over(claim_draw=True,):
        result["best_replies"] = []

        return result

    analysis = await execute_engine_request(
        stockfish.analyze,
        board,
        multipv,
        nodes,
    )
    result["best_replies"] = [
        {
            "rank": rank,
            "evaluation": asdict(get_evaluation(information,),),
            "principal_variation": get_variation(
                board,
                information.get(
                    "pv",
                    [],
                ),
            ),
        }
        for rank, information in enumerate(
            analysis,
            start=1,
        )
        if information.get("pv",)
    ]

    return result

@mcp.tool(description="Parse one standard-chess PGN without Stockfish. Plies are one-based from the supplied starting position.",)
async def parse_game(pgn: str,) -> games.ParsedGame:
    try:
        return games.parse_game(pgn,)
    except ValueError as exception:
        raise ToolError(str(exception,),) from exception

@mcp.tool(description="Analyze a batch of FEN requests through one warm Stockfish process. All scores use White's perspective.",)
async def analyze_positions(positions: list[games.PositionAnalysisRequest],) -> tuple[
    games.PositionAnalysis,
    ...,
]:
    try:
        return await execute_engine_request(
            games.analyze_positions,
            positions,
            stockfish,
        )
    except (ValueError, TypeError, RuntimeError) as exception:
        raise ToolError(str(exception,),) from exception

@mcp.tool(description="Analyze a complete standard-chess PGN with adaptive Stockfish searches. Scores use White's perspective; nodes is the configured per-position budget.",)
async def analyze_game(
    pgn: str,
    side: games.AnalysisSide = "both",
    initial_nodes: int = 20_000,
    critical_nodes: int = 250_000,
    multipv: int = 3,
    critical_loss_cp: int = 40,
) -> games.GameAnalysis:
    try:
        return await execute_engine_request(
            games.analyze_game,
            pgn,
            stockfish,
            side,
            initial_nodes,
            critical_nodes,
            multipv,
            critical_loss_cp,
        )
    except (ValueError, TypeError, RuntimeError) as exception:
        raise ToolError(str(exception,),) from exception

@mcp.tool(description="Analyze and classify a complete PGN with deterministic Gambit review labels and per-player summaries. No prose coaching is generated.",)
async def review_game(
    pgn: str,
    side: games.AnalysisSide = "both",
    initial_nodes: int = 20_000,
    critical_nodes: int = 250_000,
    multipv: int = 3,
    critical_loss_cp: int = 40,
) -> games.GameReview:
    try:
        return await execute_engine_request(
            games.review_game,
            pgn,
            stockfish,
            side,
            initial_nodes,
            critical_nodes,
            multipv,
            critical_loss_cp,
        )
    except (ValueError, TypeError, RuntimeError) as exception:
        raise ToolError(str(exception,),) from exception

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Gambit chess tutoring MCP server.",)
    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve", "initialize"),
        default="serve",
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default="stdio",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get(
            "GAMBIT_HTTP_HOST",
            "127.0.0.1",
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get(
            "GAMBIT_HTTP_PORT",
            "3025",
        ),),
    )
    arguments = parser.parse_args()

    if arguments.command == "initialize":
        from gambit.infrastructure.corpus import load_bundled_openings
        from gambit.infrastructure.storage import Store

        configuration = load_configuration()
        store = Store(configuration.database_path,)

        try:
            print(json.dumps(
                load_bundled_openings(store,),
                indent=4,
            ),)
        finally:
            store.close()

        return

    if arguments.transport == "streamable-http":
        if arguments.host not in ("127.0.0.1", "::1", "localhost"):
            parser.error("The tunnel endpoint must bind to a loopback address.",)

        if not 1 <= arguments.port <= 65535:
            parser.error("The HTTP port must be between 1 and 65535.",)

        mcp.run(
            transport="streamable-http",
            host=arguments.host,
            port=arguments.port,
        )

        return

    mcp.run(transport="stdio",)

register_tools(
    mcp,
    stockfish,
)

if __name__ == "__main__":
    main()
