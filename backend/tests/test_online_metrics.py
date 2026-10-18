from types import SimpleNamespace

import httpx
import pytest

from src.api import explanation_trials, online_metrics
from src.agent.contracts import RunTrace, StateSnapshot
from src.evaluation.online_metrics import step_metrics
from src.evaluation.contracts import Principal
from src.storage.run_store import RunStore
from tests.test_chat_runs import TOKEN, body, finished, make_app


def admit(store, **changes):
    data = {"owner": "owner", "session_id": "session", "turn_id": "turn", "request_id": "request", "fingerprint": "same", "rerun_of_run_id": None, "config_version": "v1", "mode": "auto", "retention_seconds": 3600, "max_active": 32, **changes}
    return store.live.admit(**data)[0]


def test_six_hand_calculable_steps_keep_kinds_and_attempts_separate():
    events = []
    def step(sid, kind, attempt, status, outcome=None, started=True, retrieval=False):
        base = {"step_id": sid, "kind": kind, "attempt_no": attempt, "operation": "retrieval" if retrieval else "other"}
        if started: events.append(base | {"type": "step_started", "status": "running"})
        events.append(base | {"type": "step_finished", "status": status, "outcome": outcome})
    step("retry", "tool", 1, "failed"); step("retry", "tool", 2, "succeeded", "has_result")
    step("empty", "tool", 1, "succeeded", "no_result", retrieval=True)
    step("skip", "tool", 1, "skipped", started=False)
    step("cancel", "tool", 1, "cancelled")
    step("fail", "tool", 1, "failed")
    step("clarify", "skill", 1, "succeeded", "clarification")
    step("parent", "container", 1, "succeeded")
    metrics = step_metrics(events)
    assert metrics["tool"]["success"] == {"numerator": 2, "denominator": 3, "rate": 2/3}
    assert metrics["tool"]["attempt_failure"] == {"numerator": 2, "denominator": 4, "rate": .5}
    assert metrics["tool"]["retrieval_no_result"]["rate"] == 1
    assert metrics["skill"]["success"]["denominator"] == 1


def test_primary_and_rerun_statistics_survive_reopening_without_review_tables(tmp_path):
    path = tmp_path / "runs.sqlite3"
    store = RunStore(path)
    first = admit(store)
    store.live.finish(first["run_id"], status="failed")
    second = admit(store, request_id="rerun", rerun_of_run_id=first["run_id"])
    store.live.finish(second["run_id"], status="succeeded")
    test_run = admit(store, turn_id="test-turn", request_id="test", source="test")
    store.live.finish(test_run["run_id"], status="succeeded")
    summary = store.online_metrics.summary({"source": "formal"})
    assert summary["sessions"] == summary["questions"] == 1 and summary["states"] == {"failed": 1}
    assert summary["session_states"] == {"abnormal": 1}
    assert summary["reruns"] == {"attempts": 1, "succeeded": 1, "recovered_failed_primary": 1, "sessions": 1}
    assert summary["trace_missing"] == 1
    assert store.online_metrics.summary({"source": "test"})["questions"] == 1
    assert store.online_metrics.summary({"source": "formal", "status": "normal"})["sessions"] == 0
    assert store._connection.execute("SELECT name FROM sqlite_master WHERE name LIKE 'formal_review%'").fetchall() == []
    store.close()
    reopened = RunStore(path)
    assert reopened.online_metrics.summary({"source": "formal"})["reruns"] == summary["reruns"]
    assert reopened.live.get("owner", first["run_id"])["status"] == "failed"
    reopened.close()


def save_turn(store, session, turn, *, at="2026-10-15T01:00:00+00:00", skill="case_reference",
              task="case_search", status="succeeded", mode="auto", version="v1", source="formal", owner="owner"):
    record = admit(store, session_id=session, turn_id=turn, request_id=turn, owner=owner,
                   mode=mode, config_version=version, source=source)
    store.live.finish(record["run_id"], status=status)
    with store._lock, store._connection:
        store._connection.execute("UPDATE chat_submissions SET accepted_at=? WHERE run_id=?", (at, record["run_id"]))
    trace = RunTrace(run_id=record["run_id"], primary_run_id=record["run_id"], conversation_ref=session,
                     started_at=at, input=f"问题 {turn}", history_count=0 if turn == "first" else 2,
                     state_before=StateSnapshot(), status="ok" if status == "succeeded" else "error",
                     config_version=version, source=source, mode=mode, understanding={"intents": [task]},
                     tool_calls=[{"skill": skill, "status": "ok" if status == "succeeded" else "error", "latency_ms": 10}])
    store.append(trace, session_id=session)
    return record


def test_conversation_cohort_keeps_cross_day_context_and_deduplicates_session_groups():
    store = RunStore()
    first = save_turn(store, "multi", "first")
    second = save_turn(store, "multi", "second", at="2026-10-16T01:00:00+00:00",
                       skill="case_explanation", task="explanation", mode="specified", version="v2", status="failed")
    third = save_turn(store, "multi", "third", at="2026-10-17T01:00:00+00:00", skill="case_explanation", task="explanation")
    save_turn(store, "single", "single")
    result = store.online_metrics.summary({"source": "formal"}, include_sessions=True)
    assert result["metric_version"] == "session-primary-v1" and result["unit"] == "session"
    assert result["sessions"] == 2 and result["questions"] == 4
    assert result["mean_turns"] == 2
    assert result["multi_turn"] == {"numerator": 1, "denominator": 2, "rate": .5}
    assert result["session_states"] == {"abnormal": 1, "normal": 1}
    assert result["turn_distribution"] == [{"turns": 1, "sessions": 1}, {"turns": 3, "sessions": 1}]
    assert result["by_task"] == {"case_search": 2, "explanation": 1}
    explanation = next(item for item in result["by_skill"] if item["skill"] == "case_explanation")
    assert explanation["sessions"] == 1 and explanation["calls"] == explanation["runs"] == 2
    assert result["daily"] == [{"date": "2026-10-15", "sessions": 2, "abnormal_sessions": 1, "turns": 4}]
    assert next(item for item in result["recent_sessions"] if item["session_id"] == "multi")["turns"] == 3

    cohort = store.online_metrics.summary({"source": "formal", "skill": "case_explanation", "mode": "specified",
                                          "config_version": "v2", "task_type": "explanation", "status": "abnormal",
                                          "from": "2026-10-15T00:00:00+00:00", "to": "2026-10-15T23:59:59+00:00"})
    assert cohort["sessions"] == 1 and cohort["questions"] == 3
    assert cohort["population_run_ids"] == [first["run_id"], second["run_id"], third["run_id"]]
    assert cohort["by_task"] == {"case_search": 1, "explanation": 1}
    # A follow-up date never turns an earlier conversation into a new cohort.
    assert store.online_metrics.summary({"from": "2026-10-16T00:00:00+00:00"})["sessions"] == 0
    # Conditions must match the same turn, rather than different turns in a conversation.
    assert store.online_metrics.summary({"mode": "specified", "skill": "case_reference"})["sessions"] == 0
    empty = store.online_metrics.summary({"skill": "missing"})
    assert empty["mean_turns"] is None and empty["multi_turn"]["rate"] is None
    store.close()


def test_conversations_isolate_owners_sources_and_keep_missing_traces_visible():
    store = RunStore()
    save_turn(store, "shared", "first")
    save_turn(store, "shared", "test", source="test")
    save_turn(store, "shared", "another-owner", owner="other")
    missing = admit(store, session_id="missing", turn_id="missing", request_id="missing")
    store.live.finish(missing["run_id"], status="interrupted")
    result = store.online_metrics.summary({"source": "formal"}, include_sessions=True)
    assert result["sessions"] == 3 and result["questions"] == 3 and result["trace_missing"] == 1
    assert result["session_states"] == {"normal": 2, "abnormal": 1}
    assert next(item for item in result["recent_sessions"] if item["session_id"] == "missing")["run_id"] is None
    assert store.online_metrics.summary({"source": "test"})["sessions"] == 1
    assert store.online_metrics.summary({})["sessions"] == 4
    store.close()


def test_trace_only_conversations_are_included_without_inventing_turn_links():
    store = RunStore()
    for index in range(2):
        store.append(RunTrace(run_id=f"legacy-{index}", conversation_ref="digest-only", started_at=f"2026-10-15T01:00:0{index}+00:00",
                              input="相同问题", state_before=StateSnapshot(), status="ok", config_version="legacy"))
    summary = store.online_metrics.summary({"source": "legacy"}, include_sessions=True)
    assert summary["sessions"] == 1 and summary["questions"] == 2
    assert summary["multi_turn"]["rate"] == 1 and summary["trace_missing"] == 0
    assert summary["recent_sessions"][0]["run_id"] == "legacy-0"
    store.close()


@pytest.mark.parametrize(("status", "expected"), [("accepted", "running"), ("running", "running"),
                                                   ("unknown", "unknown"), ("cancelled", "abnormal"),
                                                   ("interrupted", "abnormal")])
def test_session_states_include_unfinished_and_unconfirmed_turns(status, expected):
    store = RunStore()
    save_turn(store, "session", "first")
    current = admit(store, turn_id="pending", request_id="pending")
    if status != "accepted":
        store.live.finish(current["run_id"], status=status)
    result = store.online_metrics.summary({"status": expected})
    assert result["sessions"] == 1 and result["questions"] == 2
    assert result["session_states"] == {expected: 1}
    store.close()


@pytest.mark.asyncio
async def test_reviewer_metrics_do_not_expose_conversation_topics():
    store = RunStore()
    save_turn(store, "session", "first")
    app = make_app(store)
    app.include_router(online_metrics.router, prefix="/api")
    app.dependency_overrides[online_metrics.current_user] = lambda: Principal(tester_id="reviewer", role="reviewer")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/eval/online-metrics")
        assert response.status_code == 200
        assert response.json()["sessions"] == 1 and response.json()["recent_sessions"] == []
        assert "问题 first" not in response.text
    store.close()


@pytest.mark.asyncio
async def test_metrics_keep_auth_and_session_traces_after_review_endpoints_are_removed():
    store = RunStore()
    app = make_app(store)
    app.state.evaluation = SimpleNamespace(store=SimpleNamespace(runs=store))
    app.include_router(online_metrics.router, prefix="/api")
    app.include_router(explanation_trials.router, prefix="/api")
    headers = {"Authorization": "Bearer " + TOKEN}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        await client.get("/api/chat/session")
        receipt = (await client.post("/api/chat", json=body())).json()
        await finished(client, receipt["run_id"])
        assert (await client.get("/api/eval/online-metrics")).status_code == 401
        response = await client.get("/api/eval/online-metrics?mode=auto&source=formal", headers=headers)
        assert response.status_code == 200
        metrics = response.json()
        assert metrics["sessions"] == metrics["questions"] == 1
        assert metrics["session_states"] == {"normal": 1}
        assert metrics["recent_sessions"][0]["run_id"] == receipt["run_id"]
        assert metrics["steps"]["tool"]["success"]["rate"] is None
        assert metrics["steps"]["skill"]["success"]["rate"] == 1
        assert metrics["by_skill"][0]["calls"] == 1
        assert not {"dimensions", "review_coverage", "review_states", "sampling_sources", "primary_causes"} & metrics.keys()
        assert (await client.get("/api/eval/online-metrics?source=test", headers=headers)).json()["questions"] == 0
        skill = metrics["by_skill"][0]["skill"]
        assert (await client.get("/api/eval/online-metrics", params={"skill": skill}, headers=headers)).json()["questions"] == 1
        assert (await client.get("/api/eval/online-metrics?skill=missing", headers=headers)).json()["questions"] == 0
        assert (await client.get("/api/eval/online-metrics?from=2026-10-17", headers=headers)).status_code == 422
        assert (await client.get("/api/eval/online-metrics?source=invalid", headers=headers)).status_code == 422
        assert (await client.get("/api/eval/online-metrics?status=invalid", headers=headers)).status_code == 422
        for method, path in (("GET", "/formal-runs"), ("GET", f"/formal-runs/{receipt['run_id']}"),
                             ("POST", f"/formal-runs/{receipt['run_id']}/reviews"),
                             ("POST", f"/formal-runs/{receipt['run_id']}/replay"), ("POST", "/formal-samples")):
            response = await client.request(method, "/api/eval" + path, headers=headers)
            assert response.status_code == 404
        session = (await client.get("/api/eval/sessions/" + receipt["run_id"], headers=headers)).json()
        assert session["turn_count"] == 1 and session["turns"][0]["run_id"] == receipt["run_id"]
        assert session["turns"][0]["understanding"]["raw_query"] == body()["query"]
        assert (await client.get("/api/eval/explanation-method", headers=headers)).status_code == 200
    await app.state.chat_runs.shutdown()
    store.close()
