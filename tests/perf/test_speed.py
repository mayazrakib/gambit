import threading

import chess
import pytest

from gambit.engine.analysis import AnalysisService
from gambit.game.features import inspect_features
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store

@pytest.fixture
def analysis():
    store = Store()

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
    assert len(analysis.store.records["analysis"],) == 1
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

    from gambit.game.evidence import Evidence
    from gambit.knowledge.base import Knowledge

    evidence = Evidence(
        analysis,
        Knowledge('/tmp/unused-gambit-openings',),
        None,
    )

    turn = analysis.evaluate_move(
        chess.STARTING_FEN,
        'e4',
    )

    assert turn['assessment']['evidence_status'] == 'preliminary'

    comparison = evidence.create_turn(
        chess.STARTING_FEN,
        intent='compare',
        candidates=['e4', 'd4',],
    )

    assert len(comparison['candidate_comparisons'],) == 2

    automatic = evidence.create_turn(
        chess.STARTING_FEN,
        intent='compare',
    )

    assert len(automatic['candidate_comparisons'],) == 2
    assert searches
    assert max(searches,) == analysis.configuration.instant_nodes
    assert all((entry["classification"] == "uncertain" for entry in comparison["candidate_comparisons"]),)

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
