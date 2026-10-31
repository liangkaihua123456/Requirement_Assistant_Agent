"""FastAPI application entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes_task import router as task_router
from app.api.routes_user import router as user_router
from app.api.routes_stream import router as stream_router
from app.core.task_queue import start_worker, stop_worker
from app.storage.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await start_worker()
    try:
        yield
    finally:
        await stop_worker()


app = FastAPI(
    title="Multi-Agent Requirement Delivery System",
    description="LangChain + LangGraph multi-agent delivery workflow.",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(user_router)
app.include_router(task_router)
app.include_router(stream_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
