from dataclasses import dataclass
from threading import Event
from typing import TYPE_CHECKING, Literal

import chess

from gambit.engine.client import EngineLine, check_request_active, parse_move
from gambit.game.position import build_board, get_position_reference, replay_variation
from gambit.game.service import EngineEvaluation, get_variation, normalize_evaluation

if TYPE_CHECKING:
    from gambit.engine.analysis import EnginePool

SERIOUS_LOSS_CP = 150
ACCEPTABLE_LOSS_CP = 30
COMPACT_VARIATION_PLIES = 4
FULL_VARIATION_PLIES = 24

@dataclass(frozen=True,)
class CandidateEvidence:
    move_uci: str
    move_san: str
    evaluation: EngineEvaluation
    variation_uci: list[str]
    variation_san: list[str]
    centipawn_loss: int | None
    mate_change: str | None
    depth: int
    actual_nodes: int
    observed_changes: list[dict]
    score_perspective: str = "white"
    mate_unit: str = "moves"

@dataclass(frozen=True,)
class MoveAssessment:
    schema_version: int
    fen: str
    root_fen: str
    history: list[str]

    evidence_status: Literal[
        "preliminary",
        "deeper confirmation",
        "unstable",
    ]

    classification: Literal[
        "acceptable",
        "inaccuracy",
        "serious mistake",
        "uncertain",
    ]

    preliminary: CandidateEvidence
    verified: CandidateEvidence
    best_move_uci: str
    limitation_codes: list[str]
    position_reference: dict

def classify_loss(
    best: EngineLine,
    candidate: EngineLine,
) -> tuple[
    int | None,
    str | None,
    str,
]:
    if best.get(
        "score_bound",
        "exact",
    ) != "exact" or candidate.get(
        "score_bound",
        "exact",
    ) != "exact":
        return None, "bounded_score", "uncertain"

    best_mate = best["mate_in"]
    candidate_mate = candidate["mate_in"]

    if best_mate is not None or candidate_mate is not None:
        if candidate_mate is not None and candidate_mate > 0:
            return None, "preserves forced mate", "acceptable"

        if best_mate is not None and best_mate > 0:
            return None, "loses forced mate", "serious mistake"

        if candidate_mate is not None and candidate_mate < 0:
            if best_mate is not None and best_mate < 0:
                return None, "already facing forced mate", "uncertain"

            return None, "allows forced mate", "serious mistake"

        return None, "mate evidence differs", "uncertain"

    if best["centipawns"] is None or candidate["centipawns"] is None:
        return None, None, "uncertain"

    loss = max(
        0,
        best["centipawns"] - candidate["centipawns"],
    )

    classification = "serious mistake" if loss >= SERIOUS_LOSS_CP else "inaccuracy"

    return loss, None, "acceptable" if loss <= ACCEPTABLE_LOSS_CP else classification

def create_evidence(
    board: chess.Board,
    best: EngineLine,
    candidate: EngineLine,
    max_variation_plies: int = FULL_VARIATION_PLIES,
) -> CandidateEvidence:
    variation = get_variation(
        board,
        candidate["pv"][:max_variation_plies],
    )

    if not variation:
        raise RuntimeError("The engine returned no legal candidate variation.",)

    loss, mate_change, _ = classify_loss(
        best,
        candidate,
    )

    observations = replay_variation(
        board,
        [entry["uci"] for entry in variation],
    )

    return CandidateEvidence(
        variation[0]["uci"],
        variation[0]["san"],
        normalize_evaluation(
            candidate["centipawns"],
            candidate["mate_in"],
            board.turn,
        ),
        [move["uci"] for move in variation],
        [move["san"] for move in variation],
        loss,
        mate_change,
        candidate.get(
            "depth",
            0,
        ),
        candidate.get(
            "actual_nodes",
            0,
        ),
        observations,
    )

def assess_move(
    engine: "EnginePool",
    fen: str,
    move: str,
    history: list[str] | None = None,
    cancellation: Event | None = None,
    *,
    profile: str = "instant",
    baseline_lines: dict[
        int,
        EngineLine,
    ] | None = None,
    candidate_lines: dict[
        int,
        EngineLine,
    ] | None = None,
) -> MoveAssessment:
    if profile not in ("instant", "quick", "deep"):
        raise ValueError("Analysis profile must be instant, quick, or deep.",)

    board = build_board(
        fen,
        history,
    )

    if board.is_game_over():
        raise ValueError("A terminal position cannot be assessed for a new move.",)

    candidate = parse_move(
        board,
        move,
    )

    stages = []

    budgets = (
        (engine.configuration.quick_nodes, engine.configuration.deep_nodes)
        if profile == "deep"
        else (getattr(
            engine.configuration,
            profile + "_nodes",
        ),)
    )

    for nodes in budgets:
        check_request_active(cancellation,)
        best = baseline_lines.get(nodes,) if baseline_lines is not None else None

        if best is None:
            best = engine.analyze(
                board,
                1,
                nodes,
                cancellation=cancellation,
            )[0]

        selected = best

        if best["pv"][0] != candidate:
            selected = candidate_lines.get(nodes,) if candidate_lines is not None else None

            if selected is None:
                selected = engine.analyze(
                    board,
                    1,
                    nodes,
                    root_moves=(candidate.uci(),),
                    cancellation=cancellation,
                )[0]

        if not selected["pv"] or selected["pv"][0] != candidate:
            raise RuntimeError("The engine did not return the requested root candidate.",)

        stages.append((best, selected, classify_loss(
            best,
            selected,
        )[2]),)

    preliminary = stages[0]
    verified = stages[-1]
    is_stable = preliminary[2] == verified[2] and preliminary[0]["pv"][0] == verified[0]["pv"][0]
    has_deeper_budget = len(budgets,) > 1 and budgets[-1] > budgets[0]

    has_more_work = all((verified[index].get(
        "actual_nodes",
        0,
    ) > preliminary[index].get(
        "actual_nodes",
        0,
    )
        or verified[index].get(
            "depth",
            0,
        ) > preliminary[index].get(
            "depth",
            0,
        )
        for index in (0, 1)),)

    status = "deeper confirmation" if is_stable and has_deeper_budget else "unstable"

    if not has_deeper_budget or not has_more_work:
        status = "preliminary"

    variation_plies = FULL_VARIATION_PLIES if profile == "deep" else COMPACT_VARIATION_PLIES

    preliminary_evidence = create_evidence(
        board,
        preliminary[0],
        preliminary[1],
        variation_plies,
    )

    verified_evidence = preliminary_evidence if len(stages,) == 1 else create_evidence(
        board,
        verified[0],
        verified[1],
        variation_plies,
    )

    return MoveAssessment(
        3,
        board.fen(),
        fen,
        history or [],
        status,
        verified[2] if status == "deeper confirmation" else "uncertain",
        preliminary_evidence,
        verified_evidence,
        verified[0]["pv"][0].uci(),
        ["finite_search_not_proof", "search_agreement_not_probability",],
        get_position_reference(
            board,
            history is not None,
        ),
    )
