import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from types import SimpleNamespace

import chess
import pytest

from gambit.engine.analysis import AnalysisService, EnginePool
from gambit.engine.client import StockfishClient
from gambit.game.assessment import assess_move, build_board, classify_loss
from gambit.infrastructure.configuration import Configuration, load_package_environment
from gambit.infrastructure.storage import Store
from gambit.knowledge.tablebases import Tablebases
from gambit.learning.openings import OpeningPlan, OpeningPlans
from gambit.learning.progressive import ProgressiveAnalysis
from gambit.learning.service import Learning
from gambit.learning.training import Training, get_repertoire_progress_id
from scripts.maintain_storage import restore_backup

class CandidateEngine:
    configuration = Configuration(
        quick_nodes=100,
        deep_nodes=1000,
    )

    def analyze(
        self,
        board,
        multipv,
        nodes,
        *,
        root_moves=(),
        cancellation=None,
    ):
        move = chess.Move.from_uci(root_moves[0] if root_moves else "e2e4",)

        return [{"centipawns": -200 if move.uci() == "a2a3" else 20, "mate_in": None, "pv": [move,], "depth": 10, "actual_nodes": nodes,},]

@pytest.fixture
def database():
    store = Store(":memory:",)

    try:
        yield store
    finally:
        store.close()

def test_root_assessment_confirms_loss_without_fabricated_confidence():
    assessment = assess_move(
        CandidateEngine(),
        chess.STARTING_FEN,
        "a3",
    )
    assert assessment.classification == "serious mistake"
    assert assessment.verified.centipawn_loss == 220
    assert assessment.evidence_status == "deeper confirmation"
    assert "confidence probability" in assessment.caveat

@pytest.mark.parametrize(
    "best_mate,candidate_mate,expected",
    [(3, None, "loses forced mate"), (None, -2, "allows forced mate"), (3, 5, "preserves forced mate"), (-2, -3, "already facing forced mate"),],
)
def test_mate_transitions_are_not_centipawn_losses(
    best_mate,
    candidate_mate,
    expected,
):
    loss, transition, _ = classify_loss(
        {"centipawns": 0, "mate_in": best_mate, "pv": [],},
        {"centipawns": 0, "mate_in": candidate_mate, "pv": [],},
    )
    assert loss is None
    assert transition == expected

def test_history_preserves_repetition():
    board = build_board(
        chess.STARTING_FEN,
        ["g1f3", "g8f6", "f3g1", "f6g8",] * 2,
    )
    assert board.is_repetition(3,)

def test_stability_requires_a_larger_verification_budget():
    engine = CandidateEngine()
    engine.configuration = Configuration(
        quick_nodes=100,
        deep_nodes=100,
    )
    assessment = assess_move(
        engine,
        chess.STARTING_FEN,
        "e4",
    )
    assert assessment.evidence_status == "preliminary"
    assert assessment.classification == "uncertain"

def test_learning_hides_answers_and_tracks_independent_progress(database,):
    learning = Learning(
        SimpleNamespace(engine=CandidateEngine(),),
        database,
    )
    question = learning.start_session(chess.STARTING_FEN,)
    serialized = json.dumps(asdict(question,),)
    assert "e2e4" not in serialized
    hint = learning.get_hint(
        question.session_id,
        1,
    )
    assert "e2e4" not in json.dumps(asdict(hint,),)
    feedback = learning.submit_move(
        question.session_id,
        "e4",
    )
    assert feedback.is_accepted
    progress = learning.get_progress("default",)[0]
    assert progress["attempts"] == 1
    assert progress["independent_successes"] == 0

    with pytest.raises(
        ValueError,
        match="not active",
    ):
        learning.submit_move(
            question.session_id,
            "e4",
        )

def test_opening_plan_transpositions_and_source_coverage(database,):
    plans = OpeningPlans(database,)
    first = build_board(
        chess.STARTING_FEN,
        ["g1f3", "d7d5", "d2d4", "g8f6",],
    )
    second = build_board(
        chess.STARTING_FEN,
        ["d2d4", "g8f6", "g1f3", "d7d5",],
    )
    plan = OpeningPlan(
        "Central development",
        first.fen(),
        ["Develop before making repeated queen moves.",],
        [],
        [],
        [],
        "Authored test",
        "1",
        "2026-10-04",
    )
    plans.save_plan(plan,)
    report = plans.get_plans(second.fen(),)
    assert len(report["plans"],) == 1
    assert not report["plans"][0]["is_engine_verified"]
    assert plans.get_coverage()["sources"][0]["positions"] == 1

def test_practical_statistics_remain_separate_from_theory(database,):
    plans = OpeningPlans(database,)
    plans.import_statistics(
        chess.STARTING_FEN,
        "e4",
        10,
        3,
        7,
        "Authored test",
        "2026-10-04",
        "Twenty illustrative games",
    )
    report = plans.get_plans(chess.STARTING_FEN,)
    assert not report["plans"]
    assert report["practical_statistics"][0]["white_wins"] == 10

def test_tablebase_diagnostics_and_checksums(tmp_path,):
    payload = b"Checksum fixture, not a usable tablebase."
    (tmp_path / "KQvK.rtbw").write_bytes(payload,)
    tables = Tablebases(str(tmp_path,),)
    diagnostics = tables.get_diagnostics()
    assert diagnostics.wdl_files == 1
    assert not diagnostics.has_complete_pairs
    manifest = tmp_path / "checksums.sha256"
    manifest.write_text(hashlib.sha256(payload,).hexdigest() + "  KQvK.rtbw\n",)
    assert tables.verify_checksums(str(manifest,),)["is_valid"]
    manifest.write_text("0" * 64 + "  KQvK.rtbw\n",)
    assert not tables.verify_checksums(str(manifest,),)["is_valid"]

def test_tablebase_manifest_rejects_path_traversal(tmp_path,):
    manifest = tmp_path / "checksums.sha256"
    manifest.write_text("0" * 64 + "  ../KQvK.rtbw\n",)

    with pytest.raises(ValueError,):
        Tablebases(str(tmp_path,),).verify_checksums(str(manifest,),)

def test_backup_restore_and_retention_preserve_references(
    database,
    tmp_path,
):
    database.put(
        "analysis",
        "orphan",
        {"id": "orphan",},
    )
    database.put(
        "analysis",
        "linked",
        {"id": "linked",},
    )
    database.put(
        "lesson",
        "lesson",
        {"analysis_id": "linked",},
    )
    backup = database.create_backup(str(tmp_path / "backup.sqlite3",),)
    preview = database.prune_analysis("2099-01-01T00:00:00+00:00",)
    assert preview["candidate_count"] == 1
    assert database.count_records("analysis",) == 2
    assert database.prune_analysis(
        "2099-01-01T00:00:00+00:00",
        True,
    )["deleted_count"] == 1
    destination = restore_backup(
        backup,
        str(tmp_path / "restored.sqlite3",),
    )
    restored = Store(destination,)

    try:
        assert restored.count_records("analysis",) == 2
    finally:
        restored.close()

    with pytest.raises(FileExistsError,):
        restore_backup(
            backup,
            destination,
        )

def test_package_dotenv_does_not_load_tunnel_credentials(
    tmp_path,
    monkeypatch,
):
    from gambit.infrastructure import configuration
    module_path = tmp_path / "src" / "gambit" / "infrastructure" / "configuration.py"
    module_path.parent.mkdir(parents=True,)
    (tmp_path / ".env").write_text("OPENAI_API_KEY=fake-test-key\nCONTROL_PLANE_TUNNEL_ID=fake-tunnel\nGAMBIT_HTTP_PORT=3999\n",)
    monkeypatch.setattr(
        configuration,
        "__file__",
        str(module_path,),
    )
    monkeypatch.delenv(
        "OPENAI_API_KEY",
        raising=False,
    )
    monkeypatch.delenv(
        "CONTROL_PLANE_TUNNEL_ID",
        raising=False,
    )
    monkeypatch.delenv(
        "GAMBIT_HTTP_PORT",
        raising=False,
    )
    load_package_environment()
    import os
    assert "OPENAI_API_KEY" not in os.environ
    assert "CONTROL_PLANE_TUNNEL_ID" not in os.environ
    assert os.environ["GAMBIT_HTTP_PORT"] == "3999"

def test_interactive_search_has_capacity_during_background_work():
    entered = threading.Event()
    release = threading.Event()

    class BlockingClient:
        name = "Stockfish test"
        version = "test"

        def analyze(
            self,
            board,
            multipv,
            nodes,
            **options,
        ):
            if nodes == 100:
                entered.set()
                assert release.wait(5,)

            return [{"centipawns": 0, "mate_in": None, "pv": [chess.Move.from_uci("e2e4",),],},]

        def close(self,):
            return None

    pool = EnginePool(Configuration(worker_count=2,),)
    pool.clients = [BlockingClient(), BlockingClient(),]

    while not pool.available.empty():
        pool.available.get_nowait()

    for client in pool.clients:
        pool.available.put(client,)

    with ThreadPoolExecutor(max_workers=2,) as executor:
        background = executor.submit(
            pool.analyze,
            chess.Board(),
            1,
            100,
            is_background=True,
        )

        try:
            assert entered.wait(3,)
            interactive = executor.submit(
                pool.analyze,
                chess.Board(),
                1,
                10,
            )
            assert interactive.result(timeout=3,)
        finally:
            release.set()

        assert background.result(timeout=3,)

    assert pool.get_metrics()["has_reserved_interactive_capacity"]
    pool.close()

def test_live_engine_search_cancellation_drains_protocol(monkeypatch,):
    engine = StockfishClient(Configuration(),)
    cancellation = threading.Event()
    original = engine.send

    def send_and_cancel(command,):
        original(command,)

        if command.startswith("go ",):
            cancellation.set()

    monkeypatch.setattr(
        engine,
        "send",
        send_and_cancel,
    )

    try:
        with pytest.raises(InterruptedError,):
            engine.analyze(
                chess.Board(),
                1,
                100000,
                cancellation=cancellation,
            )

        monkeypatch.setattr(
            engine,
            "send",
            original,
        )
        assert engine.analyze(
            chess.Board(),
            1,
            1000,
        )
    finally:
        engine.close()

def test_live_checkpoint_recovery_reuses_completed_searches(database,):
    service = AnalysisService(
        Configuration(),
        database,
    )

    try:
        job = service.start_job("1. e4 e5 *",)
        service.jobs[job["id"]][0].result(timeout=30,)
        completed = database.get(
            "job",
            job["id"],
        )
        assert completed["status"] == "completed"
        completed["status"] = "interrupted"
        database.put(
            "job",
            job["id"],
            completed,
        )
        service.resume_job(job["id"],)
        service.jobs[job["id"]][0].result(timeout=30,)
        recovered = database.get(
            "job",
            job["id"],
        )
        assert recovered["reused_searches"] > 0
        assert recovered["status"] == "completed"
    finally:
        service.close()

def test_progressive_results_are_hidden_after_cancellation(database,):
    service = AnalysisService(
        Configuration(),
        database,
    )
    progressive = ProgressiveAnalysis(service,)

    try:
        started = progressive.start(
            "board",
            chess.STARTING_FEN,
        )
        status = progressive.get_status(
            started["request_id"],
            True,
        )
        assert status["status"] == "cancelled"
        assert status["analysis_id"] is None
    finally:
        progressive.close()
        service.close()

def test_live_engine_recovers_after_process_exit():
    engine = StockfishClient(Configuration(),)

    try:
        engine.analyze(
            chess.Board(),
            1,
            1000,
        )
        engine.process.kill()
        engine.process.wait(timeout=5,)

        with pytest.raises(RuntimeError,):
            engine.analyze(
                chess.Board(),
                1,
                2000,
            )

        assert engine.analyze(
            chess.Board(),
            1,
            3000,
        )
    finally:
        engine.close()

def test_repertoire_spaced_review_uses_position_identity(database,):
    from gambit.knowledge.base import Knowledge
    Knowledge(database,).import_study(
        "1. Nf3 d5 2. d4 *",
        "Repertoire",
        "Authored test",
        True,
    )
    training = Training(database,)
    fen = training.get_due_repertoire("learner",)
    assert fen is not None
    training.record_attempt(
        "learner",
        get_repertoire_progress_id(fen,),
        True,
        "attempt",
    )
    assert get_repertoire_progress_id(training.get_due_repertoire("learner",),) != get_repertoire_progress_id(fen,)

def test_unstable_assessment_does_not_grade_a_move_as_wrong():
    class UnstableEngine(CandidateEngine):
        def analyze(
            self,
            board,
            multipv,
            nodes,
            *,
            root_moves=(),
            cancellation=None,
        ):
            lines = super().analyze(
                board,
                multipv,
                nodes,
                root_moves=root_moves,
                cancellation=cancellation,
            )

            if nodes == self.configuration.deep_nodes and root_moves:
                lines[0]["centipawns"] = 20

            return lines

    assessment = assess_move(
        UnstableEngine(),
        chess.STARTING_FEN,
        "a3",
    )
    assert assessment.evidence_status == "unstable"
    assert assessment.classification == "uncertain"

def test_game_lessons_are_idempotent_and_retain_history(database,):
    database.put(
        "analysis",
        "game",
        {"initial_fen": chess.STARTING_FEN, "moves": [{"uci": "e2e4", "centipawn_loss": 120,}, {"uci": "e7e5", "centipawn_loss": 0,},],},
    )
    learning = Learning(
        SimpleNamespace(engine=CandidateEngine(),),
        database,
    )
    first = learning.create_review_lessons(
        "game",
        "learner",
        "white",
    )
    second = learning.create_review_lessons(
        "game",
        "learner",
        "white",
    )
    assert first == second
    assert first["lessons"][0]["history"] == []
    assert database.count_records("lesson",) == 1

def test_puzzle_alternative_does_not_receive_source_mastery_credit(database,):
    training = Training(
        database,
        SimpleNamespace(engine=CandidateEngine(),),
    )
    database.put(
        "puzzle",
        "puzzle",
        {"id": "puzzle", "solution": ["d2d4",],},
    )
    database.put(
        "session",
        "session",
        {"id": "session", "puzzle_id": "puzzle", "learner_id": "learner", "fen": chess.STARTING_FEN, "ply": 0, "status": "active", "has_failed": False,},
    )
    response = training.submit_tactic_move(
        "session",
        "e4",
    )
    assert response["is_correct"]
    assert not response["is_objective_verified"]
    assert database.count_records("attempt",) == 0

def test_completed_report_is_idempotent_across_json_containers(database,):
    database.put(
        "analysis",
        "tuple",
        {"moves": ("e4", "e5"),},
        is_immutable=True,
    )
    database.put(
        "analysis",
        "tuple",
        {"moves": ("e4", "e5"),},
        is_immutable=True,
    )
    assert database.get(
        "analysis",
        "tuple",
    )["moves"] == ["e4", "e5",]

def test_starter_plans_are_versioned_and_idempotent(database,):
    from gambit.learning.openings import load_starter_plans
    assert load_starter_plans(database,) == 4
    assert load_starter_plans(database,) == 4
    assert database.count_records("opening_plan",) == 4

    for plan in database.list_records("opening_plan",):
        assert plan["source_version"] == "1"
        assert not plan["is_engine_verified"]
