import hashlib
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent.runtime import AgentRuntime
from src.api import chat, demo, evaluation, files
from src.evaluation.contracts import AccessFile
from src.operations.public_access import PublicAccess, public_access
from src.storage.run_store import RunStore


@pytest.fixture
def app(tmp_path):
    app = FastAPI()
    app.state.public_settings = SimpleNamespace(public_demo_enabled=True, public_cookie_secure=False,
        public_budget_db=str(tmp_path / "budget.sqlite3"), public_requests_per_minute=100,
        public_daily_chat_limit=100, public_max_concurrent=2, cors_origin_list=["http://testserver"])
    app.state.public_access = PublicAccess(app.state.public_settings)
    app.state.eval_access = AccessFile(users=[{"tester_id": "private-admin", "role": "developer",
        "token_sha256": hashlib.sha256(b"d" * 40).hexdigest()}])
    store = RunStore(tmp_path / "private.sqlite3")
    app.state.agent_runtime = AgentRuntime(runs=store)
    app.state.chat_service = None
    for router in (chat.router, files.router, demo.router, evaluation.router):
        app.include_router(router, prefix="/api")
    app.middleware("http")(public_access)
    yield app
    store.close()
    app.state.public_access.db.close()


def test_public_archive_is_read_only_and_does_not_expose_live_records(app):
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"query": "PRIVATE_VISITOR_SENTINEL", "session_id": "private"}).status_code == 503
        response = client.get("/api/demo/catalog")
        assert response.status_code == 200
        assert len(response.json()["cases"]) == 5
        for forbidden in ("PRIVATE_VISITOR_SENTINEL", "private-admin", "token_sha256", "/root/", "conversation_ref", "file_id"):
            assert forbidden not in response.text
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            assert client.request(method, "/api/demo/catalog", json={}).status_code == 405
        assert client.get("/api/demo/catalog/private").status_code == 404


def test_all_management_routes_require_real_credentials(app):
    with TestClient(app) as client:
        # Includes every current management mutation and read, not just UI buttons.
        for route in app.routes:
            if not getattr(route, "path", "").startswith("/api/eval"):
                continue
            import re
            path = re.sub(r"\{[^}]+\}", "unpublished-private-record", route.path)
            for method in route.methods:
                response = client.request(method, path, json={}, headers={"Authorization": "Bearer public-viewer"})
                assert response.status_code == 401, (method, path, response.text)


def test_real_example_upload_followup_and_cross_visitor_isolation(app):
    with TestClient(app) as alice, TestClient(app) as bob:
        raw = alice.get("/api/demo/examples/nitrogen").content
        fixture = alice.post("/api/files?filename=Nbal_out.xls", content=raw).json()
        question = {"query": "硝态氮淋失最大值及对应日序", "file_id": fixture["file_id"], "session_id": "same-client-id"}
        answer = alice.post("/api/chat", json=question)
        assert answer.status_code == 200, answer.text
        assert answer.json()["file_evidence"][0]["model_day"] == 283
        assert "HttpOnly" in answer.headers["set-cookie"]
        followup = alice.post("/api/chat", json=question | {"query": "那最小值呢？"})
        assert followup.json()["file_evidence"][0]["value"] == 0
        assert bob.post("/api/chat", json=question).status_code == 404
        status = {'file_ids': [fixture['file_id']]}
        assert alice.post('/api/files/status', json=status).json()['files'][0]['status'] == 'available'
        assert bob.post('/api/files/status', json=status).json()['files'][0]['status'] == 'expired'
        assert alice.post('/api/files/status', json=status, headers={'Origin': 'https://untrusted.example'}).status_code == 403
        own = bob.post("/api/chat", json={"query": "那最小值呢？", "session_id": "same-client-id"})
        assert own.status_code == 200
        assert own.json()["file_evidence"] == []
        assert "上传" in own.json()["answer"]
        removed = alice.post("/api/chat", json={"query": "那最小值呢？", "session_id": "same-client-id"})
        assert removed.json()["file_evidence"] == []


def test_limits_origin_size_and_forged_cookie(app):
    with TestClient(app) as client:
        assert client.post("/api/chat", json={"query": "你能做什么？"}, headers={"Origin": "https://untrusted.example"}).status_code == 403
        assert client.post("/api/chat", content=b"x" * 100001).status_code == 413
        app.state.public_settings.public_daily_chat_limit = 1
        assert client.post("/api/chat", json={"query": "你能做什么？"}).status_code == 200
        limited = client.post("/api/chat", json={"query": "你能做什么？"})
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == "60"
        assert app.state.public_access.active == 0
    guard = app.state.public_access
    identity, token = guard.visitor(None)
    assert guard.visitor(token)[0] == identity
    assert guard.visitor(identity + ".forged")[0] != identity
    guard2 = PublicAccess(app.state.public_settings)
    assert guard2.visitor(token)[0] == identity
    assert "今日" in guard2.reserve("another-ip", True)
    guard2.db.close()


def test_concurrency_and_rate_limit(app):
    guard = app.state.public_access
    assert guard.reserve("one", False) is None
    assert guard.reserve("two", False) is None
    assert "人数" in guard.reserve("three", False)
    guard.active = 0
    app.state.public_settings.public_requests_per_minute = 1
    assert "频繁" in guard.reserve("one", False)


def test_published_example_matches_advertised_fingerprint(app):
    with TestClient(app) as client:
        asset = client.get("/api/demo/catalog").json()["assets"][0]
        raw = client.get("/api/demo/examples/nitrogen").content
        assert hashlib.sha256(raw).hexdigest() == asset["sha256"]
