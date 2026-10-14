"""Isolated HTTP/browser fixture: no production databases or credentials."""
import hashlib
import os
from pathlib import Path

from fastapi import Depends, FastAPI, Request

from src.api.literature import LiteratureStore, router
from src.evaluation.auth import current_user, login, password_hash, sessions
from src.evaluation.contracts import AccessEntry, AccessFile, LoginInput, Principal


TOKENS = {role: f"literature-test-{role}-" + "0" * 32 for role in ("tester", "reviewer", "developer")}


def create_app(root: Path | None = None):
    root = root or Path(os.environ["LITERATURE_TEST_ROOT"])
    app = FastAPI()
    app.state.literature = LiteratureStore(str(root / "library.db"), str(root / "files"))
    app.state.eval_access = AccessFile(users=[
        AccessEntry(tester_id=role, role=role, token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                    username=f"cau_{role}", password_hash=password_hash("CauTest123456"))
        for role, token in TOKENS.items()
    ])
    app.include_router(router, prefix="/api")

    @app.post("/api/eval/login")
    def account_login(request: Request, body: LoginInput):
        return login(request, body)

    @app.post("/api/eval/logout", status_code=204)
    def account_logout(request: Request):
        sessions(request).revoke(request.headers.get("authorization", "").partition(" ")[2])

    @app.get("/api/eval/me")
    def me(user: Principal = Depends(current_user)):
        return user

    return app
