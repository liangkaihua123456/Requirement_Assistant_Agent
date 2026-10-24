"""FastAPI application entrypoint."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_settings import router as settings_router
from app.api.routes_stats import router as stats_router
from app.api.routes_task import router as task_router
from app.api.routes_template import router as template_router
from app.api.routes_stream import router as stream_router
from app.api.routes_extract import router as extract_router
from app.core import pricing_sync
from app.core.logger import logger
from app.core.model_router import routing_summary
from app.core.task_queue import start_worker, stop_worker
from app.storage.db import init_db

PRICE_SYNC_INTERVAL_SECONDS = 3600


async def _price_sync_loop() -> None:
    """Refresh official prices when the cached snapshot is older than a day."""
    while True:
        try:
            if pricing_sync.needs_sync():
                await asyncio.to_thread(pricing_sync.sync_all)
        except Exception as exc:
            logger.warning(f"Price sync failed: {str(exc)[:200]}")
        await asyncio.sleep(PRICE_SYNC_INTERVAL_SECONDS)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # 早期价格同步把 DeepSeek 的人民币数值标成了 USD，启动时清掉，回落到内置价
    try:
        from app.core.pricing_store import migrate_deepseek_currency

        removed = migrate_deepseek_currency()
        if removed:
            logger.info(f"Removed {removed} legacy DeepSeek price entries")
    except Exception as exc:
        logger.warning(f"Price migration skipped: {str(exc)[:160]}")
    logger.info(f"Model routing resolved: {routing_summary()}")
    # 历史任务只有任务级快照，启动时补一次调用级记录（幂等）。
    try:
        from app.storage import repo_usage

        await asyncio.to_thread(repo_usage.backfill_from_tasks)
    except Exception as exc:
        logger.warning(f"Usage backfill skipped: {str(exc)[:200]}")
    await start_worker()
    sync_task = asyncio.create_task(_price_sync_loop())
    try:
        yield
    finally:
        sync_task.cancel()
        await stop_worker()


app = FastAPI(
    title="Multi-Agent Requirement Delivery System",
    description="LangChain + LangGraph multi-agent delivery workflow.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(task_router)
app.include_router(stream_router)
app.include_router(stats_router)
app.include_router(settings_router)
app.include_router(template_router)
app.include_router(extract_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
