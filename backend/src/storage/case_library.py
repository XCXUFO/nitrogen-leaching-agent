"""Small, authoritative case store; publishing needs no asynchronous index."""
from __future__ import annotations

import json
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
        self.db.commit()

    def close(self):
        self.db.close()

    def get(self, case_id: str, *, public: bool = False):
        with self.lock:
            row = self.db.execute("SELECT * FROM reference_cases WHERE id=? AND deleted=0" +
                                  (" AND enabled=1" if public else ""), (case_id,)).fetchone()
            if row is None:
                fail(404, "case_unavailable", "案例不存在或当前不可用。")
            return dict(row)

    def list(self, keyword="", availability="all", page=1, page_size=20):
        where, params = "deleted=0", []
        if keyword:
            where += " AND instr(lower(title), lower(?))>0"
            params.append(keyword)
        if availability != "all":
            where += " AND enabled=?"
            params.append(int(availability == "enabled"))
        with self.lock:
            total = self.db.execute(f"SELECT count(*) FROM reference_cases WHERE {where}", params).fetchone()[0]
            rows = self.db.execute(f"SELECT id,title,body,body_format, explanation!='' AS has_explanation,enabled,revision,updated_by,updated_at FROM reference_cases WHERE {where} ORDER BY updated_at DESC,id LIMIT ? OFFSET ?",
                                   [*params, page_size, (page - 1) * page_size]).fetchall()
            items = []
            for row in rows:
                item = dict(row)
                item["summary"] = body_summary(item.pop("body"), item.pop("body_format"))
                items.append(item)
            return {"items": items, "total": total, "page": page, "page_size": page_size}

    def create(self, body: CaseInput, actor: str):
        now = datetime.now(timezone.utc).isoformat()
        value = {"id": "C-" + uuid4().hex[:16].upper(), **body.model_dump(), "revision": 1,
                 "created_by": actor, "created_at": now, "updated_by": actor, "updated_at": now}
        with self.lock, self.db:
            self.db.execute(f"INSERT INTO reference_cases ({','.join(value)}) VALUES ({','.join('?' for _ in value)})", list(value.values()))
        return self.get(value["id"])

    def change(self, case_id: str, revision: int, values: dict, actor: str):
        # CAS is enforced in SQL, including across separate backend processes.
        values = {**values, "updated_by": actor, "updated_at": datetime.now(timezone.utc).isoformat()}
        with self.lock, self.db:
            result = self.db.execute(f"UPDATE reference_cases SET {','.join(k+'=?' for k in values)}, revision=revision+1 WHERE id=? AND revision=? AND deleted=0",
                                     [*values.values(), case_id, revision])
            if result.rowcount != 1:
                self.get(case_id)
                fail(409, "case_conflict", "内容已被其他人更新。已保留你的输入，请查看最新内容后再保存。")
            return {"deleted": True} if values.get("deleted") else self.get(case_id)

    def available(self, case_ids: list[str] | None = None, *, max_chars=24000, max_cases=30):
        """Bound small pilot corpus as a whole; never silently omit/truncate facts."""
        with self.lock:
            sql = "SELECT id,title,body,body_format,explanation,supplementary,source FROM reference_cases WHERE enabled=1 AND deleted=0"
            params = []
            if case_ids:
                sql += f" AND id IN ({','.join('?' for _ in case_ids)})"
                params.extend(case_ids)
            rows = self.db.execute(sql + " ORDER BY updated_at DESC,id LIMIT ?", [*params, max_cases + 1]).fetchall()
            result = [dict(r) for r in rows]
        if len(result) > max_cases or len(json.dumps(result, ensure_ascii=False)) > max_chars:
            fail(413, "case_capacity", "已开放案例超过本期调用容量（30 条／24000 字符）。请指定案例 ID 或缩小开放范围后重试。")
        return result
