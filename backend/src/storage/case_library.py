"""Small, authoritative case store; publishing needs no asynchronous index."""
from __future__ import annotations

import json
import hashlib
import re
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field, field_validator, model_validator


from src.storage.case_content import BodyFormat, normalize_body, body_summary

def fail(status: int, code: str, message: str):
    raise HTTPException(status, detail={"code": code, "message": message})


class CaseInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=50000)
    body_format: BodyFormat = "plain"
    explanation: str = Field(default="", max_length=30000)
    supplementary: str = Field(default="", max_length=10000)
    source: str = Field(default="", max_length=4000)
    enabled: bool = False
    tag_ids: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("title", "body")
    @classmethod
    def required(cls, value):
        if not value.strip():
            raise ValueError("不能为空")
        return value.strip()


    @model_validator(mode="after")
    def rich_body(self):
        self.body = normalize_body(self.body, self.body_format)
        return self


class CaseUpdate(CaseInput):
    expected_revision: int = Field(ge=1)


class RevisionInput(BaseModel):
    expected_revision: int = Field(ge=1)


class AvailabilityInput(RevisionInput):
    enabled: bool


class CaseStore:
    def __init__(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        self.db.execute('''CREATE TABLE IF NOT EXISTS reference_cases (
            id TEXT PRIMARY KEY, title TEXT NOT NULL, body TEXT NOT NULL,
            explanation TEXT NOT NULL, supplementary TEXT NOT NULL, source TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0, deleted INTEGER NOT NULL DEFAULT 0,
            revision INTEGER NOT NULL, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
            updated_by TEXT NOT NULL, updated_at TEXT NOT NULL)''')
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(reference_cases)")}
        if "body_format" not in columns:
            self.db.execute("ALTER TABLE reference_cases ADD COLUMN body_format TEXT NOT NULL DEFAULT 'plain'")
        if "tag_ids" not in columns:
            self.db.execute("ALTER TABLE reference_cases ADD COLUMN tag_ids TEXT NOT NULL DEFAULT '[]'")
        self.db.execute("""CREATE TABLE IF NOT EXISTS case_gaps (
            fingerprint TEXT PRIMARY KEY, question TEXT NOT NULL, context TEXT NOT NULL,
            occurrences INTEGER NOT NULL DEFAULT 1, updated_at TEXT NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS case_tag_jobs (
            id TEXT PRIMARY KEY, owner TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL)""")
        self.db.commit()

    def record_gap(self, question: str, context: str = ""):
        fingerprint = hashlib.sha256(json.dumps([question.strip(), context.strip()], ensure_ascii=False).encode()).hexdigest()
        with self.lock, self.db:
            self.db.execute("""INSERT INTO case_gaps (fingerprint,question,context,updated_at) VALUES (?,?,?,?)
                ON CONFLICT(fingerprint) DO UPDATE SET occurrences=occurrences+1, updated_at=excluded.updated_at""",
                (fingerprint, question, context, datetime.now(timezone.utc).isoformat()))

    def gaps(self):
        with self.lock:
            return [dict(row) for row in self.db.execute("SELECT * FROM case_gaps ORDER BY occurrences DESC,updated_at DESC LIMIT 100")]

    @staticmethod
    def content_key(item):
        # Keep table structure, numbers, regions and conflicting explanations distinct.
        return tuple(re.sub(r"\s+", " ", item.get(field, "")).strip()
                     for field in ("title", "body", "body_format", "explanation", "supplementary", "source"))

    def duplicates(self):
        with self.lock:
            rows = self.db.execute("SELECT * FROM reference_cases WHERE deleted=0 ORDER BY created_at,id").fetchall()
        groups = {}
        for row in rows:
            item = dict(row)
            groups.setdefault(self.content_key(item), []).append({"id": item["id"], "title": item["title"]})
        return [group for group in groups.values() if len(group) > 1]

    def close(self):
        self.db.close()

    def get(self, case_id: str, *, public: bool = False):
        with self.lock:
            row = self.db.execute("SELECT * FROM reference_cases WHERE id=? AND deleted=0" +
                                  (" AND enabled=1" if public else ""), (case_id,)).fetchone()
            if row is None:
                fail(404, "case_unavailable", "案例不存在或当前不可用。")
            return dict(row) | {"tag_ids": json.loads(row["tag_ids"])}

    def list(self, keyword="", availability="all", page=1, page_size=20, *, tag_groups=None, untagged=False, tag_status="all"):
        where, params = "deleted=0", []
        if keyword:
            where += " AND (" + " OR ".join(f"instr(lower({field}), lower(?))>0" for field in ("title", "body", "explanation", "supplementary", "source")) + ")"
            params.extend([keyword] * 5)
        if availability != "all":
            where += " AND enabled=?"
            params.append(int(availability == "enabled"))
        if untagged or tag_status == "untagged":
            where += " AND json_array_length(tag_ids)=0"
        elif tag_status == "tagged":
            where += " AND json_array_length(tag_ids)>0"
        for group in tag_groups or []:
            where += " AND EXISTS (SELECT 1 FROM json_each(tag_ids) WHERE value IN (" + ",".join("?" for _ in group) + "))"
            params.extend(sorted(group))
        with self.lock:
            total = self.db.execute(f"SELECT count(*) FROM reference_cases WHERE {where}", params).fetchone()[0]
            rows = self.db.execute(f"SELECT id,title,body,body_format,tag_ids, explanation!='' AS has_explanation,enabled,revision,updated_by,updated_at FROM reference_cases WHERE {where} ORDER BY updated_at DESC,id LIMIT ? OFFSET ?",
                                   [*params, page_size, (page - 1) * page_size]).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["tag_ids"] = json.loads(item["tag_ids"])
                item["summary"] = body_summary(item.pop("body"), item.pop("body_format"))
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def create(self, body: CaseInput, actor: str):
        now = datetime.now(timezone.utc).isoformat()
        value = {"id": "C-" + uuid4().hex[:16].upper(), **body.model_dump(), "revision": 1,
                 "created_by": actor, "created_at": now, "updated_by": actor, "updated_at": now}
        value["tag_ids"] = json.dumps(value["tag_ids"])
        with self.lock, self.db:
            self.db.execute(f"INSERT INTO reference_cases ({','.join(value)}) VALUES ({','.join('?' for _ in value)})", list(value.values()))
        return self.get(value["id"])

    def change(self, case_id: str, revision: int, values: dict, actor: str):
        # CAS is enforced in SQL, including across separate backend processes.
        values = {**values, "updated_by": actor, "updated_at": datetime.now(timezone.utc).isoformat()}
        if "tag_ids" in values:
            values["tag_ids"] = json.dumps(values["tag_ids"])
        with self.lock, self.db:
            result = self.db.execute(f"UPDATE reference_cases SET {','.join(k+'=?' for k in values)}, revision=revision+1 WHERE id=? AND revision=? AND deleted=0",
                                     [*values.values(), case_id, revision])
            if result.rowcount != 1:
                self.get(case_id)
                fail(409, "case_conflict", "内容已被其他人更新。已保留你的输入，请查看最新内容后再保存。")
            return {"deleted": True} if values.get("deleted") else self.get(case_id)

    def batch_availability(self, items, enabled: bool, actor: str):
        now = datetime.now(timezone.utc).isoformat()
        with self.lock, self.db:
            for item in items:
                result = self.db.execute(
                    "UPDATE reference_cases SET enabled=?, revision=revision+1, updated_by=?, updated_at=? WHERE id=? AND revision=? AND deleted=0",
                    (int(enabled), actor, now, item.case_id, item.expected_revision))
                if result.rowcount != 1:
                    fail(409, "case_conflict", "部分案例已被修改或删除，本批次未作任何更改。请刷新列表后重新选择。")
        return {"updated": len(items), "enabled": enabled}

    def tag_assignments(self, *, include_deleted=False):
        with self.lock:
            rows = self.db.execute("SELECT tag_ids FROM reference_cases" +
                                   ("" if include_deleted else " WHERE deleted=0")).fetchall()
            return [set(json.loads(row[0])) for row in rows]

    def tag_counts(self):
        counts = {}
        for assigned in self.tag_assignments():
            for identifier in assigned:
                counts[identifier] = counts.get(identifier, 0) + 1
        return counts

    def available(self, case_ids: list[str] | None = None, *, max_chars=24000, max_cases=30):
        """Bound small pilot corpus as a whole; never silently omit/truncate facts."""
        with self.lock:
            sql = "SELECT id,title,body,body_format,explanation,supplementary,source FROM reference_cases WHERE enabled=1 AND deleted=0"
            params = []
            if case_ids:
                sql += f" AND id IN ({','.join('?' for _ in case_ids)})"
                params.extend(case_ids)
            rows = self.db.execute(sql + " ORDER BY updated_at DESC,id", params).fetchall()
            result = [dict(r) for r in rows]
            if not case_ids:
                result = list({self.content_key(item): item for item in reversed(result)}.values())
        if len(result) > max_cases or len(json.dumps(result, ensure_ascii=False)) > max_chars:
            fail(413, "case_capacity", "已开放案例超过本期调用容量（30 条／24000 字符）。请指定案例 ID 或缩小开放范围后重试。")
        return result
