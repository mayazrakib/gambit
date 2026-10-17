import ctypes
import json
import os
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from gambit.infrastructure.data_lock import acquire_file_lock

MAX_RUNTIME_BYTES = 20_000_000_000

CAPACITY_MARGIN_BYTES = 1_048_576

class RuntimeCapacity:
    def __init__(
        self,
        directory: str | Path,
        maximum_bytes: int = MAX_RUNTIME_BYTES,
    ) -> None:
        self.directory = Path(directory,).resolve()

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.ledger_path = self.directory / "capacity.json"

        self.lock_path = self.directory / "capacity.lock"

        self.maximum_bytes = maximum_bytes

    @contextmanager
    def acquire_lock(self,):
        with self.lock_path.open("a+b",) as stream, acquire_file_lock(stream,):
            yield

    def read_reservations(self,) -> dict:
        reservations = json.loads(self.ledger_path.read_text(),) if self.ledger_path.exists() else {}
        recovered = {}

        for identifier, reservation in reservations.items():
            if isinstance(
                reservation,
                int,
            ):
                continue

            if os.name == "nt":
                process_handle = ctypes.windll.kernel32.OpenProcess(
                    0x1000,
                    False,
                    reservation["pid"],
                )

                if not process_handle:
                    continue

                ctypes.windll.kernel32.CloseHandle(process_handle,)
            else:
                try:
                    os.kill(
                        reservation["pid"],
                        0,
                    )
                except ProcessLookupError:
                    continue
                except PermissionError:
                    pass

            recovered[identifier] = reservation

        return recovered

    def count_reserved_bytes(
        self,
        reservations: dict,
    ) -> int:
        return sum((reservation["bytes"] for reservation in reservations.values()),)

    def write_reservations(
        self,
        reservations: dict,
    ) -> None:
        temporary_path = self.ledger_path.with_suffix(".next",)

        temporary_path.write_text(json.dumps(
            reservations,
            sort_keys=True,
        ),)

        os.replace(
            temporary_path,
            self.ledger_path,
        )

    def count_bytes(self,) -> int:
        byte_count = 0

        for path in self.directory.rglob("*",):
            try:
                if path.is_file():
                    byte_count += path.stat().st_size
            except FileNotFoundError:
                continue

        return byte_count

    def reserve_bytes(
        self,
        byte_count: int,
    ) -> str:
        if byte_count < 0:
            raise ValueError("Reserved bytes must be nonnegative.",)

        with self.acquire_lock():
            reservations = self.read_reservations()

            if self.count_bytes() + self.count_reserved_bytes(reservations,) + byte_count > self.maximum_bytes - CAPACITY_MARGIN_BYTES:
                raise RuntimeError("The repository runtime storage limit has been reached.",)

            identifier = uuid4().hex

            reservations[identifier] = {"bytes": byte_count, "pid": os.getpid(),}

            self.write_reservations(reservations,)

        return identifier

    def write_chunk(
        self,
        identifier: str,
        stream,
        content: bytes,
    ) -> None:
        with self.acquire_lock():
            reservations = self.read_reservations()
            remaining_bytes = reservations[identifier]["bytes"]

            additional_bytes = max(
                0,
                len(content,) - remaining_bytes,
            )

            if self.count_bytes() + self.count_reserved_bytes(reservations,) + additional_bytes > self.maximum_bytes - CAPACITY_MARGIN_BYTES:
                raise RuntimeError("The repository runtime storage limit has been reached.",)

            stream.write(content,)

            stream.flush()

            reservations[identifier]["bytes"] = max(
                0,
                remaining_bytes - len(content,),
            )

            self.write_reservations(reservations,)

    def release_bytes(
        self,
        identifier: str,
    ) -> None:
        with self.acquire_lock():
            reservations = self.read_reservations()

            reservations.pop(
                identifier,
                None,
            )

            self.write_reservations(reservations,)

    def get_status(self,) -> dict:
        with self.acquire_lock():
            return {"used_bytes": self.count_bytes(), "reserved_bytes": self.count_reserved_bytes(self.read_reservations(),), "limit_bytes": self.maximum_bytes,}

    @contextmanager
    def database_write(
        self,
        connection,
        reservation_bytes: int = 64 * 1024 * 1024,
    ):
        with self.acquire_lock():
            reservations = self.read_reservations()
            available_bytes = self.maximum_bytes - CAPACITY_MARGIN_BYTES - self.count_bytes() - self.count_reserved_bytes(reservations,)

            if available_bytes < reservation_bytes:
                raise RuntimeError("The repository runtime storage limit cannot accommodate a database transaction.",)

            page_count = connection.execute("PRAGMA page_count",).fetchone()[0]

            page_bytes = connection.execute("PRAGMA page_size",).fetchone()[0]

            maximum_pages = page_count + reservation_bytes // (3 * page_bytes)

            connection.execute(f"PRAGMA max_page_count = {maximum_pages}",)

            connection.execute("PRAGMA temp_store = MEMORY",)

            database_path = connection.execute("PRAGMA database_list",).fetchone()[2]
            database_paths = [Path(database_path + suffix,) for suffix in ("", "-wal", "-shm", "-journal")] if database_path else []

            def count_database_bytes():
                byte_count = 0

                for path in database_paths:
                    try:
                        byte_count += path.stat().st_size
                    except FileNotFoundError:
                        continue

                return byte_count

            starting_bytes = count_database_bytes()

            growth_limit_bytes = max(
                4096,
                reservation_bytes - min(
                    16 * 1024 * 1024,
                    reservation_bytes // 4,
                ),
            )

            def should_abort_growth():
                return int(count_database_bytes() - starting_bytes > growth_limit_bytes,)

            connection.set_progress_handler(
                should_abort_growth,
                1000,
            )

            try:
                with connection:
                    yield
            finally:
                connection.set_progress_handler(
                    None,
                    0,
                )

                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)",)
