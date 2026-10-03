import json
import sqlite3
import threading
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

Collection = Literal[
    "analysis",
    "attempt",
    "job",
    "lesson",
    "opening",
    "profile",
    "puzzle",
    "repertoire",
    "session",
    "study",
    "checkpoint",
    "concept",
    "teaching",
    "opening_plan",
    "observation",
]
COLLECTIONS = {
    "analysis",
    "attempt",
    "job",
    "lesson",
    "opening",
    "profile",
    "puzzle",
    "repertoire",
    "session",
    "study",
    "checkpoint",
    "concept",
    "teaching",
    "opening_plan",
    "observation",
}

class Store:
    def __init__(
        self,
        database_path: str,
    ) -> None:
        path = Path(database_path,).expanduser()

        if database_path != ":memory:":
            path.parent.mkdir(
                parents=True,
                exist_ok=True,
            )

        self.lock = threading.RLock()
        self.connection = sqlite3.connect(
            str(path,),
            check_same_thread=False,
        )
        self.connection.execute("PRAGMA journal_mode = WAL",)
        self.connection.execute("PRAGMA busy_timeout = 5000",)
        self.connection.execute("""
            CREATE TABLE IF NOT EXISTS record (
                id TEXT NOT NULL,

                collection TEXT NOT NULL,
                payload TEXT NOT NULL CHECK (json_valid(payload)),

                system_created_at TEXT NOT NULL,
                system_updated_at TEXT NOT NULL,

                PRIMARY KEY (collection, id)
            )
        """,)
        self.connection.execute("""
            CREATE INDEX IF NOT EXISTS record_position
            ON record (collection, json_extract(payload, '$.position_key'))
        """,)
        self.connection.commit()

    def close(self,) -> None:
        with self.lock:
            self.connection.close()

    def put(
        self,
        collection: Collection,
        record_id: str,
        payload: dict,
        *,
        is_immutable: bool = False,
    ) -> dict:
        if collection not in COLLECTIONS or not record_id or len(record_id,) > 256:
            raise ValueError("Invalid record collection or identifier.",)

        timestamp = datetime.now(UTC,).isoformat()
        serialized = json.dumps(
            payload,
            allow_nan=False,
            sort_keys=True,
        )

        with self.lock, self.connection:
            existing = self.get(
                collection,
                record_id,
            )

            if is_immutable and existing is not None:
                if existing != json.loads(serialized,):
                    raise ValueError("An immutable record cannot be replaced.",)

                return existing

            self.connection.execute(
                """
                    INSERT INTO record (id, collection, payload, system_created_at, system_updated_at)
                    VALUES (?, ?, ?, ?, ?)

                    ON CONFLICT (collection, id) DO UPDATE SET
                        payload = excluded.payload,
                        system_updated_at = excluded.system_updated_at
                """,
                (record_id, collection, serialized, timestamp, timestamp),
            )

        return payload

    def get(
        self,
        collection: Collection,
        record_id: str,
    ) -> dict | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT payload FROM record WHERE collection = ? AND id = ?",
                (collection, record_id),
            ).fetchone()

        return json.loads(row[0],) if row else None

    def put_many(
        self,
        collection: Collection,
        records: list[dict],
    ) -> None:
        if collection not in COLLECTIONS:
            raise ValueError("Invalid record collection.",)

        timestamp = datetime.now(UTC,).isoformat()
        rows = []

        for record in records:
            record_id = record.get("id",)

            if not isinstance(
                record_id,
                str,
            ) or not record_id or len(record_id,) > 256:
                raise ValueError("Invalid record identifier.",)

            rows.append((record_id, collection, json.dumps(
                record,
                allow_nan=False,
                sort_keys=True,
            ), timestamp, timestamp),)

        with self.lock, self.connection:
            self.connection.executemany(
                """
                    INSERT INTO record (id, collection, payload, system_created_at, system_updated_at)
                    VALUES (?, ?, ?, ?, ?)

                    ON CONFLICT (collection, id) DO UPDATE SET
                        payload = excluded.payload,
                        system_updated_at = excluded.system_updated_at
                """,
                rows,
            )

    def list_records(
        self,
        collection: Collection,
        limit: int = 100,
        offset: int = 0,
        position_key: str | None = None,
    ) -> list[dict]:
        if not 1 <= limit <= 1000 or offset < 0:
            raise ValueError("Record pagination is outside the supported limits.",)

        predicate = "collection = ?"
        parameters: list = [collection,]

        if position_key is not None:
            predicate += " AND json_extract(payload, '$.position_key') = ?"
            parameters.append(position_key,)

        parameters.extend([limit, offset,],)

        with self.lock:
            rows = self.connection.execute(
                f"SELECT payload FROM record WHERE {predicate} ORDER BY id LIMIT ? OFFSET ?",
                parameters,
            ).fetchall()

        return [json.loads(row[0],) for row in rows]

    def count_records(
        self,
        collection: Collection,
    ) -> int:
        with self.lock:
            row = self.connection.execute(
                "SELECT count(*) FROM record WHERE collection = ?",
                (collection,),
            ).fetchone()

        return row[0]

    def create_backup(
        self,
        destination: str,
    ) -> str:
        backup_path = Path(destination,).expanduser().resolve()
        backup_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with backup_path.open("xb",):
            backup_path.chmod(0o600,)

        try:
            with self.lock, closing(sqlite3.connect(backup_path,),) as target:
                self.connection.backup(target,)
                check = target.execute("PRAGMA integrity_check",).fetchone()[0]

                if check != "ok":
                    raise RuntimeError("The database backup failed its integrity check.",)
        except BaseException:
            backup_path.unlink(missing_ok=True,)

            raise

        return str(backup_path,)

    def prune_analysis(
        self,
        cutoff: str,
        should_apply: bool = False,
    ) -> dict:
        datetime.fromisoformat(cutoff,)

        with self.lock, self.connection:
            records = self.connection.execute(
                """
                    SELECT candidate.id FROM record AS candidate
                    WHERE candidate.collection = 'analysis'
                        AND candidate.system_updated_at < ?
                        AND NOT EXISTS (
                            SELECT 1 FROM record AS reference
                            WHERE reference.collection != 'analysis'
                                AND instr(reference.payload, candidate.id) > 0
                        )

                    ORDER BY candidate.id
                    LIMIT 1000
                """,
                (cutoff,),
            ).fetchall()
            checkpoints = self.connection.execute(
                """
                    SELECT checkpoint.id FROM record AS checkpoint
                    JOIN record AS job
                        ON job.collection = 'job'
                        AND job.id = json_extract(checkpoint.payload, '$.job_id')

                    WHERE checkpoint.collection = 'checkpoint'
                        AND checkpoint.system_updated_at < ?
                        AND json_extract(job.payload, '$.status') = 'completed'

                    ORDER BY checkpoint.id
                    LIMIT 1000
                """,
                (cutoff,),
            ).fetchall()

            if should_apply:
                self.connection.executemany(
                    "DELETE FROM record WHERE collection = 'analysis' AND id = ?",
                    records,
                )
                self.connection.executemany(
                    "DELETE FROM record WHERE collection = 'checkpoint' AND id = ?",
                    checkpoints,
                )

        return {"schema_version": 1, "candidate_count": len(records,), "deleted_count": len(records,) if should_apply else 0, "checkpoint_candidates": len(checkpoints,), "deleted_checkpoints": len(checkpoints,) if should_apply else 0, "batch_limit": 1000,}
