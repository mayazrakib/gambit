import sqlite3

import pytest

from gambit.infrastructure.storage import Store
from scripts.migrate_runtime import migrate_runtime

def test_migration_preserves_existing_destination_and_is_idempotent(tmp_path,) -> None:
    original = Store(str(tmp_path / "original.sqlite3",),)

    original.put(
        "profile",
        "learner",
        {"id": "learner", "rating": 1800,},
    )

    original.close()
    directory = tmp_path / "runtime"
    target = Store(str(directory / "gambit.sqlite3",),)

    target.put(
        "analysis",
        "new evidence",
        {"id": "new evidence", "value": 3,},
    )

    target.close()

    report = migrate_runtime(
        tmp_path / "original.sqlite3",
        directory,
    )

    assert report["added_records"] == 1

    assert migrate_runtime(
        tmp_path / "original.sqlite3",
        directory,
    )["added_records"] == 0

    restored = Store(str(directory / "gambit.sqlite3",),)

    try:
        assert restored.get(
            "profile",
            "learner",
        )["rating"] == 1800

        assert restored.get(
            "analysis",
            "new evidence",
        )["value"] == 3
    finally:
        restored.close()

def test_atomic_record_batch_rolls_back_on_database_failure(tmp_path,) -> None:
    store = Store(str(tmp_path / "records.sqlite3",),)
    store.connection.execute("CREATE TRIGGER reject_event BEFORE INSERT ON record WHEN new.collection = 'learning_event' BEGIN SELECT RAISE(ABORT, 'rejected'); END",)

    with pytest.raises(sqlite3.IntegrityError,):
        store.put_records_atomic([
            ("tutor_session", "session", {"id": "session",}),
            ("learning_event", "event", {"id": "event",}),
        ],)

    assert store.get(
        "tutor_session",
        "session",
    ) is None

    store.close()
