import hashlib
import json

import chess
import chess.pgn

from gambit.infrastructure.data_evaluations import find_evaluations

class CorpusQueries:
    def decode_puzzle(
        self,
        row,
    ) -> dict | None:
        if row is None:
            return None

        result = dict(row,)

        result["solution"] = json.loads(result["solution"],)

        result["themes"] = json.loads(result["themes"],)

        result["license"] = "CC0-1.0" if result["source"].startswith("https://database.lichess.org/",) else "source supplied"

        return result

    def select_puzzle(
        self,
        themes: list[str] | None = None,
        rating: int = 1800,
        exclude_ids: list[str] | None = None,
    ) -> dict | None:
        excluded = exclude_ids or []
        predicates = ["p.rating BETWEEN ? AND ?",]

        parameters = [
            max(
                0,
                rating - 400,
            ),
            rating + 400,
        ]

        for theme in themes or []:
            predicates.append("EXISTS (SELECT 1 FROM puzzle_theme AS t WHERE t.puzzle_id = p.id AND t.theme = ?)",)
            parameters.append(theme,)

        if excluded:
            predicates.append("p.id NOT IN (" + ",".join(("?" for identifier in excluded),) + ")",)
            parameters.extend(excluded,)

        query = "SELECT p.id, p.fen, p.solution, p.rating, p.themes, p.source, p.game_url FROM puzzle AS p WHERE " + " AND ".join(predicates,)

        with self.lock:
            lower = self.connection.execute(
                query + " AND p.rating <= ? ORDER BY p.rating DESC, p.id LIMIT 1",
                [*parameters, rating,],
            ).fetchone()

            upper = self.connection.execute(
                query + " AND p.rating >= ? ORDER BY p.rating, p.id LIMIT 1",
                [*parameters, rating,],
            ).fetchone()

        candidates = [row for row in (lower, upper) if row is not None]

        row = min(
            candidates,
            key=lambda row: (abs(row["rating"] - rating,), row["id"]),
        ) if candidates else None

        return self.decode_puzzle(row,)

    def decode_game(
        self,
        row,
    ) -> dict | None:
        if row is None:
            return None

        result = dict(row,)

        result["headers"] = json.loads(result["headers"],)

        result["moves"] = json.loads(result["moves"],)

        result["license"] = "CC-BY-SA-4.0" if result["source"].startswith("https://database.lichess.org/broadcast/",) else "Chess.com public game archive" if result["source"].startswith("https://api.chess.com/",) else "source supplied"

        return result

    def find_position_games(
        self,
        fen: str,
        limit: int = 20,
    ) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("Return between one and 100 matching games.",)

        board = chess.Board(fen,)

        if not board.is_valid():
            raise ValueError("The lookup position is invalid.",)

        key = hashlib.sha256(" ".join(board.fen().split()[:4],).encode(),).digest()

        with self.lock:
            rows = self.connection.execute(
                "SELECT game_id, ply, move_uci FROM game_position WHERE position_key = ? ORDER BY game_id, ply LIMIT ?",
                (key, limit),
            ).fetchall()

        return [{"game_id": bytes(row["game_id"],).hex(), "ply": row["ply"], "move_uci": row["move_uci"],} for row in rows]

    def get_game(
        self,
        game_id: str,
    ) -> dict | None:
        with self.lock:
            row = self.connection.execute(
                "SELECT id, pgn, headers, root_fen, moves, username, source, played_at FROM game WHERE id = ?",
                (game_id,),
            ).fetchone()

        return self.decode_game(row,)

    def list_games(
        self,
        username: str | None = None,
        limit: int = 20,
    ) -> list[dict]:
        if not 1 <= limit <= 100:
            raise ValueError("Return between one and 100 corpus games.",)

        with self.lock:
            rows = self.connection.execute(
                "SELECT id, pgn, headers, root_fen, moves, username, source, played_at FROM game WHERE (? IS NULL OR username = ?) ORDER BY played_at DESC, id LIMIT ?",
                (username, username, limit),
            ).fetchall()

        return [self.decode_game(row,) for row in rows]

    def search_material(
        self,
        query: str = "",
        kind: str | None = None,
        limit: int = 20,
    ) -> dict:
        if not 1 <= limit <= 100 or len(query,) > 200:
            raise ValueError("Corpus search parameters exceed their supported bounds.",)

        with self.lock:
            if kind == "game":
                puzzles = []
            elif not query:
                puzzles = self.connection.execute(
                    "SELECT id, fen, solution, rating, themes, source, game_url FROM puzzle ORDER BY rating, id LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                puzzles = self.connection.execute(
                    """
                    SELECT id, fen, solution, rating, themes, source, game_url FROM puzzle WHERE id = ?
                    UNION
                    SELECT p.id, p.fen, p.solution, p.rating, p.themes, p.source, p.game_url
                    FROM puzzle AS p JOIN (
                        SELECT puzzle_id FROM puzzle_theme WHERE theme = ? ORDER BY puzzle_id LIMIT ?
                    ) AS t ON t.puzzle_id = p.id
                    ORDER BY rating, id LIMIT ?
                """,
                    (query, query, limit, limit),
                ).fetchall()

            if kind == "puzzle":
                games = []
            elif query:
                expression = '"' + query.replace(
                    '"',
                    '""',
                ) + '"'

                games = self.connection.execute(
                    "SELECT g.id, g.pgn, g.headers, g.root_fen, g.moves, g.username, g.source, g.played_at FROM game AS g JOIN game_search AS s ON s.id = g.id WHERE game_search MATCH ? ORDER BY rank LIMIT ?",
                    (expression, limit),
                ).fetchall()
            else:
                games = self.connection.execute(
                    "SELECT id, pgn, headers, root_fen, moves, username, source, played_at FROM game ORDER BY played_at DESC, id LIMIT ?",
                    (limit,),
                ).fetchall()

        return {"puzzles": [self.decode_puzzle(row,) for row in puzzles], "games": [self.decode_game(row,) for row in games],}

    def find_evaluations(
        self,
        fen: str,
        limit: int = 3,
    ) -> list[dict]:
        return find_evaluations(
            self,
            fen,
            limit,
        )

    def get_status(self,) -> dict:
        with self.lock:
            puzzle_count = self.connection.execute("SELECT count(*) FROM puzzle",).fetchone()[0]
            game_count = self.connection.execute("SELECT count(*) FROM game",).fetchone()[0]
            checkpoints = [dict(row,) for row in self.connection.execute("SELECT id, sha256, processed_rows, imported_rows, rejected_rows, status, system_created_at, system_updated_at FROM import_checkpoint ORDER BY id",)]

        return {"puzzles": puzzle_count, "games": game_count, "imports": checkpoints, **self.capacity.get_status(),}
