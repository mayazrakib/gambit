import csv
import hashlib
import io
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from gambit.engine import parse_board, parse_move
from gambit.knowledge import get_position_key
from gambit.storage import Store

def get_repertoire_progress_id(fen: str,) -> str:
    key = get_position_key(parse_board(fen,),)

    return hashlib.sha256(("repertoire:" + key).encode(),).hexdigest()

def validate_training_id(identifier: str,) -> None:
    if re.fullmatch(
        r"[A-Za-z0-9_.-]{1,64}",
        identifier,
    ) is None:
        raise ValueError("Training identifiers must contain 1 to 64 letters, digits, dots, underscores, or hyphens.",)

LESSONS = {
    "tactics": {
        "name": "Checks, captures, and threats",
        "objective": "Identify forcing moves before evaluating quiet candidates.",
        "steps": [
            "List every legal check.",
            "Inspect captures and the opponent's replies.",
            "Look for pins, forks, skewers, and overloaded defenders.",
            "Calculate a complete reply before committing.",
        ],
    },
    "openings": {
        "name": "Development with a purpose",
        "objective": "Connect repertoire moves to development, central control, and king safety.",
        "steps": [
            "Identify the central pawn structure.",
            "Compare the available developing moves.",
            "Check immediate tactical threats.",
            "Recall the repertoire move and explain its purpose.",
        ],
    },
    "middlegames": {
        "name": "Candidate moves and plans",
        "objective": "Choose a plan based on the position and verify its first move.",
        "steps": [
            "Identify the opponent's threat.",
            "Compare king safety and piece activity.",
            "Find pawn breaks and possible weak squares.",
            "Select three candidates and calculate the strongest reply to each.",
        ],
    },
    "positioning": {
        "name": "Improve the least active piece",
        "objective": "Find useful piece destinations without overlooking tactics.",
        "steps": [
            "Identify a piece with few useful squares.",
            "Find an accessible square that improves its activity.",
            "Check whether the route weakens king safety or pawn structure.",
            "Compare the plan against a forcing alternative.",
        ],
    },
    "endgames": {
        "name": "King activity and conversion",
        "objective": "Coordinate king and pawns while respecting draw mechanisms.",
        "steps": [
            "Count material and identify passed pawns.",
            "Compare king routes and opposition.",
            "Check promotion races, stalemate, and the fifty-move rule.",
            "Use tablebase evidence when available.",
        ],
    },
    "calculation": {
        "name": "Calculate before moving",
        "objective": "Visualize candidate lines and actively seek a refutation.",
        "steps": [
            "Name two candidate moves.",
            "Predict the strongest opposing reply.",
            "Visualize the resulting position without moving pieces.",
            "Compare your line to the engine and identify the first divergence.",
        ],
    },
}

class Training:
    def __init__(
        self,
        store: Store,
        analysis=None,
    ) -> None:
        self.store = store
        self.analysis = analysis

    def get_due_repertoire(
        self,
        learner_id: str,
    ) -> str | None:
        validate_training_id(learner_id,)
        now = datetime.now(UTC,).isoformat()

        with self.store.lock:
            self.store.connection.create_function(
                "repertoire_progress_id",
                1,
                get_repertoire_progress_id,
                deterministic=True,
            )
            row = self.store.connection.execute(
                """
                    SELECT json_extract(repertoire.payload, '$.fen') FROM record AS repertoire
                    LEFT JOIN record AS progress
                        ON progress.collection = 'attempt'
                        AND progress.id = ? || ':' || repertoire_progress_id(json_extract(repertoire.payload, '$.fen'))

                    WHERE repertoire.collection = 'repertoire'
                        AND (progress.id IS NULL OR json_extract(progress.payload, '$.due_at') <= ?)

                    ORDER BY CASE WHEN progress.id IS NULL THEN 1 ELSE 0 END,
                        json_extract(progress.payload, '$.due_at'), repertoire.id
                    LIMIT 1
                """,
                (learner_id, now),
            ).fetchone()

        return row[0] if row else None

    def update_profile(
        self,
        learner_id: str,
        rating: int = 1200,
        style: str = "socratic",
        detail: str = "brief",
        speech_rate: int = 170,
        voice: str = "en",
    ) -> dict:
        validate_training_id(learner_id,)

        if not 100 <= rating <= 3500 or not 80 <= speech_rate <= 350:
            raise ValueError("Rating or speech rate is outside the supported range.",)

        if style not in ("socratic", "direct") or detail not in ("brief", "detailed"):
            raise ValueError("Unsupported tutoring style or detail level.",)

        if (
            not voice
            or len(voice,) > 40
            or any((character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-+"
                for character in voice),)
        ):
            raise ValueError("Voice must be a short synthesizer voice identifier.",)

        profile = {
            "id": learner_id,
            "rating": rating,
            "style": style,
            "detail": detail,
            "speech_rate": speech_rate,
            "voice": voice,
        }

        return self.store.put(
            "profile",
            learner_id,
            profile,
        )

    def import_puzzles(
        self,
        csv_text: str,
        source: str,
    ) -> dict:
        if not source.strip() or len(csv_text.encode(),) > 8 * 1024 * 1024:
            raise ValueError("Puzzle imports require attribution and at most 8 MiB of CSV.",)

        records = []

        for row in csv.DictReader(io.StringIO(csv_text,),):
            if not {"PuzzleId", "FEN", "Moves", "Rating", "Themes",}.issubset(row,):
                raise ValueError("Expected Lichess puzzle CSV columns.",)

            board = parse_board(row["FEN"],)
            moves = row["Moves"].split()

            if not 2 <= len(moves,) <= 128:
                raise ValueError("Puzzle lines must contain a setup move and 1 to 127 solution plies.",)

            for move in moves:
                board.push(parse_move(
                    board,
                    move,
                ),)

            board = parse_board(row["FEN"],)
            board.push_uci(moves[0],)
            records.append({
                "id": row["PuzzleId"],
                "fen": board.fen(),
                "solution": moves[1:],
                "rating": int(row["Rating"],),
                "themes": row["Themes"].split(),
                "source": source,
                "validation": "legal source line",
            },)

        if not records or len(records,) > 20000:
            raise ValueError("Import between 1 and 20000 puzzles per batch.",)

        for puzzle in records:
            self.store.put(
                "puzzle",
                puzzle["id"],
                puzzle,
            )

        return {
            "imported_puzzles": len(records,),
            "validation": "Moves were checked for legality; source solutions were not independently proven optimal.",
        }

    def get_tactic(
        self,
        learner_id: str,
        theme: str = "",
    ) -> dict:
        validate_training_id(learner_id,)
        profile = self.store.get(
            "profile",
            learner_id,
        ) or {"rating": 1200,}
        now = datetime.now(UTC,).isoformat()

        with self.store.lock:
            row = self.store.connection.execute(
                """
                    SELECT puzzle.payload FROM record AS puzzle
                    LEFT JOIN record AS progress
                        ON progress.collection = 'attempt'
                        AND progress.id = ? || ':' || puzzle.id

                    WHERE puzzle.collection = 'puzzle'
                        AND (? = '' OR EXISTS (
                            SELECT 1 FROM json_each(puzzle.payload, '$.themes')
                            WHERE value = ?
                        ))
                        AND (progress.id IS NULL OR json_extract(progress.payload, '$.due_at') <= ?)

                    ORDER BY CASE WHEN progress.id IS NULL THEN 1 ELSE 0 END,
                        abs(json_extract(puzzle.payload, '$.rating') - ?), puzzle.id
                    LIMIT 1
                """,
                (learner_id, theme, theme, now, profile["rating"]),
            ).fetchone()

        if row is None:
            return {
                "status": "unavailable",
                "reason": "No matching puzzles are due. Import puzzles or choose another theme.",
            }

        puzzle = json.loads(row[0],)
        session = {
            "id": str(uuid4(),),
            "learner_id": learner_id,
            "puzzle_id": puzzle["id"],
            "fen": puzzle["fen"],
            "ply": 0,
            "has_failed": False,
            "status": "active",
        }
        self.store.put(
            "session",
            session["id"],
            session,
        )

        return {
            "session_id": session["id"],
            "fen": session["fen"],
            "rating": puzzle["rating"],
            "themes": puzzle["themes"],
            "source": puzzle["source"],
        }

    def submit_tactic_move(
        self,
        session_id: str,
        move: str,
    ) -> dict:
        snapshot = self.store.get(
            "session",
            session_id,
        )

        if self.analysis is not None and snapshot is not None and snapshot["status"] == "active":
            puzzle = self.store.get(
                "puzzle",
                snapshot["puzzle_id"],
            )
            board = parse_board(snapshot["fen"],)
            candidate = parse_move(
                board,
                move,
            )

            if candidate.uci() != puzzle["solution"][snapshot["ply"]]:
                from dataclasses import asdict

                from gambit.assessment import assess_move

                assessment = assess_move(
                    self.analysis.engine,
                    snapshot["fen"],
                    move,
                )

                with self.store.lock:
                    current = self.store.get(
                        "session",
                        session_id,
                    )

                    if current != snapshot:
                        raise ValueError("The puzzle session changed during verification. Retry against the current position.",)

                    if assessment.classification == "acceptable":
                        current["status"] = "alternative accepted"
                        current["alternative_assessment"] = asdict(assessment,)
                        self.store.put(
                            "session",
                            session_id,
                            current,
                        )

                        return {"schema_version": 1, "is_correct": True, "is_source_solution": False, "is_objective_verified": False, "status": "alternative accepted", "assessment": asdict(assessment,), "message": "The alternative preserves the engine evaluation. This does not establish the source puzzle's intended teaching objective, so no source-solution mastery credit was awarded.",}

                    if assessment.classification == "uncertain":
                        return {"schema_version": 1, "is_correct": None, "status": "inconclusive", "assessment": asdict(assessment,), "message": "Searches disagree. This attempt has not been marked wrong.",}

        with self.store.lock:
            session = self.store.get(
                "session",
                session_id,
            )

            if session is None or session["status"] != "active":
                raise ValueError("The training session is not active.",)

            puzzle = self.store.get(
                "puzzle",
                session["puzzle_id"],
            )
            board = parse_board(session["fen"],)
            candidate = parse_move(
                board,
                move,
            )
            expected = puzzle["solution"][session["ply"]]

            if candidate.uci() != expected:
                session["has_failed"] = True
                self.store.put(
                    "session",
                    session_id,
                    session,
                )

                return {
                    "is_correct": False,
                    "status": "try again",
                    "message": "This move does not match the source solution. Alternative moves require separate engine analysis.",
                }

            board.push(candidate,)
            session["ply"] += 1
            reply = None

            if session["ply"] < len(puzzle["solution"],):
                reply = puzzle["solution"][session["ply"]]
                board.push_uci(reply,)
                session["ply"] += 1

            session["fen"] = board.fen()

            if session["ply"] >= len(puzzle["solution"],):
                session["status"] = "completed"
                self.record_attempt(
                    session["learner_id"],
                    puzzle["id"],
                    not session["has_failed"],
                    session_id,
                )

            self.store.put(
                "session",
                session_id,
                session,
            )

            return {
                "is_correct": True,
                "fen": board.fen(),
                "reply_uci": reply,
                "status": session["status"],
            }

    def record_attempt(
        self,
        learner_id: str,
        puzzle_id: str,
        was_successful: bool,
        attempt_id: str,
    ) -> dict:
        for identifier in (learner_id, puzzle_id, attempt_id):
            validate_training_id(identifier,)

        record_id = learner_id + ":" + puzzle_id
        event_id = "event:" + learner_id + ":" + attempt_id

        with self.store.lock:
            prior_event = self.store.get(
                "attempt",
                event_id,
            )

            if prior_event is not None:
                if prior_event["puzzle_id"] != puzzle_id or prior_event["was_successful"] != was_successful:
                    raise ValueError("The attempt identifier was already used for a different outcome.",)

                return {key: entry for key, entry in prior_event.items() if key not in ("id", "is_event")}

            previous = self.store.get(
                "attempt",
                record_id,
            ) or {"streak": 0,}

            if previous.get("attempt_id",) == attempt_id:
                return previous

            streak = previous["streak"] + 1 if was_successful else 0
            interval_days = min(
                90,
                2 ** min(
                    streak,
                    7,
                ),
            ) if was_successful else 0
            due = datetime.now(UTC,) + (
                timedelta(days=interval_days,) if was_successful else timedelta(minutes=10,)
            )
            attempt = {
                "learner_id": learner_id,
                "puzzle_id": puzzle_id,
                "attempt_id": attempt_id,
                "streak": streak,
                "was_successful": was_successful,
                "due_at": due.isoformat(),
            }

            self.store.put_many(
                "attempt",
                [{"id": record_id, **attempt,}, {"id": event_id, "is_event": True, **attempt,},],
            )

            return attempt

    def start_lesson(
        self,
        learner_id: str,
        topic: str,
    ) -> dict:
        if topic not in LESSONS:
            raise ValueError(f"Choose a lesson topic from {sorted(LESSONS,)}.",)

        lesson = {
            "id": str(uuid4(),),
            "learner_id": learner_id,
            "topic": topic,
            "completed_steps": [],
            **LESSONS[topic],
        }

        return self.store.put(
            "lesson",
            lesson["id"],
            lesson,
        )

    def advance_lesson(
        self,
        lesson_id: str,
        step: int,
    ) -> dict:
        with self.store.lock:
            lesson = self.store.get(
                "lesson",
                lesson_id,
            )

            if lesson is None or step < 0 or step >= len(lesson["steps"],):
                raise ValueError("The lesson or step does not exist.",)

            lesson["completed_steps"] = sorted(set(lesson["completed_steps"],) | {step,},)
            lesson["is_complete"] = len(lesson["completed_steps"],) == len(lesson["steps"],)

            return self.store.put(
                "lesson",
                lesson_id,
                lesson,
            )
