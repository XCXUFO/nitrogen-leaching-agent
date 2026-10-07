from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from fastapi import HTTPException, Request

from src.evaluation.contracts import AccessFile, Principal


def load_access(path: str) -> AccessFile:
    # Deliberately fail startup when enabled with an invalid/missing access file.
    # No default credentials and no role supplied by the browser.
    return AccessFile.model_validate_json(Path(path).read_text(encoding="utf-8"))


def current_user(request: Request) -> Principal:
    access = getattr(request.app.state, "eval_access", None)
    if access is None:
        raise HTTPException(404, detail={"code": "evaluation_disabled", "message": "评测后台尚未启用。"})
    header = request.headers.get("authorization", "")
    kind, _, token = header.partition(" ")
    if kind.lower() != "bearer" or not 32 <= len(token) <= 256:
        raise HTTPException(401, detail={"code": "evaluation_unauthorized", "message": "请输入有效的评测访问密钥。"})
    fingerprint = hashlib.sha256(token.encode()).hexdigest()
    for user in access.users:
        if hmac.compare_digest(fingerprint, user.token_sha256):
            return Principal(tester_id=user.tester_id, role=user.role)
    raise HTTPException(401, detail={"code": "evaluation_unauthorized", "message": "评测访问密钥无效。"})


def require_developer(user: Principal) -> None:
    if user.role != "developer":
        raise HTTPException(403, detail={"code": "evaluation_forbidden", "message": "此功能仅供开发者使用。"})
