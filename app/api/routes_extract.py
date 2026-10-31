"""图片需求识别接口。

上传即识别，不落盘：字节读入内存，识别完随请求释放。任何识别环节的失败
都以降级结果返回（HTTP 200），只有"请求本身不合法"才返回 4xx，前端因此不会
因为一次识别失败而卡住。
"""

from __future__ import annotations

from fastapi import APIRouter, File, HTTPException, UploadFile

from app.core.config import get_settings
from app.core.logger import logger
from app.vision import extract_requirement_from_image, extractor_status
from app.vision.preprocess import ImageRejected, prepare_image

router = APIRouter(prefix="/extract", tags=["extract"])

CHUNK_SIZE = 64 * 1024


@router.get("/status")
async def get_extract_status(warmup: bool = False):
    """前端据此决定提示文案与是否启用上传入口。"""
    return extractor_status(warmup_ocr=warmup)


@router.post("/image")
async def extract_image(file: UploadFile = File(...)):
    settings = get_settings()
    if not settings.image_extract_enabled:
        raise HTTPException(
            status_code=403,
            detail={"code": "disabled", "message": "图片识别功能已关闭"},
        )

    limit = settings.image_max_bytes
    buffer = bytearray()
    while True:
        chunk = await file.read(CHUNK_SIZE)
        if not chunk:
            break
        buffer.extend(chunk)
        if len(buffer) > limit:
            raise HTTPException(
                status_code=413,
                detail={
                    "code": "too_large",
                    "message": f"图片超过 {limit / 1024 / 1024:.0f}MB 上限，请压缩后重试",
                },
            )

    raw = bytes(buffer)
    try:
        prepared = prepare_image(raw)
    except ImageRejected as exc:
        logger.info(f"Image rejected: {exc.code}")
        raise HTTPException(
            status_code=400,
            detail={"code": exc.code, "message": exc.message},
        )

    result = await extract_requirement_from_image(prepared)
    result["filename"] = file.filename or ""
    return result
