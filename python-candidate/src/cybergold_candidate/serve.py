"""Native Uvicorn draining with the retained Node graceful exit disposition."""
import signal

import uvicorn


def run(app, *, host, port):
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, access_log=False))
    # Uvicorn captures and later re-raises signals through the prior handler.
    # Retain its normal drain, while a completed SIGTERM/SIGINT shutdown exits
    # normally like Node. A signal before run also requests server shutdown.
    previous = {sig: signal.signal(sig, server.handle_exit) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        server.run()
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
