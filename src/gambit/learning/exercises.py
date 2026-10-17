import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextvars import copy_context

import chess

from gambit.game.assessment import build_board

ORIGINAL_OPENING_LINES = (
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6 c3 O-O h3 Nb8 d4 Nbd7",
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O Nf3 h6 Bh4 b6 cxd5 Nxd5 Bxe7 Qxe7",
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6 Be3 e5 Nb3 Be6 f3 Be7 Qd2 O-O O-O-O",
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O Be2 e5 O-O Nc6 d5 Ne7 Ne1 Nd7 f3 f5",
    "e4 e6 d4 d5 Nc3 Bb4 e5 c5 a3 Bxc3+ bxc3 Ne7 Qg4 Qc7 Bd3 cxd4 Ne2",
    "d4 d5 c4 c6 Nf3 Nf6 Nc3 e6 e3 Nbd7 Bd3 dxc4 Bxc4 b5 Bd3 a6 e4 c5 e5",
    "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 O-O Nc6 Be3 Qb6 Nc3 Qxb2 Nb5 Rc8",
    "Nf3 Nf6 c4 e6 Nc3 d5 d4 Bb4 e3 O-O Bd3 c5 O-O Nc6 a3 Bxc3 bxc3 dxc4 Bxc4",
)

ORIGINAL_ENDGAMES = (
    "8/8/3k4/8/3K4/4P3/8/8 w - - 0 1",
    "8/6pk/7p/8/8/6KP/6P1/8 w - - 0 1",
    "8/1r4pk/7p/8/3R4/6PP/5PK1/8 w - - 0 1",
    "8/8/5k2/3p4/3P4/4K3/8/8 w - - 0 1",
    "8/2p5/1p1k4/p7/P1PK4/1P6/8/8 w - - 0 1",
    "8/5pk1/6p1/4P3/5K2/8/8/8 w - - 0 1",
    "8/8/2k5/3p4/3P4/2K2N2/8/8 w - - 0 1",
    "8/8/3k4/8/3K4/4P3/1B6/8 w - - 0 1",
)

CATEGORY_OBJECTIVES = {
    "calculation": "Compare forcing candidates, predict the strongest defense, and evaluate the resulting position.",
    "defense": "Identify the immediate threat and find a defense or counterplay against the opponent's strongest continuation.",
    "strategic planning": "Choose a useful improvement or pawn break, then test its tactical feasibility against the strongest reply.",
    "endgames": "Find a king, pawn, or piece plan that preserves the best available outcome and check draw mechanisms.",
}

def get_opening_boards():
    boards = []

    for line in ORIGINAL_OPENING_LINES:
        board = chess.Board()

        for notation in line.split():
            board.push_san(notation,)

        boards.append(board,)

    return boards

def create_original_bases(analysis,):
    openings = get_opening_boards()
    records = []
    selected_positions = set()

    for category in CATEGORY_OBJECTIVES:
        for index in range(8,):
            if category == "endgames":
                board = chess.Board(ORIGINAL_ENDGAMES[index],)
            else:
                board = openings[index].copy()

                if category in ("calculation", "defense"):
                    target_checks = category == "defense"
                    best_board = board.copy()
                    best_score = -1

                    for _ in range(10,):
                        if board.is_game_over():
                            break

                        forcing = sum((board.is_capture(move,) or board.gives_check(move,) for move in board.legal_moves),)
                        score = forcing + (20 if board.is_check() and target_checks else 0)

                        if score > best_score:
                            best_board = board.copy()
                            best_score = score

                        evidence = analysis.evaluate(
                            board.root().fen(),
                            "quick",
                            [move.uci() for move in board.move_stack],
                        )

                        variations = evidence["principal_variations"]

                        if not variations or not variations[0]["moves_uci"]:
                            break

                        board.push_uci(variations[0]["moves_uci"][0],)

                    board = best_board

            while board.board_fen() in selected_positions and not board.is_game_over():
                evidence = analysis.evaluate(
                    board.root().fen(),
                    "quick",
                    [move.uci() for move in board.move_stack],
                )

                board.push_uci(evidence["principal_variations"][0]["moves_uci"][0],)

            selected_positions.add(board.board_fen(),)

            if not board.is_valid() or board.is_game_over():
                raise RuntimeError("An original exercise position is not playable.",)

            identifier = f"original-{category.replace(
                ' ',
                '-',
            )}-{index + 1}"

            records.append({"id": identifier, "category": category, "fen": board.fen(), "root_fen": board.root().fen(), "history": [move.uci() for move in board.move_stack], "objective": CATEGORY_OBJECTIVES[category],},)

    return records

def select_variant(
    board,
    role,
    used_positions,
):
    pieces = sorted(board.piece_map().items(),)

    for square, piece in pieces:
        if piece.piece_type == chess.KING:
            continue

        destinations = chess.SquareSet(chess.BB_SQUARES[square],)

        if role == "counterexample":
            destinations = chess.SquareSet(chess.BB_ALL,)
        else:
            destinations = chess.SquareSet(chess.BB_KING_ATTACKS[square],)

        for destination in destinations:
            if destination == square or board.piece_at(destination,) is not None:
                continue

            if piece.piece_type == chess.PAWN and chess.square_rank(destination,) in (0, 7):
                continue

            variant = board.copy(stack=False,)
            variant.remove_piece_at(square,)

            variant.set_piece_at(
                destination,
                piece,
            )

            variant.castling_rights = variant.clean_castling_rights()
            variant.ep_square = None

            if variant.is_valid() and not variant.is_game_over() and variant.board_fen() not in used_positions:
                used_positions.add(variant.board_fen(),)

                return variant, {"piece": piece.symbol(), "from": chess.square_name(square,), "to": chess.square_name(destination,),}

    raise RuntimeError("No valid distinct exercise variant was found.",)

def generate_variants(
    board,
    base_move,
    used_positions,
):
    candidates = []

    for square, piece in board.piece_map().items():
        if square == base_move.from_square or piece.piece_type == chess.KING and len(board.piece_map(),) > 7:
            continue

        for destination in chess.SQUARES:
            if destination == square or board.piece_at(destination,) is not None:
                continue

            if piece.piece_type == chess.PAWN and chess.square_rank(destination,) in (0, 7):
                continue

            variant = board.copy(stack=False,)
            variant.remove_piece_at(square,)

            variant.set_piece_at(
                destination,
                piece,
            )

            variant.castling_rights = variant.clean_castling_rights()
            variant.ep_square = None

            if variant.is_valid() and not variant.is_game_over() and variant.board_fen() not in used_positions and base_move in variant.legal_moves:
                distance = chess.square_distance(
                    square,
                    destination,
                )

                candidates.append((variant, {"piece": piece.symbol(), "from": chess.square_name(square,), "to": chess.square_name(destination,),}, distance),)

    candidates.sort(key=lambda item: (item[2], hashlib.sha256(item[0].fen().encode(),).hexdigest()),)

    return candidates

def verify_related_exercise(
    analysis,
    board,
    base,
    role,
    used_positions,
    position_lock=None,
):
    position_lock = position_lock or threading.RLock()
    base_move = chess.Move.from_uci(base["solution"][0],)

    with position_lock:
        candidates = generate_variants(
            board,
            base_move,
            used_positions.copy(),
        )

    selected = None

    for variant, change, _ in candidates[:160]:
        preliminary = analysis.evaluate_move(
            variant.fen(),
            base_move.uci(),
            "instant",
            [],
        )

        loss = preliminary["assessment"]["verified"]["centipawn_loss"]
        mate_change = preliminary["assessment"]["verified"]["mate_change"]
        has_matching_relation = loss is not None and (loss <= 30 if role == "transfer" else loss >= 100) or role == "counterexample" and mate_change in ("loses forced mate", "allows forced mate")

        if not has_matching_relation:
            continue

        confirmed = analysis.evaluate_move(
            variant.fen(),
            base_move.uci(),
            "deep",
            [],
        )

        classification = confirmed["assessment"]["classification"]
        is_relation_confirmed = classification == "acceptable" if role == "transfer" else classification in ("inaccuracy", "serious mistake")

        if is_relation_confirmed:
            with position_lock:
                if variant.board_fen() in used_positions:
                    continue

                used_positions.add(variant.board_fen(),)
                selected = variant, change, confirmed

            break

    if selected is None:
        raise RuntimeError(f"No engine-confirmed {role} was found for {base['id']}. The initializer is resumable; completed exercises remain available.",)

    variant, change, comparison = selected

    variant_evidence = analysis.evaluate(
        variant.fen(),
        "quick",
        [],
    )

    return {"schema_version": 1, "id": base["id"] + "-" + role, "category": base["category"], "role": role, "base_id": base["id"], "fen": variant.fen(), "root_fen": variant.fen(), "history": [], "objective": base["objective"], "solution": variant_evidence["principal_variations"][0]["moves_uci"], "analysis_id": variant_evidence["id"], "source": base["source"], "position_change": change, "is_base_move_legal": True, "base_move_assessment": comparison["assessment"], "is_confirmed_counterexample": role == "counterexample", "validation": "The original candidate remains legal. Deeper comparisons confirm whether it remains acceptable or fails after this position change.", "construction_hash": hashlib.sha256(variant.fen().encode(),).hexdigest(),}

def initialize_original_exercises(
    analysis,
    store,
):
    records = create_original_bases(analysis,)

    used_positions = {record["fen"].split(" ",)[0] for record in store.list_records(
        "exercise",
        1000,
    )}

    position_lock = threading.RLock()

    def initialize_base(candidate,):
        base = store.get(
            "exercise",
            candidate["id"],
        )

        if base is None:
            base = candidate

            board = build_board(
                base["root_fen"],
                base["history"],
            )

            with position_lock:
                used_positions.add(board.board_fen(),)

            evidence = analysis.evaluate(
                base["root_fen"],
                "quick",
                base["history"],
            )

            base.update({"schema_version": 1, "role": "base", "solution": evidence["principal_variations"][0]["moves_uci"], "analysis_id": evidence["id"], "source": "Gambit original unannotated position construction, engine reviewed", "validation": "Legal position and engine continuation, not a proof of uniqueness or advanced difficulty", "related_ids": [base["id"] + "-transfer", base["id"] + "-counterexample",],},)

            store.put(
                "exercise",
                base["id"],
                base,
            )
        else:
            board = build_board(
                base["root_fen"],
                base["history"],
            )

        for role in ("transfer", "counterexample"):
            existing = store.get(
                "exercise",
                base["id"] + "-" + role,
            )

            if existing is not None and existing.get("is_base_move_legal",) and existing.get(
                "base_move_assessment",
                {},
            ).get("evidence_status",) == "deeper confirmation":
                continue

            related = verify_related_exercise(
                analysis,
                board,
                base,
                role,
                used_positions,
                position_lock,
            )

            store.put(
                "exercise",
                related["id"],
                related,
            )

        return base["id"]

    errors = []

    with ThreadPoolExecutor(
        max_workers=min(
            4,
            analysis.configuration.worker_count,
        ),
        thread_name_prefix="gambit-exercises",
    ) as executor:
        futures = {executor.submit(
            copy_context().run,
            initialize_base,
            candidate,
        ): candidate["id"] for candidate in records}

        for future in as_completed(futures,):
            try:
                future.result()
            except Exception as error:
                errors.append(f"{futures[future]}: {error}",)

    if errors:
        raise RuntimeError("Some original exercises remain incomplete. Rerun the initializer to resume. " + " | ".join(errors,),)

    return {"base_exercises": 32, "transfer_exercises": 32, "counterexamples": 32, "status": "initialized", "caveat": "Every related position keeps the original move legal and uses deeper comparisons to verify its changed or preserved quality.",}
