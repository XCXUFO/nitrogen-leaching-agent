"""Owned submissions and ordered public events in the existing trace database."""
from __future__ import annotations

import json
import secrets
import time
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException


def now():
    return datetime.now(timezone.utc).isoformat()


def fail(status, code, message):
    raise HTTPException(status, detail={"code": code, "message": message})


class ChatRuns:
    def __init__(self, connection, lock):
        self.db, self.lock = connection, lock
        self.history = None
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS chat_identity_key (id INTEGER PRIMARY KEY, secret TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS chat_run_conversations (
                    owner TEXT NOT NULL, session_id TEXT NOT NULL, expires_at REAL NOT NULL,
                    PRIMARY KEY(owner, session_id));
                CREATE TABLE IF NOT EXISTS chat_run_turns (
                    owner TEXT NOT NULL, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, primary_run_id TEXT NOT NULL,
                    PRIMARY KEY(owner, session_id, turn_id));
                CREATE TABLE IF NOT EXISTS chat_submissions (
                    run_id TEXT PRIMARY KEY, owner TEXT NOT NULL, session_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL, request_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
                    primary_run_id TEXT NOT NULL, rerun_of_run_id TEXT,
                    status TEXT NOT NULL, outcome TEXT, accepted_at TEXT NOT NULL,
                    expires_at REAL NOT NULL, config_version TEXT NOT NULL,
                    source TEXT NOT NULL, mode TEXT NOT NULL, result_json TEXT, error_json TEXT,
                    UNIQUE(owner, session_id, request_id));
                CREATE TABLE IF NOT EXISTS chat_run_events (
                    run_id TEXT NOT NULL, sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                    PRIMARY KEY(run_id, sequence));
                CREATE INDEX IF NOT EXISTS chat_submissions_active ON chat_submissions(status, session_id);
            """)
            self.db.execute("INSERT OR IGNORE INTO chat_identity_key VALUES (1, ?)", (secrets.token_hex(32),))
            self.secret = self.db.execute("SELECT secret FROM chat_identity_key WHERE id=1").fetchone()[0].encode()

    @staticmethod
    def _record(cursor, row):
        return dict(zip([column[0] for column in cursor.description], row)) if row else None

    def _find(self, where, args):
        cursor = self.db.execute("SELECT * FROM chat_submissions WHERE " + where, args)
        return self._record(cursor, cursor.fetchone())

    def _event(self, run_id, event):
        sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM chat_run_events WHERE run_id=?", (run_id,)).fetchone()[0]
        value = {**event, "event_id": event.get("event_id", str(uuid4())), "run_id": run_id, "sequence": sequence, "time": event.get("time", now())}
        self.db.execute("INSERT INTO chat_run_events VALUES (?,?,?)", (run_id, sequence, json.dumps(value, ensure_ascii=False)))
        return value

    def admit(self, *, owner, session_id, turn_id, request_id, fingerprint, rerun_of_run_id,
              config_version, mode, retention_seconds, max_active, source="formal"):
        with self.lock, self.db:
            # The unique request and primary-turn relations must survive races
            # across connections, not just one event loop's in-memory locks.
            self.db.execute("BEGIN IMMEDIATE")
            previous = self._find("owner=? AND session_id=? AND request_id=?", (owner, session_id, request_id))
            if previous:
                if previous["expires_at"] <= time.time():
                    fail(410, "recovery_expired", "本轮恢复窗口已过期，请新建对话后再提问。")
                if (previous["fingerprint"], previous["turn_id"], previous["rerun_of_run_id"]) != (fingerprint, turn_id, rerun_of_run_id):
                    fail(409, "request_conflict", "相同提交标识不能对应不同输入。")
                return previous, False
            namespace = self.db.execute("SELECT expires_at FROM chat_run_conversations WHERE owner=? AND session_id=?", (owner, session_id)).fetchone()
            if namespace and namespace[0] <= time.time() and not owner.startswith("internal_"):
                fail(410, "recovery_expired", "此对话的恢复窗口已结束，请新建对话。")
            active = self.db.execute("SELECT COUNT(*) FROM chat_submissions WHERE status IN ('accepted','running')").fetchone()[0]
            if active >= max_active:
                fail(429, "run_capacity", "当前处理人数较多，请稍后重试。")
            if self.db.execute("SELECT 1 FROM chat_submissions WHERE owner=? AND session_id=? AND status IN ('accepted','running')", (owner, session_id)).fetchone():
                fail(409, "conversation_busy", "当前对话仍有问题在处理，请等待完成。")
            turn = self.db.execute("SELECT fingerprint, primary_run_id FROM chat_run_turns WHERE owner=? AND session_id=? AND turn_id=?", (owner, session_id, turn_id)).fetchone()
            if turn:
                original = self._find("run_id=? AND owner=? AND session_id=? AND turn_id=?", (rerun_of_run_id, owner, session_id, turn_id)) if rerun_of_run_id else None
                if not original or turn[0] != fingerprint:
                    fail(409, "turn_conflict", "重跑必须关联同轮原运行并保留原问题及输入；修改问题请使用新轮次。")
                if original["expires_at"] <= time.time():
                    fail(410, "recovery_expired", "原运行的恢复窗口已结束，可以继续发送新问题。")
                if original["status"] in {"accepted", "running"}:
                    fail(409, "conversation_busy", "原运行尚未结束，请先等待其完成。")
            elif rerun_of_run_id:
                fail(404, "run_not_found", "未找到可关联的原运行。")
            run_id = str(uuid4())
            expires_at = max(namespace[0], time.time() + retention_seconds) if namespace and owner.startswith("internal_") else namespace[0] if namespace else time.time() + retention_seconds
            if not namespace:
                self.db.execute("INSERT INTO chat_run_conversations VALUES (?,?,?)", (owner, session_id, expires_at))
            elif owner.startswith("internal_"):
                self.db.execute("UPDATE chat_run_conversations SET expires_at=? WHERE owner=? AND session_id=?", (expires_at, owner, session_id))
            primary = turn[1] if turn else run_id
            if not turn:
                self.db.execute("INSERT INTO chat_run_turns VALUES (?,?,?,?,?)", (owner, session_id, turn_id, fingerprint, primary))
            self.db.execute("INSERT INTO chat_submissions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (run_id, owner, session_id, turn_id, request_id, fingerprint, primary, rerun_of_run_id,
                             "accepted", None, now(), expires_at, config_version, source, mode, None, None))
            self._event(run_id, {"type": "run_accepted", "status": "accepted", "summary": "问题已受理。"})
            return self._find("run_id=?", (run_id,)), True

    def event(self, run_id, event):
        with self.lock, self.db:
            self.db.execute("UPDATE chat_submissions SET status='running' WHERE run_id=? AND status='accepted'", (run_id,))
            return self._event(run_id, event)

    def finish(self, run_id, *, status, outcome=None, result=None, error=None, pending_events=()):
        with self.lock, self.db:
            for event in pending_events:
                self._event(run_id, event)
            self.db.execute("UPDATE chat_submissions SET status=?,outcome=?,result_json=?,error_json=? WHERE run_id=?",
                            (status, outcome, json.dumps(result, ensure_ascii=False) if result is not None else None,
                             json.dumps(error, ensure_ascii=False) if error else None, run_id))
            if self.history is not None:
                self.history.finish_locked(run_id, status, result, error)
            self._event(run_id, {"type": "run_finished", "status": status, "outcome": outcome,
                                 "summary": {"succeeded": "处理已结束。", "failed": "本次处理未完成。", "cancelled": "处理已停止。", "unknown": "结果保存受阻，运行状态未知。"}.get(status, "运行已中断。")})

    def mark_unknown(self, run_id):
        with self.lock, self.db:
            self.db.execute("UPDATE chat_submissions SET status='unknown',outcome='unknown' WHERE run_id=?", (run_id,))

    def recover_interrupted(self):
        with self.lock, self.db:
            rows = self.db.execute("SELECT run_id FROM chat_submissions WHERE status IN ('accepted','running')").fetchall()
            for (run_id,) in rows:
                self.db.execute("UPDATE chat_submissions SET status='interrupted',outcome='unknown' WHERE run_id=?", (run_id,))
                if self.history is not None:
                    self.history.finish_locked(run_id, "interrupted", error={"code": "run_interrupted",
                        "message": "服务重启中断了这轮请求，可以继续发送新问题。", "http_status": 409})
                self._event(run_id, {"type": "run_finished", "status": "interrupted", "outcome": "unknown", "summary": "服务重启，原运行已中断；没有自动重做。"})

    def _view(self, row, after):
        if not row:
            return None
        if row["expires_at"] <= time.time():
            # Keep the identity/fingerprint tombstone; an old namespace cannot
            # accidentally become a newly executable request after cleanup.
            self.db.execute("UPDATE chat_submissions SET result_json=NULL,error_json=NULL WHERE run_id=?", (row["run_id"],))
            self.db.execute("DELETE FROM chat_run_events WHERE run_id=?", (row["run_id"],))
            return {"status": "expired"}
        events = [json.loads(item[0]) for item in self.db.execute("SELECT payload FROM chat_run_events WHERE run_id=? AND sequence>? ORDER BY sequence", (row["run_id"], after)).fetchall()]
        sequence = self.db.execute("SELECT COALESCE(MAX(sequence),0) FROM chat_run_events WHERE run_id=?", (row["run_id"],)).fetchone()[0]
        return {key: row[key] for key in ("run_id", "turn_id", "request_id", "primary_run_id", "rerun_of_run_id", "status", "outcome", "accepted_at", "expires_at", "config_version", "source", "mode")} | {
            "events": events, "last_sequence": sequence, "result": json.loads(row["result_json"]) if row["result_json"] else None,
            "error": json.loads(row["error_json"]) if row["error_json"] else None, "result_saved": row["result_json"] is not None}

    def get(self, owner, run_id, after=0):
        with self.lock, self.db:
            return self._view(self._find("owner=? AND run_id=?", (owner, run_id)), after)

    def lookup(self, owner, session_id, request_id):
        with self.lock, self.db:
            return self._view(self._find("owner=? AND session_id=? AND request_id=?", (owner, session_id, request_id)), 0)
