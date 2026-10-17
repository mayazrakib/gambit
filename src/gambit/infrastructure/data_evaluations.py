import json
from compression import zstd
from datetime import UTC, datetime
from pathlib import Path

import chess

def import_evaluations(
    corpus,
    path: str | Path,
    source: str,
    engine_name: str,
    score_perspective: str,
) -> dict:
    if not source.strip() or not engine_name.strip() or score_perspective not in ("white", "side to move"):
        raise ValueError("Evaluation imports require attribution, an engine name, and an explicit score perspective.",)

    with corpus.acquire_write():
        corpus.connection.execute("""
            CREATE TABLE IF NOT EXISTS imported_evaluation (
                id TEXT NOT NULL,
                source TEXT NOT NULL,
                fen TEXT NOT NULL,
                engine_name TEXT NOT NULL,
                score_perspective TEXT NOT NULL,
                evaluations TEXT NOT NULL,
                system_created_at TEXT NOT NULL,
                system_updated_at TEXT NOT NULL,
                PRIMARY KEY (id, source)
            ) WITHOUT ROWID
        """,)

    report = {"imported_rows": 0, "rejected_rows": 0, "source": source, "history_status": "incomplete history",}
    opener = zstd.open if str(path,).endswith(".zst",) else open
    batch = []
    batch_bytes = 0

    with opener(
        path,
        "rt",
        encoding="utf-8",
    ) as stream:
        for line in stream:
            if corpus.cancel_event.is_set():
                raise InterruptedError("The evaluation import was cancelled.",)

            if len(line.encode(),) > 1_048_576:
                raise ValueError("An imported evaluation line exceeds one MiB.",)

            try:
                record = json.loads(line,)
                board = chess.Board(record["fen"],)

                if not board.is_valid() or not isinstance(
                    record["evals"],
                    list,
                ):
                    raise ValueError("An imported evaluation is invalid.",)

                for evaluation in record["evals"]:
                    if not isinstance(
                        evaluation.get("depth",),
                        int,
                    ) or not isinstance(
                        evaluation.get("pvs",),
                        list,
                    ):
                        raise ValueError("An imported evaluation is missing search evidence.",)

                    for variation in evaluation["pvs"]:
                        if not isinstance(
                            variation.get(
                                "cp",
                                variation.get("mate",),
                            ),
                            int,
                        ):
                            raise ValueError("An imported evaluation score is invalid.",)

                        branch = board.copy()

                        for move in variation["line"].split():
                            branch.push_uci(move,)

                key = " ".join(board.fen().split()[:4],)

                batch.append((key, source, record["fen"], engine_name, score_perspective, json.dumps(
                    record["evals"],
                    allow_nan=False,
                )),)

                batch_bytes += len(line.encode(),)
                report["imported_rows"] += 1
            except (ValueError, TypeError, KeyError):
                report["rejected_rows"] += 1

            if len(batch,) >= 100 or batch_bytes >= 8 * 1024 * 1024:
                write_evaluations(
                    corpus,
                    batch,
                )

                batch.clear()
                batch_bytes = 0

        write_evaluations(
            corpus,
            batch,
        )

    return report

def write_evaluations(
    corpus,
    rows: list,
) -> None:
    timestamp = datetime.now(UTC,).isoformat()

    with corpus.acquire_write():
        corpus.connection.executemany(
            """
            INSERT INTO imported_evaluation (
                id, source, fen, engine_name, score_perspective, evaluations,
                system_created_at, system_updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (id, source) DO UPDATE SET
                fen = excluded.fen, engine_name = excluded.engine_name,
                score_perspective = excluded.score_perspective,
                evaluations = excluded.evaluations,
                system_updated_at = excluded.system_updated_at
        """,
            [(*row, timestamp, timestamp) for row in rows],
        )

def find_evaluations(
    corpus,
    fen: str,
    limit: int = 3,
) -> list[dict]:
    if not 1 <= limit <= 100:
        raise ValueError("Return between one and 100 imported evaluations.",)

    board = chess.Board(fen,)
    key = " ".join(board.fen().split()[:4],)

    with corpus.lock:
        has_table = corpus.connection.execute("SELECT name FROM sqlite_master WHERE type = 'table' AND name = 'imported_evaluation'",).fetchone()

        if not has_table:
            return []

        rows = corpus.connection.execute(
            """
            SELECT source, fen, engine_name, score_perspective, evaluations
            FROM imported_evaluation WHERE id = ? ORDER BY source LIMIT ?
        """,
            (key, limit),
        ).fetchall()

    return [{"source": row["source"], "fen": row["fen"], "engine_name": row["engine_name"], "score_perspective": row["score_perspective"], "evaluations": json.loads(row["evaluations"],), "history_status": "incomplete history", "evidence_status": "imported engine analysis",} for row in rows]
