"""数据库连接与会话管理。

使用 SQLAlchemy 2.0 异步引擎 + aiosqlite。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import Column, DateTime, Index, Integer, String, Text, func, text
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


class DingTalkBinding(Base):
    """钉钉会话与任务的绑定。

    active=1 表示该会话当前有进行中的任务；SQLite 部分唯一索引保证
    同一个会话最多只有一个 active 绑定。
    """

    __tablename__ = "dingtalk_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    conversation_id = Column(String(128), nullable=False, index=True)
    task_id = Column(String(64), nullable=False, index=True)
    requester_staff_id = Column(String(64), default="")
    active = Column(Integer, nullable=False, default=1)
    pending_kind = Column(String(32), default="")       # clarification / approval
    pending_payload = Column(Text, default="")          # JSON：问题列表或评审摘要
    session_webhook = Column(Text, default="")
    last_notified_status = Column(String(32), default="")
    created_at = Column(DateTime, server_default=func.now())
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index(
            "uq_dingtalk_active_binding",
            "conversation_id",
            unique=True,
            sqlite_where=text("active = 1"),
        ),
    )


class DingTalkMessage(Base):
    """钉钉消息去重表：msg_id 是钉钉侧的消息唯一 ID。"""

    __tablename__ = "dingtalk_messages"

    msg_id = Column(String(128), primary_key=True)
    conversation_id = Column(String(128), nullable=False, index=True)
    received_at = Column(DateTime, server_default=func.now())


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


async def init_db():
    """初始化数据库（创建表）。"""
    engine = await get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@asynccontextmanager
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """获取一个数据库会话（异步上下文管理器，自动 close）。"""
    factory = await get_session_factory()
    session = factory()
    try:
        yield session
    finally:
        await session.close()
