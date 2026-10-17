import hashlib
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

from gambit.infrastructure.corpus_imports import CorpusImports
from gambit.infrastructure.corpus_queries import CorpusQueries
from gambit.infrastructure.data_capacity import RuntimeCapacity

class CorpusStore(
    CorpusImports,
    CorpusQueries,
):
    def __init__(
        self,
        directory: str | Path,
    ) -> None:
        self.directory = Path(directory,).resolve()

        self.directory.mkdir(
            parents=True,
            exist_ok=True,
        )

        self.path = self.directory / "corpus.sqlite3"

        self.capacity = RuntimeCapacity(self.directory,)

        self.lock = threading.RLock()

        self.cancel_event = threading.Event()

        self.connection = sqlite3.connect(
            self.path,
            check_same_thread=False,
            timeout=30,
        )

        self.connection.row_factory = sqlite3.Row

        with self.capacity.database_write(self.connection,):
            self.connection.execute("PRAGMA journal_mode = WAL",)
            self.connection.execute("PRAGMA wal_autocheckpoint = 1000",)
            self.connection.execute("PRAGMA temp_store = MEMORY",)

            self.connection.executescript("""
                CREATE TABLE IF NOT EXISTS puzzle (
                    id TEXT PRIMARY KEY,
                    fen TEXT NOT NULL,
                    solution TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    themes TEXT NOT NULL,
                    source TEXT NOT NULL,
                    game_url TEXT NOT NULL,
                    system_created_at TEXT NOT NULL,
                    system_updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS puzzle_rating ON puzzle (rating, id);
                CREATE TABLE IF NOT EXISTS puzzle_theme (
                    puzzle_id TEXT NOT NULL,
                    theme TEXT NOT NULL,
                    PRIMARY KEY (theme, puzzle_id)
                ) WITHOUT ROWID;
                CREATE INDEX IF NOT EXISTS puzzle_theme_puzzle ON puzzle_theme (puzzle_id);
                CREATE TABLE IF NOT EXISTS game (
                    id TEXT PRIMARY KEY,
                    pgn TEXT NOT NULL,
                    headers TEXT NOT NULL,
                    root_fen TEXT NOT NULL,
                    moves TEXT NOT NULL,
                    username TEXT,
                    source TEXT NOT NULL,
                    played_at TEXT NOT NULL,
                    system_created_at TEXT NOT NULL,
                    system_updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS game_username_date ON game (username, played_at DESC, id);
                CREATE TABLE IF NOT EXISTS game_position (
                    game_id BLOB NOT NULL,
                    ply INTEGER NOT NULL,
                    position_key BLOB NOT NULL,
                    move_uci TEXT NOT NULL,
                    PRIMARY KEY (game_id, ply)
                ) WITHOUT ROWID;
                CREATE INDEX IF NOT EXISTS game_position_key ON game_position (position_key, game_id);
                CREATE VIRTUAL TABLE IF NOT EXISTS game_search USING fts5(id UNINDEXED, text);
                CREATE TABLE IF NOT EXISTS import_checkpoint (
                    id TEXT PRIMARY KEY,
                    sha256 TEXT NOT NULL,
                    processed_rows INTEGER NOT NULL,
                    imported_rows INTEGER NOT NULL,
                    rejected_rows INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    system_created_at TEXT NOT NULL,
                    system_updated_at TEXT NOT NULL
                );
            """,)

        if self.connection.execute("PRAGMA user_version",).fetchone()[0] == 0:
            with self.acquire_write():
                cursor = self.connection.execute("SELECT game_id, ply, position_key, move_uci FROM game_position WHERE typeof(game_id) = 'text'",)

                while rows := cursor.fetchmany(2000,):
                    self.connection.executemany(
                        """
                        INSERT OR IGNORE INTO game_position (game_id, ply, position_key, move_uci)
                        VALUES (?, ?, ?, ?)
                    """,
                        [(bytes.fromhex(row[0],), row[1], hashlib.sha256(row[2].encode(),).digest(), row[3]) for row in rows],
                    )

                self.connection.execute("DELETE FROM game_position WHERE typeof(game_id) = 'text'",)

                self.connection.execute("PRAGMA user_version = 1",)

    def close(self,) -> None:
        with self.lock:
            self.connection.close()

    @contextmanager
    def acquire_write(self,):
        with self.lock, self.capacity.database_write(self.connection,):
            yield
