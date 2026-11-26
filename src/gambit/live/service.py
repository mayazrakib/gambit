import threading
from copy import deepcopy
from time import monotonic
from uuid import uuid4

from gambit.engine.client import check_request_active
from gambit.live.games import LiveConflict, LiveGames
from gambit.live.opponent import Opponent

class LiveWorkspace:
    def __init__(
        self,
        runtime,
    ):
        self.runtime = runtime
        self.games = LiveGames(runtime.store,)
        self.opponent = Opponent(runtime.configuration.engine_path,)
        self.cached_turns = {}
        self.cache_lock = threading.Lock()

    def get_capabilities(self,):
        capabilities = self.opponent.get_capabilities()
        self.runtime.analysis.engine.warm_up()

        return capabilities

    def create_game(
        self,
        settings: dict,
        root_fen: str,
    ):
        self.opponent.validate_settings(settings,)

        return self.games.create(
            settings,
            root_fen,
        )

    def get_game(
        self,
        game_id: str | None = None,
        known_revision: int | None = None,
        should_include_history: bool = False,
    ) -> dict:
        game = self.games.read(game_id,)

        if known_revision is not None and known_revision == game['revision']:
            return {'game_id': game['game_id'], 'revision': game['revision'], 'is_unchanged': True,}

        return self.games.render(
            game,
            should_include_history,
        )

    def play_opponent(
        self,
        game_id: str,
        expected_revision: int,
    ) -> dict:
        game = self.games.read(game_id,)
        board = self.games.build_board(game,)

        if game['revision'] != expected_revision:
            raise LiveConflict('The position changed before the engine search.',)

        if (board.is_game_over() or game.get("draw_claim",)) or (board.turn == (game['settings']['player_color'] == 'white')):
            raise LiveConflict('Stockfish is not the side to move.',)

        move = self.opponent.play(
            board,
            game['settings'],
            game_id,
        )

        check_request_active()

        return self.games.move(
            game_id,
            expected_revision,
            move,
            is_opponent=True,
        )

    def teach(
        self,
        expected_revision: int | None = None,
        game_id: str | None = None,
        intent: str = 'explain',
        profile: str = 'instant',
        known_analysis_id: str | None = None,
    ) -> dict:
        started = monotonic()
        game = self.games.read(game_id,)

        if game.get('draw_claim',):
            raise LiveConflict('A draw was claimed in this game.',)

        identifier = game['game_id']
        expected_revision = game['revision'] if expected_revision is None else expected_revision

        if type(expected_revision,) is not int or game['revision'] != expected_revision:
            raise LiveConflict('The position changed. Read the current game before teaching.',)

        request_id = str(uuid4(),)
        key = (identifier, expected_revision, intent, profile)

        with self.cache_lock:
            cached = self.cached_turns.get(key,)

        if cached is None:
            def start(current,):
                current['teaching_request'] = request_id

            self.games.update(
                identifier,
                expected_revision,
                start,
            )

            report = self.runtime.evidence.create_turn(
                game['root_fen'],
                intent=intent,
                profile=profile,
                history=game['history'],
            )
        else:
            report = cached

        position = self.games.render(
            game,
            False,
        )['fen']

        marks = [{'from': directive['from'], 'to': directive['to'], 'color': 'blue', 'source': 'engine',} for directive in report['board_directives'] if directive.get('action',) == 'add arrow' and directive.get('fen',) == position]
        teaching = {'schema_version': 3, 'facts': report.get('move_facts',), 'position_context': report['position_context'], 'evaluation': report['engine_evidence'].get('evaluation',), 'evidence_status': report['engine_evidence'].get('evidence_status',), 'intent': intent, 'profile': profile, 'analysis_id': report['engine_evidence'].get('id',), 'elapsed_ms': report['elapsed_ms'], 'revision': expected_revision,}
        check_request_active()

        if cached is None or game['annotations'] != marks or game['teaching'] != teaching or game.get('teaching_request',) != game.get('completed_teaching_request',):
            def publish(current,):
                if cached is None and current.get('teaching_request',) != request_id:
                    raise LiveConflict('A newer teaching request superseded this response.',)

                current['teaching_request'] = request_id
                current['completed_teaching_request'] = request_id
                current['annotations'] = marks
                current['teaching'] = teaching

            self.games.update(
                identifier,
                expected_revision,
                publish,
            )
        else:
            current = self.games.read(identifier,)

            if current['revision'] != expected_revision:
                raise LiveConflict('The position changed during teaching.',)

        with self.cache_lock:
            self.cached_turns[key] = report

            while len(self.cached_turns,) > 16:
                self.cached_turns.pop(next(iter(self.cached_turns,),),)

        live_game = {'game_id': identifier, 'revision': expected_revision, 'fen': position,}

        elapsed_ms = round(
            (monotonic() - started) * 1000,
            2,
        )

        if cached is not None and known_analysis_id is not None and known_analysis_id == report['engine_evidence'].get('id',):
            return {'live_game': live_game, 'analysis_id': known_analysis_id, 'is_unchanged': True, 'annotations_applied': len(marks,), 'elapsed_ms': elapsed_ms,}

        response = {name: deepcopy(report[name],) for name in ('schema_version', 'response_mode', 'is_compact', 'position_context', 'engine_evidence', 'move_facts', 'position_reference', 'limitation_codes') if name in report}

        for name in ('candidate_comparisons', 'tablebase_evidence'):
            if report.get(name,):
                response[name] = deepcopy(report[name],)

        response.update({'live_game': live_game, 'annotations_applied': len(marks,), 'elapsed_ms': elapsed_ms, 'is_cached': cached is not None,},)
        response['position_reference'].update(live_game,)

        return response

    def close(self,):
        self.opponent.close()
