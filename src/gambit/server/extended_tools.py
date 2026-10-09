from typing import TYPE_CHECKING

from gambit.api.contracts import (
    AnalysisMetrics,
    ConceptReport,
    GameJob,
    OpeningCoverage,
    OpeningPlanRecord,
    OpeningPlanReport,
    OpeningStatistics,
    ProgressiveStart,
    ProgressiveStatus,
    ReviewLessons,
)
from gambit.engine.client import execute_engine_request
from gambit.game.assessment import MoveAssessment, assess_move
from gambit.knowledge.tablebases import TablebaseDiagnostics
from gambit.learning.openings import OpeningPlan
from gambit.learning.service import TeachingFeedback, TeachingQuestion

if TYPE_CHECKING:
    from gambit.server.tools import RuntimeOwner

def register_extended_tools(
    server,
    owner: "RuntimeOwner",
) -> None:
    @server.tool(description="Verify a candidate against unrestricted and forced-root searches at two budgets, retaining full supplied history.",)
    async def assess_candidate_move(
        fen: str,
        move: str,
        history: list[str] | None = None,
    ) -> MoveAssessment:
        return await execute_engine_request(
            assess_move,
            owner.get_runtime().analysis.engine,
            fen,
            move,
            history,
        )

    @server.tool(description="Start a solution-hidden teaching cycle with a concept-specific learning objective.",)
    def start_teaching_session(
        fen: str,
        learner_id: str = "default",
        history: list[str] | None = None,
    ) -> TeachingQuestion:
        return owner.get_runtime().learning.start_session(
            fen,
            learner_id,
            history,
        )

    @server.tool(description="Reveal one of four progressive hint levels, recording assistance without exposing the full solution early.",)
    async def get_teaching_hint(
        session_id: str,
        level: int,
    ) -> TeachingQuestion:
        return await execute_engine_request(
            owner.get_runtime().learning.get_hint,
            session_id,
            level,
        )

    @server.tool(description="Assess an answer, explain verified candidate lines, update concept progress, and schedule review.",)
    async def submit_teaching_move(
        session_id: str,
        move: str,
    ) -> TeachingFeedback:
        return await execute_engine_request(
            owner.get_runtime().learning.submit_move,
            session_id,
            move,
        )

    @server.tool(description="Return concept-specific attempts, independent successes, and due review dates.",)
    def get_concept_progress(learner_id: str,) -> ConceptReport:
        return {"schema_version": 1, "concepts": owner.get_runtime().learning.get_progress(learner_id,),}

    @server.tool(description="Create up to twenty position-specific practice lessons from the learner's mistakes in a saved game analysis.",)
    async def create_game_lessons(
        analysis_id: str,
        learner_id: str,
        side: str,
    ) -> ReviewLessons:
        return await execute_engine_request(
            owner.get_runtime().learning.create_review_lessons,
            analysis_id,
            learner_id,
            side,
        )

    @server.tool(description="Return immediate preliminary evidence and queue deeper analysis; supersede older requests with the same context ID.",)
    async def start_progressive_analysis(
        context_id: str,
        fen: str,
        history: list[str] | None = None,
    ) -> ProgressiveStart:
        return await execute_engine_request(
            owner.get_runtime().progressive.start,
            context_id,
            fen,
            history,
        )

    @server.tool(description="Read progressive analysis status and its completed evidence ID, withholding stale results.",)
    def get_progressive_analysis(request_id: str,) -> ProgressiveStatus:
        return owner.get_runtime().progressive.get_status(request_id,)

    @server.tool(description="Cancel queued or running progressive analysis and mark its result stale.",)
    def cancel_progressive_analysis(request_id: str,) -> ProgressiveStatus:
        return owner.get_runtime().progressive.get_status(
            request_id,
            True,
        )

    @server.tool(description="Report bounded engine latency samples, queue delays, cache hits, and reserved interactive capacity.",)
    def get_analysis_metrics() -> AnalysisMetrics:
        return owner.get_runtime().analysis.engine.get_metrics()

    @server.tool(description="Resume an interrupted, failed, or cancelled game job using compatible durable search checkpoints.",)
    def resume_analysis_job(job_id: str,) -> GameJob:
        return owner.get_runtime().analysis.resume_job(job_id,)

    @server.tool(description="Inspect configured tablebase directories and WDL/DTZ file pairing without claiming complete coverage.",)
    async def get_tablebase_diagnostics() -> TablebaseDiagnostics:
        return await execute_engine_request(owner.get_runtime().analysis.tablebases.get_diagnostics,)

    @server.tool(description="Import a dated, versioned opening teaching plan with source attribution. Advice is not engine-verified automatically.",)
    def import_opening_plan(plan: OpeningPlan,) -> OpeningPlanRecord:
        return owner.get_runtime().opening_plans.save_plan(plan,)

    @server.tool(description="Retrieve transposition-matched opening plans separately from practical game statistics.",)
    def get_opening_plans(fen: str,) -> OpeningPlanReport:
        return owner.get_runtime().opening_plans.get_plans(fen,)

    @server.tool(description="Import source-attributed aggregate opening outcomes for an explicitly described game population.",)
    def import_opening_statistics(
        fen: str,
        move: str,
        white_wins: int,
        draws: int,
        black_wins: int,
        source: str,
        source_date: str,
        population: str,
    ) -> OpeningStatistics:
        return owner.get_runtime().opening_plans.import_statistics(
            fen,
            move,
            white_wins,
            draws,
            black_wins,
            source,
            source_date,
            population,
        )

    @server.tool(description="Report exact local opening coverage by source, keeping theoretical plans and practical statistics distinct.",)
    def get_opening_coverage() -> OpeningCoverage:
        return owner.get_runtime().opening_plans.get_coverage()
