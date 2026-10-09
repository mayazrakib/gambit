import asyncio

import chess
import pytest

from gambit.engine.analysis import AnalysisService
from gambit.game.features import inspect_features
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge, probe_tablebase
from gambit.learning.speech import create_speech_plan
from gambit.learning.training import Training
from gambit.learning.tutoring import Tutor

@pytest.fixture
def store():
    database = Store(":memory:",)

    try:
        yield database
    finally:
        database.close()

def test_persistent_records_are_immutable(tmp_path,):
    path = str(tmp_path / "state.sqlite3",)
    database = Store(path,)
    database.put(
        "analysis",
        "one",
        {"score": 15,},
        is_immutable=True,
    )
    database.close()
    database = Store(path,)

    try:
        assert database.get(
            "analysis",
            "one",
        ) == {"score": 15,}

        with pytest.raises(
            ValueError,
            match="immutable",
        ):
            database.put(
                "analysis",
                "one",
                {"score": 30,},
                is_immutable=True,
            )
    finally:
        database.close()

def test_study_keeps_variations_and_rejects_partial_imports(store,):
    knowledge = Knowledge(store,)
    report = knowledge.import_study(
        "1. e4 (1. d4 d5) e5 *",
        "Candidates",
        "authored test",
    )
    records = knowledge.find_moves(chess.STARTING_FEN,)["moves"]
    assert report["imported_edges"] == 4
    assert {record["move_uci"] for record in records} == {"e2e4", "d2d4",}

    with pytest.raises(ValueError,):
        knowledge.import_study(
            "1. e4 e5 2. Bh6",
            "Bad",
            "test",
        )

    assert store.count_records("opening",) == 4

def test_transpositions_ignore_counters_but_preserve_castling(store,):
    knowledge = Knowledge(store,)
    knowledge.import_study(
        "1. Nf3 d5 2. d4 Nf6 *",
        "Transposition",
        "test",
    )
    board = chess.Board()

    for move in ("d4", "d5", "Nf3"):
        board.push_san(move,)

    assert knowledge.find_moves(board.fen(),)["moves"][0]["move_uci"] == "g8f6"

def test_puzzle_setup_hidden_solution_and_spaced_repetition(store,):
    training = Training(store,)
    board = chess.Board()
    board.push_san("f3",)
    board.push_san("e5",)
    csv_text = "PuzzleId,FEN,Moves,Rating,Themes\n" + f"fools,{board.fen()},g2g4 d8h4,800,mateIn1\n"
    training.import_puzzles(
        csv_text,
        "authored test",
    )
    puzzle = training.get_tactic("student",)
    assert "solution" not in puzzle
    assert chess.Board(puzzle["fen"],).turn == chess.BLACK
    incorrect = training.submit_tactic_move(
        puzzle["session_id"],
        "Nc6",
    )
    assert not incorrect["is_correct"]
    completed = training.submit_tactic_move(
        puzzle["session_id"],
        "Qh4#",
    )
    assert completed["status"] == "completed"
    progress = store.get(
        "attempt",
        "student:fools",
    )
    assert not progress["was_successful"]
    assert training.get_tactic("student",)["status"] == "unavailable"

    with pytest.raises(
        ValueError,
        match="not active",
    ):
        training.submit_tactic_move(
            puzzle["session_id"],
            "Qh4#",
        )

def test_attempt_identity_is_idempotent(store,):
    training = Training(store,)
    first = training.record_attempt(
        "student",
        "puzzle",
        True,
        "attempt",
    )
    repeated = training.record_attempt(
        "student",
        "puzzle",
        True,
        "attempt",
    )
    assert first == repeated

def test_pronunciation_handles_capture_promotion_and_castling():
    promotion = create_speech_plan(
        "7k/P7/6K1/8/8/8/8/8 w - - 0 1",
        [],
        ["a8=Q#",],
    )
    assert "promoting to queen" in promotion["pronunciations"][0]["spoken"]
    castling = create_speech_plan(
        "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
        [],
        ["O-O",],
    )
    assert castling["pronunciations"][0]["spoken"] == "Castle kingside."

def test_features_and_unavailable_tablebase_are_explicit():
    features = inspect_features(chess.STARTING_FEN,)
    assert features["sides"]["white"]["material_points"] == 39
    assert features["sides"]["white"]["isolated_pawns"] == []
    assert probe_tablebase(
        chess.STARTING_FEN,
        "",
    )["status"] == "unavailable"

def test_lessons_and_preferences_persist(store,):
    training = Training(store,)
    profile = training.update_profile(
        "student",
        1600,
        "direct",
        "detailed",
    )
    assert profile["rating"] == 1600
    lesson = training.start_lesson(
        "student",
        "middlegames",
    )

    for index in range(len(lesson["steps"],),):
        lesson = training.advance_lesson(
            lesson["id"],
            index,
        )

    assert lesson["is_complete"]

def test_configuration_rejects_invalid_budgets():
    with pytest.raises(ValueError,):
        Configuration(worker_count=0,)

    with pytest.raises(ValueError,):
        Configuration(worker_count=True,)

def test_live_engine_grounded_turn_and_cache(store,):
    service = AnalysisService(
        Configuration(
            worker_count=1,
            is_reproducible=True,
        ),
        store,
    )

    try:
        tutor = Tutor(
            service,
            Knowledge(store,),
            store,
        )
        turn = tutor.create_turn(chess.STARTING_FEN,)
        assert turn["engine_evidence"]["score_perspective"] == "white"
        assert turn["engine_evidence"]["engine"]["binary_sha256"]
        assert turn["board_directives"]
        hint = tutor.create_turn(
            chess.STARTING_FEN,
            intent="hint",
        )
        assert hint["engine_evidence"]["is_solution_hidden"]
        assert not hint["board_directives"]
        assert not hint["speech_plan"]["pronunciations"]
        assert len(service.engine.cache,) == 1
    finally:
        service.close()

def test_interrupted_jobs_are_recoverable(store,):
    store.put(
        "job",
        "old",
        {"id": "old", "status": "running",},
    )
    service = AnalysisService(
        Configuration(),
        store,
    )

    try:
        assert store.get(
            "job",
            "old",
        )["status"] == "interrupted"
    finally:
        service.close()

def test_background_analysis_finishes_and_persists(store,):
    service = AnalysisService(
        Configuration(worker_count=1,),
        store,
    )

    try:
        job = service.start_job("1. e4 e5 *",)
        service.jobs[job["id"]][0].result(timeout=30,)
        completed = store.get(
            "job",
            job["id"],
        )
        assert completed["status"] == "completed", completed
        assert completed["completed_searches"] > 0
        assert store.get(
            "analysis",
            job["id"],
        )["moves"]
    finally:
        service.close()

@pytest.mark.asyncio
async def test_new_tools_over_stdio(tmp_path,):
    import os
    import sys

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    parameters = StdioServerParameters(
        command=sys.executable,
        args=["-m", "gambit.main",],
        env={**os.environ, "GAMBIT_DATABASE": str(tmp_path / "mcp.sqlite3",),},
    )

    async with asyncio.timeout(20,):
        async with stdio_client(parameters,) as (reader, writer):
            async with ClientSession(
                reader,
                writer,
            ) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert "create_tutor_turn" in {tool.name for tool in tools.tools}
                capabilities = await session.call_tool(
                    "get_capabilities",
                    {},
                )
                assert not capabilities.is_error
                assert capabilities.structured_content["counts"]["opening"] == 0
                profile = await session.call_tool(
                    "update_learner_profile",
                    {"learner_id": "student", "style": "direct",},
                )
                assert not profile.is_error
                assert profile.structured_content["style"] == "direct"
                resources = await session.list_resources()
                assert any((str(resource.uri,) == "gambit://curriculum" for resource in resources.resources),)
                prompts = await session.list_prompts()
                assert "teach_chess" in {prompt.name for prompt in prompts.prompts}
                response = await session.call_tool(
                    "create_tutor_turn",
                    {"fen": chess.STARTING_FEN,},
                )
                assert not response.is_error
                assert response.structured_content["speech_plan"]["segments"]
                invalid = await session.call_tool(
                    "evaluate_position",
                    {"fen": "bad",},
                )
                assert invalid.is_error

def test_bundled_opening_corpus_is_legal_and_idempotent(store,):
    from gambit.infrastructure.corpus import load_bundled_openings

    report = load_bundled_openings(store,)
    assert report["imported_lines"] == 3864
    assert report["imported_edges"] == 37688
    assert store.count_records("study",) == 3864
    assert store.count_records("opening",) == 37688
    repeated = load_bundled_openings(store,)
    assert report == repeated
    assert store.count_records("opening",) == 37688

def test_cancelled_job_does_not_publish_partial_analysis(store,):
    import threading

    service = AnalysisService(
        Configuration(),
        store,
    )
    cancellation = threading.Event()
    cancellation.set()

    try:
        service.run_job(
            "cancelled",
            "1. e4 e5 *",
            True,
            cancellation,
        )
        assert store.get(
            "job",
            "cancelled",
        )["status"] == "cancelled"
        assert store.get(
            "analysis",
            "cancelled",
        ) is None
        assert all((client.process is None for client in service.engine.clients),)
    finally:
        service.close()

def test_old_attempt_retry_does_not_inflate_learning_progress(store,):
    training = Training(store,)
    first = training.record_attempt(
        "student",
        "puzzle",
        True,
        "one",
    )
    training.record_attempt(
        "student",
        "puzzle",
        True,
        "two",
    )
    assert training.record_attempt(
        "student",
        "puzzle",
        True,
        "one",
    ) == first
    assert store.get(
        "attempt",
        "student:puzzle",
    )["streak"] == 2

    with pytest.raises(
        ValueError,
        match="different outcome",
    ):
        training.record_attempt(
            "student",
            "puzzle",
            False,
            "one",
        )

def test_move_history_is_part_of_engine_cache_identity(store,):
    service = AnalysisService(
        Configuration(worker_count=1,),
        store,
    )
    board = chess.Board()

    for move in ("Nf3", "Nf6", "Ng1", "Ng8"):
        board.push_san(move,)

    try:
        service.engine.analyze(
            board,
            1,
            100,
        )
        service.engine.analyze(
            board.copy(stack=False,),
            1,
            100,
        )
        assert len(service.engine.cache,) == 2
    finally:
        service.close()

def test_speech_provider_adapter_and_cache(
    tmp_path,
    monkeypatch,
):
    from gambit.learning.speech import Speech

    calls = []

    def synthesize(
        arguments,
        **keywords,
    ):
        calls.append((arguments, keywords),)
        from pathlib import Path

        Path(arguments[arguments.index("-w",) + 1],).write_bytes(b"RIFFtest",)

    monkeypatch.setattr(
        "gambit.learning.speech.shutil.which",
        lambda executable: "/mock/espeak-ng",
    )
    monkeypatch.setattr(
        "gambit.learning.speech.subprocess.run",
        synthesize,
    )
    speech = Speech(
        "espeak-ng",
        str(tmp_path,),
    )
    first = speech.synthesize("Knight to f three.",)
    assert first == speech.synthesize("Knight to f three.",)
    assert len(calls,) == 1
    assert calls[0][1]["input"] == "Knight to f three."
    assert "--stdin" in calls[0][0]

def test_missing_speech_provider_is_explicit(
    tmp_path,
    monkeypatch,
):
    from gambit.learning.speech import Speech

    monkeypatch.setattr(
        "gambit.learning.speech.shutil.which",
        lambda executable: None,
    )

    with pytest.raises(
        RuntimeError,
        match="unavailable",
    ):
        Speech(
            "missing",
            str(tmp_path,),
        ).synthesize("Test.",)
