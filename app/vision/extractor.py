"""双通道识别编排：视觉模型优先，本地 OCR 兜底，任一路失败都返回可用结果。

设计原则
- 不向上抛业务异常：接口层只需要区分"图片不合法"(4xx) 与"识别完成但有告警"(200)。
- 两路结果都保留原文，前端永远给用户可编辑的文本，避免识别误差直接进入任务。
- 结构化拆分优先用视觉模型输出；OCR 通道用规则拆分，不额外消耗模型调用。
"""

from __future__ import annotations

import re
import time
from datetime import datetime, timezone

from app.core.logger import logger
from app.core.model_router import resolve_profile
from app.core.usage import UsageRecord, estimate_cost, is_peak_hour
from app.storage.usage_writer import insert_usage
from app.vision import ocr_engine, vision_model
from app.vision.preprocess import PreparedImage

MAX_TEXT_CHARS = 6000
SECTION_HEADINGS = {
    "goal": ("产品目标", "目标", "背景", "需求背景", "业务目标", "项目背景"),
    "features": ("核心功能", "功能需求", "功能", "需求", "要求", "功能列表"),
    "constraints": ("约束条件", "约束", "限制", "技术栈", "非功能需求", "非功能", "性能要求"),
    "audience": ("目标用户", "用户", "适用人群", "受众"),
}
_HEADING_RE = re.compile(r"^[\s#*\-•·]*([^：:]{1,10})[：:]\s*(.*)$")
# 文档标题本身不是需求条目，识别到就跳过。
_SKIP_TITLES = {
    "需求说明",
    "需求文档",
    "需求清单",
    "功能清单",
    "功能说明",
    "产品需求",
    "页面说明",
    "原型说明",
    "说明",
    "需求",
}


def _is_doc_title(line: str) -> bool:
    compact = re.sub(r"[\s#*\-•·]", "", line)
    if not compact:
        return False
    if compact in _SKIP_TITLES:
        return True
    # "门店点单小程序需求说明" 这类带项目名的标题也要跳过
    if len(compact) <= 12 and compact.endswith(("需求说明", "需求文档", "需求清单", "功能清单")):
        return True
    return False


def _clean_line(line: str) -> str:
    line = line.strip()
    # 只去掉列表符号；"1.5 万字" 这类数字不能误伤，所以序号后必须跟空白。
    line = re.sub(r"^(?:[-•·*]\s*|\d+[.、)]\s*)", "", line)
    return line.strip()


def _dedupe(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for line in lines:
        cleaned = _clean_line(line)
        if len(cleaned) < 2:
            continue
        # 页码、纯符号行对需求无意义
        if re.fullmatch(r"[-—_=*·.\d\s/]+", cleaned):
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def _match_heading(text: str) -> tuple[str | None, str]:
    """把 "小标题：内容" 映射到字段。

    必须先精确匹配再退化到包含匹配，否则 "目标用户：" 会因为包含 "目标" 被
    错判成产品目标；多个关键词命中时取最长的一个。
    """
    match = _HEADING_RE.match(text)
    if not match:
        return None, text
    label, rest = match.group(1).strip(), match.group(2).strip()
    if len(label) > 8:
        return None, text

    def best(exact: bool) -> tuple[str | None, int]:
        field, size = None, 0
        for name, names in SECTION_HEADINGS.items():
            for keyword in names:
                hit = label == keyword if exact else keyword in label
                if hit and len(keyword) > size:
                    field, size = name, len(keyword)
        return field, size

    field, _ = best(exact=True)
    if field is None:
        field, _ = best(exact=False)
    return (field, rest) if field else (None, text)


def structure_from_text(text: str) -> dict:
    """把 OCR 原文按常见小标题切成目标/功能/约束，识别不到就整体归入功能。"""
    lines = _dedupe(text.splitlines())
    sections: dict[str, list[str]] = {"goal": [], "features": [], "constraints": [], "audience": []}
    current: str | None = None

    for line in lines:
        if _is_doc_title(line):
            continue
        field, rest = _match_heading(line)
        if field:
            current = field
            if rest:
                sections[field].append(rest)
            continue
        if current:
            sections[current].append(line)
        else:
            sections["features"].append(line)

    goal = " ".join(sections["goal"]).strip()
    features = [item for item in sections["features"] if len(item) <= 120]
    constraints = [item for item in sections["constraints"] if len(item) <= 120]
    audience = " ".join(sections["audience"]).strip()

    # 没有小标题时，长文本段落不适合当功能条目，只保留前几条短句。
    if len(features) > 12:
        features = features[:12]
    return {
        "goal": goal,
        "features": features,
        "constraints": constraints,
        "audience": audience,
    }


def _normalize_vision_result(data: dict) -> dict:
    def as_list(value) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [line.strip() for line in value.splitlines() if line.strip()]
        return []

    return {
        "title": str(data.get("title") or "").strip()[:60],
        "goal": str(data.get("goal") or "").strip(),
        "features": as_list(data.get("features"))[:20],
        "constraints": as_list(data.get("constraints"))[:12],
        "audience": str(data.get("audience") or "").strip(),
        "raw_text": str(data.get("raw_text") or "").strip(),
    }


_INVALID_PATTERNS = (
    "无法读取",
    "无法识别图片",
    "无法识别图片内容",
    "无法加载",
    "无法查看图片",
    "看不到图片",
    "图片不受支持",
    "不受支持",
    "未提供图片",
    "没有图片",
    "图片为空",
    "cannot read the image",
    "can't see the image",
    "cannot see the image",
    "no image provided",
    "unable to view",
    "unable to load",
    "cannot load",
    "not supported",
    "image is not provided",
)
# features 为空时，目标里的否定表述基本都意味着"模型没看到图"。
_NEGATIONS = ("无法", "不能", "未能", "不可用", "不支持", "cannot", "can't", "unable", "not support")


def _vision_result_usable(data: dict) -> tuple[bool, str]:
    """判断视觉模型是否真的读到了图。

    部分模型会接受 image_url 但忽略图片，转而回一句"图片无法加载或不受支持"。
    这种响应结构合法，却会把无意义文字当成识别结果。标题、目标与原文都要参与
    匹配：模型常把结论放在 title 里，只看 raw_text 会漏判。
    """
    title = str(data.get("title") or "").strip()
    goal = str(data.get("goal") or "").strip()
    text = str(data.get("raw_text") or "").strip()
    features = data.get("features") or []
    combined = f"{title} {goal} {text}".lower()

    if any(pattern in combined for pattern in _INVALID_PATTERNS):
        return False, "模型声明无法读取图片"
    if not features:
        if any(word in combined for word in _NEGATIONS):
            return False, "模型未读到图片内容"
        if len(text) < 12 and len(goal) < 12:
            return False, "模型返回内容为空"
    return True, ""


def _brief_error(exc: Exception, limit: int = 80) -> str:
    text = str(exc).replace("\n", " ").strip()
    return text[:limit] + ("…" if len(text) > limit else "")


def _record_vision_usage(usage: dict, task_id: str = "") -> None:
    """图片识别同样消耗 token，必须进同一本账。"""
    if not usage or not int(usage.get("total_tokens") or 0):
        return
    model = resolve_profile("vision").model
    now = datetime.now(timezone.utc)
    record = UsageRecord(
        role="vision",
        model=model,
        prompt_tokens=int(usage.get("prompt_tokens") or 0),
        completion_tokens=int(usage.get("completion_tokens") or 0),
        total_tokens=int(usage.get("total_tokens") or 0),
        cached_tokens=int(usage.get("cached_tokens") or 0),
        at=now,
    )
    amount, known = estimate_cost(record)
    insert_usage(
        task_id=task_id,
        node="image_extract",
        role="vision",
        model=model,
        prompt_tokens=record.prompt_tokens,
        completion_tokens=record.completion_tokens,
        total_tokens=record.total_tokens,
        cached_tokens=record.cached_tokens,
        cost_cny=amount,
        priced=known,
        peak=is_peak_hour(now),
        source="vision",
    )


async def extract_requirement_from_image(prepared: PreparedImage, task_id: str = "") -> dict:
    started = time.perf_counter()
    warnings: list[str] = list(prepared.warnings)
    vision_data: dict | None = None
    ocr_result: ocr_engine.OcrResult | None = None
    ocr_error = ""

    if vision_model.is_configured():
        try:
            raw = await vision_model.analyze(prepared)
            _record_vision_usage(raw.pop("_usage", {}) or {}, task_id=task_id)
            vision_data = _normalize_vision_result(raw)
            usable, reason = _vision_result_usable(vision_data)
            if not usable:
                logger.info(f"Vision result unusable ({reason}), falling back to OCR")
                warnings.append(f"视觉模型未返回有效内容（{reason}），已自动切换本地 OCR")
                vision_data = None
        except vision_model.VisionUnavailable as exc:
            warnings.append(f"视觉模型未启用（{exc}），已使用本地 OCR")
        except Exception as exc:
            ocr_error = str(exc)[:200]
            logger.warning(f"Vision channel failed, falling back to OCR: {ocr_error}")
            warnings.append(f"视觉模型调用失败（{_brief_error(exc)}），已自动切换本地 OCR")
    else:
        warnings.append("未配置视觉模型，当前使用本地 OCR")

    need_ocr = vision_data is None

    if need_ocr:
        try:
            ocr_result = await ocr_engine.recognize(prepared.jpeg_bytes)
        except ocr_engine.OcrUnavailable as exc:
            ocr_error = str(exc)
            warnings.append(f"本地 OCR 不可用：{ocr_error}")
        except Exception as exc:
            ocr_error = str(exc)[:200]
            logger.warning(f"OCR channel failed: {ocr_error}")
            warnings.append("本地 OCR 识别失败")

    if vision_data is not None:
        source = "vision"
        text = vision_data["raw_text"] or "\n".join(
            [vision_data["goal"], *vision_data["features"], *vision_data["constraints"]]
        )
        structured = {
            "goal": vision_data["goal"],
            "features": vision_data["features"],
            "constraints": vision_data["constraints"],
            "audience": vision_data["audience"],
        }
        title = vision_data["title"]
        confidence = 0.9
    elif ocr_result is not None:
        source = "ocr"
        text = ocr_result.text
        structured = structure_from_text(text)
        title = ""
        confidence = ocr_result.confidence
    else:
        source = "none"
        text = ""
        structured = {"goal": "", "features": [], "constraints": [], "audience": ""}
        title = ""
        confidence = 0.0
        warnings.append("两路识别均未返回内容，请手动填写需求")

    text = text[:MAX_TEXT_CHARS].strip()
    if source != "none" and not text:
        warnings.append("未识别到文字，请确认图片清晰度或改用更清楚的截图")
        if source == "ocr":
            source = "none"

    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info(
        "Image extract finished",
        extra={
            "source": source,
            "elapsed_ms": elapsed_ms,
            "chars": len(text),
            "warnings": len(warnings),
        },
    )

    return {
        "ok": source != "none",
        "source": source,
        "title": title,
        "text": text,
        "goal": structured["goal"],
        "features": structured["features"],
        "constraints": structured["constraints"],
        "audience": structured["audience"],
        "confidence": confidence,
        "warnings": warnings,
        "elapsed_ms": elapsed_ms,
        "image": {
            "width": prepared.width,
            "height": prepared.height,
            "bytes": len(prepared.jpeg_bytes),
            "original_bytes": prepared.original_bytes,
            "format": prepared.original_format,
        },
    }


__all__ = ["extract_requirement_from_image", "structure_from_text"]
