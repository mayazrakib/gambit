import argparse
import json
import platform
from dataclasses import asdict
from pathlib import Path
from statistics import median
from time import perf_counter

import chess

from gambit.analysis import AnalysisService
from gambit.configuration import Configuration
from gambit.features import inspect_features
from gambit.knowledge import Knowledge
from gambit.storage import Store
from gambit.tutoring import Tutor

def run_benchmark(
    iterations: int,
    configuration: Configuration | None = None,
) -> dict:
    fixtures = Path(__file__,).resolve().parents[1] / "test" / "fixtures" / "quality_positions.json"
    positions = json.loads(fixtures.read_text(),)
    timings = {"cold": [], "warm": [],}
    checks = []
    configuration = configuration or Configuration()
    metadata = None

    for _ in range(iterations,):
        for position in positions:
            store = Store(":memory:",)
            service = AnalysisService(
                configuration,
                store,
            )

            try:
                tutor = Tutor(
                    service,
                    Knowledge(store,),
                    store,
                )

                for phase in ("cold", "warm"):
                    started = perf_counter()
                    report = service.evaluate(
                        position["fen"],
                        "quick",
                    )
                    timings[phase].append((perf_counter() - started) * 1000,)
                    board = chess.Board(position["fen"],)
                    assert board.is_game_over() == position["is_terminal"]

                    if position["best_move"]:
                        assert report["principal_variations"][0]["moves_uci"][0] == position["best_move"]

                    for variation in report["principal_variations"]:
                        replay = board.copy()

                        for move in variation["moves_uci"]:
                            assert chess.Move.from_uci(move,) in replay.legal_moves
                            replay.push_uci(move,)

                    if position.get("pinned_square",):
                        features = inspect_features(position["fen"],)
                        assert position["pinned_square"] in features["sides"]["white"]["pinned_pieces"]

                hint = tutor.create_turn(
                    position["fen"],
                    intent="hint",
                )
                assert hint["engine_evidence"]["is_solution_hidden"]
                assert not hint["board_directives"]
                assert not hint["speech_plan"]["pronunciations"]
                checks.append(position["name"],)

                if service.engine.get_metadata()["version"] is not None:
                    metadata = service.engine.get_metadata()
            finally:
                service.close()
                store.close()

    summaries = {}

    for phase, samples in timings.items():
        ordered = sorted(samples,)
        summaries[phase] = {
            "samples": len(samples,),
            "median_ms": median(samples,),
            "p95_ms": ordered[min(
                len(ordered,) - 1,
                int(len(ordered,) * 0.95,),
            )],
            "raw_ms": samples,
        }

    return {"schema_version": 1, "platform": platform.platform(), "python": platform.python_version(), "configuration": asdict(configuration,), "engine": metadata, "quality_checks_passed": checks, "latency": summaries, "scope": "Local engine-to-storage latency and deterministic teaching invariants. Excludes MCP transport, tunnel latency, model generation, audio, and human teaching-quality assessment. Cold cases use fresh workers; warm cases reuse their cached search.",}

def main() -> None:
    parser = argparse.ArgumentParser(description="Benchmark cold and warm local analysis and run fixed chess-quality checks.",)
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
    )
    arguments = parser.parse_args()

    if not 1 <= arguments.iterations <= 20:
        parser.error("Choose between 1 and 20 benchmark iterations.",)

    print(json.dumps(
        run_benchmark(arguments.iterations,),
        indent=4,
    ),)

if __name__ == "__main__":
    main()
