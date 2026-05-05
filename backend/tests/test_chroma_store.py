import importlib.util
from pathlib import Path

import pytest

from src.storage import ChromaStore

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("chromadb") is None,
    reason="chromadb optional dependency missing; run `uv sync --extra rag` to enable",
)


def test_persist_dir_is_created_when_missing(tmp_path: Path) -> None:
    target = tmp_path / "nested" / "chroma"
    assert not target.exists()
    ChromaStore(persist_dir=target, collection_name="t")
    assert target.is_dir()


def test_count_zero_on_fresh_collection(tmp_path: Path) -> None:
    store = ChromaStore(persist_dir=tmp_path, collection_name="t")
    assert store.count() == 0


def test_add_then_count_reflects_inserted_documents(tmp_path: Path) -> None:
    store = ChromaStore(persist_dir=tmp_path, collection_name="t")
    store.add(
        ids=["a", "b"],
        documents=["氮淋失风险评估", "土壤水分模拟"],
        embeddings=[[1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0]],
        metadatas=[{"src": "p1"}, {"src": "p2"}],
    )
    assert store.count() == 2


def test_query_returns_nearest_by_embedding(tmp_path: Path) -> None:
    store = ChromaStore(persist_dir=tmp_path, collection_name="t")
    store.add(
        ids=["x", "y", "z"],
        documents=["alpha", "beta", "gamma"],
        embeddings=[
            [1.0, 0.0, 0.0, 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [0.0, 0.0, 1.0, 0.0],
        ],
    )
    result = store.query(embedding=[0.0, 1.0, 0.0, 0.0], k=1)
    assert result["ids"][0] == ["y"]
    assert result["documents"][0] == ["beta"]


def test_query_on_empty_collection_returns_empty_lists(tmp_path: Path) -> None:
    store = ChromaStore(persist_dir=tmp_path, collection_name="t")
    result = store.query(embedding=[0.0, 0.0, 0.0, 0.0], k=3)
    assert result["ids"] == [[]]
    assert result["documents"] == [[]]


def test_upsert_replaces_existing_id(tmp_path: Path) -> None:
    """Re-indexing the same chunk_id must not duplicate or raise."""
    store = ChromaStore(persist_dir=tmp_path, collection_name="t")
    store.upsert(
        ids=["a"],
        documents=["first"],
        embeddings=[[1.0, 0.0, 0.0, 0.0]],
        metadatas=[{"v": 1}],
    )
    assert store.count() == 1

    store.upsert(
        ids=["a"],
        documents=["second"],
        embeddings=[[0.0, 1.0, 0.0, 0.0]],
        metadatas=[{"v": 2}],
    )
    assert store.count() == 1

    result = store.query(embedding=[0.0, 1.0, 0.0, 0.0], k=1)
    assert result["ids"][0] == ["a"]
    assert result["documents"][0] == ["second"]
    assert result["metadatas"][0][0]["v"] == 2


def test_add_raises_on_duplicate_id_documenting_why_we_use_upsert(
    tmp_path: Path,
) -> None:
    """Pin chromadb's contract: ``add`` is NOT idempotent. The indexer
    relies on ``upsert`` for re-runnability; this test guards against a
    silent chromadb behavior change in future versions."""
    store = ChromaStore(persist_dir=tmp_path, collection_name="t")
    store.add(
        ids=["a"],
        documents=["one"],
        embeddings=[[1.0, 0.0, 0.0, 0.0]],
    )
    with pytest.raises(Exception):
        store.add(
            ids=["a"],
            documents=["two"],
            embeddings=[[0.0, 1.0, 0.0, 0.0]],
        )
