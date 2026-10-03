import hashlib
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import chess.syzygy

from gambit.knowledge import probe_tablebase

@dataclass(frozen=True,)
class TablebaseDiagnostics:
    schema_version: int
    directories: list[str]
    missing_directories: list[str]
    wdl_files: int
    dtz_files: int
    unpaired_files: list[str]
    has_complete_pairs: bool
    caveat: str

class Tablebases:
    def __init__(
        self,
        directory: str,
    ) -> None:
        self.directories = [str(Path(path,).expanduser().resolve(),) for path in directory.split(os.pathsep,) if path]
        self.lock = threading.RLock()
        self.tables: chess.syzygy.Tablebase | None = None

    def close(self,) -> None:
        with self.lock:
            if self.tables is not None:
                self.tables.close()
                self.tables = None

    def probe(
        self,
        fen: str,
    ) -> dict:
        if not self.directories:
            return {"schema_version": 1, "status": "unavailable", "reason": "No Syzygy directory is configured.",}

        with self.lock:
            if self.tables is None:
                tables = chess.syzygy.Tablebase(max_fds=64,)

                try:
                    for directory in self.directories:
                        tables.add_directory(directory,)
                except OSError:
                    tables.close()

                    return {"schema_version": 1, "status": "unavailable", "reason": "A configured Syzygy directory is unavailable. Run tablebase diagnostics.",}

                self.tables = tables

            report = probe_tablebase(
                fen,
                self.directories[0],
                self.tables,
            )

            return {"schema_version": 1, "evidence_status": "exact tablebase" if report["status"] == "available" else "unavailable", **report,}

    def get_diagnostics(self,) -> TablebaseDiagnostics:
        wdl = set()
        dtz = set()
        missing = []

        for directory in self.directories:
            path = Path(directory,)

            if not path.is_dir():
                missing.append(directory,)

                continue

            wdl.update((entry.stem for entry in path.glob("*.rtbw",)),)
            dtz.update((entry.stem for entry in path.glob("*.rtbz",)),)

        return TablebaseDiagnostics(
            1,
            self.directories,
            missing,
            len(wdl,),
            len(dtz,),
            sorted(wdl ^ dtz,)[:1000],
            bool(wdl,) and wdl == dtz and not missing,
            "Matching file pairs do not prove complete material coverage or file integrity. Captures and promotions can require additional tables. Unpaired names are limited to 1000 entries.",
        )

    def verify_checksums(
        self,
        manifest_path: str,
    ) -> dict:
        manifest = Path(manifest_path,).expanduser()

        if manifest.stat().st_size > 8 * 1024 * 1024:
            raise ValueError("A checksum manifest must not exceed 8 MiB.",)

        verified = 0
        failures = []

        for line in manifest.read_text().splitlines():
            if not line.strip():
                continue

            digest, filename = line.split(maxsplit=1,)
            filename = filename.lstrip("*",)

            if len(digest,) != 64 or any((character not in "0123456789abcdefABCDEF" for character in digest),) or Path(filename,).name != filename or Path(filename,).suffix not in (".rtbw", ".rtbz"):
                raise ValueError("Use a SHA-256 manifest with plain tablebase filenames.",)

            matches = [Path(directory,) / filename for directory in self.directories if (Path(directory,) / filename).is_file()]

            if not matches:
                failures.append(filename,)

                continue

            for path in matches:
                with path.open("rb",) as stream:
                    actual = hashlib.file_digest(
                        stream,
                        "sha256",
                    ).hexdigest()

                if actual != digest.lower():
                    failures.append(str(path,),)
                else:
                    verified += 1

        if verified == 0 and not failures:
            raise ValueError("The checksum manifest is empty.",)

        return {"schema_version": 1, "verified_files": verified, "failures": failures, "is_valid": not failures,}
