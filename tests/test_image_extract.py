"""图片需求识别接口测试。

覆盖：通道状态、正常中文截图、非图片、空文件、损坏图片、超大文件、
视觉通道未配置时的降级，以及视觉通道异常时自动切换到本地 OCR。
"""

from __future__ import annotations

import io

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFont

from app.core.config import get_settings
from app.main import app
from app.vision import vision_model


def _render_requirement_image() -> bytes:
    font_path = "C:/Windows/Fonts/msyh.ttc"
    try:
        font = ImageFont.truetype(font_path, 26)
        title_font = ImageFont.truetype(font_path, 32)
    except OSError:  # 非 Windows 或无中文字体时退回默认字体
        font = ImageFont.load_default()
        title_font = font
    lines = [
        "需求说明",
        "产品目标：为门店提供扫码点单能力。",
        "核心功能：",
        "1. 扫码进入菜单",
        "2. 在线支付",
        "约束条件：使用微信小程序",
    ]
    image = Image.new("RGB", (900, 380), "white")
    draw = ImageDraw.Draw(image)
    y = 24
    for index, line in enumerate(lines):
        draw.text((30, y), line, fill="black", font=title_font if index == 0 else font)
        y += 50
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture(autouse=True)
def _no_vision_by_default(monkeypatch):
    """测试环境里 .env 可能配了可用密钥，默认关掉视觉通道避免真实网络调用。

    需要验证视觉行为的用例会自行把它改回 True。
    """
    monkeypatch.setattr(vision_model, "is_configured", lambda: False)


@pytest.fixture(scope="module")
def sample_png() -> bytes:
    return _render_requirement_image()


def test_structure_separates_audience_and_skips_doc_title():
    """'目标用户' 不能被当成'目标'，带项目名的文档标题不能混进功能列表。"""
    from app.vision.extractor import structure_from_text

    text = "\n".join(
        [
            "门店点单小程序 需求说明",
            "产品目标：为门店提供扫码点单能力。",
            "核心功能：",
            "1. 扫码进入菜单",
            "约束条件：使用微信小程序",
            "目标用户：门店店长与顾客",
        ]
    )
    result = structure_from_text(text)
    assert result["goal"] == "为门店提供扫码点单能力。"
    assert result["audience"] == "门店店长与顾客"
    assert result["features"] == ["扫码进入菜单"]
    assert result["constraints"] == ["使用微信小程序"]


def test_status_reports_channels(client: TestClient):
    response = client.get("/extract/status")
    assert response.status_code == 200
    data = response.json()
    assert data["enabled"] is True
    assert data["ocr_ready"] is True
    assert data["preferred"] in {"ocr", "vision"}
    assert data["limits"]["max_bytes"] > 0


def test_ocr_extracts_chinese_text(client: TestClient, sample_png: bytes):
    response = client.post(
        "/extract/image",
        files={"file": ("req.png", sample_png, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["ok"] is True
    assert data["source"] == "ocr"
    assert "扫码" in data["text"]
    assert data["image"]["format"] == "PNG"
    # 结构化拆分应把目标与功能分开
    assert "门店" in data["goal"]
    assert any("支付" in item for item in data["features"])


def test_rejects_non_image(client: TestClient):
    response = client.post(
        "/extract/image",
        files={"file": ("note.txt", b"just text, not an image", "text/plain")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "not_image"


def test_rejects_empty_file(client: TestClient):
    response = client.post(
        "/extract/image",
        files={"file": ("empty.png", b"", "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] in {"empty", "corrupt"}


def test_rejects_truncated_image(client: TestClient, sample_png: bytes):
    response = client.post(
        "/extract/image",
        files={"file": ("broken.png", sample_png[:200], "image/png")},
    )
    assert response.status_code == 400
    assert response.json()["detail"]["code"] in {"corrupt", "not_image"}


def test_rejects_oversized_upload(client: TestClient, sample_png: bytes, monkeypatch):
    monkeypatch.setattr(get_settings(), "image_max_bytes", 1024, raising=False)
    response = client.post(
        "/extract/image",
        files={"file": ("big.png", sample_png, "image/png")},
    )
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "too_large"


def test_vision_failure_falls_back_to_ocr(client: TestClient, sample_png: bytes, monkeypatch):
    async def boom(prepared):
        raise RuntimeError("provider timeout")

    monkeypatch.setattr(vision_model, "is_configured", lambda: True)
    monkeypatch.setattr(vision_model, "analyze", boom)

    response = client.post(
        "/extract/image",
        files={"file": ("req.png", sample_png, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ocr"
    assert any("视觉模型调用失败" in item for item in data["warnings"])


def test_vision_unusable_result_falls_back_to_ocr(client: TestClient, sample_png: bytes, monkeypatch):
    """模型收下 image_url 但没读到图，返回"无法读取图片"时不能当成识别成功。"""

    async def blind_analyze(prepared):
        return {
            "title": "未识别图片",
            "goal": "无法读取图片内容，因此无法提取软件需求。",
            "features": [],
            "constraints": [],
            "audience": "",
            "raw_text": "无法读取图片内容，因此无法提取软件需求。",
        }

    monkeypatch.setattr(vision_model, "is_configured", lambda: True)
    monkeypatch.setattr(vision_model, "analyze", blind_analyze)

    response = client.post(
        "/extract/image",
        files={"file": ("req.png", sample_png, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ocr"
    assert "扫码" in data["text"]
    assert any("未返回有效内容" in item for item in data["warnings"])


def test_vision_not_supported_falls_back_to_ocr(client: TestClient, sample_png: bytes, monkeypatch):
    """模型把结论放在 title 里、goal 说"图片无法加载或不受支持"时也要判为无效。"""

    async def unsupported_analyze(prepared):
        return {
            "title": "无法识别图片内容",
            "goal": "图片无法加载或不受支持，无法提取需求。",
            "features": [],
            "constraints": [],
            "audience": "",
            "raw_text": "",
        }

    monkeypatch.setattr(vision_model, "is_configured", lambda: True)
    monkeypatch.setattr(vision_model, "analyze", unsupported_analyze)

    response = client.post(
        "/extract/image",
        files={"file": ("req.png", sample_png, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "ocr"
    assert any("未返回有效内容" in item for item in data["warnings"])


def test_vision_success_is_preferred(client: TestClient, sample_png: bytes, monkeypatch):
    async def fake_analyze(prepared):
        return {
            "title": "扫码点单",
            "goal": "让顾客自助点单",
            "features": ["扫码进入菜单", "在线支付"],
            "constraints": ["微信小程序"],
            "audience": "门店顾客",
            "raw_text": "需求说明\n扫码点单\n在线支付",
        }

    monkeypatch.setattr(vision_model, "is_configured", lambda: True)
    monkeypatch.setattr(vision_model, "analyze", fake_analyze)

    response = client.post(
        "/extract/image",
        files={"file": ("req.png", sample_png, "image/png")},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["source"] == "vision"
    assert data["title"] == "扫码点单"
    assert data["features"] == ["扫码进入菜单", "在线支付"]
    assert data["constraints"] == ["微信小程序"]
