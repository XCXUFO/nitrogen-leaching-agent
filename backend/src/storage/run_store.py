"""Append-only run traces and developer-visible conversation indexes."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import RLock

from src.agent.contracts import RunTrace
from src.storage.chat_runs import ChatRuns
from src.storage.account_history import AccountHistory
from src.storage.run_attachments import RunAttachments
from src.storage.prompt_versions import PromptVersions
from src.storage.task_prompts import TaskPrompts
from src.agent.skill_config import SkillConfigurations
from src.evaluation.online_metrics import OnlineMetrics
from src.evaluation.session_reviews import SessionReviews
from src.evaluation.conversation_cases import ConversationCases


class RunStore:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False, timeout=5)
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS agent_runs (
            run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
            conversation_ref TEXT NOT NULL, status TEXT NOT NULL,
            payload TEXT NOT NULL)""")
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(agent_runs)")}
        if "session_id" not in columns:
            self._connection.execute("ALTER TABLE agent_runs ADD COLUMN session_id TEXT")
        if "operator_id" not in columns:
            self._connection.execute("ALTER TABLE agent_runs ADD COLUMN operator_id TEXT")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS chat_sessions (
            session_id TEXT PRIMARY KEY, topic TEXT NOT NULL, created_at TEXT NOT NULL,
            operator_id TEXT NOT NULL, status TEXT NOT NULL, latency_ms INTEGER NOT NULL,
            turn_count INTEGER NOT NULL)""")
        self._connection.execute("CREATE INDEX IF NOT EXISTS agent_runs_session ON agent_runs(session_id, started_at)")
        self._connection.execute("CREATE INDEX IF NOT EXISTS chat_sessions_created ON chat_sessions(created_at DESC)")
        # Earlier traces only held a digest. Keep them browsable under that stable
        # reference; the original session ID cannot be reconstructed.
        self._connection.execute("UPDATE agent_runs SET session_id=conversation_ref WHERE session_id IS NULL")
        for raw, session_id, operator_id in self._connection.execute("""SELECT payload, session_id, operator_id FROM agent_runs
            WHERE session_id NOT IN (SELECT session_id FROM chat_sessions) ORDER BY started_at, rowid""").fetchall():
            self._index(json.loads(raw), session_id, operator_id or "未知")
        self._connection.commit()
        self.live = ChatRuns(self._connection, self._lock)
        self.history = AccountHistory(self._connection, self._lock)
        self.attachments = RunAttachments(self._connection, self._lock)
        self.live.history = self.history
        self.skill_config = SkillConfigurations(self._connection, self._lock)
        self.prompts = PromptVersions(self._connection, self._lock)
        self.task_prompts = TaskPrompts(self._connection, self._lock)
        self.online_metrics = OnlineMetrics(self._connection, self._lock)
        self.reviews = SessionReviews(self._connection, self._lock)
        self.conversation_cases = ConversationCases(self)

    def active_prompt_snapshot(self):
        # Keep a request from reading across a complete group activation.
        with self._lock:
            return {'communication': self.prompts.active(), 'task_prompts': self.task_prompts.active()}

    @staticmethod
    def _topic(question: str) -> str:
        return " ".join(question.split()).strip(" ，。！？?!.：:")[:20] or "未命名会话"

    def _index(self, payload: dict, session_id: str, operator_id: str) -> None:
        topic = self._topic(payload["input"])
        existing = self._connection.execute("SELECT topic FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
        if existing is None:
            self._connection.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,?)",
                (session_id, topic, payload["started_at"], operator_id,
                 "异常" if payload["status"] != "ok" else "正常", payload["latency_ms"], 1))
        else:
            # A greeting carries little topic information; the next real question can replace it.
            if existing[0] in {"你好", "您好", "hi", "hello"} and len(topic) > 3:
                self._connection.execute("UPDATE chat_sessions SET topic=? WHERE session_id=?", (topic, session_id))
            self._connection.execute("""UPDATE chat_sessions SET turn_count=turn_count+1,
                latency_ms=latency_ms+?, status=CASE WHEN ?!='ok' THEN '异常' ELSE status END
                WHERE session_id=?""", (payload["latency_ms"], payload["status"], session_id))

    def append(self, trace: RunTrace, *, session_id: str | None = None, operator_id: str | None = None) -> None:
        session_id = session_id or trace.conversation_ref
        operator_id = operator_id or "游客"
        with self._lock, self._connection:
            self._connection.execute(
                """INSERT INTO agent_runs (run_id, started_at, conversation_ref, status, payload, session_id, operator_id)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (trace.run_id, trace.started_at, trace.conversation_ref, trace.status,
                 trace.model_dump_json(), session_id, operator_id),
            )
            self._index(trace.model_dump(mode="json"), session_id, operator_id)

    def sessions(self, *, information: str = "", created_from: str | None = None,
                 created_to: str | None = None, status: str | None = None,
                 duration_mode: str | None = None, duration_ms: int | None = None,
                 duration_max_ms: int | None = None, operator_id: str = "",
                 review_status: str | None = None,
                 limit: int = 20, offset: int = 0) -> dict:
        clauses, values = [], []
        if information:
            escaped = information.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            clauses.append("(session_id LIKE ? ESCAPE '\\' OR topic LIKE ? ESCAPE '\\')")
            values.extend([f"%{escaped}%", f"%{escaped}%"])
        if created_from:
            clauses.append("created_at >= ?"); values.append(created_from)
        if created_to:
            clauses.append("created_at <= ?"); values.append(created_to)
        if status:
            clauses.append("status = ?"); values.append(status)
        if review_status:
            clauses.append("review_status = ?"); values.append(review_status)
        if operator_id:
            clauses.append("operator_id LIKE ? ESCAPE '\\'")
            escaped = operator_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            values.append(f"%{escaped}%")
        if duration_mode:
            symbol = {"gt": ">", "lt": "<", "eq": "=", "between": ">="}[duration_mode]
            clauses.append(f"latency_ms {symbol} ?"); values.append(duration_ms)
            if duration_mode == "between":
                clauses.append("latency_ms <= ?"); values.append(duration_max_ms)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._lock:
            total = self._connection.execute("SELECT COUNT(*) FROM reviewed_sessions" + where, values).fetchone()[0]
            cursor = self._connection.execute("SELECT * FROM reviewed_sessions" + where +
                " ORDER BY created_at DESC, session_id DESC LIMIT ? OFFSET ?", [*values, limit, offset])
            keys = [column[0] for column in cursor.description]
            rows = cursor.fetchall()
        return {"total": total, "items": [dict(zip(keys, row)) for row in rows]}

    def session(self, identifier: str) -> dict | None:
        with self._lock:
            row = self._connection.execute("SELECT session_id FROM chat_sessions WHERE session_id=?", (identifier,)).fetchone()
            if row is None:
                row = self._connection.execute("SELECT session_id FROM agent_runs WHERE run_id=?", (identifier,)).fetchone()
            if row is None:
                return None
            session_id = row[0]
            summary = self._connection.execute("SELECT * FROM chat_sessions WHERE session_id=?", (session_id,)).fetchone()
            rows = self._connection.execute("""SELECT r.payload, h.request_json FROM agent_runs r
                LEFT JOIN account_chat_turns h ON h.run_id=r.run_id
                WHERE r.session_id=? ORDER BY r.started_at, r.rowid""", (session_id,)).fetchall()
            turns = []
            for raw, historical_request in rows:
                turn = json.loads(raw)
                snapshot = turn.setdefault("request_snapshot", {})
                if not snapshot.get("attachments") and historical_request:
                    # Recover legacy filenames without exposing temporary file capabilities.
                    snapshot["attachments"] = [
                        {key: item[key] for key in ("filename", "sha256", "format") if key in item}
                        for item in json.loads(historical_request).get("attachments", [])
                        if isinstance(item, dict) and item.get("filename")]
                    if snapshot["attachments"]:
                        snapshot["has_attachments"] = True
                turns.append(turn)
            review = self.reviews.detail_locked(session_id)
        keys = ("session_id", "topic", "created_at", "operator_id", "status", "latency_ms", "turn_count")
        open_count = sum(item["status"] == "open" for item in review["issues"])
        review_status = "needs_changes" if open_count else "pending" if review["reviewed_turn_count"] < len(turns) else "passed"
        return {**dict(zip(keys, summary)), "turns": turns,
                "review": review, "review_status": review_status, "review_revision": review["revision"],
                "reviewed_turn_count": review["reviewed_turn_count"], "open_issue_count": open_count}

    def get(self, run_id: str) -> RunTrace | None:
        with self._lock:
            row = self._connection.execute("SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunTrace.model_validate_json(row[0]) if row else None

    def close(self) -> None:
        with self._lock:
            self._connection.close()
