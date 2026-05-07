"""Live integration smoke for BGE + ChromaStore over real sample.txt.

Gated behind ``RUN_LIVE_RAG=1`` to avoid downloading ~1.3GB of model weights
in default test runs. See M1.2.3 spec §5.4.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.skipif(
        not os.getenv("RUN_LIVE_RAG"),
        reason="set RUN_LIVE_RAG=1 to run real BGE + Chroma end-to-end",
    ),
    pytest.mark.skipif(
        importlib.util.find_spec("chromadb") is None
        or importlib.util.find_spec("sentence_transformers") is None,
        reason="rag extras missing; run `uv sync --extra rag` to enable",
    ),
]

# Late imports — only safe once skipif gates above pass
from src.config import settings  # noqa: E402
from src.rag import BGEEmbedder, chunk_text, load_text  # noqa: E402
from src.rag.retriever import Retriever  # noqa: E402
from src.storage import ChromaStore  # noqa: E402

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SAMPLE = _REPO_ROOT / "data" / "papers" / "sample.txt"


def test_live_index_and_retrieve_sample(tmp_path: Path) -> None:
    text = load_text(_SAMPLE)
    chunks = chunk_text(text, document_id="data/papers/sample", source=str(_SAMPLE))
    assert len(chunks) > 0

    embedder = BGEEmbedder(model_id=settings.embedding_model)
    store = ChromaStore(tmp_path / "chroma", "live-rag")
    store.add(
        ids=[c.chunk_id for c in chunks],
        documents=[c.text for c in chunks],
        embeddings=embedder.embed_documents([c.text for c in chunks]),
        metadatas=[c.metadata for c in chunks],
    )

    retriever = Retriever(embedder, store)
    results = retriever.retrieve("农田氮素淋失风险", k=3)
    assert len(results) > 0
    # Top hit should mention nitrogen-related vocabulary; we keep the
    # assertion loose because BGE's nearest neighbour may not be the only
    # passage that contains the exact phrase.
    joined = "".join(r.document for r in results)
    assert any(token in joined for token in ("氮", "淋失", "硝态氮", "WHCNS"))
