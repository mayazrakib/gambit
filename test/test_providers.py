import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import chess
import httpx
import pytest

from gambit.engine.client import REQUEST_CONTEXT, RequestContext
from gambit.infrastructure.configuration import Configuration
from gambit.providers.http import ProviderHttp
from gambit.providers.service import ExplorerOptions, Providers

@pytest.fixture
def provider_factory():
    clients = []

    def create(
        handler,
        **settings,
    ):
        http = ProviderHttp(
            replace(
                Configuration(),
                **settings,
            ),
            httpx.MockTransport(handler,),
        )

        clients.append(http,)

        return Providers(http,)

    yield create

    for client in clients:
        client.close()

def test_opening_statistics_preserve_population_and_validate_moves(provider_factory,):
    seen = []

    def handler(request,):
        seen.append(request,)

        return httpx.Response(
            200,
            json={'white': 5, 'draws': 3, 'black': 2, 'moves': [{'uci': 'e2e4', 'white': 3, 'draws': 2, 'black': 1,},], 'topGames': [{'id': 'abcdefgh',},],},
        )

    providers = provider_factory(handler,)

    result = providers.opening(
        chess.STARTING_FEN,
        [],
        ExplorerOptions(
            population='lichess',
            since='2025-01',
            speeds=['rapid',],
            ratings=[2000,],
        ),
    )

    assert result['sample_size'] == 10
    assert result['moves'][0]['sample_size'] == 6
    assert result['moves'][0]['san'] == 'e4'
    assert result['population'] == 'lichess'
    assert seen[0].url.params['speeds'] == 'rapid'
    assert result['filters']['ratings'] == [2000,]
    assert 'observed_outcomes_not_move_quality' in result['limitation_codes']

    with pytest.raises(ValueError,):
        providers.opening(
            chess.STARTING_FEN,
            options=ExplorerOptions(
                population='masters',
                ratings=[2000,],
            ),
        )

    with pytest.raises(ValueError,):
        providers.opening(
            chess.STARTING_FEN,
            options=ExplorerOptions(since='2025-01',),
        )

def test_malformed_or_illegal_provider_moves_fail_closed(provider_factory,):
    providers = provider_factory(lambda _: httpx.Response(
        200,
        json={'white': 1, 'draws': 0, 'black': 0, 'moves': [{'uci': 'e7e5', 'white': 1, 'draws': 0, 'black': 0,},],},
    ),)

    assert providers.opening(chess.STARTING_FEN,)['reason_code'] == 'malformed_response'

def test_tablebase_retains_categories_perspectives_and_draw_conditions(provider_factory,):
    providers = provider_factory(lambda _: httpx.Response(
        200,
        json={'category': 'cursed-win', 'dtz': 101, 'dtm': 120, 'moves': [{'uci': 'b1b2', 'category': 'blessed-loss', 'dtz': -100,},],},
    ),)

    result = providers.tablebase('7k/8/8/8/8/8/8/KR6 w - - 99 51',)
    assert result['category'] == 'cursed-win'
    assert result['halfmove_clock'] == 99
    assert result['dtz_plies'] == 101 and result['dtm_plies'] == 120
    assert result['moves'][0]['score_perspective'] == 'opponent_after_move'
    assert 'prior_repetition_history_unknown' in result['limitation_codes']
    assert providers.tablebase(chess.STARTING_FEN,)['status'] == 'unsupported'

def test_cloud_results_preserve_unknown_metadata_and_validate_pv(provider_factory,):
    providers = provider_factory(lambda _: httpx.Response(
        200,
        json={'fen': chess.STARTING_FEN, 'depth': 25, 'knodes': 100, 'pvs': [{'cp': 25, 'moves': 'e2e4 e7e5',},],},
    ),)

    result = providers.cloud(chess.STARTING_FEN,)
    assert result['engine']['version'] is None
    assert result['score_perspective'] == 'white'
    assert result['variations'][0]['centipawns'] == 25
    assert result['depth'] == 25

def test_puzzles_hide_all_solution_paths_until_reveal(provider_factory,):
    providers = provider_factory(lambda _: httpx.Response(
        200,
        json={'game': {'pgn': '1. e4 e5 *', 'id': 'abcdefgh',}, 'puzzle': {'id': 'abc12', 'rating': 1500, 'themes': ['fork',], 'solution': ['g1f3', 'b8c6',],},},
    ),)

    hidden = providers.puzzle('abc12',)
    assert hidden['status'] == 'available'
    assert hidden['position_reference']['fen'] == chess.Board('rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2',).fen()
    assert hidden['themes'] == []
    assert not {'solution', 'game', 'analysis_id',} & hidden.keys()

    revealed = providers.puzzle(
        'abc12',
        should_reveal=True,
    )

    assert revealed['solution'][0]['move_san'] == 'Nf3'
    assert revealed['solution'][1]['move_san'] == 'Nc6'

def test_game_and_annotated_study_keep_source_text(provider_factory,):
    pgn = '[Event "Example"]\n\n1. e4 { Source advice. } e5 *'
    seen = []

    def handler(request,):
        seen.append(str(request.url,),)

        return httpx.Response(
            200,
            text=pgn,
        )

    providers = provider_factory(handler,)

    game = providers.game(
        'abcdefgh',
        'masters',
    )

    study = providers.study(
        'abcdefgh',
        'ijklmnop',
    )

    assert game['pgn'] == study['pgn'] == pgn
    assert study['license'] is None
    assert study['headers']['Event'] == 'Example'
    assert seen[0].startswith('https://explorer.lichess.org/masters/pgn/',)

    with pytest.raises(ValueError,):
        providers.study(
            '../other',
            'ijklmnop',
        )

def test_chesscom_history_is_explicit_bounded_and_not_cached(
    provider_factory,
    tmp_path,
):
    calls = []

    def handler(request,):
        calls.append(request,)

        return httpx.Response(
            200,
            json={'games': [{'rules': 'chess', 'pgn': '1. e4 e5 *', 'url': 'https://www.chess.com/game/live/1',},],},
        )

    providers = provider_factory(handler,)

    for _ in range(2,):
        report = providers.chesscom(
            'example-account',
            2025,
            1,
        )

        assert report['games'][0]['pgn'] == '1. e4 e5 *'

    assert len(calls,) == 2 and providers.http.cache == {}
    assert list(tmp_path.iterdir(),) == []

    with pytest.raises(ValueError,):
        providers.chesscom(
            '',
            2025,
            1,
        )

    with pytest.raises(ValueError,):
        providers.chesscom(
            'example',
            2025,
            13,
        )

@pytest.mark.parametrize(
    'code,reason',
    [(404, 'not_found'), (403, 'provider_access_denied'), (500, 'provider_http_error'),],
)
def test_provider_failures_are_explicit(
    provider_factory,
    code,
    reason,
):
    providers = provider_factory(lambda _: httpx.Response(code,),)
    assert providers.cloud(chess.STARTING_FEN,)['reason_code'] == reason

def test_rate_limit_cooldown_does_not_block_the_turn(provider_factory,):
    calls = []

    def handler(request,):
        calls.append(request,)

        return httpx.Response(
            429,
            headers={'Retry-After': '120',},
        )

    providers = provider_factory(handler,)
    first = providers.cloud(chess.STARTING_FEN,)
    second = providers.cloud(chess.STARTING_FEN,)
    assert first['reason_code'] == second['reason_code'] == 'rate_limited'
    assert first['retry_after_seconds'] == 120
    assert len(calls,) == 1

def test_response_limits_and_malformed_json(provider_factory,):
    providers = provider_factory(
        lambda _: httpx.Response(
            200,
            content=b'x' * 2000,
        ),
        api_max_response_bytes=1024,
    )

    assert providers.cloud(chess.STARTING_FEN,)['reason_code'] == 'provider_response_too_large'

    providers = provider_factory(lambda _: httpx.Response(
        200,
        content=b'{broken',
    ),)

    assert providers.cloud(chess.STARTING_FEN,)['reason_code'] == 'malformed_response'

def test_timeouts_and_cancellation_remain_visible(provider_factory,):
    def handler(request,):
        raise httpx.ReadTimeout('private request details',)

    providers = provider_factory(handler,)
    result = providers.cloud(chess.STARTING_FEN,)
    assert result['reason_code'] == 'provider_timeout'
    assert 'private' not in str(result,)
    cancellation = threading.Event()
    cancellation.set()
    token = REQUEST_CONTEXT.set(RequestContext(cancellation,),)

    try:
        with pytest.raises(InterruptedError,):
            providers.cloud(chess.STARTING_FEN,)
    finally:
        REQUEST_CONTEXT.reset(token,)

def test_identical_requests_are_deduplicated_and_cache_is_isolated(provider_factory,):
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def handler(request,):
        calls.append(request,)
        entered.set()
        assert release.wait(3,)

        return httpx.Response(
            200,
            json={'value': [1,],},
        )

    providers = provider_factory(handler,)

    with ThreadPoolExecutor(max_workers=4,) as pool:
        futures = [pool.submit(
            providers.http.request,
            'lichess',
            '/api/example',
        ) for _ in range(4,)]

        assert entered.wait(3,)
        release.set()
        results = [future.result(timeout=3,) for future in futures]

    assert len(calls,) == 1
    results[0]['value'].append(2,)

    assert providers.http.request(
        'lichess',
        '/api/example',
    ) == {'value': [1,],}

@pytest.mark.parametrize(
    'score',
    ['winning', True, 1.5,],
)
def test_malformed_cloud_score_units_cannot_become_evidence(
    provider_factory,
    score,
):
    providers = provider_factory(lambda _: httpx.Response(
        200,
        json={'fen': chess.STARTING_FEN, 'pvs': [{'cp': score, 'moves': 'e2e4',},],},
    ),)

    result = providers.cloud(chess.STARTING_FEN,)
    assert result['status'] == 'failed'
    assert result['reason_code'] == 'malformed_response'
