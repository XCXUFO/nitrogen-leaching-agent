"""Bounded expression preferences; factual rules and routing are never editable."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from src.agent.contracts import Contract


class ExpressionPreferences(Contract):
    style: Literal["plain", "professional"] = "plain"
    detail: Literal["short", "medium", "detailed"] = "medium"
    organization: Literal["answer_first", "steps"] = "answer_first"


class ExpressionUpdate(Contract):
    expected_revision: int = Field(ge=0)
    values: ExpressionPreferences


class ExpressionReset(Contract):
    expected_revision: int = Field(ge=0)


class SkillConfigurations:
    def __init__(self, connection, lock):
        self.db, self.lock = connection, lock
        with lock, connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS skill_expression_revisions (
                revision INTEGER PRIMARY KEY, version TEXT NOT NULL, actor TEXT NOT NULL,
                changed_at TEXT NOT NULL, action TEXT NOT NULL, values_json TEXT NOT NULL)""")

    def _current(self):
        row = self.db.execute("SELECT revision,version,actor,changed_at,action,values_json FROM skill_expression_revisions ORDER BY revision DESC LIMIT 1").fetchone()
        if not row:
            return {"revision": 0, "version": "case-expression-v1:0", "actor": "builtin", "changed_at": None,
                    "action": "default", "values": ExpressionPreferences().model_dump(), "fallback": False}
        return dict(zip(("revision", "version", "actor", "changed_at", "action"), row[:5])) | {
            "values": ExpressionPreferences.model_validate_json(row[5]).model_dump(), "fallback": False}

    def current(self):
        with self.lock:
            return self._current()

    def history(self):
        with self.lock:
            rows = self.db.execute("SELECT revision,version,actor,changed_at,action,values_json FROM skill_expression_revisions ORDER BY revision DESC LIMIT 50").fetchall()
        return [dict(zip(("revision", "version", "actor", "changed_at", "action"), row[:5])) | {"values": json.loads(row[5])} for row in rows]

    def update(self, *, expected_revision, values, actor, reset=False):
        preferences = ExpressionPreferences() if reset else ExpressionPreferences.model_validate(values)
        with self.lock:
            try:
                self.db.execute("BEGIN IMMEDIATE")
                current = self._current()
                if current["revision"] != expected_revision:
                    raise HTTPException(409, detail={"code": "skill_config_conflict", "message": "配置已被其他人修改。输入已保留，请读取最新版本后再保存。"})
                revision = expected_revision + 1
                self.db.execute("INSERT INTO skill_expression_revisions VALUES (?,?,?,?,?,?)", (
                    revision, f"case-expression-v1:{revision}", actor, datetime.now(timezone.utc).isoformat(),
                    "reset" if reset else "save", preferences.model_dump_json()))
                result = self._current()
                self.db.commit()
                return result
            except BaseException:
                self.db.rollback()
                raise


def expression_instructions(snapshot: dict) -> str:
    preferences = ExpressionPreferences.model_validate(snapshot["values"])
    return ("以下仅为用户未明确指定表达方式时的默认偏好；本轮用户的深度、风格和组织要求优先。"
            "这些偏好可调整上文的默认篇幅，但不改变来源、数字、条件、权限、JSON输出或其他专业约束。默认风格：" +
            {"plain": "简洁易懂，先解释必要术语", "professional": "保留必要专业术语并解释含义"}[preferences.style] +
            "；默认详细程度：" + {"short": "简短", "medium": "适中", "detailed": "详细但只解释相关内容"}[preferences.detail] +
            "；默认组织：" + {"answer_first": "先回应问题，再补背景和例子", "steps": "按相关步骤组织"}[preferences.organization] + "。")
