import io
from copy import deepcopy
from functools import lru_cache

import chess
import chess.pgn

from gambit.api.structured import export_result
from gambit.game.position import build_board, get_position_reference, get_terminal_facts

@lru_cache(maxsize=16,)
def build_position(
    root_fen: str,
    history: tuple[
        str,
        ...,
    ],
) -> chess.Board:
    return build_board(
        root_fen,
        history,
    )

@lru_cache(maxsize=16,)
def inspect_position(
    root_fen: str,
    history: tuple[
        str,
        ...,
    ],
    player_color: str,
) -> dict:
    board = build_position(
        root_fen,
        history,
    )

    outcome = board.outcome()

    return {
        "fen": board.fen(),
        "side_to_move": "white" if board.turn else "black",
        "player_color": player_color,
        "ply": len(history,),
        "last_move": history[-1] if history else None,
        "is_check": board.is_check(),
        "can_claim_draw_now": get_terminal_facts(board,)["can_claim_draw_now"],
        "is_game_over": outcome is not None,
        "result": outcome.result() if outcome else None,
        "termination": outcome.termination.name.lower().replace(
            "_",
            " ",
        ) if outcome else None,
    }

@lru_cache(maxsize=16,)
def export_position(
    root_fen: str,
    history: tuple[
        str,
        ...,
    ],
    player_color: str,
) -> dict:
    board = build_position(
        root_fen,
        history,
    )

    replay = chess.Board(root_fen,)
    moves = []

    for notation in history:
        move = chess.Move.from_uci(notation,)
        moves.append({"san": replay.san(move,), "uci": notation, "number": replay.fullmove_number, "color": "white" if replay.turn else "black",},)
        replay.push(move,)

    pgn = chess.pgn.Game.from_board(board,)
    pgn.headers["White"] = "You" if player_color == "white" else "Stockfish"
    pgn.headers["Black"] = "You" if player_color == "black" else "Stockfish"

    pgn.headers["Result"] = inspect_position(
        root_fen,
        history,
        player_color,
    )["result"] or "*"

    return {"moves": moves, "pgn": str(pgn,),}

def render_position(
    game: dict,
    should_include_history: bool,
) -> dict:
    arguments = (game["root_fen"], tuple(game["history"],), game["settings"]["player_color"])
    result = {"schema_version": 3, "game_id": game["game_id"], "revision": game["revision"], **inspect_position(*arguments,),}

    result["position_reference"] = get_position_reference(build_position(
        game["root_fen"],
        tuple(game["history"],),
    ),)

    result["position_reference"].update({"game_id": game["game_id"], "revision": game["revision"],},)
    result["draw_claim"] = game.get("draw_claim",)

    if result["draw_claim"]:
        result.update({"is_game_over": True, "result": "1/2-1/2", "termination": result["draw_claim"]["reason"],},)

    if should_include_history:
        result.update({
            **deepcopy(export_position(*arguments,),),
            "event_id": game["event_id"],
            "event_sequence": game.get(
                "event_sequence",
                0,
            ),
            "root_fen": game["root_fen"],
            "history": list(game["history"],),
            "settings": dict(game["settings"],),
            "annotations": deepcopy(game["annotations"],),
            "teaching": export_result(deepcopy(game["teaching"],),) if (game.get("teaching",) or {}).get("schema_version",) == 3 else None,
        },)

    if game.get("draw_claim",) and should_include_history:
        exported = chess.pgn.read_game(io.StringIO(result["pgn"],),)
        exported.headers["Result"] = "1/2-1/2"
        result["pgn"] = str(exported,)

    return result
