"""Single-worker public demo limits and signed, HttpOnly visitor identities.

Budgets survive restarts in a separate SQLite file. IPs are hashed and proxy
headers are deliberately ignored; deploy behind a trusted, configured proxy.
"""
import hashlib
import hmac
import secrets
import sqlite3
import time
from collections import defaultdict, deque
from pathlib import Path

from starlette.responses import JSONResponse

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
        identity, _, signature = (token or "").partition(".")
        if len(identity) != 32 or not hmac.compare_digest(signature, hmac.new(self.secret, identity.encode(), "sha256").hexdigest()):
            identity = secrets.token_hex(16)
        return identity, identity + "." + hmac.new(self.secret, identity.encode(), "sha256").hexdigest()

    def reserve(self, address, is_chat):
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
        if self.active >= self.settings.public_max_concurrent:
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
        self.active += 1
        return None


async def public_access(request, call_next):
    settings = request.app.state.public_settings
    if not settings.public_demo_enabled:
        return await call_next(request)
    path = request.url.path
    protected = path in {"/api/chat", "/api/files", "/api/files/status"} and request.method == "POST"
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
    problem = guard.reserve(request.client.host if request.client else "unknown", path == "/api/chat")
    if problem:
        return JSONResponse({"detail": {"code": "public_demo_limit", "message": problem}}, status_code=429, headers={"Retry-After": "60"})
    try:
        raw = bytearray()
        cap = 10 * 1024 * 1024 if path == "/api/files" else 100000
        async for chunk in request.stream():
            if len(raw) + len(chunk) > cap:
                return JSONResponse({"detail": {"code": "public_body_too_large", "message": "提交内容过大。"}}, status_code=413)
            raw.extend(chunk)
        request._body = bytes(raw)
        response = await call_next(request)
        response.set_cookie(COOKIE, cookie, httponly=True, secure=settings.public_cookie_secure, samesite="lax", max_age=86400, path="/api")
        return response
    finally:
        guard.active -= 1
