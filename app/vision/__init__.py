"""图片需求识别：多模态模型优先，本地 OCR 兜底。"""

from app.vision.extractor import extract_requirement_from_image
from app.vision.status import extractor_status

__all__ = ["extract_requirement_from_image", "extractor_status"]
