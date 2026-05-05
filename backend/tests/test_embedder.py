import sys
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.rag import BGEEmbedder, Embedder
from src.rag.base import Embedder as EmbedderBase


class FakeEmbedder(EmbedderBase):
    _DIM = 4

    @property
    def dim(self) -> int:
        return self._DIM

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [[0.1, 0.2, 0.3, 0.4] for _ in texts]

    def embed_query(self, text: str) -> list[float]:
        return [0.1, 0.2, 0.3, 0.4]


def test_embedder_abc_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        Embedder()  # type: ignore[abstract]


def test_bge_embedder_constructor_does_not_load_model() -> None:
    embedder = BGEEmbedder()
    assert embedder._model is None


def test_bge_embedder_dim_is_1024_without_model_load() -> None:
    embedder = BGEEmbedder()
    assert embedder.dim == 1024
    assert embedder._model is None  # accessing dim must not trigger load


def test_bge_embedder_lazy_loads_on_first_embed(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_model = MagicMock()
    encoded = MagicMock()
    encoded.tolist.return_value = [[0.0] * 1024]
    fake_model.encode.return_value = encoded

    factory = MagicMock(return_value=fake_model)
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=factory),
    )

    embedder = BGEEmbedder()
    assert factory.call_count == 0  # constructor still inert

    embedder.embed_documents(["hello"])
    assert factory.call_count == 1

    embedder.embed_documents(["world"])
    assert factory.call_count == 1  # cached on second call

    call_kwargs = fake_model.encode.call_args.kwargs
    assert call_kwargs.get("normalize_embeddings") is True


def test_bge_embedder_embed_query_returns_list_of_float(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_model = MagicMock()
    encoded = MagicMock()
    encoded.__getitem__.return_value.tolist.return_value = [0.5] * 1024
    fake_model.encode.return_value = encoded
    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=lambda *_, **__: fake_model),
    )

    embedder = BGEEmbedder()
    vector = embedder.embed_query("稻田氮素淋失")
    assert len(vector) == 1024
    assert vector[0] == 0.5


def test_bge_embedder_raises_helpful_error_when_optional_dependency_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delitem(sys.modules, "sentence_transformers", raising=False)

    real_import = __import__

    def fake_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "sentence_transformers":
            raise ImportError("missing optional dependency")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr("builtins.__import__", fake_import)

    with pytest.raises(RuntimeError, match="uv sync --extra rag"):
        BGEEmbedder().embed_query("稻田氮素淋失")


def test_fake_embedder_round_trip() -> None:
    fake = FakeEmbedder()
    assert fake.dim == 4
    assert fake.embed_query("x") == [0.1, 0.2, 0.3, 0.4]
    docs = fake.embed_documents(["a", "b", "c"])
    assert len(docs) == 3
    assert all(len(v) == fake.dim for v in docs)
