from __future__ import annotations

from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.api import evaluation
from src.evaluation.auth import LOGIN_ATTEMPTS, load_access, password_hash
from src.evaluation.contracts import AccessFile


@pytest.fixture
def account_client():
    app = FastAPI()
    app.state.eval_access = AccessFile(users=[
        {"tester_id": name, "username": f"cau_{name}", "role": role, "password_hash": password_hash(f"Cau{name}123")}
        for name, role in (("dev", "developer"), ("expert", "reviewer"), ("test", "tester"))
    ])
    app.include_router(evaluation.router, prefix="/api")
    with TestClient(app) as client:
        yield client


def login(client, name="test", **extra):
    return client.post("/api/eval/login", json={"username": f"cau_{name}", "password": f"Cau{name}123", **extra})


def test_account_roles_logout_and_no_registration(account_client):
    for name, role in (("dev", "developer"), ("expert", "reviewer"), ("test", "tester")):
        response = login(account_client, name)
        assert response.status_code == 200
        body = response.json()
        assert body["user"]["role"] == role
        assert "password" not in response.text and "scrypt" not in response.text
        headers = {"Authorization": f'Bearer {body["token"]}'}
        assert account_client.get("/api/eval/me", headers=headers).json() == {"tester_id": name, "role": role}
        assert account_client.post("/api/eval/logout", headers=headers).status_code == 204
        assert account_client.get("/api/eval/me", headers=headers).status_code == 401
    assert account_client.post("/api/eval/register", json={}).status_code == 404
    assert login(account_client, role="developer").status_code == 422
    assert login(account_client, tester_id="dev").status_code == 422


def test_bad_credentials_throttle_and_disabled_workbench(account_client):
    missing = login(account_client, username="missing").json()
    wrong = login(account_client, password="wrong")
    assert wrong.status_code == 401 and wrong.json() == missing
    for _ in range(LOGIN_ATTEMPTS - 1):
        assert login(account_client, password="wrong").status_code == 401
    assert login(account_client).status_code == 429
    account_client.app.state.eval_access = None
    assert login(account_client).status_code == 404


def test_expiry_password_change_and_restart_revoke_session(account_client):
    token = login(account_client).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    sessions = account_client.app.state.eval_sessions
    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    username, encoded, _ = sessions.sessions[fingerprint]
    sessions.sessions[fingerprint] = (username, encoded, 0)
    assert account_client.get("/api/eval/me", headers=headers).status_code == 401
    token = login(account_client).json()["token"]
    headers = {"Authorization": f"Bearer {token}"}
    account_client.app.state.eval_access.users[-1].password_hash = password_hash("Changed123")
    assert account_client.get("/api/eval/me", headers=headers).status_code == 401
    token = login(account_client, password="Changed123").json()["token"]
    del account_client.app.state.eval_sessions
    assert account_client.get("/api/eval/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_password_login_preserves_permission_boundaries(account_client):
    tester = login(account_client).json()["token"]
    reviewer = login(account_client, "expert").json()["token"]
    for path in ("/review-queue", "/assets", "/reviewers", "/runs", "/regressions"):
        assert account_client.get(f"/api/eval{path}", headers={"Authorization": f"Bearer {tester}"}).status_code == 403
    for path in ("/reviewers", "/runs", "/regressions"):
        assert account_client.get(f"/api/eval{path}", headers={"Authorization": f"Bearer {reviewer}"}).status_code == 403


def test_provision_six_accounts_retains_owners_and_disables_old_keys(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts/create_eval_accounts.py"
    spec = importlib.util.spec_from_file_location("create_eval_accounts", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    previous = {"users": [{"tester_id": name, "role": role, "token_sha256": hashlib.sha256((name * 4).encode()).hexdigest()}
                          for name, role in (("local-developer", "developer"), ("local-tester", "tester"))]}
    path = tmp_path / "access-keys.json"
    path.write_text(json.dumps(previous))
    _, credentials = module.provision(tmp_path)
    access = load_access(str(path))
    assert Counter(u.role for u in access.users) == {"developer": 1, "reviewer": 2, "tester": 3}
    assert {u.username: u.tester_id for u in access.users}["cau_tester1"] == "local-tester"
    assert {u.username: u.tester_id for u in access.users}["cau_dev"] == "local-developer"
    assert all(not u.token_sha256 for u in access.users)
    assert path.stat().st_mode & 0o777 == 0o600
    assert credentials.stat().st_mode & 0o777 == 0o600
    assert json.loads(next(tmp_path.glob("access-keys.pre-accounts-*.json")).read_text()) == previous
    app = FastAPI()
    app.state.eval_access = access
    app.include_router(evaluation.router, prefix="/api")
    with TestClient(app) as client:
        for line in credentials.read_text().splitlines()[1:]:
            label, password = line.split(": ")
            assert client.post("/api/eval/login", json={"username": label.split()[0], "password": password}).status_code == 200
        for old_user in previous["users"]:
            assert client.get("/api/eval/me", headers={"Authorization": "Bearer " + old_user["tester_id"] * 4}).status_code == 401
    saved = path.read_bytes()
    with pytest.raises(ValueError, match="already exist"):
        module.provision(tmp_path)
    assert path.read_bytes() == saved


def test_hash_salt_and_duplicate_accounts():
    first, second = password_hash("CauTest123"), password_hash("CauTest123")
    assert first != second and "CauTest123" not in first
    with pytest.raises(ValueError):
        AccessFile(users=[{"tester_id": str(i), "role": "tester", "username": "cau", "password_hash": first} for i in range(2)])


def test_active_window_session_renews_instead_of_absolute_expiry(account_client, monkeypatch):
    from src.evaluation import auth
    now = [100.0]
    monkeypatch.setattr(auth.time, 'monotonic', lambda: now[0])
    token = login(account_client).json()['token']
    headers = {'Authorization': 'Bearer ' + token}
    for _ in range(3):
        now[0] += auth.SESSION_SECONDS - 1
        assert account_client.get('/api/eval/me', headers=headers).status_code == 200
    now[0] += auth.SESSION_SECONDS + 1
    assert account_client.get('/api/eval/me', headers=headers).status_code == 401
