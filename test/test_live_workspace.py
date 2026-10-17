import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from threading import Event
from types import SimpleNamespace

import chess
import pytest
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.routing import Route
from starlette.testclient import TestClient

from gambit.infrastructure.storage import Store
from gambit.live.games import LiveConflict, LiveGames
from gambit.live.opponent import Opponent, OpponentSettings
from gambit.live.service import LiveWorkspace
from gambit.server.live_http import is_local_request, register_live_http

def test_tailnet_ui_requires_configured_host_origin_and_loopback(monkeypatch,):
    origin = "https://olympus.example.ts.net:8445"

    monkeypatch.setenv(
        "GAMBIT_UI_ORIGIN",
        origin,
    )

    def make_request(
        host,
        request_origin=None,
        client="127.0.0.1",
        path="/api/live/game",
        site="same-origin",
    ):
        headers = [(b"host", host.encode()), (b"sec-fetch-site", site.encode()),]

        if request_origin is not None:
            headers.append((b"origin", request_origin.encode()),)

        return Request({"type": "http", "method": "GET", "scheme": "http", "path": path, "query_string": b"", "headers": headers, "client": (client, 1234), "server": ("127.0.0.1", 3025),},)

    host = "olympus.example.ts.net:8445"

    assert is_local_request(make_request(
        host,
        origin,
    ),)

    assert is_local_request(make_request(
        host,
        path="/",
        site="cross-site",
    ),)

    assert not is_local_request(make_request(
        host,
        "https://evil.example",
    ),)

    assert not is_local_request(make_request(
        host,
        "http://" + host,
    ),)

    assert not is_local_request(make_request(
        host,
        origin,
        client="100.64.0.2",
    ),)

    assert not is_local_request(make_request(
        host,
        origin,
        site="cross-site",
    ),)

    assert not is_local_request(make_request(
        "olympus.example.ts.net:8446",
        origin,
    ),)

    monkeypatch.delenv("GAMBIT_UI_ORIGIN",)

    assert not is_local_request(make_request(
        host,
        origin,
    ),)

@pytest.fixture
def games(tmp_path,):
    store = Store()

    try:
        yield LiveGames(store,)
    finally:
        store.close()

def start_game(
    games,
    **settings,
):
    return games.create(asdict(OpponentSettings(**settings,),),)

def test_turn_ownership_history_takeback_and_stale_mutations(games,):
    game = start_game(games,)

    with pytest.raises(LiveConflict,):
        games.move(
            game["game_id"],
            0,
            "e4",
            is_opponent=True,
        )

    moved = games.move(
        game["game_id"],
        0,
        "e4",
    )

    assert moved["history"] == ["e2e4",]
    assert moved["moves"][0]["san"] == "e4"

    with pytest.raises(LiveConflict,):
        games.move(
            game["game_id"],
            0,
            "d4",
        )

    with pytest.raises(LiveConflict,):
        games.move(
            game["game_id"],
            1,
            "e5",
        )

    replied = games.move(
        game["game_id"],
        1,
        "e5",
        is_opponent=True,
    )

    games.annotate(
        game["game_id"],
        2,
        [{"from": "g1", "to": "f3",},],
    )

    undone = games.undo(
        game["game_id"],
        replied["revision"],
    )

    assert undone["history"] == []
    assert undone["annotations"] == []
    assert undone["revision"] == 3
    assert "1. e4 e5" in replied["pgn"]

def test_annotations_are_atomic_bounded_and_separate_from_moves(games,):
    game = start_game(games,)

    annotated = games.annotate(
        game["game_id"],
        0,
        [{"from": "e4", "color": "green",}, {"from": "g1", "to": "f3", "label": "Develop",},],
    )

    assert annotated["revision"] == 0
    assert annotated["event_sequence"] == 1
    assert annotated["fen"] == chess.STARTING_FEN

    for marks in ([{"from": "z9",},], [{"from": "e4", "to": "x1",},], [{"from": "e4", "color": "purple",},], [{"from": "e4", "unknown": "bad",},], [{"from": "e4",},] * 33):
        with pytest.raises(ValueError,):
            games.annotate(
                game["game_id"],
                0,
                marks,
            )

    assert len(games.read()["annotations"],) == 2
    replacement = start_game(games,)

    with pytest.raises(LiveConflict,):
        games.annotate(
            game["game_id"],
            0,
            [],
        )

    assert replacement["game_id"] != game["game_id"]

def test_promotions_terminal_positions_and_black_start(games,):
    game = games.create(
        asdict(OpponentSettings(),),
        "7k/P7/8/8/8/8/8/7K w - - 0 1",
    )

    promoted = games.move(
        game["game_id"],
        0,
        "a7a8q",
    )

    assert promoted["moves"][0]["san"] == "a8=Q+"

    game = games.create(
        asdict(OpponentSettings(),),
        "7k/6Q1/6K1/8/8/8/8/8 b - - 0 1",
    )

    assert game["is_game_over"]

    with pytest.raises(ValueError,):
        games.move(
            game["game_id"],
            0,
            "h8h7",
            is_opponent=True,
        )

    game = start_game(
        games,
        player_color="black",
    )

    assert games.move(
        game["game_id"],
        0,
        "e4",
        is_opponent=True,
    )["side_to_move"] == "black"

def test_separate_stores_do_not_share_games(tmp_path,):
    first = Store()
    second = Store()

    try:
        left = LiveGames(first,)
        right = LiveGames(second,)
        game = start_game(left,)

        left.move(
            game["game_id"],
            0,
            "e4",
        )

        with pytest.raises(LiveConflict,):
            right.move(
                game["game_id"],
                0,
                "d4",
            )

        with pytest.raises(LiveConflict,):
            right.read()
    finally:
        first.close()
        second.close()

def create_workspace(
    games,
    tutor,
):
    runtime = SimpleNamespace(
        store=games.store,
        configuration=SimpleNamespace(engine_path="stockfish",),
        evidence=tutor,
    )

    return LiveWorkspace(runtime,)

def test_compact_reads_cached_turns_and_hidden_hints(games,):
    calls = []

    def create_turn(
        fen,
        **options,
    ):
        calls.append(options,)

        return {"engine_evidence": {"id": "analysis-1",}, "position_reference": {"fen": fen,}, "position_context": {"fen": fen,}, "move_facts": {"variation": [],}, "elapsed_ms": 10, "board_directives": [] if options["intent"] == "hint" else [{"action": "add arrow", "from": "g1", "to": "f3", "fen": fen,},],}

    live = create_workspace(
        games,
        SimpleNamespace(create_turn=create_turn,),
    )

    game = start_game(games,)
    compact = live.get_game()
    assert "history" not in compact and "pgn" not in compact
    assert live.get_game(known_revision=0,)["is_unchanged"]
    first = live.teach()
    event_sequence = games.read()["event_sequence"]
    second = live.teach()
    assert first["engine_evidence"] == second["engine_evidence"]
    assert len(calls,) == 1
    assert games.read()["event_sequence"] == event_sequence
    delta = live.teach(known_analysis_id="analysis-1",)
    assert delta["is_unchanged"]
    assert "speech_plan" not in delta
    assert games.read()["annotations"][0]["from"] == "g1"
    live.teach(intent="hint",)
    assert games.read()["annotations"] == []
    assert calls[-1]["history"] == []
    assert first["live_game"]["revision"] == game["revision"]

def test_cached_turn_supersedes_an_inflight_hint(games,):
    started = Event()
    release = Event()

    def create_turn(
        fen,
        **options,
    ):
        if options["intent"] == "hint":
            started.set()
            assert release.wait(5,)

        return {"engine_evidence": {"id": "cached",}, "position_reference": {"fen": fen,}, "position_context": {"fen": fen,}, "move_facts": {"variation": [],}, "elapsed_ms": 1, "board_directives": [],}

    live = create_workspace(
        games,
        SimpleNamespace(create_turn=create_turn,),
    )

    start_game(games,)
    live.teach()

    with ThreadPoolExecutor(max_workers=1,) as executor:
        future = executor.submit(
            live.teach,
            intent="hint",
        )

        assert started.wait(5,)
        live.teach()
        release.set()

        with pytest.raises(LiveConflict,):
            future.result(timeout=5,)

    assert games.read()["teaching"]["intent"] == "explain"

def test_teaching_cannot_publish_after_position_changes(games,):
    started = Event()
    release = Event()

    def create_turn(
        fen,
        **options,
    ):
        started.set()
        assert release.wait(5,)

        return {"engine_evidence": {"id": "old",}, "position_reference": {"fen": fen,}, "position_context": {"fen": fen,}, "move_facts": {"variation": [],}, "elapsed_ms": 10, "board_directives": [],}

    live = create_workspace(
        games,
        SimpleNamespace(create_turn=create_turn,),
    )

    game = start_game(games,)

    with ThreadPoolExecutor(max_workers=1,) as executor:
        future = executor.submit(live.teach,)
        assert started.wait(5,)

        games.move(
            game["game_id"],
            0,
            "e4",
        )

        release.set()

        with pytest.raises(LiveConflict,):
            future.result(timeout=5,)

    assert games.read()["teaching"] is None

def test_real_stockfish_strength_modes_and_legal_replies():
    opponent = Opponent("stockfish",)

    try:
        capabilities = opponent.get_capabilities()
        minimum = capabilities["options"]["UCI_Elo"]["min"]

        for mode in ("skill", "elo", "full"):
            settings = asdict(OpponentSettings(
                strength_mode=mode,
                target_elo=minimum,
                think_time_ms=50,
            ),)

            move = opponent.play(
                chess.Board(),
                settings,
                "test-" + mode,
            )

            assert chess.Move.from_uci(move,) in chess.Board().legal_moves
    finally:
        opponent.close()

def test_http_local_boundary_body_validation_and_revision_conflict(
    games,
    request,
):
    live = create_workspace(
        games,
        None,
    )

    request.addfinalizer(live.close,)

    routes = []

    class TestServer:
        def custom_route(
            self,
            path,
            methods,
        ):
            def register(endpoint,):
                routes.append(Route(
                    path,
                    endpoint=endpoint,
                    methods=methods,
                ),)

            return register

    register_live_http(
        TestServer(),
        SimpleNamespace(get_runtime=lambda: SimpleNamespace(live=live,),),
    )

    with TestClient(Starlette(routes=routes,),) as client:
        assert client.get("/api/live/game",).json() == {"game": None,}

        assert client.post(
            "/api/live/new",
            json={},
            headers={"origin": "https://evil.example",},
        ).status_code == 403

        assert client.get(
            "/api/live/game",
            headers={"host": "evil.example",},
        ).status_code == 403

        assert client.post(
            "/api/live/new",
            content="{}",
        ).status_code == 415

        assert client.post(
            "/api/live/new",
            content="x" * 17000,
            headers={"content-type": "application/json",},
        ).status_code == 413

        assert client.post(
            "/api/live/new",
            content="{",
            headers={"content-type": "application/json",},
        ).status_code == 400

        game = client.post(
            "/api/live/new",
            json={"settings": asdict(OpponentSettings(),), "root_fen": chess.STARTING_FEN,},
        ).json()["game"]

        move = {"game_id": game["game_id"], "expected_revision": 0, "move": "e4",}

        assert client.post(
            "/api/live/move",
            json=move,
        ).status_code == 200

        assert client.post(
            "/api/live/move",
            content=json.dumps(move,),
            headers={"content-type": "application/json",},
        ).status_code == 409
