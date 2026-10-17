import json
import sqlite3
from dataclasses import asdict
from unittest.mock import patch

import chess
import pytest

from gambit.engine.analysis import AnalysisService
from gambit.game.evidence import Evidence
from gambit.infrastructure.cleanup import clean_runtime
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge
from gambit.live.games import LiveConflict, LiveGames
from gambit.live.opponent import OpponentSettings
from gambit.main import mcp
from gambit.providers.http import ProviderHttp
from gambit.providers.service import Providers

def test_state_is_bounded_isolated_and_expires_on_restart():
    first = Store(capacity=2,)
    games = LiveGames(first,)
    games.create(asdict(OpponentSettings(),),)

    for number in range(3,):
        first.put(
            'analysis',
            str(number,),
            {'id': str(number,),},
        )

    assert first.get(
        'analysis',
        '0',
    ) is None

    assert len(first.records['analysis'],) == 2

    result = first.get(
        'analysis',
        '2',
    )

    result['id'] = 'mutated'

    assert first.get(
        'analysis',
        '2',
    )['id'] == '2'

    with pytest.raises(LiveConflict,):
        LiveGames(Store(),).read()

    first.close()

    assert first.get(
        'analysis',
        '2',
    ) is None

def test_rules_only_request_starts_no_engine_or_network_and_marks_unknown_history(tmp_path,):
    store = Store()

    analysis = AnalysisService(
        Configuration(),
        store,
    )

    http = ProviderHttp(Configuration(),)

    evidence = Evidence(
        analysis,
        Knowledge(str(tmp_path,),),
        Providers(http,),
    )

    try:
        with patch.object(
            analysis.engine,
            'analyze',
            side_effect=AssertionError('engine started',),
        ), patch.object(
            http.client,
            'stream',
            side_effect=AssertionError('network accessed',),
        ):
            report = evidence.collect(
                chess.STARTING_FEN,
                sections=['facts',],
            )

        assert report['facts']['state']['can_claim_threefold_repetition'] is None
        assert 'prior_repetition_history_unknown' in report['limitation_codes']
        assert list(tmp_path.iterdir(),) == []
    finally:
        analysis.close()
        http.close()

def test_opening_snapshot_is_validated_atomic_and_transposition_aware(tmp_path,):
    knowledge = Knowledge(str(tmp_path,),)
    knowledge.load()
    assert len(knowledge.records,) == 3864
    first = chess.Board()
    second = chess.Board()

    for move in ('Nf3', 'd5', 'g3'):
        first.push_san(move,)

    for move in ('g3', 'd5', 'Nf3'):
        second.push_san(move,)

    assert knowledge.find_moves(first.fen(),)['records'] == knowledge.find_moves(second.fen(),)['records']
    revision = 'a' * 40
    rows = [{'eco': 'A00', 'name': 'Example', 'pgn': '1. e4',},]

    knowledge.publish(
        revision,
        rows,
    )

    before = (tmp_path / 'openings.json').read_bytes()

    with pytest.raises(ValueError,):
        knowledge.publish(
            'b' * 40,
            [{'eco': 'A00', 'name': 'Invalid', 'pgn': '1. e5',},],
        )

    assert (tmp_path / 'openings.json').read_bytes() == before
    assert Knowledge(str(tmp_path,),).search_openings('Example',)['revision'] == revision
    assert not list(tmp_path.glob('.openings-*',),)

def test_cleanup_is_idempotent_and_preserves_unknown_files_openings_and_symlinks(tmp_path,):
    runtime = tmp_path / 'runtime'
    runtime.mkdir()
    database = runtime / 'gambit.sqlite3'

    with sqlite3.connect(database,) as connection:
        connection.execute('CREATE TABLE record (id TEXT)',)

    (runtime / 'datasets.json').write_text('{}',)
    (runtime / 'openings.json').write_text('{}',)
    (runtime / '.env').write_text('KEEP=private',)
    (runtime / 'unrelated.txt').write_text('keep',)
    downloads = runtime / 'downloads'
    downloads.mkdir()
    (downloads / 'personal-example-2025-01.json').write_text('{}',)
    (downloads / 'lichess_db_puzzle.csv.zst').write_bytes(b'dataset',)
    tablebase = runtime / 'syzygy'
    tablebase.mkdir()
    (tablebase / 'KRvK.rtbw').write_bytes(b'table',)
    outside = tmp_path / 'outside.sqlite3'
    outside.write_text('preserve',)
    (runtime / 'linked.sqlite3').symlink_to(outside,)
    preview = clean_runtime(str(runtime,),)
    assert preview['removed_files'] == 0 and database.exists()

    result = clean_runtime(
        str(runtime,),
        True,
    )

    assert result['removed_files'] == len(preview['targets'],) == 5
    assert not database.exists()
    assert (runtime / 'openings.json').exists() and (runtime / '.env').exists()
    assert (runtime / 'unrelated.txt').exists() and outside.read_text() == 'preserve'

    assert clean_runtime(
        str(runtime,),
        True,
    )['removed_files'] == 0

@pytest.mark.asyncio
async def test_mcp_contract_has_no_learner_tools_and_no_duplicate_text():
    tools = await mcp.list_tools()
    names = {tool.name for tool in tools}
    assert not {'create_tutor_turn', 'start_tutor_session', 'update_learner_profile', 'manage_chess_data', 'start_practice', 'get_due_reviews',} & names
    assert {'get_evidence', 'get_position', 'get_chesscom_games', 'get_tablebase',} <= names

    result = await mcp.call_tool(
        'get_evidence',
        {'fen': chess.STARTING_FEN, 'sections': ['facts',],},
    )

    assert result.content == []
    assert result.structured_content['schema_version'] == 3
    assert result.structured_content['position_reference']['fen'] == chess.STARTING_FEN

    expired = await mcp.call_tool(
        'get_analysis',
        {'analysis_id': 'missing',},
    )

    assert expired.structured_content['status'] == 'expired'
    schema = next((tool for tool in tools if tool.name == 'get_evidence'),).output_schema
    assert 'position_reference' in json.dumps(schema,)

def test_unknown_history_terminal_claim_is_not_refuted():
    from gambit.game.queries import ChessFactQuery, query_position_facts

    unknown = query_position_facts(
        chess.STARTING_FEN,
        [ChessFactQuery(predicate='terminal',),],
    )

    known = query_position_facts(
        chess.STARTING_FEN,
        [ChessFactQuery(predicate='terminal',),],
        history=[],
    )

    assert unknown['results'][0]['status'] == 'unknown'
    assert known['results'][0]['status'] == 'refuted'
    assert unknown['position_reference']['history_id'] == known['position_reference']['history_id']
    assert unknown['position_reference']['history_scope'] != known['position_reference']['history_scope']

def test_black_score_bounds_are_flipped_with_white_relative_scores():
    from gambit.game.service import analyze_board

    class BoundEngine:
        def analyze(
            self,
            board,
            multipv,
            nodes,
        ):
            return [{'centipawns': 20, 'mate_in': None, 'pv': [next(iter(board.legal_moves,),),], 'score_bound': 'lower',},]

    board = chess.Board()
    board.push_san('e4',)

    report = analyze_board(
        board,
        BoundEngine(),
        100,
        1,
    )

    assert report.evaluation.centipawns == -20
    assert report.principal_variations[0].score_bound == 'upper'

def test_combined_request_keeps_local_results_when_provider_is_unavailable(tmp_path,):
    import httpx
    store = Store()

    analysis = AnalysisService(
        Configuration(),
        store,
    )

    http = ProviderHttp(
        Configuration(),
        httpx.MockTransport(lambda _: httpx.Response(503,),),
    )

    try:
        evidence = Evidence(
            analysis,
            Knowledge(str(tmp_path,),),
            Providers(http,),
        )

        result = evidence.collect(
            chess.STARTING_FEN,
            sections=['facts', 'statistics',],
        )

        assert result['facts']['features']['legal_move_count'] == 20
        assert result['statistics']['status'] == 'unavailable'
        assert not result.get('engine_evidence',)
    finally:
        analysis.close()
        http.close()

def test_opening_update_requires_all_five_pinned_volumes_before_publication(tmp_path,):
    import httpx

    from gambit.knowledge.update import update_openings
    knowledge = Knowledge(str(tmp_path,),)
    requested = []

    def handler(request,):
        requested.append(request.url.path,)

        letter = request.url.path.rsplit(
            '/',
            1,
        )[1][0].upper()

        return httpx.Response(
            200,
            text=f'eco\tname\tpgn\n{letter}00\tExample {letter}\t1. e4\n',
        )

    with httpx.Client(transport=httpx.MockTransport(handler,),) as client:
        result = update_openings(
            knowledge,
            'a' * 40,
            client,
        )

    assert result['lines'] == 5 and len(requested,) == 5
    before = (tmp_path / 'openings.json').read_bytes()

    with httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(404,),),) as client:
        with pytest.raises(httpx.HTTPStatusError,):
            update_openings(
                knowledge,
                'b' * 40,
                client,
            )

    assert (tmp_path / 'openings.json').read_bytes() == before

def test_ordinary_runtime_game_and_analysis_leave_no_personal_files(
    tmp_path,
    monkeypatch,
):
    from gambit.server.tools import Runtime
    configuration = tmp_path / 'configuration.toml'
    configuration.write_text('',)

    monkeypatch.setenv(
        'GAMBIT_CONFIG',
        str(configuration,),
    )

    monkeypatch.setenv(
        'GAMBIT_RUNTIME_DIRECTORY',
        str(tmp_path,),
    )

    runtime = Runtime()

    try:
        game = runtime.live.games.create(asdict(OpponentSettings(),),)

        runtime.live.games.move(
            game['game_id'],
            0,
            'e4',
        )

        result = runtime.evidence.collect(
            chess.STARTING_FEN,
            history=['e4',],
            sections=['analysis',],
        )

        assert result['engine_evidence']['has_complete_history']

        assert runtime.store.get(
            'live_game',
            'active',
        )['history'] == ['e2e4',]
    finally:
        runtime.close()

    assert sorted((path.name for path in tmp_path.iterdir()),) == ['configuration.toml',]
