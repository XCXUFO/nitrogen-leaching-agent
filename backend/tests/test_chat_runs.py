"""Executable recovery boundaries: real API/SQLite, no remote model calls."""
from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from src.agent.chat_service import ChatServiceResult, Citation
from src.agent.runtime import AgentRuntime
from src.api import chat, demo, evaluation, files
from src.evaluation.contracts import AccessFile
from src.llm.base import ChatUsage
from src.operations.public_access import COOKIE, PublicAccess, public_access
from src.operations.visitor_identity import signed_visitor
from src.storage.run_store import RunStore

QUESTION = "小麦土壤中的氮素迁移有哪些过程？"
TOKEN = "run-test-developer-" + "a" * 32


class Service:
    def __init__(self):
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.citations = []

    async def answer(self, query, **kwargs):
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return ChatServiceResult(answer="固定回答。" + ("[1]" if self.citations else ""), citations=self.citations,
                                 usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
                                 retrieved_count=len(self.citations), model="isolated-test")


def make_app(store, *, public=False):
    app = FastAPI()
    app.state.agent_runtime = AgentRuntime(runs=store, config_version="run-test:fixed-version")
    app.state.chat_service = Service()
    app.state.eval_access = AccessFile(users=[{"tester_id": "dev", "role": "developer", "token_sha256": hashlib.sha256(TOKEN.encode()).hexdigest()}])
    app.state.public_settings = SimpleNamespace(public_demo_enabled=public, public_cookie_secure=False,
        public_budget_db=":memory:", public_requests_per_minute=120, public_daily_chat_limit=100,
        public_max_concurrent=2, cors_origin_list=["http://testserver"])
    if public:
        app.state.public_access = PublicAccess(app.state.public_settings)
    for router in (chat.router, demo.router, files.router, evaluation.router):
        app.include_router(router, prefix="/api")
    app.middleware("http")(public_access)
    return app


@pytest_asyncio.fixture
async def context(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    app = make_app(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        handshake = await client.get("/api/chat/session")
        assert handshake.status_code == 200
        yield app, client, store
    if hasattr(app.state, "chat_runs"):
        await app.state.chat_runs.shutdown()
    store.close()


def body(**changes):
    return {"query": QUESTION, "session_id": "conversation-one", "turn_id": "turn-one", "request_id": "request-one", **changes}


async def finished(client, run_id):
    for _ in range(200):
        response = await client.get("/api/chat/runs/" + run_id)
        assert response.status_code == 200, response.text
        value = response.json()
        if value["status"] not in {"accepted", "running"}:
            return value
        await asyncio.sleep(0.005)
    raise AssertionError("Isolated run did not finish")


@pytest.mark.asyncio
async def test_same_visitor_independent_conversations_remain_separate_in_reviews(context):
    _, client, store = context
    questions = ["明天吃啥", "你妈是谁", "解释下动能定理", "1", "晚上好"]
    run_ids = []
    for index, question in enumerate(questions):
        response = await client.post("/api/chat", json=body(
            query=question, session_id=f"independent-{index}"))
        assert response.status_code == 202, response.text
        result = await finished(client, response.json()["run_id"])
        assert result["status"] == "succeeded"
        run_ids.append(result["run_id"])
    listing = store.sessions()
    assert listing["total"] == 5
    assert len({item["operator_id"] for item in listing["items"]}) == 1
    assert all(item["turn_count"] == 1 for item in listing["items"])
    for run_id, question in zip(run_ids, questions):
        session = store.session(run_id)
        assert session["topic"] == question
        assert [turn["run_id"] for turn in session["turns"]] == [run_id]


@pytest.mark.asyncio
async def test_lost_receipt_recovered_by_request_and_concurrent_retries_execute_once(context):
    app, client, store = context
    service = app.state.chat_service
    service.release.clear()
    first, duplicate = await asyncio.gather(client.post("/api/chat", json=body()), client.post("/api/chat", json=body()))
    assert first.status_code == duplicate.status_code == 202
    assert first.json()["run_id"] == duplicate.json()["run_id"]
    await service.started.wait()
    lookup = await client.get("/api/chat/requests/request-one", params={"session_id": "conversation-one"})
    assert lookup.status_code == 200
    assert lookup.json()["run_id"] == first.json()["run_id"]
    assert lookup.json()["status"] == "running"
    assert lookup.json()["result"] is None
    assert [event["type"] for event in lookup.json()["events"] if event.get("kind") != "service"] == ["run_accepted", "plan_created", "step_started"]
    assert service.calls == 1
    service.release.set()
    result = await finished(client, first.json()["run_id"])
    assert result["status"] == "succeeded" and result["result_saved"]
    assert result["result"]["answer"] == "固定回答。"
    replay = await client.post("/api/chat", json=body())
    assert replay.status_code == 202 and replay.json()["result"] == result["result"]
    assert service.calls == 1
    trace = store.get(result["run_id"])
    assert (trace.turn_id, trace.request_id, trace.primary_run_id, trace.source, trace.mode) == ("turn-one", "request-one", trace.run_id, "formal", "auto")


@pytest.mark.asyncio
async def test_request_conflict_and_explicit_rerun_keep_primary_and_trace_immutable(context):
    app, client, store = context
    accepted = (await client.post("/api/chat", json=body())).json()
    original = await finished(client, accepted["run_id"])
    assert (await client.post("/api/chat", json=body(query="另一问题"))).status_code == 409
    assert (await client.post("/api/chat", json=body(request_id="other-request"))).status_code == 409
    changed = await client.post("/api/chat", json=body(request_id="rerun-request", query="修改原问题", rerun_of_run_id=original["run_id"]))
    assert changed.status_code == 409
    second = await client.post("/api/chat", json=body(request_id="rerun-request", rerun_of_run_id=original["run_id"]))
    assert second.status_code == 202
    rerun = await finished(client, second.json()["run_id"])
    assert rerun["run_id"] != original["run_id"]
    assert rerun["primary_run_id"] == original["run_id"]
    assert rerun["rerun_of_run_id"] == original["run_id"]
    assert store.get(original["run_id"]).request_id == "request-one"
    assert app.state.chat_service.calls == 2


@pytest.mark.asyncio
async def test_visitor_and_authenticated_ownership_cannot_be_forged(context):
    app, alice, _ = context
    accepted = (await alice.post("/api/chat", json=body(operator_id="visitor_fake-owner"))).json()
    await finished(alice, accepted["run_id"])
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as bob:
        await bob.get("/api/chat/session")
        assert (await bob.get("/api/chat/runs/" + accepted["run_id"])).status_code == 404
        assert (await bob.get("/api/chat/requests/request-one", params={"session_id": "conversation-one"})).status_code == 404
        bob.cookies.set(COOKIE, "x" * 32 + "." + "0" * 64)
        assert (await bob.get("/api/chat/runs/" + accepted["run_id"])).status_code == 404
    internal = {"Authorization": "Bearer " + TOKEN}
    internal_run = await alice.post("/api/chat", json=body(request_id="internal-request"), headers=internal)
    assert internal_run.status_code == 202
    assert (await alice.get("/api/chat/runs/" + internal_run.json()["run_id"])).status_code == 404
    assert (await alice.get("/api/chat/runs/" + internal_run.json()["run_id"], headers=internal)).status_code == 200
    assert (await alice.get("/api/chat/runs/" + accepted["run_id"], headers=internal)).status_code == 404


@pytest.mark.asyncio
async def test_complete_enriched_response_and_events_survive_process_reopen(context, monkeypatch):
    app, client, store = context
    app.state.chat_service.citations = [Citation(index=1, chunk_id="chunk-one", source="local-paper", score=1, snippet="原文依据。")]
    monkeypatch.setattr(chat, "citation_metadata", lambda source: {"title": "补充题名", "author_hint": "张三、李四", "year": "2024", "document_id": "document-one", "document_available": True})
    receipt = (await client.post("/api/chat", json=body())).json()
    result = await finished(client, receipt["run_id"])
    assert result["result"]["citations"][0]["title"] == "补充题名"
    assert result["result"]["citations"][0]["author_hint"] == "张三、李四"
    assert result["result"]["citations"][0]["year"] == "2024"
    assert result["result"]["citations"][0]["document_id"] == "document-one"
    assert result["result"]["trace_saved"]
    path = store._connection.execute("PRAGMA database_list").fetchone()[2]
    reopened = RunStore(path)
    restarted = make_app(reopened)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted), base_url="http://testserver", cookies=client.cookies) as recovered:
            saved = await recovered.get("/api/chat/runs/" + receipt["run_id"])
            assert saved.status_code == 200 and saved.json()["result"] == result["result"]
            after = await recovered.get("/api/chat/runs/" + receipt["run_id"], params={"after": 3})
            assert all(event["sequence"] > 3 for event in after.json()["events"])
            assert [event["sequence"] for event in saved.json()["events"]] == list(range(1, saved.json()["last_sequence"] + 1))
            assert restarted.state.chat_service.calls == 0
    finally:
        if hasattr(restarted.state, "chat_runs"):
            await restarted.state.chat_runs.shutdown()
        reopened.close()


@pytest.mark.asyncio
async def test_dropped_connection_does_not_cancel_an_accepted_task(context):
    app, client, _ = context
    service = app.state.chat_service
    service.release.clear()
    receipt = (await client.post("/api/chat", json=body())).json()
    await service.started.wait()
    # The submit response has completed; a separate reader can recover while the
    # original HTTP operation no longer exists.
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver", cookies=client.cookies) as reader:
        assert (await reader.get("/api/chat/runs/" + receipt["run_id"])).json()["status"] == "running"
        service.release.set()
        result = await finished(reader, receipt["run_id"])
        assert result["status"] == "succeeded" and service.calls == 1


@pytest.mark.asyncio
async def test_terminal_failure_is_not_retried_and_new_run_keeps_failed_primary(context):
    app, client, _ = context
    app.state.chat_service = None
    receipt = (await client.post("/api/chat", json=body())).json()
    failed = await finished(client, receipt["run_id"])
    assert failed["status"] == "failed" and failed["error"]["code"] == "rag_not_configured"
    app.state.chat_service = Service()
    repeated = await client.post("/api/chat", json=body())
    assert repeated.json()["status"] == "failed" and app.state.chat_service.calls == 0
    rerun = await client.post("/api/chat", json=body(request_id="after-repair", rerun_of_run_id=receipt["run_id"]))
    successful = await finished(client, rerun.json()["run_id"])
    assert successful["status"] == "succeeded" and successful["primary_run_id"] == failed["run_id"]


@pytest.mark.asyncio
@pytest.mark.parametrize("code,status,expected", [
    ("llm_unreachable", 502, "无法连接大模型服务"),
    ("llm_timeout", 504, "大模型响应超时"),
    ("llm_rate_limited", 429, "大模型服务请求较多"),
    ("llm_auth_failed", 500, "大模型服务配置异常"),
    ("llm_upstream_error", 502, "大模型服务暂时不可用"),
    ("rag_query_failed", 503, "文献检索暂时失败"),
    ("internal_error", 500, "服务内部异常"),
    ("unknown_provider_error", 502, "本次处理未完成"),
])
async def test_recoverable_failure_preserves_error_category_without_raw_details(context, code, status, expected):
    from fastapi import HTTPException
    app, client, store = context
    async def fail(*args, **kwargs):
        raise HTTPException(status, detail={"code": code, "message": "private-provider-detail"})
    app.state.chat_service.answer = fail
    receipt = (await client.post("/api/chat", json=body())).json()
    terminal = await finished(client, receipt["run_id"])
    assert terminal["status"] == "failed"
    assert terminal["error"]["code"] == code and terminal["error"]["http_status"] == status
    assert expected in terminal["error"]["message"]
    assert "private-provider-detail" not in terminal["error"]["message"]
    replay = await client.post("/api/chat", json=body())
    assert replay.json()["error"] == terminal["error"]


@pytest.mark.asyncio
async def test_restore_expired_returns_410_and_keeps_tombstone(context):
    app, client, store = context
    receipt = (await client.post("/api/chat", json=body())).json()
    await finished(client, receipt["run_id"])
    with store._connection:
        store._connection.execute("UPDATE chat_submissions SET expires_at=?", (time.time() - 1,))
        store._connection.execute("UPDATE chat_run_conversations SET expires_at=?", (time.time() - 1,))
    assert (await client.get("/api/chat/runs/" + receipt["run_id"])).status_code == 410
    assert (await client.post("/api/chat", json=body())).status_code == 410
    assert (await client.post("/api/chat", json=body(turn_id="new-turn", request_id="new-request"))).status_code == 410
    assert store._connection.execute("SELECT result_json FROM chat_submissions").fetchone()[0] is None
    assert store._connection.execute("SELECT status FROM chat_submissions").fetchone()[0] == "succeeded"
    assert app.state.chat_service.calls == 1


@pytest.mark.asyncio
async def test_delayed_completion_event_is_committed_with_result_without_reexecution(context, monkeypatch):
    app, client, store = context
    original_event = store.live.event
    failed = False

    def event(run_id, value):
        nonlocal failed
        if value["type"] == "step_finished" and value.get("kind") == "skill" and not failed:
            failed = True
            raise sqlite3.OperationalError("transient write failure")
        return original_event(run_id, value)

    monkeypatch.setattr(store.live, "event", event)
    receipt = (await client.post("/api/chat", json=body())).json()
    result = await finished(client, receipt["run_id"])
    assert result["status"] == "succeeded" and result["result_saved"]
    assert [item["type"] for item in result["events"]][-2:] == ["step_finished", "run_finished"]
    assert app.state.chat_service.calls == 1


@pytest.mark.asyncio
async def test_unrecorded_step_start_never_invokes_model(context, monkeypatch):
    app, client, store = context
    original_event = store.live.event

    def event(run_id, value):
        if value["type"] == "step_started" and value.get("kind") == "skill":
            raise sqlite3.OperationalError("temporarily locked")
        return original_event(run_id, value)

    monkeypatch.setattr(store.live, "event", event)
    receipt = (await client.post("/api/chat", json=body())).json()
    result = await finished(client, receipt["run_id"])
    assert result["status"] == "failed" and app.state.chat_service.calls == 0
    assert result["events"][-2]["outcome"] == "not_executed"
    assert store.get(receipt["run_id"]).tool_calls == []


@pytest.mark.asyncio
async def test_delayed_prior_event_stops_next_skill_instead_of_running_unrecorded(context, monkeypatch):
    _, client, store = context
    original_event = store.live.event

    def event(run_id, value):
        if value["type"] == "step_finished" and value.get("kind") == "skill":
            raise sqlite3.OperationalError("temporarily locked")
        return original_event(run_id, value)

    monkeypatch.setattr(store.live, "event", event)
    raw = (await client.get("/api/demo/examples/nitrogen")).content
    upload = await client.post("/api/files?filename=Nbal_out.xls&session_id=conversation-one", content=raw)
    receipt = (await client.post("/api/chat", json=body(query="硝态氮淋失最大值及对应日序", file_ids=[upload.json()["file_id"]]))).json()
    result = await finished(client, receipt["run_id"])
    assert result["status"] == "failed"
    assert [call.skill for call in store.get(receipt["run_id"]).tool_calls] == ["file_inspector"]
    assert result["events"][-2]["skill"] == "whcns_analyzer"
    assert result["events"][-2]["outcome"] == "not_executed"


@pytest.mark.asyncio
async def test_shutdown_before_task_first_instruction_still_records_terminal_status(context):
    app, _, store = context
    manager = app.state.chat_runs
    called = False

    async def execute(record, observer):
        nonlocal called
        called = True

    receipt = manager.submit(execute=execute, owner="isolated", session_id="isolated", turn_id="isolated",
        request_id="isolated", fingerprint="isolated", rerun_of_run_id=None, config_version="test", mode="auto")
    await manager.shutdown()
    assert not called and manager.tasks == {}
    assert store.live.get("isolated", receipt["run_id"])["status"] == "cancelled"


@pytest.mark.asyncio
async def test_result_save_failure_is_unknown_with_explicit_volatile_answer(context, monkeypatch):
    app, client, store = context

    def fail_save(*args, **kwargs):
        raise sqlite3.OperationalError("private internal database path")

    monkeypatch.setattr(store.live, "finish", fail_save)
    receipt = (await client.post("/api/chat", json=body())).json()
    result = await finished(client, receipt["run_id"])
    assert result["status"] == "unknown" and not result["result_saved"]
    assert result["result"]["answer"] == "固定回答。"
    assert "private internal" not in json.dumps(result)
    assert (await client.post("/api/chat", json=body())).json()["run_id"] == receipt["run_id"]
    assert app.state.chat_service.calls == 1


@pytest.mark.asyncio
async def test_admission_failure_never_starts_model(context, monkeypatch):
    app, client, store = context
    monkeypatch.setattr(store.live, "admit", lambda **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("unavailable")))
    response = await client.post("/api/chat", json=body())
    assert response.status_code == 503 and response.json()["detail"]["code"] == "run_admission_unavailable"
    assert app.state.chat_service.calls == 0


@pytest.mark.asyncio
async def test_busy_and_capacity_do_not_block_recovery_or_duplicate_receipts(context):
    app, client, _ = context
    service = app.state.chat_service
    service.release.clear()
    app.state.chat_runs.max_active = 1
    receipt = (await client.post("/api/chat", json=body())).json()
    await service.started.wait()
    duplicate = await client.post("/api/chat", json=body())
    assert duplicate.status_code == 202 and duplicate.json()["run_id"] == receipt["run_id"]
    assert (await client.post("/api/chat", json=body(session_id="another", turn_id="other", request_id="other"))).status_code == 429
    assert (await client.get("/api/chat/runs/" + receipt["run_id"])).status_code == 200
    service.release.set()
    await finished(client, receipt["run_id"])


@pytest.mark.asyncio
async def test_real_file_evidence_and_clarification_remain_distinct(context):
    _, client, _ = context
    raw = (await client.get("/api/demo/examples/nitrogen")).content
    upload = await client.post("/api/files?filename=Nbal_out.xls&session_id=conversation-one", content=raw)
    assert upload.status_code == 200
    receipt = await client.post("/api/chat", json=body(query="硝态氮淋失最大值及对应日序", file_ids=[upload.json()["file_id"]]))
    computed = await finished(client, receipt.json()["run_id"])
    assert computed["result"]["file_evidence"][0]["model_day"] == 283
    assert [event["skill"] for event in computed["events"] if event["type"] == "step_started" and event.get("kind") == "skill"] == ["file_inspector", "whcns_analyzer"]
    clarify = await client.post("/api/chat", json=body(query="那最小值呢？", session_id="no-file", turn_id="missing", request_id="missing", file_ids=[]))
    result = await finished(client, clarify.json()["run_id"])
    assert result["status"] == "succeeded" and result["outcome"] == "clarification"
    assert not any(event["kind"] == "tool" for event in result["events"] if event["type"] == "step_started")


def test_durable_unique_admission_across_connections_and_restart_never_replays(tmp_path):
    path = tmp_path / "shared.sqlite3"
    first, second = RunStore(path), RunStore(path)
    data = dict(owner="owner", session_id="session", turn_id="turn", request_id="request", fingerprint="input-hash",
                rerun_of_run_id=None, config_version="fixed", mode="auto", retention_seconds=3600, max_active=8)
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            a, b = list(pool.map(lambda store: store.live.admit(**data), (first, second)))
        assert a[0]["run_id"] == b[0]["run_id"] and sum([a[1], b[1]]) == 1
        first.live.recover_interrupted()
        value = first.live.get("owner", a[0]["run_id"])
        assert value["status"] == "interrupted" and value["result"] is None
        same, created = second.live.admit(**data)
        assert not created and same["status"] == "interrupted"
    finally:
        first.close()
        second.close()


def test_malformed_unicode_signature_is_replaced_without_crashing():
    identity, cookie = signed_visitor(b"private-local-key", "x" * 32 + ".非 ASCII")
    assert len(identity) == 32 and cookie.startswith(identity + ".")


@pytest.mark.asyncio
async def test_public_budget_and_concurrency_follow_background_execution_and_not_retries(tmp_path):
    store = RunStore(tmp_path / "public.sqlite3")
    app = make_app(store, public=True)
    app.state.public_settings.public_max_concurrent = 1
    app.state.public_settings.public_daily_chat_limit = 1
    service = app.state.chat_service
    service.release.clear()
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
            await client.get("/api/chat/session")
            receipt = await client.post("/api/chat", json=body())
            assert receipt.status_code == 202
            await service.started.wait()
            assert app.state.public_access.active == 1
            repeated = await client.post("/api/chat", json=body())
            assert repeated.status_code == 202 and repeated.json()["run_id"] == receipt.json()["run_id"]
            assert app.state.public_access.active == 1
            assert app.state.public_access.db.execute("SELECT requests FROM budget").fetchone()[0] == 1
            limited = await client.post("/api/chat", json=body(session_id="another", turn_id="other", request_id="other"))
            assert limited.status_code == 429
            assert (await client.get("/api/chat/runs/" + receipt.json()["run_id"])).status_code == 200
            service.release.set()
            await finished(client, receipt.json()["run_id"])
            await asyncio.sleep(0)
            assert app.state.public_access.active == 0
            assert service.calls == 1
    finally:
        if hasattr(app.state, "chat_runs"):
            await app.state.chat_runs.shutdown()
        app.state.public_access.db.close()
        store.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("changes", [{"turn_id": None}, {"request_id": None}, {"session_id": None}, {"request_id": "bad/id"}])
async def test_invalid_lifecycle_identity_is_rejected_before_execution(context, changes):
    app, client, _ = context
    assert (await client.post("/api/chat", json=body(**changes))).status_code == 422
    assert app.state.chat_service.calls == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("public", [False, True])
async def test_visitor_cookie_covers_the_declared_recovery_window(monkeypatch, public):
    store = RunStore()
    app = make_app(store, public=public)
    monkeypatch.setattr(chat.settings, "chat_run_retention_seconds", 604800)
    app.state.public_settings.chat_run_retention_seconds = 604800
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        response = await client.get("/api/chat/session")
        assert response.json()["recovery_window_seconds"] == 604800
        assert "Max-Age=604800" in response.headers["set-cookie"]
    await app.state.chat_runs.shutdown()
    if public: app.state.public_access.db.close()
    store.close()
