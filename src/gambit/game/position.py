import hashlib
import json

import chess

MAX_HISTORY_PLIES = 1024
MAX_CONTINUATION_PLIES = 24

def build_board(
    fen: str,
    history: list[str] | None = None,
) -> chess.Board:
    from gambit.engine.client import parse_board, parse_move

    if history is not None and (not isinstance(
        history,
        (list, tuple),
    ) or len(history,) > MAX_HISTORY_PLIES):
        raise ValueError("Supply an ordered history of at most 1024 moves.",)

    board = parse_board(fen,)

    for notation in history or []:
        if board.is_game_over():
            raise ValueError("Position history continues after an automatic terminal state.",)

        board.push(parse_move(
            board,
            notation,
        ),)

    return board

def get_position_reference(
    board: chess.Board,
    has_history: bool = True,
) -> dict:
    root = board.root().fen()
    history = [move.uci() for move in board.move_stack]

    identity = json.dumps(
        [root, history,],
        separators=(",", ":"),
    )

    return {
        "fen": board.fen(),
        "history_id": hashlib.sha256(identity.encode(),).hexdigest(),
        "history_scope": "complete" if has_history and root == chess.STARTING_FEN else "supplied_root" if has_history or history else "position_only",
    }

def get_terminal_facts(
    board: chess.Board,
    has_history: bool = True,
) -> dict:
    outcome = board.outcome()

    result = {
        "side_to_move": "white" if board.turn else "black",
        "is_check": board.is_check(),
        "is_checkmate": board.is_checkmate(),
        "is_stalemate": board.is_stalemate(),
        "is_terminal": outcome is not None,
        "result": outcome.result() if outcome else None,
        "termination": outcome.termination.name.lower() if outcome else None,
        "can_claim_draw_now": not board.is_game_over() and (board.is_fifty_moves() or board.is_repetition(3,)),
        "can_claim_fifty_moves": outcome is None and board.can_claim_fifty_moves(),
        "can_claim_threefold_repetition": outcome is None and board.can_claim_threefold_repetition(),
    }

    if outcome is None and get_position_reference(
        board,
        has_history,
    )["history_scope"] != "complete":
        if not result["can_claim_threefold_repetition"]:
            result["can_claim_threefold_repetition"] = None

        if not result["can_claim_draw_now"]:
            result["can_claim_draw_now"] = None

        result["is_terminal"] = None

    return result

def validate_draw_claim(
    board: chess.Board,
    intended_move: str | None = None,
) -> dict:
    from gambit.engine.client import parse_move

    if board.is_game_over():
        raise ValueError("An automatic terminal position cannot accept a draw claim.",)

    replay = board.copy(stack=True,)
    notation = None

    if intended_move is not None:
        move = parse_move(
            replay,
            intended_move,
        )

        notation = move.uci()
        replay.push(move,)

    reason = "threefold_repetition" if replay.is_repetition(3,) else "fifty_moves" if replay.is_fifty_moves() else None

    if reason is None:
        raise ValueError("The supplied history and intended move do not establish a valid draw claim.",)

    return {"reason": reason, "intended_move_uci": notation, "claiming_side": "white" if board.turn else "black", "result": "1/2-1/2",}

def get_material(board: chess.Board,) -> dict:
    return {side: {chess.piece_name(kind,): len(board.pieces(
        kind,
        color,
    ),) for kind in chess.PIECE_TYPES} for color, side in ((chess.WHITE, "white"), (chess.BLACK, "black"))}

def replay_variation(
    board: chess.Board,
    moves: list[str],
    variation_id: str = "principal",
    has_history: bool = True,
) -> list[dict]:
    from gambit.engine.client import parse_move

    if len(moves,) > MAX_CONTINUATION_PLIES:
        raise ValueError("A hypothetical continuation supports at most 24 plies.",)

    replay = board.copy(stack=True,)
    observations = []

    for ply, notation in enumerate(
        moves,
        start=1,
    ):
        if replay.is_game_over():
            raise ValueError("A continuation cannot extend beyond an automatic terminal state.",)

        move = parse_move(
            replay,
            notation,
        )

        before = get_position_reference(
            replay,
            has_history,
        )

        material_before = get_material(replay,)
        capture_square = move.to_square - (8 if replay.turn else -8) if replay.is_en_passant(move,) else move.to_square
        captured = replay.piece_at(capture_square,) if replay.is_capture(move,) else None

        entry = {
            "variation_id": variation_id,
            "ply": ply,
            "position_before": before,
            "side": "white" if replay.turn else "black",
            "move_uci": move.uci(),
            "move_san": replay.san(move,),
            "is_capture": replay.is_capture(move,),
            "is_en_passant": replay.is_en_passant(move,),
            "is_castling": replay.is_castling(move,),
            "promotion": chess.piece_name(move.promotion,) if move.promotion else None,
            "captured_piece": captured.symbol() if captured else None,
        }

        replay.push(move,)
        piece = replay.piece_at(move.to_square,)
        attacks = sorted((chess.square_name(square,) for square in replay.attacks(move.to_square,)),)
        material_after = get_material(replay,)

        entry.update({
            "position_after": get_position_reference(
                replay,
                has_history,
            ),
            "facts": get_terminal_facts(
                replay,
                has_history,
            ),
            "geometric_attacks": {"from": chess.square_name(move.to_square,), "targets": attacks,},
            "is_moved_piece_absolutely_pinned": replay.is_pinned(
                piece.color,
                move.to_square,
            ),
            "material_delta": {side: {kind: material_after[side][kind] - material_before[side][kind] for kind in material_after[side] if material_after[side][kind] != material_before[side][kind]} for side in material_after},
            "evidence_kind": "rules_verified",
            "scope": "shown_variation",
        },)

        observations.append(entry,)

    return observations
