import csv
import hashlib
import io
from importlib.resources import files

import chess

from gambit.infrastructure.storage import Store
from gambit.knowledge.base import get_position_key
from gambit.learning.openings import load_starter_plans

OPENING_REVISION = "5a13018164f6bd88f48b3dc31a8e2a39f31a060a"
OPENING_SOURCE = f"https://github.com/lichess-org/chess-openings/tree/{OPENING_REVISION}"

def load_bundled_openings(store: Store,) -> dict:
    records = []
    studies = []
    line_count = 0

    for letter in "abcde":
        content = files("gambit",).joinpath(
            "data",
            f"{letter}.tsv",
        ).read_text()

        for row in csv.DictReader(
            io.StringIO(content,),
            delimiter="\t",
        ):
            board = chess.Board()
            study_id = hashlib.sha256((OPENING_REVISION + row["pgn"] + row["name"]).encode(),).hexdigest()
            line_count += 1

            for token in row["pgn"].split():
                if token.endswith(".",):
                    continue

                move = board.parse_san(token,)
                key = get_position_key(board,)
                record_id = hashlib.sha256((study_id + key + move.uci()).encode(),).hexdigest()
                records.append({
                    "id": record_id,
                    "study_id": study_id,
                    "name": row["name"],
                    "eco": row["eco"],
                    "position_key": key,
                    "fen": board.fen(),
                    "move_uci": move.uci(),
                    "move_san": board.san(move,),
                    "comment": "",
                    "source": OPENING_SOURCE,
                    "provenance": "corpus",
                    "ply": board.ply(),
                },)
                board.push(move,)

            studies.append({"id": study_id, "name": row["name"], "eco": row["eco"], "position_key": get_position_key(board,), "fen": board.fen(), "source": OPENING_SOURCE, "provenance": "corpus", "pgn": row["pgn"],},)

    store.put_many(
        "opening",
        records,
    )
    store.put_many(
        "study",
        studies,
    )

    return {"imported_lines": line_count, "imported_edges": len(records,), "revision": OPENING_REVISION, "source": OPENING_SOURCE, "imported_teaching_plans": load_starter_plans(store,),}
