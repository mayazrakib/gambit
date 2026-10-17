from typing import Literal

from gambit.engine.client import execute_engine_request

def register_tutoring_tools(
    server,
    owner,
) -> None:
    @server.tool(description="Start a persistent tutoring variation tree from a position and known history.",)
    def start_tutor_session(
        fen: str,
        learner_id: str = "default",
        history: list[str] | None = None,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().sessions.create_session(
            fen,
            learner_id,
            history,
        )

    @server.tool(description="Read session state; include the variation tree only when needed.",)
    def get_tutor_session(
        session_id: str,
        should_include_tree: bool = False,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().sessions.get_session(
            session_id,
            should_include_tree,
        )

    @server.tool(description="Advance, branch, select, or restore the game with revision and idempotency protection.",)
    def navigate_tutor_session(
        session_id: str,
        expected_revision: int,
        operation_id: str,
        action: Literal[
            "advance",
            "branch",
            "select",
            "return",
            "retry",
        ],
        move: str | None = None,
        node_id: str | None = None,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().sessions.navigate_session(
            session_id,
            expected_revision,
            operation_id,
            action,
            move,
            node_id,
        )

    @server.tool(description="Verify a learner prediction and record reasoning, confidence, and the first missed resource.",)
    async def submit_tutor_reasoning(
        session_id: str,
        expected_revision: int,
        operation_id: str,
        move: str,
        reasoning: str = "",
        continuation: list[str] | None = None,
        confidence: float | None = None,
        estimated_centipawns: int | None = None,
        profile: str = "instant",
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().sessions.submit_reasoning,
            session_id,
            expected_revision,
            operation_id,
            move,
            reasoning,
            continuation,
            confidence,
            estimated_centipawns,
            profile,
        )

    @server.tool(description="Test structured plan objectives and candidate moves against concrete defensive evidence.",)
    async def assess_tutor_plan(
        session_id: str,
        objectives: list[str],
        candidates: list[str],
        profile: str = "instant",
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().sessions.assess_plan,
            session_id,
            objectives,
            candidates,
            profile,
        )

    @server.tool(description="Compare candidate quality and observed practical difficulty without invented human probabilities.",)
    async def compare_practical_moves(
        session_id: str,
        candidates: list[str],
        profile: str = "instant",
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().sessions.compare_practical,
            session_id,
            candidates,
            profile,
        )

    @server.tool(description="Start hidden-solution calculation, refutation, defense, opening, transfer, prediction, or endgame practice.",)
    async def start_practice(
        mode: Literal[
            "calculation",
            "refutation",
            "defense",
            "mixed",
            "transfer",
            "counterexample",
            "opening",
            "prediction",
            "endgame",
            "timed diagnosis",
        ],
        learner_id: str = "default",
        fen: str | None = None,
        history: list[str] | None = None,
        source_id: str | None = None,
        is_timed: bool = False,
    ) -> dict[
        str,
        object,
    ]:
        owner.get_runtime().get_corpus()

        return await execute_engine_request(
            owner.get_runtime().practice.start_practice,
            mode,
            learner_id,
            fen,
            history,
            source_id,
            is_timed,
        )

    @server.tool(description="Submit a practice line, request a progressive hint, reveal, replay, or retry using the current revision.",)
    async def act_practice(
        practice_id: str,
        expected_revision: int,
        operation_id: str,
        action: Literal[
            "submit",
            "hint",
            "reveal",
            "replay",
            "retry",
            "play",
            "repair",
        ],
        moves: list[str] | None = None,
        confidence: float | None = None,
        reasoning: str = "",
        elapsed_ms: int | None = None,
        profile: str = "instant",
        checkpoint: int | None = None,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().practice.act_practice,
            practice_id,
            expected_revision,
            operation_id,
            action,
            moves,
            confidence,
            reasoning,
            elapsed_ms,
            profile,
            checkpoint,
        )

    @server.tool(description="Resume a persisted practice session without revealing its answer.",)
    def get_practice(practice_id: str,) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().practice.get_practice(practice_id,)

    @server.tool(description="Read unassisted accuracy, delayed retention, transfer, confidence calibration, and comparable timing.",)
    def get_learning_dashboard(learner_id: str,) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().practice.get_dashboard(learner_id,)

    @server.tool(description="Read recurring evidenced mistakes and examples without claiming an established causal diagnosis.",)
    def get_learner_patterns(learner_id: str,) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().practice.get_patterns(learner_id,)

    @server.tool(description="Select due independent reviews without exposing their solutions.",)
    def get_due_reviews(learner_id: str,) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().practice.get_due_reviews(learner_id,)

    @server.tool(description="Export the explored tutoring study as PGN with learner and tutor annotations.",)
    def export_tutor_study(session_id: str,) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().sessions.export_session(session_id,)

    @server.tool(description="Search local puzzles, personal games, and attributed model games with bounded results.",)
    async def search_chess_material(
        query: str = "",
        kind: str | None = None,
        limit: int = 20,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().get_corpus().search_material,
            query,
            kind,
            limit,
        )
