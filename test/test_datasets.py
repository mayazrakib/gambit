import io
import json
import sqlite3
import threading
from compression import zstd
from pathlib import Path

import chess
import pytest

from gambit.infrastructure.corpus_store import CorpusStore
from gambit.infrastructure.data_capacity import RuntimeCapacity
from gambit.infrastructure.data_downloads import DatasetDownloads
from gambit.infrastructure.data_lock import acquire_file_lock

def test_runtime_capacity_serializes_reservations(tmp_path: Path,) -> None:
    first = RuntimeCapacity(
        tmp_path,
        maximum_bytes=2_100_000,
    )

    second = RuntimeCapacity(
        tmp_path,
        maximum_bytes=2_100_000,
    )

    reservation = first.reserve_bytes(800_000,)

    with pytest.raises(RuntimeError,):
        second.reserve_bytes(800_000,)

    with (tmp_path / "data").open("wb",) as stream:
        first.write_chunk(
            reservation,
            stream,
            b"x" * 800_000,
        )

    first.release_bytes(reservation,)

    assert first.get_status()["reserved_bytes"] == 0

    assert first.get_status()["used_bytes"] < 2_100_000

def test_runtime_capacity_recovers_dead_reservations(tmp_path: Path,) -> None:
    capacity = RuntimeCapacity(tmp_path,)
    capacity.write_reservations({"dead": {"pid": 999_999_999, "bytes": 19_000_000_000,},},)
    assert capacity.get_status()["reserved_bytes"] == 0

def test_file_lock_wait_can_be_cancelled(tmp_path: Path,) -> None:
    cancel_event = threading.Event()
    entered = threading.Event()
    cancelled = threading.Event()
    path = tmp_path / "shared.lock"

    def wait_for_lock():
        with path.open("a+b",) as stream:
            entered.set()

            try:
                with acquire_file_lock(
                    stream,
                    cancel_event,
                ):
                    pytest.fail("The held file lock must not be acquired.",)
            except InterruptedError:
                cancelled.set()

    with path.open("a+b",) as stream, acquire_file_lock(stream,):
        worker = threading.Thread(target=wait_for_lock,)
        worker.start()
        assert entered.wait(1,)
        cancel_event.set()
        worker.join(1,)
        assert cancelled.is_set()
        assert not worker.is_alive()

def test_database_capacity_rejects_transaction_before_mutation(tmp_path: Path,) -> None:
    capacity = RuntimeCapacity(
        tmp_path,
        maximum_bytes=2_000_000,
    )

    connection = sqlite3.connect(tmp_path / "test.sqlite3",)

    with pytest.raises(RuntimeError,):
        with capacity.database_write(connection,):
            connection.execute("CREATE TABLE forbidden (id INTEGER)",)

    assert connection.execute("SELECT name FROM sqlite_master",).fetchall() == []

    connection.close()

def test_database_capacity_bounds_batch_growth_and_rolls_back(tmp_path: Path,) -> None:
    capacity = RuntimeCapacity(
        tmp_path,
        maximum_bytes=4_000_000,
    )

    connection = sqlite3.connect(tmp_path / "test.sqlite3",)
    connection.execute("CREATE TABLE payload (id INTEGER PRIMARY KEY, content BLOB)",)
    connection.commit()

    with pytest.raises(sqlite3.DatabaseError,):
        with capacity.database_write(
            connection,
            reservation_bytes=512_000,
        ):
            connection.execute("INSERT INTO payload (content) VALUES (zeroblob(1000000))",)

    assert connection.execute("SELECT count(*) FROM payload",).fetchone()[0] == 0
    assert capacity.get_status()["used_bytes"] < 4_000_000
    connection.close()

def test_streamed_puzzles_apply_setup_and_resume(tmp_path: Path,) -> None:
    path = tmp_path / "puzzles.csv.zst"
    content = "PuzzleId,FEN,Moves,Rating,Themes,GameUrl\nvalid," + chess.STARTING_FEN + ",e2e4 e7e5,1800,opening,https://lichess.org/example\nbad,invalid,e2e4 e7e5,1800,tactics,\n"

    with zstd.open(
        path,
        "wt",
    ) as stream:
        stream.write(content,)

    corpus = CorpusStore(tmp_path,)

    try:
        report = corpus.import_puzzles(
            path,
            "source",
            "revision",
        )

        assert report["imported_rows"] == 1

        assert report["rejected_rows"] == 1

        puzzle = corpus.select_puzzle(
            ["opening",],
            1800,
        )

        board = chess.Board()

        board.push_uci("e2e4",)

        assert puzzle["fen"] == board.fen()

        assert puzzle["solution"] == ["e7e5",]

        assert corpus.select_puzzle(exclude_ids=["valid",],) is None

        assert corpus.import_puzzles(
            path,
            "source",
            "revision",
        )["imported_rows"] == 1

        assert corpus.get_status()["puzzles"] == 1
    finally:
        corpus.close()

def test_corpus_game_identity_search_and_history(tmp_path: Path,) -> None:
    corpus = CorpusStore(tmp_path,)

    try:
        pgn = '[Event "Personal lesson"]\n[Date "2026.10.01"]\n\n1. e4 e5 2. Nf3 Nc6 *'

        identifier = corpus.import_game(
            pgn,
            "source",
            "mayazrakib",
            "game-url",
        )

        assert corpus.import_game(
            pgn,
            "source",
            "mayazrakib",
            "game-url",
        ) == identifier

        game = corpus.get_game(identifier,)

        assert game["moves"] == ["e2e4", "e7e5", "g1f3", "b8c6",]
        assert corpus.find_position_games(chess.STARTING_FEN,)[0]["game_id"] == identifier

        assert len(corpus.list_games("mayazrakib",),) == 1

        assert corpus.search_material("Personal",)["games"][0]["id"] == identifier

        assert corpus.connection.execute("PRAGMA integrity_check",).fetchone()[0] == "ok"
    finally:
        corpus.close()

def test_imported_evaluations_preserve_provenance_and_history_limits(tmp_path: Path,) -> None:
    corpus = CorpusStore(tmp_path,)
    path = tmp_path / "evaluations.jsonl"
    record = {"fen": " ".join(chess.STARTING_FEN.split()[:4],), "evals": [{"depth": 20, "knodes": 100, "pvs": [{"cp": 20, "line": "e2e4 e7e5",},],},],}
    path.write_text(json.dumps(record,) + "\n",)

    try:
        report = corpus.import_evaluations(
            path,
            "attributed source",
            "Stockfish source version unknown",
            "white",
        )

        assert report["imported_rows"] == 1
        evidence = corpus.find_evaluations(chess.STARTING_FEN,)[0]
        assert evidence["score_perspective"] == "white"
        assert evidence["history_status"] == "incomplete history"
        assert evidence["evaluations"][0]["depth"] == 20

        with pytest.raises(ValueError,):
            corpus.import_evaluations(
                path,
                "source",
                "Stockfish",
                "",
            )
    finally:
        corpus.close()

class DownloadResponse(io.BytesIO,):
    def __init__(
        self,
        content: bytes,
        status: int = 200,
    ) -> None:
        super().__init__(content,)
        self.status = status
        self.headers = {"Content-Length": str(len(content,),), "ETag": "version",}

def test_download_checksum_failure_is_not_promoted(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.open_request",
        lambda *arguments, **options: DownloadResponse(b"content",),
    )

    downloads = DatasetDownloads(tmp_path,)

    source = {"key": "test", "filename": "test.rtbw", "kind": "syzygy", "url": "https://example.invalid/test", "sha256": "0" * 64,}

    with pytest.raises(
        RuntimeError,
        match="checksum",
    ):
        downloads.download_source(source,)

    assert not (tmp_path / "syzygy/test.rtbw").exists()

    assert downloads.capacity.get_status()["reserved_bytes"] == 0

    assert json.loads(downloads.manifest_path.read_text(),)["test"]["status"] == "incomplete"

def test_download_resume_restarts_when_server_ignores_range(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.open_request",
        lambda *arguments, **options: DownloadResponse(b"complete",),
    )

    downloads = DatasetDownloads(tmp_path,)

    (tmp_path / "downloads/test.part").write_bytes(b"old",)

    downloads.record_source(
        "test",
        {"etag": "version",},
    )

    report = downloads.download_source({"key": "test", "filename": "test", "kind": "puzzles", "url": "https://example.invalid/test",},)

    assert Path(report["path"],).read_bytes() == b"complete"

    assert report["bytes"] == 8

def test_download_promotes_complete_partial_after_restart(
    tmp_path: Path,
    monkeypatch,
) -> None:
    calls = []

    def open_response(
        url,
        headers=None,
        method="GET",
    ):
        calls.append(method,)

        return DownloadResponse(b"complete",)

    monkeypatch.setattr(
        "gambit.infrastructure.data_downloads.open_request",
        open_response,
    )

    downloads = DatasetDownloads(tmp_path,)
    (tmp_path / "downloads/test.part").write_bytes(b"complete",)

    downloads.record_source(
        "test",
        {"etag": "version",},
    )

    report = downloads.download_source({"key": "test", "filename": "test", "kind": "puzzles", "url": "https://example.invalid/test",},)
    assert calls == ["HEAD",]
    assert report["status"] == "complete"
