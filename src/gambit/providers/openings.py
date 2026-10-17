from gambit.game.position import get_position_reference
from gambit.providers.contracts import Outcomes

def read_opening(
    http,
    board,
    options,
    params,
    has_history,
) -> dict:
    payload = http.request(
        'explorer',
        '/' + options.population,
        params,
    )

    outcomes = Outcomes.model_validate(payload,).model_dump()
    moves = []

    for entry in payload['moves'][:options.limit]:
        move = board.parse_uci(entry['uci'],)
        counts = Outcomes.model_validate(entry,).model_dump()
        moves.append({'uci': move.uci(), 'san': board.san(move,), **counts, 'sample_size': sum(counts.values(),), 'average_rating': entry.get('averageRating',),},)

    return {
        'status': 'available' if sum(outcomes.values(),) else 'empty',
        'source': 'https://explorer.lichess.org/' + options.population,
        'evidence_kind': 'observed_game_statistics',
        'population': options.population,
        'filters': {
            **options.model_dump(exclude={'limit', 'example_limit',},),
            'since': params.get(
                'since',
                '1952' if options.population == 'masters' else '1952-01',
            ),
            'until': params.get('until',),
            'variant': 'standard',
        },
        'sample_size': sum(outcomes.values(),),
        'outcomes': outcomes,
        'moves': moves,
        'example_games': payload.get(
            'topGames',
            [],
        )[:options.example_limit],
        'opening': payload.get('opening',),
        'position_reference': get_position_reference(
            board,
            has_history,
        ),
        'limitation_codes': ['observed_outcomes_not_move_quality', 'provider_coverage_not_exhaustive',],
    }
