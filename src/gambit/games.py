"""Standard-chess game analysis. Scores always use White's perspective."""

import io
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from statistics import mean, median
from typing import Literal

import chess
import chess.pgn

from gambit.engine import (
    ENGINE_HASH_MB,
    ENGINE_THREADS,
    StockfishClient,
    get_variation,
    parse_board,
    validate_multipv,
    validate_nodes,
)

Side = Literal["white", "black"]
AnalysisSide = Literal["white", "black", "both"]
MoveClassification = Literal[
    "forced", "best", "excellent", "good", "inaccuracy", "mistake", "blunder"
]
MAX_PGN_BYTES = 262_144
MAX_GAME_PLIES = 1_024
MAX_BATCH_POSITIONS = 128
MAX_VARIATION_PLIES = 64
SUBSTANTIAL_ADVANTAGE_CP = 200
EQUAL_POSITION_CP = 50
MATE_LENGTH_CHANGE = 2
# Inclusive upper bounds, in centipawns. These are Gambit labels, not engine facts.
CLASSIFICATION_THRESHOLDS: tuple[tuple[int, MoveClassification], ...] = (
    (20, "excellent"),
    (50, "good"),
    (100, "inaccuracy"),
    (200, "mistake"),
)


@dataclass(frozen=True)
class ParsedMove:
    ply: int
    move_number: int
    side: Side
    san: str
    uci: str
    fen_before: str
    fen_after: str
    comment: str | None
    clock_seconds: float | None
    elapsed_move_seconds: float | None
    numeric_annotation_glyphs: tuple[int, ...]


@dataclass(frozen=True)
class ParsedGame:
    headers: Mapping[str, str]
    initial_fen: str
    result: str | None
    moves: tuple[ParsedMove, ...]


@dataclass(frozen=True)
class EngineEvaluation:
    centipawns: int | None
    mate_in: int | None
    # Disambiguates terminal mate_in=0, which cannot carry a sign in JSON.
    mating_side: Side | None = None


@dataclass(frozen=True)
class PrincipalVariation:
    rank: int
    evaluation: EngineEvaluation
    moves_uci: tuple[str, ...]
    moves_san: tuple[str, ...]


@dataclass(frozen=True)
class PositionAnalysisRequest:
    fen: str
    nodes: int = 100_000
    multipv: int = 3


@dataclass(frozen=True)
class PositionAnalysis:
    fen: str
    evaluation: EngineEvaluation
    principal_variations: tuple[PrincipalVariation, ...]


@dataclass(frozen=True)
class MoveAnalysis(ParsedMove):
    evaluation_before: EngineEvaluation
    evaluation_after: EngineEvaluation
    best_move_san: str
    best_move_uci: str
    played_move_rank: int | None
    centipawn_loss: int | None
    principal_variations: tuple[PrincipalVariation, ...]
    nodes: int
    was_reanalyzed: bool
    is_critical: bool


@dataclass(frozen=True)
class EngineMetadata:
    name: str
    version: str | None
    initial_nodes: int
    critical_nodes: int
    multipv: int
    threads: int
    hash_mb: int


@dataclass(frozen=True)
class GameAnalysis:
    headers: Mapping[str, str]
    initial_fen: str
    result: str | None
    moves: tuple[MoveAnalysis, ...]
    engine: EngineMetadata


@dataclass(frozen=True)
class PositionFeatures:
    legal_move_count: int
    is_check: bool
    is_checkmate: bool
    is_stalemate: bool


@dataclass(frozen=True)
class MoveReview:
    analysis: MoveAnalysis
    is_best_move: bool
    best_move_difference_cp: int | None
    is_forced: bool
    legal_move_count: int
    classification: MoveClassification
    features_before: PositionFeatures
    features_after: PositionFeatures


@dataclass(frozen=True)
class PlayerGameSummary:
    side: Side
    move_count: int
    forced_moves: int
    best_moves: int
    excellent_moves: int
    good_moves: int
    inaccuracies: int
    mistakes: int
    blunders: int
    average_centipawn_loss: float | None
    median_centipawn_loss: float | None
    largest_centipawn_loss: int | None
    largest_loss_ply: int | None
    critical_plies: tuple[int, ...]


@dataclass(frozen=True)
class GameReview:
    headers: Mapping[str, str]
    initial_fen: str
    result: str | None
    moves: tuple[MoveReview, ...]
    engine: EngineMetadata
    summaries: tuple[PlayerGameSummary, ...]


class ValidatedGameBuilder(chess.pgn.GameBuilder):
    """Make python-chess parsing errors fatal instead of returning partial games."""

    def begin_game(self) -> None:
        super().begin_game()
        self.game.headers.clear()
        self.initial_ply = 0
        self.has_result = False

    def end_headers(self) -> None:
        if self.game.headers.get("Variant", "Standard").lower() not in (
            "standard",
            "chess",
            "normal",
        ):
            raise ValueError("Only standard chess PGN is supported.")
        board = parse_board(self.game.headers.get("FEN", chess.STARTING_FEN))
        self.initial_ply = board.ply()
        if self.game.headers.get("SetUp") == "1" and "FEN" not in self.game.headers:
            raise ValueError("PGN SetUp=1 requires a FEN header.")
        if self.game.headers.get("Result", "*") not in ("*", "1-0", "0-1", "1/2-1/2"):
            raise ValueError("Invalid PGN Result header.")

    def parse_san(self, board: chess.Board, san: str) -> chess.Move:
        if self.has_result:
            raise ValueError("PGN contains moves after its result.")
        try:
            move = super().parse_san(board, san)
            if move not in board.legal_moves:
                raise ValueError("Null moves are not legal game moves.")
            return move
        except ValueError as exception:
            raise ValueError(
                f"Illegal SAN {san!r} at move {board.fullmove_number}, "
                f"ply {board.ply() - self.initial_ply + 1}: {exception}"
            ) from exception

    def visit_result(self, result: str) -> None:
        header_result = self.game.headers.get("Result", "*")
        if self.has_result or (header_result != "*" and header_result != result):
            raise ValueError("PGN has conflicting or duplicate results.")
        self.has_result = True
        super().visit_result(result)

    def handle_error(self, error: Exception) -> None:
        raise ValueError(f"Invalid PGN: {error}") from error


def validate_pgn_tokens(pgn: str) -> None:
    """Reject text the forgiving library lexer would otherwise silently skip."""
    token_pattern = re.compile(
        r"\s+|\ufeff|\{[^}]*\}|;[^\n]*|(?m:^%[^\n]*)|"
        r'(?m:^\[[A-Za-z0-9][A-Za-z0-9_+#=:-]*\s+"[^\r\n]*"\][ \t]*$)|'
        r"\d+\.(?:\.\.)?|(?:" + chess.pgn.MOVETEXT_REGEX.pattern + r")[+#]?",
        re.VERBOSE,
    )
    offset = 0
    variation_depth = 0
    has_movetext = False
    while offset < len(pgn):
        match = token_pattern.match(pgn, offset)
        if (
            match is None
            or match.group().startswith("{")
            and not match.group().endswith("}")
        ):
            raise ValueError(
                f"Malformed PGN near character {offset + 1}: {pgn[offset : offset + 32]!r}"
            )
        token = match.group()
        if token.startswith("["):
            if has_movetext:
                raise ValueError(
                    "PGN headers must precede movetext; submit exactly one game."
                )
        elif not token.isspace() and not token.startswith(("{", ";", "%", "\ufeff")):
            has_movetext = True
        if token == "(":
            variation_depth += 1
        elif token == ")":
            variation_depth -= 1
            if variation_depth < 0:
                raise ValueError("PGN has an unmatched variation closing parenthesis.")
        offset = match.end()
    if variation_depth:
        raise ValueError("PGN has an unclosed variation.")


def parse_game(pgn: str) -> ParsedGame:
    if not pgn.strip():
        raise ValueError("pgn must be non-empty.")
    if len(pgn.encode("utf-8")) > MAX_PGN_BYTES:
        raise ValueError(f"pgn must contain at most {MAX_PGN_BYTES} UTF-8 bytes.")
    pgn = pgn.replace("\r\n", "\n").replace("\r", "\n").lstrip("\ufeff")
    validate_pgn_tokens(pgn)
    stream = io.StringIO(pgn)
    game = chess.pgn.read_game(stream, Visitor=ValidatedGameBuilder)
    if game is None:
        raise ValueError("pgn must contain a game.")
    if chess.pgn.read_game(stream, Visitor=ValidatedGameBuilder) is not None:
        raise ValueError("Submit exactly one PGN game.")
    board = parse_board(game.board().fen())
    initial_fen = board.fen()
    moves: list[ParsedMove] = []
    for ply, node in enumerate(game.mainline(), start=1):
        if ply > MAX_GAME_PLIES:
            raise ValueError(f"Game exceeds {MAX_GAME_PLIES} plies.")
        fen_before = board.fen()
        san = board.san(node.move)
        side: Side = "white" if board.turn else "black"
        move_number = board.fullmove_number
        board.push(node.move)
        moves.append(
            ParsedMove(
                ply,
                move_number,
                side,
                san,
                node.move.uci(),
                fen_before,
                board.fen(),
                node.comment or None,
                node.clock(),
                node.emt(),
                tuple(sorted(node.nags)),
            )
        )
    # A header-only game is valid to inspect, but not to engine-analyze.
    return ParsedGame(
        dict(game.headers), initial_fen, game.headers.get("Result"), tuple(moves)
    )


def normalize_evaluation(
    centipawns: int | None, mate_in: int | None, turn: chess.Color
) -> EngineEvaluation:
    sign = 1 if turn == chess.WHITE else -1
    if mate_in is not None:
        mate = mate_in * sign
        # UCI mate 0 means the side to move has already been mated.
        mating_side: Side = (
            ("black" if turn else "white")
            if mate_in == 0
            else ("white" if mate > 0 else "black")
        )
        return EngineEvaluation(None, mate, mating_side)
    if centipawns is None:
        raise RuntimeError("Stockfish returned a variation without an evaluation.")
    return EngineEvaluation(centipawns * sign, None)


def analyze_board(
    board: chess.Board, engine: StockfishClient, nodes: int, multipv: int
) -> PositionAnalysis:
    if board.is_checkmate():
        return PositionAnalysis(
            board.fen(), normalize_evaluation(None, 0, board.turn), ()
        )
    if board.is_game_over(claim_draw=False):
        return PositionAnalysis(board.fen(), EngineEvaluation(0, None), ())
    lines = engine.analyze(board, multipv, nodes)
    variations: list[PrincipalVariation] = []
    for rank, line in enumerate(lines, start=1):
        moves = get_variation(board, line["pv"][:MAX_VARIATION_PLIES])
        if not moves:
            raise RuntimeError(
                f"Stockfish returned an invalid root move for {board.fen()} (rank {rank})."
            )
        variations.append(
            PrincipalVariation(
                rank,
                normalize_evaluation(line["centipawns"], line["mate_in"], board.turn),
                tuple(move["uci"] for move in moves),
                tuple(move["san"] for move in moves),
            )
        )
    if not variations:
        raise RuntimeError(f"Stockfish returned no variations for {board.fen()}.")
    return PositionAnalysis(board.fen(), variations[0].evaluation, tuple(variations))


def analyze_positions(
    positions: Sequence[PositionAnalysisRequest], engine: StockfishClient
) -> tuple[PositionAnalysis, ...]:
    if not 1 <= len(positions) <= MAX_BATCH_POSITIONS:
        raise ValueError(
            f"positions must contain between 1 and {MAX_BATCH_POSITIONS} requests."
        )
    boards: list[chess.Board] = []
    for index, request in enumerate(positions):
        try:
            validate_nodes(request.nodes)
            validate_multipv(request.multipv)
            boards.append(parse_board(request.fen))
        except (ValueError, TypeError) as exception:
            raise ValueError(
                f"Invalid position request {index + 1}: {exception}"
            ) from exception
    cache: dict[tuple[str, int, int], PositionAnalysis] = {}
    results: list[PositionAnalysis] = []
    for request, board in zip(positions, boards, strict=True):
        key = (board.fen(), request.nodes, request.multipv)
        if key not in cache:
            cache[key] = analyze_board(board, engine, request.nodes, request.multipv)
        results.append(cache[key])
    return tuple(results)


def calculate_centipawn_loss(
    before: EngineEvaluation, after: EngineEvaluation, side: Side
) -> int | None:
    if before.centipawns is None or after.centipawns is None:
        return None
    return max(
        0, (before.centipawns - after.centipawns) * (1 if side == "white" else -1)
    )


def is_mate_transition(
    before: EngineEvaluation, after: EngineEvaluation, side: Side
) -> bool:
    if before.mating_side != after.mating_side:
        return True
    if before.mate_in is None or after.mate_in is None:
        return False
    expected_distance = max(0, abs(before.mate_in) - (before.mating_side == side))
    return abs(abs(after.mate_in) - expected_distance) >= MATE_LENGTH_CHANGE


def is_critical_move(
    before: EngineEvaluation, after: EngineEvaluation, side: Side, critical_loss_cp: int
) -> bool:
    loss = calculate_centipawn_loss(before, after, side)
    if loss is not None and loss >= critical_loss_cp:
        return True
    if is_mate_transition(before, after, side):
        return True
    if before.centipawns is None or after.centipawns is None:
        return False
    first, second = before.centipawns, after.centipawns
    return (
        first * second < 0
        and min(abs(first), abs(second)) >= SUBSTANTIAL_ADVANTAGE_CP
        or abs(first) >= SUBSTANTIAL_ADVANTAGE_CP
        and abs(second) <= EQUAL_POSITION_CP
        or abs(first) <= EQUAL_POSITION_CP
        and abs(second) >= SUBSTANTIAL_ADVANTAGE_CP
    )


def validate_game_options(
    side: AnalysisSide,
    initial_nodes: int,
    critical_nodes: int,
    multipv: int,
    critical_loss_cp: int,
) -> None:
    if side not in ("white", "black", "both"):
        raise ValueError("side must be white, black, or both.")
    validate_nodes(initial_nodes)
    validate_nodes(critical_nodes)
    validate_multipv(multipv)
    if critical_nodes < initial_nodes:
        raise ValueError("critical_nodes must be at least initial_nodes.")
    if (
        isinstance(critical_loss_cp, bool)
        or not isinstance(critical_loss_cp, int)
        or critical_loss_cp < 0
    ):
        raise ValueError("critical_loss_cp must be a non-negative integer.")


def analyze_game(
    pgn: str,
    engine: StockfishClient,
    side: AnalysisSide = "both",
    initial_nodes: int = 20_000,
    critical_nodes: int = 250_000,
    multipv: int = 3,
    critical_loss_cp: int = 40,
) -> GameAnalysis:
    validate_game_options(
        side, initial_nodes, critical_nodes, multipv, critical_loss_cp
    )
    game = parse_game(pgn)
    if not game.moves:
        raise ValueError("Game analysis requires at least one played move.")
    selected = tuple(move for move in game.moves if side == "both" or move.side == side)
    boards: dict[str, chess.Board] = {}
    cache: dict[tuple[str, int, int], PositionAnalysis] = {}

    def get_analysis(fen: str, nodes: int) -> PositionAnalysis:
        key = (fen, nodes, multipv)
        if key not in cache:
            if fen not in boards:
                boards[fen] = parse_board(fen)
            cache[key] = analyze_board(boards[fen], engine, nodes, multipv)
        return cache[key]

    # Finish the cheap pass before selecting any deeper searches.
    for move in selected:
        get_analysis(move.fen_before, initial_nodes)
        get_analysis(move.fen_after, initial_nodes)
    critical_plies = {
        move.ply
        for move in selected
        if is_critical_move(
            get_analysis(move.fen_before, initial_nodes).evaluation,
            get_analysis(move.fen_after, initial_nodes).evaluation,
            move.side,
            critical_loss_cp,
        )
    }
    analyses: list[MoveAnalysis] = []
    for move in selected:
        is_critical = move.ply in critical_plies
        nodes = critical_nodes if is_critical else initial_nodes
        before = get_analysis(move.fen_before, nodes)
        after = get_analysis(move.fen_after, nodes)
        if not before.principal_variations:
            raise ValueError(
                f"Cannot analyze ply {move.ply}: move played from a terminal position."
            )
        best = before.principal_variations[0]
        rank = next(
            (
                variation.rank
                for variation in before.principal_variations
                if variation.moves_uci[0] == move.uci
            ),
            None,
        )
        analyses.append(
            MoveAnalysis(
                move.ply,
                move.move_number,
                move.side,
                move.san,
                move.uci,
                move.fen_before,
                move.fen_after,
                move.comment,
                move.clock_seconds,
                move.elapsed_move_seconds,
                move.numeric_annotation_glyphs,
                before.evaluation,
                after.evaluation,
                best.moves_san[0],
                best.moves_uci[0],
                rank,
                calculate_centipawn_loss(
                    before.evaluation, after.evaluation, move.side
                ),
                before.principal_variations,
                nodes,
                is_critical and critical_nodes > initial_nodes,
                is_critical,
            )
        )
    return GameAnalysis(
        game.headers,
        game.initial_fen,
        game.result,
        tuple(analyses),
        EngineMetadata(
            engine.name,
            engine.version,
            initial_nodes,
            critical_nodes,
            multipv,
            ENGINE_THREADS,
            ENGINE_HASH_MB,
        ),
    )


def get_position_features(fen: str) -> PositionFeatures:
    board = parse_board(fen)
    return PositionFeatures(
        board.legal_moves.count(),
        board.is_check(),
        board.is_checkmate(),
        board.is_stalemate(),
    )


def classify_move(move: MoveAnalysis, legal_move_count: int) -> MoveClassification:
    if legal_move_count == 1:
        return "forced"
    before, after = move.evaluation_before, move.evaluation_after
    if before.mate_in is not None or after.mate_in is not None:
        if (
            before.mating_side == move.side
            and after.mating_side != move.side
            or after.mating_side is not None
            and after.mating_side != move.side
            and before.mating_side != after.mating_side
        ):
            return "blunder"
        if move.uci == move.best_move_uci:
            return "best"
        if after.mating_side == move.side:
            return (
                "good"
                if before.mating_side == move.side
                and is_mate_transition(before, after, move.side)
                else "excellent"
            )
        if before.mating_side is not None and after.mating_side is None:
            return "excellent"
        # Retaining an opponent's forced mate cannot be assigned an ordinary CP loss.
        return "good"
    if move.uci == move.best_move_uci:
        return "best"
    if move.centipawn_loss is None:
        raise ValueError("Non-mate move is missing its centipawn loss.")
    for upper_bound, classification in CLASSIFICATION_THRESHOLDS:
        if move.centipawn_loss <= upper_bound:
            return classification
    return "blunder"


def summarize_player(side: Side, moves: Sequence[MoveReview]) -> PlayerGameSummary:
    selected = tuple(move for move in moves if move.analysis.side == side)
    losses = [
        move.analysis.centipawn_loss
        for move in selected
        if move.analysis.centipawn_loss is not None
    ]
    largest = max(losses) if losses else None
    largest_ply = next(
        (
            move.analysis.ply
            for move in selected
            if largest is not None and move.analysis.centipawn_loss == largest
        ),
        None,
    )
    return PlayerGameSummary(
        side,
        len(selected),
        sum(move.classification == "forced" for move in selected),
        sum(move.classification == "best" for move in selected),
        sum(move.classification == "excellent" for move in selected),
        sum(move.classification == "good" for move in selected),
        sum(move.classification == "inaccuracy" for move in selected),
        sum(move.classification == "mistake" for move in selected),
        sum(move.classification == "blunder" for move in selected),
        float(mean(losses)) if losses else None,
        float(median(losses)) if losses else None,
        largest,
        largest_ply,
        tuple(move.analysis.ply for move in selected if move.analysis.is_critical),
    )


def review_game(
    pgn: str,
    engine: StockfishClient,
    side: AnalysisSide = "both",
    initial_nodes: int = 20_000,
    critical_nodes: int = 250_000,
    multipv: int = 3,
    critical_loss_cp: int = 40,
) -> GameReview:
    game = analyze_game(
        pgn, engine, side, initial_nodes, critical_nodes, multipv, critical_loss_cp
    )
    features: dict[str, PositionFeatures] = {}
    reviews: list[MoveReview] = []
    for move in game.moves:
        for fen in (move.fen_before, move.fen_after):
            if fen not in features:
                features[fen] = get_position_features(fen)
        before, after = features[move.fen_before], features[move.fen_after]
        reviews.append(
            MoveReview(
                move,
                move.uci == move.best_move_uci,
                move.centipawn_loss,
                before.legal_move_count == 1,
                before.legal_move_count,
                classify_move(move, before.legal_move_count),
                before,
                after,
            )
        )
    sides: tuple[Side, ...] = ("white", "black") if side == "both" else (side,)
    return GameReview(
        game.headers,
        game.initial_fen,
        game.result,
        tuple(reviews),
        game.engine,
        tuple(summarize_player(player, reviews) for player in sides),
    )
