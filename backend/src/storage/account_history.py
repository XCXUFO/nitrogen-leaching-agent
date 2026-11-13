"""Account-owned chat transcripts, independent of the run recovery window."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class AccountHistory:
    def __init__(self, connection, lock):
        self.db, self.lock = connection, lock
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS account_chat_conversations (
                    account_id TEXT NOT NULL, client_id TEXT NOT NULL, session_id TEXT NOT NULL,
                    title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    PRIMARY KEY(account_id, client_id), UNIQUE(account_id, session_id));
                CREATE TABLE IF NOT EXISTS account_chat_turns (
                    run_id TEXT PRIMARY KEY, account_id TEXT NOT NULL, client_id TEXT NOT NULL,
                    turn_id TEXT NOT NULL, request_json TEXT NOT NULL, status TEXT NOT NULL,
                    response_json TEXT, error_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS account_history_order
                    ON account_chat_conversations(account_id, created_at DESC);
                CREATE INDEX IF NOT EXISTS account_history_turns
                    ON account_chat_turns(account_id, client_id, created_at);
            """)

    def _record(self, account_id, client_id, session_id, body, receipt, attachments):
        timestamp = receipt.get("accepted_at") or now()
        request = {"query": body["query"], "history": body.get("history", []),
                   "attachments": attachments, "turnId": receipt["turn_id"],
                   "requestId": receipt["request_id"], "rerunOfRunId": receipt.get("rerun_of_run_id")}
        if body.get("case_ids"):
            request["caseIds"] = body["case_ids"]
        self.db.execute("""INSERT OR IGNORE INTO account_chat_conversations VALUES (?,?,?,?,?,?)""",
                        (account_id, client_id, session_id, body["query"][:80], timestamp, timestamp))
        self.db.execute("""INSERT OR IGNORE INTO account_chat_turns VALUES (?,?,?,?,?,?,?,?,?,?)""",
                        (receipt["run_id"], account_id, client_id, receipt["turn_id"],
                         json.dumps(request, ensure_ascii=False), receipt["status"],
                         json.dumps(receipt["result"], ensure_ascii=False) if receipt.get("result") is not None else None,
                         json.dumps(receipt["error"], ensure_ascii=False) if receipt.get("error") else None,
                         timestamp, timestamp))
        self.db.execute("""UPDATE account_chat_conversations SET updated_at=MAX(updated_at,?)
                           WHERE account_id=? AND client_id=?""", (timestamp, account_id, client_id))

    def record(self, account_id, client_id, session_id, body, receipt, attachments):
        with self.lock, self.db:
            self._record(account_id, client_id, session_id, body, receipt, attachments)

    def finish_locked(self, run_id, status, result=None, error=None):
        """Called inside the same transaction that finishes the live run."""
        if status != "succeeded" and error is None:
            error = {"code": "run_" + status, "message": "这轮请求未完成，可以继续发送新问题。", "http_status": 409}
        timestamp = now()
        self.db.execute("""UPDATE account_chat_turns SET status=?,response_json=?,error_json=?,updated_at=?
                           WHERE run_id=?""",
                        (status, json.dumps(result, ensure_ascii=False) if result is not None else None,
                         json.dumps(error, ensure_ascii=False) if error else None, timestamp, run_id))
        self.db.execute("""UPDATE account_chat_conversations SET updated_at=? WHERE (account_id,client_id)
                           IN (SELECT account_id,client_id FROM account_chat_turns WHERE run_id=?)""",
                        (timestamp, run_id))

    @staticmethod
    def _legacy_response(trace):
        from src.api.chat_schema import ChatResponse

        citations, files = [], []
        for evidence in trace.get("evidence", []):
            location, provenance = evidence.get("location", {}), evidence.get("provenance", {})
            if evidence["source_type"] == "literature" and location.get("citation_index"):
                citations.append({"index": location["citation_index"], "chunk_id": evidence["source_id"],
                    "retrieval_ids": evidence.get("retrieval_ids", []), "chunk_ids": evidence.get("chunk_ids", []),
                    "source": provenance.get("source", ""), "title": provenance.get("title"), "score": 0,
                    "snippet": str(evidence["claim_or_value"]),
                    **{key: provenance[key] for key in ("content_version", "file_sha256") if key in provenance},
                    **{key: location[key] for key in ("char_start", "char_end") if key in location}})
            elif evidence["source_type"] == "file":
                files.append({**provenance, **location, "sha256": evidence["source_id"],
                              "value": evidence["claim_or_value"], "unit": evidence.get("unit") or ""})
        route = {"DIRECT": "direct", "KNOWLEDGE": "knowledge", "FILE_ANALYSIS": "file",
                 "COMPOSED": "composed", "CLARIFY": "clarification", "OUT_OF_SCOPE": "out_of_scope"}
        return ChatResponse(answer=trace["answer"], citations=citations, file_evidence=files,
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            retrieved_count=len(citations), model=trace.get("model") or "archived",
            route=route.get((trace.get("decision") or {}).get("route"), "knowledge"),
            run_id=trace["run_id"], agent_route=(trace.get("decision") or {}).get("route"),
            evidence=trace.get("evidence", []), sections=trace.get("sections", []),
            warnings=trace.get("warnings", []), outcome=trace.get("outcome") or "complete",
            trace_saved=True).model_dump(mode="json")

    def _backfill(self, account_id):
        # Only account-attributed formal/legacy chats are imported. Guest,
        # evaluation and trial records never become an account's chat history.
        rows = self.db.execute("""SELECT a.payload,a.session_id,s.result_json,s.owner
            FROM agent_runs a LEFT JOIN chat_submissions s ON s.run_id=a.run_id
            WHERE a.operator_id=? AND a.run_id NOT IN (SELECT run_id FROM account_chat_turns)
            ORDER BY a.started_at,a.rowid""", (account_id,)).fetchall()
        for raw, session_id, saved, owner in rows:
            trace = json.loads(raw)
            if trace.get("source", "legacy") not in {"formal", "legacy"} or (owner and owner != "internal_" + account_id):
                continue
            previous = self.db.execute("SELECT client_id FROM account_chat_conversations WHERE account_id=? AND session_id=?",
                                       (account_id, session_id)).fetchone()
            client_id = previous[0] if previous else "saved_" + hashlib.sha256(session_id.encode()).hexdigest()[:32]
            snapshot = trace.get("request_snapshot") or {}
            response = json.loads(saved) if saved else self._legacy_response(trace) if trace.get("answer") else None
            self._record(account_id, client_id, session_id, {"query": trace["input"], "history": snapshot.get("history", []), "case_ids": snapshot.get("case_ids", [])},
                {"run_id": trace["run_id"], "turn_id": trace.get("turn_id") or trace["run_id"],
                 "request_id": trace.get("request_id") or trace["run_id"],
                 "accepted_at": trace["started_at"], "status": "succeeded" if response else "failed",
                 "result": response, "error": None if response else {"code": trace.get("error_code") or "run_failed",
                     "message": "这轮历史请求未完成，可以继续发送新问题。", "http_status": 500}}, [])

    def list(self, account_id, *, limit=30, offset=0):
        with self.lock, self.db:
            self._backfill(account_id)
            total = self.db.execute("SELECT COUNT(*) FROM account_chat_conversations WHERE account_id=?", (account_id,)).fetchone()[0]
            rows = self.db.execute("""SELECT client_id,title,created_at,updated_at FROM account_chat_conversations
                WHERE account_id=? ORDER BY created_at DESC,client_id DESC LIMIT ? OFFSET ?""",
                (account_id, limit, offset)).fetchall()
            items = []
            for client_id, title, created_at, updated_at in rows:
                turns = {}
                recovery_session = hashlib.sha256(("internal_" + account_id + ":" + client_id).encode()).hexdigest()
                for run_id, turn_id, request, status, response, error, expires_at, live_session in self.db.execute("""
                    SELECT t.run_id,t.turn_id,t.request_json,t.status,t.response_json,t.error_json,s.expires_at,s.session_id
                    FROM account_chat_turns t LEFT JOIN chat_submissions s ON s.run_id=t.run_id
                    WHERE t.account_id=? AND t.client_id=? ORDER BY t.created_at,t.rowid""", (account_id, client_id)):
                    old = turns.get(turn_id, {})
                    turns[turn_id] = {"run_id": run_id, "turn_id": turn_id, "request": json.loads(request),
                        "status": status, "response": json.loads(response) if response else old.get("response"),
                        "error": json.loads(error) if error else None,
                        "expires_at": expires_at, "recoverable": bool(expires_at and expires_at > time.time()
                                                                    and live_session == recovery_session)}
                items.append({"id": client_id, "title": title, "created_at": created_at,
                              "updated_at": updated_at, "turns": list(turns.values())})
            return {"items": items, "total": total}
