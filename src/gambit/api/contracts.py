from typing import Literal, NotRequired, TypedDict

class VersionedResponse(TypedDict,):
    schema_version: Literal[3]

class EngineIdentity(TypedDict,):
    name: str
    version: str | None
    binary_sha256: str | None
    worker_count: int
    threads_per_worker: int
    hash_mb_per_worker: int
    is_reproducible: bool

class EngineScore(TypedDict,):
    centipawns: int | None
    mate_in: int | None

    mating_side: Literal[
        "white",
        "black",
    ] | None

class VariationEvidence(TypedDict,):
    rank: int
    observations: NotRequired[list[dict]]
    evaluation: EngineScore
    moves_uci: list[str]
    moves_san: list[str]
    depth: int | None
    actual_nodes: int | None
    engine_time_ms: int | None

    score_bound: NotRequired[Literal[
        "exact",
        "lower",
        "upper",
    ]]

    mate_unit: NotRequired[Literal["moves"]]

class PositionEvidence(VersionedResponse,):
    is_compact: NotRequired[bool]
    id: str
    fen: str
    position_reference: dict
    limitation_codes: list[str]
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

class AnalysisMetrics(VersionedResponse,):
    search_count: int
    cache_hits: int
    pending_count: int
    sample_count: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    queue_p95_ms: float | None
    has_reserved_interactive_capacity: bool

class GameJob(VersionedResponse,):
    id: str
    status: str
    completed_searches: int
    pgn: str
    should_review: bool
    reused_searches: NotRequired[int]
    analysis_id: NotRequired[str]
    error: NotRequired[str | None]
