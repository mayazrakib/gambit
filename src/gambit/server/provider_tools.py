from typing import Literal

from gambit.engine.client import execute_engine_request
from gambit.providers.service import ExplorerOptions

def register_provider_tools(
    server,
    owner,
):
    @server.tool(description='Get attributed Masters or Lichess move outcomes and examples. Preserve population, filters, and sample sizes; popularity is not quality.',)
    async def get_opening_stats(
        fen: str,
        history: list[str] | None = None,
        options: ExplorerOptions | None = None,
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().providers.opening,
            fen,
            history,
            options,
        )

    @server.tool(description='Retrieve one public puzzle by ID or theme. Solutions and themes are hidden unless explicitly revealed. No learner tracking.',)
    async def get_puzzle(
        puzzle_id: str | None = None,
        angle: str | None = None,
        should_reveal: bool = False,
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().providers.puzzle,
            puzzle_id,
            angle,
            should_reveal,
        )

    @server.tool(description='Retrieve one attributed Lichess or Masters game as validated PGN through its API.',)
    async def get_game(
        game_id: str,
        population: Literal[
            'lichess',
            'masters',
        ] = 'lichess',
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().providers.game,
            game_id,
            population,
        )

    @server.tool(description='Retrieve one explicitly selected public study chapter with annotations. Source advice is not engine-verified. No arbitrary study search.',)
    async def get_study(
        study_id: str,
        chapter_id: str,
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().providers.study,
            study_id,
            chapter_id,
        )

    @server.tool(description='Retrieve existing Lichess cloud analysis, if available. Does not request remote engine execution or replace local verification.',)
    async def get_cloud_analysis(
        fen: str,
        multipv: int = 1,
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().providers.cloud,
            fen,
            multipv,
        )

    @server.tool(description='Probe the remote tablebase API for up to seven pieces without castling rights. Preserve category and draw-rule conditions. No local files.',)
    async def get_tablebase(
        fen: str,
        history: list[str] | None = None,
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().providers.tablebase,
            fen,
            history,
        )

    @server.tool(description='Retrieve a bounded page from one Chess.com account month. Explicit account required. API-only, no disk storage or personal index.',)
    async def get_chesscom_games(
        username: str,
        year: int,
        month: int,
        offset: int = 0,
        limit: int = 5,
    ) -> dict:
        return await execute_engine_request(
            owner.get_runtime().providers.chesscom,
            username,
            year,
            month,
            offset,
            limit,
        )
