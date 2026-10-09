import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

import chess

from gambit.api.contracts import ConceptProgress, ReviewLessons
from gambit.engine.client import parse_move
from gambit.game.assessment import MoveAssessment, assess_move, build_board
from gambit.game.features import inspect_features
from gambit.infrastructure.storage import Store
from gambit.learning.training import validate_training_id

if TYPE_CHECKING:
    from gambit.engine.analysis import AnalysisService

@dataclass(frozen=True,)
class TeachingQuestion:
    schema_version: int
    session_id: str
    fen: str
    concept: str
    question: str
    hint_level: int
    status: str

@dataclass(frozen=True,)
class TeachingFeedback:
    schema_version: int
    session_id: str
    is_accepted: bool
    assessment: MoveAssessment
    explanation: str
    next_question: str
    due_at: str

def diagnose_concept(board: chess.Board,) -> str:
    if board.is_check():
        return "check defense"

    if len(board.piece_map(),) <= 7:
        return "endgame conversion"

    features = inspect_features(board.fen(),)["sides"]["white" if board.turn else "black"]

    if features["pinned_pieces"]:
        return "absolute pins"

    if features["isolated_pawns"]:
        return "pawn structure"

    return "candidate calculation"

class Learning:
    def __init__(
        self,
        analysis: "AnalysisService",
        store: Store,
    ) -> None:
        self.analysis = analysis
        self.store = store

    def start_session(
        self,
        fen: str,
        learner_id: str = "default",
        history: list[str] | None = None,
    ) -> TeachingQuestion:
        validate_training_id(learner_id,)
        board = build_board(
            fen,
            history,
        )

        if board.is_game_over():
            raise ValueError("Start a teaching session from a nonterminal position.",)

        concept = diagnose_concept(board,)
        session_id = str(uuid4(),)
        self.store.put(
            "teaching",
            session_id,
            {
                "id": session_id,
                "learner_id": learner_id,
                "root_fen": fen,
                "history": history or [],
                "fen": board.fen(),
                "concept": concept,
                "hint_level": 0,
                "status": "active",
            },
        )

        return TeachingQuestion(
            1,
            session_id,
            board.fen(),
            concept,
            "Choose a candidate move and calculate the opponent's strongest reply. Explain your reasoning before submitting the move.",
            0,
            "active",
        )

    def get_hint(
        self,
        session_id: str,
        level: int,
    ) -> TeachingQuestion:
        if not 1 <= level <= 4:
            raise ValueError("Choose a hint level between 1 and 4.",)

        session = self.store.get(
            "teaching",
            session_id,
        )

        if session is None or session["status"] != "active":
            raise ValueError("The teaching session is not active.",)

        prompt = f"Focus on {session['concept']}. This is a teaching topic, not a proven cause of an evaluation change."

        if level > 1:
            analysis = self.analysis.evaluate(
                session["root_fen"],
                "quick",
                session["history"],
            )
            line = analysis["principal_variations"][0]
            board = build_board(
                session["root_fen"],
                session["history"],
            )
            move = parse_move(
                board,
                line["moves_uci"][0],
            )

            if level == 2:
                prompt = f"Consider the {chess.piece_name(board.piece_at(move.from_square,).piece_type,)} on {chess.square_name(move.from_square,)}. Compare its legal moves."
            elif level == 3:
                prompt = f"Investigate {board.san(move,)}. What is the strongest reply?"
            else:
                prompt = "The current engine line is " + ", ".join(line["moves_san"][:6],) + ". This is search evidence, not proof that every alternative fails."

        with self.store.lock:
            current = self.store.get(
                "teaching",
                session_id,
            )

            if current["status"] != "active":
                raise ValueError("The teaching session changed while the hint was prepared.",)

            current["hint_level"] = max(
                current["hint_level"],
                level,
            )
            self.store.put(
                "teaching",
                session_id,
                current,
            )

        return TeachingQuestion(
            1,
            session_id,
            session["fen"],
            session["concept"],
            prompt,
            level,
            "active",
        )

    def submit_move(
        self,
        session_id: str,
        move: str,
    ) -> TeachingFeedback:
        session = self.store.get(
            "teaching",
            session_id,
        )

        if session is None or session["status"] != "active":
            raise ValueError("The teaching session is not active.",)

        assessment = assess_move(
            self.analysis.engine,
            session["root_fen"],
            move,
            session["history"],
        )
        is_accepted = assessment.classification == "acceptable"
        is_conclusive = assessment.classification != "uncertain"
        progress_id = hashlib.sha256(f"{session['learner_id']}:{session['concept']}".encode(),).hexdigest()

        with self.store.lock:
            current = self.store.get(
                "teaching",
                session_id,
            )

            if current["status"] != "active":
                raise ValueError("The teaching answer was already recorded.",)

            progress = self.store.get(
                "concept",
                progress_id,
            ) or {
                "id": progress_id,
                "learner_id": session["learner_id"],
                "concept": session["concept"],
                "attempts": 0,
                "independent_successes": 0,
                "interval_days": 1,
            }

            if is_conclusive:
                progress["attempts"] += 1
                has_independent_success = is_accepted and current["hint_level"] == 0
                progress["independent_successes"] += int(has_independent_success,)
                progress["interval_days"] = min(
                    30,
                    progress["interval_days"] * 2,
                ) if has_independent_success else 1

            progress["due_at"] = (datetime.now(UTC,) + timedelta(days=progress["interval_days"],)).isoformat()
            self.store.put(
                "concept",
                progress_id,
                progress,
            )
            current.update(
                status="completed",
                assessment=asdict(assessment,),
            )
            self.store.put(
                "teaching",
                session_id,
                current,
            )

        variation = ", ".join(assessment.verified.variation_san[:6],)
        explanation = f"The verified candidate line is {variation}. Assessment: {assessment.classification}."

        if assessment.verified.mate_change:
            explanation += f" Mate evidence: {assessment.verified.mate_change}."
        elif assessment.verified.centipawn_loss is not None:
            explanation += f" The estimated loss against the root baseline is {assessment.verified.centipawn_loss} centipawns."

        return TeachingFeedback(
            1,
            session_id,
            is_accepted,
            assessment,
            explanation,
            "Compare the resulting position with your prediction. Which reply or positional change did you miss?",
            progress["due_at"],
        )

    def get_progress(
        self,
        learner_id: str,
    ) -> list[ConceptProgress]:
        validate_training_id(learner_id,)

        with self.store.lock:
            rows = self.store.connection.execute(
                """
                    SELECT payload FROM record
                    WHERE collection = 'concept' AND json_extract(payload, '$.learner_id') = ?

                    ORDER BY json_extract(payload, '$.due_at'), id
                    LIMIT 100
                """,
                (learner_id,),
            ).fetchall()

        import json

        return [json.loads(row[0],) for row in rows]

    def create_review_lessons(
        self,
        analysis_id: str,
        learner_id: str,
        side: str,
    ) -> ReviewLessons:
        if side not in ("white", "black"):
            raise ValueError("Choose white or black for the learner's side.",)

        validate_training_id(learner_id,)
        report = self.store.get(
            "analysis",
            analysis_id,
        )

        if report is None or "moves" not in report:
            raise ValueError("The game analysis does not exist.",)

        lessons = []
        history = []

        for entry in report["moves"]:
            move = entry.get(
                "analysis",
                entry,
            )
            board = build_board(
                report["initial_fen"],
                history,
            )
            is_learner_turn = board.turn == (side == "white")
            loss = move.get("centipawn_loss",) or 0

            if is_learner_turn and loss >= 100 and len(lessons,) < 20:
                lesson_id = hashlib.sha256(f"{analysis_id}:{learner_id}:{len(history,)}".encode(),).hexdigest()
                lesson = {"id": lesson_id, "learner_id": learner_id, "analysis_id": analysis_id, "topic": diagnose_concept(board,), "root_fen": report["initial_fen"], "history": list(history,), "fen": board.fen(), "status": "due", "source": "personal game review", "question": "Find an improvement and verify it in a teaching session.",}
                self.store.put(
                    "lesson",
                    lesson_id,
                    lesson,
                    is_immutable=True,
                )
                lessons.append(lesson,)

            history.append(move["uci"],)

        return {"schema_version": 1, "lessons": lessons, "grouping": "Repeated topics identify candidates for focused practice, not proven causal diagnoses.",}
