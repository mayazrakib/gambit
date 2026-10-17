import io
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import chess
import chess.pgn
import pytest

from gambit.engine.analysis import AnalysisService
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge
from gambit.learning.exercises import ORIGINAL_ENDGAMES, get_opening_boards, select_variant
from gambit.learning.practice import Practice
from gambit.learning.sessions import TutorSessions
from gambit.learning.tutoring import Tutor

@pytest.fixture
def tutor_services():
    store = Store(":memory:",)

    analysis = AnalysisService(
        Configuration(
            worker_count=2,
            instant_nodes=1000,
            quick_nodes=4000,
            deep_nodes=16000,
            candidate_count=1,
            prefetch_branches=0,
        ),
        store,
    )

    sessions = TutorSessions(
        analysis,
        store,
    )

    practice = Practice(
        analysis,
        store,
        sessions,
    )

    try:
        yield store, analysis, sessions, practice
    finally:
        analysis.close()
        store.close()

def test_variation_tree_preserves_mainline_and_replays_operations(tutor_services,):
    _, _, sessions, _ = tutor_services

    session = sessions.create_session(
        chess.STARTING_FEN,
        history=[],
    )

    identifier = session["session_id"]
    root = session["active_node_id"]

    first = sessions.navigate_session(
        identifier,
        0,
        "advance-first",
        "advance",
        "e4",
    )

    assert sessions.navigate_session(
        identifier,
        0,
        "advance-first",
        "advance",
        "e4",
    ) == first

    with pytest.raises(
        ValueError,
        match="different arguments",
    ):
        sessions.navigate_session(
            identifier,
            0,
            "advance-first",
            "advance",
            "d4",
        )

    sessions.navigate_session(
        identifier,
        1,
        "select-root",
        "select",
        node_id=root,
    )

    branch = sessions.navigate_session(
        identifier,
        2,
        "branch",
        "branch",
        "d4",
    )

    assert branch["history"] == ["d2d4",]

    returned = sessions.navigate_session(
        identifier,
        3,
        "return",
        "return",
    )

    assert returned["history"] == ["e2e4",]
    assert returned["node_count"] == 3
    assert returned["board_directives"][0]["revision"] == 4

def test_revision_rejects_racing_writers(tutor_services,):
    _, _, sessions, _ = tutor_services
    identifier = sessions.create_session(chess.STARTING_FEN,)["session_id"]

    def advance(index,):
        try:
            return sessions.navigate_session(
                identifier,
                0,
                f"race-{index}",
                "advance",
                "e4",
            )
        except ValueError:
            return None

    with ThreadPoolExecutor(max_workers=2,) as executor:
        results = list(executor.map(
            advance,
            range(2,),
        ),)

    assert sum((result is not None for result in results),) == 1
    assert sessions.get_session(identifier,)["revision"] == 1

def test_session_restart_and_pgn_roundtrip(tmp_path,):
    path = str(tmp_path / "learner.sqlite3",)
    store = Store(path,)

    sessions = TutorSessions(
        None,
        store,
    )

    identifier = sessions.create_session(chess.STARTING_FEN,)["session_id"]
    root = sessions.get_session(identifier,)["active_node_id"]

    sessions.navigate_session(
        identifier,
        0,
        "e4",
        "advance",
        "e4",
    )

    sessions.navigate_session(
        identifier,
        1,
        "root",
        "select",
        node_id=root,
    )

    sessions.navigate_session(
        identifier,
        2,
        "d4",
        "branch",
        "d4",
    )

    store.close()
    reopened = Store(path,)

    try:
        restored = TutorSessions(
            None,
            reopened,
        )

        exported = restored.export_session(identifier,)
        game = chess.pgn.read_game(io.StringIO(exported["content"],),)
        assert not game.errors
        assert {variation.move.uci() for variation in game.variations} == {"e2e4", "d2d4",}
        assert restored.get_session(identifier,)["revision"] == 3
    finally:
        reopened.close()

def test_reasoning_uses_engine_and_retains_uncertainty(tutor_services,):
    store, _, sessions, _ = tutor_services

    identifier = sessions.create_session(
        chess.STARTING_FEN,
        history=[],
    )["session_id"]

    report = sessions.submit_reasoning(
        identifier,
        0,
        "reason",
        "e4",
        "Control the center.",
        ["e5", "Nf3",],
        0.8,
        20,
    )

    assert report["assessment"]["evidence_status"] == "preliminary"
    assert not report["is_confirmed"]
    assert len(report["continuation_evidence"],) == 2
    assert store.count_records("learning_event",) == 1

    assert sessions.submit_reasoning(
        identifier,
        0,
        "reason",
        "e4",
        "Control the center.",
        ["e5", "Nf3",],
        0.8,
        20,
    ) == report

    assert store.count_records("learning_event",) == 1

@pytest.mark.parametrize(
    "confidence",
    [float("nan",), float("inf",), -1, 2, True,],
)
def test_reasoning_rejects_invalid_confidence(
    tutor_services,
    confidence,
):
    _, _, sessions, _ = tutor_services
    identifier = sessions.create_session(chess.STARTING_FEN,)["session_id"]

    with pytest.raises(
        ValueError,
        match="Confidence",
    ):
        sessions.submit_reasoning(
            identifier,
            0,
            "invalid",
            "e4",
            confidence=confidence,
        )

def test_calculation_keeps_board_fixed_and_hides_solution(tutor_services,):
    _, _, _, practice = tutor_services

    session = practice.start_practice(
        "calculation",
        fen=chess.STARTING_FEN,
    )

    assert "e2e4" not in json.dumps(session,)

    first_hint = practice.act_practice(
        session["practice_id"],
        0,
        "hint",
        "hint",
    )

    assert "e2e4" not in json.dumps(first_hint,)

    submitted = practice.act_practice(
        session["practice_id"],
        1,
        "line",
        "submit",
        ["e4", "e5", "Nf3",],
    )

    assert submitted["fen"] == chess.STARTING_FEN
    assert submitted["is_assisted"]
    assert not submitted["is_confirmed"]
    assert "board_directives" not in submitted

    replayed = practice.act_practice(
        session["practice_id"],
        2,
        "replay",
        "replay",
    )

    assert replayed["board_directives"][0]["action"] == "replay variation"
    assert replayed["board_directives"][0]["moves_uci"] == ["e2e4", "e7e5", "g1f3",]

def test_refutation_requires_prediction_and_reveals_incrementally(tutor_services,):
    _, _, _, practice = tutor_services

    session = practice.start_practice(
        "refutation",
        fen=chess.STARTING_FEN,
    )

    submitted = practice.act_practice(
        session["practice_id"],
        0,
        "candidate",
        "submit",
        ["f3",],
    )

    assert "line_evidence" not in submitted
    assert "variation_uci" not in json.dumps(submitted,)
    assert submitted["candidate_feedback"]["is_reply_hidden"]

    revealed = practice.act_practice(
        session["practice_id"],
        1,
        "reply",
        "reveal",
    )

    assert len(revealed["refutation_uci"],) == 1
    assert revealed["is_assisted"]

    repaired = practice.act_practice(
        session["practice_id"],
        2,
        "repair",
        "repair",
        ["e4",],
    )

    assert repaired["revision"] == 3

def test_invalid_continuation_does_not_create_attempt(tutor_services,):
    store, _, _, practice = tutor_services

    identifier = practice.start_practice(
        "calculation",
        fen=chess.STARTING_FEN,
    )["practice_id"]

    with pytest.raises(ValueError,):
        practice.act_practice(
            identifier,
            0,
            "illegal",
            "submit",
            ["e4", "e4",],
        )

    assert store.count_records("learning_event",) == 0
    assert practice.get_practice(identifier,)["revision"] == 0

def test_endgame_play_retains_history_and_retry_checkpoint(tutor_services,):
    _, _, _, practice = tutor_services
    fen = "8/8/3k4/8/3K4/4P3/8/8 w - - 0 1"

    identifier = practice.start_practice(
        "endgame",
        fen=fen,
    )["practice_id"]

    played = practice.act_practice(
        identifier,
        0,
        "play",
        "play",
        ["Kd3",],
    )

    assert played["snapshot_count"] == 2
    assert played["board_directives"][0]["revision"] == 1
    assert "tablebase_evidence" in played

    retried = practice.act_practice(
        identifier,
        1,
        "retry",
        "retry",
        checkpoint=0,
    )

    assert retried["fen"] == fen
    assert retried["is_assisted"]

def test_dashboard_only_counts_confirmed_independent_results(tutor_services,):
    store, _, _, practice = tutor_services
    now = datetime.now(UTC,)

    rows = [
        {"id": "1", "is_confirmed": False, "is_accepted": False, "is_assisted": False, "confidence": 0.9,},
        {"id": "2", "is_confirmed": True, "is_accepted": True, "is_assisted": True, "confidence": 0.9,},
        {"id": "3", "is_confirmed": True, "is_accepted": False, "is_assisted": False, "confidence": 0.9,},
        {"id": "4", "is_confirmed": True, "is_accepted": True, "is_assisted": False, "confidence": 0.6,},
    ]

    for index, row in enumerate(rows,):
        event = {"learner_id": "default", "source_id": "same", "fen": chess.STARTING_FEN, "move_uci": "e2e4", "classification": "acceptable" if row["is_accepted"] else "serious mistake", "themes": ["calculation",], "mode": "transfer", "is_timed": index == 2, "elapsed_ms": 10000, "system_created_at": (now - timedelta(days=4 - index,)).isoformat(), "due_at": (now - timedelta(days=1,)).isoformat(), **row,}

        store.put(
            "learning_event",
            row["id"],
            event,
        )

    dashboard = practice.get_dashboard()
    assert dashboard["confirmed_attempts"] == 3
    assert dashboard["independent_attempts"] == 2
    assert dashboard["unassisted_accuracy"] == 0.5
    assert dashboard["confidence_brier_score"] == pytest.approx(0.485,)
    assert [item["event_id"] for item in dashboard["confidently_wrong_events"]] == ["3",]
    assert dashboard["delayed_unassisted_count"] == 2
    assert len(dashboard["timed_untimed_comparisons"],) == 1
    assert len(practice.get_due_reviews()["reviews"],) == 1

def test_opening_prediction_is_separate_from_engine_quality(tutor_services,):
    _, _, sessions, practice = tutor_services

    class Corpus:
        def list_games(
            self,
            limit,
        ):
            return [{"id": "game", "root_fen": chess.STARTING_FEN, "moves": ["e2e4", "e7e5", "g1f3", "b8c6",], "source": "original test game", "headers": {},},]

    practice.corpus = Corpus()
    identifier = practice.start_practice("prediction",)["practice_id"]

    response = practice.act_practice(
        identifier,
        0,
        "prediction",
        "submit",
        ["Nc6",],
    )

    assert response["matches_played_move"]
    assert "played_move_caveat" in response

    revealed = practice.act_practice(
        identifier,
        1,
        "game-reveal",
        "reveal",
    )

    assert revealed["variation_uci"] == ["b8c6",]

def test_tutor_delta_reuses_evidence_and_session_move_is_idempotent(tutor_services,):
    store, analysis, sessions, _ = tutor_services

    tutor = Tutor(
        analysis,
        Knowledge(store,),
        store,
        sessions,
    )

    session = sessions.create_session(
        chess.STARTING_FEN,
        history=[],
    )

    first = tutor.create_turn(
        chess.STARTING_FEN,
        session_id=session["session_id"],
        expected_revision=0,
    )

    identifier = first["engine_evidence"]["id"]
    searches = analysis.engine.search_count

    second = tutor.create_turn(
        chess.STARTING_FEN,
        session_id=session["session_id"],
        expected_revision=0,
        response_mode="delta",
        known_evidence_ids=[identifier,],
    )

    assert second["engine_evidence"] == {"id": identifier, "is_unchanged": True,}
    assert analysis.engine.search_count == searches

    moved = tutor.create_turn(
        chess.STARTING_FEN,
        move="e4",
        session_id=session["session_id"],
        expected_revision=0,
        operation_id="turn-move",
    )

    assert tutor.create_turn(
        chess.STARTING_FEN,
        move="e4",
        session_id=session["session_id"],
        expected_revision=0,
        operation_id="turn-move",
    ) == moved

    assert sessions.get_session(session["session_id"],)["revision"] == 1

def test_original_position_construction_is_legal_and_variants_are_distinct():
    boards = get_opening_boards() + [chess.Board(fen,) for fen in ORIGINAL_ENDGAMES]
    seen = {board.board_fen() for board in boards}

    for board in boards:
        assert board.is_valid()
        assert not board.is_game_over()

        for role in ("transfer", "counterexample"):
            variant, change = select_variant(
                board,
                role,
                seen,
            )

            assert variant.is_valid()
            assert variant.fen() != board.fen()
            assert change["from"] != change["to"]

def test_delta_payload_reduces_tokens_without_new_searches(tutor_services,):
    store, analysis, sessions, _ = tutor_services

    tutor = Tutor(
        analysis,
        Knowledge(store,),
        store,
        sessions,
    )

    detailed = tutor.create_turn(
        chess.STARTING_FEN,
        detail="detailed",
    )

    identifier = detailed["engine_evidence"]["id"]
    searches = analysis.engine.search_count

    delta = tutor.create_turn(
        chess.STARTING_FEN,
        detail="detailed",
        response_mode="delta",
        known_evidence_ids=[identifier,],
    )

    assert len(json.dumps(delta,),) < len(json.dumps(detailed,),) / 2
    assert analysis.engine.search_count == searches
    assert delta["speech_plan"]["is_unchanged"]
    assert "engine" not in delta["engine_evidence"]

def test_explained_answers_are_marked_assisted(tutor_services,):
    store, analysis, sessions, _ = tutor_services

    tutor = Tutor(
        analysis,
        Knowledge(store,),
        store,
        sessions,
    )

    identifier = sessions.create_session(chess.STARTING_FEN,)["session_id"]

    tutor.create_turn(
        chess.STARTING_FEN,
        session_id=identifier,
        expected_revision=0,
    )

    sessions.submit_reasoning(
        identifier,
        0,
        "after-explanation",
        "e4",
        confidence=0.9,
    )

    event = store.list_records("learning_event",)[0]
    assert event["is_assisted"]

def test_transfer_selects_related_position_and_keeps_answer_hidden(tutor_services,):
    store, _, _, practice = tutor_services
    base = {"id": "base", "category": "calculation", "role": "base", "root_fen": chess.STARTING_FEN, "fen": chess.STARTING_FEN, "history": [], "solution": ["e2e4",], "source": "original test construction",}
    board = chess.Board()
    board.push_san("d4",)
    related = {**base, "id": "base-transfer", "role": "transfer", "base_id": "base", "root_fen": board.fen(), "fen": board.fen(), "solution": ["d7d5",],}

    store.put(
        "exercise",
        base["id"],
        base,
    )

    store.put(
        "exercise",
        related["id"],
        related,
    )

    result = practice.start_practice(
        "transfer",
        source_id="base",
    )

    assert result["fen"] == related["fen"]
    assert "d7d5" not in json.dumps(result,)
    assert "base_move_assessment" not in json.dumps(result,)

def test_practice_replay_is_idempotent_and_conflicting_reuse_fails(tutor_services,):
    store, _, _, practice = tutor_services

    identifier = practice.start_practice(
        "mixed",
        fen=chess.STARTING_FEN,
    )["practice_id"]

    first = practice.act_practice(
        identifier,
        0,
        "submit-once",
        "submit",
        ["e4",],
    )

    replayed = practice.act_practice(
        identifier,
        0,
        "submit-once",
        "submit",
        ["e4",],
    )

    assert replayed == first
    assert store.count_records("learning_event",) == 1

    with pytest.raises(
        ValueError,
        match="different arguments",
    ):
        practice.act_practice(
            identifier,
            0,
            "submit-once",
            "submit",
            ["d4",],
        )

def test_plan_and_practical_comparisons_share_one_baseline(
    tutor_services,
    monkeypatch,
):
    _, analysis, sessions, _ = tutor_services

    identifier = sessions.create_session(
        chess.STARTING_FEN,
        history=[],
    )["session_id"]

    seen = []
    original = analysis.engine.analyze_candidates

    def record_candidates(
        board,
        moves,
        nodes,
    ):
        seen.append((tuple(moves,), nodes),)

        return original(
            board,
            moves,
            nodes,
        )

    monkeypatch.setattr(
        analysis.engine,
        "analyze_candidates",
        record_candidates,
    )

    result = sessions.assess_plan(
        identifier,
        ["Develop a knight and prepare central control.",],
        ["Nf3", "Nc3",],
    )

    assert len(seen,) == 1
    assert len(result["candidate_evidence"],) == 2
    assert "unrestricted" in result["unresolved"]
    assert all(("strongest_reply_uci" in candidate for candidate in result["candidate_evidence"]),)

def test_tutor_failed_or_cancelled_analysis_does_not_advance(
    tutor_services,
    monkeypatch,
):
    import threading

    from gambit.engine.client import REQUEST_CONTEXT, RequestContext

    store, analysis, sessions, _ = tutor_services

    tutor = Tutor(
        analysis,
        Knowledge(store,),
        store,
        sessions,
    )

    identifier = sessions.create_session(chess.STARTING_FEN,)["session_id"]
    evaluate_move = analysis.evaluate_move

    def fail_analysis(
        *arguments,
        **options,
    ):
        raise RuntimeError("The engine stopped.",)

    monkeypatch.setattr(
        analysis,
        "evaluate_move",
        fail_analysis,
    )

    with pytest.raises(
        RuntimeError,
        match="engine stopped",
    ):
        tutor.create_turn(
            chess.STARTING_FEN,
            move="e4",
            session_id=identifier,
            expected_revision=0,
            operation_id="retry-turn",
        )

    assert sessions.get_session(identifier,)["revision"] == 0
    assert sessions.get_session(identifier,)["history"] == []
    cancellation = threading.Event()

    def cancel_after_analysis(
        *arguments,
        **options,
    ):
        result = evaluate_move(
            *arguments,
            **options,
        )

        cancellation.set()

        return result

    monkeypatch.setattr(
        analysis,
        "evaluate_move",
        cancel_after_analysis,
    )

    token = REQUEST_CONTEXT.set(RequestContext(cancellation,),)

    try:
        with pytest.raises(InterruptedError,):
            tutor.create_turn(
                chess.STARTING_FEN,
                move="e4",
                session_id=identifier,
                expected_revision=0,
                operation_id="retry-turn",
            )
    finally:
        REQUEST_CONTEXT.reset(token,)

    assert sessions.get_session(identifier,)["revision"] == 0

    monkeypatch.setattr(
        analysis,
        "evaluate_move",
        evaluate_move,
    )

    finished = tutor.create_turn(
        chess.STARTING_FEN,
        move="e4",
        session_id=identifier,
        expected_revision=0,
        operation_id="retry-turn",
    )

    assert finished["session"]["revision"] == 1
    assert finished["session"]["history"] == ["e2e4",]

    assert tutor.create_turn(
        chess.STARTING_FEN,
        move="e4",
        session_id=identifier,
        expected_revision=0,
        operation_id="retry-turn",
    ) == finished

def test_game_review_identifies_opportunity_before_the_blunder(tutor_services,):
    from gambit.learning.service import Learning

    store, analysis, _, _ = tutor_services

    store.put(
        "analysis",
        "review",
        {"initial_fen": chess.STARTING_FEN, "moves": [{"uci": "e2e4", "centipawn_loss": 40,}, {"uci": "e7e5", "centipawn_loss": 0,}, {"uci": "g1f3", "centipawn_loss": 180,},],},
    )

    report = Learning(
        analysis,
        store,
    ).create_review_lessons(
        "review",
        "default",
        "white",
    )

    assert report["first_missed_decision"]["ply"] == 1
    assert report["first_missed_decision"]["observed_loss_centipawns"] == 40
    assert len(report["lessons"],) == 1
    assert report["lessons"][0]["history"] == ["e2e4", "e7e5",]
    assert "confirmation" in report["first_missed_decision"]["status"]
