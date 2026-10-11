"""Isolated Python worker entry. Ops alone invokes reconciliation; no timer."""
from contextlib import asynccontextmanager
import os

from .core_activity import get_core_activity
from .database import Database
from .environment import load_environment
from .protocol_metrics import ProtocolMetrics
from .retained_reads import dashboard_snapshot, disabled_dashboard
from .telemetry import configure_logging
from .serve import run
from .worker_engine import WorkerEngine
from .worker_http import create_worker_app


def create_configured_worker(settings=None, database=None):
    settings = settings or load_environment()
    database = database or Database(settings.DATABASE_URL)
    engine = WorkerEngine(database, settings)
    app = create_worker_app(engine, settings.ONCHAIN_INDEXER_WORKER_TOKEN,
        os.environ.get('CYBERGOLD_BACKEND_COMMIT') or os.environ.get('CYBERGOLD_APP_COMMIT'))
    async def snapshot():
        if engine.config is None:
            return disabled_dashboard()
        return await dashboard_snapshot(database, engine.config['chainId'], engine.config['coreAddress'])
    async def activity():
        return await get_core_activity(database if settings.DATABASE_URL else None, int(settings.NEXT_PUBLIC_CHAIN_ID), settings.NEXT_PUBLIC_CORE_DIAMOND_ADDRESS)
    engine.product_metrics = ProtocolMetrics(app.state.metrics.registry, snapshot, activity)
    app.state.engine = engine
    @asynccontextmanager
    async def lifespan(_app):
        try:
            engine.refresh_product_metrics()
            yield
        finally:
            await engine.close()
    app.router.lifespan_context = lifespan
    return app


if __name__ == '__main__':
    configure_logging()
    run(create_configured_worker(), host=os.environ.get('HOST', '127.0.0.1'),
        port=int(os.environ.get('PORT', '3001')))
