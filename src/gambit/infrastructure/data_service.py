import json
import threading
from pathlib import Path

from gambit.infrastructure.corpus_store import CorpusStore
from gambit.infrastructure.data_downloads import DatasetDownloads
from gambit.infrastructure.data_lock import acquire_file_lock

class DatasetService:
    def __init__(
        self,
        directory: str | Path,
    ) -> None:
        self.directory = Path(directory,).resolve()
        self.corpus = CorpusStore(self.directory,)
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.corpus.cancel_event = self.cancel_event

    def close(self,) -> None:
        self.corpus.close()

    def get_status(self,) -> dict:
        manifest_path = self.directory / "datasets.json"
        sources = json.loads(manifest_path.read_text(),) if manifest_path.exists() else {}
        summary = {}

        for source in sources.values():
            kind = source["kind"]

            entry = summary.setdefault(
                kind,
                {"complete": 0, "incomplete": 0, "bytes": 0,},
            )

            entry["complete" if source["status"] == "complete" else "incomplete"] += 1

            entry["bytes"] += source.get(
                "bytes",
                0,
            )

        failures = [{"key": source["key"], "error": source.get("error",),} for source in sources.values() if source["status"] == "incomplete"]

        return {"schema_version": 1, "datasets": summary, "failures": failures[:20], "corpus": self.corpus.get_status(),}

    def cancel_data(self,) -> dict:
        self.cancel_event.set()

        return {"status": "cancellation requested",}

    def search_material(
        self,
        query: str = "",
        kind: str | None = None,
        limit: int = 20,
    ) -> dict:
        result = self.corpus.search_material(
            query,
            kind,
            limit,
        )

        return {"puzzles": [{key: puzzle[key] for key in ("id", "fen", "rating", "themes", "source", "game_url")} for puzzle in result["puzzles"]], "games": [{"id": game["id"], "headers": game["headers"], "source": game["source"], "license": game["license"], "move_count": len(game["moves"],),} for game in result["games"]],}

    def import_sources(
        self,
        username: str = "mayazrakib",
        kinds: list[str] | None = None,
    ) -> dict:
        manifest_path = self.directory / "datasets.json"

        if not manifest_path.is_file():
            return {"imports": [], "reason": "No downloaded dataset manifest is available.",}

        reports = []

        with self.lock, (self.directory / "import.lock").open("a+b",) as lock_stream, acquire_file_lock(
            lock_stream,
            self.cancel_event,
        ):
            sources = json.loads(manifest_path.read_text(),)

            ordered_sources = sorted(
                sources.values(),
                key=lambda source: ({"personal": 0, "puzzles": 1, "broadcast": 2, "syzygy": 3,}[source["kind"]], source["key"]),
            )

            for source in ordered_sources:
                if self.cancel_event.is_set():
                    raise InterruptedError("The data import was cancelled.",)

                if source["status"] != "complete" or kinds is not None and source["kind"] not in kinds:
                    continue

                if source["kind"] == "syzygy" or source.get("is_metadata",):
                    continue

                if source["kind"] == "personal" and not source["key"].startswith(f"personal-{username.lower()}-",):
                    continue

                if source["kind"] == "puzzles":
                    report = self.corpus.import_puzzles(
                        source["path"],
                        source["url"],
                        source["sha256"],
                    )
                else:
                    report = self.corpus.import_games(
                        source["path"],
                        source["url"],
                        source["sha256"],
                        username if source["kind"] == "personal" else None,
                    )

                reports.append(report,)

        return {"imports": reports, "corpus": self.corpus.get_status(),}

    def sync_data(
        self,
        username: str = "mayazrakib",
        should_refresh: bool = False,
    ) -> dict:
        downloads = DatasetDownloads(
            self.directory,
            self.cancel_event,
        ).sync_sources(
            username,
            should_refresh,
        )

        imports = self.import_sources(username,)

        return {"downloads": downloads, "imports": imports,}

    def sync_games(
        self,
        username: str = "mayazrakib",
        should_refresh: bool = False,
    ) -> dict:
        downloads = DatasetDownloads(
            self.directory,
            self.cancel_event,
        ).sync_personal_sources(
            username,
            should_refresh,
        )

        imports = self.import_sources(
            username.lower(),
            ["personal",],
        )

        return {"downloads": downloads, "imports": imports,}
