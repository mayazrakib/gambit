import chess

from gambit.engine import parse_board

PIECE_POINTS = {
    chess.PAWN: 1,
    chess.KNIGHT: 3,
    chess.BISHOP: 3,
    chess.ROOK: 5,
    chess.QUEEN: 9,
    chess.KING: 0,
}

def inspect_features(fen: str,) -> dict:
    board = parse_board(fen,)
    sides = {}

    for color, name in ((chess.WHITE, "white"), (chess.BLACK, "black")):
        pawns = board.pieces(
            chess.PAWN,
            color,
        )
        enemy_pawns = board.pieces(
            chess.PAWN,
            not color,
        )
        pawn_files = [chess.square_file(square,) for square in pawns]
        isolated = []
        passed = []

        for square in pawns:
            file_index = chess.square_file(square,)
            rank = chess.square_rank(square,)

            if all((abs(other_file - file_index,) != 1 for other_file in pawn_files),):
                isolated.append(chess.square_name(square,),)

            blockers = [
                enemy
                for enemy in enemy_pawns
                if abs(chess.square_file(enemy,) - file_index,) <= 1
                and (chess.square_rank(enemy,) > rank if color else chess.square_rank(enemy,) < rank)
            ]

            if not blockers:
                passed.append(chess.square_name(square,),)

        pinned = []
        undefended = []
        forks = []

        for square, piece in board.piece_map().items():
            if piece.color != color:
                continue

            if board.is_pinned(
                color,
                square,
            ):
                pinned.append(chess.square_name(square,),)

            if piece.piece_type != chess.KING and not board.is_attacked_by(
                color,
                square,
            ):
                undefended.append(chess.square_name(square,),)

            targets = [
                chess.square_name(target,)
                for target in board.attacks(square,)
                if board.piece_at(target,) is not None
                and board.color_at(target,) != color
                and board.piece_type_at(target,) != chess.PAWN
            ]

            if len(targets,) >= 2:
                forks.append({
                    "attacker": chess.square_name(square,),
                    "targets": targets,
                    "is_forced_win": False,
                },)

        sides[name] = {
            "material_points": sum((PIECE_POINTS[piece.piece_type]
                for piece in board.piece_map().values()
                if piece.color == color),),
            "isolated_pawns": isolated,
            "passed_pawns": passed,
            "doubled_pawn_files": [
                chess.FILE_NAMES[index] for index in range(8,) if pawn_files.count(index,) > 1
            ],
            "pinned_pieces": pinned,
            "undefended_pieces": undefended,
            "fork_candidates": forks,
            "has_bishop_pair": len(board.pieces(
                chess.BISHOP,
                color,
            ),) >= 2,
            "king_square": chess.square_name(board.king(color,),),
        }

    return {
        "fen": board.fen(),
        "sides": sides,
        "legal_move_count": board.legal_moves.count(),
        "is_check": board.is_check(),
        "is_checkmate": board.is_checkmate(),
        "is_stalemate": board.is_stalemate(),
        "can_claim_fifty_moves": board.can_claim_fifty_moves(),
        "provenance": "rules and geometric features",
        "caveat": "Geometric attacks and undefended pieces do not by themselves prove a tactical win.",
    }
