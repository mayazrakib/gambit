import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import dotenv_values

def load_package_environment() -> None:
    package_directory = Path(__file__,).resolve().parents[2]
    environment_path = package_directory / ".env"

    for name, setting in dotenv_values(environment_path,).items():
        if setting is not None and (name.startswith("GAMBIT_",) or name == "STOCKFISH_PATH"):
            os.environ.setdefault(
                name,
                setting,
            )

@dataclass(frozen=True,)
class Configuration:
    database_path: str = "~/.local/share/gambit/gambit.sqlite3"
    engine_path: str = "stockfish"
    worker_count: int = 2
    threads_per_worker: int = 1
    hash_mb_per_worker: int = 64
    cache_capacity: int = 512
    is_reproducible: bool = False
    syzygy_path: str = ""
    speech_executable: str = "espeak-ng"
    speech_directory: str = "~/.cache/gambit/speech"
    max_jobs: int = 16
    instant_nodes: int = 12000
    quick_nodes: int = 100000
    deep_nodes: int = 1000000
    candidate_count: int = 3
    search_time_ms: int = 5000
    search_depth: int = 64

    def __post_init__(self,) -> None:
        limits = {
            "worker_count": (1, 8),
            "threads_per_worker": (1, 64),
            "hash_mb_per_worker": (16, 4096),
            "cache_capacity": (1, 10000),
            "max_jobs": (1, 128),
            "instant_nodes": (1, 2000000),
            "quick_nodes": (1, 2000000),
            "deep_nodes": (1, 2000000),
            "candidate_count": (1, 5),
            "search_time_ms": (50, 20000),
            "search_depth": (1, 128),
        }

        for name, bounds in limits.items():
            quantity = getattr(
                self,
                name,
            )

            if type(quantity,) is not int or not bounds[0] <= quantity <= bounds[1]:
                raise ValueError(f"Configuration {name} must be between {bounds[0]} and {bounds[1]}.",)

        if type(self.is_reproducible,) is not bool:
            raise ValueError("Configuration is_reproducible must be a boolean.",)

        for name in (
            "database_path",
            "engine_path",
            "syzygy_path",
            "speech_executable",
            "speech_directory",
        ):
            if not isinstance(
                getattr(
                    self,
                    name,
                ),
                str,
            ):
                raise ValueError(f"Configuration {name} must be a string.",)

def load_configuration() -> Configuration:
    load_package_environment()
    configuration_path = os.environ.get("GAMBIT_CONFIG",)
    settings = {}

    if configuration_path:
        with Path(configuration_path,).expanduser().open("rb",) as configuration_file:
            settings = tomllib.load(configuration_file,)

    known_names = {field.name for field in fields(Configuration,)}
    unknown_names = set(settings,) - known_names

    if unknown_names:
        raise ValueError(f"Unknown Gambit configuration keys: {sorted(unknown_names,)}.",)

    if os.environ.get("STOCKFISH_PATH",):
        settings["engine_path"] = os.environ["STOCKFISH_PATH"]

    if os.environ.get("GAMBIT_DATABASE",):
        settings["database_path"] = os.environ["GAMBIT_DATABASE"]

    return Configuration(**settings,)
