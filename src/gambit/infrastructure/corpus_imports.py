import csv
import hashlib
import io
import json
from compression import zstd
from concurrent.futures import ProcessPoolExecutor
from contextlib import nullcontext
from datetime import UTC, datetime
from itertools import islice
from pathlib import Path

import chess
import chess.pgn

from gambit.infrastructure.data_evaluations import import_evaluations
from gambit.infrastructure.data_puzzles import lower_import_priority, validate_puzzle_row

IMPORT_BATCH_ROWS = 2000

class CorpusImports:
    def get_checkpoint(
        self,
        identifier: str,
    ) -> dict | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT id, sha256, processed_rows, imported_rows, rejected_rows, status, system_created_at, system_updated_at FROM import_checkpoint WHERE id = ?",
                (identifier,),
            ).fetchone()

        return dict(row,) if row else None

    def save_checkpoint(
        self,
        report: dict,
    ) -> None:
        timestamp = datetime.now(UTC,).isoformat()

        self.connection.execute(
            """
            INSERT INTO import_checkpoint (
                id, sha256, processed_rows, imported_rows, rejected_rows, status,
                system_created_at, system_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id) DO UPDATE SET
                sha256 = excluded.sha256,
                processed_rows = excluded.processed_rows,
                imported_rows = excluded.imported_rows,
                rejected_rows = excluded.rejected_rows,
                status = excluded.status,
                system_updated_at = excluded.system_updated_at
        """,
            (report["id"], report["sha256"], report["processed_rows"], report["imported_rows"], report["rejected_rows"], report["status"], timestamp, timestamp),
        )

    def import_puzzles(
        self,
        path: str | Path,
        source: str,
        sha256: str = "",
    ) -> dict:
        identifier = "puzzles:" + source
        checkpoint = self.get_checkpoint(identifier,)

        if checkpoint and checkpoint["sha256"] == sha256 and checkpoint["status"] == "complete":
            return checkpoint

        report = {"id": identifier, "sha256": sha256, "processed_rows": 0, "imported_rows": 0, "rejected_rows": 0, "status": "importing",}

        skip_rows = checkpoint["processed_rows"] if checkpoint and checkpoint["sha256"] == sha256 else 0

        if skip_rows:
            report.update({key: checkpoint[key] for key in ("processed_rows", "imported_rows", "rejected_rows")},)

        rows = []

        with zstd.open(
            path,
            "rt",
            encoding="utf-8",
            newline="",
        ) as stream:
            reader = csv.DictReader(stream,)

            if not {"PuzzleId", "FEN", "Moves", "Rating", "Themes",}.issubset(reader.fieldnames or [],):
                raise ValueError("The puzzle dataset is missing required columns.",)

            should_parallelize = Path(path,).stat().st_size > 5 * 1024 * 1024

            context = ProcessPoolExecutor(
                max_workers=4,
                initializer=lower_import_priority,
            ) if should_parallelize else nullcontext()

            with context as executor:
                remaining_rows = islice(
                    reader,
                    skip_rows,
                    None,
                )

                validated_rows = executor.map(
                    validate_puzzle_row,
                    remaining_rows,
                    chunksize=500,
                    buffersize=4,
                ) if executor is not None else map(
                    validate_puzzle_row,
                    remaining_rows,
                )

                for validated_row in validated_rows:
                    if self.cancel_event.is_set():
                        raise InterruptedError("The puzzle import was cancelled.",)

                    report["processed_rows"] += 1

                    if validated_row is None:
                        report["rejected_rows"] += 1
                    else:
                        rows.append((*validated_row[:5], source, validated_row[5]),)
                        report["imported_rows"] += 1

                    if report["processed_rows"] % IMPORT_BATCH_ROWS == 0:
                        self.write_puzzles(
                            rows,
                            report,
                        )

                        rows.clear()

            report["status"] = "complete"

            self.write_puzzles(
                rows,
                report,
            )

        return report

    def write_puzzles(
        self,
        rows: list[tuple],
        report: dict,
    ) -> None:
        timestamp = datetime.now(UTC,).isoformat()

        with self.acquire_write():
            for row in rows:
                self.connection.execute(
                    "DELETE FROM puzzle_theme WHERE puzzle_id = ?",
                    (row[0],),
                )

            self.connection.executemany(
                """
                INSERT INTO puzzle (
                    id, fen, solution, rating, themes, source, game_url,
                    system_created_at, system_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    fen = excluded.fen, solution = excluded.solution,
                    rating = excluded.rating, themes = excluded.themes,
                    source = excluded.source, game_url = excluded.game_url,
                    system_updated_at = excluded.system_updated_at
            """,
                [(*row, timestamp, timestamp) for row in rows],
            )

            self.connection.executemany(
                "INSERT INTO puzzle_theme (puzzle_id, theme) VALUES (?, ?)",
                [(row[0], theme) for row in rows for theme in json.loads(row[4],)],
            )

            self.save_checkpoint(report,)

    def import_game(
        self,
        pgn: str,
        source: str,
        username: str | None = None,
        source_id: str | None = None,
        should_acquire_write: bool = True,
    ) -> str:
        if len(pgn.encode(),) > 1_048_576:
            raise ValueError("A corpus game exceeds one MiB.",)

        game = chess.pgn.read_game(io.StringIO(pgn,),)

        if game is None or game.errors or not game.board().is_valid():
            raise ValueError("The game cannot be parsed legally.",)

        if game.headers.get(
            "Variant",
            "Standard",
        ) not in ("Standard", "Chess"):
            raise ValueError("Only standard chess corpus games are supported.",)

        identifier = hashlib.sha256((source_id or source + "\n" + pgn).encode(),).hexdigest()

        board = game.board()

        root_fen = board.fen()

        positions = []

        moves = []

        for ply, move in enumerate(game.mainline_moves(),):
            positions.append((bytes.fromhex(identifier,), ply, hashlib.sha256(" ".join(board.fen().split()[:4],).encode(),).digest(), move.uci()),)
            moves.append(move.uci(),)
            board.push(move,)

        timestamp = datetime.now(UTC,).isoformat()

        headers = dict(game.headers,)

        with (self.acquire_write() if should_acquire_write else nullcontext()):
            self.connection.execute(
                """
                INSERT INTO game (
                    id, pgn, headers, root_fen, moves, username, source, played_at,
                    system_created_at, system_updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (id) DO UPDATE SET
                    pgn = excluded.pgn, headers = excluded.headers, root_fen = excluded.root_fen,
                    moves = excluded.moves, username = excluded.username, source = excluded.source,
                    played_at = excluded.played_at, system_updated_at = excluded.system_updated_at
            """,
                (identifier, pgn, json.dumps(headers,), root_fen, json.dumps(moves,), username, source, headers.get(
                    "UTCDate",
                    headers.get(
                        "Date",
                        "",
                    ),
                ), timestamp, timestamp),
            )

            self.connection.execute(
                "DELETE FROM game_position WHERE game_id = ?",
                (bytes.fromhex(identifier,),),
            )

            self.connection.executemany(
                "INSERT INTO game_position (game_id, ply, position_key, move_uci) VALUES (?, ?, ?, ?)",
                positions,
            )

            self.connection.execute(
                "DELETE FROM game_search WHERE id = ?",
                (identifier,),
            )

            self.connection.execute(
                "INSERT INTO game_search (id, text) VALUES (?, ?)",
                (identifier, " ".join(headers.values(),) + " " + " ".join((node.comment for node in game.mainline() if node.comment),)),
            )

        return identifier

    def import_games(
        self,
        path: str | Path,
        source: str,
        sha256: str = "",
        username: str | None = None,
    ) -> dict:
        identifier = "games:" + source
        checkpoint = self.get_checkpoint(identifier,)

        if checkpoint and checkpoint["sha256"] == sha256 and checkpoint["status"] == "complete":
            return checkpoint

        report = {"id": identifier, "sha256": sha256, "processed_rows": 0, "imported_rows": 0, "rejected_rows": 0, "status": "importing",}

        skip_rows = checkpoint["processed_rows"] if checkpoint and checkpoint["sha256"] == sha256 else 0

        if skip_rows:
            report.update({key: checkpoint[key] for key in ("processed_rows", "imported_rows", "rejected_rows")},)

        is_personal = str(path,).endswith(".json",)

        if is_personal:
            records = json.loads(Path(path,).read_text(),)["games"]

            games = ((record.get(
                "pgn",
                "",
            ), record.get("url",)) for record in records if record.get(
                "rules",
                "chess",
            ) == "chess")

            stream = None
        else:
            stream = zstd.open(
                path,
                "rt",
                encoding="utf-8",
            )

            def read_games():
                while game := chess.pgn.read_game(stream,):
                    if game.errors:
                        yield "", None
                    else:
                        yield game.accept(chess.pgn.StringExporter(
                            headers=True,
                            variations=True,
                            comments=True,
                        ),), None

            games = read_games()

        batch = []

        batch_bytes = 0

        try:
            for row_number, (pgn, source_id) in enumerate(games,):
                if row_number < skip_rows:
                    continue

                if self.cancel_event.is_set():
                    raise InterruptedError("The game import was cancelled.",)

                if batch and (len(batch,) >= 200 or batch_bytes + len(pgn.encode(),) > 8 * 1024 * 1024):
                    self.write_game_batch(
                        batch,
                        source,
                        username,
                        report,
                    )

                    batch.clear()

                    batch_bytes = 0

                batch.append((pgn, source_id),)

                batch_bytes += len(pgn.encode(),)

            self.write_game_batch(
                batch,
                source,
                username,
                report,
            )

            report["status"] = "complete"

            with self.acquire_write():
                self.save_checkpoint(report,)
        finally:
            if stream is not None:
                stream.close()

        return report

    def write_game_batch(
        self,
        batch: list,
        source: str,
        username: str | None,
        report: dict,
    ) -> None:
        with self.acquire_write():
            for pgn, source_id in batch:
                report["processed_rows"] += 1

                try:
                    self.import_game(
                        pgn,
                        source,
                        username,
                        source_id,
                        should_acquire_write=False,
                    )

                    report["imported_rows"] += 1
                except (ValueError, KeyError, TypeError):
                    report["rejected_rows"] += 1

            self.save_checkpoint(report,)

    def import_evaluations(
        self,
        path: str | Path,
        source: str,
        engine_name: str,
        score_perspective: str,
    ) -> dict:
        return import_evaluations(
            self,
            path,
            source,
            engine_name,
            score_perspective,
        )
