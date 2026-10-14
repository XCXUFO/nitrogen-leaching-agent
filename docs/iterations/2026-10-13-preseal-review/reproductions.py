"""Review reproductions: assertions document current defects, not acceptance."""
import os
os.environ.update(DEEPSEEK_API_KEY="review-placeholder", AGENT_TRACE_DB=":memory:",
                  RAG_ENABLED="false", EVAL_ENABLED="false", PUBLIC_DEMO_ENABLED="false")

from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from src.api import chat, files
from src.agent.runtime import AgentRuntime
from src.agent.chat_service import ChatService
from tests.test_session_documents import EmptyRetriever, RecordingLLM
from tests.test_whcns_results import make_nitrogen

@pytest.fixture
def client():
    app = FastAPI()
    app.state.chat_service = ChatService(EmptyRetriever(), RecordingLLM(), top_k=5, max_context_chars=4000, temperature=0)
    app.state.agent_runtime = AgentRuntime()
    app.include_router(chat.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    with TestClient(app) as c:
        yield c
    app.state.agent_runtime.runs.close()

def test_named_workbook_with_space_cannot_be_selected(client, tmp_path):
    name = "trial A.xlsx"
    raw = make_nitrogen(tmp_path / name).read_bytes()
    token = client.post("/api/files", params={"filename": name, "session_id": "s"}, content=raw).json()["file_id"]
    generic = client.post("/api/chat", json={"query": "硝态氮最大值", "session_id": "s", "file_ids": [token]}).json()
    named = client.post("/api/chat", json={"query": name + " 硝态氮最大值", "session_id": "s", "file_ids": [token]}).json()
    assert generic["file_evidence"][0]["value"] == 1.5
    assert named["file_evidence"] == []
    assert "未找到可用的文件：A.xlsx" in named["answer"]
    print("SPACE_FILENAME:", named["answer"])

def test_omitted_files_reuses_previously_sent_capabilities(client, tmp_path):
    token = client.post("/api/files", params={"filename": "Nbal_out.xlsx", "session_id": "s"},
                        content=make_nitrogen(tmp_path / "n.xlsx").read_bytes()).json()["file_id"]
    first = client.post("/api/chat", json={"query": "硝态氮最大值", "session_id": "s", "file_ids": [token]}).json()
    second = client.post("/api/chat", json={"query": "那最小值呢？", "session_id": "s"}).json()
    assert first["file_evidence"] and second["file_evidence"]
    print("OMITTED_FILES:", second["route"], second["file_evidence"][0]["value"])

def test_real_lifespan_disables_document_qa_without_rag(monkeypatch):
    import src.main as main
    llm = RecordingLLM()
    monkeypatch.setattr(main, "DeepSeekClient", lambda **kwargs: llm)
    monkeypatch.setattr(main.settings, "deepseek_proxy", None)
    with TestClient(main.app) as c:
        receipt = c.post("/api/files", params={"filename": "evidence.txt", "session_id": "s"}, content="硝态氮淋失值得关注。".encode()).json()
        response = c.post("/api/chat", json={"query": "这份文件主要说什么？", "session_id": "s", "file_ids": [receipt["file_id"]]})
        assert receipt["status"] == "ready"
        assert response.status_code == 503
        assert response.json()["detail"]["code"] == "rag_not_configured"
        assert not llm.messages
        print("DOCUMENT_QA_WITHOUT_RAG:", response.status_code, response.json()["detail"]["code"])

def test_readiness_accepts_empty_index_and_missing_model(monkeypatch, tmp_path):
    import src.main as main
    monkeypatch.setattr(main.settings, "rag_enabled", True)
    monkeypatch.setattr(main.settings, "rag_reranker_enabled", False)
    monkeypatch.setattr(main.settings, "rag_chroma_dir", str(tmp_path / "missing-index"))
    monkeypatch.setattr(main.settings, "embedding_model", str(tmp_path / "missing-model"))
    monkeypatch.setattr(main, "DeepSeekClient", lambda **kwargs: RecordingLLM())
    def missing_model(self):
        raise FileNotFoundError("isolated missing model")
    monkeypatch.setattr(main.BGEEmbedder, "_ensure_loaded", missing_model)
    with TestClient(main.app) as c:
        assert main.app.state.chat_service._retriever._store.count() == 0
        ready = c.get("/api/ready")
        failed = c.post("/api/chat", json={"query": "土壤质地影响氮素迁移吗？"})
        assert ready.status_code == 200
        assert failed.status_code == 503
        print("FALSE_READINESS:", ready.json(), failed.json()["detail"]["code"])

def test_public_response_conversation_id_cannot_be_reused(tmp_path):
    from types import SimpleNamespace
    from src.operations.public_access import PublicAccess, public_access
    app = FastAPI()
    app.state.public_settings = SimpleNamespace(public_demo_enabled=True, public_cookie_secure=False,
        public_budget_db=":memory:", public_requests_per_minute=100, public_daily_chat_limit=100,
        public_max_concurrent=5, cors_origin_list=["http://testserver"])
    app.state.public_access = PublicAccess(app.state.public_settings)
    app.state.agent_runtime = AgentRuntime()
    for router in (chat.router, files.router): app.include_router(router, prefix="/api")
    app.middleware("http")(public_access)
    with TestClient(app) as c:
        token = c.post("/api/files", params={"filename": "Nbal_out.xlsx"},
                       content=make_nitrogen(tmp_path / "n.xlsx").read_bytes()).json()["file_id"]
        first = c.post("/api/chat", json={"query": "硝态氮最大值", "file_id": token}).json()
        continued = c.post("/api/chat", json={"query": "那最小值呢？", "file_id": token,
                                               "session_id": first["conversation_id"]}).json()
        assert first["file_evidence"]
        assert continued["file_evidence"] == []
        assert first["conversation_id"] != continued["conversation_id"]
        print("PUBLIC_RETURNED_SESSION:", continued["route"], "conversation id changed")
    app.state.agent_runtime.runs.close()
    app.state.public_access.db.close()
