"""Conversation index compatibility for databases created before session columns."""
import json
import sqlite3

from src.storage.run_store import RunStore


def test_existing_run_rows_migrate_to_readable_legacy_conversation(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE agent_runs (
        run_id TEXT PRIMARY KEY, started_at TEXT NOT NULL,
        conversation_ref TEXT NOT NULL, status TEXT NOT NULL, payload TEXT NOT NULL)""")
    for number in (1, 2):
        payload = {"run_id": f"old-{number}", "conversation_ref": "digest-only",
                   "started_at": f"2026-10-05T08:00:0{number}+00:00", "input": f"旧问题{number}",
                   "answer": f"旧回答{number}", "status": "ok", "latency_ms": 10, "tool_calls": []}
        db.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?)",
                   (payload["run_id"], payload["started_at"], "digest-only", "ok", json.dumps(payload)))
    db.commit(); db.close()

    store = RunStore(path)
    listing = store.sessions()
    assert listing["total"] == 1
    assert listing["items"][0]["turn_count"] == 2
    assert listing["items"][0]["session_id"] == "digest-only"
    assert [turn["answer"] for turn in store.session("old-2")["turns"]] == ["旧回答1", "旧回答2"]
    store.close()
    reopened = RunStore(path)
    assert reopened.sessions()["items"][0]["turn_count"] == 2
    reopened.close()
