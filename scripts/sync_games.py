import argparse
import json

from gambit.infrastructure.configuration import DEFAULT_RUNTIME_DIRECTORY
from gambit.infrastructure.data_service import DatasetService

def main() -> None:
    parser = argparse.ArgumentParser(description="Import Chess.com history, then synchronize recent months without engine analysis.",)

    parser.add_argument(
        "--directory",
        default=DEFAULT_RUNTIME_DIRECTORY,
    )

    parser.add_argument(
        "--username",
        default="mayazrakib",
    )

    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Revalidate historical months as well as the current and previous month.",
    )

    arguments = parser.parse_args()
    service = DatasetService(arguments.directory,)

    try:
        print(json.dumps(service.sync_games(
            arguments.username,
            arguments.refresh,
        ),),)
    finally:
        service.close()

if __name__ == "__main__":
    main()
