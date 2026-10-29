"""数据库连接与会话管理。

使用 SQLAlchemy 2.0 异步引擎 + aiosqlite。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
import sqlite3
from typing import AsyncGenerator

from sqlalchemy import Boolean, Column, DateTime, Float, Integer, String, Text, func
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings


class Base(DeclarativeBase):
    """SQLAlchemy 声明基类。"""
    pass


class TaskRecord(Base):
    """任务记录表。"""

    __tablename__ = "tasks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), unique=True, nullable=False, index=True)
    user_input = Column(Text, nullable=False)
    status = Column(String(32), nullable=False, default="created")
    current_node = Column(String(64), default="")
    state_snapshot = Column(Text, default="{}")
    result = Column(Text, default="{}")
    reflow_count = Column(Integer, default=0)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class FeedbackRecord(Base):
    """人工反馈记录表。"""

    __tablename__ = "feedbacks"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, index=True)
    node = Column(String(64), default="")
    feedback_type = Column(String(32), default="general")
    content = Column(Text, default="")
    created_at = Column(DateTime, server_default=func.now())


class TemplateRecord(Base):
    """需求模板，创建任务时可复用。"""

    __tablename__ = "requirement_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, server_default=func.now())


class LlmUsageRecord(Base):
    """一次模型调用一行。

    存成独立表而不是只写在任务快照里：快照依赖图运行成功落库，节点抛异常时
    已消耗的 token 会整段丢失，统计也就永远对不上账单。
    """

    __tablename__ = "llm_usage"

    id = Column(Integer, primary_key=True, autoincrement=True)
    task_id = Column(String(64), nullable=False, default="", index=True)
    node = Column(String(64), default="")
    role = Column(String(32), default="")
    model = Column(String(80), default="", index=True)
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    total_tokens = Column(Integer, default=0)
    cached_tokens = Column(Integer, default=0)
    cost_cny = Column(Float, default=0.0)
    priced = Column(Boolean, default=False)
    # 计价时段：1 = 高峰价，0 = 空闲价（DeepSeek 分时计价）
    peak = Column(Boolean, default=True)
    # agent = 智能体调用，vision = 图片识别，backfill = 历史快照回填
    source = Column(String(16), default="agent", index=True)
    created_at = Column(DateTime, server_default=func.now(), index=True)


_engine = None
_session_factory = None


async def get_engine():
    """获取异步数据库引擎（单例）。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        # 确保 data 目录存在
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        connect_args = {}
        if settings.database_url.startswith("sqlite"):
            # Concurrent workers write to the same SQLite file; without a busy
            # timeout the second writer fails immediately with "database is locked".
            connect_args["timeout"] = 30
        _engine = create_async_engine(settings.database_url, echo=False, connect_args=connect_args)
    return _engine


async def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取异步 Session 工厂。"""
    global _session_factory
    if _session_factory is None:
        engine = await get_engine()
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


async def init_db():
    """初始化数据库（创建表），并为已存在的表补齐新增列。"""
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    await run_column_migrations()


async def run_column_migrations() -> None:
    """create_all 不会给旧表加列，增量列在这里补。"""
    settings = get_settings()
    if not settings.database_url.startswith("sqlite"):
        return
    path = settings.database_url.split("///", 1)[-1]
    try:
        with sqlite3.connect(path, timeout=15) as conn:
            existing = {row[1] for row in conn.execute("PRAGMA table_info(llm_usage)")}
            if not existing:
                return
            if "peak" not in existing:
                conn.execute("ALTER TABLE llm_usage ADD COLUMN peak BOOLEAN DEFAULT 1")
                conn.execute("UPDATE llm_usage SET peak = 1 WHERE peak IS NULL")
    except Exception:
        # 迁移失败不应阻止启动，页面会显示 0 而不是崩掉
        pass


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取一个数据库会话（异步上下文管理器，自动 close）。"""
    factory = await get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        await session.close()
