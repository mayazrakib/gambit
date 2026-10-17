from typing import Literal

import chess
from pydantic import BaseModel, ConfigDict, Field, model_validator

from gambit.engine.client import parse_move
from gambit.game.position import (
    build_board,
    get_material,
    get_position_reference,
    get_terminal_facts,
    replay_variation,
)

class ChessFactQuery(BaseModel,):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    predicate: Literal[
        "geometric_attack",
        "legal_move",
        "legal_capture",
        "absolute_pin",
        "capture",
        "check",
        "material",
        "terminal",
        "repetition_claim",
    ]

    source_square: str | None = Field(
        default=None,
        pattern="^[a-h][1-8]$",
    )

    target_square: str | None = Field(
        default=None,
        pattern="^[a-h][1-8]$",
    )

    move_uci: str | None = Field(
        default=None,
        pattern="^[a-h][1-8][a-h][1-8][qrbn]?$",
    )

    @model_validator(mode="after",)
    def validate_arguments(self,):
        expected = {"geometric_attack": {"source_square", "target_square",}, "absolute_pin": {"source_square",}, "legal_move": {"move_uci",}, "legal_capture": {"move_uci",}, "capture": {"move_uci",},}

        supplied = {name for name in ("source_square", "target_square", "move_uci") if getattr(
            self,
            name,
        ) is not None}

        if supplied != expected.get(
            self.predicate,
            set(),
        ):
            raise ValueError("Supply exactly the arguments required by this fact predicate.",)

        return self

def query_board_facts(
    board: chess.Board,
    queries: list[ChessFactQuery],
    has_history: bool = True,
) -> list[dict]:
    if len(queries,) > 64:
        raise ValueError("Supply at most 64 fact queries.",)

    results = []

    for index, query in enumerate(queries,):
        data = None
        is_supported = False
        reason = None

        if query.predicate == "geometric_attack":
            source = chess.parse_square(query.source_square,)
            is_supported = chess.parse_square(query.target_square,) in board.attacks(source,)
        elif query.predicate == "absolute_pin":
            square = chess.parse_square(query.source_square,)
            piece = board.piece_at(square,)

            is_supported = piece is not None and piece.piece_type != chess.KING and board.is_pinned(
                piece.color,
                square,
            )
        elif query.predicate in ("legal_move", "legal_capture", "capture"):
            move = chess.Move.from_uci(query.move_uci,)
            is_supported = not board.is_game_over() and board.is_legal(move,)

            if query.predicate != "legal_move":
                is_supported = is_supported and board.is_capture(move,)

            if is_supported:
                data = replay_variation(
                    board,
                    [move.uci(),],
                    "query",
                    has_history,
                )
        elif query.predicate == "check":
            is_supported = board.is_check()
        elif query.predicate == "terminal":
            is_supported = board.is_game_over()

            data = get_terminal_facts(
                board,
                has_history,
            )

            if data["is_terminal"] is None:
                reason = "incomplete_prior_history"
        elif query.predicate == "material":
            is_supported = True
            data = get_material(board,)
        elif query.predicate == "repetition_claim":
            is_supported = not board.is_game_over() and board.can_claim_threefold_repetition()

            if not is_supported and not board.is_game_over() and get_position_reference(
                board,
                has_history,
            )["history_scope"] != "complete":
                reason = "incomplete_prior_history"

        results.append({"query_index": index, "query": query.model_dump(exclude_none=True,), "status": "unknown" if reason else "supported" if is_supported else "refuted", "evidence": data, "reason_code": reason, "evidence_kind": "rules_verified",},)

    return results

def query_position_facts(
    fen: str,
    queries: list[ChessFactQuery],
    history: list[str] | None = None,
    continuation: list[str] | None = None,
) -> dict:
    board = build_board(
        fen,
        history,
    )

    reference = get_position_reference(
        board,
        history is not None,
    )

    observations = replay_variation(
        board,
        continuation or [],
        "query_continuation",
        history is not None,
    )

    for notation in continuation or []:
        board.push(parse_move(
            board,
            notation,
        ),)

    return {
        "schema_version": 3,
        "position_reference": get_position_reference(
            board,
            history is not None,
        ),
        "root_reference": reference,
        "scope": "hypothetical" if continuation else "current",
        "variation": observations,
        "results": query_board_facts(
            board,
            queries,
            history is not None,
        ),
    }
