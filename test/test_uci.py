import chess
import pytest

from gambit.engine.uci import parse_analysis_line

@pytest.mark.parametrize(
    "bound",
    ["lowerbound", "upperbound",],
)
def test_bound_scores_do_not_replace_exact_variations(bound: str,) -> None:
    assert parse_analysis_line(
        f"info depth 18 score cp 50 {bound} pv e2e4".split(),
        {"depth": 18,},
    ) is None

def test_truncates_invalid_continuation_and_preserves_metrics() -> None:
    parsed = parse_analysis_line(
        "info multipv 2 score mate -4 pv e2e4 e7e5 invalid g1f3".split(),
        {"depth": 18, "nodes": 250, "time": 12,},
    )

    assert parsed == (2, {
        "centipawns": None,
        "mate_in": -4,
        "pv": [chess.Move.from_uci("e2e4",), chess.Move.from_uci("e7e5",),],
        "depth": 18,
        "actual_nodes": 250,
        "engine_time_ms": 12,
    },)

def test_malformed_scores_keep_existing_error_semantics() -> None:
    with pytest.raises(ValueError,):
        parse_analysis_line(
            "info score cp invalid pv e2e4".split(),
            {},
        )
