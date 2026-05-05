from pathlib import Path

from pydantic import field_validator
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
    deepseek_model: str = "deepseek-chat"

    embedding_model: str = "BAAI/bge-large-zh-v1.5"

    database_url: str = "sqlite:///./data/app.db"
    chroma_persist_dir: str = "./data/chroma"

    rag_enabled: bool = False
    rag_chroma_dir: str | None = None
    rag_collection: str = "papers"

    chat_top_k: int = 5
    chat_max_context_chars: int = 4000
    chat_temperature: float = 0.3

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
