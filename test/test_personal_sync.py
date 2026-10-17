import io
import json
import threading
import urllib.error
from datetime import UTC, datetime
from pathlib import Path

from gambit.infrastructure.data_downloads import DatasetDownloads, discover_personal_sources
from gambit.infrastructure.data_service import DatasetService

class Response(io.BytesIO,):
    def __init__(
        self,
        payload,
        etag="version",
    ):
        super().__init__(json.dumps(payload,).encode(),)
        self.headers = {"ETag": etag, "Last-Modified": "Thu, 01 Oct 2026 00:00:00 GMT",}

class FixedDate(datetime,):
    @classmethod
    def now(
        cls,
        timezone=None,
    ):
        return datetime(
            2026,
            10,
            18,
            tzinfo=UTC,
        )

def test_initial_archive_and_incremental_sync_use_conditional_serial_requests(
    tmp_path,
    monkeypatch,
):
    prefix = "https://api.chess.com/pub/player/mayazrakib/games/"
    months = [prefix + month for month in ("2026/08", "2026/09", "2026/10")]
    calls = []
    is_syncing_again = False

    def open_response(
        url,
        headers=None,
        method="GET",
    ):
        assert method == "GET"
        calls.append((url, headers or {}),)

        if is_syncing_again:
            assert headers["If-None-Match"] == "version"
            assert headers["If-Modified-Since"]

            raise urllib.error.HTTPError(
                url,
                304,
                "unchanged",
                {},
                io.BytesIO(),
            )

        return Response({"archives": months,} if url.endswith("archives",) else {"games": [],},)

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.open_request",
        open_response,
    )

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.datetime",
        FixedDate,
    )

    first = DatasetDownloads(tmp_path,).sync_personal_sources()
    assert first["complete"] == 3
    assert [url for url, headers in calls] == [prefix + "archives", *months,]
    calls.clear()
    is_syncing_again = True
    second = DatasetDownloads(tmp_path,).sync_personal_sources()
    assert second["complete"] == 3
    assert second["incomplete"] == []
    assert [url for url, headers in calls] == [prefix + "archives", *months[1:],]
    assert json.loads((tmp_path / "downloads/mayazrakib-2026-08.json").read_text(),) == {"games": [],}

def test_month_boundary_refreshes_december_and_january(
    tmp_path,
    monkeypatch,
):
    class January(datetime,):
        @classmethod
        def now(
            cls,
            timezone=None,
        ):
            return datetime(
                2027,
                1,
                1,
                tzinfo=UTC,
            )

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.datetime",
        January,
    )

    sources = discover_personal_sources(
        "MayazRakib",
        {
            "archives": [
                "https://api.chess.com/pub/player/mayazrakib/games/2026/11",
                "https://api.chess.com/pub/player/mayazrakib/games/2026/12",
                "https://api.chess.com/pub/player/mayazrakib/games/2027/01",
            ],
        },
    )

    calls = []
    downloads = DatasetDownloads(tmp_path,)
    downloads.download_with_retries = lambda source, should_refresh: calls.append(should_refresh,) or {"status": "complete",}

    downloads.sync_personal_months(
        sources,
        False,
    )

    assert calls == [False, True, True,]

def test_personal_import_retains_raw_metadata_and_deduplicates_updated_games(
    tmp_path,
    monkeypatch,
):
    prefix = "https://api.chess.com/pub/player/mayazrakib/games/"
    game_url = "https://www.chess.com/game/live/123"
    pgn = '[Event "Personal"]\n[White "mayazrakib"]\n[Black "opponent"]\n\n1. e4 e5 *'
    records = [{"url": game_url, "pgn": pgn, "rules": "chess", "time_class": "rapid", "white": {"rating": 1700,}, "end_time": 1790812800,},]

    def open_response(
        url,
        headers=None,
        method="GET",
    ):
        return Response(
            {"archives": [prefix + "2026/10",],} if url.endswith("archives",) else {"games": records,},
            str(len(records,),),
        )

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.open_request",
        open_response,
    )

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.datetime",
        FixedDate,
    )

    service = DatasetService(tmp_path,)

    try:
        service.sync_games()
        game = service.corpus.list_games("mayazrakib",)[0]
        identifier = game["id"]
        assert game["moves"] == ["e2e4", "e7e5",]

        records[0]["pgn"] = pgn.replace(
            "e5",
            "e5 {Updated annotation}",
        )

        records.append({"url": "https://www.chess.com/game/live/124", "pgn": pgn, "rules": "chess",},)
        service.sync_games()
        assert len(service.corpus.list_games("mayazrakib",),) == 2
        assert "Updated annotation" in service.corpus.get_game(identifier,)["pgn"]
        payload = json.loads((tmp_path / "downloads/mayazrakib-2026-10.json").read_text(),)
        assert payload["games"][0]["white"]["rating"] == 1700
        assert payload["games"][0]["time_class"] == "rapid"
        assert service.corpus.get_status()["games"] == 2
    finally:
        service.close()

def test_personal_sync_retries_rate_limits_and_preserves_existing_archive_on_failure(
    tmp_path,
    monkeypatch,
):
    source = discover_personal_sources(
        "mayazrakib",
        {"archives": ["https://api.chess.com/pub/player/mayazrakib/games/2026/10",],},
    )[0]

    downloads = DatasetDownloads(tmp_path,)
    waits = []
    calls = 0

    def open_response(
        url,
        headers=None,
        method="GET",
    ):
        nonlocal calls
        calls += 1

        if calls == 1:
            raise urllib.error.HTTPError(
                url,
                429,
                "limited",
                {"Retry-After": "3",},
                io.BytesIO(),
            )

        return Response({"games": [],},)

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.open_request",
        open_response,
    )

    monkeypatch.setattr(
        downloads.cancel_event,
        "wait",
        waits.append,
    )

    report = downloads.download_with_retries(
        source,
        True,
    )

    assert waits == [3,]
    assert report["status"] == "complete"

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.open_request",
        lambda *arguments, **options: Response({"invalid": True,},),
    )

    try:
        downloads.download_source(
            source,
            True,
        )
    except ValueError:
        pass
    else:
        raise AssertionError("An invalid archive must be rejected.",)

    assert json.loads(Path(report["path"],).read_text(),) == {"games": [],}
    assert downloads.manifest[source["key"]]["sha256"] == report["sha256"]

def test_game_only_mcp_sync_uses_personal_service_without_bulk_downloads():
    from types import SimpleNamespace

    from gambit.server.dataset_tools import DatasetJobs, register_dataset_tools

    calls = []

    service = SimpleNamespace(
        cancel_event=threading.Event(),
        sync_games=lambda username, should_refresh: calls.append((username, should_refresh),) or {"imports": [],},
    )

    runtime = SimpleNamespace(get_datasets=lambda: service,)
    runtime.data_jobs = DatasetJobs(runtime,)
    registered = {}

    class Server:
        def tool(
            self,
            **options,
        ):
            def register(function,):
                registered[function.__name__] = function

                return function

            return register

    try:
        register_dataset_tools(
            Server(),
            SimpleNamespace(get_runtime=lambda: runtime,),
        )

        registered["manage_chess_data"](action="sync_games",)
        runtime.data_jobs.future.result(timeout=5,)
        assert calls == [("mayazrakib", False),]
        assert runtime.data_jobs.get_status()["job"]["status"] == "completed"
    finally:
        runtime.data_jobs.close()
