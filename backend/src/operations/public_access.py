"""Single-worker public demo limits and signed, HttpOnly visitor identities.

Budgets survive restarts in a separate SQLite file. IPs are hashed and proxy
headers are deliberately ignored; deploy behind a trusted, configured proxy.
"""
import hashlib
import json
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path

from starlette.responses import JSONResponse
from src.operations.visitor_identity import signed_visitor

COOKIE = "nitrogen_demo_visitor"


class PublicAccess:
    def __init__(self, settings):
        self.settings = settings
        self.active = 0
        self.windows = defaultdict(deque)
        path = settings.public_budget_db
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS budget (day TEXT PRIMARY KEY, requests INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS identity_key (id INTEGER PRIMARY KEY CHECK(id=1), secret TEXT NOT NULL)")
        self.db.execute("INSERT OR IGNORE INTO identity_key VALUES (1, ?)", (secrets.token_hex(32),))
        self.db.commit()
        self.secret = self.db.execute("SELECT secret FROM identity_key WHERE id=1").fetchone()[0].encode()

    def visitor(self, token):
        return signed_visitor(self.secret, token)

    def reserve(self, address, is_chat, *, acquire_slot=True):
        now = time.monotonic()
        key = hashlib.sha256(address.encode()).hexdigest()
        for old in list(self.windows):
            if not self.windows[old] or self.windows[old][-1] <= now - 60:
                del self.windows[old]
        if key not in self.windows and len(self.windows) >= 10000:
            return "当前体验人数较多，请稍后重试。"
        window = self.windows[key]
        while window and window[0] <= now - 60:
            window.popleft()
        if len(window) >= self.settings.public_requests_per_minute:
            return "操作较频繁，请一分钟后再试。"
        if acquire_slot and self.active >= self.settings.public_max_concurrent:
            return "当前体验人数较多，请稍后重试，也可以查看已保存案例。"
        if is_chat:
            day = time.strftime("%Y-%m-%d", time.gmtime())
            with self.db:
                self.db.execute("INSERT OR IGNORE INTO budget VALUES (?, 0)", (day,))
                changed = self.db.execute("UPDATE budget SET requests=requests+1 WHERE day=? AND requests<?", (day, self.settings.public_daily_chat_limit)).rowcount
                self.db.execute("DELETE FROM budget WHERE day < ?", (day,))
            if not changed:
                return "今日实时体验额度已用完，请查看已保存案例，或明天再试。"
        window.append(now)
        if acquire_slot:
            self.active += 1
        return None


def known_submission(request, raw, identity):
    """Only waive new-execution budget for an already owned submission.

    The route still checks its fingerprint and rejects conflicting inputs.
    Transport retries remain rate limited; no client claim grants an owner.
    """
    try:
        from src.evaluation.auth import front_principal
        data = json.loads(raw)
        if not data.get("request_id") or not data.get("session_id"):
            return False
        user = front_principal(request)
        owner = "internal_" + user.tester_id if user else identity
        session = hashlib.sha256((owner + ":" + data["session_id"]).encode()).hexdigest()
        value = request.app.state.agent_runtime.runs.live.lookup(owner, session, data["request_id"])
        return value is not None
    except Exception:
        return False


async def bounded_body(request, cap):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > cap:
            return None
        raw.extend(chunk)
    return bytes(raw)


async def public_access(request, call_next):
    settings = request.app.state.public_settings
    cookie_age = max(86400, getattr(settings, "chat_run_retention_seconds", 86400))
    path = request.url.path
    lifecycle = path.startswith("/api/chat/")
    identity_path = lifecycle or path == "/api/chat" or path.startswith("/api/files")
    if not settings.public_demo_enabled:
        if not identity_path:
            return await call_next(request)
        runtime = getattr(request.app.state, "agent_runtime", None)
        if runtime is None:
            from src.agent.runtime import AgentRuntime
            runtime = request.app.state.agent_runtime = AgentRuntime()
        identity, cookie = signed_visitor(runtime.runs.live.secret, request.cookies.get(COOKIE))
        request.state.public_visitor = identity
        response = await call_next(request)
        response.set_cookie(COOKIE, cookie, httponly=True, secure=request.url.scheme == "https", samesite="lax", max_age=cookie_age, path="/api")
        return response
    if lifecycle and request.method == "GET":
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origin_list:
            return JSONResponse({"detail": {"code": "public_origin_denied", "message": "请从本站页面开始体验。"}}, status_code=403)
        identity, cookie = request.app.state.public_access.visitor(request.cookies.get(COOKIE))
        request.state.public_visitor = identity
        response = await call_next(request)
        response.set_cookie(COOKIE, cookie, httponly=True, secure=settings.public_cookie_secure, samesite="lax", max_age=cookie_age, path="/api")
        return response
    protected = path in {"/api/chat", "/api/files", "/api/files/status", "/api/files/release"} and request.method == "POST"
    if not protected:
        return await call_next(request)
    origin = request.headers.get("origin")
    if origin and origin not in settings.cors_origin_list:
        return JSONResponse({"detail": {"code": "public_origin_denied", "message": "请从本站页面开始体验。"}}, status_code=403)
    # Reject oversized bodies before buffering/parsing.
    length = request.headers.get("content-length", "0")
    if not length.isdigit() or int(length) > (10 * 1024 * 1024 if path == "/api/files" else 100000):
        return JSONResponse({"detail": {"code": "public_body_too_large", "message": "提交内容过大。"}}, status_code=413)
    guard = request.app.state.public_access
    identity, cookie = guard.visitor(request.cookies.get(COOKIE))
    request.state.public_visitor = identity
    retry = False
    if path == "/api/chat":
        raw = await bounded_body(request, 100000)
        if raw is None:
            return JSONResponse({"detail": {"code": "public_body_too_large", "message": "提交内容过大。"}}, status_code=413)
        request._body = raw
        retry = known_submission(request, raw, identity)
    problem = guard.reserve(request.client.host if request.client else "unknown", path == "/api/chat" and not retry, acquire_slot=not retry)
    if problem:
        return JSONResponse({"detail": {"code": "public_demo_limit", "message": problem}}, status_code=429, headers={"Retry-After": "60"})
    request.state.public_slot_acquired = not retry
    try:
        if path != "/api/chat":
            raw = await bounded_body(request, 10 * 1024 * 1024 if path == "/api/files" else 100000)
            if raw is None:
                return JSONResponse({"detail": {"code": "public_body_too_large", "message": "提交内容过大。"}}, status_code=413)
            request._body = raw
        response = await call_next(request)
        response.set_cookie(COOKIE, cookie, httponly=True, secure=settings.public_cookie_secure, samesite="lax", max_age=cookie_age, path="/api")
        return response
    finally:
        if not retry and not getattr(request.state, "public_slot_transferred", False):
            guard.active -= 1
