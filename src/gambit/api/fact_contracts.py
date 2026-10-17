from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

class PositionReference(BaseModel,):
    model_config = ConfigDict(
        extra="allow",
        strict=True,
    )

    fen: str
    history_id: str = Field(pattern="^[a-f0-9]{64}$",)

    history_scope: Literal[
        "complete",
        "supplied_root",
        "position_only",
    ]

class FactQueryResult(BaseModel,):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
    )

    query_index: int = Field(
        ge=0,
        le=63,
    )

    query: dict

    status: Literal[
        "supported",
        "refuted",
        "unknown",
    ]

    evidence: object
    reason_code: str | None
    evidence_kind: Literal["rules_verified"]

class MoveObservation(BaseModel,):
    model_config = ConfigDict(
        extra="allow",
        strict=True,
    )

    variation_id: str

    ply: int = Field(
        ge=1,
        le=24,
    )

    position_before: PositionReference
    position_after: PositionReference

    side: Literal[
        "white",
        "black",
    ]

    move_uci: str = Field(pattern="^[a-h][1-8][a-h][1-8][qrbn]?$",)
    move_san: str
    is_capture: bool
    is_castling: bool
    is_en_passant: bool
    facts: dict
    material_delta: dict
    evidence_kind: Literal["rules_verified"]
    scope: Literal["shown_variation"]
