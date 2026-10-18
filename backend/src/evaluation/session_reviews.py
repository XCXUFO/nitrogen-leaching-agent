"""Small, shared human review log attached directly to saved conversations."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Literal

from fastapi import HTTPException
from pydantic import Field, model_validator

from src.agent.contracts import Contract


def fail(code, message, status=409):
    raise HTTPException(status, detail={"code": code, "message": message})


class SessionReviewInput(Contract):
    action_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=0)
    action: Literal["pass", "issue", "comment", "resolve", "reopen"]
    run_ids: list[str] = Field(default_factory=list, max_length=10000)
    run_id: str | None = Field(default=None, max_length=100)
    issue_id: str | None = Field(default=None, max_length=100)
    note: str = Field(default="", max_length=5000)
    verification_run_id: str | None = Field(default=None, max_length=100)

    @model_validator(mode="after")
    def validate_action(self):
        self.note = self.note.strip()
        if self.action in {"issue", "comment", "reopen"} and not self.note:
            raise ValueError("请填写具体意见")
        if self.action == "issue" and not self.run_id:
            raise ValueError("请选择有问题的回答")
        if self.action in {"resolve", "reopen"} and not self.issue_id:
            raise ValueError("缺少原问题")
        if self.action == "pass" and not self.run_ids:
            raise ValueError("请先读取会话")
        return self


class SessionRetestInput(Contract):
    submission_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    source_run_id: str = Field(min_length=1, max_length=100)
    issue_id: str | None = Field(default=None, max_length=100)


class SessionReviews:
    def __init__(self, connection, lock):
        self.db, self.lock = connection, lock
        with lock, connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS session_review_state (
                    session_id TEXT PRIMARY KEY, revision INTEGER NOT NULL,
                    reviewed_count INTEGER NOT NULL, open_count INTEGER NOT NULL,
                    issues_json TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS session_review_events (
                    session_id TEXT NOT NULL, action_id TEXT NOT NULL,
                    revision INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(session_id, action_id));
                CREATE INDEX IF NOT EXISTS session_review_history
                    ON session_review_events(session_id, revision);
                CREATE VIEW IF NOT EXISTS reviewed_sessions AS
                    SELECT s.*, COALESCE(r.revision,0) AS review_revision,
                        COALESCE(r.reviewed_count,0) AS reviewed_turn_count,
                        COALESCE(r.open_count,0) AS open_issue_count,
                        CASE WHEN COALESCE(r.open_count,0)>0 THEN 'needs_changes'
                             WHEN COALESCE(r.reviewed_count,0)<s.turn_count THEN 'pending'
                             ELSE 'passed' END AS review_status
                    FROM chat_sessions s LEFT JOIN session_review_state r USING(session_id)
                    WHERE NOT EXISTS (SELECT 1 FROM agent_runs a WHERE a.session_id=s.session_id
                        AND json_extract(a.payload,'$.replay_of_run_id') IS NOT NULL);
            """)

    def _state(self, session_id):
        row = self.db.execute("SELECT revision, reviewed_count, issues_json FROM session_review_state WHERE session_id=?", (session_id,)).fetchone()
        return (row[0], row[1], json.loads(row[2])) if row else (0, 0, [])

    def _turn_ids(self, session_id):
        if not self.db.execute("SELECT 1 FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone():
            fail("session_not_found", "未找到会话记录。", 404)
        return [row[0] for row in self.db.execute("SELECT run_id FROM agent_runs WHERE session_id=? ORDER BY started_at,rowid", (session_id,))]

    def _save(self, session_id, action_id, revision, reviewed_count, issues, event):
        event = {**event, "revision": revision, "recorded_at": datetime.now(timezone.utc).isoformat(), "review_kind": "human"}
        self.db.execute("INSERT INTO session_review_events VALUES (?,?,?,?)", (session_id, action_id, revision, json.dumps(event, ensure_ascii=False)))
        self.db.execute("INSERT OR REPLACE INTO session_review_state VALUES (?,?,?,?,?)", (session_id, revision, reviewed_count,
            sum(item["status"] == "open" for item in issues), json.dumps(issues, ensure_ascii=False)))

    def detail_locked(self, session_id):
        revision, reviewed_count, issues = self._state(session_id)
        events = [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM session_review_events WHERE session_id=? ORDER BY revision", (session_id,))]
        retests = []
        for event in events:
            if event["action"] != "retest":
                continue
            item = {key: event.get(key) for key in ("run_id", "source_run_id", "issue_id", "recorded_by", "recorded_at")}
            row = self.db.execute("SELECT status,result_json,error_json FROM chat_submissions WHERE run_id=?", (item["run_id"],)).fetchone()
            trace = self.db.execute("SELECT payload FROM agent_runs WHERE run_id=?", (item["run_id"],)).fetchone()
            item.update(status=row[0] if row else "unknown", answer=None, error=None)
            if row and row[1]:
                item["answer"] = json.loads(row[1]).get("answer")
            if row and row[2]:
                item["error"] = json.loads(row[2]).get("message")
            if trace:
                payload = json.loads(trace[0])
                item.update(answer=payload.get("answer"), config_version=payload.get("config_version"))
            retests.append(item)
        return {"revision": revision, "reviewed_turn_count": reviewed_count, "issues": issues, "history": events, "retests": retests}

    def apply(self, session_id, body: SessionReviewInput, actor: str):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            run_ids = self._turn_ids(session_id)
            previous = self.db.execute("SELECT payload FROM session_review_events WHERE session_id=? AND action_id=?", (session_id, body.action_id)).fetchone()
            if previous:
                if json.loads(previous[0]).get("input") != body.model_dump() or json.loads(previous[0])["recorded_by"] != actor:
                    fail("review_action_conflict", "同一提交标识对应的审核内容不同。")
                return self.detail_locked(session_id)
            revision, reviewed_count, issues = self._state(session_id)
            if revision != body.expected_revision:
                fail("review_changed", "有人更新了审核意见，请刷新记录后继续；当前输入已保留。")
            issue = next((item for item in issues if item["issue_id"] == body.issue_id), None)
            if body.action == "pass":
                if any(item["status"] == "open" for item in issues):
                    fail("unresolved_issues", "请先确认已标记的问题是否解决。")
                # Only the exact prefix the person read is approved. Later turns remain pending.
                if body.run_ids != run_ids[:len(body.run_ids)]:
                    fail("review_turns_changed", "会话内容已更新，请重新读取后审核。")
                reviewed_count = max(reviewed_count, len(body.run_ids))
            elif body.action == "issue":
                if body.run_id not in run_ids:
                    fail("review_run_mismatch", "该回答不属于当前会话。", 422)
                issues.append({"issue_id": body.action_id, "run_id": body.run_id, "note": body.note,
                    "status": "open", "recorded_by": actor, "verification_run_id": None})
            elif body.action in {"resolve", "reopen"}:
                if issue is None:
                    fail("review_issue_not_found", "未找到原问题。", 404)
                if body.action == "resolve":
                    if issue["status"] != "open":
                        fail("review_issue_closed", "该问题已确认解决。")
                    if not body.verification_run_id and not body.note:
                        fail("verification_required", "请先重新验证，或填写手动确认的依据。", 422)
                    if body.verification_run_id:
                        matching = any(event["action"] == "retest" and event.get("issue_id") == body.issue_id and event.get("run_id") == body.verification_run_id
                                       for event in self.detail_locked(session_id)["history"])
                        result = self.db.execute("SELECT status FROM chat_submissions WHERE run_id=?", (body.verification_run_id,)).fetchone()
                        if not matching or not result or result[0] != "succeeded":
                            fail("invalid_verification", "请选择此问题已完成的验证回答。", 422)
                    issue.update(status="resolved", verification_run_id=body.verification_run_id, resolution_note=body.note)
                else:
                    issue.update(status="open", verification_run_id=None)
                    reviewed_count = 0
            self._save(session_id, body.action_id, revision + 1, reviewed_count, issues,
                {"action": body.action, "recorded_by": actor, "note": body.note, "run_id": body.run_id,
                 "issue_id": body.issue_id or (body.action_id if body.action == "issue" else None), "input": body.model_dump()})
            return self.detail_locked(session_id)

    def record_retest(self, session_id, body: SessionRetestInput, run_id: str, actor: str):
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            action_id = "retest_" + actor + ":" + body.submission_id
            if self.db.execute("SELECT 1 FROM session_review_events WHERE session_id=? AND action_id=?", (session_id, action_id)).fetchone():
                return
            revision, reviewed_count, issues = self._state(session_id)
            self._save(session_id, action_id, revision + 1, reviewed_count, issues,
                {"action": "retest", "recorded_by": actor, "run_id": run_id,
                 "source_run_id": body.source_run_id, "issue_id": body.issue_id})
