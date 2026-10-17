import copy
import hashlib
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime
from uuid import uuid4

import chess
import chess.pgn

from gambit.engine.client import parse_move
from gambit.game.assessment import assess_move, build_board
from gambit.game.features import inspect_features
from gambit.learning.training import validate_training_id

MAX_SESSION_NODES = 2048
MAX_REMEMBERED_OPERATIONS = 128
MAX_REASONING_CHARACTERS = 8000
MAX_CALCULATION_PLIES = 24

def create_timestamp():
    return datetime.now(UTC,).isoformat()

def validate_confidence(confidence,):
    if confidence is not None and (type(confidence,) not in (int, float) or not math.isfinite(confidence,) or not 0 <= confidence <= 1):
        raise ValueError("Confidence must be a finite number between zero and one.",)

def get_operation_fingerprint(payload,):
    return hashlib.sha256(json.dumps(
        payload,
        sort_keys=True,
        allow_nan=False,
    ).encode(),).hexdigest()

def check_active_request():
    from gambit.engine import client

    check = getattr(
        client,
        "check_request_active",
        None,
    )

    if check is not None:
        check()

class TutorSessions:
    def __init__(
        self,
        analysis,
        store,
    ):
        self.analysis = analysis
        self.store = store

    def create_session(
        self,
        fen,
        learner_id="default",
        history=None,
    ):
        validate_training_id(learner_id,)

        board = build_board(
            fen,
            history,
        )

        node_id = str(uuid4(),)
        identifier = str(uuid4(),)

        session = {
            "schema_version": 1,
            "id": identifier,
            "learner_id": learner_id,
            "revision": 0,
            "root_fen": fen,
            "root_history": history if history is not None else None,
            "active_node_id": node_id,
            "mainline_node_id": node_id,
            "nodes": {node_id: {"id": node_id, "parent_id": None, "move_uci": None, "fen": board.fen(), "history": list(history or [],), "children": [], "evidence_ids": [], "annotations": [],},},
            "operations": {},
            "system_created_at": create_timestamp(),
        }

        check_active_request()

        self.store.put(
            "tutor_session",
            identifier,
            session,
        )

        return self.render_session(session,)

    def read_session(
        self,
        session_id,
    ):
        session = self.store.get(
            "tutor_session",
            session_id,
        )

        if session is None:
            raise ValueError("The tutoring session is unavailable.",)

        return session

    def render_session(
        self,
        session,
        should_include_tree=False,
    ):
        active = session["nodes"][session["active_node_id"]]
        response = {"schema_version": 1, "session_id": session["id"], "learner_id": session["learner_id"], "revision": session["revision"], "active_node_id": active["id"], "mainline_node_id": session["mainline_node_id"], "fen": active["fen"], "root_fen": session["root_fen"], "history": active["history"], "evidence_ids": active["evidence_ids"], "node_count": len(session["nodes"],),}

        if should_include_tree:
            response["nodes"] = [{key: value for key, value in node.items() if key != "annotations"} for node in session["nodes"].values()]

        return response

    def get_session(
        self,
        session_id,
        should_include_tree=False,
    ):
        return self.render_session(
            self.read_session(session_id,),
            should_include_tree,
        )

    def get_operation(
        self,
        session,
        expected_revision,
        operation_id,
        payload,
    ):
        validate_training_id(operation_id,)
        fingerprint = get_operation_fingerprint(payload,)
        previous = session["operations"].get(operation_id,)

        if previous is not None:
            if previous["fingerprint"] != fingerprint:
                raise ValueError("This operation identifier was already used with different arguments.",)

            return copy.deepcopy(previous["response"],)

        if type(expected_revision,) is not int or session["revision"] != expected_revision:
            raise ValueError("The tutoring session revision changed. Read the current session and retry.",)

        return None

    def commit_operation(
        self,
        session_id,
        expected_revision,
        operation_id,
        payload,
        mutate,
    ):
        check_active_request()

        with self.store.lock, self.store.connection:
            session = self.read_session(session_id,)

            replay = self.get_operation(
                session,
                expected_revision,
                operation_id,
                payload,
            )

            if replay is not None:
                return replay

            extra = mutate(session,) or {}

            records = extra.pop(
                "atomic_records",
                [],
            )

            session["revision"] += 1
            response = {**self.render_session(session,), **extra,}
            session["operations"][operation_id] = {"fingerprint": get_operation_fingerprint(payload,), "response": copy.deepcopy(response,),}

            while len(session["operations"],) > MAX_REMEMBERED_OPERATIONS:
                del session["operations"][next(iter(session["operations"],),)]

            check_active_request()
            self.store.put_records_atomic([*records, ("tutor_session", session_id, session),],)

        return response

    def apply_navigation(
        self,
        session,
        action,
        move=None,
        node_id=None,
    ):
        if action not in ("advance", "branch", "select", "return", "retry"):
            raise ValueError("Navigation action must be advance, branch, select, return, or retry.",)

        if action in ("select", "retry"):
            if node_id not in session["nodes"]:
                raise ValueError("The requested variation node is unavailable.",)

            session["active_node_id"] = node_id
        elif action == "return":
            session["active_node_id"] = session["mainline_node_id"]
        else:
            if len(session["nodes"],) >= MAX_SESSION_NODES:
                raise ValueError("The tutoring session has reached its variation limit.",)

            current = session["nodes"][session["active_node_id"]]

            board = build_board(
                session["root_fen"],
                current["history"],
            )

            if not isinstance(
                move,
                str,
            ):
                raise ValueError("Advancing requires a legal move.",)

            parsed = parse_move(
                board,
                move,
            )

            matching = next(
                (child for child in current["children"] if session["nodes"][child]["move_uci"] == parsed.uci()),
                None,
            )

            if matching is None:
                identifier = str(uuid4(),)
                board.push(parsed,)
                session["nodes"][identifier] = {"id": identifier, "parent_id": current["id"], "move_uci": parsed.uci(), "fen": board.fen(), "history": [*current["history"], parsed.uci(),], "children": [], "evidence_ids": [], "annotations": [],}
                current["children"].append(identifier,)
                matching = identifier

            session["active_node_id"] = matching

            if action == "advance":
                session["mainline_node_id"] = matching

        return {"board_directives": [{"action": "set position", "fen": session["nodes"][session["active_node_id"]]["fen"], "revision": session["revision"] + 1,},],}

    def cancel_position_work(
        self,
        session_id,
    ):
        if hasattr(
            self,
            "progressive",
        ):
            self.progressive.cancel_context(session_id,)

        if hasattr(
            self,
            "cancel_anticipation",
        ):
            self.cancel_anticipation()

    def navigate_session(
        self,
        session_id,
        expected_revision,
        operation_id,
        action,
        move=None,
        node_id=None,
    ):
        payload = {"action": action, "move": move, "node_id": node_id,}

        def mutate(session,):
            return self.apply_navigation(
                session,
                action,
                move,
                node_id,
            )

        response = self.commit_operation(
            session_id,
            expected_revision,
            operation_id,
            payload,
            mutate,
        )

        self.cancel_position_work(session_id,)

        return response

    def inspect_submission(
        self,
        session_id,
        expected_revision,
        operation_id,
        payload,
    ):
        with self.store.lock:
            session = self.read_session(session_id,)

            replay = self.get_operation(
                session,
                expected_revision,
                operation_id,
                payload,
            )

        return session, replay

    def assess_candidate(
        self,
        session,
        move,
        profile="instant",
        node_id=None,
    ):
        node = session["nodes"][node_id or session["active_node_id"]]

        return asdict(assess_move(
            self.analysis.engine,
            session["root_fen"],
            move,
            node["history"],
            profile=profile,
        ),)

    def submit_reasoning(
        self,
        session_id,
        expected_revision,
        operation_id,
        move,
        reasoning="",
        continuation=None,
        confidence=None,
        estimated_centipawns=None,
        profile="instant",
    ):
        validate_confidence(confidence,)

        if not isinstance(
            reasoning,
            str,
        ) or len(reasoning,) > MAX_REASONING_CHARACTERS:
            raise ValueError("Reasoning must contain at most 8000 characters.",)

        if continuation is not None and len(continuation,) > MAX_CALCULATION_PLIES:
            raise ValueError("A calculation submission supports at most 24 plies.",)

        if estimated_centipawns is not None and (type(estimated_centipawns,) not in (int, float) or not math.isfinite(estimated_centipawns,)):
            raise ValueError("The estimated White-perspective evaluation must be finite.",)

        payload = {"kind": "reasoning", "move": move, "reasoning": reasoning, "continuation": continuation, "confidence": confidence, "estimated_centipawns": estimated_centipawns, "profile": profile,}

        session, replay = self.inspect_submission(
            session_id,
            expected_revision,
            operation_id,
            payload,
        )

        if replay is not None:
            return replay

        assessment = self.assess_candidate(
            session,
            move,
            profile,
        )

        node = session["nodes"][session["active_node_id"]]

        board = build_board(
            session["root_fen"],
            node["history"],
        )

        parsed = parse_move(
            board,
            move,
        )

        variations = []
        board.push(parsed,)
        history = [*node["history"], parsed.uci(),]
        first_divergence = {"ply": 1, "fen": node["fen"], "move_uci": parsed.uci(), "classification": assessment["classification"], "status": assessment["evidence_status"],} if assessment["classification"] in ("inaccuracy", "serious mistake") else None

        for index, notation in enumerate(continuation or [],):
            selected = parse_move(
                board,
                notation,
            )

            evidence = asdict(assess_move(
                self.analysis.engine,
                session["root_fen"],
                notation,
                history,
                profile=profile,
            ),)

            variations.append({"ply": index + 2, "move_uci": selected.uci(), "evidence": evidence,},)

            if first_divergence is None and evidence["classification"] not in ("acceptable", "uncertain"):
                first_divergence = {"ply": index + 2, "fen": board.fen(), "move_uci": selected.uci(), "classification": evidence["classification"], "status": evidence["evidence_status"],}

            board.push(selected,)
            history.append(selected.uci(),)

        result = self.analysis.evaluate(
            session["root_fen"],
            profile,
            history,
        )

        is_confirmed = assessment["evidence_status"] == "deeper confirmation"
        observations = [{"category": "candidate selection", "finding": assessment["classification"], "status": assessment["evidence_status"],},]

        if first_divergence is not None:
            observations.append({"category": "calculation", "finding": "The supplied continuation first loses evaluation at this decision.", "evidence": first_divergence,},)

        evaluation_error = None

        if estimated_centipawns is not None and result["evaluation"]["centipawns"] is not None:
            evaluation_error = abs(estimated_centipawns - result["evaluation"]["centipawns"],)
            observations.append({"category": "evaluation", "absolute_error_centipawns": evaluation_error, "score_perspective": "white", "analysis_id": result["id"],},)

        exposure = self.store.get(
            "observation",
            session_id + ":" + node["id"],
        )

        is_assisted = bool(exposure and exposure.get("has_revealed_solution",),)
        event = {"id": str(uuid4(),), "learner_id": session["learner_id"], "session_id": session_id, "node_id": node["id"], "fen": node["fen"], "root_fen": session["root_fen"], "history": node["history"], "move_uci": parsed.uci(), "reasoning": reasoning, "confidence": confidence, "estimated_centipawns": estimated_centipawns, "evaluation_error_centipawns": evaluation_error, "classification": assessment["classification"], "is_confirmed": is_confirmed, "is_assisted": is_assisted, "is_accepted": is_confirmed and assessment["classification"] == "acceptable", "observations": observations, "analysis_id": result["id"], "system_created_at": create_timestamp(),}

        def mutate(current,):
            current_node = current["nodes"][node["id"]]
            current_node["annotations"].append({"move_uci": parsed.uci(), "reasoning": reasoning, "confidence": confidence, "classification": assessment["classification"], "evidence_status": assessment["evidence_status"],},)
            current_node["evidence_ids"].append(result["id"],)

            return {"atomic_records": [("learning_event", event["id"], event),], "assessment": assessment, "continuation_evidence": variations, "first_divergence": first_divergence, "reasoning_observations": observations, "evaluation_evidence_id": result["id"], "is_confirmed": is_confirmed, "interpretation_caveat": "These observations describe this attempt. Written reasoning alone does not establish the cause of an error.",}

        return self.commit_operation(
            session_id,
            expected_revision,
            operation_id,
            payload,
            mutate,
        )

    def assess_plan(
        self,
        session_id,
        objectives,
        candidates,
        profile="instant",
    ):
        if not isinstance(
            objectives,
            list,
        ) or not 1 <= len(objectives,) <= 8 or any((not isinstance(
            item,
            str,
        ) or not item.strip() or len(item,) > 500 for item in objectives),):
            raise ValueError("Supply one to eight concise plan objectives.",)

        comparison = self.compare_practical(
            session_id,
            candidates,
            profile,
        )

        session = self.read_session(session_id,)

        if session["revision"] != comparison["revision"]:
            raise ValueError("The tutoring position changed while checking the plan. Retry from the current revision.",)

        node = session["nodes"][session["active_node_id"]]

        board = build_board(
            session["root_fen"],
            node["history"],
        )

        before = inspect_features(board.fen(),)
        tested = []

        for item in comparison["candidates"]:
            line_board = board.copy()

            for move in item["assessment"]["verified"]["variation_uci"]:
                line_board.push(parse_move(
                    line_board,
                    move,
                ),)

            tested.append({"move_uci": item["move_uci"], "assessment": item["assessment"], "resulting_fen": line_board.fen(), "before_features": before, "after_features": inspect_features(line_board.fen(),), "strongest_reply_uci": item["strongest_reply_uci"],},)

        return {"schema_version": 1, "session_id": session_id, "revision": session["revision"], "objectives": objectives, "candidate_evidence": tested, "feasibility": "Compare the structured objectives against the verified positions and defensive replies.", "unresolved": "A finite search cannot prove an unrestricted natural-language plan feasible against every defense.",}

    def compare_practical(
        self,
        session_id,
        candidates,
        profile="instant",
    ):
        if not isinstance(
            candidates,
            list,
        ) or not 1 <= len(candidates,) <= 4:
            raise ValueError("Compare one to four legal candidates.",)

        session = self.read_session(session_id,)
        node = session["nodes"][session["active_node_id"]]

        board = build_board(
            session["root_fen"],
            node["history"],
        )

        items = []

        parsed_candidates = [parse_move(
            board,
            notation,
        ) for notation in candidates]

        stage_evidence = {}

        if hasattr(
            self.analysis.engine,
            "analyze_candidates",
        ):
            if profile not in ("instant", "quick", "deep"):
                raise ValueError("Analysis profile must be instant, quick, or deep.",)

            configuration = self.analysis.configuration

            budgets = (configuration.quick_nodes, configuration.deep_nodes) if profile == "deep" else (getattr(
                configuration,
                profile + "_nodes",
            ),)

            for nodes in budgets:
                stage_evidence[nodes] = self.analysis.engine.analyze_candidates(
                    board,
                    [move.uci() for move in parsed_candidates],
                    nodes,
                )

        for move in parsed_candidates:
            if stage_evidence:
                assessment = asdict(assess_move(
                    self.analysis.engine,
                    session["root_fen"],
                    move.uci(),
                    node["history"],
                    profile=profile,
                    baseline_lines={nodes: result["best"] for nodes, result in stage_evidence.items()},
                    candidate_lines={nodes: result["candidates"][move.uci()] for nodes, result in stage_evidence.items()},
                ),)
            else:
                assessment = self.assess_candidate(
                    session,
                    move.uci(),
                    profile,
                )

            variation = assessment["verified"]["variation_uci"]
            selected = board.copy()
            selected.push(move,)
            reply_count = selected.legal_moves.count()
            forcing_replies = []

            for reply in selected.legal_moves:
                if selected.is_capture(reply,) or selected.gives_check(reply,):
                    forcing_replies.append(reply.uci(),)

            items.append({"move_uci": move.uci(), "move_san": board.san(move,), "assessment": assessment, "strongest_reply_uci": variation[1] if len(variation,) > 1 else None, "legal_reply_count": reply_count, "forcing_reply_count": len(forcing_replies,), "forcing_replies": forcing_replies[:12], "observed_line_plies": len(variation,), "score_change_centipawns": assessment["verified"]["centipawn_loss"], "practical_caveat": "Reply counts and searched line length are observable indicators, not calibrated human difficulty or a required calculation depth.",},)

        check_active_request()

        if self.read_session(session_id,)["revision"] != session["revision"]:
            raise ValueError("The tutoring position changed while comparing moves. Retry from the current revision.",)

        return {"schema_version": 1, "session_id": session_id, "revision": session["revision"], "candidates": items,}

    def export_session(
        self,
        session_id,
    ):
        session = self.read_session(session_id,)

        board = build_board(
            session["root_fen"],
            session["root_history"],
        )

        game = chess.pgn.Game()
        game.setup(board,)
        game.headers["Event"] = "Gambit tutoring study"
        game.headers["Annotator"] = "Gambit engine-backed tutoring"
        root_id = next((identifier for identifier, node in session["nodes"].items() if node["parent_id"] is None),)

        pending = [(root_id, game),]

        while pending:
            node_id, parent = pending.pop()
            node = session["nodes"][node_id]
            annotations = []

            for entry in node["annotations"]:
                annotations.append(f"Learner {entry['move_uci']}: {entry['reasoning']} | confidence {entry['confidence']} | {entry['classification']} | {entry['evidence_status']}",)

            if annotations:
                parent.comment = "\n".join(annotations,)

            children = []

            for child_id in node["children"]:
                child = session["nodes"][child_id]
                variation = parent.add_variation(chess.Move.from_uci(child["move_uci"],),)
                children.append((child_id, variation),)

            pending.extend(reversed(children,),)

        pgn = game.accept(chess.pgn.StringExporter(
            headers=True,
            variations=True,
            comments=True,
        ),)

        return {"schema_version": 1, "session_id": session_id, "revision": session["revision"], "filename": f"gambit-{session_id}.pgn", "mime_type": "application/x-chess-pgn", "content": pgn, "history_scope": "The supplied prior history is retained in the session. PGN begins at the session's initial teaching position.",}
