import asyncio
import os
import shutil
import sys
import tempfile
import threading
import unittest
from collections import Counter
from dataclasses import replace
from pathlib import Path
from typing import cast
from unittest.mock import patch

import chess
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.types import CallToolResult

from gambit import games
from gambit.engine import EngineLine, StockfishClient
from gambit.main import mcp


class RecordingEngine(StockfishClient):
    """Deterministic search double with explicit White-relative root scores."""

    def __init__(self, scores: dict[int, int] | None = None) -> None:
        super().__init__()
        self.scores = scores or {}
        self.calls: list[tuple[str, int, int]] = []

    def analyze(self, board: chess.Board, multipv: int, nodes: int) -> list[EngineLine]:
        self.calls.append((board.fen(), nodes, multipv))
        score = self.scores.get(board.ply(), 0) * (1 if board.turn else -1)
        return [
            {"centipawns": score - rank, "mate_in": None, "pv": [move]}
            for rank, move in enumerate(list(board.legal_moves)[:multipv])
        ]


class GameParsingTests(unittest.TestCase):
    def test_bom_and_windows_line_endings(self) -> None:
        game = games.parse_game('\ufeff[Event "Test"]\r\n\r\n1.e4 e5 *')
        self.assertEqual(game.headers["Event"], "Test")
        self.assertEqual(len(game.moves), 2)

    def test_metadata_and_missing_optional_fields(self) -> None:
        game = games.parse_game(
            '[Event "Test"]\n\n1. e4 $1 {hi [%clk 0:04:58.5] [%emt 0:00:01.2]} e5 2.Nf3'
        )
        self.assertEqual(game.headers, {"Event": "Test"})
        self.assertIsNone(game.result)
        self.assertEqual([move.ply for move in game.moves], [1, 2, 3])
        self.assertEqual([move.move_number for move in game.moves], [1, 1, 2])
        self.assertEqual(game.moves[0].clock_seconds, 298.5)
        self.assertEqual(game.moves[0].elapsed_move_seconds, 1.2)
        self.assertEqual(game.moves[0].numeric_annotation_glyphs, (1,))
        self.assertIsNone(game.moves[1].clock_seconds)
        self.assertEqual(game.moves[0].fen_after, game.moves[1].fen_before)

    def test_custom_black_start_and_promotion(self) -> None:
        game = games.parse_game(
            '[SetUp "1"]\n[FEN "7k/8/8/8/8/8/p6K/8 b - - 0 42"]\n\n42...a1=Q'
        )
        move = game.moves[0]
        self.assertEqual((move.ply, move.move_number, move.side), (1, 42, "black"))
        self.assertEqual(move.uci, "a2a1q")

    def test_castling_and_en_passant(self) -> None:
        game = games.parse_game("1.e4 e5 2.Nf3 Nc6 3.Bc4 Bc5 4.O-O *")
        self.assertEqual(game.moves[-1].uci, "e1g1")
        game = games.parse_game("1.e4 a6 2.e5 d5 3.exd6 *")
        board = chess.Board(game.moves[-1].fen_after)
        self.assertIsNone(board.piece_at(chess.D5))
        self.assertEqual(board.piece_at(chess.D6), chess.Piece(chess.PAWN, chess.WHITE))

    def test_results_and_variations(self) -> None:
        for result in ("1-0", "0-1", "1/2-1/2", "*"):
            with self.subTest(result=result):
                self.assertEqual(
                    games.parse_game(f"1.e4 (1.d4 d5) e5 {result}").result, result
                )
        game = games.parse_game("1.f3 e5 2.g4 Qh4# 0-1")
        self.assertTrue(chess.Board(game.moves[-1].fen_after).is_checkmate())

    def test_stalemate(self) -> None:
        game = games.parse_game(
            '[FEN "7k/5K2/8/6Q1/8/8/8/8 w - - 0 1"]\n\n1.Qg6 1/2-1/2'
        )
        self.assertTrue(chess.Board(game.moves[-1].fen_after).is_stalemate())

    def test_header_only_game_is_inspectable(self) -> None:
        game = games.parse_game('[Event "Unplayed"]\n\n*')
        self.assertEqual(game.moves, ())
        with self.assertRaisesRegex(ValueError, "at least one"):
            games.analyze_game('[Event "Unplayed"]', RecordingEngine())

    def test_invalid_pgn_is_never_returned_as_partial(self) -> None:
        invalid = (
            "",
            "nonsense",
            "1.e4 e5 2.Bh6",
            "1.e4 garbage",
            "1.e4 {unclosed",
            "1.e4 (1.d4",
            "1.e4 )",
            "[Event broken]\n1.e4",
            '[SetUp "1"]\n\n1.e4',
            '[FEN "invalid"]\n\n*',
            '[FEN "8/8/8/8/8/8/8/8 w - - 0 1"]\n\n*',
            "1.e4 * 1...e5",
            "1.e4 1-0\n\n1.d4 0-1",
            "1.--",
            '[Result "1-0"]\n\n1.e4 0-1',
            '1.e4 [Event "Wrong place"] e5',
        )
        for pgn in invalid:
            with self.subTest(pgn=pgn), self.assertRaises(ValueError):
                games.parse_game(pgn)
        with self.assertRaisesRegex(ValueError, "Bh6.*move 2, ply 3"):
            games.parse_game("1.e4 e5 2.Bh6")

    def test_variants_rejected(self) -> None:
        for variant in ("Chess960", "Crazyhouse", "Atomic", "Horde", "Three-check"):
            with (
                self.subTest(variant=variant),
                self.assertRaisesRegex(ValueError, "standard chess"),
            ):
                games.parse_game(f'[Variant "{variant}"]\n\n*')

    def test_limits(self) -> None:
        with patch.object(games, "MAX_PGN_BYTES", 3), self.assertRaises(ValueError):
            games.parse_game("1.e4")
        with patch.object(games, "MAX_GAME_PLIES", 1), self.assertRaises(ValueError):
            games.parse_game("1.e4 e5")


class GameAnalysisTests(unittest.TestCase):
    def test_batch_cache_distinguishes_configuration(self) -> None:
        engine = RecordingEngine()
        games.analyze_positions(
            [
                games.PositionAnalysisRequest(chess.STARTING_FEN, 100, 1),
                games.PositionAnalysisRequest(chess.STARTING_FEN, 200, 1),
                games.PositionAnalysisRequest(chess.STARTING_FEN, 100, 2),
                games.PositionAnalysisRequest(chess.STARTING_FEN, 100, 1),
            ],
            engine,
        )
        self.assertEqual(len(engine.calls), 3)

    def test_white_relative_evaluation_and_loss(self) -> None:
        self.assertEqual(
            games.normalize_evaluation(80, None, chess.BLACK).centipawns, -80
        )
        self.assertEqual(games.normalize_evaluation(None, 4, chess.BLACK).mate_in, -4)
        self.assertEqual(games.normalize_evaluation(None, -3, chess.BLACK).mate_in, 3)
        for side, before, after, expected in (
            ("white", 80, 20, 60),
            ("black", -80, -20, 60),
            ("black", -20, 100, 120),
            ("white", 20, 80, 0),
            ("black", 100, 0, 0),
        ):
            with self.subTest(side=side, before=before, after=after):
                self.assertEqual(
                    games.calculate_centipawn_loss(
                        games.EngineEvaluation(before, None),
                        games.EngineEvaluation(after, None),
                        side,
                    ),
                    expected,
                )
        self.assertIsNone(
            games.calculate_centipawn_loss(
                games.EngineEvaluation(0, None),
                games.EngineEvaluation(None, -2, "black"),
                "white",
            )
        )

    def test_batch_order_validation_cache_and_terminal_positions(self) -> None:
        engine = RecordingEngine({1: 80})
        after = games.parse_game("1.e4").moves[0].fen_after
        requests = [
            games.PositionAnalysisRequest(fen, 100, 2)
            for fen in (after, chess.STARTING_FEN, after)
        ]
        results = games.analyze_positions(requests, engine)
        self.assertEqual(
            [result.fen for result in results], [request.fen for request in requests]
        )
        self.assertEqual(results[0].evaluation.centipawns, 80)
        self.assertEqual(len(engine.calls), 2)
        engine.calls.clear()
        with self.assertRaisesRegex(ValueError, "request 2"):
            games.analyze_positions(
                [requests[0], games.PositionAnalysisRequest("bad")], engine
            )
        self.assertEqual(engine.calls, [])
        for fen, mate in (
            ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", 0),
            ("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1", None),
            ("7k/8/5K2/8/8/8/8/8 b - - 0 1", None),
        ):
            result = games.analyze_positions(
                [games.PositionAnalysisRequest(fen)], engine
            )[0]
            self.assertEqual(result.evaluation.mate_in, mate)
            self.assertEqual(result.principal_variations, ())
            if mate == 0:
                self.assertEqual(result.evaluation.mating_side, "white")
        self.assertEqual(engine.calls, [])

    def test_sequential_san_and_invalid_pv_prefix(self) -> None:
        engine = RecordingEngine()
        line: EngineLine = {
            "centipawns": 10,
            "mate_in": None,
            "pv": [
                chess.Move.from_uci(move) for move in ("e2e4", "e7e5", "g1f3", "e7e6")
            ],
        }
        with patch.object(engine, "analyze", return_value=[line]):
            result = games.analyze_positions(
                [games.PositionAnalysisRequest(chess.STARTING_FEN)], engine
            )[0]
        self.assertEqual(result.principal_variations[0].moves_san, ("e4", "e5", "Nf3"))
        with (
            patch.object(
                engine,
                "analyze",
                return_value=[{**line, "pv": [chess.Move.from_uci("e7e5")]}],
            ),
            self.assertRaisesRegex(RuntimeError, "invalid root"),
        ):
            games.analyze_positions(
                [games.PositionAnalysisRequest(chess.STARTING_FEN)], engine
            )
        with (
            patch.object(engine, "analyze", return_value=[]),
            self.assertRaisesRegex(RuntimeError, "no variations"),
        ):
            games.analyze_positions(
                [games.PositionAnalysisRequest(chess.STARTING_FEN)], engine
            )

    def test_two_pass_reuse_and_side_filtering(self) -> None:
        engine = RecordingEngine({0: 80, 1: 20, 2: 20, 3: 20, 4: 20})
        result = games.analyze_game(
            "1.e4 e5 2.Nf3 Nc6", engine, initial_nodes=100, critical_nodes=1000
        )
        self.assertEqual(len(engine.calls), 7)  # Five cheap roots, two deep roots.
        self.assertEqual(
            [nodes for _, nodes, _ in engine.calls], [100] * 5 + [1000] * 2
        )
        self.assertEqual(len(set(engine.calls)), len(engine.calls))
        self.assertEqual(
            [move.was_reanalyzed for move in result.moves], [True, False, False, False]
        )
        self.assertEqual(result.moves[0].centipawn_loss, 60)
        engine.calls.clear()
        result = games.analyze_game(
            "1.e4 e5 2.Nf3 Nc6",
            engine,
            side="black",
            initial_nodes=100,
            critical_nodes=1000,
        )
        self.assertEqual([move.ply for move in result.moves], [2, 4])
        self.assertEqual(len(engine.calls), 4)
        self.assertEqual(result.initial_fen, chess.STARTING_FEN)

    def test_deeper_scores_are_authoritative(self) -> None:
        engine = RecordingEngine()

        def analyze(board: chess.Board, multipv: int, nodes: int) -> list[EngineLine]:
            score = (80 if board.ply() == 0 else 0) if nodes == 100 else 10
            return [
                {
                    "centipawns": score * (1 if board.turn else -1),
                    "mate_in": None,
                    "pv": [next(iter(board.legal_moves))],
                }
            ]

        with patch.object(engine, "analyze", side_effect=analyze):
            result = games.analyze_game(
                "1.e4", engine, initial_nodes=100, critical_nodes=1000
            )
        self.assertEqual(result.moves[0].centipawn_loss, 0)
        self.assertTrue(result.moves[0].was_reanalyzed)
        self.assertEqual(result.moves[0].nodes, 1000)

    def test_adjacent_critical_moves_share_deep_search(self) -> None:
        engine = RecordingEngine()
        result = games.analyze_game(
            "1.e4 e5",
            engine,
            initial_nodes=100,
            critical_nodes=1000,
            critical_loss_cp=0,
        )
        self.assertEqual(len(engine.calls), 6)
        self.assertTrue(all(move.was_reanalyzed for move in result.moves))
        engine.calls.clear()
        result = games.analyze_game(
            "1.e4 e5", engine, initial_nodes=100, critical_nodes=100, critical_loss_cp=0
        )
        self.assertEqual(len(engine.calls), 3)
        self.assertTrue(
            all(not move.was_reanalyzed and move.is_critical for move in result.moves)
        )

    def test_ranking(self) -> None:
        game = games.analyze_game(
            "1.Nh3", RecordingEngine(), initial_nodes=1, critical_nodes=1
        )
        self.assertEqual(game.moves[0].played_move_rank, 1)
        game = games.analyze_game(
            "1.Nf3", RecordingEngine(), initial_nodes=1, critical_nodes=1
        )
        self.assertEqual(game.moves[0].played_move_rank, 2)
        game = games.analyze_game(
            "1.e4", RecordingEngine(), initial_nodes=1, critical_nodes=1
        )
        self.assertIsNone(game.moves[0].played_move_rank)

    def test_request_validation(self) -> None:
        options = (
            {"initial_nodes": 0},
            {"critical_nodes": 1},
            {"multipv": 0},
            {"multipv": 6},
            {"initial_nodes": 2_000_001},
            {"critical_loss_cp": -1},
            {"side": "invalid"},
            {"initial_nodes": True},
            {"critical_loss_cp": True},
        )
        for option in options:
            with (
                self.subTest(option=option),
                self.assertRaises((ValueError, TypeError)),
            ):
                games.analyze_game("1.e4", RecordingEngine(), **option)
        for requests in ([], [games.PositionAnalysisRequest(chess.STARTING_FEN)] * 129):
            with self.assertRaises(ValueError):
                games.analyze_positions(requests, RecordingEngine())

    def test_critical_mate_and_advantage_transitions(self) -> None:
        cp = games.EngineEvaluation
        for before, after in (
            (cp(0, None), cp(None, -3, "black")),
            (cp(None, 3, "white"), cp(0, None)),
            (cp(None, 3, "white"), cp(None, 7, "white")),
            (cp(-250, None), cp(250, None)),
            (cp(250, None), cp(0, None)),
        ):
            self.assertTrue(games.is_critical_move(before, after, "white", 1000))
        self.assertFalse(
            games.is_critical_move(
                cp(None, 3, "white"), cp(None, 2, "white"), "white", 40
            )
        )


class GameReviewTests(unittest.TestCase):
    def test_only_legal_move_is_forced(self) -> None:
        review = games.review_game(
            '[FEN "8/8/8/8/8/1k6/r7/K7 w - - 0 1"]\n\n1.Kb1',
            RecordingEngine(),
            initial_nodes=1,
            critical_nodes=1,
        )
        move = review.moves[0]
        self.assertTrue(move.is_forced)
        self.assertTrue(move.features_before.is_check)
        self.assertEqual(move.legal_move_count, 1)
        self.assertEqual(move.classification, "forced")
        self.assertEqual(review.summaries[0].forced_moves, 1)

    def test_classification_boundaries_and_best_identity(self) -> None:
        move = games.analyze_game(
            "1.e4", RecordingEngine(), initial_nodes=1, critical_nodes=1
        ).moves[0]
        for loss, classification in (
            (0, "excellent"),
            (1, "excellent"),
            (20, "excellent"),
            (21, "good"),
            (50, "good"),
            (51, "inaccuracy"),
            (100, "inaccuracy"),
            (101, "mistake"),
            (200, "mistake"),
            (201, "blunder"),
        ):
            with self.subTest(loss=loss):
                self.assertEqual(
                    games.classify_move(replace(move, centipawn_loss=loss), 20),
                    classification,
                )
        self.assertEqual(
            games.classify_move(replace(move, best_move_uci=move.uci), 20), "best"
        )
        self.assertEqual(games.classify_move(move, 1), "forced")

    def test_mate_classification_and_summary_exclusion(self) -> None:
        review = games.review_game(
            "1.e4 e5", RecordingEngine(), initial_nodes=1, critical_nodes=1
        )
        move = review.moves[0].analysis
        lost_mate = replace(
            move,
            evaluation_before=games.EngineEvaluation(None, 3, "white"),
            evaluation_after=games.EngineEvaluation(300, None),
            centipawn_loss=None,
        )
        self.assertEqual(games.classify_move(lost_mate, 20), "blunder")
        allows_mate = replace(
            move,
            evaluation_after=games.EngineEvaluation(None, -2, "black"),
            centipawn_loss=None,
        )
        self.assertEqual(games.classify_move(allows_mate, 20), "blunder")
        mate_review = replace(
            review.moves[0], analysis=lost_mate, classification="blunder"
        )
        summary = games.summarize_player("white", [mate_review])
        self.assertEqual(summary.blunders, 1)
        self.assertIsNone(summary.average_centipawn_loss)
        self.assertIsNone(summary.largest_loss_ply)

    def test_review_analyzes_once_and_filters_summaries(self) -> None:
        engine = RecordingEngine({0: 80, 1: 20, 2: 20, 3: -60})
        review = games.review_game(
            "1.e4 e5 2.Nf3", engine, side="white", initial_nodes=10, critical_nodes=10
        )
        self.assertEqual(len(engine.calls), 4)
        self.assertEqual(len(review.summaries), 1)
        summary = review.summaries[0]
        self.assertEqual(summary.side, "white")
        self.assertEqual(summary.move_count, 2)
        self.assertEqual(summary.average_centipawn_loss, 70)
        self.assertEqual(summary.median_centipawn_loss, 70)
        self.assertEqual(summary.largest_centipawn_loss, 80)
        self.assertEqual(summary.largest_loss_ply, 3)
        self.assertEqual(summary.critical_plies, (1, 3))
        self.assertEqual(review.moves[0].features_before.legal_move_count, 20)


class GameToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_new_tools_serialize_through_mcp(self) -> None:
        engine = RecordingEngine()
        with patch("gambit.main.stockfish", engine):
            for name, arguments in (
                ("parse_game", {"pgn": "1.e4 e5"}),
                (
                    "analyze_game",
                    {"pgn": "1.e4 e5", "initial_nodes": 10, "critical_nodes": 10},
                ),
                (
                    "review_game",
                    {"pgn": "1.e4 e5", "initial_nodes": 10, "critical_nodes": 10},
                ),
                (
                    "analyze_positions",
                    {"positions": [{"fen": chess.STARTING_FEN, "nodes": 10}]},
                ),
            ):
                with self.subTest(tool=name):
                    result = cast(CallToolResult, await mcp.call_tool(name, arguments))
                    self.assertFalse(result.is_error)
                    self.assertIsNotNone(result.structured_content)

    async def test_game_over_stdio_with_real_engine(self) -> None:
        if shutil.which("stockfish") is None:
            self.skipTest("Stockfish is not installed")
        server = StdioServerParameters(
            command=sys.executable, args=["-m", "gambit.main"]
        )
        async with asyncio.timeout(15):
            async with (
                stdio_client(server) as (read_stream, write_stream),
                ClientSession(read_stream, write_stream) as session,
            ):
                await session.initialize()
                tools = await session.list_tools()
                self.assertTrue(
                    {"parse_game", "analyze_positions", "analyze_game", "review_game"}
                    <= {tool.name for tool in tools.tools}
                )
                result = cast(
                    CallToolResult,
                    await session.call_tool(
                        "review_game",
                        {
                            "pgn": "1.f3 e5 2.g4 Qh4# 0-1",
                            "initial_nodes": 1000,
                            "critical_nodes": 2000,
                            "multipv": 2,
                        },
                    ),
                )
                self.assertFalse(result.is_error, result.content)
                self.assertEqual(
                    result.structured_content["moves"][-1]["analysis"][
                        "evaluation_after"
                    ]["mating_side"],
                    "black",
                )
                self.assertTrue(
                    result.structured_content["moves"][-1]["features_after"][
                        "is_checkmate"
                    ]
                )
                result = cast(
                    CallToolResult,
                    await session.call_tool("parse_game", {"pgn": "1.e4 garbage"}),
                )
                self.assertTrue(result.is_error)
                self.assertIn("Malformed PGN", str(result.content))


class StockfishLifecycleTests(unittest.TestCase):
    def test_invalid_uci_continuation_and_bestmove(self) -> None:
        engine = StockfishClient()
        engine.output.put("info depth 1 multipv 1 score cp 10 pv e2e4 e7e5 invalid")
        engine.output.put("bestmove e2e4")
        lines = engine.read_analysis(chess.Board())
        self.assertEqual([move.uci() for move in lines[0]["pv"]], ["e2e4", "e7e5"])
        engine.output.put("bestmove e7e5")
        with self.assertRaisesRegex(RuntimeError, "invalid best move"):
            engine.read_analysis(chess.Board())

    def test_timeout_crash_and_recovery(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / "engine"
            executable.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(10)\n")
            executable.chmod(0o755)
            engine = StockfishClient()
            with (
                patch.dict(os.environ, {"STOCKFISH_PATH": str(executable)}),
                patch("gambit.engine.ENGINE_RESPONSE_TIMEOUT_SECONDS", 0.1),
                self.assertRaisesRegex(RuntimeError, "timed out"),
            ):
                engine.analyze(chess.Board(), 1, 100)
            self.assertIsNone(engine.process)
            executable.write_text(f"#!{sys.executable}\n")
            with (
                patch.dict(os.environ, {"STOCKFISH_PATH": str(executable)}),
                self.assertRaisesRegex(RuntimeError, "stopped"),
            ):
                engine.analyze(chess.Board(), 1, 100)
            self.assertIsNone(engine.process)
            if shutil.which("stockfish"):
                try:
                    self.assertTrue(engine.analyze(chess.Board(), 1, 100))
                finally:
                    engine.close()

    def test_warm_process_and_serialized_concurrent_access(self) -> None:
        if shutil.which("stockfish") is None:
            self.skipTest("Stockfish is not installed")
        engine = StockfishClient()
        try:
            engine.analyze(chess.Board(), 1, 100)
            process = engine.process
            errors: list[Exception] = []

            def analyze(fen: str) -> None:
                try:
                    games.analyze_positions(
                        [games.PositionAnalysisRequest(fen, 200, 2)], engine
                    )
                except (RuntimeError, ValueError) as exception:
                    errors.append(exception)

            fens = [
                move.fen_after for move in games.parse_game("1.e4 e5 2.Nf3 Nc6").moves
            ]
            threads = [threading.Thread(target=analyze, args=(fen,)) for fen in fens]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join(timeout=5)
            self.assertFalse(any(thread.is_alive() for thread in threads))
            self.assertEqual(errors, [])
            self.assertIs(engine.process, process)
            self.assertEqual(Counter(key[2] for key in engine.cache), {100: 1, 200: 4})
        finally:
            engine.close()


if __name__ == "__main__":
    unittest.main()
