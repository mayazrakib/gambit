from dataclasses import asdict
from unittest.mock import Mock, patch

import chess
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from gambit.live.opponent import OpponentSettings
from gambit.main import GambitMcpServer, mcp
from gambit.server.tools import register_tools

TOOL_NAMES = {
    'get_position',
    'get_evidence',
    'analyze_position',
    'analyze_move',
    'compare_moves',
    'read_board',
    'read_pgn',
    'analyze_game',
    'start_game_analysis',
    'get_analysis_job',
    'cancel_analysis_job',
    'get_analysis',
    'find_openings',
    'get_opening',
    'get_opening_stats',
    'get_puzzle',
    'get_game',
    'get_study',
    'get_cloud_analysis',
    'get_tablebase',
    'get_chesscom_games',
    'get_live_game',
    'analyze_live_game',
    'annotate_live_game',
    'claim_live_draw',
    'get_capabilities',
    'get_metrics',
}

@pytest.fixture
def interface(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv(
        'GAMBIT_RUNTIME_DIRECTORY',
        str(tmp_path,),
    )

    server = GambitMcpServer(name='interface-test',)
    owner = register_tools(server,)

    try:
        yield server, owner
    finally:
        if owner.runtime is not None:
            owner.runtime.close()

@pytest.mark.asyncio
async def test_catalog_replaces_the_old_interface():
    tools = await mcp.list_tools()
    assert {tool.name for tool in tools} == TOOL_NAMES
    assert len(tools,) == 27
    assert all((tool.input_schema['additionalProperties'] is False for tool in tools),)
    descriptions = {tool.name: tool.description for tool in tools}
    assert 'White-relative' in descriptions['analyze_position']
    assert 'stale' in descriptions['analyze_live_game']

@pytest.mark.asyncio
async def test_position_queries_need_no_runtime_and_preserve_hypothetical_history(interface,):
    server, owner = interface
    cycle = ['Nf3', 'Nf6', 'Ng1', 'Ng8',]

    with patch.object(
        owner,
        'get_runtime',
        side_effect=AssertionError('Runtime started',),
    ):
        result = await server.call_tool(
            'get_position',
            {
                'fen': chess.STARTING_FEN,
                'history': cycle,
                'continuation': cycle,
                'queries': [{'predicate': 'repetition_claim',},],
            },
        )

        unknown = await server.call_tool(
            'get_position',
            {'fen': chess.STARTING_FEN,},
        )

    report = result.structured_content
    assert report['scope'] == 'hypothetical'
    assert report['position_reference']['history_scope'] == 'complete'
    assert report['results'][0]['status'] == 'supported'
    assert report['state']['can_claim_threefold_repetition'] is True
    assert report['state']['is_terminal'] is False
    assert report['legal_move_count'] == len(report['moves'],) == 20
    assert {'san': 'e4', 'uci': 'e2e4',} in report['moves']
    assert unknown.structured_content['state']['can_claim_threefold_repetition'] is None
    assert report['root_reference']['history_id'] != report['position_reference']['history_id']

@pytest.mark.asyncio
async def test_live_position_queries_preserve_game_and_reject_stale_revisions(interface,):
    server, owner = interface
    games = owner.get_runtime().live.games
    game = games.create(asdict(OpponentSettings(),),)
    before = games.read(game['game_id'],)
    arguments = {'game_id': game['game_id'], 'expected_revision': 0, 'continuation': ['e4',],}

    report = (await server.call_tool(
        'get_position',
        arguments,
    )).structured_content

    assert report['side_to_move'] == 'black'
    assert games.read(game['game_id'],) == before

    with pytest.raises(
        ToolError,
        match='revision',
    ):
        await server.call_tool(
            'get_position',
            {**arguments, 'expected_revision': 1,},
        )

@pytest.mark.asyncio
@pytest.mark.parametrize(
    'arguments',
    [
        {},
        {'positions': [],},
        {'fen': chess.STARTING_FEN, 'positions': [{'fen': chess.STARTING_FEN,},],},
        {'positions': [{'fen': chess.STARTING_FEN,},], 'history': [],},
        {'positions': [{'fen': chess.STARTING_FEN,}, {'fen': 'invalid',},],},
        {'positions': [{'fen': chess.STARTING_FEN,},] * 129,},
        {'fen': chess.STARTING_FEN, 'nodes': 100,},
        {'fen': chess.STARTING_FEN, 'multipv': 3,},
    ],
)
async def test_invalid_analysis_requests_fail_before_runtime_start(
    interface,
    arguments,
):
    server, owner = interface

    with patch.object(
        owner,
        'get_runtime',
        side_effect=AssertionError('Runtime started',),
    ):
        with pytest.raises(ToolError,):
            await server.call_tool(
                'analyze_position',
                arguments,
            )

@pytest.mark.asyncio
async def test_single_and_batch_analysis_share_history_scores_and_evidence(interface,):
    server, owner = interface
    runtime = owner.get_runtime()

    def analyze(
        board,
        multipv,
        nodes,
    ):
        return [{'centipawns': 30, 'mate_in': None, 'pv': [next(iter(board.legal_moves,),),],},]

    with patch.object(
        runtime.analysis.engine,
        'analyze',
        side_effect=analyze,
    ):
        single = (await server.call_tool(
            'analyze_position',
            {'fen': chess.STARTING_FEN, 'history': ['e4',],},
        )).structured_content

        batch = (await server.call_tool(
            'analyze_position',
            {'positions': [{'fen': chess.STARTING_FEN, 'history': ['e4',],}, {'fen': chess.STARTING_FEN,},],},
        )).structured_content['items']

    assert single['id'] == batch[0]['id']
    assert single['evaluation']['centipawns'] == -30
    assert batch[1]['evaluation']['centipawns'] == 30
    assert single['position_reference']['history_scope'] == 'complete'
    assert batch[1]['position_reference']['history_scope'] == 'position_only'
    assert all((item['score_perspective'] == 'white' for item in batch),)
    assert all((item['evidence_status'] == 'preliminary' for item in batch),)
    assert all((item['profile'] == 'instant' for item in batch),)
    assert batch[0]['position_reference']['fen'] == single['position_reference']['fen']

@pytest.mark.asyncio
@pytest.mark.parametrize(
    'tool,method,arguments,expected',
    [
        ('get_opening_stats', 'opening', {'fen': chess.STARTING_FEN,}, (chess.STARTING_FEN, None, None)),
        ('get_puzzle', 'puzzle', {'puzzle_id': 'fixture',}, ('fixture', None, False)),
        ('get_game', 'game', {'game_id': 'fixture', 'population': 'masters',}, ('fixture', 'masters')),
        ('get_study', 'study', {'study_id': 'study', 'chapter_id': 'chapter',}, ('study', 'chapter')),
        ('get_cloud_analysis', 'cloud', {'fen': chess.STARTING_FEN,}, (chess.STARTING_FEN, 1)),
        ('get_tablebase', 'tablebase', {'fen': chess.STARTING_FEN, 'history': [],}, (chess.STARTING_FEN, [])),
        ('get_chesscom_games', 'chesscom', {'username': 'fixture', 'year': 2026, 'month': 10,}, ('fixture', 2026, 10, 0, 5)),
    ],
)
async def test_renamed_provider_tools_preserve_arguments_and_attribution(
    interface,
    tool,
    method,
    arguments,
    expected,
):
    server, owner = interface
    provider = Mock(return_value={'source': 'fixture-provider', 'status': 'available',},)

    with patch.object(
        owner.get_runtime().providers,
        method,
        provider,
    ):
        result = await server.call_tool(
            tool,
            arguments,
        )

    provider.assert_called_once_with(*expected,)
    assert result.content == []
    assert result.structured_content['source'] == 'fixture-provider'
    assert result.structured_content['schema_version'] == 3
