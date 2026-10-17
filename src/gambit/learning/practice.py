import copy
import json
import math
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import chess

from gambit.engine.client import parse_move
from gambit.game.assessment import assess_move, build_board
from gambit.learning.exercises import initialize_original_exercises
from gambit.learning.sessions import (
    MAX_CALCULATION_PLIES,
    MAX_REMEMBERED_OPERATIONS,
    check_active_request,
    create_timestamp,
    get_operation_fingerprint,
    validate_confidence,
)
from gambit.learning.training import validate_training_id

PRACTICE_MODES = ("calculation", "refutation", "defense", "mixed", "transfer", "counterexample", "opening", "prediction", "endgame", "timed diagnosis")
REVIEW_INTERVAL_DAYS = (1, 3, 7, 21, 60)

class Practice:
    def __init__(
        self,
        analysis,
        store,
        sessions,
        corpus=None,
    ):
        self.analysis = analysis
        self.store = store
        self.sessions = sessions
        self.corpus = corpus

    def initialize_exercises(self,):
        return initialize_original_exercises(
            self.analysis,
            self.store,
        )

    def find_events(
        self,
        learner_id,
        limit=1000,
    ):
        validate_training_id(learner_id,)

        with self.store.lock:
            rows = self.store.connection.execute(
                """
                    SELECT payload FROM record
                    WHERE collection = 'learning_event'
                        AND json_extract(payload, '$.learner_id') = ?

                    ORDER BY system_created_at DESC, id DESC
                    LIMIT ?
                """,
                (learner_id, limit),
            ).fetchall()

        return sorted(
            (json.loads(row[0],) for row in rows),
            key=lambda event: (event.get(
                "system_created_at",
                "",
            ), event["id"]),
        )

    def select_source(
        self,
        mode,
        learner_id,
        fen,
        history,
        source_id,
    ):
        if fen is not None:
            board = build_board(
                fen,
                history,
            )

            return {"id": source_id or str(uuid4(),), "root_fen": fen, "history": history, "fen": board.fen(), "source": "learner-supplied position", "themes": [],}

        if source_id is not None:
            exercise = self.store.get(
                "exercise",
                source_id,
            )

            if exercise is not None:
                if mode in ("transfer", "counterexample"):
                    related = self.store.get(
                        "exercise",
                        exercise.get(
                            "base_id",
                            exercise["id"],
                        ) + "-" + mode,
                    )

                    if related is not None:
                        return related

                return exercise

            lesson = self.store.get(
                "lesson",
                source_id,
            )

            if lesson is not None and lesson["learner_id"] == learner_id:
                return {
                    **lesson,
                    "themes": [
                        lesson.get(
                            "topic",
                            "personal review",
                        ),
                    ],
                }

            event = self.store.get(
                "learning_event",
                source_id,
            )

            if event is not None and event["learner_id"] == learner_id:
                return {
                    "id": source_id,
                    "root_fen": event.get(
                        "root_fen",
                        event["fen"],
                    ),
                    "history": event.get("history",),
                    "fen": event["fen"],
                    "source": "personal review",
                    "themes": event.get(
                        "themes",
                        [],
                    ),
                    "review_event_id": source_id,
                }

        if mode in ("opening", "prediction") and self.corpus is not None:
            game = self.corpus.get_game(source_id,) if source_id else next(
                iter(self.corpus.list_games(limit=20,),),
                None,
            )

            if game is not None and game["moves"]:
                offset = min(
                    18 if mode == "opening" else max(
                        12,
                        len(game["moves"],) // 2,
                    ),
                    len(game["moves"],) - 1,
                )

                board = build_board(
                    game["root_fen"],
                    game["moves"][:offset],
                )

                return {
                    "id": game["id"],
                    "root_fen": game["root_fen"],
                    "history": game["moves"][:offset],
                    "fen": board.fen(),
                    "solution": game["moves"][offset:offset + 12],
                    "source": game["source"],
                    "themes": [mode,],
                    "game_headers": game.get(
                        "headers",
                        {},
                    ),
                    "is_game_continuation": True,
                }

        events = self.find_events(learner_id,)
        used = [event.get("source_id",) for event in events]

        if mode in ("mixed", "calculation", "defense", "refutation", "timed diagnosis") and self.corpus is not None and (mode != "mixed" or len(events,) % 3 == 0):
            profile = self.store.get(
                "profile",
                learner_id,
            ) or {"rating": 1800,}

            themes = ["defensiveMove",] if mode == "defense" else None

            if mode == "calculation":
                patterns = self.get_patterns(learner_id,)["patterns"]

                recurring = next(
                    (pattern for pattern in patterns if pattern["confirmed_mistakes"] >= 2),
                    None,
                )

                if recurring is not None:
                    themes = [recurring["theme"],]

            puzzle = self.corpus.select_puzzle(
                themes=themes,
                rating=profile["rating"],
                exclude_ids=[item for item in used if item],
            )

            if puzzle is not None:
                return {**puzzle, "root_fen": puzzle["fen"], "history": None,}

        exercises = self.store.list_records(
            "exercise",
            1000,
        )

        category = {"defense": "defense", "calculation": "calculation", "endgame": "endgames", "opening": "strategic planning", "prediction": "strategic planning",}.get(mode,)
        role = mode if mode in ("transfer", "counterexample") else "base"
        eligible = [exercise for exercise in exercises if exercise.get("role",) == role and (category is None or exercise["category"] == category)]

        if source_id is not None and mode in ("transfer", "counterexample"):
            parent = self.store.get(
                "exercise",
                source_id,
            )

            if parent is not None:
                related = self.store.get(
                    "exercise",
                    parent.get(
                        "base_id",
                        parent["id"],
                    ) + "-" + mode,
                )

                if related is not None:
                    return related

        if eligible:
            eligible.sort(key=lambda exercise: (exercise["id"] in used, sum((item == exercise["id"] for item in used),), exercise["id"]),)

            return eligible[0]

        if mode == "opening":
            openings = self.store.list_records(
                "opening",
                100,
            )

            if openings:
                opening = openings[0]

                return {**opening, "root_fen": opening["fen"], "history": None, "solution": [opening["move_uci"],], "themes": ["opening understanding",],}

        raise ValueError("No matching local material is available. Supply a position, import material, or initialize original exercises.",)

    def start_practice(
        self,
        mode,
        learner_id="default",
        fen=None,
        history=None,
        source_id=None,
        is_timed=False,
    ):
        validate_training_id(learner_id,)

        if mode not in PRACTICE_MODES:
            raise ValueError("Choose a supported practice mode.",)

        if type(is_timed,) is not bool:
            raise ValueError("The timed flag must be a boolean.",)

        if mode == "mixed" and source_id is None and fen is None:
            due = self.get_due_reviews(learner_id,)["reviews"]

            if due:
                source_id = due[0]["event_id"]

        source = self.select_source(
            mode,
            learner_id,
            fen,
            history,
            source_id,
        )

        root_fen = source.get(
            "root_fen",
            source["fen"],
        )

        selected_history = source.get("history",)

        board = build_board(
            root_fen,
            selected_history,
        )

        if not board.is_valid() or board.is_game_over():
            raise ValueError("Practice requires a valid nonterminal standard chess position.",)

        identifier = str(uuid4(),)

        practice = {
            "schema_version": 1,
            "id": identifier,
            "learner_id": learner_id,
            "revision": 0,
            "mode": mode,
            "source_id": source["id"],
            "source": source.get(
                "source",
                "local material",
            ),
            "themes": source.get(
                "themes",
                [
                    source.get(
                        "category",
                        "candidate calculation",
                    ),
                ],
            ),
            "root_fen": root_fen,
            "history": selected_history,
            "initial_history": selected_history,
            "fen": board.fen(),
            "initial_fen": board.fen(),
            "solution": source.get(
                "solution",
                [],
            ),
            "source_record": source,
            "status": "active",
            "hint_level": 0,
            "is_assisted": False,
            "is_timed": is_timed or mode == "timed diagnosis",
            "system_created_at": create_timestamp(),
            "operations": {},
            "snapshots": [{"fen": board.fen(), "history": selected_history,},],
            "attempts": [],
            "reply_line": [],
            "reply_reveal_plies": 0,
        }

        check_active_request()

        self.store.put(
            "practice",
            identifier,
            practice,
        )

        return self.render_practice(practice,)

    def read_practice(
        self,
        practice_id,
    ):
        practice = self.store.get(
            "practice",
            practice_id,
        )

        if practice is None:
            raise ValueError("The practice session is unavailable.",)

        return practice

    def render_practice(
        self,
        practice,
    ):
        prompts = {
            "calculation": "Calculate a candidate and the strongest reply without moving the visible pieces. Submit your complete variation and final evaluation.",
            "refutation": "Propose a move. Then predict the strongest response before asking to reveal the refutation.",
            "defense": "Identify the threat, compare defensive resources, and explain your chosen reply.",
            "mixed": "What does this position require? Choose a move, calculate the reply, and explain your evaluation.",
            "transfer": "Apply the earlier concept in this new position. Verify whether its conditions still hold.",
            "counterexample": "Test whether the earlier idea still works. Identify the changed condition before committing.",
            "opening": "Explain the pawn break or piece placement you want, then choose a move and predict the strongest reply.",
            "prediction": "Predict the next move and the opponent's response before revealing the game continuation. A played move need not be best.",
            "endgame": "Choose a move and explain the conversion or drawing plan. You can retry an earlier checkpoint.",
            "timed diagnosis": "Calculate under your chosen time budget, submit your elapsed time, and compare with a later untimed attempt.",
        }

        return {"schema_version": 1, "practice_id": practice["id"], "learner_id": practice["learner_id"], "revision": practice["revision"], "mode": practice["mode"], "fen": practice["fen"], "status": practice["status"], "hint_level": practice["hint_level"], "is_assisted": practice["is_assisted"], "is_timed": practice["is_timed"], "prompt": prompts[practice["mode"]], "snapshot_count": len(practice["snapshots"],), "is_solution_hidden": practice["hint_level"] < 4,}

    def get_practice(
        self,
        practice_id,
    ):
        return self.render_practice(self.read_practice(practice_id,),)

    def inspect_operation(
        self,
        practice,
        expected_revision,
        operation_id,
        payload,
    ):
        validate_training_id(operation_id,)
        previous = practice["operations"].get(operation_id,)

        if previous is not None:
            if previous["fingerprint"] != get_operation_fingerprint(payload,):
                raise ValueError("This practice operation identifier was used with different arguments.",)

            return copy.deepcopy(previous["response"],)

        if type(expected_revision,) is not int or practice["revision"] != expected_revision:
            raise ValueError("The practice revision changed. Read the session before retrying.",)

        return None

    def get_solution(
        self,
        practice,
    ):
        if practice["solution"]:
            return practice["solution"], None

        evidence = self.analysis.evaluate(
            practice["root_fen"],
            "quick",
            practice["history"],
        )

        lines = evidence["principal_variations"]
        solution = lines[0]["moves_uci"] if lines else []

        return solution, evidence["id"]

    def assess_line(
        self,
        practice,
        moves,
        profile,
    ):
        if not moves or len(moves,) > MAX_CALCULATION_PLIES:
            raise ValueError("Submit between one and 24 legal plies.",)

        board = build_board(
            practice["root_fen"],
            practice["history"],
        )

        history = list(practice["history"] or [],)
        evidence = []
        first_divergence = None
        first_preliminary_divergence = None

        for index, notation in enumerate(moves,):
            move = parse_move(
                board,
                notation,
            )

            assessment = asdict(assess_move(
                self.analysis.engine,
                practice["root_fen"],
                notation,
                history,
                profile=profile,
            ),)

            item = {"ply": index + 1, "fen": board.fen(), "move_uci": move.uci(), "assessment": assessment,}
            evidence.append(item,)

            if assessment["classification"] in ("inaccuracy", "serious mistake") and first_divergence is None:
                first_divergence = {"ply": index + 1, "fen": board.fen(), "move_uci": move.uci(), "classification": assessment["classification"],}

            if first_preliminary_divergence is None and (assessment["verified"]["centipawn_loss"] or 0) > 30:
                first_preliminary_divergence = {"ply": index + 1, "fen": board.fen(), "move_uci": move.uci(), "status": assessment["evidence_status"], "observed_loss_centipawns": assessment["verified"]["centipawn_loss"],}

            board.push(move,)
            history.append(move.uci(),)

        return {"evidence": evidence, "first_divergence": first_divergence, "preliminary_divergence": first_preliminary_divergence, "resulting_fen": board.fen(), "history": history, "is_confirmed": all((item["assessment"]["evidence_status"] == "deeper confirmation" for item in evidence),),}

    def create_attempt(
        self,
        practice,
        report,
        confidence,
        reasoning,
        elapsed_ms,
    ):
        assessment = report["evidence"][0]["assessment"]
        is_confirmed = report["is_confirmed"]
        is_accepted = is_confirmed and assessment["classification"] == "acceptable" and report["first_divergence"] is None
        interval = REVIEW_INTERVAL_DAYS[0]
        earlier = [event for event in self.find_events(practice["learner_id"],) if event.get("source_id",) == practice["source_id"] and event.get("is_confirmed",) and event.get("is_accepted",) and not event.get("is_assisted",)]

        if is_accepted and not practice["is_assisted"]:
            interval = REVIEW_INTERVAL_DAYS[min(
                len(earlier,),
                len(REVIEW_INTERVAL_DAYS,) - 1,
            )]

        return {"id": str(uuid4(),), "learner_id": practice["learner_id"], "practice_id": practice["id"], "source_id": practice["source_id"], "mode": practice["mode"], "themes": practice["themes"], "fen": practice["fen"], "root_fen": practice["root_fen"], "history": practice["history"], "move_uci": report["evidence"][0]["move_uci"], "classification": assessment["classification"], "is_confirmed": is_confirmed, "is_accepted": is_accepted, "is_assisted": practice["is_assisted"], "is_timed": practice["is_timed"], "elapsed_ms": elapsed_ms, "confidence": confidence, "reasoning": reasoning, "first_divergence": report["first_divergence"], "preliminary_divergence": report["preliminary_divergence"], "due_at": (datetime.now(UTC,) + timedelta(days=interval,)).isoformat(), "system_created_at": create_timestamp(),}

    def act_practice(
        self,
        practice_id,
        expected_revision,
        operation_id,
        action,
        moves=None,
        confidence=None,
        reasoning="",
        elapsed_ms=None,
        profile="instant",
        checkpoint=None,
    ):
        validate_confidence(confidence,)

        if action not in ("submit", "hint", "reveal", "replay", "retry", "play", "repair"):
            raise ValueError("Practice action must be submit, hint, reveal, replay, retry, play, or repair.",)

        if not isinstance(
            reasoning,
            str,
        ) or len(reasoning,) > 8000:
            raise ValueError("Reasoning must contain at most 8000 characters.",)

        if elapsed_ms is not None and (type(elapsed_ms,) not in (int, float) or not math.isfinite(elapsed_ms,) or elapsed_ms < 0):
            raise ValueError("Elapsed milliseconds must be finite and nonnegative.",)

        payload = {"action": action, "moves": moves, "confidence": confidence, "reasoning": reasoning, "elapsed_ms": elapsed_ms, "profile": profile, "checkpoint": checkpoint,}
        practice = self.read_practice(practice_id,)

        replay = self.inspect_operation(
            practice,
            expected_revision,
            operation_id,
            payload,
        )

        if replay is not None:
            return replay

        work = copy.deepcopy(practice,)
        extra = {}
        event = None

        if action in ("submit", "repair", "play"):
            if work["status"] == "completed" and action != "repair":
                raise ValueError("Retry a completed practice position before submitting again.",)

            report = self.assess_line(
                work,
                moves,
                profile,
            )

            work["submitted_line"] = [entry["move_uci"] for entry in report["evidence"]]

            event = self.create_attempt(
                work,
                report,
                confidence,
                reasoning,
                elapsed_ms,
            )

            work["attempts"].append(event["id"],)
            extra = {"is_confirmed": report["is_confirmed"], "is_accepted": event["is_accepted"], "first_divergence": report["first_divergence"], "preliminary_divergence": report["preliminary_divergence"], "due_at": event["due_at"], "feedback": "Verified candidate and continuation evidence." if report["is_confirmed"] else "Preliminary evidence. Request deeper verification before treating this attempt as graded.",}

            if work["mode"] == "refutation":
                candidate = report["evidence"][0]["assessment"]
                work["reply_line"] = candidate["verified"]["variation_uci"][1:]
                extra["candidate_feedback"] = {"classification": candidate["classification"], "evidence_status": candidate["evidence_status"], "centipawn_loss": candidate["verified"]["centipawn_loss"], "is_reply_hidden": True,}
                work["proposed_move"] = report["evidence"][0]["move_uci"]
                extra["prompt"] = "Predict the strongest reply. Reveal it one ply at a time, then repair your original candidate."
            else:
                extra["line_evidence"] = report["evidence"]

            if work["mode"] == "prediction":
                solution, _ = self.get_solution(work,)
                submitted = report["evidence"][0]["move_uci"]
                extra["matches_played_move"] = bool(solution and submitted == solution[0],)
                extra["played_move_caveat"] = "Matching the game continuation is separate from engine quality. Reveal the continuation after making your prediction."

            if work["mode"] in ("transfer", "counterexample"):
                source = work["source_record"]

                extra["transfer_evidence"] = {
                    "position_change": source.get("position_change",),
                    "is_confirmed_counterexample": source.get(
                        "is_confirmed_counterexample",
                        False,
                    ),
                    "base_move_assessment": source.get("base_move_assessment",),
                    "caveat": "Concept credit requires a confirmed unassisted response and reasoning about the changed conditions.",
                }

            if action == "play":
                if work["mode"] != "endgame" or len(moves or [],) != 1:
                    raise ValueError("Endgame play accepts exactly one learner move.",)

                work["history"] = report["history"]

                board = build_board(
                    work["root_fen"],
                    work["history"],
                )

                directives = [{"action": "play move", "move_uci": report["evidence"][0]["move_uci"],},]

                if not board.is_game_over(claim_draw=True,):
                    engine = self.analysis.evaluate(
                        work["root_fen"],
                        "quick",
                        work["history"],
                    )

                    reply = engine["principal_variations"][0]["moves_uci"][0]
                    work["history"].append(reply,)
                    board.push_uci(reply,)
                    directives.append({"action": "play move", "move_uci": reply, "analysis_id": engine["id"],},)

                work["fen"] = board.fen()
                work["snapshots"].append({"fen": board.fen(), "history": list(work["history"],),},)
                extra["board_directives"] = directives
                extra["tablebase_evidence"] = self.analysis.tablebases.probe(board.fen(),)
                extra["outcome"] = board.result(claim_draw=True,) if board.is_game_over(claim_draw=True,) else None
                extra["rules_caveat"] = "DTZ measures distance to a zeroing move, not distance to mate. Apply the halfmove clock and draw claims."

                if board.is_game_over(claim_draw=True,):
                    work["status"] = "completed"
            elif report["is_confirmed"] and work["mode"] != "refutation":
                work["status"] = "completed"
        elif action == "hint":
            work["is_assisted"] = True

            work["hint_level"] = min(
                4,
                work["hint_level"] + 1,
            )

            level = work["hint_level"]

            if level == 1:
                extra["hint"] = "Check the opponent's threat, forcing moves, and the least active piece before choosing a candidate."
            else:
                solution, analysis_id = self.get_solution(work,)
                work["solution"] = solution

                if not solution:
                    extra["hint"] = "No legal continuation is available. Check whether the position is terminal."
                elif level == 2:
                    board = build_board(
                        work["root_fen"],
                        work["history"],
                    )

                    move = parse_move(
                        board,
                        solution[0],
                    )

                    extra["hint"] = "Consider a move by your " + chess.piece_name(board.piece_type_at(move.from_square,),) + "."
                elif level == 3:
                    extra["hint"] = {"first_move_uci": solution[0], "analysis_id": analysis_id,}
                else:
                    extra["hint"] = {"variation_uci": solution, "analysis_id": analysis_id,}
        elif action == "reveal":
            work["is_assisted"] = True

            if work["mode"] == "refutation":
                if not work["reply_line"]:
                    raise ValueError("Submit a candidate before revealing its strongest reply.",)

                work["reply_reveal_plies"] = min(
                    len(work["reply_line"],),
                    work["reply_reveal_plies"] + 1,
                )

                extra["refutation_uci"] = work["reply_line"][:work["reply_reveal_plies"]]
            else:
                solution, analysis_id = self.get_solution(work,)
                work["hint_level"] = 4
                extra["variation_uci"] = solution
                extra["analysis_id"] = analysis_id
                extra["source"] = work["source"]
                extra["continuation_kind"] = "played game continuation, not proof of best play" if work["source_record"].get("is_game_continuation",) else "source or engine continuation"
        elif action == "replay":
            if not work["attempts"] and work["hint_level"] < 4:
                raise ValueError("Submit a calculation or reveal the solution before replaying it.",)

            if work.get("submitted_line",):
                solution = work["submitted_line"]
                analysis_id = None
            else:
                solution, analysis_id = self.get_solution(work,)

            work["is_assisted"] = True
            extra["board_directives"] = [{"action": "replay variation", "root_fen": work["root_fen"], "history": work["history"], "moves_uci": solution, "analysis_id": analysis_id,},]
        else:
            index = 0 if checkpoint is None else checkpoint

            if type(index,) is not int or not 0 <= index < len(work["snapshots"],):
                raise ValueError("Choose an existing practice checkpoint.",)

            snapshot = work["snapshots"][index]
            work["history"] = snapshot["history"]
            work["fen"] = snapshot["fen"]
            work["status"] = "active"
            work["is_assisted"] = work["is_assisted"] or bool(work["attempts"],)
            extra["board_directives"] = [{"action": "set position", "fen": work["fen"],},]

        check_active_request()

        with self.store.lock, self.store.connection:
            current = self.read_practice(practice_id,)

            replay = self.inspect_operation(
                current,
                expected_revision,
                operation_id,
                payload,
            )

            if replay is not None:
                return replay

            work["revision"] += 1
            response = {**self.render_practice(work,), **extra,}

            for directive in response.get(
                "board_directives",
                [],
            ):
                directive["revision"] = work["revision"]
                directive["practice_id"] = practice_id

            work["operations"][operation_id] = {"fingerprint": get_operation_fingerprint(payload,), "response": copy.deepcopy(response,),}

            while len(work["operations"],) > MAX_REMEMBERED_OPERATIONS:
                del work["operations"][next(iter(work["operations"],),)]

            records = [("practice", practice_id, work),]

            if event is not None:
                records.append(("learning_event", event["id"], event),)

            self.store.put_records_atomic(records,)

        return response

    def get_due_reviews(
        self,
        learner_id="default",
    ):
        now = create_timestamp()
        latest = {}

        for event in self.find_events(learner_id,):
            if "due_at" in event:
                latest[event["source_id"]] = event

        due = [{"event_id": event["id"], "source_id": source_id, "fen": event["fen"], "due_at": event["due_at"], "was_assisted": event["is_assisted"], "was_confirmed": event["is_confirmed"],} for source_id, event in latest.items() if event["due_at"] <= now]

        return {
            "schema_version": 1,
            "learner_id": learner_id,
            "reviews": sorted(
                due,
                key=lambda item: (item["due_at"], item["source_id"]),
            ),
            "selection": "Use event_id as source_id to retry this personal position without showing its answer.",
        }

    def get_patterns(
        self,
        learner_id="default",
    ):
        events = self.find_events(learner_id,)
        groups = {}

        for event in events:
            if not event.get("is_confirmed",):
                continue

            for theme in event.get("themes",) or ["candidate calculation",]:
                group = groups.setdefault(
                    theme,
                    {"theme": theme, "confirmed_attempts": 0, "confirmed_mistakes": 0, "independent_successes": 0, "supporting_events": [],},
                )

                group["confirmed_attempts"] += 1

                if event["classification"] in ("inaccuracy", "serious mistake"):
                    group["confirmed_mistakes"] += 1
                    group["supporting_events"].append({"event_id": event["id"], "fen": event["fen"], "move_uci": event["move_uci"], "first_divergence": event.get("first_divergence",),},)
                elif event.get("is_accepted",) and not event.get("is_assisted",):
                    group["independent_successes"] += 1

        return {
            "schema_version": 1,
            "learner_id": learner_id,
            "patterns": sorted(
                groups.values(),
                key=lambda group: (-group["confirmed_mistakes"], group["theme"]),
            ),
            "caveat": "Counts describe observed attempts. They are not calibrated mastery, rating, or proof of the cause of mistakes.",
            "observed_events": len(events,),
            "is_window_limited": len(events,) >= 1000,
        }

    def get_dashboard(
        self,
        learner_id="default",
    ):
        events = self.find_events(learner_id,)
        confirmed = [event for event in events if event.get("is_confirmed",)]
        independent = [event for event in confirmed if not event.get("is_assisted",)]
        calibrated = [event for event in independent if event.get("confidence",) is not None and "is_accepted" in event]
        confidently_wrong = [event for event in calibrated if event["confidence"] >= 0.8 and not event["is_accepted"]]
        delayed = []
        prior = {}
        comparisons = []
        timed = {}

        for event in events:
            source_id = event.get("source_id",)

            if source_id is None:
                continue

            if event.get("is_confirmed",) and not event.get("is_assisted",) and source_id in prior:
                elapsed = datetime.fromisoformat(event["system_created_at"],) - datetime.fromisoformat(prior[source_id]["system_created_at"],)

                if elapsed >= timedelta(days=1,):
                    delayed.append(event,)

            if event.get("is_timed",):
                timed[source_id] = event
            elif source_id in timed and event.get("is_confirmed",) and timed[source_id].get("is_confirmed",):
                comparisons.append({"source_id": source_id, "timed_event_id": timed[source_id]["id"], "untimed_event_id": event["id"], "timed_classification": timed[source_id]["classification"], "untimed_classification": event["classification"], "timed_elapsed_ms": timed[source_id].get("elapsed_ms",), "untimed_elapsed_ms": event.get("elapsed_ms",), "caveat": "A repeated position includes memory effects. Interpret this as a within-position comparison, not a causal diagnosis.",},)

            prior[source_id] = event

        brier = sum(((event["confidence"] - int(event["is_accepted"],)) ** 2 for event in calibrated),) / len(calibrated,) if calibrated else None
        transfer = [event for event in independent if event.get("mode",) in ("transfer", "counterexample")]

        return {"schema_version": 1, "learner_id": learner_id, "attempt_count": len(events,), "confirmed_attempts": len(confirmed,), "independent_attempts": len(independent,), "unassisted_accuracy": sum((bool(event.get("is_accepted",),) for event in independent),) / len(independent,) if independent else None, "confidence_brier_score": brier, "confidence_sample_count": len(calibrated,), "confidently_wrong_events": [{"event_id": event["id"], "source_id": event.get("source_id",), "confidence": event["confidence"],} for event in confidently_wrong], "delayed_unassisted_count": len(delayed,), "delayed_unassisted_accuracy": sum((bool(event.get("is_accepted",),) for event in delayed),) / len(delayed,) if delayed else None, "transfer_count": len(transfer,), "transfer_unassisted_accuracy": sum((bool(event.get("is_accepted",),) for event in transfer),) / len(transfer,) if transfer else None, "timed_untimed_comparisons": comparisons[-20:], "due_reviews": self.get_due_reviews(learner_id,)["reviews"], "patterns": self.get_patterns(learner_id,)["patterns"], "caveat": "These are descriptive observations, not a calibrated skill score. Preliminary or assisted attempts never count as independent mastery.", "is_window_limited": len(events,) >= 1000,}
