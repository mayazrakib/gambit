import json
import threading
from dataclasses import asdict
from time import monotonic

from gambit.engine.analysis import AnalysisService, compact_position_evidence
from gambit.engine.client import parse_move
from gambit.game.assessment import assess_move, build_board
from gambit.game.features import inspect_features
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge
from gambit.learning.openings import OpeningPlans
from gambit.learning.sessions import TutorSessions, check_active_request
from gambit.learning.speech import create_speech_plan, pronounce_move

SPOKEN_OPENING_LIMIT = 3

class Tutor:
    def __init__(
        self,
        analysis: AnalysisService,
        knowledge: Knowledge,
        store: Store,
        sessions=None,
        progressive=None,
    ) -> None:
        self.analysis = analysis
        self.knowledge = knowledge
        self.store = store

        self.sessions = sessions or TutorSessions(
            analysis,
            store,
        )

        self.progressive = progressive
        self.anticipated_positions = set()
        self.anticipation_cancellations = []
        self.anticipation_context = None
        self.anticipation_lock = threading.RLock()
        self.sessions.cancel_anticipation = self.cancel_anticipation

    def create_turn(
        self,
        fen: str,
        learner_id: str = "default",
        intent: str = "explain",
        profile: str = "instant",
        history: list[str] | None = None,
        candidates: list[str] | None = None,
        move: str | None = None,
        is_compact: bool = True,
        session_id: str | None = None,
        expected_revision: int | None = None,
        operation_id: str | None = None,
        question: str | None = None,
        detail: str | None = None,
        response_mode: str = "full",
        known_evidence_ids: list[str] | None = None,
    ) -> dict:
        started = monotonic()
        check_active_request()

        if response_mode not in ("full", "delta"):
            raise ValueError("Response mode must be full or delta.",)

        if detail not in (None, "brief", "detailed", "variations"):
            raise ValueError("Detail must be brief, detailed, or variations.",)

        if question is not None and (not isinstance(
            question,
            str,
        ) or len(question,) > 4000):
            raise ValueError("A tutoring question must contain at most 4000 characters.",)

        if known_evidence_ids is not None and (len(known_evidence_ids,) > 128 or any((not isinstance(
            identifier,
            str,
        ) for identifier in known_evidence_ids),)):
            raise ValueError("Supply at most 128 known evidence identifiers.",)

        session_state = None
        turn_arguments = {"fen": fen, "learner_id": learner_id, "intent": intent, "profile": profile, "history": history, "candidates": candidates, "move": move, "is_compact": is_compact, "question": question, "detail": detail, "response_mode": response_mode, "known_evidence_ids": known_evidence_ids,}

        turn_payload = {"kind": "tutor turn", **turn_arguments,}

        if session_id is not None:
            saved_session = self.sessions.read_session(session_id,)

            if move is not None:
                if operation_id is None:
                    raise ValueError("A session move requires an operation identifier.",)

                replay = self.sessions.get_operation(
                    saved_session,
                    expected_revision,
                    operation_id,
                    turn_payload,
                )

                if replay is not None:
                    return replay["tutor_report"]

            session_state = self.sessions.render_session(saved_session,)

            if type(expected_revision,) is not int or session_state["revision"] != expected_revision:
                raise ValueError("Read the current tutoring revision before requesting this turn.",)

            fen = session_state["root_fen"]
            history = session_state["history"]
            learner_id = session_state["learner_id"]

        if detail is not None:
            is_compact = detail == "brief"

        if intent not in ("explain", "hint", "compare", "endgame"):
            raise ValueError("Tutor intent must be explain, hint, compare, or endgame.",)

        board = build_board(
            fen,
            history,
        )

        move_assessment = None

        if move is not None:
            move_assessment = self.analysis.evaluate_move(
                fen,
                move,
                profile,
                history,
            )

            board.push(parse_move(
                board,
                move,
            ),)

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

        if detail is not None:
            learner = {**learner, "detail": "detailed" if detail != "brief" else "brief",}

        features = inspect_features(position_fen,)

        analysis = move_assessment["after"] if move_assessment is not None else self.analysis.evaluate(
            fen,
            profile,
            history,
        )

        record_limit = SPOKEN_OPENING_LIMIT if is_compact else 100

        openings = self.knowledge.find_moves(
            position_fen,
            limit=record_limit,
        ) if intent != "hint" else None

        lines = analysis["principal_variations"]
        spoken = []
        directives = []
        moves = []
        diagnosis = []
        comparisons = []

        if intent == "compare" and not board.is_game_over():
            selected = candidates or [line["moves_uci"][0] for line in lines[:2]]

            if len(selected,) < 2:
                alternatives = self.analysis.engine.analyze(
                    board,
                    min(
                        2,
                        board.legal_moves.count(),
                    ),
                    getattr(
                        self.analysis.configuration,
                        profile + "_nodes",
                    ),
                )

                selected = [line["pv"][0].uci() for line in alternatives[:2]]

            comparisons = [asdict(assess_move(
                self.analysis.engine,
                board.root().fen(),
                candidate,
                [entry.uci() for entry in board.move_stack],
                profile=profile,
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
            (compact_position_evidence(analysis,) if is_compact else analysis)
            if intent != "hint"
            else {"id": analysis["id"], "engine": analysis["engine"], "is_solution_hidden": True,}
        )

        if is_compact and openings is not None:
            for name in ("moves", "reached_openings"):
                records = openings[name]

                openings[name] = [
                    {key: value for key, value in record.items() if key != "pgn"}
                    for record in records[:SPOKEN_OPENING_LIMIT]
                ]

        if is_compact and move_assessment is not None:
            move_assessment = {
                "move": move_assessment["move"],
                "centipawn_loss": move_assessment["centipawn_loss"],
                "assessment": move_assessment["assessment"],
                "before_analysis_id": move_assessment["before"]["id"],
                "after_analysis_id": move_assessment["after"]["id"],
            }

        report = {
            "schema_version": 1,
            "is_compact": is_compact,
            "move_assessment": move_assessment if intent != "hint" else None,
            "candidate_comparisons": comparisons,
            "position_context": features,
            "engine_evidence": evidence,
            "opening_evidence": openings if intent != "hint" else None,
            "opening_plan_evidence": OpeningPlans(self.store,).get_plans(
                position_fen,
                record_limit,
            ) if intent != "hint" else None,
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

        report["question"] = question
        report["detail"] = detail or learner["detail"]
        report["response_mode"] = response_mode
        report["session"] = session_state
        report["background_request"] = None

        if session_state is not None:
            for directive in report["board_directives"]:
                directive.update({"session_id": session_id, "revision": session_state["revision"], "node_id": session_state["active_node_id"],},)

        if intent != "hint":
            known = set(known_evidence_ids or [],)

            report["explanation_evidence"] = {"analysis_id": analysis["id"], "is_unchanged": True,} if response_mode == "delta" and analysis["id"] in known else self.create_explanation(
                board,
                analysis,
                features,
                move_assessment,
                is_compact,
            )

            if response_mode == "delta" and analysis["id"] in known:
                report["engine_evidence"] = {"id": analysis["id"], "is_unchanged": True,}
                report["position_context"] = {"fen": board.fen(), "is_unchanged": True,}
                report["explanation_evidence"] = {"analysis_id": analysis["id"], "is_unchanged": True,}
                report["opening_evidence"] = None
                report["opening_plan_evidence"] = None
                report["speech_plan"] = {"is_unchanged": True, "position_fen": board.fen(),}
                report["board_directives"] = []

                report.pop(
                    "model_instructions",
                    None,
                )

                report.pop(
                    "learning_diagnosis",
                    None,
                )

                report.pop(
                    "teaching_plan",
                    None,
                )

            if response_mode == "delta":
                report = {key: value for key, value in report.items() if value is not None and value != []}

                if analysis["id"] not in known:
                    report["engine_evidence"] = {"id": analysis["id"], "fen": analysis["fen"], "evaluation": analysis["evaluation"], "principal_variations": compact_position_evidence(analysis,)["principal_variations"][:1], "evidence_status": analysis["evidence_status"],}
                    report["position_context"] = {"fen": board.fen(), "is_check": board.is_check(), "is_terminal": board.is_game_over(),}

                    report.pop(
                        "model_instructions",
                        None,
                    )

                    report.pop(
                        "opening_evidence",
                        None,
                    )

                    report.pop(
                        "opening_plan_evidence",
                        None,
                    )

                    report.pop(
                        "learning_diagnosis",
                        None,
                    )

            if session_state is not None and self.sessions.get_session(session_id,)["revision"] != expected_revision:
                raise ValueError("The tutoring position changed during analysis. Request the current revision.",)

            should_refine = self.should_refine(
                analysis,
                move_assessment,
                comparisons,
                profile,
            )

            if should_refine and self.progressive is not None and getattr(
                self.analysis.configuration,
                "worker_count",
                1,
            ) > 1:
                context_id = session_id if session_state is not None else analysis["id"]

                try:
                    request = self.progressive.start(
                        context_id,
                        fen,
                        [
                            *(history or []),
                            *([
                                parse_move(
                                    build_board(
                                        fen,
                                        history,
                                    ),
                                    move,
                                ).uci(),
                            ] if move is not None else []),
                        ],
                        is_automatic=True,
                    )

                    report["background_request"] = {key: value for key, value in request.items() if key != "preliminary"}
                except RuntimeError:
                    report["background_request"] = {"status": "deferred", "reason": "Interactive evidence is ready. Background capacity is currently unavailable.",}

            self.anticipate(
                fen,
                history,
                move,
                analysis,
            )

            if session_state is not None and move is None:
                with self.store.lock:
                    check_active_request()

                    if self.sessions.get_session(session_id,)["revision"] != session_state["revision"]:
                        raise ValueError("The tutoring position changed during analysis. Request the current revision.",)

                    self.store.put(
                        "observation",
                        session_id + ":" + session_state["active_node_id"],
                        {"id": session_id + ":" + session_state["active_node_id"], "kind": "tutor evidence exposure", "learner_id": learner_id, "session_id": session_id, "node_id": session_state["active_node_id"], "revision": session_state["revision"], "analysis_id": analysis["id"], "has_revealed_solution": True,},
                    )

        check_active_request()

        report["elapsed_ms"] = round(
            (monotonic() - started) * 1000,
            2,
        )

        if response_mode == "delta" and session_state is not None:
            report["session"] = {key: session_state[key] for key in ("session_id", "revision", "active_node_id", "fen")}

        if session_id is not None and move is not None:
            report = json.loads(json.dumps(
                report,
                allow_nan=False,
            ),)

            def mutate(session,):
                self.sessions.apply_navigation(
                    session,
                    "advance",
                    move,
                )

                node = session["nodes"][session["active_node_id"]]
                node["evidence_ids"].append(analysis["id"],)
                state = self.sessions.render_session(session,)
                state["revision"] += 1
                report["session"] = {key: state[key] for key in ("session_id", "revision", "active_node_id", "fen")} if response_mode == "delta" else state

                for directive in report.get(
                    "board_directives",
                    [],
                ):
                    directive.update({"session_id": session_id, "revision": state["revision"], "node_id": state["active_node_id"],},)

                records = []

                if intent != "hint":
                    identifier = session_id + ":" + node["id"]
                    records.append(("observation", identifier, {"id": identifier, "kind": "tutor evidence exposure", "learner_id": learner_id, "session_id": session_id, "node_id": node["id"], "revision": state["revision"], "analysis_id": analysis["id"], "has_revealed_solution": True,}),)

                return {"tutor_report": report, "atomic_records": records,}

            committed = self.sessions.commit_operation(
                session_id,
                expected_revision,
                operation_id,
                turn_payload,
                mutate,
            )

            report = committed["tutor_report"]

        return report

    def should_refine(
        self,
        analysis,
        move_assessment,
        comparisons,
        profile,
    ):
        if profile == "deep" or not getattr(
            self.analysis.configuration,
            "should_refine_automatically",
            True,
        ):
            return False

        if analysis["evaluation"]["mate_in"] is not None:
            return True

        if move_assessment is not None:
            assessment = move_assessment.get("assessment",)

            if isinstance(
                assessment,
                dict,
            ) and assessment.get("evidence_status",) == "unstable":
                return True

            if (move_assessment.get("centipawn_loss",) or 0) >= 150:
                return True

        scores = [line["evaluation"]["centipawns"] for line in analysis["principal_variations"][:2] if line["evaluation"]["centipawns"] is not None]

        return len(scores,) == 2 and abs(scores[0] - scores[1],) <= 30 or any((item.get("evidence_status",) == "unstable" for item in comparisons),)

    def create_explanation(
        self,
        board,
        analysis,
        features,
        move_assessment,
        is_compact=False,
    ):
        lines = analysis["principal_variations"]

        if is_compact:
            line = lines[0]["moves_uci"] if lines else []

            return {"analysis_id": analysis["id"], "move_uci": line[0] if line else None, "strongest_searched_reply_uci": line[1] if len(line,) > 1 else None, "geometry_reference": "position_context", "candidate_reference": "move_assessment" if move_assessment is not None else None, "interpretation_rule": "Explain purpose from the shown position and line. Label strategic causes as interpretation.",}

        claims = [{"kind": "measured geometry", "fen": board.fen(), "facts": features, "source": "python-chess legal rules and piece geometry",},]

        if lines and lines[0]["moves_uci"]:
            selected = board.copy()
            variation = []

            for notation in lines[0]["moves_uci"][:8]:
                move = parse_move(
                    selected,
                    notation,
                )

                before = inspect_features(selected.fen(),)
                is_capture = selected.is_capture(move,)
                is_check = selected.gives_check(move,)
                san = selected.san(move,)
                selected.push(move,)
                after = inspect_features(selected.fen(),)
                variation.append({"move_uci": move.uci(), "move_san": san, "fen": selected.fen(), "is_capture": is_capture, "is_check": is_check, "material_change": {side: after["sides"][side]["material_points"] - before["sides"][side]["material_points"] for side in ("white", "black")}, "piece_activity": {"legal_move_count": after["legal_move_count"], "side_to_move": "white" if selected.turn else "black",}, "pawn_structure": {side: {key: after["sides"][side][key] for key in ("isolated_pawns", "passed_pawns", "doubled_pawn_files")} for side in ("white", "black")}, "king_safety": {"is_check": selected.is_check(), "king_squares": {side: after["sides"][side]["king_square"] for side in ("white", "black")},},},)

            claims.append({"kind": "engine preference", "analysis_id": analysis["id"], "fen": board.fen(), "move_uci": lines[0]["moves_uci"][0], "strongest_searched_reply_uci": lines[0]["moves_uci"][1] if len(lines[0]["moves_uci"],) > 1 else None, "variation": variation, "evidence_status": analysis["evidence_status"],},)

        return {"analysis_id": analysis["id"], "claims": claims, "purpose_guidance": "Explain the move's purpose from the shown measurable changes and defensive reply. Label strategic causal explanations as interpretation.", "candidate_reference": "move_assessment" if move_assessment is not None else None, "caveat": "Legal mobility and king geometry are observations. They are not independent proof that a strategic plan succeeds.",}

    def cancel_anticipation(self,):
        with self.anticipation_lock:
            for cancellation in self.anticipation_cancellations:
                cancellation.set()

            self.anticipation_cancellations.clear()

    def anticipate(
        self,
        fen,
        history,
        move,
        evidence,
    ):
        count = getattr(
            self.analysis.configuration,
            "prefetch_branches",
            0,
        )

        if count < 1 or getattr(
            self.analysis.configuration,
            "worker_count",
            1,
        ) < 2 or not hasattr(
            self.analysis,
            "submit_background",
        ):
            return

        with self.anticipation_lock:
            if self.anticipation_context != evidence["fen"]:
                self.cancel_anticipation()
                self.anticipation_context = evidence["fen"]

        base_history = list(history or [],)

        if move is not None:
            base_history.append(parse_move(
                build_board(
                    fen,
                    history,
                ),
                move,
            ).uci(),)

        for variation in evidence["principal_variations"][:min(
            count,
            2,
        )]:
            if not variation["moves_uci"]:
                continue

            anticipated = [*base_history, variation["moves_uci"][0],]
            key = (fen, tuple(anticipated,))

            if key in self.anticipated_positions:
                continue

            if len(self.anticipated_positions,) >= 128:
                self.anticipated_positions.clear()

            try:
                cancellation = threading.Event()

                self.analysis.submit_background(
                    self.analysis.evaluate,
                    fen,
                    "quick",
                    anticipated,
                    cancellation=cancellation,
                    is_automatic=True,
                    is_anticipation=True,
                )

                self.anticipated_positions.add(key,)
                self.anticipation_cancellations.append(cancellation,)
            except RuntimeError:
                continue
