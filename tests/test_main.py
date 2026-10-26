from __future__ import annotations

import base64
import os
import sys
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import chess
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from gambit.main import mcp, runtime_owner
from gambit.server.tools import Runtime

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
ITALIAN_PLACEMENT = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R"
FIXTURES = Path(__file__,).parent / "fixtures"

FAKE_STOCKFISH = """#!/usr/bin/env python3
import sys

moves = iter(("e7e5", "g1f3", "b8c6"),)

for line in sys.stdin:
    command = line.strip()

    if command == "uci":
        print(
            "uciok",
            flush=True,
        )
    elif command == "isready":
        print(
            "readyok",
            flush=True,
        )
    elif command.startswith("go ",):
        move = next(moves,)
        print(
            f"info depth 1 multipv 1 score cp 0 pv {move}",
            flush=True,
        )
        print(
            f"bestmove {move}",
            flush=True,
        )
    elif command == "quit":
        break
"""

def create_fake_stockfish(directory: str,) -> str:
    stockfish_path = os.path.join(
        directory,
        "stockfish",
    )

    with open(
        stockfish_path,
        "w",
        encoding="utf-8",
    ) as stockfish_file:
        stockfish_file.write(FAKE_STOCKFISH,)

    os.chmod(
        stockfish_path,
        0o755,
    )

    return stockfish_path

class PositionToolTests(unittest.IsolatedAsyncioTestCase,):
    def setUp(self,) -> None:
        self.runtime = Runtime()
        self.addCleanup(self.runtime.close,)

        runtime_patch = patch.object(
            runtime_owner,
            'get_runtime',
            return_value=self.runtime,
        )

        runtime_patch.start()
        self.addCleanup(runtime_patch.stop,)

    async def test_server_handles_calls_over_stdio(self,) -> None:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "gambit.main",],
        )

        async with (
            stdio_client(server,) as (read_stream, write_stream),
            ClientSession(
                read_stream,
                write_stream,
            ) as session,
        ):
            await session.initialize()

            result = cast(
                CallToolResult,
                await session.call_tool(
                    "get_position",
                    {"fen": STARTING_FEN,},
                ),
            )

        self.assertFalse(result.is_error,)

        self.assertEqual(
            result.structured_content["legal_move_count"],
            20,
        )

    async def test_get_position_returns_state(self,) -> None:
        result = cast(
            CallToolResult,
            await mcp.call_tool(
                "get_position",
                {"fen": STARTING_FEN,},
            ),
        )

        self.assertFalse(result.is_error,)

        self.assertEqual(
            result.structured_content["legal_move_count"],
            20,
        )

    async def test_get_position_returns_legal_moves(self,) -> None:
        result = cast(
            CallToolResult,
            await mcp.call_tool(
                "get_position",
                {"fen": STARTING_FEN,},
            ),
        )

        self.assertFalse(result.is_error,)
        moves = result.structured_content["moves"]

        self.assertEqual(
            len(moves,),
            20,
        )

        self.assertIn(
            {"san": "e4", "uci": "e2e4",},
            moves,
        )

    async def test_analyze_position_can_be_called_through_mcp(self,) -> None:
        analysis = [
            {
                "centipawns": 25,
                "mate_in": None,
                "pv": [chess.Move.from_uci("e2e4",),],
            },
        ]

        with patch.object(
            self.runtime.analysis.engine,
            "analyze",
            return_value=analysis,
        ):
            result = cast(
                CallToolResult,
                await mcp.call_tool(
                    "analyze_position",
                    {"fen": STARTING_FEN, "profile": "instant",},
                ),
            )

        self.assertFalse(result.is_error,)

        self.assertEqual(
            result.structured_content["evaluation"]["centipawns"],
            25,
        )

        self.assertEqual(
            result.structured_content["principal_variations"][0]["moves_san"][0],
            "e4",
        )

    async def test_read_board_can_be_called_through_mcp(self,) -> None:
        image = base64.b64encode((FIXTURES / "fen2image-italian.png").read_bytes(),).decode("ascii",)

        result = cast(
            CallToolResult,
            await mcp.call_tool(
                "read_board",
                {"image": image, "side_to_move": "black",},
            ),
        )

        self.assertFalse(
            result.is_error,
            result.content,
        )

        self.assertEqual(
            result.structured_content["fen"],
            f"{ITALIAN_PLACEMENT} b - - 0 1",
        )

        self.assertTrue(result.structured_content["reliable"],)
        self.assertTrue(result.structured_content["plausible"],)

        self.assertGreater(
            result.structured_content["confidence"]["minimum"],
            0.7,
        )

    async def test_read_board_position_can_be_analyzed(self,) -> None:
        recognized = await mcp.call_tool(
            "read_board",
            {"image": str(FIXTURES / "fen2image-italian.png",),},
        )

        self.assertFalse(recognized.is_error,)
        position = recognized.structured_content
        self.assertTrue(position["reliable"],)
        self.assertTrue(position["plausible"],)

        analysis = [{"centipawns": 30, "mate_in": None, "pv": [chess.Move.from_uci("c4f7",),],},]

        with patch.object(
            self.runtime.analysis.engine,
            "analyze",
            return_value=analysis,
        ):
            result = await mcp.call_tool(
                "analyze_position",
                {"fen": position["fen"],},
            )

        self.assertFalse(result.is_error,)

        self.assertEqual(
            result.structured_content["position_reference"]["fen"],
            position["fen"],
        )

        self.assertEqual(
            result.structured_content["principal_variations"][0]["moves_san"][0],
            "Bxf7+",
        )

if __name__ == "__main__":
    unittest.main()
