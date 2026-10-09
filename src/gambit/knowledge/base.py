import csv
import hashlib
import io
import json
from contextlib import nullcontext
from pathlib import Path

import chess
import chess.pgn
import chess.syzygy

from gambit.engine.client import parse_board
from gambit.game.service import ValidatedGameBuilder, validate_pgn_tokens
from gambit.infrastructure.storage import Store

MAX_IMPORT_BYTES = 8 * 1024 * 1024

def get_position_key(board: chess.Board,) -> str:
    return " ".join(board.fen().split()[:4],)

def parse_study(pgn: str,) -> chess.pgn.Game:
    if not pgn.strip() or len(pgn.encode(),) > MAX_IMPORT_BYTES:
        raise ValueError("A study must contain between 1 byte and 8 MiB of PGN.",)

    validate_pgn_tokens(pgn,)
    stream = io.StringIO(pgn,)
    game = chess.pgn.read_game(
        stream,
        Visitor=ValidatedGameBuilder,
    )

    if game is None or chess.pgn.read_game(stream,) is not None:
        raise ValueError("Import exactly one PGN study at a time, including its variations.",)

    return game

class Knowledge:
    def __init__(
        self,
        store: Store,
    ) -> None:
        self.store = store

    def import_study(
        self,
        pgn: str,
        name: str,
        source: str,
        is_repertoire: bool = False,
    ) -> dict:
        if not name.strip() or not source.strip():
            raise ValueError("A study name and source attribution are required.",)

        game = parse_study(pgn,)
        study_id = hashlib.sha256((source + "\n" + name + "\n" + pgn).encode(),).hexdigest()
        collection = "repertoire" if is_repertoire else "opening"
        records = []
        stack = [(game, game.board(), 0),]

        while stack:
            node, board, ply = stack.pop()

            if len(records,) >= 10000 or ply > 256:
                raise ValueError("A study exceeds 10000 branches or 256 plies.",)

            for child in node.variations:
                key = get_position_key(board,)
                move = child.move
                record_id = hashlib.sha256((study_id + key + move.uci()).encode(),).hexdigest()
                records.append({
                    "id": record_id,
                    "study_id": study_id,
                    "name": name,
                    "eco": game.headers.get("ECO",),
                    "position_key": key,
                    "fen": board.fen(),
                    "move_uci": move.uci(),
                    "move_san": board.san(move,),
                    "comment": child.comment,
                    "source": source,
                    "provenance": collection,
                    "ply": ply,
                },)
                next_board = board.copy()
                next_board.push(move,)
                stack.append((child, next_board, ply + 1),)

        self.store.put_many(
            collection,
            records,
        )
        final_board = game.end().board()
        self.store.put(
            "study",
            study_id,
            {"id": study_id, "name": name, "eco": game.headers.get("ECO",), "position_key": get_position_key(final_board,), "fen": final_board.fen(), "source": source, "provenance": collection, "pgn": pgn,},
        )

        return {"study_id": study_id, "imported_edges": len(records,), "source": source,}

    def find_moves(
        self,
        fen: str,
        is_repertoire: bool = False,
        offset: int = 0,
    ) -> dict:
        board = parse_board(fen,)
        collection = "repertoire" if is_repertoire else "opening"
        records = self.store.list_records(
            collection,
            100,
            offset,
            get_position_key(board,),
        )

        return {
            "fen": board.fen(),
            "moves": records,
            "reached_openings": self.store.list_records(
                "study",
                100,
                offset,
                get_position_key(board,),
            ),
            "next_offset": offset + 100 if len(records,) == 100 else None,
        }

    def import_opening_tsv(
        self,
        tsv: str,
        source: str,
    ) -> dict:
        if len(tsv.encode(),) > MAX_IMPORT_BYTES or not source.strip():
            raise ValueError("Opening imports require a source and at most 8 MiB of TSV.",)

        rows = list(csv.DictReader(
            io.StringIO(tsv,),
            delimiter="\t",
        ),)

        if not rows or not {"eco", "name", "pgn",}.issubset(rows[0],):
            raise ValueError("Opening TSV must include eco, name, and pgn columns.",)

        for row in rows:
            parse_study(row["pgn"],)

        imported = 0

        for row in rows:
            report = self.import_study(
                f'[ECO "{row["eco"]}"]\n\n{row["pgn"]}',
                row["name"],
                source,
            )
            imported += report["imported_edges"]

        return {"imported_lines": len(rows,), "imported_edges": imported, "source": source,}

    def search_openings(
        self,
        query: str,
        offset: int = 0,
    ) -> list[dict]:
        if len(query,) > 200 or offset < 0:
            raise ValueError("Opening search parameters are outside supported limits.",)

        with self.store.lock:
            rows = self.store.connection.execute(
                """
                    SELECT payload FROM record
                    WHERE collection = 'opening'
                        AND instr(lower(json_extract(payload, '$.name')), lower(?)) > 0

                    ORDER BY id
                    LIMIT 100 OFFSET ?
                """,
                (query, offset),
            ).fetchall()

        return [json.loads(row[0],) for row in rows]

def probe_tablebase(
    fen: str,
    directory: str,
    tables: chess.syzygy.Tablebase | None = None,
) -> dict:
    board = parse_board(fen,)

    if not directory:
        return {"status": "unavailable", "reason": "No Syzygy directory is configured.",}

    if board.castling_rights or len(board.piece_map(),) > 7:
        return {
            "status": "unsupported",
            "reason": "Syzygy requires at most seven pieces and no castling rights.",
        }

    try:
        with (nullcontext(tables,) if tables is not None else chess.syzygy.open_tablebase(str(Path(directory,).expanduser(),),)) as tablebase:
            wdl = tablebase.probe_wdl(board,)
            dtz = tablebase.probe_dtz(board,)
            moves = []

            for move in board.legal_moves:
                san = board.san(move,)
                board.push(move,)

                if board.is_checkmate():
                    child_wdl = -2
                elif board.is_stalemate() or board.is_insufficient_material():
                    child_wdl = 0
                else:
                    child_wdl = tablebase.probe_wdl(board,)

                board.pop()
                moves.append({"uci": move.uci(), "san": san, "wdl": -child_wdl,},)

        return {
            "status": "available",
            "wdl": wdl,
            "dtz": dtz,
            "score_perspective": "side to move",
            "halfmove_clock": board.halfmove_clock,
            "moves": sorted(
                moves,
                key=lambda move: -move["wdl"],
            ),
            "provenance": "local syzygy",
            "caveat": "WDL and DTZ are raw Syzygy values. Apply the current halfmove clock and draw-claim rules before declaring a forced result.",
        }
    except (KeyError, OSError) as exception:
        return {"status": "unavailable", "reason": str(exception,),}
