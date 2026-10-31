"""本地 OCR 引擎封装。

RapidOCR（ONNX Runtime / CPU）在进程内加载，不依赖任何外部服务或二进制。
引擎只初始化一次，识别放到线程池执行，并用信号量限制并发，避免多张图同时
上传时把 CPU 打满、拖慢整个 Web 服务。
"""

from __future__ import annotations

import asyncio
import io
import threading
import time
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from app.core.config import get_settings
from app.core.logger import logger


@dataclass
class OcrResult:
    text: str
    lines: list[str] = field(default_factory=list)
    confidence: float = 0.0
    elapsed_ms: float = 0.0


class OcrUnavailable(Exception):
    """OCR 依赖缺失或模型加载失败。"""


_engine = None
_engine_error: str | None = None
_engine_lock = threading.Lock()
_semaphore: asyncio.Semaphore | None = None
_semaphore_lock = threading.Lock()


def _get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        with _semaphore_lock:
            if _semaphore is None:
                _semaphore = asyncio.Semaphore(get_settings().ocr_max_concurrency)
    return _semaphore


def _load_engine():
    """懒加载引擎。首次调用会读取 ONNX 模型，约 1-3 秒。"""
    global _engine, _engine_error
    if _engine is not None:
        return _engine
    if _engine_error is not None:
        raise OcrUnavailable(_engine_error)
    with _engine_lock:
        if _engine is not None:
            return _engine
        if _engine_error is not None:
            raise OcrUnavailable(_engine_error)
        try:
            from rapidocr import RapidOCR  # 延迟导入，缺依赖时不影响服务启动

            _engine = RapidOCR()
            logger.info("OCR engine loaded (rapidocr)")
        except Exception as exc:  # 依赖缺失、模型损坏
            _engine_error = str(exc)[:300]
            logger.warning(f"OCR engine unavailable: {_engine_error}")
            raise OcrUnavailable(_engine_error)
    return _engine


def _to_bgr(jpeg_bytes: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(jpeg_bytes)) as image:
        rgb = np.asarray(image.convert("RGB"))
    return np.ascontiguousarray(rgb[:, :, ::-1])


def _normalize_output(output) -> tuple[list[str], list[float]]:
    """兼容 RapidOCR 不同版本的返回形状。"""
    # 3.x: RapidOCROutput(txts=..., scores=...)
    texts = getattr(output, "txts", None)
    scores = getattr(output, "scores", None)
    if texts is not None:
        return list(texts), [float(s) for s in (scores or [])]

    # 1.x: (result, elapse)，result 为 [(box, text, score), ...]
    payload = output[0] if isinstance(output, tuple) and output else output
    if isinstance(payload, list):
        lines: list[str] = []
        confidences: list[float] = []
        for item in payload:
            if isinstance(item, (list, tuple)) and len(item) >= 3:
                lines.append(str(item[1]))
                try:
                    confidences.append(float(item[2]))
                except (TypeError, ValueError):
                    confidences.append(0.0)
        return lines, confidences
    return [], []


def _run(jpeg_bytes: bytes) -> OcrResult:
    engine = _load_engine()
    started = time.perf_counter()
    output = engine(_to_bgr(jpeg_bytes))
    lines, scores = _normalize_output(output)
    cleaned = [line.strip() for line in lines if line and line.strip()]
    elapsed_ms = (time.perf_counter() - started) * 1000
    return OcrResult(
        text="\n".join(cleaned),
        lines=cleaned,
        confidence=round(sum(scores) / len(scores), 4) if scores else 0.0,
        elapsed_ms=round(elapsed_ms, 1),
    )


async def recognize(jpeg_bytes: bytes) -> OcrResult:
    """在线程池中执行识别，带并发限制与超时。"""
    if not get_settings().image_extract_enabled:
        raise OcrUnavailable("图片识别功能已关闭")

    semaphore = _get_semaphore()
    async with semaphore:
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(_run, jpeg_bytes),
                timeout=get_settings().ocr_timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise OcrUnavailable("本地 OCR 超时")


def warmup() -> None:
    """服务启动时预热，避免首个请求承担模型加载耗时。"""
    try:
        _load_engine()
    except OcrUnavailable:
        pass


def is_available() -> tuple[bool, str]:
    try:
        _load_engine()
        return True, ""
    except OcrUnavailable as exc:
        return False, str(exc)
