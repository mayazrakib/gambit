import chess

from gambit.game.position import get_position_reference, get_terminal_facts, replay_variation
from gambit.providers.contracts import validate_optional_integer

def read_tablebase(
    http,
    board,
    has_history,
) -> dict:
    payload = http.request(
        'tablebase',
        '/standard',
        {'fen': board.fen(),},
    )

    categories = {'win', 'unknown', 'syzygy-win', 'maybe-win', 'cursed-win', 'draw', 'blessed-loss', 'maybe-loss', 'syzygy-loss', 'loss',}

    if payload['category'] not in categories:
        raise ValueError('Unknown tablebase category.',)

    moves = []

    for entry in payload['moves']:
        move = board.parse_uci(entry['uci'],)

        if entry['category'] not in categories:
            raise ValueError('Unknown tablebase move category.',)

        moves.append({'uci': move.uci(), 'san': board.san(move,), 'category': entry['category'], 'score_perspective': 'opponent_after_move', 'dtz_plies': validate_optional_integer(entry.get('dtz',),), 'dtm_plies': validate_optional_integer(entry.get('dtm',),), 'is_zeroing': entry.get('zeroing',),},)

    return {
        'status': 'unknown' if payload['category'] == 'unknown' else 'available',
        'source': 'https://tablebase.lichess.ovh/standard',
        'evidence_kind': 'tablebase',
        'category': payload['category'],
        'score_perspective': 'side_to_move',
        'dtz_plies': validate_optional_integer(payload.get('dtz',),),
        'precise_dtz_plies': validate_optional_integer(payload.get('precise_dtz',),),
        'dtm_plies': validate_optional_integer(payload.get('dtm',),),
        'halfmove_clock': board.halfmove_clock,
        'rules_state': get_terminal_facts(
            board,
            has_history,
        ),
        'moves': moves,
        'position_reference': get_position_reference(
            board,
            has_history,
        ),
        'limitation_codes': ['fifty_move_rule_applies', 'dtz_is_not_dtm', 'provider_category_conditions_apply', *([] if has_history and board.root().fen() == chess.STARTING_FEN else ['prior_repetition_history_unknown',]),],
    }

def read_cloud(
    http,
    board,
    multipv,
) -> dict:
    payload = http.request(
        'lichess',
        '/api/cloud-eval',
        {'fen': board.fen(), 'multiPv': multipv, 'variant': 'standard',},
    )

    if ' '.join(payload['fen'].split()[:4],) != ' '.join(board.fen().split()[:4],):
        raise ValueError('Cloud position mismatch.',)

    lines = []

    for entry in payload['pvs'][:multipv]:
        if ('cp' in entry) == ('mate' in entry):
            raise ValueError('Cloud scores require exactly one score unit.',)

        moves = entry['moves'].split()

        replay_variation(
            board,
            moves[:24],
            has_history=False,
        )

        lines.append({'moves_uci': moves[:24], 'is_truncated': len(moves,) > 24, 'centipawns': validate_optional_integer(entry.get('cp',),), 'mate_moves': validate_optional_integer(entry.get('mate',),),},)

    return {
        'status': 'available',
        'source': 'https://lichess.org/api/cloud-eval',
        'evidence_kind': 'imported_engine_analysis',
        'engine': {'name': 'Stockfish', 'version': None,},
        'depth': validate_optional_integer(payload.get('depth',),),
        'knodes': validate_optional_integer(payload.get('knodes',),),
        'score_perspective': 'white',
        'variations': lines,
        'position_reference': get_position_reference(
            board,
            False,
        ),
        'limitation_codes': ['finite_search_not_proof', 'engine_version_unknown', 'prior_repetition_history_unknown',],
    }
