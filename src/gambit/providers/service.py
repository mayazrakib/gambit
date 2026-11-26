import re
from datetime import date
from typing import Literal

from pydantic import ValidationError

from gambit.game.position import build_board, get_position_reference
from gambit.providers.contracts import ExplorerOptions
from gambit.providers.http import ProviderFailure, ProviderHttp
from gambit.providers.material import read_chesscom, read_pgn, read_puzzle
from gambit.providers.openings import read_opening
from gambit.providers.positions import read_cloud, read_tablebase

class Providers:
    def __init__(
        self,
        http: ProviderHttp,
    ) -> None:
        self.http = http

    def execute(
        self,
        provider: str,
        operation,
        *args,
        **kwargs,
    ) -> dict:
        try:
            return operation(
                *args,
                **kwargs,
            )
        except ProviderFailure as error:
            return error.render(provider,)
        except (ValidationError, KeyError, TypeError, ValueError, RuntimeError):
            return {'status': 'failed', 'provider': provider, 'reason_code': 'malformed_response',}

    def opening(
        self,
        fen: str,
        history: list[str] | None = None,
        options: ExplorerOptions | None = None,
    ) -> dict:
        board = build_board(
            fen,
            history,
        )

        options = options or ExplorerOptions()

        if options.population == 'masters' and (options.ratings is not None or options.speeds is not None):
            raise ValueError('Rating and speed filters apply only to the Lichess population.',)

        params = {'fen': fen, 'play': ','.join((move.uci() for move in board.move_stack),), 'moves': options.limit, 'topGames': options.example_limit,}

        for name in ('since', 'until'):
            value = getattr(
                options,
                name,
            )

            if value is not None:
                pattern = r'\d{4}' if options.population == 'masters' else r'\d{4}-(0[1-9]|1[0-2])'

                if not re.fullmatch(
                    pattern,
                    value,
                ):
                    raise ValueError('Use years for Masters and YYYY-MM for Lichess date filters.',)

                params[name] = value

        if options.since and options.until and options.since > options.until:
            raise ValueError('The start date must not follow the end date.',)

        if options.population == 'lichess':
            params.update({'variant': 'standard', 'recentGames': 0,},)

            for name in ('speeds', 'ratings'):
                value = getattr(
                    options,
                    name,
                )

                if value is not None:
                    if not value:
                        raise ValueError('An explicit population filter must not be empty.',)

                    params[name] = ','.join(map(
                        str,
                        value,
                    ),)

        return self.execute(
            'explorer',
            read_opening,
            self.http,
            board,
            options,
            params,
            history is not None,
        )

    def tablebase(
        self,
        fen: str,
        history: list[str] | None = None,
    ) -> dict:
        board = build_board(
            fen,
            history,
        )

        if board.castling_rights or len(board.piece_map(),) > 7:
            return {
                'status': 'unsupported',
                'reason_code': 'requires_at_most_seven_pieces_without_castling',
                'position_reference': get_position_reference(
                    board,
                    history is not None,
                ),
            }

        return self.execute(
            'tablebase',
            read_tablebase,
            self.http,
            board,
            history is not None,
        )

    def cloud(
        self,
        fen: str,
        multipv: int = 1,
    ) -> dict:
        board = build_board(fen,)

        if not 1 <= multipv <= 5:
            raise ValueError('Request between one and five cloud variations.',)

        return self.execute(
            'lichess',
            read_cloud,
            self.http,
            board,
            multipv,
        )

    def puzzle(
        self,
        puzzle_id: str | None = None,
        angle: str | None = None,
        should_reveal: bool = False,
    ) -> dict:
        if puzzle_id is not None and not re.fullmatch(
            r'[A-Za-z0-9]{5}',
            puzzle_id,
        ):
            raise ValueError('A Lichess puzzle identifier has five alphanumeric characters.',)

        if angle is not None and not re.fullmatch(
            r'[A-Za-z0-9_]{1,64}',
            angle,
        ):
            raise ValueError('Supply a valid puzzle theme or opening identifier.',)

        if puzzle_id and angle:
            raise ValueError('A puzzle identifier cannot be combined with a selection filter.',)

        return self.execute(
            'lichess',
            read_puzzle,
            self.http,
            puzzle_id,
            angle,
            should_reveal,
        )

    def game(
        self,
        game_id: str,
        population: Literal[
            'lichess',
            'masters',
        ] = 'lichess',
    ) -> dict:
        if not re.fullmatch(
            r'[A-Za-z0-9]{8}',
            game_id,
        ):
            raise ValueError('Supply an eight-character public game identifier.',)

        provider, path = ('explorer', '/masters/pgn/' + game_id) if population == 'masters' else ('lichess', '/game/export/' + game_id)

        return self.execute(
            provider,
            read_pgn,
            self.http,
            provider,
            path,
        )

    def study(
        self,
        study_id: str,
        chapter_id: str,
    ) -> dict:
        if not all((re.fullmatch(
            r'[A-Za-z0-9]{8}',
            value,
        ) for value in (study_id, chapter_id)),):
            raise ValueError('Supply explicit eight-character public study and chapter identifiers.',)

        return self.execute(
            'lichess',
            read_pgn,
            self.http,
            'lichess',
            f'/api/study/{study_id}/{chapter_id}.pgn',
        )

    def chesscom(
        self,
        username: str,
        year: int,
        month: int,
        offset: int = 0,
        limit: int = 5,
    ) -> dict:
        if not re.fullmatch(
            r'[A-Za-z0-9_-]{1,64}',
            username,
        ):
            raise ValueError('Supply an explicit Chess.com account name.',)

        date(
            year,
            month,
            1,
        )

        if not 0 <= offset <= 100000 or not 1 <= limit <= 20:
            raise ValueError('Request a bounded page of games.',)

        return self.execute(
            'chesscom',
            read_chesscom,
            self.http,
            username,
            year,
            month,
            offset,
            limit,
        )
