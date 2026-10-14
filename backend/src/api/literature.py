"""Paper registration and taxonomy. Separate from the immutable RAG corpus."""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import secrets
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from functools import wraps
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

import fitz
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse
from loguru import logger
from pydantic import AliasChoices, BaseModel, Field

from src.api.literature_extract import local_suggestions, read_pdf_for_extraction, suggest_fields
from src.config import settings
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal

router = APIRouter(prefix="/literature")
FIELD_LABELS = {"title": "论文标题", "authors": "作者", "authors_unknown": "作者未知", "publication_type": "发表形式", "venue": "发表载体", "venue_unknown": "载体未知", "year": "发表年份", "year_unknown": "年份未知", "language": "语言", "language_note": "语言说明", "doi": "DOI", "source_url": "来源链接", "source_note": "出处说明", "abstract": "摘要", "version_note": "版本说明", "related_paper_ids": "关联文献", "internal_note": "内部备注", "tag_ids": "分类标签", "filename": "文件名", "sha256": "文件指纹", "usage": "使用状态", "name": "名称", "description": "说明", "selection": "选择方式", "required": "登记必填", "enabled": "启用状态", "sort_order": "展示顺序", "parent_id": "父标签"}


def fail(code: str, message: str, status: int = 400):
    raise HTTPException(status, detail={"code": code, "message": message})


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def doi_key(value: str) -> str:
    value = value.strip()
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", value, flags=re.I)
    return value.strip().casefold()


def valid_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.hostname) and not any(c.isspace() for c in value)
    except ValueError:
        return False


class AuthorInput(BaseModel):
    name: str = Field(max_length=200)
    kind: Literal["person", "institution"] = "person"


class PaperInput(BaseModel):
    upload_id: str | None = None
    title: str = Field(default="", max_length=500)
    authors: list[AuthorInput | str] = Field(default_factory=list, max_length=100)
    authors_unknown: bool = False
    publication_type: Literal["期刊论文", "会议论文", "预印本", "其他学术论文"] | None = None
    venue: str = Field(default="", max_length=500)
    venue_unknown: bool = False
    year: int | None = Field(default=None, ge=1000, le=3000)
    year_unknown: bool = False
    language: Literal["中文", "英文", "其他"] | None = None
    language_note: str = Field(default="", max_length=100)
    doi: str = Field(default="", max_length=300)
    source_url: str = Field(default="", max_length=2000)
    source_note: str = Field(default="", max_length=2000)
    abstract: str = Field(default="", max_length=20000)
    version_note: str = Field(default="", max_length=2000)
    related_paper_ids: list[str] = Field(default_factory=list, max_length=20)
    internal_note: str = Field(default="", max_length=2000)
    tag_ids: list[str] = Field(default_factory=list, max_length=100)
    action: Literal["draft", "register"] = "draft"
    confirm_same_doi: bool = False


class PaperUpdateInput(PaperInput):
    expected_revision: int = Field(ge=1, validation_alias=AliasChoices("expected_revision", "revision"))


class DimensionInput(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=2000)
    selection: Literal["single", "multiple"] = "multiple"
    required: bool = False
    enabled: bool = True
    sort_order: int = 0


class TagInput(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    description: str = Field(default="", max_length=2000)
    parent_id: str | None = None
    enabled: bool = True
    sort_order: int = 0


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=2000)


class ExtractInput(BaseModel):
    upload_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{32}$")
    paper_id: str | None = Field(default=None, pattern=r"^P-[0-9A-F]{16}$")


def synchronized(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return locked


class LiteratureStore:
    def __init__(self, db_path: str, files_dir: str):
        self.root = Path(files_dir)
        self.root.mkdir(parents=True, exist_ok=True)
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(db_path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.lock = threading.RLock()
        with self.db:
            self.db.executescript("""
            CREATE TABLE IF NOT EXISTS uploads (id TEXT PRIMARY KEY, filename TEXT NOT NULL, sha256 TEXT NOT NULL, size INTEGER NOT NULL, owner TEXT NOT NULL, created_at TEXT NOT NULL, consumed_at TEXT);
            CREATE TABLE IF NOT EXISTS papers (id TEXT PRIMARY KEY, data TEXT NOT NULL, filename TEXT NOT NULL, sha256 TEXT NOT NULL, registration TEXT NOT NULL, usage TEXT NOT NULL DEFAULT 'normal', deleted INTEGER NOT NULL DEFAULT 0, created_by TEXT NOT NULL, created_at TEXT NOT NULL, updated_by TEXT NOT NULL, updated_at TEXT NOT NULL, registered_by TEXT, registered_at TEXT);
            CREATE INDEX IF NOT EXISTS papers_hash ON papers(sha256, deleted);
            CREATE UNIQUE INDEX IF NOT EXISTS active_paper_hash ON papers(sha256) WHERE deleted=0;
            CREATE TABLE IF NOT EXISTS dimensions (id TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, description TEXT NOT NULL, selection TEXT NOT NULL, required INTEGER NOT NULL, enabled INTEGER NOT NULL, sort_order INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS tags (id TEXT PRIMARY KEY, dimension_id TEXT NOT NULL REFERENCES dimensions(id), parent_id TEXT REFERENCES tags(id), name TEXT NOT NULL, description TEXT NOT NULL, enabled INTEGER NOT NULL, sort_order INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
            CREATE UNIQUE INDEX IF NOT EXISTS root_tag_name ON tags(dimension_id, name COLLATE NOCASE) WHERE parent_id IS NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS child_tag_name ON tags(dimension_id, parent_id, name COLLATE NOCASE) WHERE parent_id IS NOT NULL;
            CREATE TABLE IF NOT EXISTS paper_tags (paper_id TEXT NOT NULL REFERENCES papers(id), tag_id TEXT NOT NULL REFERENCES tags(id), PRIMARY KEY(paper_id,tag_id));
            CREATE TABLE IF NOT EXISTS events (id TEXT PRIMARY KEY, entity TEXT NOT NULL, entity_id TEXT NOT NULL, action TEXT NOT NULL, actor TEXT NOT NULL, at TEXT NOT NULL, before_json TEXT, after_json TEXT, reason TEXT, summary TEXT NOT NULL DEFAULT '');
            CREATE INDEX IF NOT EXISTS events_entity ON events(entity,entity_id,at);
            """)
            if "summary" not in {r[1] for r in self.db.execute("PRAGMA table_info(events)")}:
                self.db.execute("ALTER TABLE events ADD COLUMN summary TEXT NOT NULL DEFAULT ''")
            if "revision" not in {r[1] for r in self.db.execute("PRAGMA table_info(papers)")}:
                self.db.execute("ALTER TABLE papers ADD COLUMN revision INTEGER NOT NULL DEFAULT 1")
        self.prune_uploads()

    def close(self):
        self.db.close()

    @contextmanager
    def write(self):
        # Acquire the database write lock before duplicate checks, including
        # checks made by another worker using a separate SQLite connection.
        with self.lock:
            self.db.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.db.commit()
            except BaseException:
                self.db.rollback()
                raise

    def preserve_upload(self, upload_row):
        source = self.root / f"upload-{upload_row['id']}"
        if not source.is_file():
            fail("upload_not_found", "上传文件已失效，请重新上传。", 404)
        target = self.root / f"blob-{upload_row['sha256']}.pdf"
        if not target.is_file():
            # The committed PDF is immutable. Retain the upload for retries if
            # any database write fails; only metadata switches the current file.
            staging = self.root / f"upload-{secrets.token_hex(16)}"
            try:
                shutil.copyfile(source, staging)
                staging.replace(target)
            finally:
                staging.unlink(missing_ok=True)

    def prune_uploads(self):
        """Keep uncommitted PDF uploads for at most one day."""
        cutoff_time = datetime.now(timezone.utc) - timedelta(days=1)
        cutoff = cutoff_time.isoformat()
        with self.write():
            stale = [r[0] for r in self.db.execute("SELECT id FROM uploads WHERE consumed_at IS NULL AND created_at<?", (cutoff,))]
            for identifier in stale:
                (self.root / f"upload-{identifier}").unlink(missing_ok=True)
            self.db.execute("DELETE FROM uploads WHERE consumed_at IS NULL AND created_at<?", (cutoff,))
            for path in self.root.glob("upload-*"):
                if path.is_file() and path.stat().st_mtime < cutoff_time.timestamp():
                    path.unlink(missing_ok=True)
            # A failed transaction may leave a copied blob with no record.
            # Deleted records still retain their original files.
            referenced = {row[0] for row in self.db.execute("SELECT sha256 FROM papers")}
            for path in self.root.glob("blob-*.pdf"):
                if path.stem[5:] not in referenced and path.stat().st_mtime < cutoff_time.timestamp():
                    path.unlink(missing_ok=True)

    def event(self, entity: str, entity_id: str, action: str, actor: str, before=None, after=None, reason=""):
        if isinstance(before, dict) and isinstance(after, dict):
            changed = [FIELD_LABELS.get(key, key) for key in dict.fromkeys([*before, *after]) if key not in {"id", "dimension_id", "created_at", "updated_at"} and before.get(key) != after.get(key)]
            summary = "修改：" + "、".join(changed[:8]) + ("等" if len(changed) > 8 else "") if changed else "保存记录"
        else:
            summary = {"create_draft": "新增并保存草稿", "register": "完成登记", "disable": "停用", "restore": "恢复", "delete": "逻辑删除", "create": "新增", "edit": "修改", "replace_file": "替换草稿文件"}.get(action, action)
        self.db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?)", (secrets.token_hex(12), entity, entity_id, action, actor, now(), json.dumps(before, ensure_ascii=False) if before is not None else None, json.dumps(after, ensure_ascii=False) if after is not None else None, reason, summary))

    @synchronized
    def events(self, entity: str, entity_id: str):
        return [dict(row) | {"before": json.loads(row["before_json"]) if row["before_json"] else None, "after": json.loads(row["after_json"]) if row["after_json"] else None} for row in self.db.execute("SELECT * FROM events WHERE entity=? AND entity_id=? ORDER BY at DESC", (entity, entity_id))]

    @synchronized
    def paper(self, row, *, full=False):
        data = json.loads(row["data"])
        result = data | {key: row[key] for key in ("id", "revision", "filename", "sha256", "registration", "usage", "created_by", "created_at", "updated_by", "updated_at", "registered_by", "registered_at")}
        result["tag_ids"] = [r[0] for r in self.db.execute("SELECT tag_id FROM paper_tags WHERE paper_id=?", (row["id"],))]
        if full:
            result["events"] = self.events("paper", row["id"])
            result["related_papers"] = [{"id": i, "title": (json.loads(r["data"])["title"] if (r := self.db.execute("SELECT data,deleted FROM papers WHERE id=?", (i,)).fetchone()) and not r["deleted"] else "关联文献已删除"), "deleted": not bool(r) or bool(r["deleted"])} for i in data.get("related_paper_ids", [])]
            taxonomy = self.taxonomy()
            by_id = {t["id"]: t for t in taxonomy["tags"]}
            warnings = []
            for tid in result["tag_ids"]:
                tag = by_id.get(tid)
                if tag and not tag["enabled"]:
                    warnings.append(f"标签“{tag['path']}”已停用")
            for dim in taxonomy["dimensions"]:
                if not dim["enabled"] and any(by_id.get(tid, {}).get("dimension_id") == dim["id"] for tid in result["tag_ids"]):
                    warnings.append(f"维度“{dim['name']}”已停用")
                if dim["enabled"] and dim["required"] and not any(by_id.get(tid, {}).get("dimension_id") == dim["id"] and by_id[tid]["enabled"] for tid in result["tag_ids"]):
                    warnings.append(f"必填维度“{dim['name']}”待补充")
            result["warnings"] = warnings
        return result

    @synchronized
    def get_paper(self, paper_id: str, *, full=False):
        row = self.db.execute("SELECT * FROM papers WHERE id=? AND deleted=0", (paper_id,)).fetchone()
        if not row:
            fail("paper_not_found", "文献不存在或已删除。", 404)
        return self.paper(row, full=full)

    @synchronized
    def taxonomy(self):
        dims = [dict(r) for r in self.db.execute("SELECT * FROM dimensions ORDER BY sort_order,name")]
        tags = [dict(r) for r in self.db.execute("SELECT t.*, COUNT(DISTINCT CASE WHEN p.deleted=0 THEN p.id END) AS paper_count FROM tags t LEFT JOIN paper_tags pt ON pt.tag_id=t.id LEFT JOIN papers p ON p.id=pt.paper_id GROUP BY t.id ORDER BY t.sort_order,t.name")]
        paths = {}
        by_id = {t["id"]: t for t in tags}
        for tag in tags:
            names, node, seen = [], tag, set()
            while node and node["id"] not in seen:
                seen.add(node["id"]); names.append(node["name"])
                node = by_id.get(node["parent_id"])
            paths[tag["id"]] = " / ".join(reversed(names))
        for tag in tags: tag["path"] = paths[tag["id"]]
        return {"dimensions": dims, "tags": tags}

    def descendants(self, tag_id: str, tags: list[dict]):
        ids = {tag_id}
        while True:
            more = {t["id"] for t in tags if t["parent_id"] in ids}
            if more <= ids: return ids
            ids |= more


def store(request: Request) -> LiteratureStore:
    value = getattr(request.app.state, "literature", None)
    if value is None: fail("literature_disabled", "文献库后台尚未启用。", 404)
    return value


def validate_paper(db: LiteratureStore, body: PaperInput, existing_id: str | None = None):
    raw = body.model_dump()
    previous = db.get_paper(existing_id) if existing_id else {}
    for key in ("title", "venue", "doi", "source_url", "source_note", "language_note", "version_note", "abstract", "internal_note"):
        raw[key] = raw[key].strip()
    raw["authors"] = []
    for author in body.authors:
        name = author.strip() if isinstance(author, str) else author.name.strip()
        if len(name) > 200: fail("invalid_author", "作者名称不能超过 200 字符。")
        if name:
            raw["authors"].append({"name": name, "kind": "person" if isinstance(author, str) else author.kind})
    raw["doi"] = doi_key(raw["doi"])
    if raw["authors_unknown"] and raw["authors"]: fail("authors_conflict", "已填写作者时不能同时标记未知。")
    if raw["venue_unknown"] and raw["venue"]: fail("venue_conflict", "已填写发表载体时不能同时标记未知。")
    if raw["year_unknown"] and raw["year"] is not None: fail("year_conflict", "已填写发表年份时不能同时标记未知。")
    if raw["doi"] and not re.fullmatch(r"10\.\d{4,9}/\S+", raw["doi"], re.I): fail("invalid_doi", "DOI 格式不正确。")
    if raw["source_url"] and not valid_url(raw["source_url"]): fail("invalid_source_url", "来源链接须为有效 HTTP/HTTPS 地址。")
    tags = db.taxonomy()
    chosen = {}
    for tag_id in raw["tag_ids"]:
        tag = next((t for t in tags["tags"] if t["id"] == tag_id), None)
        if not tag: fail("invalid_tag", "标签不存在。")
        dim = next(d for d in tags["dimensions"] if d["id"] == tag["dimension_id"])
        if (not tag["enabled"] or not dim["enabled"]) and tag_id not in previous.get("tag_ids", []):
            fail("invalid_tag", "不能新增已停用标签或维度的关联。")
        chosen.setdefault(dim["id"], []).append(tag)
    for dim in tags["dimensions"]:
        selected = chosen.get(dim["id"], [])
        if dim["selection"] == "single" and len(selected) > 1: fail("single_dimension", f"{dim['name']}只能选择一个标签。")
        ids = {t["id"] for t in selected}
        if any((db.descendants(t["id"], tags["tags"]) - {t["id"]}) & ids for t in selected): fail("ancestor_conflict", "同一维度不能同时保存祖先和后代标签。")
        if body.action == "register" and dim["enabled"] and dim["required"] and not any(t["enabled"] for t in selected): fail("required_tag", f"请选择{dim['name']}的有效标签。")
    if len(set(raw["tag_ids"])) != len(raw["tag_ids"]): fail("duplicate_tag", "标签不能重复选择。")
    for related in raw["related_paper_ids"]:
        if related == existing_id: fail("self_relation", "不能关联文献自身。")
        if related not in previous.get("related_paper_ids", []):
            db.get_paper(related)
    if body.action == "register":
        if not raw["title"]: fail("title_required", "请填写论文标题。")
        if not raw["authors"] and not raw["authors_unknown"]: fail("authors_required", "请填写作者或标记未知。")
        if not raw["publication_type"]: fail("publication_type_required", "请选择发表形式。")
        if not raw["venue"] and not raw["venue_unknown"]: fail("venue_required", "请填写发表载体或标记未知。")
        if raw["year"] is None and not raw["year_unknown"]: fail("year_required", "请选择发表年份或标记未知。")
        if not raw["language"] or raw["language"] == "其他" and not raw["language_note"]: fail("language_required", "请选择语言，其他语言需说明。")
        if not raw["source_url"] and not raw["source_note"]: fail("source_required", "来源链接与出处说明至少填写一项。")
    if raw["doi"]:
        matches = [r[0] for r in db.db.execute("SELECT id FROM papers WHERE deleted=0 AND id!=? AND json_extract(data,'$.doi')=?", (existing_id or "", raw["doi"]))]
        previously_confirmed = previous.get("doi") == raw["doi"] and bool(previous.get("version_note")) and bool(set(matches).intersection(previous.get("related_paper_ids", [])))
        if matches and (not (raw["confirm_same_doi"] or previously_confirmed) or not raw["version_note"] or not set(matches).intersection(raw["related_paper_ids"])):
            fail("doi_confirmation_required", "DOI 已存在。继续登记需确认、填写版本差异说明并关联已有文献。", 409)
    raw.pop("expected_revision", None); raw.pop("upload_id"); raw.pop("action"); raw.pop("confirm_same_doi")
    return raw


@router.get("/taxonomy")
def taxonomy(request: Request, user: Principal = Depends(current_user)):
    return store(request).taxonomy()


@router.get("/users")
def users(request: Request, user: Principal = Depends(current_user)):
    store(request)
    return [{"id": entry.tester_id, "name": entry.tester_id} for entry in request.app.state.eval_access.users]


@router.get("/config")
def config(request: Request, user: Principal = Depends(current_user)):
    store(request)
    return {"max_pdf_mb": settings.literature_max_pdf_mb}


@router.post("/uploads")
async def upload(request: Request, filename: str = Query(max_length=255), user: Principal = Depends(current_user)):
    db = store(request)
    if not filename.lower().endswith(".pdf") or Path(filename).name != filename or "\\" in filename: fail("invalid_filename", "仅支持单篇 PDF 文件。")
    limit = settings.literature_max_pdf_mb * 1024 * 1024
    content_length = request.headers.get("content-length", "")
    if content_length.isdigit() and int(content_length) > limit:
        fail("file_too_large", f"PDF 不能超过 {settings.literature_max_pdf_mb} MB。", 413)
    upload_id = secrets.token_hex(16)
    path = db.root / f"upload-{upload_id}"
    size = 0; digest = hashlib.sha256()
    try:
        with path.open("xb") as target:
            async for chunk in request.stream():
                size += len(chunk)
                if size > limit: fail("file_too_large", f"PDF 不能超过 {settings.literature_max_pdf_mb} MB。", 413)
                digest.update(chunk); target.write(chunk)
        with path.open("rb") as source:
            if size == 0 or source.read(5) != b"%PDF-": fail("invalid_pdf", "文件内容不是 PDF。")
        try:
            with fitz.open(path) as pdf:
                if pdf.needs_pass: fail("protected_pdf", "请上传未加密且可正常读取的 PDF。")
                if pdf.page_count < 1: fail("invalid_pdf", "PDF 没有可预览的页面。")
                pdf.load_page(0)
        except HTTPException: raise
        except Exception: fail("invalid_pdf", "PDF 无法正常打开。")
        with db.write():
            duplicate = db.db.execute("SELECT id,usage FROM papers WHERE sha256=? AND deleted=0 LIMIT 1", (digest.hexdigest(),)).fetchone()
            if duplicate: raise HTTPException(409, detail={"code": "duplicate_file", "message": "已有相同内容的 PDF。", "paper_id": duplicate["id"], "usage": duplicate["usage"]})
            db.db.execute("INSERT INTO uploads VALUES (?,?,?,?,?,?,NULL)", (upload_id, filename, digest.hexdigest(), size, user.tester_id, now()))
        return {"upload_id": upload_id, "filename": filename, "sha256": digest.hexdigest(), "size": size}
    except BaseException:
        path.unlink(missing_ok=True)
        raise


@router.post("/extract")
async def extract_paper_fields(request: Request, body: ExtractInput, user: Principal = Depends(current_user)):
    """Suggest metadata from an owned upload or an existing paper; never save it."""
    if bool(body.upload_id) == bool(body.paper_id):
        fail("extract_target_required", "请选择一份已上传或已登记的 PDF。")
    db = store(request)
    if body.upload_id:
        with db.lock:
            row = db.db.execute("SELECT id FROM uploads WHERE id=? AND owner=? AND consumed_at IS NULL",
                                (body.upload_id, user.tester_id)).fetchone()
        if not row:
            fail("upload_not_found", "上传文件已失效，请重新上传。", 404)
        path = db.root / f"upload-{body.upload_id}"
    else:
        paper = db.get_paper(body.paper_id)
        path = db.root / f"blob-{paper['sha256']}.pdf"
        if not path.is_file():
            path = db.root / f"{body.paper_id}.pdf"  # Migrated records keep their original path.
    if not path.is_file():
        fail("pdf_not_found", "PDF 文件不可用。", 404)
    try:
        text, pages = await asyncio.to_thread(read_pdf_for_extraction, path)
    except ValueError as exc:
        fail("pdf_text_unavailable", str(exc), 422)
    except Exception as exc:
        logger.warning("Literature PDF extraction failed: {}", exc)
        fail("pdf_extract_failed", "PDF 读取失败，请稍后重试。", 422)
    local_fields = None
    try:
        local_fields = await asyncio.to_thread(local_suggestions, path)
    except Exception as exc:
        logger.warning("Literature local extraction failed: {}", exc)
    llm = getattr(request.app.state, "llm", None)
    warning = "AI 服务暂不可达，已从 PDF 原文提取可确认的字段；请核对后保存。"
    if llm is not None and time.monotonic() >= getattr(request.app.state, "literature_ai_retry_at", 0.0):
        try:
            fields = await asyncio.wait_for(suggest_fields(text, llm), timeout=18)
            # A model can omit a field that is present in the PDF metadata.
            for key in ("title", "publication_type", "venue", "year", "language", "doi", "abstract"):
                if local_fields is not None and not getattr(fields, key) and getattr(local_fields, key):
                    setattr(fields, key, getattr(local_fields, key))
            request.app.state.literature_ai_retry_at = 0.0
            return {"fields": fields.model_dump(), "pages_read": pages, "method": "ai", "warning": ""}
        except Exception as exc:
            logger.warning("Literature AI extraction unavailable; using local PDF fields: {}", exc)
            if isinstance(exc, ValueError):
                # Malformed output belongs to this document; it is not a service outage.
                warning = "AI 解析结果未通过校验，已使用 PDF 原文字段；请核对后保存。"
            else:
                request.app.state.literature_ai_retry_at = time.monotonic() + 60
    if local_fields is None:
        fail("pdf_extract_failed", "PDF 字段读取失败，请稍后重试或手动填写。", 422)
    return {
        "fields": local_fields.model_dump(), "pages_read": pages, "method": "local",
        "warning": warning,
    }


@router.get("/duplicates")
def duplicates(request: Request, doi: str = "", user: Principal = Depends(current_user)):
    db = store(request); key = doi_key(doi)
    if not key: return {"papers": []}
    with db.lock:
        return {"papers": [{"id": r["id"], "title": json.loads(r["data"])["title"], "usage": r["usage"]} for r in db.db.execute("SELECT id,data,usage FROM papers WHERE deleted=0 AND json_extract(data,'$.doi')=?", (key,))]}


@router.post("/papers")
def create_paper(request: Request, body: PaperInput, user: Principal = Depends(current_user)):
    db = store(request)
    if not body.upload_id: fail("upload_required", "请先上传 PDF。")
    with db.write():
        upload_row = db.db.execute("SELECT * FROM uploads WHERE id=? AND owner=? AND consumed_at IS NULL", (body.upload_id, user.tester_id)).fetchone()
        if not upload_row: fail("upload_not_found", "上传文件已失效，请重新上传。", 404)
        if not (db.root / f"upload-{body.upload_id}").is_file(): fail("upload_not_found", "上传文件已失效，请重新上传。", 404)
        duplicate = db.db.execute("SELECT id FROM papers WHERE sha256=? AND deleted=0", (upload_row["sha256"],)).fetchone()
        if duplicate: raise HTTPException(409, detail={"code": "duplicate_file", "message": "已有相同内容的 PDF。", "paper_id": duplicate["id"]})
        data = validate_paper(db, body)
        if not data["title"]: data["title"] = Path(upload_row["filename"]).stem[:500]
        paper_id = "P-" + secrets.token_hex(8).upper(); at = now()
        db.preserve_upload(upload_row)
        db.db.execute("INSERT INTO papers (id,data,filename,sha256,registration,usage,deleted,created_by,created_at,updated_by,updated_at,registered_by,registered_at) VALUES (?,?,?,?,?,'normal',0,?,?,?,?,?,?)", (paper_id, json.dumps(data, ensure_ascii=False), upload_row["filename"], upload_row["sha256"], "registered" if body.action == "register" else "draft", user.tester_id, at, user.tester_id, at, user.tester_id if body.action == "register" else None, at if body.action == "register" else None))
        db.db.executemany("INSERT INTO paper_tags VALUES (?,?)", [(paper_id, t) for t in data["tag_ids"]])
        db.db.execute("UPDATE uploads SET consumed_at=? WHERE id=?", (at, body.upload_id))
        db.event("paper", paper_id, "register" if body.action == "register" else "create_draft", user.tester_id, after=data)
    return db.get_paper(paper_id, full=True)


@router.put("/papers/{paper_id}")
def update_paper(request: Request, paper_id: str, body: PaperUpdateInput, user: Principal = Depends(current_user)):
    db = store(request)
    with db.write():
        before = db.get_paper(paper_id)
        if body.expected_revision != before["revision"]:
            fail("paper_revision_conflict", "文献已被其他操作更新，当前输入已保留。请查看最新版本后重新编辑。", 409)
        if before["registration"] == "registered" and body.action != "register": fail("registered_cannot_draft", "已登记文献不能退回草稿。")
        data = validate_paper(db, body, paper_id)
        if not data["title"]: data["title"] = before["title"]
        if body.upload_id:
            if before["registration"] != "draft": fail("registered_file_locked", "已登记文献不能替换 PDF，请新增关联文献。")
            up = db.db.execute("SELECT * FROM uploads WHERE id=? AND owner=? AND consumed_at IS NULL", (body.upload_id, user.tester_id)).fetchone()
            if not up: fail("upload_not_found", "上传文件已失效。", 404)
            duplicate = db.db.execute("SELECT id FROM papers WHERE sha256=? AND id!=? AND deleted=0", (up["sha256"], paper_id)).fetchone()
            if duplicate: raise HTTPException(409, detail={"code": "duplicate_file", "message": "已有相同内容的 PDF。", "paper_id": duplicate["id"]})
            db.preserve_upload(up)
            db.db.execute("UPDATE papers SET filename=?, sha256=? WHERE id=?", (up["filename"], up["sha256"], paper_id))
            db.db.execute("UPDATE uploads SET consumed_at=? WHERE id=?", (now(), body.upload_id))
            db.event("paper", paper_id, "replace_file", user.tester_id, before={"filename": before["filename"], "sha256": before["sha256"]}, after={"filename": up["filename"], "sha256": up["sha256"]})
        registration = "registered" if body.action == "register" else "draft"
        db.db.execute("UPDATE papers SET revision=revision+1,data=?,registration=?,updated_by=?,updated_at=?,registered_by=CASE WHEN ?='registered' THEN COALESCE(registered_by,?) ELSE registered_by END,registered_at=CASE WHEN ?='registered' THEN COALESCE(registered_at,?) ELSE registered_at END WHERE id=?", (json.dumps(data, ensure_ascii=False), registration, user.tester_id, now(), registration, user.tester_id, registration, now(), paper_id))
        db.db.execute("DELETE FROM paper_tags WHERE paper_id=?", (paper_id,))
        db.db.executemany("INSERT INTO paper_tags VALUES (?,?)", [(paper_id, t) for t in data["tag_ids"]])
        db.event("paper", paper_id, "register" if before["registration"] == "draft" and registration == "registered" else "edit", user.tester_id, before={k: before.get(k) for k in data}, after=data)
    return db.get_paper(paper_id, full=True)


@router.get("/papers")
def list_papers(request: Request, keyword: str = "", field: str = "all", publication_type: str = "", year_from: int | None = None, year_to: int | None = None, year_unknown: bool = False, language: str = "", registration: str = "all", usage: str = "normal", creators: str = "", editors: str = "", created_from: str = "", created_to: str = "", updated_from: str = "", updated_to: str = "", tags: str = "", include_disabled_tags: bool = False, sort: str = "updated", direction: str = "desc", page: int = Query(1, ge=1), page_size: int = Query(20, ge=1, le=100), user: Principal = Depends(current_user)):
    # Date inputs and displayed timestamps share the library's business timezone.
    bounds = {}
    for key, value in (("created_from", created_from), ("created_to", created_to), ("updated_from", updated_from), ("updated_to", updated_to)):
        if value:
            try:
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value): raise ValueError()
                bounds[key] = date.fromisoformat(value)
            except ValueError:
                fail("invalid_date_filter", "日期格式应为有效的 YYYY-MM-DD。", 422)
    for prefix in ("created", "updated"):
        if bounds.get(prefix + "_from", date.min) > bounds.get(prefix + "_to", date.max):
            fail("invalid_date_filter", "起始日期不能晚于结束日期。", 422)
    db = store(request)
    with db.lock:
        rows = db.db.execute("SELECT * FROM papers WHERE deleted=0").fetchall()
        counts = {"total": len(rows), "draft": sum(r["registration"] == "draft" for r in rows), "registered": sum(r["registration"] == "registered" for r in rows), "disabled": sum(r["usage"] == "disabled" for r in rows)}
        taxonomy = db.taxonomy(); selected = [t for t in tags.split(",") if t]
        chosen_by_dim = {}
        for tid in selected:
            tag = next((t for t in taxonomy["tags"] if t["id"] == tid), None)
            if not tag: fail("invalid_tag", "筛选标签不存在。")
            if not include_disabled_tags and not tag["enabled"]: fail("disabled_tag", "筛选已停用标签时请启用“包含已停用标签”。")
            chosen_by_dim.setdefault(tag["dimension_id"], set()).update(db.descendants(tid, taxonomy["tags"]))
        types = set(filter(None, publication_type.split(","))); langs = set(filter(None, language.split(",")))
        creators_set = set(filter(None, creators.split(","))); editors_set = set(filter(None, editors.split(",")))
        query = keyword.strip().casefold(); key_doi = doi_key(query)
        def match(row):
            p = db.paper(row)
            if registration != "all" and p["registration"] != registration or usage != "all" and p["usage"] != usage: return False
            if types and p["publication_type"] not in types or langs and p["language"] not in langs: return False
            if year_unknown and not p["year_unknown"] or not year_unknown and (year_from is not None and (p["year"] is None or p["year"] < year_from) or year_to is not None and (p["year"] is None or p["year"] > year_to)): return False
            if creators_set and p["created_by"] not in creators_set or editors_set and p["updated_by"] not in editors_set: return False
            for prefix in ("created", "updated"):
                local_date = datetime.fromisoformat(p[prefix + "_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date()
                if local_date < bounds.get(prefix + "_from", date.min) or local_date > bounds.get(prefix + "_to", date.max): return False
            if query:
                values = {"id": p["id"], "title": p["title"], "authors": " ".join(a["name"] if isinstance(a, dict) else a for a in p["authors"]), "venue": p["venue"], "doi": p["doi"]}
                fields = values if field == "all" else {field: values.get(field, "")}
                if not any((str(v).casefold() == query if k == "id" else (bool(key_doi) and key_doi in str(v).casefold() if k == "doi" else query in str(v).casefold())) for k,v in fields.items()): return False
            grouped = {}
            by_id = {t["id"]: t for t in taxonomy["tags"]}
            for tid in p["tag_ids"]:
                if tid in by_id: grouped.setdefault(by_id[tid]["dimension_id"], set()).add(tid)
            return all(grouped.get(did, set()) & allowed for did,allowed in chosen_by_dim.items())
        papers = [db.paper(r) for r in rows if match(r)]
        reverse = direction != "asc"
        if sort == "year": papers.sort(key=lambda p: (p["year"] is None, -(p["year"] or 0) if reverse else p["year"] or 0, p["id"]))
        else: papers.sort(key=lambda p: (p["created_at"] if sort == "created" else p["updated_at"], p["id"]), reverse=reverse)
        start = (page - 1) * page_size
        return {"counts": counts, "total": len(papers), "page": page, "page_size": page_size, "items": papers[start:start+page_size]}


@router.get("/papers/{paper_id}")
def get_paper(request: Request, paper_id: str, user: Principal = Depends(current_user)):
    return store(request).get_paper(paper_id, full=True)


@router.get("/papers/{paper_id}/file")
def paper_file(request: Request, paper_id: str, download: bool = False, user: Principal = Depends(current_user)):
    db = store(request); paper = db.get_paper(paper_id)
    path = db.root / f"blob-{paper['sha256']}.pdf"
    if not path.is_file():
        path = db.root / f"{paper_id}.pdf"  # Existing libraries retain their files.
    if not path.is_file(): fail("file_unavailable", "原文件不可用。", 404)
    return FileResponse(path, media_type="application/pdf", filename=paper["filename"], content_disposition_type="attachment" if download else "inline")


@router.post("/papers/{paper_id}/disable")
def disable_paper(request: Request, paper_id: str, body: ReasonInput, user: Principal = Depends(current_user)):
    db = store(request)
    if not body.reason.strip(): fail("reason_required", "请填写停用原因。")
    with db.write():
        before = db.get_paper(paper_id)
        if before["usage"] == "disabled": fail("already_disabled", "文献已停用。", 409)
        db.db.execute("UPDATE papers SET revision=revision+1,usage='disabled',updated_by=?,updated_at=? WHERE id=?", (user.tester_id, now(), paper_id))
        db.event("paper", paper_id, "disable", user.tester_id, before={"usage": before["usage"]}, after={"usage": "disabled"}, reason=body.reason.strip())
    return db.get_paper(paper_id)


@router.post("/papers/{paper_id}/restore")
def restore_paper(request: Request, paper_id: str, user: Principal = Depends(current_user)):
    db = store(request)
    with db.write():
        before = db.get_paper(paper_id)
        if before["usage"] == "normal": fail("already_normal", "文献已处于正常状态。", 409)
        db.db.execute("UPDATE papers SET revision=revision+1,usage='normal',updated_by=?,updated_at=? WHERE id=?", (user.tester_id, now(), paper_id))
        db.event("paper", paper_id, "restore", user.tester_id, before={"usage": before["usage"]}, after={"usage": "normal"})
    return db.get_paper(paper_id)


@router.post("/papers/{paper_id}/delete")
def delete_paper(request: Request, paper_id: str, body: ReasonInput, user: Principal = Depends(current_user)):
    db = store(request)
    if not body.reason.strip(): fail("reason_required", "请填写删除原因。")
    with db.write():
        before = db.get_paper(paper_id)
        db.db.execute("UPDATE papers SET revision=revision+1,deleted=1,updated_by=?,updated_at=? WHERE id=?", (user.tester_id, now(), paper_id))
        db.event("paper", paper_id, "delete", user.tester_id, before={"title": before["title"]}, reason=body.reason.strip())
    return {"deleted": True}


@router.post("/dimensions")
def create_dimension(request: Request, body: DimensionInput, user: Principal = Depends(current_user)):
    db = store(request); identifier = "D-" + secrets.token_hex(6); at = now()
    if not body.name.strip(): fail("dimension_name_required", "请填写维度名称。")
    with db.write():
        try: db.db.execute("INSERT INTO dimensions VALUES (?,?,?,?,?,?,?,?,?)", (identifier, body.name.strip(), body.description.strip(), body.selection, int(body.required), int(body.enabled), body.sort_order, at, at))
        except sqlite3.IntegrityError: fail("dimension_name_conflict", "维度名称已存在。", 409)
        db.event("dimension", identifier, "create", user.tester_id, after=body.model_dump())
    return {"id": identifier}


@router.put("/dimensions/{dimension_id}")
def update_dimension(request: Request, dimension_id: str, body: DimensionInput, user: Principal = Depends(current_user)):
    db = store(request)
    if not body.name.strip(): fail("dimension_name_required", "请填写维度名称。")
    with db.write():
        old = db.db.execute("SELECT * FROM dimensions WHERE id=?", (dimension_id,)).fetchone()
        if not old: fail("dimension_not_found", "维度不存在。", 404)
        if old["selection"] == "multiple" and body.selection == "single":
            count = db.db.execute("SELECT 1 FROM paper_tags pt JOIN tags t ON t.id=pt.tag_id JOIN papers p ON p.id=pt.paper_id WHERE t.dimension_id=? AND p.deleted=0 GROUP BY p.id HAVING COUNT(*)>1 LIMIT 1", (dimension_id,)).fetchone()
            if count: fail("dimension_in_use", "已有文献在此维度使用多个标签，请先调整文献。", 409)
        try: db.db.execute("UPDATE dimensions SET name=?,description=?,selection=?,required=?,enabled=?,sort_order=?,updated_at=? WHERE id=?", (body.name.strip(), body.description.strip(), body.selection, int(body.required), int(body.enabled), body.sort_order, now(), dimension_id))
        except sqlite3.IntegrityError: fail("dimension_name_conflict", "维度名称已存在。", 409)
        db.event("dimension", dimension_id, "edit", user.tester_id, before=dict(old), after=body.model_dump())
    return {"id": dimension_id}


@router.delete("/dimensions/{dimension_id}")
def delete_dimension(request: Request, dimension_id: str, user: Principal = Depends(current_user)):
    db = store(request)
    with db.write():
        old = db.db.execute("SELECT * FROM dimensions WHERE id=?", (dimension_id,)).fetchone()
        if not old: fail("dimension_not_found", "维度不存在。", 404)
        if db.db.execute("SELECT 1 FROM tags WHERE dimension_id=?", (dimension_id,)).fetchone(): fail("dimension_in_use", "维度包含标签，请先停用。", 409)
        db.db.execute("DELETE FROM dimensions WHERE id=?", (dimension_id,))
        db.event("dimension", dimension_id, "delete", user.tester_id, before=dict(old))
    return {"deleted": True}


def validate_tag(db: LiteratureStore, dimension_id: str, body: TagInput, self_id: str | None = None):
    if not body.name.strip(): fail("tag_name_required", "请填写标签名称。")
    if not db.db.execute("SELECT 1 FROM dimensions WHERE id=?", (dimension_id,)).fetchone(): fail("dimension_not_found", "维度不存在。", 404)
    parent = db.db.execute("SELECT * FROM tags WHERE id=?", (body.parent_id,)).fetchone() if body.parent_id else None
    if body.parent_id and (not parent or parent["dimension_id"] != dimension_id): fail("invalid_parent", "父标签须位于同一维度。")
    if parent:
        level, node = 2, parent
        while node["parent_id"]:
            if node["id"] == self_id: fail("tag_cycle", "不能将标签移动到自身的后代。")
            level += 1; node = db.db.execute("SELECT * FROM tags WHERE id=?", (node["parent_id"],)).fetchone()
        if level > 5: fail("tag_depth", "标签最多五级。")
    sibling = db.db.execute("SELECT id FROM tags WHERE dimension_id=? AND parent_id IS ? AND name=? COLLATE NOCASE AND id!=?", (dimension_id, body.parent_id, body.name.strip(), self_id or "")).fetchone()
    if sibling: fail("tag_name_conflict", "同级标签名称已存在。", 409)


@router.post("/dimensions/{dimension_id}/tags")
def create_tag(request: Request, dimension_id: str, body: TagInput, user: Principal = Depends(current_user)):
    db = store(request); identifier = "T-" + secrets.token_hex(6); at = now()
    with db.write():
        validate_tag(db, dimension_id, body)
        db.db.execute("INSERT INTO tags VALUES (?,?,?,?,?,?,?,?,?)", (identifier, dimension_id, body.parent_id, body.name.strip(), body.description.strip(), int(body.enabled), body.sort_order, at, at))
        db.event("tag", identifier, "create", user.tester_id, after=body.model_dump())
    return {"id": identifier}


@router.put("/tags/{tag_id}")
def update_tag(request: Request, tag_id: str, body: TagInput, user: Principal = Depends(current_user)):
    db = store(request)
    with db.write():
        old = db.db.execute("SELECT * FROM tags WHERE id=?", (tag_id,)).fetchone()
        if not old: fail("tag_not_found", "标签不存在。", 404)
        validate_tag(db, old["dimension_id"], body, tag_id)
        descendants = db.descendants(tag_id, db.taxonomy()["tags"])
        if body.parent_id in descendants: fail("tag_cycle", "不能移动到自身或后代。")
        if body.parent_id:
            level = 1; node = db.db.execute("SELECT * FROM tags WHERE id=?", (body.parent_id,)).fetchone()
            while node: level += 1; node = db.db.execute("SELECT * FROM tags WHERE id=?", (node["parent_id"],)).fetchone() if node["parent_id"] else None
            sublevels = {tag_id: 1}
            while True:
                changed = False
                for t in db.taxonomy()["tags"]:
                    if t["parent_id"] in sublevels and t["id"] in descendants and t["id"] not in sublevels:
                        sublevels[t["id"]] = sublevels[t["parent_id"]] + 1; changed = True
                if not changed: break
            if level + max(sublevels.values()) - 1 > 5: fail("tag_depth", "移动后标签会超过五级。")
        if body.parent_id != old["parent_id"]:
            proposed = db.taxonomy()["tags"]
            for tag in proposed:
                if tag["id"] == tag_id: tag["parent_id"] = body.parent_id
            for (paper_id,) in db.db.execute("SELECT DISTINCT pt.paper_id FROM paper_tags pt JOIN papers p ON p.id=pt.paper_id WHERE p.deleted=0"):
                assigned = {r[0] for r in db.db.execute("SELECT tag_id FROM paper_tags WHERE paper_id=?", (paper_id,))}
                if any((db.descendants(tid, proposed) - {tid}) & assigned for tid in assigned):
                    fail("tag_move_conflict", "移动后已有文献会同时关联祖先和后代标签，请先调整文献。", 409)
        db.db.execute("UPDATE tags SET parent_id=?,name=?,description=?,enabled=?,sort_order=?,updated_at=? WHERE id=?", (body.parent_id, body.name.strip(), body.description.strip(), int(body.enabled), body.sort_order, now(), tag_id))
        db.event("tag", tag_id, "edit", user.tester_id, before=dict(old), after=body.model_dump())
    return {"id": tag_id}


@router.delete("/tags/{tag_id}")
def delete_tag(request: Request, tag_id: str, user: Principal = Depends(current_user)):
    db = store(request)
    with db.write():
        old = db.db.execute("SELECT * FROM tags WHERE id=?", (tag_id,)).fetchone()
        if not old: fail("tag_not_found", "标签不存在。", 404)
        if db.db.execute("SELECT 1 FROM tags WHERE parent_id=?", (tag_id,)).fetchone() or db.db.execute("SELECT 1 FROM paper_tags WHERE tag_id=?", (tag_id,)).fetchone(): fail("tag_in_use", "标签有子标签或关联文献，请先停用。", 409)
        db.db.execute("DELETE FROM tags WHERE id=?", (tag_id,))
        db.event("tag", tag_id, "delete", user.tester_id, before=dict(old))
    return {"deleted": True}


@router.get("/events/{entity}/{entity_id}")
def events(request: Request, entity: Literal["paper", "tag", "dimension"], entity_id: str, user: Principal = Depends(current_user)):
    return store(request).events(entity, entity_id)
