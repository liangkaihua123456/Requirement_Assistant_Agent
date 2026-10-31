"""数据库连接与会话管理。

使用 SQLAlchemy 2.0 异步引擎 + aiosqlite。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import Column, DateTime, Integer, String, Text, func
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
    user_id = Column(Integer, index=True, nullable=True)
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


class UserRecord(Base):
    """用户表（登录 / 注册 / 鉴权）。"""

    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    email = Column(String(255), unique=True, nullable=True, index=True)
    password_hash = Column(String(255), nullable=False)
    is_active = Column(Integer, nullable=False, default=1)
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())


class PasswordResetTokenRecord(Base):
    """忘记密码的一次性重置 token（仅存哈希）。"""

    __tablename__ = "password_reset_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    token_hash = Column(String(64), unique=True, nullable=False, index=True)
    expires_at = Column(DateTime, nullable=False)
    used = Column(Integer, nullable=False, default=0)
    created_at = Column(DateTime, server_default=func.now())


_engine = None
_session_factory = None


async def get_engine():
    """获取异步数据库引擎（单例）。"""
    global _engine
    if _engine is None:
        settings = get_settings()
        # 确保 data 目录存在
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(settings.database_url, echo=False)
    return _engine


async def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """获取异步 Session 工厂。"""
    global _session_factory
    if _session_factory is None:
        engine = await get_engine()
        _session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return _session_factory


def _ensure_columns(sync_conn) -> None:
    """幂等补列迁移：create_all 不会给已存在的表加列，这里手动补齐。

    主要用于给历史 tasks 表补上 user_id（鉴权改造后任务归属用户）。
    """
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    table_names = set(insp.get_table_names())
    if "tasks" in table_names:
        cols = {c["name"] for c in insp.get_columns("tasks")}
        if "user_id" not in cols:
            sync_conn.execute(text("ALTER TABLE tasks ADD COLUMN user_id INTEGER"))
            sync_conn.execute(text("CREATE INDEX IF NOT EXISTS ix_tasks_user_id ON tasks (user_id)"))


async def init_db():
    """初始化数据库（创建新表 + 补齐已存在表缺失的列）。"""
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_ensure_columns)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取一个数据库会话（异步上下文管理器，自动 close）。"""
    factory = await get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        await session.close()
