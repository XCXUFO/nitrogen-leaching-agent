"""Persistent batch receipts; each PDF remains a draft until human review."""
import asyncio
import json
import hashlib
import secrets
import time
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from src.api.literature import (
    ExtractInput, PaperInput, PaperUpdateInput, TagSuggestionInput, create_paper_record,
    extract_paper_fields, fail, now, store, suggest_paper_tags, update_paper_record,
)
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal

router = APIRouter()


class BatchInput(BaseModel):
    upload_ids: list[str] = Field(min_length=1, max_length=100)
    ai_extract: bool = True
    ai_tag: bool = True


class BatchAIInput(BaseModel):
    paper_ids: list[str] = Field(min_length=1, max_length=100)
    ai_extract: bool = True
    ai_tag: bool = True


def read_batch(db, identifier, user):
    with db.lock:
        row = db.db.execute("SELECT data FROM literature_imports WHERE id=? AND owner=?",
                            (identifier, user.tester_id)).fetchone()
    if not row:
        fail("import_not_found", "导入任务不存在。", 404)
    return json.loads(row[0])


def write_batch(db, batch):
    db.db.execute("UPDATE literature_imports SET data=? WHERE id=?",
                  (json.dumps(batch, ensure_ascii=False), batch["id"]))


def message(exc):
    if isinstance(exc, HTTPException) and isinstance(exc.detail, dict):
        return exc.detail.get("message", "处理失败，请重试。")
    return "处理失败，请重试。"


async def process_batch(request, identifier, user):
    db = store(request)
    # Three workers per batch, with a shared per-process cap across batches.
    if not hasattr(request.app.state, "literature_batch_slots"):
        request.app.state.literature_batch_slots = asyncio.Semaphore(3)
    slots = request.app.state.literature_batch_slots

    async def process(index):
        async with slots:
            attempt = secrets.token_hex(16)
            with db.write():
                batch = read_batch(db, identifier, user)
                item = batch["items"][index]
                if item["status"] != "queued":
                    return
                item.update(status="processing", started_at=time.time(), attempt=attempt)
                write_batch(db, batch)
            warnings = []
            try:
                paper = db.get_paper(item["paper_id"])
                if paper["revision"] != item["revision"]:
                    fail("import_paper_changed", "文献已被修改，已停止自动处理，请人工审核。", 409)
                values = dict(paper)
                values["action"] = "register" if paper["registration"] == "registered" else "draft"
                if batch["ai_extract"]:
                    try:
                        result = await extract_paper_fields(request, ExtractInput(paper_id=paper["id"]), user)
                        values.update({key: value for key, value in result["fields"].items() if value not in (None, "", [])})
                        for key in ("authors", "venue", "year"):
                            if result["fields"].get(key):
                                values[key + "_unknown"] = False
                        if result["warning"]:
                            warnings.append(result["warning"])
                    except Exception as exc:
                        warnings.append("解析：" + message(exc))
                if batch["ai_tag"]:
                    try:
                        tag_fields = {key: values[key] for key in ("title", "abstract", "conclusion", "tag_ids")}
                        if batch.get("kind") == "existing":
                            tag_fields["tag_ids"] = []
                        result = await suggest_paper_tags(request, TagSuggestionInput(
                            paper_id=paper["id"], **tag_fields), user)
                        values["tag_ids"] = result["tag_ids"]
                    except Exception as exc:
                        warnings.append("打标：" + message(exc))
                # Fence stale attempts and commit the paper and receipt together.
                with db.write():
                    latest = read_batch(db, identifier, user)
                    target = latest["items"][index]
                    if target.get("attempt") != attempt or target["status"] != "processing":
                        return
                    try:
                        saved = update_paper_record(db, paper["id"], PaperUpdateInput(**values, expected_revision=paper["revision"]), user)
                    except HTTPException as exc:
                        if not isinstance(exc.detail, dict) or exc.detail.get("code") != "doi_confirmation_required":
                            raise
                        warnings.append(f"解析到 DOI {values['doi']}，与已有文献重复，请审核时确认版本并关联文献。")
                        values["doi"] = paper["doi"]
                        saved = update_paper_record(db, paper["id"], PaperUpdateInput(**values, expected_revision=paper["revision"]), user)
                    target.update(status="warning" if warnings else "ready", warnings=warnings, revision=saved["revision"])
                    write_batch(db, latest)
            except Exception as exc:
                warnings.append(message(exc))
                with db.write():
                    latest = read_batch(db, identifier, user)
                    target = latest["items"][index]
                    if target.get("attempt") == attempt and target["status"] == "processing":
                        target.update(status="failed", warnings=warnings, revision=item["revision"])
                        write_batch(db, latest)

    batch = read_batch(db, identifier, user)
    await asyncio.gather(*(process(index) for index in range(len(batch["items"]))))


@router.post("/imports", status_code=202)
def create_import(request: Request, body: BatchInput, background_tasks: BackgroundTasks,
                  user: Principal = Depends(current_user)):
    db = store(request)
    if len(set(body.upload_ids)) != len(body.upload_ids):
        fail("duplicate_upload", "同一批次不能重复提交同一上传文件。", 422)
    # The same upload set is idempotent, including a lost HTTP response.
    identifier = hashlib.sha256(json.dumps([user.tester_id, sorted(body.upload_ids)]).encode()).hexdigest()[:32]
    with db.write():
        existing = db.db.execute("SELECT data FROM literature_imports WHERE id=? AND owner=?",
                                 (identifier, user.tester_id)).fetchone()
        if existing:
            return json.loads(existing[0])
        for upload_id in body.upload_ids:
            if not db.db.execute("SELECT id FROM uploads WHERE id=? AND owner=? AND consumed_at IS NULL",
                                 (upload_id, user.tester_id)).fetchone():
                fail("upload_not_found", "部分上传文件已失效，请重新上传。", 404)
        batch = {"id": identifier, "ai_extract": body.ai_extract, "ai_tag": body.ai_tag,
                 "created_at": now(), "items": []}
        for upload_id in body.upload_ids:
            filename = db.db.execute("SELECT filename FROM uploads WHERE id=?", (upload_id,)).fetchone()[0]
            try:
                paper = create_paper_record(db, PaperInput(upload_id=upload_id), user)
                batch["items"].append({"filename": filename, "paper_id": paper["id"], "revision": paper["revision"],
                                       "status": "queued", "warnings": []})
            except HTTPException as exc:
                batch["items"].append({"filename": filename, "paper_id": exc.detail.get("paper_id"),
                                       "status": "duplicate" if exc.detail.get("code") == "duplicate_file" else "failed",
                                       "warnings": [message(exc)]})
        db.db.execute("INSERT INTO literature_imports VALUES (?,?,?,?)",
                      (batch["id"], user.tester_id, json.dumps(batch, ensure_ascii=False), batch["created_at"]))
    background_tasks.add_task(process_batch, request, batch["id"], user)
    return batch


@router.post("/batch-ai", status_code=202)
def create_batch_ai(request: Request, body: BatchAIInput, background_tasks: BackgroundTasks,
                    user: Principal = Depends(current_user)):
    db = store(request)
    if not body.ai_extract and not body.ai_tag:
        fail("ai_required", "请至少勾选一项 AI 能力。", 422)
    if len(set(body.paper_ids)) != len(body.paper_ids):
        fail("duplicate_paper", "不能重复选择同一文献。", 422)
    with db.write():
        papers = [db.get_paper(identifier) for identifier in body.paper_ids]
        batch = {"id": secrets.token_hex(16), "kind": "existing", "ai_extract": body.ai_extract,
                 "ai_tag": body.ai_tag, "created_at": now(), "items": [
                     {"filename": paper["filename"], "paper_id": paper["id"], "revision": paper["revision"],
                      "status": "queued", "warnings": []} for paper in papers]}
        db.db.execute("INSERT INTO literature_imports VALUES (?,?,?,?)",
                      (batch["id"], user.tester_id, json.dumps(batch, ensure_ascii=False), batch["created_at"]))
    background_tasks.add_task(process_batch, request, batch["id"], user)
    return batch


def retryable(item, batch):
    if not item.get("paper_id") or not item.get("revision"):
        return False
    if item["status"] in {"warning", "failed"}:
        return True
    if item["status"] == "processing":
        return time.time() - item.get("started_at", 0) > 300
    if item["status"] == "queued":
        # A process restart loses BackgroundTasks, but not the durable receipt.
        # Re-dispatch is safe: workers claim queued items inside db.write().
        queued_at = item.get("queued_at", datetime.fromisoformat(batch["created_at"]).timestamp())
        return time.time() - queued_at > 300
    return False


def with_retry_status(batch):
    for item in batch["items"]:
        item["retryable"] = retryable(item, batch)
    return batch


@router.get("/imports")
def list_imports(request: Request, user: Principal = Depends(current_user)):
    db = store(request)
    with db.lock:
        rows = db.db.execute("SELECT data FROM literature_imports WHERE owner=? ORDER BY created_at DESC LIMIT 10",
                             (user.tester_id,)).fetchall()
    return {"items": [with_retry_status(json.loads(row[0])) for row in rows]}


@router.get("/imports/{identifier}")
def get_import(request: Request, identifier: str, user: Principal = Depends(current_user)):
    return with_retry_status(read_batch(store(request), identifier, user))


class RetryInput(BaseModel):
    paper_ids: list[str] | None = Field(default=None, min_length=1, max_length=100)


@router.post("/imports/{identifier}/retry", status_code=202)
def retry_import(request: Request, identifier: str, background_tasks: BackgroundTasks, body: RetryInput | None = None,
                 user: Principal = Depends(current_user)):
    db = store(request)
    with db.write():
        batch = read_batch(db, identifier, user)
        selected = set(body.paper_ids) if body and body.paper_ids else None
        if selected and not selected.issubset({item.get("paper_id") for item in batch["items"]}):
            fail("invalid_retry_papers", "只能重试本批次文献。", 422)
        for item in batch["items"]:
            if selected is not None and item.get("paper_id") not in selected:
                continue
            if not item.get("paper_id") or not item.get("revision"):
                continue
            if retryable(item, batch):
                item.update(status="queued", queued_at=time.time(), attempt=None)
        write_batch(db, batch)
    background_tasks.add_task(process_batch, request, identifier, user)
    return batch
