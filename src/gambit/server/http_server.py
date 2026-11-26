import atexit

import uvicorn

def serve_http(
    server,
    host: str,
    port: int,
    owner,
):
    application = server.streamable_http_app(host=host,)

    try:
        uvicorn.run(
            application,
            host=host,
            port=port,
            log_level=server.settings.log_level.lower(),
            timeout_graceful_shutdown=3,
            proxy_headers=False,
        )
    finally:
        if owner.runtime is not None:
            atexit.unregister(owner.runtime.close,)
            owner.runtime.close()
