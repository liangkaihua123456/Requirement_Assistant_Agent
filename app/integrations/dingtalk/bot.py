"""钉钉 Stream 机器人的启动、Leader 锁和生命周期。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import dingtalk_stream
import httpx

from app.core.config import Settings
from app.core.logger import logger
from app.integrations.dingtalk.handler import DingTalkHandler
from app.integrations.dingtalk.notifier import notify_loop

try:
    import fcntl
except ImportError:  # Windows
    fcntl = None


class LeaderLock:
    """基于 flock 的单实例锁；多个 worker 中只有 leader 连钉钉。"""

    def __init__(self, path: Path):
        self.path = path
        self.fd: int | None = None

    def try_acquire(self) -> bool:
        if fcntl is None:
            raise RuntimeError("当前平台不支持 fcntl，无法使用钉钉 Leader 锁")

        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(fd)
            return False
        except Exception:
            os.close(fd)
            raise

        self.fd = fd
        os.ftruncate(fd, 0)
        os.write(fd, f"{os.getpid()}\n".encode())
        return True

    def release(self) -> None:
        if self.fd is None or fcntl is None:
            return
        try:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
        finally:
            os.close(self.fd)
            self.fd = None


class DingTalkService:
    """在 FastAPI 进程内后台运行；不阻塞非 leader 的 API worker。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._lock = LeaderLock(settings.dingtalk_lock_path)

    async def start(self) -> bool:
        if not self.settings.dingtalk_app_key or not self.settings.dingtalk_app_secret:
            logger.error(
                "DingTalk enabled but DINGTALK_APP_KEY/SECRET is missing",
                extra={"node": "dingtalk"},
            )
            return False
        if fcntl is None:
            logger.error(
                "DingTalk leader lock needs fcntl; disabled on this platform",
                extra={"node": "dingtalk"},
            )
            return False

        self._stopping = False
        self._task = asyncio.create_task(
            self._supervise(), name="dingtalk-supervisor"
        )
        logger.info("DingTalk supervisor started", extra={"node": "dingtalk"})
        return True

    async def stop(self) -> None:
        self._stopping = True
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _supervise(self) -> None:
        while not self._stopping:
            try:
                acquired = self._lock.try_acquire()
            except Exception as exc:
                logger.error(
                    f"DingTalk leader lock failed: {exc}", extra={"node": "dingtalk"}
                )
                await asyncio.sleep(10)
                continue

            if not acquired:
                logger.info(
                    "Another worker holds the DingTalk leader lock; retrying",
                    extra={"node": "dingtalk"},
                )
                await asyncio.sleep(5)
                continue

            try:
                await self._run_bot()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    f"DingTalk bot stopped unexpectedly: {exc}",
                    extra={"node": "dingtalk"},
                )
            finally:
                self._lock.release()

            if not self._stopping:
                await asyncio.sleep(5)

    async def _run_bot(self) -> None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(10.0, connect=5.0)
        ) as http:
            credential = dingtalk_stream.Credential(
                self.settings.dingtalk_app_key,
                self.settings.dingtalk_app_secret,
            )
            client = dingtalk_stream.DingTalkStreamClient(credential)
            client.register_callback_handler(
                dingtalk_stream.ChatbotMessage.TOPIC,
                DingTalkHandler(http),
            )

            notifier = asyncio.create_task(
                notify_loop(http), name="dingtalk-notifier"
            )
            logger.info("DingTalk stream client starting", extra={"node": "dingtalk"})
            try:
                await client.start()
            finally:
                stop = getattr(client, "stop", None)
                if stop is not None:
                    await stop()
                notifier.cancel()
                await asyncio.gather(notifier, return_exceptions=True)
