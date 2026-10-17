import threading
from dataclasses import asdict
from uuid import uuid4

import chess

from gambit.engine.client import parse_board, parse_move
from gambit.game.position import validate_draw_claim
from gambit.infrastructure.storage import Store
from gambit.live.opponent import OpponentSettings
from gambit.live.position import build_position, render_position

class LiveConflict(ValueError,):
    pass

class LiveGames:
    def __init__(
        self,
        store: Store,
    ) -> None:
        self.store = store
        self.listeners = set()
        self.listener_lock = threading.Lock()

    def notify(self,):
        with self.listener_lock:
            for loop, event in self.listeners:
                if not loop.is_closed():
                    loop.call_soon_threadsafe(event.set,)

    def subscribe(
        self,
        loop,
        event,
    ):
        with self.listener_lock:
            self.listeners.add((loop, event),)

    def unsubscribe(
        self,
        loop,
        event,
    ):
        with self.listener_lock:
            self.listeners.discard((loop, event),)

    def read(
        self,
        game_id: str | None = None,
    ) -> dict:
        game = self.store.get(
            "live_game",
            "active",
        )

        if game is None:
            raise LiveConflict("Start a game in the local playing interface first.",)

        if game_id is not None and game["game_id"] != game_id:
            raise LiveConflict("The active game changed. Read the current game.",)

        return game

    def create(
        self,
        settings: dict,
        root_fen: str = chess.STARTING_FEN,
    ) -> dict:
        board = parse_board(root_fen,)
        opponent = OpponentSettings(**settings,)

        game = {
            "game_id": str(uuid4(),),
            "revision": 0,
            "event_id": str(uuid4(),),
            "event_sequence": 0,
            "root_fen": board.fen(),
            "history": [],
            "settings": asdict(opponent,),
            "annotations": [],
            "teaching": None,
        }

        self.store.put(
            "live_game",
            "active",
            game,
        )

        self.notify()

        return self.render(game,)

    def build_board(
        self,
        game: dict,
    ) -> chess.Board:
        return build_position(
            game["root_fen"],
            tuple(game["history"],),
        ).copy(stack=True,)

    def update(
        self,
        game_id: str,
        revision: int,
        operation,
    ) -> dict:
        with self.store.acquire_write():
            game = self.read(game_id,)

            if type(revision,) is not int or game["revision"] != revision:
                raise LiveConflict("The position changed. Read the current game before retrying.",)

            operation(game,)
            game["event_id"] = str(uuid4(),)

            game["event_sequence"] = game.get(
                "event_sequence",
                0,
            ) + 1

            self.store.put(
                'live_game',
                'active',
                game,
            )

        self.notify()

        return self.render(game,)

    def move(
        self,
        game_id: str,
        revision: int,
        notation: str,
        is_opponent: bool = False,
    ) -> dict:
        def apply(game,):
            board = self.build_board(game,)

            if board.is_game_over() or game.get("draw_claim",):
                raise ValueError("The game has ended. Start a new game or take back a move.",)

            is_player_turn = board.turn == (game["settings"]["player_color"] == "white")

            if is_player_turn == is_opponent:
                raise LiveConflict("Wait for the correct side to move.",)

            if len(game["history"],) >= 1024:
                raise ValueError("The game has reached the supported move limit.",)

            move = parse_move(
                board,
                notation,
            )

            game["history"].append(move.uci(),)
            self.clear_teaching(game,)

        return self.update(
            game_id,
            revision,
            apply,
        )

    def claim_draw(
        self,
        game_id,
        revision,
        intended_move=None,
    ):
        def apply(game,):
            if game.get("draw_claim",):
                raise ValueError("A draw has already been claimed.",)

            claim = validate_draw_claim(
                self.build_board(game,),
                intended_move,
            )

            self.clear_teaching(game,)
            game["draw_claim"] = claim

        return self.update(
            game_id,
            revision,
            apply,
        )

    def undo(
        self,
        game_id: str,
        revision: int,
    ) -> dict:
        def apply(game,):
            if game.get("draw_claim",):
                self.clear_teaching(game,)

                return

            if not game["history"]:
                raise ValueError("There are no moves to take back.",)

            game["history"].pop()
            board = self.build_board(game,)
            player = game["settings"]["player_color"] == "white"

            if board.turn != player and game["history"]:
                game["history"].pop()

            self.clear_teaching(game,)

        return self.update(
            game_id,
            revision,
            apply,
        )

    def clear_teaching(
        self,
        game: dict,
    ) -> None:
        game.pop(
            "draw_claim",
            None,
        )

        game["revision"] += 1
        game["annotations"] = []
        game["teaching"] = None

    def annotate(
        self,
        game_id: str,
        revision: int,
        annotations: list[dict],
        teaching: dict | None = None,
    ) -> dict:
        if not isinstance(
            annotations,
            list,
        ) or len(annotations,) > 32:
            raise ValueError("Supply at most 32 board annotations.",)

        marks = []

        for mark in annotations:
            if not isinstance(
                mark,
                dict,
            ) or set(mark,) - {"from", "to", "color", "label",}:
                raise ValueError("Annotations accept from, to, color, and label only.",)

            if mark.get("from",) not in chess.SQUARE_NAMES or ("to" in mark and mark["to"] not in chess.SQUARE_NAMES):
                raise ValueError("Annotations must refer to valid board squares.",)

            if mark.get(
                "color",
                "blue",
            ) not in ("blue", "green", "amber", "red"):
                raise ValueError("Annotation color must be blue, green, amber, or red.",)

            if not isinstance(
                mark.get(
                    "label",
                    "",
                ),
                str,
            ) or len(mark.get(
                "label",
                "",
            ),) > 100:
                raise ValueError("Annotation labels must contain at most 100 characters.",)

            marks.append({
                **mark,
                "color": mark.get(
                    "color",
                    "blue",
                ),
                "source": "engine",
            },)

        def apply(game,):
            game["annotations"] = marks

            if teaching is not None:
                game["teaching"] = teaching

        return self.update(
            game_id,
            revision,
            apply,
        )

    def render(
        self,
        game: dict,
        should_include_history: bool = True,
    ) -> dict:
        return render_position(
            game,
            should_include_history,
        )
