import json
import sqlite3

import pytest

from scripts.repair_scope_probe_sessions import OPERATOR, QUESTIONS, SESSIONS, repair
from src.storage.run_store import RunStore


def incident(tmp_path):
    path = tmp_path / "runs.sqlite3"
    RunStore(path).close()
    db = sqlite3.connect(path)
    for session_id in SESSIONS:
        db.execute("INSERT INTO chat_sessions VALUES (?,?,?,?,?,?,?)",
                   (session_id, QUESTIONS[0], "2026-11-11T15:25:06+00:00", OPERATOR, "正常", 50, 5))
        for index, question in enumerate(QUESTIONS):
            run_id = session_id + str(index)
            trace = {"run_id": run_id, "input": question, "history_count": 0, "source": "legacy",
                     "request_snapshot": {"history": [], "has_attachments": False},
                     "started_at": f"2026-11-11T15:25:06.{index}00000+00:00", "latency_ms": 10, "status": "ok"}
            db.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?)",
                       (run_id, trace["started_at"], "original-digest", "ok", json.dumps(trace), session_id, OPERATOR))
    db.commit()
    return path, db


def test_repair_splits_only_index_preserves_traces_and_is_idempotent(tmp_path):
    path, db = incident(tmp_path)
    original = db.execute("SELECT run_id,payload,conversation_ref FROM agent_runs ORDER BY run_id").fetchall()
    assert len(repair(db)) == 10
    assert db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 2
    assert len(repair(db, apply=True)) == 10
    assert repair(db, apply=True) == []
    assert db.execute("SELECT run_id,payload,conversation_ref FROM agent_runs ORDER BY run_id").fetchall() == original
    db.close()
    store = RunStore(path)
    try:
        listing = store.sessions()
        assert listing["total"] == 10
        assert all(item["turn_count"] == 1 and item["review_status"] == "pending" for item in listing["items"])
        assert all(len(store.session(item["session_id"])["turns"]) == 1 for item in listing["items"])
    finally:
        store.close()


@pytest.mark.parametrize("change", ["history", "review", "extra_run"])
def test_repair_aborts_entire_batch_if_incident_has_changed(tmp_path, change):
    _, db = incident(tmp_path)
    if change == "history":
        db.execute("UPDATE agent_runs SET payload=json_set(payload,'$.history_count',2) WHERE session_id=?", (SESSIONS[1],))
    elif change == "review":
        db.execute("INSERT INTO session_review_events VALUES (?,?,?,?)", (SESSIONS[1], "review", 1, "{}"))
    else:
        db.execute("INSERT INTO agent_runs SELECT 'extra',started_at,conversation_ref,status,payload,session_id,operator_id FROM agent_runs LIMIT 1")
    db.commit()
    before = db.execute("SELECT run_id,session_id FROM agent_runs ORDER BY run_id").fetchall()
    with pytest.raises(ValueError):
        repair(db, apply=True)
    assert db.execute("SELECT run_id,session_id FROM agent_runs ORDER BY run_id").fetchall() == before
    assert db.execute("SELECT COUNT(*) FROM chat_sessions").fetchone()[0] == 2
    db.close()
