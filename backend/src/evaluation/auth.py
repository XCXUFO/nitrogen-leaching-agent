from __future__ import annotations

import hashlib
import hmac
from pathlib import Path
import secrets
from threading import Lock
import time

from fastapi import HTTPException, Request

from src.evaluation.contracts import AccessFile, LoginInput, Principal

SESSION_SECONDS = 8 * 60 * 60
LOGIN_WINDOW_SECONDS = 5 * 60
LOGIN_ATTEMPTS = 10
_state_lock = Lock()


def password_hash(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=32768,
                            r=8, p=1, dklen=32, maxmem=128 * 1024 * 1024).hex()
    return f"scrypt${salt}${digest}"


# Unknown accounts perform the same password work as known accounts.
_DUMMY_HASH = password_hash(secrets.token_urlsafe(32))


def verify_password(password: str, encoded: str) -> bool:
    _, salt, _ = encoded.split("$")
    return hmac.compare_digest(password_hash(password, salt), encoded)


class LoginSessions:
    """Bounded, process-local sessions for the single-worker workbench deployment."""

    def __init__(self):
        self.lock = Lock()
        self.sessions: dict[str, tuple[str, str, float]] = {}
        self.attempts: dict[str, tuple[int, float]] = {}

    def throttle(self, username: str, address: str):
        now = time.monotonic()
        with self.lock:
            self.attempts = {key: value for key, value in self.attempts.items() if value[1] > now}
            # Rate limit both account and remote peer; never trust forwarded headers.
            keys = (f"user:{username}", f"ip:{address}")
            limits = (LOGIN_ATTEMPTS, LOGIN_ATTEMPTS * 6)
            if len(self.attempts) >= 10000 or any(self.attempts.get(key, (0, 0))[0] >= limit for key, limit in zip(keys, limits)):
                raise HTTPException(429, detail={"code": "login_rate_limited", "message": "登录尝试过于频繁，请 5 分钟后重试。"}, headers={"Retry-After": "300"})
            for key in keys:
                count, expiry = self.attempts.get(key, (0, now + LOGIN_WINDOW_SECONDS))
                self.attempts[key] = (count + 1, expiry)

    def issue(self, username: str, encoded: str) -> str:
        token = secrets.token_urlsafe(36)
        with self.lock:
            now = time.monotonic()
            self.sessions = {key: value for key, value in self.sessions.items() if value[2] > now}
            if len(self.sessions) >= 10000:
                raise HTTPException(503, detail={"code": "session_capacity", "message": "登录人数过多，请稍后重试。"})
            self.sessions[hashlib.sha256(token.encode()).hexdigest()] = (username, encoded, now + SESSION_SECONDS)
        return token

    def resolve(self, fingerprint: str, access: AccessFile) -> Principal | None:
        with self.lock:
            session = self.sessions.get(fingerprint)
            if not session:
                return None
            username, encoded, expires = session
            user = next((u for u in access.users if u.username == username and u.password_hash == encoded), None)
            if expires <= time.monotonic() or user is None:
                self.sessions.pop(fingerprint, None)
                return None
            self.sessions[fingerprint] = (username, encoded, time.monotonic() + SESSION_SECONDS)
            return Principal(tester_id=user.tester_id, role=user.role)

    def revoke(self, token: str):
        with self.lock:
            self.sessions.pop(hashlib.sha256(token.encode()).hexdigest(), None)


def sessions(request: Request) -> LoginSessions:
    with _state_lock:
        if not hasattr(request.app.state, "eval_sessions"):
            request.app.state.eval_sessions = LoginSessions()
        return request.app.state.eval_sessions


def load_access(path: str) -> AccessFile:
    return AccessFile.model_validate_json(Path(path).read_text(encoding="utf-8"))


def access_file(request: Request) -> AccessFile:
    access = getattr(request.app.state, "eval_access", None)
    if access is None:
        raise HTTPException(404, detail={"code": "evaluation_disabled", "message": "评测后台尚未启用。"})
    return access


def login(request: Request, body: LoginInput) -> dict:
    access = access_file(request)
    username = body.username.strip()
    state = sessions(request)
    state.throttle(username, request.client.host if request.client else "unknown")
    user = next((u for u in access.users if u.username == username), None)
    valid = verify_password(body.password, user.password_hash if user and user.password_hash else _DUMMY_HASH)
    if not valid or user is None or not user.password_hash:
        raise HTTPException(401, detail={"code": "login_failed", "message": "账号或密码错误。"})
    return {"token": state.issue(username, user.password_hash), "expires_in": SESSION_SECONDS,
            "user": Principal(tester_id=user.tester_id, role=user.role)}


def current_user(request: Request) -> Principal:
    access = access_file(request)
    kind, _, token = request.headers.get("authorization", "").partition(" ")
    if kind.lower() != "bearer" or not 32 <= len(token) <= 256:
        raise HTTPException(401, detail={"code": "evaluation_unauthorized", "message": "请先使用账号和密码登录。"})
    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    user = sessions(request).resolve(fingerprint, access)
    if user:
        return user
    # Compatibility for unmigrated installations and isolated legacy fixtures.
    # Migrating an account removes its old token hash, disabling key login.
    for entry in access.users:
        if entry.token_sha256 and hmac.compare_digest(fingerprint, entry.token_sha256):
            return Principal(tester_id=entry.tester_id, role=entry.role)
    raise HTTPException(401, detail={"code": "evaluation_unauthorized", "message": "登录已失效，请重新登录。"})


def require_developer(user: Principal) -> None:
    if user.role != "developer":
        raise HTTPException(403, detail={"code": "evaluation_forbidden", "message": "此功能仅供开发者使用。"})


def front_principal(request: Request) -> Principal | None:
    # Workbench execution endpoints already assign identity and conversation IDs.
    if request.url.path.startswith("/api/eval/") or not request.headers.get("authorization"):
        return None
    return current_user(request)


def front_owner(request: Request) -> str | None:
    user = front_principal(request)
    return "internal_" + user.tester_id if user else getattr(request.state, "public_visitor", None)
