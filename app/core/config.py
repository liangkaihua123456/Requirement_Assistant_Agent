"""全局配置模块，基于 pydantic-settings 管理环境变量。"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field

# 项目根目录
BASE_DIR = Path(__file__).resolve().parent.parent.parent

# 加载 .env 文件
from dotenv import load_dotenv

load_dotenv(BASE_DIR / ".env")


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

    # DingTalk integration
    dingtalk_enabled: bool = Field(
        default_factory=lambda: os.getenv(
            "DINGTALK_SERVICE_ENABLED", "false"
        ).lower()
        == "true"
    )
    dingtalk_app_key: str = Field(
        default_factory=lambda: os.getenv("DINGTALK_APP_KEY", "")
    )
    dingtalk_app_secret: str = Field(
        default_factory=lambda: os.getenv("DINGTALK_APP_SECRET", "")
    )
    dingtalk_notify_interval_seconds: float = Field(
        default_factory=lambda: float(os.getenv("DINGTALK_NOTIFY_INTERVAL_SECONDS", "3"))
    )
    dingtalk_lock_path: Path = Field(
        default_factory=lambda: Path(
            os.getenv("DINGTALK_LOCK_PATH")
            or (BASE_DIR / "data" / "dingtalk.lock")
        )
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
