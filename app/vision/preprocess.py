"""图片校验与预处理。

上传内容一律视为不可信：先按字节数限制读取，再真正解码校验格式，
最后统一转正、缩放、转 RGB 后压缩为 JPEG，避免把超大图或畸形图送进识别通道。
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field

from PIL import Image, ImageOps, UnidentifiedImageError

from app.core.config import get_settings

# Pillow 能解码不等于业务需要，只放行常见的截图与扫描件格式。
ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}
FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "WEBP": "image/webp",
    "BMP": "image/bmp",
    "TIFF": "image/tiff",
}
JPEG_QUALITY = 88


class ImageRejected(Exception):
    """上传内容不满足识别条件。code 供接口层映射为提示文案。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class PreparedImage:
    jpeg_bytes: bytes
    mime: str
    width: int
    height: int
    original_bytes: int
    original_format: str
    warnings: list[str] = field(default_factory=list)

    @property
    def data_url(self) -> str:
        import base64

        encoded = base64.b64encode(self.jpeg_bytes).decode("ascii")
        return f"data:{self.mime};base64,{encoded}"


def prepare_image(raw: bytes) -> PreparedImage:
    """校验并规整图片，任何异常都以 ImageRejected 抛出。"""
    settings = get_settings()
    if not raw:
        raise ImageRejected("empty", "图片内容为空，请重新选择")
    if len(raw) > settings.image_max_bytes:
        limit_mb = settings.image_max_bytes / 1024 / 1024
        raise ImageRejected("too_large", f"图片超过 {limit_mb:.0f}MB 上限，请压缩后重试")

    try:
        with Image.open(io.BytesIO(raw)) as probe:
            probe_format = (probe.format or "").upper()
            width, height = probe.size
            # verify() 会消耗文件对象，仅用于校验完整性。
            probe.verify()
    except UnidentifiedImageError:
        raise ImageRejected("not_image", "无法识别该文件，请上传 JPG、PNG、WEBP 或 BMP 图片")
    except Exception:
        raise ImageRejected("corrupt", "图片已损坏或不完整，请换一张图片")

    if probe_format not in ALLOWED_FORMATS:
        raise ImageRejected("unsupported_format", f"暂不支持 {probe_format or '未知'} 格式")

    pixels = width * height
    if pixels <= 0:
        raise ImageRejected("corrupt", "图片尺寸异常")
    if pixels > settings.image_max_pixels:
        megapixels = settings.image_max_pixels / 1_000_000
        raise ImageRejected("too_many_pixels", f"图片像素超过 {megapixels:.0f} 万上限，请压缩后重试")

    warnings: list[str] = []
    try:
        with Image.open(io.BytesIO(raw)) as image:
            image = ImageOps.exif_transpose(image)
            if image.mode in ("RGBA", "LA", "P"):
                # 透明底直接转 RGB 会发黑，先铺白底。
                background = Image.new("RGB", image.size, (255, 255, 255))
                converted = image.convert("RGBA")
                background.paste(converted, mask=converted.split()[-1])
                image = background
            elif image.mode != "RGB":
                image = image.convert("RGB")

            long_edge = max(image.size)
            if long_edge > settings.image_target_long_edge:
                ratio = settings.image_target_long_edge / long_edge
                new_size = (
                    max(1, int(image.width * ratio)),
                    max(1, int(image.height * ratio)),
                )
                image = image.resize(new_size, Image.LANCZOS)
                warnings.append("图片已按长边上限压缩，细小文字可能受影响")

            buffer = io.BytesIO()
            image.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
            normalized = buffer.getvalue()
            width, height = image.size
    except ImageRejected:
        raise
    except Exception:
        raise ImageRejected("corrupt", "图片处理失败，请换一张图片")

    if len(normalized) < 1024:
        warnings.append("图片内容偏小，识别结果可能不完整")

    return PreparedImage(
        jpeg_bytes=normalized,
        mime=FORMAT_TO_MIME["JPEG"],
        width=width,
        height=height,
        original_bytes=len(raw),
        original_format=probe_format,
        warnings=warnings,
    )
