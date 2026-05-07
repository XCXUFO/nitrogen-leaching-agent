from src.config import BASE_DIR, Settings


def test_settings_normalize_relative_storage_paths():
    settings = Settings(
        database_url="sqlite:///./data/app.db",
        chroma_persist_dir="./data/chroma",
    )

    assert settings.database_url == f"sqlite:///{(BASE_DIR / 'data/app.db').resolve()}"
    assert settings.chroma_persist_dir == str((BASE_DIR / "data/chroma").resolve())


def test_settings_preserve_sqlite_memory_url():
    settings = Settings(database_url="sqlite:///:memory:")

    assert settings.database_url == "sqlite:///:memory:"


def test_settings_preserve_absolute_and_non_sqlite_paths():
    settings = Settings(
        database_url="postgresql://user:pass@localhost:5432/app",
        chroma_persist_dir="/tmp/chroma",
        rag_chroma_dir="/tmp/rag-chroma",
    )

    assert settings.database_url == "postgresql://user:pass@localhost:5432/app"
    assert settings.chroma_persist_dir == "/tmp/chroma"
    assert settings.rag_chroma_dir == "/tmp/rag-chroma"


def test_settings_normalize_optional_rag_chroma_dir():
    default_settings = Settings(rag_chroma_dir=None)
    explicit_empty_settings = Settings(rag_chroma_dir="")
    relative_settings = Settings(rag_chroma_dir="./var/chroma")

    assert default_settings.rag_chroma_dir is None
    assert explicit_empty_settings.rag_chroma_dir is None
    assert relative_settings.rag_chroma_dir == str((BASE_DIR / "var/chroma").resolve())


def test_settings_chat_rag_defaults():
    settings = Settings(_env_file=None)

    assert settings.rag_enabled is False
    assert settings.rag_collection == "papers"
    assert settings.chat_top_k == 5
    assert settings.chat_max_context_chars == 4000
    assert settings.chat_temperature == 0.3
