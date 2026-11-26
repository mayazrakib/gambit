from gambit.engine.client import check_request_active
from gambit.game.position import build_board, get_position_reference, replay_variation
from gambit.game.service import parse_game
from gambit.providers.contracts import validate_optional_integer

def read_puzzle(
    http,
    puzzle_id,
    angle,
    should_reveal,
) -> dict:
    path = '/api/puzzle/' + puzzle_id if puzzle_id else '/api/puzzle/next'

    payload = http.request(
        'lichess',
        path,
        {'angle': angle,} if angle else {},
        should_cache=puzzle_id is not None,
    )

    if puzzle_id is not None and payload['puzzle']['id'] != puzzle_id:
        raise ValueError('Puzzle identifier mismatch.',)

    game = parse_game(payload['game']['pgn'],)

    board = build_board(
        game.initial_fen,
        [move.uci for move in game.moves],
    )

    solution = payload['puzzle']['solution']

    observations = replay_variation(
        board,
        solution,
    )

    result = {
        'status': 'available',
        'id': payload['puzzle']['id'],
        'source': 'https://lichess.org/training/' + payload['puzzle']['id'],
        'rating': validate_optional_integer(payload['puzzle']['rating'],),
        'themes': payload['puzzle'].get(
            'themes',
            [],
        ) if should_reveal else [],
        'position_reference': get_position_reference(
            board,
            True,
        ),
        'is_solution_hidden': not should_reveal,
        'limitation_codes': ['puzzle_solution_not_exhaustive_proof',],
    }

    if should_reveal:
        result['solution'] = observations
        result['game'] = payload['game']

    return result

def read_pgn(
    http,
    provider: str,
    path: str,
) -> dict:
    pgn = http.request(
        provider,
        path,
        is_text=True,
    )

    game = parse_game(pgn,)

    return {'status': 'available', 'source': {'lichess': 'https://lichess.org', 'explorer': 'https://explorer.lichess.org',}[provider] + path, 'pgn': pgn, 'headers': dict(game.headers,), 'license': None, 'evidence_kind': 'attributed_source', 'limitation_codes': ['source_commentary_not_engine_verified', 'license_not_supplied_by_endpoint',],}

def read_chesscom(
    http,
    username,
    year,
    month,
    offset,
    limit,
) -> dict:
    payload = http.request(
        'chesscom',
        f'/pub/player/{username}/games/{year:04d}/{month:02d}',
        should_cache=False,
    )

    games = payload['games']
    selected = []

    for entry in games[offset:offset + limit]:
        check_request_active()

        if entry.get('rules',) != 'chess':
            continue

        parsed = parse_game(entry['pgn'],)
        selected.append({'url': entry['url'], 'pgn': entry['pgn'], 'headers': dict(parsed.headers,), 'end_time': entry.get('end_time',), 'time_control': entry.get('time_control',),},)

    return {'status': 'available' if selected else 'empty', 'source': 'https://www.chess.com/news/view/published-data-api', 'year': year, 'month': month, 'games': selected, 'next_offset': offset + limit if len(games,) > offset + limit else None, 'limitation_codes': ['provider_archive_may_lag', 'standard_chess_only', 'archive_bounded_by_response_bytes',],}
