from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_env: str = "local"
    public_mode: bool = False
    admin_token: str | None = None
    admin_token_min_chars: int = 32
    cloudflare_access_required: bool = False
    cloudflare_access_allowed_emails: str = ""
    cloudflare_access_require_jwt: bool = True
    auth_max_failed_attempts: int = 5
    auth_lockout_seconds: int = 900
    data_dir: Path = REPO_ROOT / "data"
    sqlite_path: Path = REPO_ROOT / "data" / "knownet.db"
    knownet_db_version: str = Field(default="v2", validation_alias="KNOWNET_DB_VERSION")
    rust_core_path: Path = REPO_ROOT / ".local" / "cargo-target" / "debug" / "knownet-core.exe"
    sqlite_busy_timeout_ms: int = 5000
    sse_event_retention_hours: int = 24
    job_stale_after_seconds: int = 300
    max_message_bytes: int = 65536
    max_title_chars: int = 160
    max_slug_chars: int = 96
    write_requests_per_minute: int = 20
    queued_jobs_per_actor: int = 10
    openai_api_key: str | None = None
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-5-mini"
    openai_reasoning_effort: str | None = "low"
    openai_max_output_tokens: int = 2000
    openai_timeout_seconds: float = 60.0
    local_embedding_model: str = "snunlp/KR-SBERT-V40K-klueNLI-augSTS"
    local_embedding_auto_load: bool = True
    local_embedding_local_files_only: bool = True
    backup_retention_count: int = 10
    backup_max_bytes: int = 1073741824
    restore_require_snapshot: bool = True
    health_backup_max_age_hours: int = 168
    smoke_test_timeout_seconds: int = 120
    gemini_api_key: str | None = None
    gemini_base_url: str = "https://generativelanguage.googleapis.com/v1beta"
    gemini_model: str = "gemini-2.5-pro"
    gemini_response_mime_type: str = "application/json"
    gemini_thinking_budget: int | None = 0
    gemini_runner_enabled: bool = False
    gemini_max_context_tokens: int = 32000
    gemini_max_context_chars: int = 120000
    gemini_timeout_seconds: float = 90.0
    gemini_daily_run_limit: int = 20
    gemini_require_operator_import: bool = True
    deepseek_api_key: str | None = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_anthropic_base_url: str = "https://api.deepseek.com/anthropic"
    deepseek_model: str = "deepseek-v4-flash"
    deepseek_reasoning_effort: str = "high"
    deepseek_thinking_enabled: bool = True
    deepseek_runner_enabled: bool = False
    deepseek_timeout_seconds: float = 90.0
    minimax_api_key: str | None = None
    minimax_base_url: str = "https://api.minimaxi.com/v1"
    minimax_model: str = "MiniMax-M2.7"
    minimax_max_tokens: int = 4000
    minimax_reasoning_split: bool = True
    minimax_runner_enabled: bool = False
    minimax_timeout_seconds: float = 90.0
    qwen_api_key: str | None = None
    qwen_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_model: str = "qwen-plus"
    qwen_max_tokens: int = 4000
    qwen_enable_search: bool = False
    qwen_runner_enabled: bool = False
    qwen_timeout_seconds: float = 90.0
    kimi_api_key: str | None = None
    kimi_base_url: str = "https://api.moonshot.ai/v1"
    kimi_model: str = "kimi-k2.5"
    kimi_max_tokens: int = 4000
    kimi_thinking_enabled: bool = False
    kimi_runner_enabled: bool = False
    kimi_timeout_seconds: float = 90.0
    glm_api_key: str | None = None
    glm_base_url: str = "https://api.z.ai/api/paas/v4"
    glm_model: str = "glm-5.1"
    glm_max_tokens: int = 4000
    glm_thinking_enabled: bool = False
    glm_runner_enabled: bool = False
    glm_timeout_seconds: float = 90.0

    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    def model_post_init(self, __context) -> None:
        for name in ("data_dir", "sqlite_path", "rust_core_path"):
            path = getattr(self, name)
            if not path.is_absolute():
                setattr(self, name, REPO_ROOT / path)


@lru_cache
def get_settings() -> Settings:
    return Settings()
