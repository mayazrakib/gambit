
import chess
import pytest

from gambit.game.assessment import assess_move, build_board, classify_loss
from gambit.infrastructure.configuration import Configuration

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

def test_root_assessment_confirms_loss_without_fabricated_confidence():
    assessment = assess_move(
        CandidateEngine(),
        chess.STARTING_FEN,
        "a3",
        profile="deep",
    )

    assert assessment.classification == "serious mistake"
    assert assessment.verified.centipawn_loss == 220
    assert assessment.evidence_status == "deeper confirmation"
    assert "search_agreement_not_probability" in assessment.limitation_codes

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
        profile="deep",
    )

    assert assessment.evidence_status == "preliminary"
    assert assessment.classification == "uncertain"
