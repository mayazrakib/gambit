import argparse
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path

from gambit.configuration import load_configuration
from gambit.storage import Store

def restore_backup(
    source: str,
    destination: str,
) -> str:
    source_path = Path(source,).expanduser().resolve()
    destination_path = Path(destination,).expanduser().resolve()

    if not source_path.is_file():
        raise ValueError("The backup file does not exist.",)

    with closing(sqlite3.connect(
        source_path.as_uri() + "?mode=ro",
        uri=True,
    ),) as backup:
        if backup.execute("PRAGMA integrity_check",).fetchone()[0] != "ok":
            raise ValueError("The backup failed its integrity check.",)

        if backup.execute("SELECT count(*) FROM sqlite_master WHERE type = 'table' AND name = 'record'",).fetchone()[0] != 1:
            raise ValueError("The backup is not a Gambit database.",)

        destination_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with destination_path.open("xb",):
            destination_path.chmod(0o600,)

        try:
            with closing(sqlite3.connect(destination_path,),) as restored:
                backup.backup(restored,)
        except BaseException:
            destination_path.unlink(missing_ok=True,)

            raise

    return str(destination_path,)

def main() -> None:
    parser = argparse.ArgumentParser(description="Back up, restore, or prune Gambit analysis records.",)
    parser.add_argument(
        "operation",
        choices=("backup", "restore", "prune"),
    )
    parser.add_argument("--path",)
    parser.add_argument("--destination",)
    parser.add_argument(
        "--age-days",
        type=int,
        default=90,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
    )
    arguments = parser.parse_args()

    if arguments.operation == "restore":
        if not arguments.path or not arguments.destination:
            parser.error("Restore requires --path and a new --destination.",)

        print(json.dumps({
            "restored_path": restore_backup(
                arguments.path,
                arguments.destination,
            ),
        },),)

        return

    store = Store(load_configuration().database_path,)

    try:
        if arguments.operation == "backup":
            if not arguments.path:
                parser.error("Backup requires a new --path.",)

            report = {"backup_path": store.create_backup(arguments.path,),}
        else:
            if arguments.age_days < 1:
                parser.error("Retention must be at least one day.",)

            if arguments.apply and not arguments.path:
                parser.error("Applying retention requires --path for a recoverable backup.",)

            if arguments.apply:
                store.create_backup(arguments.path,)

            cutoff = (datetime.now(UTC,) - timedelta(days=arguments.age_days,)).isoformat()
            report = store.prune_analysis(
                cutoff,
                arguments.apply,
            )

        print(json.dumps(report,),)
    finally:
        store.close()

if __name__ == "__main__":
    main()
