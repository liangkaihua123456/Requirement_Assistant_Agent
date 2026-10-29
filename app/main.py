"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes_task import router as task_router
from app.api.routes_stream import router as stream_router
from app.core.config import get_settings
from app.core.task_queue import start_worker, stop_worker
from app.integrations.dingtalk.bot import DingTalkService
from app.storage.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await init_db()
    await start_worker()

    dingtalk: DingTalkService | None = None
    if settings.dingtalk_enabled:
        dingtalk = DingTalkService(settings)
        await dingtalk.start()

    try:
        yield
    finally:
        # 先停止接收钉钉消息，再停 worker
        if dingtalk is not None:
            await dingtalk.stop()
        await stop_worker()


app = FastAPI(
    title="Multi-Agent Requirement Delivery System",
    description="LangChain + LangGraph multi-agent delivery workflow.",
    version="1.0.0",
    lifespan=lifespan,
)

app.include_router(task_router)
app.include_router(stream_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
