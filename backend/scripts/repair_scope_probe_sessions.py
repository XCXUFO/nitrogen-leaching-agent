"""Repair the two verified 2026-11-11 batches of independent scope probes.

Defaults to a read-only preview. --apply requires a new backup path. Original
trace payloads stay intact; only the review index's conversation assignments move.
This is deliberately incident-specific, not a rule for splitting empty histories.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path


SESSIONS = (
    "471589ec21024145ed47a74854c1a29ffcba6a4a88ed411970ed47b310e659ea",
    "1abd333bcf8ff5035da3b027cd54e0a03f1275fa390c8344d105fe0c09428984",
)
OPERATOR = "visitor_2fe7bd8a392da4102425b02d1da1cb90"
QUESTIONS = ("明天吃啥", "你妈是谁", "解释下动能定理", "1", "晚上好")


def repair(db: sqlite3.Connection, *, apply: bool = False) -> list[dict]:
    plan = []
    with db:
        # Validate the complete plan under the write lock before moving anything.
        if apply:
            db.execute("BEGIN IMMEDIATE")
        for session_id in SESSIONS:
            rows = db.execute(
                "SELECT run_id,payload,operator_id FROM agent_runs WHERE session_id=? ORDER BY started_at,rowid",
                (session_id,),
            ).fetchall()
            if len(rows) == 1 and json.loads(rows[0][1])["input"] == QUESTIONS[0]:
                # Reruns are a no-op only when every moved row is still present.
                moved = [db.execute("SELECT payload FROM agent_runs WHERE session_id=?", (destination,)).fetchall()
                         for destination in [hashlib.sha256((session_id + ":" + q).encode()).hexdigest() for q in QUESTIONS[1:]]]
                if all(len(items) == 1 and json.loads(items[0][0])["input"] == q
                       for q, items in zip(QUESTIONS[1:], moved)):
                    continue
            traces = [json.loads(row[1]) for row in rows]
            if tuple(t["input"] for t in traces) != QUESTIONS:
                raise ValueError("Incident rows changed; refusing to infer conversation boundaries")
            if db.execute("SELECT 1 FROM session_review_events WHERE session_id=?", (session_id,)).fetchone():
                raise ValueError("Human reviews exist; preserve them before repairing")
            if db.execute("SELECT 1 FROM session_review_state WHERE session_id=?", (session_id,)).fetchone():
                raise ValueError("Human review state exists; refusing to reset it")
            if db.execute("SELECT 1 FROM account_chat_conversations WHERE session_id=?", (session_id,)).fetchone():
                raise ValueError("Account history exists; refusing to change its conversation")
            for index, ((run_id, _, operator), trace) in enumerate(zip(rows, traces)):
                snapshot = trace.get("request_snapshot") or {}
                if (operator != OPERATOR or not trace["started_at"].startswith("2026-11-11T15:25:")
                        or trace.get("history_count") != 0 or snapshot.get("history")
                        or snapshot.get("has_attachments") or trace.get("source") != "legacy"
                        or trace.get("turn_id") or trace.get("request_id")
                        or db.execute("SELECT 1 FROM chat_submissions WHERE run_id=?", (run_id,)).fetchone()):
                    raise ValueError("Not an independent legacy probe; refusing to move it")
                destination = session_id if index == 0 else hashlib.sha256((session_id + ":" + trace["input"]).encode()).hexdigest()
                if index and (db.execute("SELECT 1 FROM chat_sessions WHERE session_id=?", (destination,)).fetchone()
                              or db.execute("SELECT 1 FROM agent_runs WHERE session_id=?", (destination,)).fetchone()):
                    raise ValueError("Destination conversation already exists")
                plan.append({"run_id": run_id, "from": session_id, "to": destination, "query": trace["input"], "trace": trace})
        if apply:
            for item in plan:
                trace = item["trace"]
                db.execute("UPDATE agent_runs SET session_id=? WHERE run_id=?", (item["to"], item["run_id"]))
                db.execute("""INSERT OR REPLACE INTO chat_sessions
                    (session_id,topic,created_at,operator_id,status,latency_ms,turn_count) VALUES (?,?,?,?,?,?,1)""",
                    (item["to"], trace["input"], trace["started_at"], OPERATOR,
                     "正常" if trace["status"] == "ok" else "异常", trace["latency_ms"]))
    return [{k: v for k, v in item.items() if k != "trace"} for item in plan]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    with sqlite3.connect(args.database.resolve().as_uri() + ("?mode=rw" if args.apply else "?mode=ro"), uri=True) as db:
        plan = repair(db)
        if args.apply:
            if not args.backup:
                parser.error("--apply requires --backup")
            args.backup.parent.mkdir(parents=True, exist_ok=True)
            with args.backup.open("xb"):
                pass
            with sqlite3.connect(args.backup) as backup:
                db.backup(backup)
            plan = repair(db, apply=True)
        print(json.dumps({"applied": args.apply, "plan": plan}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
