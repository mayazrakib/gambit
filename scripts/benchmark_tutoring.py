import argparse
import json
from statistics import median
from time import perf_counter

import chess

from gambit.engine.analysis import AnalysisService
from gambit.infrastructure.configuration import Configuration
from gambit.infrastructure.storage import Store
from gambit.knowledge.base import Knowledge
from gambit.learning.tutoring import Tutor

def run_benchmark(iterations: int,) -> dict:
    store = Store(":memory:",)
    service = AnalysisService(
        Configuration(),
        store,
    )
    tutor = Tutor(
        service,
        Knowledge(store,),
        store,
    )

    try:
        started = perf_counter()
        service.engine.warm_up()
        startup_ms = (perf_counter() - started) * 1000
        positions = [chess.STARTING_FEN,]
        board = chess.Board()

        for move in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6"):
            board.push_san(move,)
            positions.append(board.fen(),)

        samples = {}

        for mode in ("explain", "move", "compare"):
            timings = {"first": [], "cached": [],}
            payload_bytes = []

            for fen in positions:
                arguments = {"fen": fen,}
                board = chess.Board(fen,)
                candidates = [entry.uci() for entry in list(board.legal_moves,)[:2]]

                if mode == "move":
                    arguments["move"] = candidates[0]
                elif mode == "compare":
                    arguments.update(
                        intent="compare",
                        candidates=candidates,
                    )

                for index in range(iterations + 1,):
                    started = perf_counter()
                    result = tutor.create_turn(**arguments,)
                    elapsed_ms = (perf_counter() - started) * 1000
                    phase = "first" if index == 0 else "cached"
                    timings[phase].append(elapsed_ms,)
                    payload_bytes.append(len(json.dumps(result,).encode(),),)
                    assert result["engine_evidence"]["profile"] == "instant"
                    assert result["engine_evidence"]["fen"] == result["speech_plan"]["position_fen"]

            samples[mode] = {
                phase: {
                    "samples": len(values,),
                    "median_ms": median(values,),
                    "maximum_ms": max(values,),
                }
                for phase, values in timings.items()
            }
            samples[mode]["median_payload_bytes"] = median(payload_bytes,)

        return {
            "startup_ms": startup_ms,
            "engine": service.engine.get_metadata(),
            "samples": samples,
            "scope": "Local complete tutoring calls with an in-memory database and an empty opening corpus. Workers are warmed before calls. Modes share caches; first means the first call for each mode and position, not an isolated cold search. Excludes MCP transport, tunnel, ChatGPT, and audio latency.",
        }
    finally:
        service.close()
        store.close()

def main() -> None:
    parser = argparse.ArgumentParser(description="Measure complete instant tutoring calls and response sizes with warm engine workers.",)
    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
    )
    arguments = parser.parse_args()

    if not 1 <= arguments.iterations <= 20:
        parser.error("Choose between 1 and 20 cached iterations.",)

    print(json.dumps(
        run_benchmark(arguments.iterations,),
        indent=4,
    ),)

if __name__ == "__main__":
    main()
