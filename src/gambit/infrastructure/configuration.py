import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

from dotenv import dotenv_values

PACKAGE_DIRECTORY = Path(__file__,).resolve().parents[3]
DEFAULT_RUNTIME_DIRECTORY = str(PACKAGE_DIRECTORY / "runtime",)

def load_package_environment() -> None:
    package_directory = Path(__file__,).resolve().parents[3]
    environment_path = package_directory / ".env"

    for name, setting in dotenv_values(environment_path,).items():
        if setting is not None and (name.startswith("GAMBIT_",) or name == "STOCKFISH_PATH"):
            os.environ.setdefault(
                name,
                setting,
            )

@dataclass(frozen=True,)
class Configuration:
    runtime_directory: str = DEFAULT_RUNTIME_DIRECTORY
    engine_path: str = "stockfish"
    worker_count: int = 2
    threads_per_worker: int = 1
    hash_mb_per_worker: int = 64
    cache_capacity: int = 512
    is_reproducible: bool = False
    max_jobs: int = 16
    instant_nodes: int = 12000
    quick_nodes: int = 100000
    deep_nodes: int = 1000000
    candidate_count: int = 3
    instant_search_time_ms: int = 150
    quick_search_time_ms: int = 600
    search_time_ms: int = 5000
    search_depth: int = 64
    api_timeout_seconds: int = 8
    api_cache_capacity: int = 64
    api_max_response_bytes: int = 2 * 1024 * 1024

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
            "instant_search_time_ms": (50, 20000),
            "quick_search_time_ms": (50, 20000),
            "search_time_ms": (50, 20000),
            "search_depth": (1, 128),
            "api_timeout_seconds": (1, 30),
            "api_cache_capacity": (1, 512),
            "api_max_response_bytes": (1024, 8 * 1024 * 1024),
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
            "runtime_directory",
            "engine_path",
        ):
            if not isinstance(
                getattr(
                    self,
                    name,
                ),
                str,
            ):
                raise ValueError(f"Configuration {name} must be a string.",)

    def get_search_time_ms(
        self,
        nodes: int,
    ) -> int:
        if nodes <= self.instant_nodes:
            return min(
                self.instant_search_time_ms,
                self.search_time_ms,
            )

        if nodes <= self.quick_nodes:
            return min(
                self.quick_search_time_ms,
                self.search_time_ms,
            )

        return self.search_time_ms

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

    if os.environ.get("GAMBIT_RUNTIME_DIRECTORY",):
        settings["runtime_directory"] = os.environ["GAMBIT_RUNTIME_DIRECTORY"]

    return Configuration(**settings,)
