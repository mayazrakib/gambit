import atexit
import threading
from typing import Literal

from pydantic import BaseModel, ConfigDict

from gambit.engine.analysis import AnalysisService, EnginePool, compact_position_evidence
from gambit.engine.client import execute_engine_request
from gambit.game.evidence import Evidence
from gambit.game.position import build_board
from gambit.game.service import MAX_BATCH_POSITIONS
from gambit.infrastructure.configuration import load_configuration
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge
from gambit.live.service import LiveWorkspace
from gambit.providers.http import ProviderHttp
from gambit.providers.service import ExplorerOptions, Providers

Profile = Literal[
    'instant',
    'quick',
    'deep',
]

Section = Literal[
    'facts',
    'analysis',
    'openings',
    'statistics',
    'cloud',
    'tablebase',
]

class PositionRequest(BaseModel,):
    model_config = ConfigDict(
        extra='forbid',
        strict=True,
    )

    fen: str
    history: list[str] | None = None

class Runtime:
    def __init__(
        self,
        engine: EnginePool | None = None,
    ) -> None:
        self.configuration = load_configuration()
        self.store = Store(self.configuration.cache_capacity,)

        self.analysis = AnalysisService(
            self.configuration,
            self.store,
            engine,
        )

        self.knowledge = Knowledge(self.configuration.runtime_directory,)
        self.http = ProviderHttp(self.configuration,)
        self.providers = Providers(self.http,)

        self.evidence = Evidence(
            self.analysis,
            self.knowledge,
            self.providers,
        )

        self.live = LiveWorkspace(self,)
        self.is_closed = False

    def close(self,) -> None:
        if self.is_closed:
            return

        self.is_closed = True
        self.live.close()
        self.analysis.close()
        self.http.close()
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
) -> RuntimeOwner:
    owner = RuntimeOwner(engine,)
    from gambit.server.fact_tools import register_fact_tools
    from gambit.server.live_http import register_live_http
    from gambit.server.live_tools import register_live_tools
    from gambit.server.provider_tools import register_provider_tools

    register_fact_tools(
        server,
        owner,
    )

    register_live_http(
        server,
        owner,
    )

    register_live_tools(
        server,
        owner,
    )

    register_provider_tools(
        server,
        owner,
    )

    @server.tool(description='Get contract, retention, and provider capabilities without engine startup or network requests.',)
    def get_capabilities() -> dict:
        return {'contract_version': 3, 'persistent_data': ['opening_classifications',], 'temporary_state': ['active_game', 'engine_evidence', 'api_cache', 'analysis_jobs',], 'providers': ['lichess', 'explorer', 'tablebase', 'chesscom',], 'explanation_provider': 'client', 'limitations': ['finite_search_not_proof', 'client_explanation_unverified', 'provider_coverage_not_exhaustive',], 'game_sharing': 'same_process_only',}

    @server.tool(description='Get selected evidence sections in one call. Defaults to local facts and instant preliminary analysis. External sources are opt-in. Scores are White-relative.',)
    async def get_evidence(
        fen: str,
        history: list[str] | None = None,
        sections: list[Section] | None = None,
        profile: Profile = 'instant',
        is_compact: bool = True,
        known_analysis_id: str | None = None,
        explorer: ExplorerOptions | None = None,
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().evidence.collect,
            fen,
            history,
            sections,
            profile,
            is_compact,
            known_analysis_id,
            explorer,
        )

    @server.tool(description='Analyze one position or a batch of up to 128 positions with Stockfish. Supply fen with optional history, or positions containing fen and optional history. Batches return items in request order. Instant and quick are preliminary; deep is finite search, not proof. Scores are White-relative.',)
    async def analyze_position(
        fen: str | None = None,
        profile: Profile = 'instant',
        history: list[str] | None = None,
        is_compact: bool = True,
        positions: list[PositionRequest] | None = None,
    ) -> dict:
        if (fen is None) == (positions is None):
            raise ValueError('Supply exactly one of fen or positions.',)

        if positions is not None and history is not None:
            raise ValueError('Batch history belongs to each position.',)

        requests = positions if positions is not None else [
            PositionRequest(
                fen=fen,
                history=history,
            ),
        ]

        if not 1 <= len(requests,) <= MAX_BATCH_POSITIONS:
            raise ValueError(f'Supply between one and {MAX_BATCH_POSITIONS} positions.',)

        for request in requests:
            build_board(
                request.fen,
                request.history,
            )

        analysis = owner.get_runtime().analysis
        results = []

        for request in requests:
            result = await execute_engine_request(
                analysis.evaluate,
                request.fen,
                profile,
                request.history,
            )

            results.append(compact_position_evidence(result,) if is_compact else result,)

        return {'items': results,} if positions is not None else results[0]

    @server.tool(description='Analyze a legal move against the best alternatives and replies. Preserves history, preliminary status, and score bounds. Scores are White-relative.',)
    async def analyze_move(
        fen: str,
        move: str,
        profile: Profile = 'instant',
        history: list[str] | None = None,
        is_compact: bool = True,
    ) -> dict:
        result = await execute_engine_request(
            owner.get_runtime().analysis.evaluate_move,
            fen,
            move,
            profile,
            history,
        )

        if is_compact:
            result['before'] = compact_position_evidence(result['before'],)
            result['after'] = compact_position_evidence(result['after'],)

        return result

    @server.tool(description='Compare up to eight legal moves from the same position. Returns evaluations and best replies under the same search budget. Scores are White-relative.',)
    async def compare_moves(
        fen: str,
        moves: list[str],
        profile: Profile = 'instant',
        history: list[str] | None = None,
    ) -> dict:
        if not 1 <= len(moves,) <= 8:
            raise ValueError('Compare between one and eight candidates.',)

        return {
            'comparisons': [await analyze_move(
                fen,
                move,
                profile,
                history,
            ) for move in moves],
        }

    @server.tool(description='Retrieve temporary full evidence. References expire on eviction or restart.',)
    def get_analysis(analysis_id: str,) -> dict:
        return owner.get_runtime().store.get(
            'analysis',
            analysis_id,
        ) or {'status': 'expired', 'reason_code': 'evidence_reference_expired', 'id': analysis_id,}

    @server.tool(description='Start a bounded in-memory whole-game analysis job. No game or checkpoint survives restart.',)
    def start_game_analysis(
        pgn: str,
        should_review: bool = True,
    ) -> dict:
        return owner.get_runtime().analysis.start_job(
            pgn,
            should_review,
        )

    @server.tool(description='Read temporary job progress. Missing references are expired.',)
    def get_analysis_job(job_id: str,) -> dict:
        return owner.get_runtime().store.get(
            'job',
            job_id,
        ) or {'status': 'expired', 'reason_code': 'job_reference_expired',}

    @server.tool(description='Cancel a temporary analysis job at its next bounded search boundary.',)
    def cancel_analysis_job(job_id: str,) -> dict:
        return owner.get_runtime().analysis.cancel_job(job_id,)

    @server.tool(description='Read bounded process-local search and cache latency metrics.',)
    def get_metrics() -> dict:
        return owner.get_runtime().analysis.engine.get_metrics()

    @server.tool(description='Find opening names and ECO codes in the pinned local classification corpus. This is not complete opening theory.',)
    def find_openings(
        query: str,
        offset: int = 0,
        limit: int = 12,
    ) -> dict:
        return owner.get_runtime().knowledge.search_openings(
            query,
            offset,
            limit,
        )

    @server.tool(description='Get transposition-matched classifications and corpus continuations. Corpus membership does not establish move quality.',)
    def get_opening(
        fen: str,
        offset: int = 0,
        limit: int = 12,
    ) -> dict:
        return owner.get_runtime().knowledge.find_moves(
            fen,
            offset,
            limit,
        )

    @server.resource('gambit://contracts/v3',)
    def get_contract() -> dict:
        return {'schema_version': 3, 'evidence_kinds': ['rules_verified', 'engine_analysis', 'opening_classification', 'observed_game_statistics', 'tablebase', 'attributed_source',], 'score_perspective': 'white_for_engine_scores', 'retention': 'openings_only_on_disk', 'limitations': ['finite_search_not_proof', 'client_explanation_unverified',],}

    @server.prompt(description='Use matching chess evidence and qualify unsupported claims.',)
    def analyze_chess(fen: str,) -> str:
        return f'Analyze {fen}. Use get_evidence with only needed sections, or get_position for rules. Preserve history identity, score perspective, bounds, and source limitations. Verify concrete explanations; qualify or omit unsupported claims. Treat statistics as observations and source commentary as advice. Reuse matching evidence. Never present finite search as proof.'

    return owner
