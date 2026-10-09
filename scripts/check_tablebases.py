import argparse
import json
from dataclasses import asdict

from gambit.infrastructure.configuration import load_configuration
from gambit.knowledge.tablebases import Tablebases

def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect local tablebases and optionally verify a trusted SHA-256 manifest.",)
    parser.add_argument("--manifest",)
    arguments = parser.parse_args()
    tables = Tablebases(load_configuration().syzygy_path,)

    try:
        report = asdict(tables.get_diagnostics(),)

        if arguments.manifest:
            report["checksums"] = tables.verify_checksums(arguments.manifest,)

        print(json.dumps(
            report,
            indent=4,
        ),)

        if arguments.manifest and not report["checksums"]["is_valid"]:
            raise SystemExit(1,)
    finally:
        tables.close()

if __name__ == "__main__":
    main()
