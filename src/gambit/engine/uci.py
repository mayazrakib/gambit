from typing import Literal, NotRequired, TypedDict

import chess

class EngineLine(TypedDict,):
    centipawns: int | None
    mate_in: int | None
    pv: list[chess.Move]

    score_bound: NotRequired[Literal[
        "exact",
        "lower",
        "upper",
    ]]

    depth: NotRequired[int]
    actual_nodes: NotRequired[int]
    engine_time_ms: NotRequired[int]

def get_uci_token_index(
    tokens: list[str],
    token: str,
) -> int | None:
    try:
        return tokens.index(token,)
    except ValueError:
        return None

def get_uci_integer(
    tokens: list[str],
    token: str,
    default: int,
) -> int:
    token_index = get_uci_token_index(
        tokens,
        token,
    )

    if token_index is None or token_index + 1 >= len(tokens,):
        return default

    try:
        return int(tokens[token_index + 1],)
    except ValueError:
        return default

def parse_analysis_line(
    tokens: list[str],
    metrics: dict[
        str,
        int,
    ],
) -> tuple[
    int,
    EngineLine,
] | None:
    rank = get_uci_integer(
        tokens,
        "multipv",
        default=1,
    )

    score_index = get_uci_token_index(
        tokens,
        "score",
    )

    pv_index = get_uci_token_index(
        tokens,
        "pv",
    )

    if score_index is None or pv_index is None or score_index + 2 >= len(tokens,):
        return None

    if "lowerbound" in tokens or "upperbound" in tokens:
        return None

    score_type = tokens[score_index + 1]

    if score_type not in ("cp", "mate"):
        return None

    score_value = int(tokens[score_index + 2],)
    moves: list[chess.Move] = []

    for token in tokens[pv_index + 1 :]:
        try:
            moves.append(chess.Move.from_uci(token,),)
        except ValueError as exception:
            raise RuntimeError("Stockfish returned malformed principal variation notation.",) from exception

    return rank, {
        "centipawns": score_value if score_type == "cp" else None,
        "mate_in": score_value if score_type == "mate" else None,
        "pv": moves,
        "score_bound": "exact",
        "depth": metrics.get(
            "depth",
            0,
        ),
        "actual_nodes": metrics.get(
            "nodes",
            0,
        ),
        "engine_time_ms": metrics.get(
            "time",
            0,
        ),
    }
