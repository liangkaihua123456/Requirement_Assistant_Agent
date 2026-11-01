"""钉钉 Stream 机器人的启动、Leader 锁和生命周期。

机器人1/2 都可接入 Stream 收消息建任务：
- 机器人1 侧重提问（也可用 OpenAPI 主动发群）
- 机器人2 侧重建议与确认
"""

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


def _build_stream_client(
    app_key: str,
    app_secret: str,
    http: httpx.AsyncClient,
    role: str,
) -> dingtalk_stream.DingTalkStreamClient:
    credential = dingtalk_stream.Credential(app_key, app_secret)
    client = dingtalk_stream.DingTalkStreamClient(credential)
    client.register_callback_handler(
        dingtalk_stream.ChatbotMessage.TOPIC,
        DingTalkHandler(http, robot_role=role),
    )
    return client


class DingTalkService:
    """在 FastAPI 进程内后台运行；不阻塞非 leader 的 API worker。"""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._task: asyncio.Task | None = None
        self._stopping = False
        self._lock = LeaderLock(settings.dingtalk_lock_path)

    async def start(self) -> bool:
        if not self.settings.dingtalk_robot2_configured:
            logger.error(
                "DingTalk enabled but robot2 Client ID/Secret is missing "
                "(DINGTALK_ROBOT2_APP_KEY/SECRET or DINGTALK_APP_KEY/SECRET)",
                extra={"node": "dingtalk"},
            )
            return False
        if fcntl is None:
            logger.error(
                "DingTalk leader lock needs fcntl; disabled on this platform",
                extra={"node": "dingtalk"},
            )
            return False

        if self.settings.dingtalk_robot1_configured:
            logger.info(
                "DingTalk robot1 Stream+OpenAPI enabled "
                f"(key={self.settings.dingtalk_robot1_app_key})",
                extra={"node": "dingtalk"},
            )
        else:
            logger.warning(
                "DingTalk robot1 is NOT configured; only robot2 will receive messages. "
                "Set DINGTALK_ROBOT1_APP_KEY/SECRET to enable.",
                extra={"node": "dingtalk"},
            )

        self._stopping = False
        self._task = asyncio.create_task(
            self._supervise(), name="dingtalk-supervisor"
        )
        logger.info(
            "DingTalk supervisor started "
            f"(robot2 key={self.settings.dingtalk_robot2_app_key})",
            extra={"node": "dingtalk"},
        )
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

    async def _keep_stream(
        self,
        *,
        role: str,
        app_key: str,
        app_secret: str,
        http: httpx.AsyncClient,
    ) -> None:
        """单个机器人 Stream 独立保活，互不影响。"""
        while not self._stopping:
            client = _build_stream_client(app_key, app_secret, http, role)
            logger.info(
                f"DingTalk {role} stream client starting",
                extra={"node": "dingtalk"},
            )
            try:
                await client.start()
                if self._stopping:
                    return
                logger.warning(
                    f"DingTalk {role} stream exited; reconnecting",
                    extra={"node": "dingtalk"},
                )
            except asyncio.CancelledError:
                stop = getattr(client, "stop", None)
                if stop is not None:
                    try:
                        await stop()
                    except Exception:
                        pass
                raise
            except Exception as exc:
                logger.error(
                    f"DingTalk {role} stream error: {exc}",
                    extra={"node": "dingtalk"},
                )
            await asyncio.sleep(5)

    async def _run_bot(self) -> None:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(90.0, connect=10.0)
        ) as http:
            workers = [
                asyncio.create_task(
                    self._keep_stream(
                        role="robot2",
                        app_key=self.settings.dingtalk_robot2_app_key,
                        app_secret=self.settings.dingtalk_robot2_app_secret,
                        http=http,
                    ),
                    name="dingtalk-robot2-stream",
                ),
                asyncio.create_task(
                    notify_loop(http), name="dingtalk-notifier"
                ),
            ]
            if self.settings.dingtalk_robot1_configured:
                workers.append(
                    asyncio.create_task(
                        self._keep_stream(
                            role="robot1",
                            app_key=self.settings.dingtalk_robot1_app_key,
                            app_secret=self.settings.dingtalk_robot1_app_secret,
                            http=http,
                        ),
                        name="dingtalk-robot1-stream",
                    )
                )
            try:
                await asyncio.gather(*workers)
            finally:
                for task in workers:
                    task.cancel()
                await asyncio.gather(*workers, return_exceptions=True)
