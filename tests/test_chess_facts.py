from dataclasses import asdict

import chess
import pytest
from pydantic import ValidationError

from gambit.api.structured import validate_public_result
from gambit.engine.uci import parse_analysis_line
from gambit.game.assessment import classify_loss
from gambit.game.position import (
    build_board,
    get_position_reference,
    replay_variation,
    validate_draw_claim,
)
from gambit.game.queries import ChessFactQuery, query_position_facts
from gambit.infrastructure.storage import Store
from gambit.live.games import LiveGames
from gambit.live.opponent import OpponentSettings

HISTORY = ["g1f3", "g8f6", "f3g1", "f6g8",]

def query(
    fen,
    predicate,
    **arguments,
):
    return query_position_facts(
        fen,
        [
            ChessFactQuery(
                predicate=predicate,
                **arguments,
            ),
        ],
    )["results"][0]

def test_bb5_attacks_but_does_not_pin_knight_behind_d7_pawn():
    board = build_board(
        chess.STARTING_FEN,
        ["e4", "e5", "Nf3", "Nc6", "Nc3", "Nf6", "Bb5",],
    )

    assert query(
        board.fen(),
        "geometric_attack",
        source_square="b5",
        target_square="c6",
    )["status"] == "supported"

    assert query(
        board.fen(),
        "absolute_pin",
        source_square="c6",
    )["status"] == "refuted"

def test_absolute_pin_does_not_remove_geometric_attacks_but_blocks_capture():
    fen = "4r2k/8/8/8/8/2p5/4N3/4K3 w - - 0 1"

    assert query(
        fen,
        "absolute_pin",
        source_square="e2",
    )["status"] == "supported"

    assert query(
        fen,
        "geometric_attack",
        source_square="e2",
        target_square="c3",
    )["status"] == "supported"

    assert query(
        fen,
        "legal_capture",
        move_uci="e2c3",
    )["status"] == "refuted"

@pytest.mark.parametrize(
    "fen,move",
    [
        ("k3r3/8/8/3pP3/8/8/8/4K3 w - d6 0 1", "e5d6"),
        ("4r2k/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1"),
        (chess.STARTING_FEN, "0000"),
    ],
)
def test_replay_rejects_illegal_moves_and_null_moves(
    fen,
    move,
):
    with pytest.raises(ValueError,):
        replay_variation(
            build_board(fen,),
            [move,],
        )

def test_capture_en_passant_and_underpromotion_have_exact_material_changes():
    captured = replay_variation(
        build_board("7k/8/8/3pP3/8/8/8/4K3 w - d6 0 1",),
        ["e5d6",],
    )[0]

    assert captured["captured_piece"] == "p"
    assert captured["is_en_passant"]
    assert captured["material_delta"]["black"]["pawn"] == -1

    promoted = replay_variation(
        build_board("7k/P7/8/8/8/8/8/4K3 w - - 0 1",),
        ["a7a8n",],
    )[0]

    assert promoted["promotion"] == "knight"
    assert promoted["material_delta"]["white"]["pawn"] == -1
    assert promoted["material_delta"]["white"]["knight"] == 1

def test_automatic_terminal_states_do_not_accept_continuations():
    assert query(
        "7k/5K2/6Q1/8/8/8/8/8 b - - 0 1",
        "terminal",
    )["status"] == "supported"

    board = build_board(
        chess.STARTING_FEN,
        HISTORY * 4,
    )

    assert board.is_fivefold_repetition()

    with pytest.raises(ValueError,):
        replay_variation(
            board,
            ["g1f3",],
        )

def test_claimable_draw_requires_explicit_claim_and_intended_move_is_not_played():
    board = build_board(
        chess.STARTING_FEN,
        HISTORY + HISTORY[:3],
    )

    before = board.fen()
    assert not board.is_game_over()
    assert board.can_claim_threefold_repetition()

    with pytest.raises(ValueError,):
        validate_draw_claim(board,)

    claim = validate_draw_claim(
        board,
        "f6g8",
    )

    assert claim["reason"] == "threefold_repetition"
    assert board.fen() == before
    assert len(board.move_stack,) == 7

def test_unknown_repetition_history_and_history_identity():
    result = query(
        chess.STARTING_FEN,
        "repetition_claim",
    )

    assert result["status"] == "unknown"

    complete = query_position_facts(
        chess.STARTING_FEN,
        [ChessFactQuery(predicate="repetition_claim",),],
        history=[],
    )

    assert complete["results"][0]["status"] == "refuted"

    assert get_position_reference(build_board(
        chess.STARTING_FEN,
        [],
    ),)["history_id"] != get_position_reference(build_board(
        chess.STARTING_FEN,
        HISTORY,
    ),)["history_id"]

def test_query_limits_and_unsupported_predicates_fail_closed():
    with pytest.raises(ValidationError,):
        ChessFactQuery(predicate="wins_queen",)

    with pytest.raises(ValidationError,):
        ChessFactQuery(
            predicate="absolute_pin",
            source_square="z9",
        )

    with pytest.raises(ValidationError,):
        ChessFactQuery(
            predicate="check",
            move_uci="e2e4",
        )

    with pytest.raises(ValueError,):
        query_position_facts(
            chess.STARTING_FEN,
            [ChessFactQuery(predicate="check",),] * 65,
        )

    with pytest.raises(ValueError,):
        query_position_facts(
            chess.STARTING_FEN,
            [],
            continuation=HISTORY * 7,
        )

def create_store():
    from contextlib import contextmanager

    @contextmanager
    def open_store():
        store = Store()

        try:
            yield store
        finally:
            store.close()

    return open_store()

def test_live_fifty_move_claim_preserves_position_and_undo_reopens_game():
    with create_store() as store:
        games = LiveGames(store,)

        game = games.create(
            asdict(OpponentSettings(),),
            "7k/8/8/8/8/8/8/KR6 w - - 100 51",
        )

        assert not game["is_game_over"]

        result = games.claim_draw(
            game["game_id"],
            0,
        )

        assert result["is_game_over"]
        assert result["fen"] == game["fen"]
        assert result["history"] == []
        assert '[Result "1/2-1/2"]' in result["pgn"]

        with pytest.raises(ValueError,):
            games.move(
                game["game_id"],
                1,
                "b1b2",
            )

        reopened = games.undo(
            game["game_id"],
            1,
        )

        assert not reopened["is_game_over"]
        assert reopened["revision"] == 2

def test_bounds_cannot_produce_a_grade_and_malformed_pv_is_rejected():
    line = {"centipawns": 500, "mate_in": None, "pv": [chess.Move.from_uci("e2e4",),], "score_bound": "lower",}

    assert classify_loss(
        line,
        line,
    )[2] == "uncertain"

    with pytest.raises(RuntimeError,):
        parse_analysis_line(
            "info depth 8 score cp 25 pv e2e4 garbage".split(),
            {},
        )

def test_legacy_response_adapter_preserves_user_text_and_removes_generated_prose():
    source = {"schema_version": 1, "fen": chess.STARTING_FEN, "speech_plan": {"response_text": "Invented explanation",}, "observed_changes": ["Old explanation",], "caveat": "Old caveat", "user_text": {"question": "Why Bb5?",}, "reasoning": "My reasoning", "source_text": {"message": "Attributed quotation",},}
    result = validate_public_result(source,)
    assert result["schema_version"] == 3
    assert "speech_plan" not in result
    assert "caveat" not in result
    assert result["observed_changes"] == []
    assert result["user_text"]["question"] == "Why Bb5?"
    assert result["source_text"]["message"] == "Attributed quotation"
    assert result["reasoning"] == "My reasoning"
    assert source["schema_version"] == 1

def test_generated_observation_types_and_query_results_fail_closed():
    observation = replay_variation(
        chess.Board(),
        ["e4",],
    )[0]

    observation["is_capture"] = "false"

    with pytest.raises(ValidationError,):
        validate_public_result(observation,)

    with pytest.raises(ValidationError,):
        validate_public_result({"query_index": 0, "query": {}, "status": "probably", "evidence": None, "reason_code": None, "evidence_kind": "rules_verified",},)
