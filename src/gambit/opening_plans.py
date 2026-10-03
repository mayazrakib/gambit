import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import date

from gambit.contracts import (
    OpeningCoverage,
    OpeningPlanRecord,
    OpeningPlanReport,
    OpeningStatistics,
)
from gambit.engine import parse_board, parse_move
from gambit.knowledge import get_position_key
from gambit.storage import Store

STARTER_PLANS = (
    (
        "Open-game development",
        "e4 e5 Nf3 Nc6",
        ["Develop the remaining minor pieces and compare king-safety plans before beginning a flank attack.",],
        ["Evaluate a d4 central break against Black's available captures.",],
        ["Compare the bishop's development to b5 or c4, and explain the different pressure each creates.",],
        ["Repeated queen moves can concede development time; verify any concrete threat before making an exception.",],
    ),
    (
        "Sicilian central tension",
        "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3",
        ["Compare development and central control in this asymmetric pawn structure.",],
        ["For Black, assess whether d5 can be prepared safely rather than assuming it is immediately playable.",],
        ["Compare Black's kingside bishop development with the intended central pawn structure.",],
        ["An early attack without development may allow a central response; calculate the opponent's forcing replies.",],
    ),
    (
        "Queen's Gambit Declined development",
        "d4 d5 c4 e6 Nc3 Nf6",
        ["Develop pieces while tracking the tension between the c4 and d5 pawns.",],
        ["For Black, compare preparations for c5 with the consequences of changing the central structure.",],
        ["Consider how Black can activate the c8 bishop after the central structure is clarified.",],
        ["Releasing central tension changes the available plans; do not exchange solely because a capture is available.",],
    ),
    (
        "French pawn-chain plans",
        "e4 e6 d4 d5 e5",
        ["Identify the pawn-chain bases and relate piece development to future central breaks.",],
        ["For Black, examine c5 against d4 and the conditions for a later f6 break.",],
        ["Consider the constraints on Black's c8 bishop and the squares available to White's knights.",],
        ["A flank attack can be mistimed if the opponent can undermine the center; compare the timing concretely.",],
    ),
)

def load_starter_plans(store: Store,) -> int:
    import chess

    plans = OpeningPlans(store,)

    for name, sequence, objectives, breaks, placements, mistakes in STARTER_PLANS:
        board = chess.Board()

        for notation in sequence.split():
            board.push_san(notation,)

        plans.save_plan(OpeningPlan(
            name,
            board.fen(),
            objectives,
            breaks,
            placements,
            mistakes,
            "Gambit original teaching notes",
            "1",
            "2026-10-04",
        ),)

    return len(STARTER_PLANS,)

@dataclass(frozen=True,)
class OpeningPlan:
    name: str
    fen: str
    plans: list[str]
    pawn_breaks: list[str]
    piece_placements: list[str]
    common_mistakes: list[str]
    source: str
    source_version: str
    source_date: str

class OpeningPlans:
    def __init__(
        self,
        store: Store,
    ) -> None:
        self.store = store

    def save_plan(
        self,
        plan: OpeningPlan,
    ) -> OpeningPlanRecord:
        board = parse_board(plan.fen,)
        date.fromisoformat(plan.source_date,)
        payload = asdict(plan,)

        if not plan.name.strip() or not plan.source.strip() or not plan.source_version.strip() or len(json.dumps(payload,),) > 32000:
            raise ValueError("Opening plans require a name, source, version, and at most 32000 characters.",)

        for entries in (plan.plans, plan.pawn_breaks, plan.piece_placements, plan.common_mistakes):
            if len(entries,) > 20 or any((not entry.strip() or len(entry,) > 1000 for entry in entries),):
                raise ValueError("Opening plan sections support up to 20 nonempty entries of 1000 characters each.",)

        identifier = hashlib.sha256(json.dumps(
            payload,
            sort_keys=True,
        ).encode(),).hexdigest()
        record = {"schema_version": 1, "id": identifier, "position_key": get_position_key(board,), **payload, "evidence_kind": "source teaching advice", "is_engine_verified": False,}
        self.store.put(
            "opening_plan",
            identifier,
            record,
            is_immutable=True,
        )

        return record

    def get_plans(
        self,
        fen: str,
    ) -> OpeningPlanReport:
        key = get_position_key(parse_board(fen,),)

        return {
            "schema_version": 1,
            "plans": self.store.list_records(
                "opening_plan",
                100,
                0,
                key,
            ),
            "practical_statistics": self.store.list_records(
                "observation",
                100,
                0,
                key,
            ),
            "caveat": "Source advice and observed game outcomes are distinct from engine recommendations. A common mistake must be checked with move assessment in the actual position.",
        }

    def import_statistics(
        self,
        fen: str,
        move: str,
        white_wins: int,
        draws: int,
        black_wins: int,
        source: str,
        source_date: str,
        population: str,
    ) -> OpeningStatistics:
        board = parse_board(fen,)
        candidate = parse_move(
            board,
            move,
        )
        date.fromisoformat(source_date,)

        if any((type(count,) is not int or count < 0 or count > 1000000000 for count in (white_wins, draws, black_wins)),) or not source.strip() or not population.strip():
            raise ValueError("Opening statistics require bounded nonnegative counts, a source, and a population description.",)

        payload = {"schema_version": 1, "position_key": get_position_key(board,), "move_uci": candidate.uci(), "white_wins": white_wins, "draws": draws, "black_wins": black_wins, "source": source, "source_date": source_date, "population": population,}
        identifier = hashlib.sha256(json.dumps(
            payload,
            sort_keys=True,
        ).encode(),).hexdigest()
        self.store.put(
            "observation",
            identifier,
            {"id": identifier, **payload,},
            is_immutable=True,
        )

        return payload

    def get_coverage(self,) -> OpeningCoverage:
        with self.store.lock:
            rows = self.store.connection.execute("""
                    SELECT collection, json_extract(payload, '$.source'), count(*),
                        count(DISTINCT json_extract(payload, '$.position_key')),
                        min(system_created_at), max(system_updated_at)
                    FROM record
                    WHERE collection IN ('opening', 'opening_plan', 'repertoire', 'observation')

                    GROUP BY collection, json_extract(payload, '$.source')
                    ORDER BY collection, json_extract(payload, '$.source')
                    LIMIT 1000
                """,).fetchall()

        return {"schema_version": 1, "sources": [{"collection": row[0], "source": row[1], "records": row[2], "positions": row[3], "first_imported_at": row[4], "last_updated_at": row[5],} for row in rows], "is_exhaustive_chess_coverage": False, "source_limit": 1000,}
