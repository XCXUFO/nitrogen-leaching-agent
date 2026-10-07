from fastapi import FastAPI
from fastapi.testclient import TestClient

from src import __version__
from src.api import health
from src.main import app

client = TestClient(app)


def test_health_endpoint_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "nitrogen-leaching-agent-backend"
    assert body["version"] == __version__


def test_ready_rejects_unavailable_configured_knowledge_service(monkeypatch):
    isolated = FastAPI()
    isolated.include_router(health.router, prefix="/api")
    isolated.state.chat_service = None
    monkeypatch.setattr(health.settings, "rag_enabled", True)
    with TestClient(isolated) as candidate:
        assert candidate.get("/api/health").status_code == 200
        response = candidate.get("/api/ready")
        assert response.status_code == 503
        assert response.json() == {"status": "not_ready", "reason": "knowledge_unavailable"}
        isolated.state.chat_service = object()
        assert candidate.get("/api/ready").json() == {"status": "ready"}
