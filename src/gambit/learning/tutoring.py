from dataclasses import asdict

from gambit.engine.analysis import AnalysisService
from gambit.engine.client import parse_move
from gambit.game.assessment import assess_move, build_board
from gambit.game.features import inspect_features
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge
from gambit.learning.openings import OpeningPlans
from gambit.learning.speech import create_speech_plan, pronounce_move

class Tutor:
    def __init__(
        self,
        analysis: AnalysisService,
        knowledge: Knowledge,
        store: Store,
    ) -> None:
        self.analysis = analysis
        self.knowledge = knowledge
        self.store = store

    def create_turn(
        self,
        fen: str,
        learner_id: str = "default",
        intent: str = "explain",
        profile: str = "instant",
        history: list[str] | None = None,
        candidates: list[str] | None = None,
    ) -> dict:
        if intent not in ("explain", "hint", "compare", "endgame"):
            raise ValueError("Tutor intent must be explain, hint, compare, or endgame.",)

        board = build_board(
            fen,
            history,
        )
        position_fen = board.fen()

        if candidates is not None and len(candidates,) > 4:
            raise ValueError("A teaching comparison supports at most four candidates.",)

        learner = self.store.get(
            "profile",
            learner_id,
        ) or {
            "style": "socratic",
            "detail": "brief",
            "rating": 1200,
            "speech_rate": 170,
            "voice": "en",
        }
        features = inspect_features(position_fen,)
        analysis = self.analysis.evaluate(
            fen,
            profile,
            history,
        )
        openings = self.knowledge.find_moves(position_fen,)
        lines = analysis["principal_variations"]
        spoken = []
        directives = []
        moves = []
        diagnosis = []
        comparisons = []

        if intent == "compare" and not board.is_game_over():
            selected = candidates or [line["moves_uci"][0] for line in lines[:2]]

            if len(selected,) < 2:
                alternatives = self.analysis.evaluate(
                    fen,
                    "quick",
                    history,
                )["principal_variations"]
                selected = [line["moves_uci"][0] for line in alternatives[:2]]

            comparisons = [asdict(assess_move(
                self.analysis.engine,
                fen,
                candidate,
                history,
            ),) for candidate in selected]

        side = "white" if board.turn else "black"
        own_features = features["sides"][side]

        if board.is_checkmate():
            spoken.append("This position is checkmate.",)
        elif board.is_stalemate():
            spoken.append("This position is stalemate. The game is drawn.",)
        elif board.is_game_over():
            spoken.append("This position is terminal under the standard rules.",)
        elif intent == "hint":
            spoken.append("Find a forcing candidate, then calculate the opponent's strongest reply.",)

            if board.is_check():
                spoken = ["Your king is in check. Compare captures, blocks, and king moves.",]
        elif lines:
            best_move = parse_move(
                board,
                lines[0]["moves_uci"][0],
            )
            moves = list(lines[0]["moves_uci"][:4],)
            spoken.append("The engine's current first choice is: " + pronounce_move(
                board,
                best_move,
            ),)
            directives.append({
                "action": "add arrow",
                "from": best_move.uci()[:2],
                "to": best_move.uci()[2:4],
                "source": "engine",
                "fen": board.fen(),
            },)

            if learner["style"] == "socratic":
                spoken.append("What is the opponent's strongest reply, and what changes after it?",)

            if comparisons:
                spoken.append("Compare each candidate's strongest reply and resulting position using the verified lines.",)

        if own_features["isolated_pawns"]:
            diagnosis.append({
                "concept": "pawn structure",
                "evidence": own_features["isolated_pawns"],
                "interpretation": "These pawns have no friendly pawns on adjacent files. Whether they are weaknesses depends on the position.",
            },)

        if own_features["pinned_pieces"]:
            diagnosis.append({"concept": "absolute pin", "evidence": own_features["pinned_pieces"],},)

        if learner["detail"] == "detailed" and diagnosis:
            spoken.append("Check the marked structural features before selecting a long-term plan.",)

        tablebase = None

        if intent == "endgame":
            tablebase = self.analysis.tablebases.probe(position_fen,)

        evidence = (
            analysis
            if intent != "hint"
            else {"id": analysis["id"], "engine": analysis["engine"], "is_solution_hidden": True,}
        )

        return {
            "schema_version": 1,
            "candidate_comparisons": comparisons,
            "position_context": features,
            "engine_evidence": evidence,
            "opening_evidence": openings if intent != "hint" else None,
            "opening_plan_evidence": OpeningPlans(self.store,).get_plans(position_fen,) if intent != "hint" else None,
            "tablebase_evidence": tablebase,
            "learning_diagnosis": diagnosis,
            "teaching_plan": {
                "style": learner["style"],
                "intent": intent,
                "next_step": "Ask the learner to calculate a candidate and verify it with evaluate_move.",
            },
            "board_directives": directives,
            "speech_plan": create_speech_plan(
                position_fen,
                spoken,
                moves,
            ),
            "model_instructions": "Use only the supplied facts and legal variations. Distinguish engine preferences, geometric observations, and teaching advice. Do not describe a forcing win unless the evidence establishes it. Keep each spoken turn brief and allow interruptions.",
        }
