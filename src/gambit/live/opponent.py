import threading
from dataclasses import dataclass

import chess
import chess.engine

@dataclass(frozen=True,)
class OpponentSettings:
    player_color: str = "white"
    strength_mode: str = "skill"
    skill_level: int = 8
    target_elo: int = 1500
    budget_mode: str = "time"
    think_time_ms: int = 500
    depth: int = 12
    nodes: int = 100000
    threads: int = 1
    hash_mb: int = 32

    def __post_init__(self,):
        if self.player_color not in ("white", "black") or self.strength_mode not in ("skill", "elo", "full") or self.budget_mode not in ("time", "depth", "nodes"):
            raise ValueError("Choose a valid color, strength mode, and search budget.",)

        for name, lower, upper in (("skill_level", 0, 20), ("target_elo", 100, 4000), ("think_time_ms", 50, 5000), ("depth", 1, 24), ("nodes", 100, 2000000), ("threads", 1, 8), ("hash_mb", 16, 512)):
            value = getattr(
                self,
                name,
            )

            if type(value,) is not int or not lower <= value <= upper:
                raise ValueError(f"{name} must be between {lower} and {upper}.",)

class Opponent:
    def __init__(
        self,
        engine_path: str,
    ):
        self.engine_path = engine_path
        self.engine = None
        self.lock = threading.Lock()
        self.capabilities = None

    def open(self,):
        if self.engine is None:
            self.engine = chess.engine.SimpleEngine.popen_uci(
                self.engine_path,
                timeout=8,
            )

        return self.engine

    def get_capabilities(self,) -> dict:
        if self.capabilities is not None:
            return self.capabilities

        with self.lock:
            engine = self.open()

            self.capabilities = {
                "name": engine.id.get(
                    "name",
                    "Stockfish",
                ),
                "options": {name: {"min": option.min, "max": option.max, "default": option.default,} for name, option in engine.options.items() if name in ("Skill Level", "UCI_Elo", "UCI_LimitStrength", "Threads", "Hash")},
            }

            return self.capabilities

    def validate_settings(
        self,
        settings: dict,
    ) -> dict:
        configuration = OpponentSettings(**settings,)
        capabilities = self.get_capabilities()
        values = {"Threads": configuration.threads, "Hash": configuration.hash_mb, "UCI_LimitStrength": configuration.strength_mode == "elo", "Skill Level": configuration.skill_level if configuration.strength_mode == "skill" else 20,}

        if configuration.strength_mode == "elo":
            values["UCI_Elo"] = configuration.target_elo

        for name, value in values.items():
            option = capabilities["options"].get(name,)

            if option is None:
                raise ValueError(f"This engine does not support {name}.",)

            if type(value,) is int and ((option["min"] is not None and value < option["min"]) or (option["max"] is not None and value > option["max"])):
                raise ValueError(f"{name} must be between {option['min']} and {option['max']} for this engine.",)

        return values

    def play(
        self,
        board: chess.Board,
        settings: dict,
        game_id: str,
    ) -> str:
        configuration = OpponentSettings(**settings,)
        options = self.validate_settings(settings,)

        if not self.lock.acquire(blocking=False,):
            raise RuntimeError("Stockfish is already thinking. Wait for its current search to finish.",)

        try:
            engine = self.open()

            for name, value in options.items():
                option = engine.options.get(name,)

                if option is None:
                    raise ValueError(f"This engine does not support {name}.",)

                option.parse(value,)

            limit = chess.engine.Limit(
                time=configuration.think_time_ms / 1000,
                depth=configuration.depth if configuration.budget_mode == "depth" else None,
                nodes=configuration.nodes if configuration.budget_mode == "nodes" else None,
            )

            result = engine.play(
                board,
                limit,
                game=game_id,
                options=options,
            )

            if result.move is None or result.move not in board.legal_moves:
                raise RuntimeError("Stockfish returned no legal move.",)

            return result.move.uci()
        except (chess.engine.EngineError, TimeoutError):
            if self.engine is not None:
                self.engine.close()
                self.engine = None

            raise
        finally:
            self.lock.release()

    def close(self,):
        with self.lock:
            if self.engine is not None:
                self.engine.close()
                self.engine = None
