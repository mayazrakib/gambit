import json

from gambit.api.fact_contracts import FactQueryResult, MoveObservation, PositionReference
from gambit.api.structured import StructuredResponse
from gambit.engine.client import parse_move
from gambit.game.position import build_board, get_material, get_terminal_facts
from gambit.game.queries import ChessFactQuery, query_position_facts

def register_fact_tools(
    server,
    owner,
):
    @server.resource("gambit://contracts/v3/facts",)
    def get_structured_contract() -> str:
        return json.dumps({"schema_version": 3, "response": StructuredResponse.model_json_schema(), "position_reference": PositionReference.model_json_schema(), "fact_query": ChessFactQuery.model_json_schema(), "fact_query_result": FactQueryResult.model_json_schema(), "move_observation": MoveObservation.model_json_schema(),},)

    @server.tool(description="Get board state, material, legal moves, and optional rules answers without engine search. Supply fen with optional history, or game_id with expected_revision. Up to 64 queries and 24 hypothetical continuation plies. Attacks, legal captures, and pins are distinct; unknown repetition history stays unknown.",)
    def get_position(
        fen: str | None = None,
        history: list[str] | None = None,
        game_id: str | None = None,
        expected_revision: int | None = None,
        queries: list[ChessFactQuery] | None = None,
        continuation: list[str] | None = None,
    ) -> dict:
        if sum((value is not None for value in (fen, game_id)),) != 1:
            raise ValueError("Supply exactly one of fen or game_id.",)

        state = None

        if game_id is not None:
            runtime = owner.get_runtime()

            if history is not None:
                raise ValueError("Live queries use authoritative stored history.",)

            state = runtime.live.games.read(game_id,)

            if type(expected_revision,) is not int or state["revision"] != expected_revision:
                raise ValueError("Read the current position revision before querying facts.",)

            fen = state["root_fen"]
            history = state["history"]
        elif expected_revision is not None:
            raise ValueError("A standalone position has no revision.",)

        result = query_position_facts(
            fen,
            queries or [],
            history,
            continuation,
        )

        board = build_board(
            fen,
            history,
        )

        for notation in continuation or []:
            board.push(parse_move(
                board,
                notation,
            ),)

        terminal = get_terminal_facts(
            board,
            history is not None,
        )

        result.update({
            "fen": board.fen(),
            "side_to_move": terminal["side_to_move"],
            "legal_move_count": board.legal_moves.count(),
            "moves": [{"san": board.san(move,), "uci": move.uci(),} for move in board.legal_moves],
            "state": terminal,
            "material": get_material(board,),
        },)

        if state is not None:
            current = runtime.live.games.read(game_id,)

            if current["revision"] != expected_revision:
                raise ValueError("The position changed while querying facts.",)

            result["draw_claim"] = state.get("draw_claim",)
            result["source_reference"] = {"game_id": game_id, "revision": expected_revision,}

        return result

    @server.tool(description="Claim a draw in the active live game. The optional intended_move is checked without being played. Requires current game identifier and revision.",)
    def claim_live_draw(
        game_id: str,
        expected_revision: int,
        intended_move: str | None = None,
    ) -> dict:
        return owner.get_runtime().live.games.claim_draw(
            game_id,
            expected_revision,
            intended_move,
        )
