import argparse
import asyncio
import atexit
import json
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.stdio import stdio_server

from gambit.api.structured import wrap_structured_tool
from gambit.engine.analysis import EnginePool
from gambit.engine.client import execute_engine_request
from gambit.game import service
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

class GambitMcpServer(MCPServer,):
    def tool(
        self,
        *args,
        **kwargs,
    ):
        register = super().tool(
            *args,
            **kwargs,
        )

        def register_structured(function,):
            registered = register(wrap_structured_tool(function,),)
            name = kwargs.get('name',) or function.__name__
            tool = self._tool_manager.get_tool(name,)
            tool.parameters['additionalProperties'] = False

            return registered

        return register_structured

    async def call_tool(
        self,
        name,
        arguments,
        context=None,
    ):
        tool = self._tool_manager.get_tool(name,)

        if tool is not None:
            unexpected = set(arguments,) - set(tool.parameters.get(
                'properties',
                {},
            ),)

            if unexpected:
                raise ToolError('Unsupported arguments: ' + ', '.join(sorted(unexpected,),) + '.',)

        return await super().call_tool(
            name,
            arguments,
            context,
        )

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

stockfish = EnginePool(load_configuration(),)
atexit.register(stockfish.close,)

@asynccontextmanager
async def initialize_runtime(server: MCPServer,):
    await asyncio.to_thread(runtime_owner.get_runtime,)

    yield

mcp = GambitMcpServer(
    name="gambit",
    version="0.3.0",
    title="Gambit Chess Evidence",
    description="Validated chess facts, local analysis, and attributed API information.",
    instructions="Use get_evidence with only needed sections or get_position for exact rules. Engine scores are White-relative. Preserve history, evidence identity, and limitations. Request API data explicitly. Verify concrete claims; finite search is not proof. For the live UI use analyze_live_game at its current revision. No personal history is retained.",
    lifespan=initialize_runtime,
)

@mcp.tool(description="Read a 2D board image as a FEN position. Accepts a local path, file URL, base64, or data URL. Returns confidence and reliability. Verify uncertain squares before analysis; side to move and castling rights need explicit context.",)
async def read_board(
    image: str,
    side_to_move: str = "white",
    orientation: Orientation = "auto",
    infer_castling_rights: bool = False,
) -> dict:
    from gambit.vision.recognizer import recognize_chessboard_image

    return await execute_engine_request(
        recognize_chessboard_image,
        image,
        side_to_move,
        orientation,
        infer_castling_rights,
    )

@mcp.tool(description="Read one standard-chess PGN into validated positions, moves, headers, and comments. Does not run Stockfish. Plies are one-based from the starting position.",)
async def read_pgn(pgn: str,) -> service.ParsedGame:
    return service.parse_game(pgn,)

@mcp.tool(description="Analyze a standard-chess PGN with Stockfish. Includes deterministic move classifications and player summaries by default; set should_review=false for analysis only. Scores are White-relative; finite search is not proof.",)
async def analyze_game(
    pgn: str,
    side: service.AnalysisSide = "both",
    initial_nodes: int = 20_000,
    critical_nodes: int = 250_000,
    multipv: int = 3,
    critical_loss_cp: int = 40,
    should_review: bool = True,
) -> service.GameAnalysis | service.GameReview:
    operation = service.review_game if should_review else service.analyze_game

    return await execute_engine_request(
        operation,
        pgn,
        stockfish,
        side,
        initial_nodes,
        critical_nodes,
        multipv,
        critical_loss_cp,
    )

def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Gambit chess evidence MCP server.",)

    parser.add_argument(
        "command",
        nargs="?",
        choices=("serve", "initialize", "play", "cleanup", "update-openings"),
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

    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply runtime cleanup; preview is the default.",
    )

    parser.add_argument(
        "--revision",
        help="Pinned Git commit for the complete opening update.",
    )

    arguments = parser.parse_args()

    if arguments.command == "update-openings":
        if arguments.revision is None:
            parser.error("Opening updates require --revision with a full Git commit SHA.",)

        from gambit.knowledge.base import Knowledge
        from gambit.knowledge.update import update_openings

        print(json.dumps(
            update_openings(
                Knowledge(load_configuration().runtime_directory,),
                arguments.revision,
            ),
            indent=4,
        ),)

        return

    if arguments.command == "cleanup":
        from gambit.infrastructure.cleanup import clean_runtime

        print(json.dumps(
            clean_runtime(
                load_configuration().runtime_directory,
                arguments.apply,
            ),
            indent=4,
        ),)

        return

    if arguments.command == "initialize":
        from gambit.knowledge.base import Knowledge
        knowledge = Knowledge(load_configuration().runtime_directory,)
        knowledge.load()

        print(json.dumps(
            {"revision": knowledge.revision, "lines": len(knowledge.records,),},
            indent=4,
        ),)

        return

    if arguments.transport == "streamable-http" or arguments.command == "play":
        if arguments.host not in ("127.0.0.1", "::1", "localhost"):
            parser.error("The tunnel endpoint must bind to a loopback address.",)

        if not 1 <= arguments.port <= 65535:
            parser.error("The HTTP port must be between 1 and 65535.",)

        from gambit.server.http_server import serve_http

        serve_http(
            mcp,
            arguments.host,
            arguments.port,
            runtime_owner,
        )

        return

    mcp.run(transport="stdio",)

runtime_owner = register_tools(
    mcp,
    stockfish,
)

if __name__ == "__main__":
    main()
