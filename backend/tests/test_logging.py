from src.utils.logging import configure_logging


def test_configure_logging_uses_configured_level(monkeypatch):
    calls: dict[str, str | int] = {}

    def fake_remove() -> None:
        calls["removed"] = 1

    def fake_add(sink, level: str) -> None:
        calls["level"] = level

    monkeypatch.setattr("src.utils.logging.logger.remove", fake_remove)
    monkeypatch.setattr("src.utils.logging.logger.add", fake_add)

    configure_logging("debug")

    assert calls["removed"] == 1
    assert calls["level"] == "DEBUG"
