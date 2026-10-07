"""Append-only run traces and developer-visible conversation indexes."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from threading import Lock

from src.agent.contracts import RunTrace


class RunStore:
    def __init__(self, path: str | Path = ":memory:"):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()
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
            total = self._connection.execute("SELECT COUNT(*) FROM chat_sessions" + where, values).fetchone()[0]
            rows = self._connection.execute("SELECT * FROM chat_sessions" + where +
                " ORDER BY created_at DESC, session_id DESC LIMIT ? OFFSET ?", [*values, limit, offset]).fetchall()
        keys = ("session_id", "topic", "created_at", "operator_id", "status", "latency_ms", "turn_count")
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
            turns = self._connection.execute("SELECT payload FROM agent_runs WHERE session_id=? ORDER BY started_at, rowid", (session_id,)).fetchall()
        keys = ("session_id", "topic", "created_at", "operator_id", "status", "latency_ms", "turn_count")
        return {**dict(zip(keys, summary)), "turns": [json.loads(turn[0]) for turn in turns]}

    def get(self, run_id: str) -> RunTrace | None:
        with self._lock:
            row = self._connection.execute("SELECT payload FROM agent_runs WHERE run_id = ?", (run_id,)).fetchone()
        return RunTrace.model_validate_json(row[0]) if row else None

    def close(self) -> None:
        with self._lock:
            self._connection.close()
