"""Immutable shared Prompt versions and a single active selection."""
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException

from src.agent.explanation_method import METHOD_PROMPT
from src.agent.skill_config import ExpressionPreferences, expression_instructions

# Keep the existing baseline and candidate expression instructions verbatim.
# Task-specific grounding / output contracts remain part of each task's system prompt.
LEGACY_PROMPT = expression_instructions({"values": ExpressionPreferences().model_dump()})
ENHANCED_PROMPT = LEGACY_PROMPT + METHOD_PROMPT


def prompt_snapshot(label, text):
    digest = hashlib.sha256(text.encode()).hexdigest()
    return {"label": label, "text": text, "sha256": digest, "version": "prompt-" + digest[:12]}


class PromptVersions:
    def __init__(self, connection, lock):
        self.db, self.lock = connection, lock
        with lock, connection:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS prompt_versions (
                    prompt_id TEXT PRIMARY KEY, actor TEXT NOT NULL, label TEXT NOT NULL,
                    sha256 TEXT NOT NULL, payload TEXT NOT NULL, UNIQUE(actor,label,sha256));
                CREATE TABLE IF NOT EXISTS active_prompt (
                    singleton INTEGER PRIMARY KEY CHECK(singleton=1), prompt_id TEXT NOT NULL,
                    actor TEXT NOT NULL, changed_at TEXT NOT NULL);
            """)
            for label, text in (("原版解释 v1", LEGACY_PROMPT), ("增强解释 v2", ENHANCED_PROMPT)):
                value = self._save(label, text, "builtin")
            self.db.execute("INSERT OR IGNORE INTO active_prompt VALUES (1,?,?,?)",
                            (value["prompt_id"], "builtin", value["created_at"]))

    def _save(self, label, text, actor):
        value = {**prompt_snapshot(label, text), "prompt_id": str(uuid4()), "actor": actor,
                 "created_at": datetime.now(timezone.utc).isoformat()}
        self.db.execute("INSERT OR IGNORE INTO prompt_versions VALUES (?,?,?,?,?)",
            (value["prompt_id"], actor, label, value["sha256"], json.dumps(value, ensure_ascii=False)))
        row = self.db.execute("SELECT payload FROM prompt_versions WHERE actor=? AND label=? AND sha256=?",
                              (actor, label, value["sha256"])).fetchone()
        return json.loads(row[0])

    def save(self, label, text, actor):
        with self.lock, self.db:
            return self._save(label, text, actor)

    def list(self):
        with self.lock:
            return [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM prompt_versions ORDER BY rowid DESC")]

    def active(self):
        with self.lock:
            row = self.db.execute("SELECT p.payload,a.actor,a.changed_at FROM active_prompt a JOIN prompt_versions p ON p.prompt_id=a.prompt_id WHERE a.singleton=1").fetchone()
        return {**json.loads(row[0]), "activated_by": row[1], "activated_at": row[2]}

    def activate(self, prompt_id, actor):
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM prompt_versions WHERE prompt_id=?", (prompt_id,)).fetchone():
                raise HTTPException(404, detail={"code": "prompt_not_found", "message": "未找到已保存的 Prompt 版本。"})
            self.db.execute("UPDATE active_prompt SET prompt_id=?,actor=?,changed_at=? WHERE singleton=1",
                (prompt_id, actor, datetime.now(timezone.utc).isoformat()))
        return self.active()
