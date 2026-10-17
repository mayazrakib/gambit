import asyncio
import os
import socket
import subprocess
import sys
from dataclasses import asdict

import chess
import httpx2
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from gambit.live.opponent import OpponentSettings

@pytest.mark.asyncio
async def test_live_mcp_teaching_annotations_deltas_and_stale_rejection(tmp_path,):
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0),)
        port = listener.getsockname()[1]

    environment = {**os.environ, 'GAMBIT_DATABASE': str(tmp_path / 'mcp.sqlite3',), 'GAMBIT_RUNTIME_DIRECTORY': str(tmp_path,),}

    process = subprocess.Popen(
        [sys.executable, '-m', 'gambit.main', 'play', '--port', str(port,),],
        env=environment,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    base = f'http://127.0.0.1:{port}'

    try:
        async with asyncio.timeout(15,):
            while True:
                try:
                    _, writer = await asyncio.open_connection(
                        '127.0.0.1',
                        port,
                    )

                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    if process.poll() is not None:
                        raise RuntimeError('The live test server exited during startup.',)

                    await asyncio.sleep(0.05,)

        async with httpx2.AsyncClient(base_url=base,) as client:
            created = await client.post(
                '/api/live/new',
                json={'settings': asdict(OpponentSettings(),), 'root_fen': chess.STARTING_FEN,},
            )

            assert created.status_code == 200
            game = created.json()['game']

            async with streamable_http_client(base + '/mcp',) as (read, write):
                async with ClientSession(
                    read,
                    write,
                ) as session:
                    await session.initialize()
                    catalog = await session.list_tools()
                    assert {'get_live_game', 'analyze_live_game', 'annotate_live_game',} <= {tool.name for tool in catalog.tools}
                    current = await session.call_tool('get_live_game',)
                    assert not current.is_error
                    assert 'history' not in current.structured_content
                    taught = await session.call_tool('analyze_live_game',)
                    assert not taught.is_error
                    report = taught.structured_content
                    assert report['annotations_applied'] == 1
                    assert report['live_game']['fen'] == chess.STARTING_FEN
                    assert report['position_context']['side_to_move'] == 'white'
                    assert 'model_instructions' not in report

                    delta = await session.call_tool(
                        'analyze_live_game',
                        {'known_analysis_id': report['engine_evidence']['id'],},
                    )

                    assert not delta.is_error
                    assert delta.structured_content['is_unchanged']
                    assert 'speech_plan' not in delta.structured_content

                    marked = await session.call_tool(
                        'annotate_live_game',
                        {'game_id': game['game_id'], 'expected_revision': 0, 'marks': [{'from': 'e4', 'color': 'green',}, {'from': 'g1', 'to': 'f3',},],},
                    )

                    assert not marked.is_error
                    state = (await client.get('/api/live/game',)).json()['game']
                    assert len(state['annotations'],) == 2
                    assert state['annotations'][0]['color'] == 'green'

                    hint = await session.call_tool(
                        'analyze_live_game',
                        {'intent': 'hint',},
                    )

                    assert not hint.is_error
                    assert hint.structured_content['annotations_applied'] == 0
                    assert 'move_facts' not in hint.structured_content

                    moved = await client.post(
                        '/api/live/move',
                        json={'game_id': game['game_id'], 'expected_revision': 0, 'move': 'e4',},
                    )

                    assert moved.status_code == 200

                    stale = await session.call_tool(
                        'annotate_live_game',
                        {'game_id': game['game_id'], 'expected_revision': 0, 'marks': [{'from': 'e4',},],},
                    )

                    assert stale.is_error
                    state = (await client.get('/api/live/game',)).json()['game']
                    assert state['annotations'] == [] and state['revision'] == 1

            async with client.stream(
                'GET',
                '/api/events',
            ) as response:
                assert response.status_code == 200
                lines = response.aiter_lines()
                assert (await anext(lines,)).startswith('data: ',)
                process.terminate()

                await asyncio.to_thread(
                    process.wait,
                    timeout=6,
                )
    finally:
        process.terminate()

        try:
            process.wait(timeout=10,)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5,)
