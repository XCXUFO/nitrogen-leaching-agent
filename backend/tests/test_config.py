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
    )

    assert settings.database_url == "postgresql://user:pass@localhost:5432/app"
    assert settings.chroma_persist_dir == "/tmp/chroma"
