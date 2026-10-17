import asyncio
import io
import os
import socket
import subprocess
import sys

import chess
import chess.pgn
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

@pytest.mark.asyncio
async def test_http_sessions_practice_and_local_data_survive_reconnection(tmp_path,) -> None:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0),)
        port = listener.getsockname()[1]

    configuration = tmp_path / "gambit.toml"
    configuration.write_text('should_refine_automatically = false\nprefetch_branches = 0\n',)

    environment = {
        **os.environ,
        "GAMBIT_RUNTIME_DIRECTORY": str(tmp_path / "runtime",),
        "GAMBIT_DATABASE": str(tmp_path / "runtime" / "gambit.sqlite3",),
        "GAMBIT_CONFIG": str(configuration,),
    }

    process = subprocess.Popen(
        [sys.executable, "-m", "gambit.main", "serve", "--transport", "streamable-http", "--port", str(port,),],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )

    address = f"http://127.0.0.1:{port}/mcp"

    try:
        async with asyncio.timeout(30,):
            while True:
                try:
                    _, writer = await asyncio.open_connection(
                        "127.0.0.1",
                        port,
                    )

                    writer.close()
                    await writer.wait_closed()

                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError(process.stderr.read().decode(),)

                    await asyncio.sleep(0.05,)

            async with streamable_http_client(address,) as streams:
                async with ClientSession(
                    streams[0],
                    streams[1],
                ) as client:
                    await client.initialize()
                    tools = {tool.name: tool for tool in (await client.list_tools()).tools}
                    assert "delta" in str(tools["create_tutor_turn"].input_schema,) or "response_mode" in tools["create_tutor_turn"].input_schema["properties"]

                    started = await client.call_tool(
                        "start_tutor_session",
                        {"fen": chess.STARTING_FEN, "learner_id": "http-tutoring",},
                    )

                    assert not started.is_error
                    session_id = started.structured_content["session_id"]

                    moved = await client.call_tool(
                        "navigate_tutor_session",
                        {"session_id": session_id, "expected_revision": 0, "operation_id": "first-move", "action": "advance", "move": "e4",},
                    )

                    assert not moved.is_error
                    assert moved.structured_content["revision"] == 1

                    stale = await client.call_tool(
                        "navigate_tutor_session",
                        {"session_id": session_id, "expected_revision": 0, "operation_id": "stale-move", "action": "advance", "move": "e5",},
                    )

                    assert stale.is_error

            async with streamable_http_client(address,) as streams:
                async with ClientSession(
                    streams[0],
                    streams[1],
                ) as client:
                    await client.initialize()

                    resumed = await client.call_tool(
                        "get_tutor_session",
                        {"session_id": session_id,},
                    )

                    assert resumed.structured_content["revision"] == 1

                    turn = await client.call_tool(
                        "create_tutor_turn",
                        {"fen": chess.STARTING_FEN, "session_id": session_id, "expected_revision": 1, "response_mode": "delta",},
                    )

                    assert not turn.is_error
                    assert turn.structured_content["session"]["revision"] == 1

                    exported = await client.call_tool(
                        "export_tutor_study",
                        {"session_id": session_id,},
                    )

                    assert not exported.is_error
                    game = chess.pgn.read_game(io.StringIO(exported.structured_content["content"],),)
                    assert game is not None and not game.errors
                    assert list(game.mainline_moves(),) == [chess.Move.from_uci("e2e4",),]

                    practice = await client.call_tool(
                        "start_practice",
                        {"mode": "calculation", "learner_id": "http-tutoring", "fen": chess.STARTING_FEN,},
                    )

                    assert not practice.is_error
                    practice_id = practice.structured_content["practice_id"]
                    assert "solution" not in practice.structured_content

                    submission = await client.call_tool(
                        "act_practice",
                        {"practice_id": practice_id, "expected_revision": 0, "operation_id": "prediction", "action": "submit", "moves": ["e4",], "confidence": 0.7,},
                    )

                    assert not submission.is_error
                    assert not submission.structured_content["is_confirmed"]

                    dashboard = await client.call_tool(
                        "get_learning_dashboard",
                        {"learner_id": "http-tutoring",},
                    )

                    assert not dashboard.is_error
                    assert dashboard.structured_content["independent_attempts"] == 0

                    data = await client.call_tool(
                        "manage_chess_data",
                        {"action": "status",},
                    )

                    assert not data.is_error
    finally:
        process.terminate()

        try:
            process.wait(timeout=10,)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=10,)

        process.stderr.close()
