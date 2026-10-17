import asyncio
import ipaddress
import json
import os
from pathlib import Path
from time import monotonic
from urllib.parse import urlsplit

import chess.engine
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, StreamingResponse

from gambit.engine.client import execute_engine_request
from gambit.live.games import LiveConflict

ASSET_DIRECTORY = Path(__file__,).resolve().parents[1] / "web" / "assets"
MAX_BODY_BYTES = 16384

async def run_connected(
    request,
    operation,
    *arguments,
):
    task = asyncio.create_task(execute_engine_request(
        operation,
        *arguments,
    ),)

    try:
        while not task.done():
            done, _ = await asyncio.wait(
                {task,},
                timeout=0.03,
            )

            if done:
                break

            if await request.is_disconnected():
                task.cancel()
                raise InterruptedError("The browser cancelled this request.",)

        return await task
    finally:
        if not task.done():
            task.cancel()

        await asyncio.gather(
            task,
            return_exceptions=True,
        )

def is_local_request(request: Request,) -> bool:
    host = request.url.hostname
    origin = request.headers.get("origin",)
    client = request.client.host if request.client else ""

    configured_origin = os.environ.get(
        "GAMBIT_UI_ORIGIN",
        "",
    ).rstrip("/",)

    configured = urlsplit(configured_origin,)
    is_tailnet_host = configured.scheme == "https" and (configured.hostname or "").endswith(".ts.net",) and configured.netloc == request.headers.get("host",) and configured.path == "" and not configured.query and not configured.fragment and configured.username is None

    try:
        is_loopback = ipaddress.ip_address(client,).is_loopback
    except ValueError:
        is_loopback = client in ("localhost", "testclient")

    is_allowed_host = host in ("localhost", "127.0.0.1", "::1", "testserver") or is_tailnet_host
    is_allowed_origin = origin is None or (origin == configured_origin if is_tailnet_host else urlsplit(origin,).netloc == request.headers.get("host",))
    is_cross_site_api = request.url.path.startswith("/api/",) and request.headers.get("sec-fetch-site",) == "cross-site"

    return is_loopback and is_allowed_host and is_allowed_origin and not is_cross_site_api

def register_live_http(
    server,
    owner,
):
    async def api(request: Request,):
        if not is_local_request(request,):
            return JSONResponse(
                {"error": "The playing interface accepts its configured origins through loopback only.",},
                status_code=403,
            )

        try:
            live = owner.get_runtime().live
            action = request.path_params["action"]

            if request.method == "GET":
                if action == "game":
                    try:
                        game = await asyncio.to_thread(live.games.read,)

                        return JSONResponse({"game": live.games.render(game,),},)
                    except LiveConflict:
                        return JSONResponse({"game": None,},)

                if action == "capabilities":
                    return JSONResponse(await execute_engine_request(live.get_capabilities,),)

                return JSONResponse(
                    {"error": "Unknown endpoint.",},
                    status_code=404,
                )

            if request.headers.get(
                "content-type",
                "",
            ).split(";",)[0] != "application/json":
                return JSONResponse(
                    {"error": "Send application/json.",},
                    status_code=415,
                )

            body = bytearray()

            async for chunk in request.stream():
                body.extend(chunk,)

                if len(body,) > MAX_BODY_BYTES:
                    return JSONResponse(
                        {"error": "The request body is too large.",},
                        status_code=413,
                    )

            data = json.loads(body,)

            if not isinstance(
                data,
                dict,
            ):
                raise ValueError("The request must contain a JSON object.",)

            if action == "new":
                game = await execute_engine_request(
                    live.create_game,
                    data["settings"],
                    data["root_fen"],
                )

                return JSONResponse({"game": game,},)

            game_id = data["game_id"]
            revision = data["expected_revision"]

            if action == "move":
                game = await asyncio.to_thread(
                    live.games.move,
                    game_id,
                    revision,
                    data["move"],
                )
            elif action == "opponent":
                game = await run_connected(
                    request,
                    live.play_opponent,
                    game_id,
                    revision,
                )
            elif action == "claim_draw":
                game = await asyncio.to_thread(
                    live.games.claim_draw,
                    game_id,
                    revision,
                    data.get("intended_move",),
                )
            elif action == "undo":
                game = await asyncio.to_thread(
                    live.games.undo,
                    game_id,
                    revision,
                )
            elif action == "clear":
                game = await asyncio.to_thread(
                    live.games.annotate,
                    game_id,
                    revision,
                    [],
                )
            elif action == "teach":
                report = await run_connected(
                    request,
                    live.teach,
                    revision,
                    game_id,
                    data["intent"],
                    data["profile"],
                )

                return JSONResponse({"game": live.games.render(live.games.read(game_id,),), "analysis_id": report["engine_evidence"].get("id",),},)
            else:
                return JSONResponse(
                    {"error": "Unknown endpoint.",},
                    status_code=404,
                )

            return JSONResponse({"game": game,},)
        except LiveConflict as exception:
            return JSONResponse(
                {"error": str(exception,),},
                status_code=409,
            )
        except (ValueError, TypeError, KeyError) as exception:
            return JSONResponse(
                {"error": str(exception,),},
                status_code=400,
            )
        except (RuntimeError, OSError, TimeoutError, chess.engine.EngineError) as exception:
            return JSONResponse(
                {"error": str(exception,),},
                status_code=503,
            )

    async def events(request: Request,):
        if not is_local_request(request,):
            return JSONResponse(
                {"error": "Local access is required.",},
                status_code=403,
            )

        async def stream():
            previous = None
            heartbeat_at = monotonic()
            live = owner.get_runtime().live
            loop = asyncio.get_running_loop()
            changed = asyncio.Event()

            live.games.subscribe(
                loop,
                changed,
            )

            try:
                while not await request.is_disconnected():
                    changed.clear()

                    try:
                        game = await asyncio.to_thread(live.games.read,)

                        if game["event_id"] != previous:
                            previous = game["event_id"]

                            yield "data: " + json.dumps(
                                live.games.render(game,),
                                separators=(",", ":"),
                            ) + "\n\n"
                    except LiveConflict:
                        pass

                    if monotonic() - heartbeat_at >= 15:
                        heartbeat_at = monotonic()
                        yield ": heartbeat\n\n"

                    try:
                        await asyncio.wait_for(
                            changed.wait(),
                            timeout=15,
                        )
                    except TimeoutError:
                        pass
            finally:
                live.games.unsubscribe(
                    loop,
                    changed,
                )

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",},
        )

    async def asset(request: Request,):
        if not is_local_request(request,):
            return JSONResponse(
                {"error": "Local access is required.",},
                status_code=403,
            )

        relative = request.url.path.lstrip("/",) or "index.html"
        path = (ASSET_DIRECTORY / relative).resolve()

        if not path.is_relative_to(ASSET_DIRECTORY,) or not path.is_file():
            return JSONResponse(
                {"error": "Build the playing interface with npm ci and npm run build in ui/.",},
                status_code=404,
            )

        return FileResponse(
            path,
            headers={"Cache-Control": "no-cache" if path.name == "index.html" else "public, max-age=3600",},
        )

    server.custom_route(
        "/api/live/{action}",
        methods=["GET", "POST",],
    )(api,)

    server.custom_route(
        "/api/events",
        methods=["GET",],
    )(events,)

    server.custom_route(
        "/",
        methods=["GET",],
    )(asset,)

    server.custom_route(
        "/assets/{path:path}",
        methods=["GET",],
    )(asset,)
