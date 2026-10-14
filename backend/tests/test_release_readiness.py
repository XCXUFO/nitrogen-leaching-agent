"""Startup checks must exercise retrieval without making paid model calls."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from tests.test_session_documents import RecordingLLM


@pytest.mark.parametrize("failure", [None, "empty", "embedding", "index", "reranker"])
def test_real_lifespan_readiness_tracks_retrieval(monkeypatch, tmp_path, failure):
    import src.main as main

    for name, value in {
        "rag_enabled": True, "rag_reranker_enabled": True,
        "eval_enabled": False, "public_demo_enabled": False,
        "deepseek_api_key": "test-placeholder", "deepseek_proxy": None,
        "agent_trace_db": str(tmp_path / "runs.sqlite3"),
        "case_library_db": str(tmp_path / "cases.sqlite3"),
    }.items():
        monkeypatch.setattr(main.settings, name, value)
    monkeypatch.setattr(main, "build_manifest", lambda _: {"manifest_sha256": "test-manifest"})
    llm = RecordingLLM()
    monkeypatch.setattr(main, "DeepSeekClient", lambda **kwargs: llm)

    def embed(query):
        if failure == "embedding":
            raise FileNotFoundError("missing embedding weights")
        return [0.0, 1.0]

    def query(vector, k):
        if failure == "index":
            raise ValueError("index embedding dimension mismatch")
        return {"ids": [["test-chunk"]], "documents": [["农田氮淋失与土壤有关。"]],
                "distances": [[0.1]], "metadatas": [[{"source": "test.txt"}]]}

    def rerank(query, candidates):
        if failure == "reranker":
            raise FileNotFoundError("missing reranker weights")
        return candidates

    monkeypatch.setattr(main, "BGEEmbedder", lambda **kwargs: SimpleNamespace(embed_query=embed))
    monkeypatch.setattr(main, "ChromaStore", lambda *args: SimpleNamespace(
        count=lambda: 0 if failure == "empty" else 1, query=query))
    monkeypatch.setattr(main, "Reranker", lambda **kwargs: SimpleNamespace(rerank=rerank))
    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
        assert client.get("/api/ready").status_code == (503 if failure else 200)
        assert llm.messages == []
        if failure:
            response = client.post("/api/chat", json={"query": "土壤质地影响氮素迁移吗？"})
            assert response.status_code == 503
