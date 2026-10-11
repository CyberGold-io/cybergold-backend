import os

from .runtime import create_configured_app
from .serve import run
from .telemetry import configure_logging


if __name__ == '__main__':
    configure_logging()
    # Loopback by default like the retained runtime. Container fixtures may
    # override HOST; this entry point is not installed by Ops.
    run(create_configured_app(), host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '3000')))
