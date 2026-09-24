from __future__ import annotations

import asyncio
import base64
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import patch

import chess
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from gambit.main import mcp

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
ITALIAN_PLACEMENT = "r1bqk1nr/pppp1ppp/2n5/2b1p3/2B1P3/5N2/PPPP1PPP/RNBQK2R"
FIXTURES = Path(__file__).parent / "fixtures"

FAKE_STOCKFISH = """#!/usr/bin/env python3
import sys

moves = iter(("e7e5", "g1f3", "b8c6"))

for line in sys.stdin:
    command = line.strip()
    if command == "uci":
        print("uciok", flush=True)
    elif command == "isready":
        print("readyok", flush=True)
    elif command.startswith("go "):
        move = next(moves)
        print(f"info depth 1 multipv 1 score cp 0 pv {move}", flush=True)
        print(f"bestmove {move}", flush=True)
    elif command == "quit":
        break
"""


def create_fake_stockfish(directory: str) -> str:
    stockfish_path = os.path.join(directory, "stockfish")
    with open(stockfish_path, "w", encoding="utf-8") as stockfish_file:
        stockfish_file.write(FAKE_STOCKFISH)
    os.chmod(stockfish_path, 0o755)
    return stockfish_path


class PositionToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_server_handles_calls_over_stdio(self) -> None:
        server = StdioServerParameters(
            command=sys.executable,
            args=["-m", "gambit.main"],
        )

        async with (
            stdio_client(server) as (read_stream, write_stream),
            ClientSession(read_stream, write_stream) as session,
        ):
            await session.initialize()
            result = cast(
                CallToolResult,
                await session.call_tool("inspect_position", {"fen": STARTING_FEN}),
            )

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["legal_move_count"], 20)

    async def test_server_handles_successive_moves_over_stdio(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            server = StdioServerParameters(
                command=sys.executable,
                args=["-m", "gambit.main"],
                env={**os.environ, "STOCKFISH_PATH": create_fake_stockfish(directory)},
            )

            async with asyncio.timeout(5):
                async with (
                    stdio_client(server) as (read_stream, write_stream),
                    ClientSession(read_stream, write_stream) as session,
                ):
                    await session.initialize()
                    fen = STARTING_FEN

                    for move in ("e4", "e5", "Nf3"):
                        result = cast(
                            CallToolResult,
                            await session.call_tool(
                                "tutor_move",
                                {
                                    "fen": fen,
                                    "move": move,
                                    "multipv": 1,
                                    "nodes": 1,
                                },
                            ),
                        )
                        self.assertFalse(result.is_error, result.content)
                        fen = result.structured_content["resulting_position"]["fen"]

        self.assertEqual(
            fen,
            "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
        )

    async def test_inspect_position_can_be_called_through_mcp(self) -> None:
        result = cast(
            CallToolResult,
            await mcp.call_tool("inspect_position", {"fen": STARTING_FEN}),
        )

        self.assertFalse(result.is_error)
        self.assertEqual(result.structured_content["legal_move_count"], 20)

    async def test_list_legal_moves_can_be_called_through_mcp(self) -> None:
        result = cast(
            CallToolResult,
            await mcp.call_tool("list_legal_moves", {"fen": STARTING_FEN}),
        )

        self.assertFalse(result.is_error)
        moves = result.structured_content["moves"]
        self.assertEqual(len(moves), 20)
        self.assertIn({"san": "e4", "uci": "e2e4"}, moves)

    async def test_analyze_position_can_be_called_through_mcp(self) -> None:
        analysis = [
            {
                "centipawns": 25,
                "mate_in": None,
                "pv": [chess.Move.from_uci("e2e4")],
            }
        ]

        with patch("gambit.main.stockfish.analyze", return_value=analysis):
            result = cast(
                CallToolResult,
                await mcp.call_tool(
                    "analyze_position",
                    {"fen": STARTING_FEN, "multipv": 1, "nodes": 100},
                ),
            )

        self.assertFalse(result.is_error)
        self.assertEqual(
            result.structured_content["lines"][0]["evaluation"]["pawns"], 0.25
        )
        self.assertEqual(
            result.structured_content["lines"][0]["principal_variation"][0],
            {"san": "e4", "uci": "e2e4"},
        )

    async def test_tutor_move_can_be_called_through_mcp(self) -> None:
        analysis = [
            {
                "centipawns": -15,
                "mate_in": None,
                "pv": [chess.Move.from_uci("e7e5")],
            }
        ]

        with patch("gambit.main.stockfish.analyze", return_value=analysis):
            result = cast(
                CallToolResult,
                await mcp.call_tool(
                    "tutor_move",
                    {
                        "fen": STARTING_FEN,
                        "move": "e4",
                        "multipv": 1,
                        "nodes": 100,
                    },
                ),
            )

        self.assertFalse(result.is_error)
        self.assertEqual(
            result.structured_content["move"], {"san": "e4", "uci": "e2e4"}
        )
        self.assertEqual(
            result.structured_content["best_replies"][0]["principal_variation"][0],
            {"san": "e5", "uci": "e7e5"},
        )

    async def test_recognize_chessboard_can_be_called_through_mcp(self) -> None:
        image = base64.b64encode(
            (FIXTURES / "fen2image-italian.png").read_bytes()
        ).decode("ascii")

        result = cast(
            CallToolResult,
            await mcp.call_tool(
                "recognize_chessboard",
                {"image": image, "side_to_move": "black"},
            ),
        )

        self.assertFalse(result.is_error, result.content)
        self.assertEqual(
            result.structured_content["fen"],
            f"{ITALIAN_PLACEMENT} b - - 0 1",
        )
        self.assertTrue(result.structured_content["reliable"])
        self.assertTrue(result.structured_content["plausible"])
        self.assertGreater(result.structured_content["confidence"]["minimum"], 0.7)

    async def test_analyze_chessboard_combines_ocr_and_engine(self) -> None:
        analysis = [
            {
                "centipawns": 30,
                "mate_in": None,
                "pv": [chess.Move.from_uci("c4f7")],
            }
        ]

        with patch("gambit.main.stockfish.analyze", return_value=analysis):
            result = cast(
                CallToolResult,
                await mcp.call_tool(
                    "analyze_chessboard",
                    {
                        "image": str(FIXTURES / "fen2image-italian.png"),
                        "multipv": 1,
                        "nodes": 100,
                    },
                ),
            )

        self.assertFalse(result.is_error, result.content)
        self.assertEqual(
            result.structured_content["recognition"]["piece_placement"],
            ITALIAN_PLACEMENT,
        )
        self.assertEqual(
            result.structured_content["analysis"]["lines"][0]["principal_variation"][0],
            {"san": "Bxf7+", "uci": "c4f7"},
        )


if __name__ == "__main__":
    unittest.main()
