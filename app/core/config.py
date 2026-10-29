"""全局配置模块，基于 pydantic-settings 管理环境变量。"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 加载 .env 文件
from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")

# 支持按角色覆盖模型配置的角色名
ROLE_NAMES = (
    "planner",
    "solution",
    "engineer",
    "reviewer",
    "repairer",
    "evaluator",
    "dialogue",
    "normalizer",
    # 图片识别使用的多模态模型。未显式配置时该通道自动关闭，识别走本地 OCR。
    "vision",
)


class RoleOverride(BaseModel):
    """单个角色的模型覆盖配置，空值表示继承全局。"""

    model: str = ""
    api_base: str = ""
    api_key: str = ""
    max_tokens: int = 0
    reasoning_effort: str = ""


class ModelPrice(BaseModel):
    """模型单价：每百万 token 的价格。"""

    input: float = 0.0
    cached_input: float = 0.0
    output: float = 0.0
    currency: str = "CNY"


DEFAULT_MODEL_PRICING: dict[str, ModelPrice] = {
    # DeepSeek 官方价目表（元/百万 token）。这里存的是**高峰时段**单价，
    # 空闲时段（工作日 9-12、14-18 之外，以及周末与法定节假日全天）按半价计。
    "deepseek-flash": ModelPrice(input=2.0, cached_input=0.04, output=8.0, currency="CNY"),
    "deepseek-v4-pro": ModelPrice(input=9.0, cached_input=0.30, output=27.0, currency="CNY"),
    # OpenAI 官方标准价（美元/百万 token，短上下文），无时段区分
    "gpt-6.1-sol": ModelPrice(input=2.0, cached_input=0.10, output=10.0, currency="USD"),
}


def _role_overrides() -> dict[str, RoleOverride]:
    overrides: dict[str, RoleOverride] = {}
    for role in ROLE_NAMES:
        prefix = f"ROLE_{role.upper()}_"
        max_tokens_raw = os.getenv(prefix + "MAX_TOKENS", "0") or "0"
        overrides[role] = RoleOverride(
            model=os.getenv(prefix + "MODEL", ""),
            api_base=os.getenv(prefix + "API_BASE", ""),
            api_key=os.getenv(prefix + "API_KEY", ""),
            max_tokens=int(max_tokens_raw) if max_tokens_raw.isdigit() else 0,
            reasoning_effort=os.getenv(prefix + "REASONING_EFFORT", ""),
        )
    return overrides


def _model_pricing() -> dict[str, ModelPrice]:
    pricing = dict(DEFAULT_MODEL_PRICING)
    raw = os.getenv("MODEL_PRICING_JSON", "").strip()
    if not raw:
        return pricing
    try:
        parsed = json.loads(raw)
        for model, item in parsed.items():
            if isinstance(item, dict):
                pricing[str(model)] = ModelPrice(**item)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return pricing


class Settings(BaseModel):
    """应用配置。"""

    # LLM
    openai_api_key: str = Field(default_factory=lambda: os.getenv("OPENAI_API_KEY", ""))
    openai_api_base: str = Field(
        default_factory=lambda: os.getenv("OPENAI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    )
    openai_model_name: str = Field(
        default_factory=lambda: os.getenv("OPENAI_MODEL_NAME", "qwen-max")
    )
    openai_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("OPENAI_TIMEOUT_SECONDS", "180"))
    )
    structured_output_method: str = Field(
        default_factory=lambda: os.getenv("STRUCTURED_OUTPUT_METHOD", "function_calling")
    )
    openai_max_tokens: int = Field(
        default_factory=lambda: int(os.getenv("OPENAI_MAX_TOKENS", "8192"))
    )
    structured_output_max_continuations: int = Field(
        default_factory=lambda: int(os.getenv("STRUCTURED_OUTPUT_MAX_CONTINUATIONS", "3"))
    )

    # 模型路由：按角色选择模型，空配置继承全局
    model_routing_enabled: bool = Field(
        default_factory=lambda: os.getenv("MODEL_ROUTING_ENABLED", "true").lower() == "true"
    )
    model_routing_fallback_enabled: bool = Field(
        default_factory=lambda: os.getenv("MODEL_ROUTING_FALLBACK_ENABLED", "true").lower() == "true"
    )
    role_overrides: dict[str, RoleOverride] = Field(default_factory=_role_overrides)
    model_pricing: dict[str, ModelPrice] = Field(default_factory=_model_pricing)
    usd_to_cny_rate: float = Field(
        default_factory=lambda: float(os.getenv("USD_TO_CNY_RATE", "7.1"))
    )
    # DeepSeek 空闲时段单价 = 高峰价 × 该系数（官方为半价）
    off_peak_ratio: float = Field(
        default_factory=lambda: float(os.getenv("OFF_PEAK_PRICE_RATIO", "0.5"))
    )
    peak_timezone_offset: int = Field(
        default_factory=lambda: int(os.getenv("PEAK_TIMEZONE_OFFSET", "8"))
    )

    # LangSmith
    langchain_tracing_v2: bool = Field(
        default_factory=lambda: os.getenv("LANGCHAIN_TRACING_V2", "false").lower() == "true"
    )
    langchain_api_key: str = Field(default_factory=lambda: os.getenv("LANGCHAIN_API_KEY", ""))
    langchain_project: str = Field(
        default_factory=lambda: os.getenv("LANGCHAIN_PROJECT", "multi-agent-v1")
    )

    # Database
    database_url: str = Field(
        default_factory=lambda: os.getenv(
            "DATABASE_URL", f"sqlite+aiosqlite:///{BASE_DIR / 'data' / 'tasks.db'}"
        )
    )

    # App
    app_env: str = Field(default_factory=lambda: os.getenv("APP_ENV", "development"))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))
    max_reflow_count: int = Field(
        default_factory=lambda: int(os.getenv("MAX_REFLOW_COUNT", "2"))
    )
    prompt_version: str = Field(
        default_factory=lambda: os.getenv("PROMPT_VERSION", "v1")
    )

    # Memory / RAG
    memory_enabled: bool = Field(
        default_factory=lambda: os.getenv("MEMORY_ENABLED", "false").lower() == "true"
    )
    memory_top_k: int = Field(
        default_factory=lambda: int(os.getenv("MEMORY_TOP_K", "3"))
    )
    memory_context_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("MEMORY_CONTEXT_MAX_CHARS", "1800"))
    )
    memory_item_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("MEMORY_ITEM_MAX_CHARS", "900"))
    )
    memory_embedding_model: str = Field(
        default_factory=lambda: os.getenv("MEMORY_EMBEDDING_MODEL", "text-embedding-v3")
    )
    memory_embedding_dimensions: int = Field(
        default_factory=lambda: int(os.getenv("MEMORY_EMBEDDING_DIMENSIONS", "1024"))
    )

    # Short-term memory
    short_term_memory_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("SHORT_TERM_MEMORY_MAX_CHARS", "1200"))
    )
    short_term_memory_max_entries: int = Field(
        default_factory=lambda: int(os.getenv("SHORT_TERM_MEMORY_MAX_ENTRIES", "15"))
    )

    # Dynamic Few-shot
    few_shot_top_k: int = Field(
        default_factory=lambda: int(os.getenv("FEW_SHOT_TOP_K", "2"))
    )
    few_shot_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("FEW_SHOT_MAX_CHARS", "1500"))
    )
    few_shot_min_score: float = Field(
        default_factory=lambda: float(os.getenv("FEW_SHOT_MIN_SCORE", "7.0"))
    )

    # Memory Consolidation & Conflict Detection
    memory_consolidation_enabled: bool = Field(
        default_factory=lambda: os.getenv("MEMORY_CONSOLIDATION_ENABLED", "true").lower() == "true"
    )
    memory_consolidation_trigger_count: int = Field(
        default_factory=lambda: int(os.getenv("MEMORY_CONSOLIDATION_TRIGGER_COUNT", "20"))
    )
    memory_conflict_similarity_threshold: float = Field(
        default_factory=lambda: float(os.getenv("MEMORY_CONFLICT_SIMILARITY_THRESHOLD", "0.65"))
    )
    memory_consolidation_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("MEMORY_CONSOLIDATION_MAX_CHARS", "4000"))
    )

    # Repairer (轻量修复)
    repairer_enabled: bool = Field(
        default_factory=lambda: os.getenv("REPAIRER_ENABLED", "true").lower() == "true"
    )

    # Self-Refine
    self_refine_enabled: bool = Field(
        default_factory=lambda: os.getenv("SELF_REFINE_ENABLED", "true").lower() == "true"
    )
    self_refine_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("SELF_REFINE_MAX_CHARS", "800"))
    )

    # Multi-Agent Dialogue
    dialogue_enabled: bool = Field(
        default_factory=lambda: os.getenv("DIALOGUE_ENABLED", "false").lower() == "true"
    )
    dialogue_max_rounds: int = Field(
        default_factory=lambda: int(os.getenv("DIALOGUE_MAX_ROUNDS", "3"))
    )

    # Input Normalize (False = rule-based cleanup, saves one LLM round-trip)
    input_normalize_llm_enabled: bool = Field(
        default_factory=lambda: os.getenv("INPUT_NORMALIZE_LLM_ENABLED", "false").lower() == "true"
    )
    input_normalize_max_chars: int = Field(
        default_factory=lambda: int(os.getenv("INPUT_NORMALIZE_MAX_CHARS", "8000"))
    )

    # Task queue concurrency (number of tasks executed in parallel)
    task_worker_concurrency: int = Field(
        default_factory=lambda: max(1, int(os.getenv("TASK_WORKER_CONCURRENCY", "2")))
    )

    # Structured output continuation
    continuation_slim_context_enabled: bool = Field(
        default_factory=lambda: os.getenv("CONTINUATION_SLIM_CONTEXT_ENABLED", "true").lower() == "true"
    )

    # Context Compression
    dialogue_compression_enabled: bool = Field(
        default_factory=lambda: os.getenv("DIALOGUE_COMPRESSION_ENABLED", "true").lower() == "true"
    )
    dialogue_compression_threshold: int = Field(
        default_factory=lambda: int(os.getenv("DIALOGUE_COMPRESSION_THRESHOLD", "2"))
    )
    context_budget_total_tokens: int = Field(
        default_factory=lambda: int(os.getenv("CONTEXT_BUDGET_TOTAL_TOKENS", "6000"))
    )

    # Image intake (OCR / vision)
    image_extract_enabled: bool = Field(
        default_factory=lambda: os.getenv("IMAGE_EXTRACT_ENABLED", "true").lower() == "true"
    )
    image_max_bytes: int = Field(
        default_factory=lambda: int(os.getenv("IMAGE_MAX_BYTES", str(10 * 1024 * 1024)))
    )
    image_max_pixels: int = Field(
        default_factory=lambda: int(os.getenv("IMAGE_MAX_PIXELS", "40000000"))
    )
    image_target_long_edge: int = Field(
        default_factory=lambda: int(os.getenv("IMAGE_TARGET_LONG_EDGE", "2000"))
    )
    vision_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("VISION_TIMEOUT_SECONDS", "60"))
    )
    ocr_timeout_seconds: float = Field(
        default_factory=lambda: float(os.getenv("OCR_TIMEOUT_SECONDS", "30"))
    )
    ocr_max_concurrency: int = Field(
        default_factory=lambda: max(1, int(os.getenv("OCR_MAX_CONCURRENCY", "2")))
    )
    vision_fallback_ocr_enabled: bool = Field(
        default_factory=lambda: os.getenv("VISION_FALLBACK_OCR_ENABLED", "true").lower() == "true"
    )

    # Plan-Verify (轻量并行规划)
    plan_variants_enabled: bool = Field(
        default_factory=lambda: os.getenv("PLAN_VARIANTS_ENABLED", "false").lower() == "true"
    )
    plan_variant_count: int = Field(
        default_factory=lambda: int(os.getenv("PLAN_VARIANT_COUNT", "2"))
    )

    # Paths
    data_dir: Path = Field(default=BASE_DIR / "data")
    templates_dir: Path = Field(default=BASE_DIR / "app" / "tools" / "templates")
    output_dir: Path = Field(default=BASE_DIR / "output")
    memory_persist_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("MEMORY_PERSIST_DIR", BASE_DIR / "data" / "chroma"))
    )
    checkpoint_dir: Path = Field(
        default_factory=lambda: Path(os.getenv("CHECKPOINT_DIR", BASE_DIR / "data" / "checkpoints"))
    )


@lru_cache()
def get_settings() -> Settings:
    """获取全局配置单例。"""
    return Settings()
