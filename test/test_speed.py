import asyncio
import json
import threading
from types import SimpleNamespace

import chess
import pytest

from gambit.engine.analysis import AnalysisService
from gambit.engine.client import execute_engine_request
from gambit.game.features import inspect_features
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge
from gambit.learning.service import Learning
from gambit.learning.training import Training
from gambit.learning.tutoring import Tutor

@pytest.fixture
def analysis():
    store = Store(":memory:",)
    service = AnalysisService(
        Configuration(worker_count=2,),
        store,
    )

    try:
        yield service
    finally:
        service.close()
        store.close()

def test_repeated_evidence_reuses_identity_and_preserves_history(analysis,):
    first = analysis.evaluate(chess.STARTING_FEN,)
    repeated = analysis.evaluate(chess.STARTING_FEN,)
    assert repeated["id"] == first["id"]
    assert analysis.store.count_records("analysis",) == 1
    repeated["evaluation"]["centipawns"] = 99999
    assert analysis.evaluate(chess.STARTING_FEN,)["evaluation"] == first["evaluation"]
    history = ["g1f3", "g8f6", "f3g1", "f6g8",]
    historical = analysis.evaluate(
        chess.STARTING_FEN,
        moves=history,
    )
    position_only = analysis.evaluate(historical["fen"],)
    assert historical["id"] != position_only["id"]
    assert historical["has_complete_history"]
    assert not position_only["has_complete_history"]
    cancellation = threading.Event()
    cancellation.set()

    with pytest.raises(InterruptedError,):
        analysis.evaluate(
            chess.STARTING_FEN,
            cancellation=cancellation,
        )

def test_instant_move_and_comparison_never_escalate(
    analysis,
    monkeypatch,
):
    searches = []
    analyze = analysis.engine.analyze

    def record_search(
        board,
        multipv,
        nodes,
        **kwargs,
    ):
        searches.append(nodes,)

        return analyze(
            board,
            multipv,
            nodes,
            **kwargs,
        )

    monkeypatch.setattr(
        analysis.engine,
        "analyze",
        record_search,
    )
    tutor = Tutor(
        analysis,
        Knowledge(analysis.store,),
        analysis.store,
    )
    turn = tutor.create_turn(
        chess.STARTING_FEN,
        move="e4",
    )
    assert turn["engine_evidence"]["fen"] == turn["position_context"]["fen"]
    assert turn["speech_plan"]["position_fen"] == turn["position_context"]["fen"]
    assert turn["move_assessment"]["assessment"]["evidence_status"] == "preliminary"
    comparison = tutor.create_turn(
        chess.STARTING_FEN,
        intent="compare",
        candidates=["e4", "d4",],
    )
    assert len(comparison["candidate_comparisons"],) == 2
    automatic = tutor.create_turn(
        chess.STARTING_FEN,
        intent="compare",
    )
    assert len(automatic["candidate_comparisons"],) == 2
    assert searches
    assert max(searches,) == analysis.configuration.instant_nodes
    assert all((entry["classification"] == "uncertain" for entry in comparison["candidate_comparisons"]),)

def test_compact_tutoring_retains_full_evidence_and_hides_hint_solutions(analysis,):
    knowledge = Knowledge(analysis.store,)
    knowledge.import_study(
        "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 *",
        "Test opening",
        "Authored test",
    )
    tutor = Tutor(
        analysis,
        knowledge,
        analysis.store,
    )
    full = tutor.create_turn(
        chess.STARTING_FEN,
        profile="quick",
        is_compact=False,
    )
    compact = tutor.create_turn(
        chess.STARTING_FEN,
        profile="quick",
    )
    evidence_id = compact["engine_evidence"]["id"]
    stored = analysis.store.get(
        "analysis",
        evidence_id,
    )
    assert stored["principal_variations"] == json.loads(json.dumps(full["engine_evidence"]["principal_variations"],),)
    assert len(json.dumps(compact,),) < len(json.dumps(full,),)
    assert all((len(line["moves_uci"],) <= 4 for line in compact["engine_evidence"]["principal_variations"]),)
    hint = tutor.create_turn(
        chess.STARTING_FEN,
        intent="hint",
        move="e4",
    )
    assert hint["engine_evidence"]["is_solution_hidden"]
    assert "principal_variations" not in hint["engine_evidence"]
    assert hint["move_assessment"] is None
    assert hint["opening_evidence"] is None
    assert not hint["candidate_comparisons"]
    assert not hint["board_directives"]
    assert not hint["speech_plan"]["pronunciations"]

def test_preliminary_teaching_can_be_confirmed_without_false_mastery():
    from test_improvements import CandidateEngine

    store = Store(":memory:",)

    try:
        learning = Learning(
            SimpleNamespace(engine=CandidateEngine(),),
            store,
        )
        question = learning.start_session(chess.STARTING_FEN,)
        preliminary = learning.submit_move(
            question.session_id,
            "e4",
        )
        assert preliminary.assessment.evidence_status == "preliminary"
        assert learning.get_progress("default",)[0]["attempts"] == 0
        confirmed = learning.submit_move(
            question.session_id,
            "e4",
            "deep",
        )
        assert confirmed.is_accepted
        assert learning.get_progress("default",)[0]["independent_successes"] == 1
        training = Training(
            store,
            SimpleNamespace(engine=CandidateEngine(),),
        )
        store.put(
            "puzzle",
            "puzzle",
            {"id": "puzzle", "solution": ["d2d4",],},
        )
        store.put(
            "session",
            "session",
            {"id": "session", "puzzle_id": "puzzle", "learner_id": "learner", "fen": chess.STARTING_FEN, "ply": 0, "status": "active", "has_failed": False,},
        )
        preliminary_tactic = training.submit_tactic_move(
            "session",
            "e4",
        )
        assert preliminary_tactic["assessment"]["evidence_status"] == "preliminary"
        assert store.count_records("attempt",) == 0
        confirmed_tactic = training.submit_tactic_move(
            "session",
            "e4",
            "deep",
        )
        assert confirmed_tactic["is_correct"]
        assert store.count_records("attempt",) == 0
    finally:
        store.close()

def test_cached_features_cannot_be_mutated_by_callers():
    first = inspect_features(chess.STARTING_FEN,)
    first["sides"]["white"]["isolated_pawns"].append("a2",)
    assert not inspect_features(chess.STARTING_FEN,)["sides"]["white"]["isolated_pawns"]

def test_time_limits_respect_explicit_search_ceiling():
    configuration = Configuration(search_time_ms=100,)
    assert configuration.get_search_time_ms(configuration.instant_nodes,) == 100
    assert configuration.get_search_time_ms(configuration.quick_nodes,) == 100
    assert configuration.get_search_time_ms(configuration.deep_nodes,) == 100

    with pytest.raises(ValueError,):
        Configuration(instant_search_time_ms=0,)

def test_storage_position_lookup_uses_ordered_index(analysis,):
    rows = analysis.store.connection.execute(
        "EXPLAIN QUERY PLAN SELECT payload FROM record WHERE collection = ? AND json_extract(payload, '$.position_key') = ? ORDER BY id LIMIT ? OFFSET ?",
        ("opening", "position", 3, 0),
    ).fetchall()
    assert any(("record_position_order" in row[3] for row in rows),)
    assert not any(("TEMP B-TREE" in row[3] for row in rows),)

@pytest.mark.asyncio
async def test_executor_completion_and_errors_reach_async_callers():
    completed = await execute_engine_request(lambda: 42,)
    assert completed == 42

    def raise_failure():
        raise ValueError("Expected failure.",)

    with pytest.raises(
        ValueError,
        match="Expected failure",
    ):
        await execute_engine_request(raise_failure,)

    await asyncio.wait_for(
        execute_engine_request(lambda: 43,),
        timeout=1,
    )
