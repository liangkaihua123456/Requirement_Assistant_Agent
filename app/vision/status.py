"""识别通道状态，供前端展示"当前用哪条通道"。"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.model_router import resolve_profile
from app.vision import ocr_engine, vision_model


def extractor_status(warmup_ocr: bool = False) -> dict:
    settings = get_settings()
    vision_on = vision_model.is_configured()
    vision_model_name = resolve_profile("vision").model if vision_on else ""

    if not settings.image_extract_enabled:
        return {
            "enabled": False,
            "vision_ready": vision_on,
            "vision_model": vision_model_name,
            "ocr_ready": False,
            "ocr_detail": "",
            "preferred": "none",
            "limits": _limits(),
        }

    if warmup_ocr:
        ocr_engine.warmup()
    ocr_ready, ocr_detail = ocr_engine.is_available()

    if vision_on:
        preferred = "vision"
    elif ocr_ready:
        preferred = "ocr"
    else:
        preferred = "none"

    return {
        "enabled": True,
        "vision_ready": vision_on,
        "vision_model": vision_model_name,
        "ocr_ready": ocr_ready,
        "ocr_detail": ocr_detail,
        "preferred": preferred,
        "limits": _limits(),
    }


def _limits() -> dict:
    settings = get_settings()
    return {
        "max_bytes": settings.image_max_bytes,
        "max_pixels": settings.image_max_pixels,
        "long_edge": settings.image_target_long_edge,
        "vision_timeout": settings.vision_timeout_seconds,
        "ocr_timeout": settings.ocr_timeout_seconds,
    }
