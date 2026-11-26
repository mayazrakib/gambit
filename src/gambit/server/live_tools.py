from typing import Literal

from gambit.engine.client import execute_engine_request

def register_live_tools(
    server,
    owner,
):
    @server.tool(description="Read the active live game. History is omitted by default; known_revision omits unchanged state. Use analyze_live_game for combined analysis and board annotations.",)
    def get_live_game(
        game_id: str | None = None,
        known_revision: int | None = None,
        should_include_history: bool = False,
    ) -> dict[
        str,
        object,
    ]:
        return owner.get_runtime().live.get_game(
            game_id,
            known_revision,
            should_include_history,
        )

    @server.tool(description="Analyze the active live position and draw matching annotations. Supply the known game identifier and revision; stale results are rejected. Defaults to instant evidence. Hint mode hides solutions. The client writes explanations and supplies audio. Do not poll the board.",)
    async def analyze_live_game(
        expected_revision: int | None = None,
        game_id: str | None = None,
        intent: Literal[
            "explain",
            "hint",
            "compare",
            "endgame",
        ] = "explain",
        profile: Literal[
            "instant",
            "quick",
            "deep",
        ] = "instant",
        known_analysis_id: str | None = None,
    ) -> dict[
        str,
        object,
    ]:
        return await execute_engine_request(
            owner.get_runtime().live.teach,
            expected_revision,
            game_id,
            intent,
            profile,
            known_analysis_id,
        )

    @server.tool(description="Replace the tutor's annotations on the live board without moving pieces. Match game_id and expected_revision. Up to 32 marks: from square, optional to square for an arrow, optional color blue/green/amber/red, and optional label. Empty marks clear tutor annotations. Do not reveal solutions in hints.",)
    def annotate_live_game(
        game_id: str,
        expected_revision: int,
        marks: list[dict[
            str,
            str,
        ]],
    ) -> dict[
        str,
        object,
    ]:
        live = owner.get_runtime().live

        live.games.annotate(
            game_id,
            expected_revision,
            marks,
        )

        return {"game_id": game_id, "revision": expected_revision, "annotation_count": len(marks,),}
