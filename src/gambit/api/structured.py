import inspect
import json
from dataclasses import asdict, is_dataclass
from functools import wraps
from typing import Literal

from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict, Field

from gambit.api.fact_contracts import FactQueryResult, MoveObservation, PositionReference
from gambit.game.position import build_board, get_position_reference

REMOVED_FIELDS = frozenset({"speech_plan", "response_text", "model_instructions", "purpose_guidance", "interpretation_rule", "interpretation", "explanation", "next_question", "next_step", "question", "message", "grouping", "feasibility", "unresolved", "spoken", "continuation_rule", "speech_rate", "voice", "prompt", "selection",},)
LIMITATION_FIELDS = frozenset({"caveat", "interpretation_caveat", "practical_caveat", "played_move_caveat", "validation",},)

class StructuredResponse(BaseModel,):
    model_config = ConfigDict(
        extra="allow",
        strict=True,
    )

    schema_version: Literal[3] = 3

    status: Literal[
        'available',
        'unsupported',
        'unknown',
        'empty',
        'expired',
        'failed',
        'unavailable',
        'queued',
        'running',
        'completed',
        'cancelled',
        'interrupted',
    ] | None = None

    position_reference: PositionReference | None = None
    engine_evidence: dict | None = None
    facts: dict | None = None
    openings: dict | None = None
    statistics: dict | None = None
    tablebase: dict | None = None
    cloud: dict | None = None
    source: str | None = None
    reason_code: str | None = None
    limitation_codes: list[str] = Field(default_factory=list,)

def export_result(
    value,
    is_attributed=False,
    inherited_reference=None,
):
    if is_dataclass(value,):
        value = asdict(value,)

    if isinstance(
        value,
        (list, tuple),
    ):
        return [export_result(
            entry,
            is_attributed,
            inherited_reference,
        ) for entry in value]

    if not isinstance(
        value,
        dict,
    ):
        return value

    inherited_reference = value.get(
        "position_reference",
        inherited_reference,
    )

    if "query_index" in value and "evidence_kind" in value:
        FactQueryResult.model_validate(value,)

    if value.get("evidence_kind",) == "rules_verified" and "position_before" in value:
        MoveObservation.model_validate(value,)

    result = {}

    limitations = list(value.get(
        "limitation_codes",
        [],
    ),)

    for key, entry in value.items():
        if key == "schema_version":
            result[key] = 3
        elif key in REMOVED_FIELDS and not is_attributed:
            continue
        elif key in LIMITATION_FIELDS and not is_attributed:
            limitations.append("finite_search_not_proof" if key == "caveat" else "interpretation_unverified",)
        elif key == "observed_changes" and isinstance(
            entry,
            list,
        ) and any((isinstance(
            item,
            str,
        ) for item in entry),):
            limitations.append("legacy_observations_unavailable",)
            result[key] = []
        else:
            result[key] = export_result(
                entry,
                is_attributed or key in ("user_text", "source_text", "headers", "reasoning", "comments"),
                inherited_reference,
            )

    if "engine" in value and any((name in value for name in ("moves", "principal_variations", "lines")),):
        limitations.append("finite_search_not_proof",)

    if value.get("schema_version",) == 1:
        limitations.append("legacy_record_adapted",)

    if limitations:
        result["limitation_codes"] = sorted(set(limitations,),)

    if isinstance(
        result.get("fen",),
        str,
    ) and "position_reference" not in result and "history_id" not in result and (inherited_reference is None or inherited_reference.get("fen",) != result["fen"]):
        root = result.get(
            "root_fen",
            result["fen"],
        )

        history = result.get("history",) if "root_fen" in result else None

        board = build_board(
            root,
            history,
        )

        if board.fen() != result["fen"]:
            raise ValueError("The response position does not match its root and history.",)

        result["position_reference"] = get_position_reference(
            board,
            history is not None,
        )

    return result

def validate_public_result(
    value,
    arguments=None,
):
    result = export_result(value,)

    if not isinstance(
        result,
        dict,
    ):
        result = {"items": result,} if isinstance(
            result,
            list,
        ) else {"value": result,}

    arguments = arguments or {}

    if "position_reference" not in result:
        for name in ("assessment", "position_context", "features", "tablebase"):
            candidate = result.get(name,)

            if isinstance(
                candidate,
                dict,
            ) and candidate.get("position_reference",) is not None:
                result["position_reference"] = candidate["position_reference"]
                break

    if "position_reference" not in result and isinstance(
        arguments.get("fen",),
        str,
    ):
        board = build_board(
            arguments["fen"],
            arguments.get("history",),
        )

        result["position_reference"] = get_position_reference(
            board,
            arguments.get("history",) is not None,
        )

    result["schema_version"] = 3
    StructuredResponse.model_validate(result,)

    json.dumps(
        result,
        allow_nan=False,
    )

    return result

def wrap_structured_tool(function,):
    signature = inspect.signature(function,)

    if inspect.iscoroutinefunction(function,):
        @wraps(function,)
        async def invoke_async(
            *args,
            **kwargs,
        ):
            try:
                value = await function(
                    *args,
                    **kwargs,
                )

                return CallToolResult(
                    content=[],
                    structured_content=validate_public_result(
                        value,
                        signature.bind(
                            *args,
                            **kwargs,
                        ).arguments,
                    ),
                )
            except (ValueError, TypeError) as exception:
                raise ToolError(str(exception,),) from exception

        wrapped = invoke_async
    else:
        @wraps(function,)
        def invoke_sync(
            *args,
            **kwargs,
        ):
            try:
                value = function(
                    *args,
                    **kwargs,
                )

                return CallToolResult(
                    content=[],
                    structured_content=validate_public_result(
                        value,
                        signature.bind(
                            *args,
                            **kwargs,
                        ).arguments,
                    ),
                )
            except (ValueError, TypeError) as exception:
                raise ToolError(str(exception,),) from exception

        wrapped = invoke_sync

    wrapped.__signature__ = signature.replace(return_annotation=StructuredResponse,)

    wrapped.__annotations__ = {
        **function.__annotations__,
        "return": StructuredResponse,
    }

    return wrapped
