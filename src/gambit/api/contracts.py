from typing import Literal, NotRequired, TypedDict

class VersionedResponse(TypedDict):
    schema_version: int

class EngineIdentity(TypedDict):
    name: str
    version: str | None
    binary_sha256: str | None
    worker_count: int
    threads_per_worker: int
    hash_mb_per_worker: int
    is_reproducible: bool

class EngineScore(TypedDict):
    centipawns: int | None
    mate_in: int | None
    mating_side: Literal[
        "white",
        "black",
    ] | None

class VariationEvidence(TypedDict):
    rank: int
    evaluation: EngineScore
    moves_uci: list[str]
    moves_san: list[str]
    depth: int | None
    actual_nodes: int | None
    engine_time_ms: int | None

class PositionEvidence(VersionedResponse):
    id: str
    fen: str
    evaluation: EngineScore
    principal_variations: list[VariationEvidence]
    profile: str
    score_perspective: Literal["white"]
    configured_nodes: int
    elapsed_ms: float
    engine: EngineIdentity
    has_complete_history: bool
    history_scope: str
    evidence_status: Literal[
        "preliminary",
        "deeper search",
    ]

class AnalysisMetrics(VersionedResponse):
    search_count: int
    cache_hits: int
    pending_count: int
    sample_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    queue_p95_ms: float | None
    has_reserved_interactive_capacity: bool

class ProgressiveStart(VersionedResponse):
    request_id: str
    context_id: str
    position_fen: str
    status: str
    preliminary: PositionEvidence

class ProgressiveStatus(VersionedResponse):
    request_id: str
    context_id: str
    status: str
    analysis_id: str | None
    error: str | None

class GameJob(VersionedResponse):
    id: str
    status: str
    completed_searches: int
    pgn: str
    should_review: bool
    reused_searches: NotRequired[int]
    analysis_id: NotRequired[str]
    error: NotRequired[str | None]

class ConceptProgress(TypedDict):
    id: str
    learner_id: str
    concept: str
    attempts: int
    independent_successes: int
    interval_days: int
    due_at: str

class ConceptReport(VersionedResponse):
    concepts: list[ConceptProgress]

class ReviewLesson(TypedDict):
    id: str
    learner_id: str
    analysis_id: str
    topic: str
    root_fen: str
    history: list[str]
    fen: str
    status: str
    source: str
    question: str

class ReviewLessons(VersionedResponse):
    lessons: list[ReviewLesson]
    grouping: str

class OpeningPlanRecord(VersionedResponse):
    id: str
    position_key: str
    name: str
    fen: str
    plans: list[str]
    pawn_breaks: list[str]
    piece_placements: list[str]
    common_mistakes: list[str]
    source: str
    source_version: str
    source_date: str
    evidence_kind: str
    is_engine_verified: bool

class OpeningStatistics(VersionedResponse):
    id: NotRequired[str]
    position_key: str
    move_uci: str
    white_wins: int
    draws: int
    black_wins: int
    source: str
    source_date: str
    population: str

class OpeningPlanReport(VersionedResponse):
    plans: list[OpeningPlanRecord]
    practical_statistics: list[OpeningStatistics]
    caveat: str

class CoverageSource(TypedDict):
    collection: str
    source: str | None
    records: int
    positions: int
    first_imported_at: str
    last_updated_at: str

class OpeningCoverage(VersionedResponse):
    sources: list[CoverageSource]
    is_exhaustive_chess_coverage: bool
    source_limit: int
