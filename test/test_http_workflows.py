import asyncio
import os
import socket
import subprocess
import sys

import chess
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

@pytest.mark.asyncio
async def test_http_reconnection_preserves_learning_and_schemas(tmp_path,):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0),)
        port = listener.getsockname()[1]

    environment = {**os.environ, "GAMBIT_DATABASE": str(tmp_path / "http.sqlite3",),}

    process = subprocess.Popen(
        [sys.executable, "-m", "gambit.main", "serve", "--transport", "streamable-http", "--port", str(port,),],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    address = f"http://127.0.0.1:{port}/mcp"

    try:
        async with asyncio.timeout(15,):
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
                        raise RuntimeError("The HTTP test server exited before startup.",)

                    await asyncio.sleep(0.05,)

            async with streamable_http_client(address,) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                ) as session:
                    initialization = await session.initialize()
                    assert "profile instant" in initialization.instructions
                    catalog = await session.list_tools()
                    tools_by_name = {tool.name: tool for tool in catalog.tools}
                    assert tools_by_name["assess_candidate_move"].output_schema
                    assert tools_by_name["get_analysis_metrics"].output_schema

                    for name in ("evaluate_position", "evaluate_move", "compare_candidate_moves", "assess_candidate_move", "submit_teaching_move", "submit_tactic_move", "create_tutor_turn"):
                        assert tools_by_name[name].input_schema["properties"]["profile"]["default"] == "instant"

                    for name in ("analyze_position", "analyze_chessboard", "tutor_move"):
                        assert tools_by_name[name].input_schema["properties"]["nodes"]["default"] == 12000
                        assert tools_by_name[name].input_schema["properties"]["multipv"]["default"] == 1

                    question = await session.call_tool(
                        "start_teaching_session",
                        {"fen": chess.STARTING_FEN, "learner_id": "http",},
                    )

                    assert not question.is_error
                    session_id = question.structured_content["session_id"]

            async with streamable_http_client(address,) as (read_stream, write_stream):
                async with ClientSession(
                    read_stream,
                    write_stream,
                ) as session:
                    await session.initialize()

                    hint = await session.call_tool(
                        "get_teaching_hint",
                        {"session_id": session_id, "level": 1,},
                    )

                    assert not hint.is_error
                    assert hint.structured_content["hint_level"] == 1
                    metrics = await session.call_tool("get_analysis_metrics",)
                    assert not metrics.is_error
                    assert metrics.structured_content["schema_version"] == 1

                    evaluation = await session.call_tool(
                        "evaluate_position",
                        {"fen": chess.STARTING_FEN, "profile": "instant",},
                    )

                    assert not evaluation.is_error
                    assert evaluation.structured_content["schema_version"] == 1

                    turn = await session.call_tool(
                        "create_tutor_turn",
                        {"fen": chess.STARTING_FEN, "move": "e4",},
                    )

                    assert not turn.is_error
                    assert turn.structured_content["is_compact"]
                    assert turn.structured_content["engine_evidence"]["profile"] == "instant"
                    assert turn.structured_content["move_assessment"]["move"]["uci"] == "e2e4"
                    assert turn.structured_content["engine_evidence"]["fen"] == turn.structured_content["speech_plan"]["position_fen"]
    finally:
        process.terminate()

        try:
            process.wait(timeout=10,)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5,)
