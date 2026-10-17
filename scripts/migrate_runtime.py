import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from gambit.infrastructure.configuration import DEFAULT_RUNTIME_DIRECTORY
from gambit.infrastructure.data_capacity import RuntimeCapacity
from gambit.infrastructure.storage import Store

def migrate_runtime(
    source: Path,
    directory: Path,
) -> dict:
    source = source.expanduser().resolve()
    directory = directory.expanduser().resolve()
    destination = directory / "gambit.sqlite3"

    if source == destination or not source.is_file():
        return {"status": "unchanged", "reason": "The legacy database is absent or already selected.",}

    capacity = RuntimeCapacity(directory,)

    reservation = capacity.reserve_bytes(max(
        1_048_576,
        source.stat().st_size * 4,
    ),)

    stamp = datetime.now(UTC,).strftime("%Y%m%dT%H%M%S%fZ",)
    backup = directory / "backups" / f"gambit-{stamp}.sqlite3"
    original = Store(str(source,),)
    target = None

    try:
        original.create_backup(str(backup,),)

        target = Store(
            str(destination,),
            str(directory,),
        )

        with original.lock:
            rows = original.connection.execute("SELECT collection, id, payload FROM record ORDER BY collection, id",).fetchall()

        pending = []

        for collection, identifier, serialized in rows:
            payload = json.loads(serialized,)

            existing = target.get(
                collection,
                identifier,
            )

            if existing is not None and existing != payload:
                raise ValueError(f"The destination contains a conflicting {collection} record: {identifier}.",)

            if existing is None:
                pending.append((collection, identifier, payload),)

        target.put_records_atomic(pending,)

        for collection, identifier, serialized in rows:
            if target.get(
                collection,
                identifier,
            ) != json.loads(serialized,):
                raise RuntimeError("Database migration verification failed.",)

        with target.lock:
            if target.connection.execute("PRAGMA integrity_check",).fetchone()[0] != "ok":
                raise RuntimeError("The migrated database failed its integrity check.",)

        return {"status": "verified", "records": len(rows,), "added_records": len(pending,), "backup": str(backup,), "database_path": str(destination,),}
    finally:
        original.close()

        if target is not None:
            target.close()

        capacity.release_bytes(reservation,)

def main() -> None:
    parser = argparse.ArgumentParser(description="Back up and merge the legacy Gambit state into repository-local storage.",)

    parser.add_argument(
        "--source",
        type=Path,
        default=Path("~/.local/share/gambit/gambit.sqlite3",),
    )

    parser.add_argument(
        "--directory",
        type=Path,
        default=Path(DEFAULT_RUNTIME_DIRECTORY,),
    )

    arguments = parser.parse_args()

    print(json.dumps(
        migrate_runtime(
            arguments.source,
            arguments.directory,
        ),
        indent=4,
    ),)

if __name__ == "__main__":
    sys.exit(main(),)
