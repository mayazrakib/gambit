from dataclasses import asdict
from time import monotonic

from gambit.engine.analysis import compact_position_evidence
from gambit.engine.client import check_request_active, parse_move
from gambit.game.assessment import assess_move
from gambit.game.features import inspect_features
from gambit.game.position import (
    build_board,
    get_position_reference,
    get_terminal_facts,
    replay_variation,
)

class Evidence:
    def __init__(
        self,
        analysis,
        knowledge,
        providers,
    ) -> None:
        self.analysis = analysis
        self.knowledge = knowledge
        self.providers = providers

    def collect(
        self,
        fen: str,
        history: list[str] | None = None,
        sections: list[str] | None = None,
        profile: str = 'instant',
        is_compact: bool = True,
        known_analysis_id: str | None = None,
        explorer=None,
    ) -> dict:
        sections = ['facts', 'analysis',] if sections is None else sections

        if not sections or len(sections,) > 6 or len(set(sections,),) != len(sections,) or set(sections,) - {'facts', 'analysis', 'openings', 'statistics', 'cloud', 'tablebase',}:
            raise ValueError('Select distinct supported evidence sections.',)

        board = build_board(
            fen,
            history,
        )

        result = {
            'schema_version': 3,
            'position_reference': get_position_reference(
                board,
                history is not None,
            ),
            'limitation_codes': ['client_explanation_unverified',],
        }

        if 'facts' in sections:
            state = get_terminal_facts(
                board,
                history is not None,
            )

            if result['position_reference']['history_scope'] != 'complete' and not state['can_claim_threefold_repetition']:
                state['can_claim_threefold_repetition'] = None

                if not state['can_claim_fifty_moves']:
                    state['can_claim_draw_now'] = None

                result['limitation_codes'].append('prior_repetition_history_unknown',)

            result['facts'] = {'state': state, 'features': inspect_features(board.fen(),),}

        if 'analysis' in sections:
            analysis = self.analysis.evaluate(
                fen,
                profile,
                history,
            )

            if known_analysis_id == analysis['id']:
                result['engine_evidence'] = {'id': analysis['id'], 'is_unchanged': True,}
            else:
                result['engine_evidence'] = compact_position_evidence(analysis,) if is_compact else analysis

        if 'openings' in sections:
            result['openings'] = self.knowledge.find_moves(board.fen(),)

        if 'statistics' in sections:
            result['statistics'] = self.providers.opening(
                fen,
                history,
                explorer,
            )

        if 'cloud' in sections:
            result['cloud'] = self.providers.cloud(board.fen(),)

        if 'tablebase' in sections:
            result['tablebase'] = self.providers.tablebase(
                fen,
                history,
            )

        check_request_active()

        return result

    def create_turn(
        self,
        fen: str,
        intent: str = 'explain',
        profile: str = 'instant',
        history: list[str] | None = None,
        candidates: list[str] | None = None,
        is_compact: bool = True,
    ) -> dict:
        if intent not in ('explain', 'hint', 'compare', 'endgame'):
            raise ValueError('Unsupported evidence intent.',)

        started = monotonic()

        board = build_board(
            fen,
            history,
        )

        reference = get_position_reference(
            board,
            history is not None,
        )

        report = {
            'schema_version': 3,
            'position_reference': reference,
            'position_context': {
                'fen': board.fen(),
                **get_terminal_facts(
                    board,
                    history is not None,
                ),
            },
            'board_directives': [],
            'limitation_codes': ['client_explanation_unverified', 'finite_search_not_proof',],
        }

        if intent == 'hint':
            report['engine_evidence'] = {'is_solution_hidden': True,}

            report['elapsed_ms'] = round(
                (monotonic() - started) * 1000,
                2,
            )

            return report

        analysis = self.analysis.evaluate(
            fen,
            profile,
            history,
        )

        report['engine_evidence'] = compact_position_evidence(analysis,) if is_compact else analysis
        lines = analysis['principal_variations']
        first_line = lines[0]['moves_uci'][:1 if is_compact else 24] if lines else []

        report['move_facts'] = {
            'analysis_id': analysis['id'],
            'variation': replay_variation(
                board,
                first_line,
                has_history=history is not None,
            ),
            'evidence_kind': 'rules_verified',
            'scope': 'shown_variation',
        }

        if first_line:
            move = parse_move(
                board,
                first_line[0],
            )

            report['board_directives'] = [{'action': 'add arrow', 'from': move.uci()[:2], 'to': move.uci()[2:4], 'fen': board.fen(), 'source': 'engine',},]

        if intent == 'compare' and not board.is_game_over():
            selected = candidates or [move.uci() for move in list(board.legal_moves,)[:2]]

            if not 1 <= len(selected,) <= 4:
                raise ValueError('Compare between one and four candidates.',)

            report['candidate_comparisons'] = [asdict(assess_move(
                self.analysis.engine,
                fen,
                move,
                history,
                profile=profile,
            ),) for move in selected]

        if intent == 'endgame':
            report['tablebase_evidence'] = self.providers.tablebase(
                fen,
                history,
            )

        report['elapsed_ms'] = round(
            (monotonic() - started) * 1000,
            2,
        )

        return report
