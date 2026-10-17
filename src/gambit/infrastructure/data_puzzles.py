import json
import os

import chess

def lower_import_priority() -> None:
    if hasattr(
        os,
        "nice",
    ):
        os.nice(10,)

def validate_puzzle_row(row: dict,) -> tuple | None:
    try:
        themes = sorted(set(row["Themes"].split(),),)

        if not 1 <= len(row["PuzzleId"],) <= 64 or len(themes,) > 64 or any((len(theme,) > 64 for theme in themes),) or len(row.get(
            "GameUrl",
            "",
        ),) > 2048:
            return None

        board = chess.Board(row["FEN"],)

        if not board.is_valid():
            return None

        moves = row["Moves"].split()

        if not 2 <= len(moves,) <= 128:
            return None

        board.push_uci(moves[0],)
        fen = board.fen()

        for move in moves[1:]:
            board.push_uci(move,)

        return (row["PuzzleId"], fen, json.dumps(moves[1:],), int(row["Rating"],), json.dumps(themes,), row.get(
            "GameUrl",
            "",
        ))
    except (ValueError, KeyError, TypeError):
        return None
