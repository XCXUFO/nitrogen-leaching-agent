from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ENV_FILE,
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_env: str = "development"
    log_level: str = "INFO"

    cors_origins: str = "http://localhost:3000"

    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_proxy: str | None = None
    deepseek_model: str = "deepseek-v4-flash"
    # M1.5-a demo hardening: 有界超时 + 显式有界重试，替代 SDK 默认（timeout=600s）。
    # 这是策略默认值，可被 .env 覆盖；后续 A 档延迟变化时只改这里，不牵动测试。
    deepseek_timeout_s: float = 60.0
    deepseek_max_retries: int = 2

    embedding_model: str = "data/models/bge-large-zh-v1.5"

    database_url: str = "sqlite:///./data/app.db"
    chroma_persist_dir: str = "./data/chroma"

    rag_enabled: bool = False
    rag_chroma_dir: str | None = None
    rag_collection: str = "papers"

    chat_top_k: int = 5
    chat_max_context_chars: int = 4000
    chat_temperature: float = 0.3

    agent_trace_db: str = str(BASE_DIR / "var/agent/runs.sqlite3")
    agent_build_version: str = "local-unversioned"

    eval_enabled: bool = False
    eval_access_file: str = str(BASE_DIR / "var/eval/access-keys.json")

    public_demo_enabled: bool = False
    public_cookie_secure: bool = True
    public_requests_per_minute: int = Field(default=12, ge=1, le=120)
    public_daily_chat_limit: int = Field(default=300, ge=1)
    public_max_concurrent: int = Field(default=5, ge=1, le=16)
    public_max_output_tokens: int = Field(default=2048, ge=128, le=8192)
    public_budget_db: str = str(BASE_DIR / "var/demo/budget.sqlite3")

    @field_validator("agent_trace_db", "eval_access_file", "public_budget_db", mode="before")
    @classmethod
    def normalize_agent_trace_db(cls, value: str) -> str:
        if value == ":memory:":
            return value
        path = Path(value)
        return str(path if path.is_absolute() else (BASE_DIR / path).resolve())

    rag_reranker_enabled: bool = False
    rag_reranker_top_k_recall: int = 20
    rag_reranker_top_n: int = 5
    rag_reranker_model: str = "data/models/bge-reranker-v2-m3"

    # M1.5-a demo default = M1.4-c 验证过的 A2 配置（recall20 / top_n5 /
    # ref-filter on / overfetch10）：A2 是全矩阵唯一让 q04 evidence-level 翻盘的
    # 配置。这是 demo 默认而非最终最优检索策略；M1.5-b 解 q08 后可覆盖。
    rag_reference_filter_enabled: bool = True
    rag_reference_filter_min_keep: int = 1
    rag_reference_filter_overfetch: int = 10

    # M1.5-b: numeric/evidence boost — reranker post-processing that lifts
    # numeric/statistical data chunks the cross-encoder underweights (solves q08
    # 026::0172 R²/RMSE/IA). Only active on the RAG + reranker path; does not
    # change RAG_ENABLED / RAG_RERANKER_ENABLED opt-in semantics. Defaults are
    # the DoD-2-validated weight/band (see src/rag/numeric_boost.py
    # DEFAULT_NUMERIC_BOOST_WEIGHT / _BAND); under these only q08's top_n changes
    # vs boost-off, the other nine mini-eval questions are byte-identical.
    rag_numeric_boost_enabled: bool = True
    rag_numeric_boost_weight: float = 0.445
    rag_numeric_boost_band: float = 0.30

    @field_validator("database_url", mode="before")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        sqlite_prefix = "sqlite:///"
        if not value.startswith(sqlite_prefix):
            return value

        raw_path = value[len(sqlite_prefix) :]
        if raw_path == ":memory:":
            return value

        db_path = Path(raw_path)
        if db_path.is_absolute():
            return value

        return f"{sqlite_prefix}{(BASE_DIR / db_path).resolve()}"

    @field_validator("chroma_persist_dir", mode="before")
    @classmethod
    def normalize_chroma_persist_dir(cls, value: str) -> str:
        chroma_path = Path(value)
        if chroma_path.is_absolute():
            return str(chroma_path)

        return str((BASE_DIR / chroma_path).resolve())

    @field_validator("rag_chroma_dir", mode="before")
    @classmethod
    def normalize_rag_chroma_dir(cls, value: str | None) -> str | None:
        if value in (None, ""):
            return None

        chroma_path = Path(value)
        if chroma_path.is_absolute():
            return str(chroma_path)

        return str((BASE_DIR / chroma_path).resolve())

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
