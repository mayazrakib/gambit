import argparse
import json
import sys
from pathlib import Path
from time import sleep

sys.path.insert(
    0,
    str(Path(__file__,).resolve().parents[1] / "src",),
)

from gambit.infrastructure.data_service import DatasetService

def main() -> None:
    parser = argparse.ArgumentParser(description="Import downloaded Gambit chess material.",)

    parser.add_argument(
        "--directory",
        default="runtime",
    )

    parser.add_argument(
        "--username",
        default="mayazrakib",
    )

    parser.add_argument(
        "--kind",
        action="append",
        choices=("puzzles", "personal", "broadcast"),
    )

    parser.add_argument(
        "--wait-puzzles",
        action="store_true",
    )

    parser.add_argument("--evaluation-path",)
    parser.add_argument("--source",)
    parser.add_argument("--engine-name",)

    parser.add_argument(
        "--score-perspective",
        choices=("white", "side to move"),
    )

    arguments = parser.parse_args()

    if arguments.evaluation_path and not all((arguments.source, arguments.engine_name, arguments.score_perspective),):
        parser.error("Evaluation imports require --source, --engine-name, and --score-perspective.",)

    if arguments.wait_puzzles:
        while not (Path(arguments.directory,) / "downloads/lichess_db_puzzle.csv.zst").is_file():
            sleep(2,)

    service = DatasetService(arguments.directory,)

    try:
        if arguments.evaluation_path:
            print(
                json.dumps(service.corpus.import_evaluations(
                    arguments.evaluation_path,
                    arguments.source,
                    arguments.engine_name,
                    arguments.score_perspective,
                ),),
                flush=True,
            )

            return

        print(
            json.dumps(service.import_sources(
                arguments.username,
                arguments.kind,
            ),),
            flush=True,
        )
    finally:
        service.close()

if __name__ == "__main__":
    main()
