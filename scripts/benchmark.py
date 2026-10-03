import json
import platform
import statistics
import tempfile
from pathlib import Path
from time import perf_counter

import chess

from gambit.analysis import AnalysisService
from gambit.configuration import Configuration
from gambit.storage import Store

def main() -> None:
    with tempfile.TemporaryDirectory(prefix="gambit-benchmark-",) as directory:
        store = Store(str(Path(directory,) / "benchmark.sqlite3",),)
        service = AnalysisService(
            Configuration(worker_count=1,),
            store,
        )

        try:
            samples = []
            positions = [chess.STARTING_FEN,]
            board = chess.Board()

            for move in ("e4", "e5", "Nf3", "Nc6", "Bb5", "a6"):
                board.push_san(move,)
                positions.append(board.fen(),)

            for profile in ("instant", "quick", "deep"):
                elapsed_ms = []

                for fen in positions:
                    started = perf_counter()
                    service.evaluate(
                        fen,
                        profile,
                    )
                    elapsed_ms.append((perf_counter() - started) * 1000,)

                cached_started = perf_counter()
                service.evaluate(
                    positions[-1],
                    profile,
                )
                samples.append({"profile": profile, "first_position_ms": elapsed_ms[0], "median_ms": statistics.median(elapsed_ms,), "maximum_ms": max(elapsed_ms,), "cached_ms": (perf_counter() - cached_started) * 1000, "position_count": len(positions,),},)

            print(json.dumps(
                {"python": platform.python_version(), "platform": platform.platform(), "engine": service.engine.get_metadata(), "samples": samples, "scope": "Local service calls, including SQLite evidence writes; not MCP, model, or audio latency.",},
                indent=4,
            ),)
        finally:
            service.close()
            store.close()

if __name__ == "__main__":
    main()
