"""End-to-end smoke for the M1.2 sub-link: ingest -> chunk -> store -> query.

Uses FakeEmbedder (deterministic vectors keyed off chunk text hash) so the
test runs without sentence-transformers / torch / model weights. The real
BGE chain is covered by tests/test_rag_live.py under RUN_LIVE_RAG=1.
"""
from __future__ import annotations

import hashlib
import importlib.util
import math
from pathlib import Path

import pytest

from src.rag import Chunk, chunk_text, load_text
from src.rag.base import Embedder
from src.rag.retriever import Retriever

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("chromadb") is None,
    reason="chromadb optional dependency missing; run `uv sync --extra rag` to enable",
)

from src.storage.chroma_store import ChromaStore  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE = _REPO_ROOT / "data" / "papers" / "sample.txt"


class HashEmbedder(Embedder):
    """Hash-derived deterministic embedder for offline pipeline testing."""

    _DIM = 16

    @property
    def dim(self) -> int:
        return self._DIM

    def _vec(self, text: str) -> list[float]:
        h = hashlib.sha256(text.encode("utf-8")).digest()
        # 16 dims, each from one byte mapped to [-1, 1)
        raw = [(b / 127.5) - 1.0 for b in h[: self._DIM]]
        norm = math.sqrt(sum(x * x for x in raw)) or 1.0
        return [x / norm for x in raw]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._vec(t) for t in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vec(text)


def test_pipeline_ingest_chunk_store_query(tmp_path: Path) -> None:
    """ingest sample.txt -> chunker -> ChromaStore.add; query roundtrips a known chunk."""
    text = load_text(_SAMPLE)
    assert "氮素淋失" in text, "sample.txt must contain the topic keyword"

    chunks: list[Chunk] = chunk_text(
        text,
        document_id="data/papers/sample",
        source=str(_SAMPLE),
    )
    assert len(chunks) > 0

    embedder = HashEmbedder()
    store = ChromaStore(tmp_path / "chroma", "smoke")
    store.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=embedder.embed_documents([c.text for c in chunks]),
        metadatas=[c.metadata for c in chunks],
    )
    assert store.count() == len(chunks)

    # Query with the exact text of the first chunk; HashEmbedder is
    # deterministic so the same text vector → distance 0 → top hit.
    target = chunks[0]
    retriever = Retriever(embedder, store)
    results = retriever.retrieve(target.text, k=1)
    assert len(results) == 1
    assert results[0].chunk_id == target.chunk_id
    assert results[0].document == target.text


def test_pipeline_is_idempotent_on_repeat(tmp_path: Path) -> None:
    """Running the same ingest+chunk+upsert pipeline twice must not duplicate
    chunks or raise. Mirrors the indexer's ``store.upsert`` path; if the
    script regresses to ``store.add``, this test will catch it."""
    text = load_text(_SAMPLE)
    chunks = chunk_text(text, document_id="data/papers/sample", source=str(_SAMPLE))
    embedder = HashEmbedder()
    store = ChromaStore(tmp_path / "chroma", "smoke-idempotent")

    def _push() -> None:
        store.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=embedder.embed_documents([c.text for c in chunks]),
            metadatas=[c.metadata for c in chunks],
        )

    _push()
    first_count = store.count()
    _push()
    assert store.count() == first_count


def test_pipeline_chunk_metadata_lands_in_store(tmp_path: Path) -> None:
    """Reserved metadata fields written by chunker survive the round-trip."""
    text = load_text(_SAMPLE)
    chunks = chunk_text(
        text,
        document_id="data/papers/sample",
        source=str(_SAMPLE),
        base_metadata={"title": "WHCNS sample", "year": 2024},
    )
    assert len(chunks) > 0

    embedder = HashEmbedder()
    store = ChromaStore(tmp_path / "chroma", "smoke-meta")
    store.upsert(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=embedder.embed_documents([c.text for c in chunks]),
        metadatas=[c.metadata for c in chunks],
    )

    retriever = Retriever(embedder, store)
    results = retriever.retrieve(chunks[0].text, k=1)
    meta = results[0].metadata

    # Reserved fields written by chunker
    assert meta["source"] == str(_SAMPLE)
    assert meta["document_id"] == "data/papers/sample"
    assert meta["chunk_index"] == 0
    assert isinstance(meta["char_start"], int)
    assert isinstance(meta["char_end"], int)
    # base_metadata pass-through
    assert meta["title"] == "WHCNS sample"
    assert meta["year"] == 2024
