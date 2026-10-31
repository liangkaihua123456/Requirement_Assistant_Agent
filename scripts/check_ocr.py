"""OCR 自检：生成一张中文样图并跑一次本地识别，用于部署后确认引擎可用。

用法：python scripts/check_ocr.py
退出码 0 表示引擎正常，1 表示不可用。
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw, ImageFont

SAMPLE_LINES = [
    "需求说明",
    "产品目标：为中小餐饮门店提供扫码点单能力。",
    "核心功能：",
    "1. 扫码进入菜单",
    "2. 在线支付",
]


def build_sample() -> bytes:
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 26)
        title = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 32)
    except OSError:
        font = ImageFont.load_default()
        title = font
    image = Image.new("RGB", (900, 340), "white")
    draw = ImageDraw.Draw(image)
    y = 24
    for index, line in enumerate(SAMPLE_LINES):
        draw.text((30, y), line, fill="black", font=title if index == 0 else font)
        y += 52
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def main() -> int:
    from app.vision.ocr_engine import is_available
    from app.vision.preprocess import prepare_image
    from app.vision.extractor import structure_from_text

    ready, detail = is_available()
    if not ready:
        print(f"[FAIL] OCR 引擎不可用：{detail}")
        return 1

    import asyncio

    from app.vision import ocr_engine

    prepared = prepare_image(build_sample())
    result = asyncio.run(ocr_engine.recognize(prepared.jpeg_bytes))
    print(f"[OK] 识别 {len(result.lines)} 行，耗时 {result.elapsed_ms}ms，平均置信度 {result.confidence:.3f}")
    print(result.text)

    structured = structure_from_text(result.text)
    print(f"[OK] 目标：{structured['goal']}")
    print(f"[OK] 功能：{' / '.join(structured['features'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
