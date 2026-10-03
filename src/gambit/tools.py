import atexit
import threading
from dataclasses import asdict

from gambit.analysis import AnalysisService, EnginePool
from gambit.configuration import load_configuration
from gambit.contracts import PositionEvidence
from gambit.corpus import load_bundled_openings
from gambit.engine import execute_engine_request
from gambit.features import inspect_features
from gambit.knowledge import Knowledge
from gambit.learning import Learning
from gambit.opening_plans import OpeningPlans
from gambit.progressive import ProgressiveAnalysis
from gambit.speech import Speech, create_speech_plan
from gambit.storage import Store
from gambit.training import LESSONS, Training, get_repertoire_progress_id, validate_training_id
from gambit.tutoring import Tutor

class Runtime:
    def __init__(
        self,
        engine: EnginePool | None = None,
    ) -> None:
        self.configuration = load_configuration()
        self.store = Store(self.configuration.database_path,)
        self.analysis = AnalysisService(
            self.configuration,
            self.store,
            engine,
        )
        self.knowledge = Knowledge(self.store,)
        self.training = Training(
            self.store,
            self.analysis,
        )
        self.learning = Learning(
            self.analysis,
            self.store,
        )
        self.opening_plans = OpeningPlans(self.store,)
        self.progressive = ProgressiveAnalysis(self.analysis,)
        self.speech = Speech(
            self.configuration.speech_executable,
            self.configuration.speech_directory,
        )
        self.tutor = Tutor(
            self.analysis,
            self.knowledge,
            self.store,
        )

    def close(self,) -> None:
        self.progressive.close()
        self.analysis.close()
        self.store.close()

class RuntimeOwner:
    def __init__(
        self,
        engine: EnginePool | None = None,
    ) -> None:
        self.runtime = None
        self.engine = engine
        self.lock = threading.Lock()

    def get_runtime(self,) -> Runtime:
        with self.lock:
            if self.runtime is None:
                self.runtime = Runtime(self.engine,)
                atexit.register(self.runtime.close,)

            return self.runtime

def register_tools(
    server,
    engine: EnginePool | None = None,
) -> None:
    owner = RuntimeOwner(engine,)
    from gambit.extended_tools import register_extended_tools

    register_extended_tools(
        server,
        owner,
    )

    @server.tool(description="Load the bundled, version-pinned Lichess named opening corpus into local storage.",)
    async def initialize_openings() -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            load_bundled_openings,
            owner.get_runtime().store,
        )

    @server.tool(description="Report engine settings and exact local corpus counts without launching an engine.",)
    def get_capabilities() -> dict[
        str,
        object,
    ]:
        runtime = owner.get_runtime()

        return {
            "configuration": asdict(runtime.configuration,),
            "counts": {
                name: runtime.store.count_records(name,)
                for name in ("opening", "repertoire", "puzzle", "analysis")
            },
            "lesson_topics": list(LESSONS,),
            "speech": "Local espeak-ng or client-managed TTS.",
            "model": "The MCP host supplies the language model.",
        }

    @server.tool(description="Analyze a position with White-relative scores, immutable evidence, and optional move history.",)
    async def evaluate_position(
        fen: str,
        profile: str = "quick",
        moves: list[str] | None = None,
    ) -> PositionEvidence:
        return await execute_engine_request(
            owner.get_runtime().analysis.evaluate,
            fen,
            profile,
            moves,
        )

    @server.tool(description="Compare a legal move against engine analysis before and after it. Scores are White-relative.",)
    async def evaluate_move(
        fen: str,
        move: str,
        profile: str = "quick",
        history: list[str] | None = None,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().analysis.evaluate_move,
            fen,
            move,
            profile,
            history,
        )

    @server.tool(description="Analyze and compare up to eight candidate moves under the same search profile.",)
    async def compare_candidate_moves(
        fen: str,
        moves: list[str],
        profile: str = "quick",
        history: list[str] | None = None,
    ) -> dict[
        str,
        object,
    ]:
        if not 1 <= len(moves,) <= 8:
            raise ValueError("Compare between one and eight candidate moves.",)

        comparisons = []

        for move in moves:
            comparisons.append(await evaluate_move(
                fen,
                move,
                profile,
                history,
            ),)

        return {"comparisons": comparisons,}

    @server.tool(description="Start a bounded, persistent background game analysis or review job.",)
    def start_analysis_job(
        pgn: str,
        should_review: bool = True,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().analysis.start_job(
            pgn,
            should_review,
        )

    @server.tool(description="Read analysis job status and completed-search progress.",)
    def get_analysis_job(job_id: str,) -> dict[
        str,
        object,
    ]:
        job = owner.get_runtime().store.get(
            "job",
            job_id,
        )

        if job is None:
            raise ValueError("The analysis job does not exist.",)

        return job

    @server.tool(description="Cancel a job at its next search boundary. An active search has a bounded deadline.",)
    def cancel_analysis_job(job_id: str,) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().analysis.cancel_job(job_id,)

    @server.tool(description="Retrieve an immutable position analysis or completed game report.",)
    def get_analysis(analysis_id: str,) -> dict[
        str,
        object,
    ]:
        analysis = owner.get_runtime().store.get(
            "analysis",
            analysis_id,
        )

        if analysis is None:
            raise ValueError("The analysis record does not exist.",)

        return analysis

    @server.tool(description="Import a source-attributed PGN study, including variations and transpositions.",)
    async def import_study(
        pgn: str,
        name: str,
        source: str,
        is_repertoire: bool = False,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().knowledge.import_study,
            pgn,
            name,
            source,
            is_repertoire,
        )

    @server.tool(description="Import a bounded Lichess-format opening TSV batch with explicit source attribution.",)
    async def import_opening_tsv(
        tsv: str,
        source: str,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().knowledge.import_opening_tsv,
            tsv,
            source,
        )

    @server.tool(description="Search locally imported opening names with pagination.",)
    def find_opening(
        query: str,
        offset: int = 0,
    ) -> list[dict[
        str,
        object,
    ]]:
        return owner.get_runtime().knowledge.search_openings(
            query,
            offset,
        )

    @server.tool(description="Get source-attributed corpus moves at a position, including transpositions.",)
    def get_opening_position(
        fen: str,
        offset: int = 0,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().knowledge.find_moves(
            fen,
            False,
            offset,
        )

    @server.tool(description="Get personal repertoire moves at a position.",)
    def get_repertoire_move(
        fen: str,
        offset: int = 0,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().knowledge.find_moves(
            fen,
            True,
            offset,
        )

    @server.tool(description="Create a repertoire recall drill without exposing its expected moves.",)
    def create_repertoire_drill(
        learner_id: str,
        fen: str,
    ) -> dict[
        str,
        object,
    ]:
        from uuid import uuid4
        validate_training_id(learner_id,)
        runtime = owner.get_runtime()
        repertoire = runtime.knowledge.find_moves(
            fen,
            True,
        )

        if not repertoire["moves"]:
            raise ValueError("No repertoire moves are recorded at this position.",)

        drill = {
            "id": str(uuid4(),),
            "kind": "repertoire",
            "learner_id": learner_id,
            "fen": fen,
            "expected_moves": [record["move_uci"] for record in repertoire["moves"]],
            "status": "active",
            "has_failed": False,
        }
        runtime.store.put(
            "session",
            drill["id"],
            drill,
        )

        return {
            "session_id": drill["id"],
            "fen": fen,
            "prompt": "Recall a move from your repertoire.",
        }

    @server.tool(description="Select a due repertoire position using transposition-aware spaced review and hide expected moves.",)
    def get_due_repertoire_drill(learner_id: str,) -> dict[
        str,
        object,
    ]:
        fen = owner.get_runtime().training.get_due_repertoire(learner_id,)

        if fen is None:
            return {"schema_version": 1, "status": "unavailable", "reason": "No repertoire positions are due.",}

        return {
            "schema_version": 1,
            **create_repertoire_drill(
                learner_id,
                fen,
            ),
        }

    @server.tool(description="Submit a legal move to a repertoire recall drill.",)
    def submit_repertoire_move(
        session_id: str,
        move: str,
    ) -> dict[
        str,
        object,
    ]:
        from gambit.engine import parse_board, parse_move
        runtime = owner.get_runtime()

        with runtime.store.lock:
            session = runtime.store.get(
                "session",
                session_id,
            )

            if (
                session is None
                or session.get("kind",) != "repertoire"
                or session["status"] != "active"
            ):
                raise ValueError("The repertoire drill is not active.",)

            candidate = parse_move(
                parse_board(session["fen"],),
                move,
            )
            is_correct = candidate.uci() in session["expected_moves"]

            if is_correct:
                session["status"] = "completed"
                runtime.training.record_attempt(
                    session["learner_id"],
                    get_repertoire_progress_id(session["fen"],),
                    not session.get(
                        "has_failed",
                        False,
                    ),
                    session_id,
                )
            else:
                session["has_failed"] = True

            runtime.store.put(
                "session",
                session_id,
                session,
            )

            return {"is_correct": is_correct, "status": session["status"],}

    @server.tool(description="Inspect legal state, material, pins, attacks, and pawn structures without an engine.",)
    def explain_position(fen: str,) -> dict[
        str,
        object,
    ]:
        return inspect_features(fen,)

    @server.tool(description="Return factual isolated, doubled, and passed-pawn geometry for both sides.",)
    def analyze_pawn_structure(fen: str,) -> dict[
        str,
        object,
    ]:
        return inspect_features(fen,)

    @server.tool(description="Probe configured local Syzygy WDL and DTZ with explicit availability and draw semantics.",)
    async def get_tablebase_result(fen: str,) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().analysis.tablebases.probe,
            fen,
        )

    @server.tool(description="Combine endgame features with tablebase evidence or engine analysis when unavailable.",)
    async def evaluate_endgame(fen: str,) -> dict[
        str,
        object,
    ]:
        tablebase = await get_tablebase_result(fen,)
        analysis = None

        if tablebase["status"] != "available":
            analysis = await evaluate_position(fen,)

        return {"features": inspect_features(fen,), "tablebase": tablebase, "analysis": analysis,}

    @server.tool(description="Persist a learner's rating band, teaching preferences, and voice settings.",)
    def update_learner_profile(
        learner_id: str,
        rating: int = 1200,
        style: str = "socratic",
        detail: str = "brief",
        speech_rate: int = 170,
        voice: str = "en",
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().training.update_profile(
            learner_id,
            rating,
            style,
            detail,
            speech_rate,
            voice,
        )

    @server.tool(description="Read persisted learner preferences and a paginated training-progress view.",)
    def get_learner_progress(
        learner_id: str,
        offset: int = 0,
    ) -> dict[
        str,
        object,
    ]:
        runtime = owner.get_runtime()
        records = runtime.store.list_records(
            "attempt",
            100,
            offset,
        )

        return {
            "profile": runtime.store.get(
                "profile",
                learner_id,
            ),
            "attempts": [record for record in records if record["learner_id"] == learner_id and not record.get(
                "is_event",
                False,
            )],
            "next_offset": offset + 100 if len(records,) == 100 else None,
        }

    @server.tool(description="Import a bounded puzzle CSV batch, validating the setup move and complete source line.",)
    async def import_puzzles(
        csv_text: str,
        source: str,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().training.import_puzzles,
            csv_text,
            source,
        )

    @server.tool(description="Select a due puzzle near the learner's rating and begin a solution-hidden session.",)
    def get_tactic(
        learner_id: str,
        theme: str = "",
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().training.get_tactic(
            learner_id,
            theme,
        )

    @server.tool(description="Check a puzzle move, play the source reply, and schedule completed puzzles for review.",)
    async def submit_tactic_move(
        session_id: str,
        move: str,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().training.submit_tactic_move,
            session_id,
            move,
        )

    @server.tool(description="Record an explicitly reported training outcome with idempotent attempt identity.",)
    def record_training_attempt(
        learner_id: str,
        puzzle_id: str,
        was_successful: bool,
        attempt_id: str,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().training.record_attempt(
            learner_id,
            puzzle_id,
            was_successful,
            attempt_id,
        )

    @server.tool(description="Start a persisted lesson in tactics, openings, middlegames, positioning, endgames, or calculation.",)
    def start_lesson(
        learner_id: str,
        topic: str,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().training.start_lesson(
            learner_id,
            topic,
        )

    @server.tool(description="Mark a lesson step complete without equating completion to demonstrated mastery.",)
    def advance_lesson(
        lesson_id: str,
        step: int,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().training.advance_lesson(
            lesson_id,
            step,
        )

    @server.tool(description="Create a grounded tutor turn with engine evidence, teaching guidance, board actions, and speech segments.",)
    async def create_tutor_turn(
        fen: str,
        learner_id: str = "default",
        intent: str = "explain",
        profile: str = "instant",
        history: list[str] | None = None,
        candidates: list[str] | None = None,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().tutor.create_turn,
            fen,
            learner_id,
            intent,
            profile,
            history,
            candidates,
        )

    @server.tool(description="Create interruptible speech segments and legal SAN/UCI pronunciations.",)
    def get_speech_plan(
        fen: str,
        segments: list[str],
        moves: list[str] | None = None,
    ) -> dict[
        str,
        object,
    ]:
        return create_speech_plan(
            fen,
            segments,
            moves,
        )

    @server.tool(description="Synthesize a short local WAV using espeak-ng. Returns a local file URI, not streamed audio.",)
    async def synthesize_speech(
        text: str,
        voice: str = "en",
        rate: int = 170,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().speech.synthesize,
            text,
            voice,
            rate,
        )

    @server.resource("gambit://curriculum",)
    def get_curriculum() -> dict[
        str,
        object,
    ]:
        return LESSONS

    @server.resource("gambit://analysis/{analysis_id}",)
    def read_analysis(analysis_id: str,) -> dict[
        str,
        object,
    ]:
        return get_analysis(analysis_id,)

    @server.prompt(description="Ground a short chess tutoring conversation in Gambit's rules, corpus, and engine evidence.",)
    def teach_chess(
        fen: str,
        learner_id: str = "default",
    ) -> str:
        return f"Tutor learner {learner_id} at FEN {fen}. Call create_tutor_turn. Use only its evidence for chess claims. Preserve score perspective and provenance. Ask one short question at a time. Validate moves before discussing them. For hints, do not reveal the solution. Use speech segments and board directives only for the matching position."
