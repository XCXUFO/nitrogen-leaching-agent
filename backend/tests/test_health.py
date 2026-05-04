from fastapi.testclient import TestClient

from src import __version__
from src.main import app

client = TestClient(app)


def test_health_endpoint_returns_ok():
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "nitrogen-leaching-agent-backend"
    assert body["version"] == __version__
