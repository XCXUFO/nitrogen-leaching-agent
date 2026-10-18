"""Durable account transcripts use real SQLite and authenticated API calls."""
import asyncio
import hashlib
import json
import time

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from src.agent.chat_service import ChatServiceResult, Citation
from src.agent.runtime import AgentRuntime
from src.api import chat
from src.agent.submissions import ChatRunManager
from src.evaluation.contracts import AccessFile
from src.llm.base import ChatUsage
from src.storage.run_store import RunStore


class Literature:
    def __init__(self):
        self.release = asyncio.Event()
        self.release.set()

    async def answer(self, query, **kwargs):
        await self.release.wait()
        return ChatServiceResult(answer="历史回答 [1]", citations=[Citation(index=1, chunk_id="chunk-a",
            source="paper.pdf", score=.9, snippet="原文依据")], usage=ChatUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7),
            retrieved_count=1, model="history-test")


def headers(account):
    return {"Authorization": "Bearer " + account * 40}


def app_for(store):
    app = FastAPI()
    app.state.agent_runtime = AgentRuntime(runs=store)
    app.state.chat_service = Literature()
    app.state.eval_access = AccessFile(users=[{"tester_id": name, "role": role,
        "token_sha256": hashlib.sha256((name * 40).encode()).hexdigest()}
        for name, role in (("a", "tester"), ("b", "reviewer"), ("c", "developer"))])
    app.include_router(chat.router, prefix="/api")
    return app


@pytest_asyncio.fixture
async def context(tmp_path):
    store = RunStore(tmp_path / "history.sqlite3")
    app = app_for(store)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://test") as client:
        yield app, client, store
    if hasattr(app.state, "chat_runs"):
        await app.state.chat_runs.shutdown()
    store.close()


async def submit(client, account="a", **changes):
    body = {"query": "小麦的氮素迁移有哪些过程？", "session_id": "chat-one", "file_ids": [],
            "turn_id": "turn-one", "request_id": "request-one", **changes}
    receipt = await client.post("/api/chat", json=body, headers=headers(account))
    assert receipt.status_code == 202, receipt.text
    return receipt.json(), body


async def finish(client, run, account="a"):
    for _ in range(100):
        value = (await client.get("/api/chat/runs/" + run["run_id"], headers=headers(account))).json()
        if value["status"] not in {"accepted", "running"}:
            return value
        await asyncio.sleep(.005)
    raise AssertionError("Test request did not finish")


async def history(client, account="a", **params):
    response = await client.get("/api/chat/history", params=params, headers=headers(account))
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


@pytest.mark.asyncio
async def test_history_is_owned_by_verified_account_and_keeps_full_answers(context):
    _, client, _ = context
    for account in ("a", "b", "c"):
        receipt, _ = await submit(client, account, operator_id="a", query=f"小麦土壤氮素迁移问题 {account}")
        result = await finish(client, receipt, account)
        assert result["status"] == "succeeded"
    assert (await client.get("/api/chat/history")).status_code == 401
    for account in ("a", "b", "c"):
        saved = await history(client, account, account_id="a")
        assert saved["total"] == 1
        item = saved["items"][0]
        assert item["id"] == "chat-one"
        turn = item["turns"][0]
        assert turn["recoverable"]
        assert turn["request"]["query"].endswith(account)
        assert turn["response"]["citations"][0]["snippet"] == "原文依据"
        assert turn["response"]["usage"]["total_tokens"] == 7


@pytest.mark.asyncio
async def test_history_survives_recovery_cleanup_restart_and_allows_new_turns(context):
    app, client, store = context
    receipt, original = await submit(client)
    await finish(client, receipt)
    with store._lock, store._connection:
        store._connection.execute("UPDATE chat_submissions SET expires_at=?", (time.time() - 1,))
        store._connection.execute("UPDATE chat_run_conversations SET expires_at=?", (time.time() - 1,))
    expired = await client.get("/api/chat/runs/" + receipt["run_id"], headers=headers("a"))
    assert expired.status_code == 410
    assert (await history(client))["items"][0]["turns"][0]["response"]["answer"] == "历史回答 [1]"
    assert (await client.post("/api/chat", json=original, headers=headers("a"))).status_code == 410
    await app.state.chat_runs.shutdown()
    reopened = RunStore(store._connection.execute("PRAGMA database_list").fetchone()[2])
    other = app_for(reopened)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(other), base_url="http://test") as second:
        before = await history(second)
        assert before["items"][0]["turns"][0]["response"]["citations"]
        follow, _ = await submit(second, turn_id="turn-two", request_id="request-two", query="如何减少小麦氮素淋失？",
            history=[{"role": "user", "content": original["query"]}, {"role": "assistant", "content": "历史回答 [1]"}])
        assert (await finish(second, follow))["status"] == "succeeded"
        saved = await history(second)
        assert saved["total"] == 1 and len(saved["items"][0]["turns"]) == 2
    await other.state.chat_runs.shutdown()
    reopened.close()


@pytest.mark.asyncio
async def test_pending_run_is_archived_without_browser_and_interruption_is_visible(context):
    app, client, store = context
    app.state.chat_service.release.clear()
    receipt, _ = await submit(client)
    pending = await history(client)
    assert pending["items"][0]["turns"][0]["status"] == "accepted"
    app.state.chat_service.release.set()
    await finish(client, receipt)
    assert (await history(client))["items"][0]["turns"][0]["response"]["answer"]
    app.state.chat_service.release.clear()
    await submit(client, turn_id="turn-two", request_id="request-two")
    await asyncio.sleep(.01)
    # Simulate a process restart that left an unfinished durable submission.
    with store._lock, store._connection:
        store._connection.execute("UPDATE chat_submissions SET status='running' WHERE turn_id='turn-two'")
    store.live.recover_interrupted()
    interrupted = (await history(client))["items"][0]["turns"][-1]
    assert interrupted["status"] == "interrupted"
    assert interrupted["error"]["code"] == "run_interrupted"


@pytest.mark.asyncio
async def test_duplicate_and_regeneration_do_not_duplicate_the_question(context):
    _, client, _ = context
    receipt, original = await submit(client)
    await finish(client, receipt)
    repeated = await client.post("/api/chat", json=original, headers=headers("a"))
    assert repeated.json()["run_id"] == receipt["run_id"]
    rerun, _ = await submit(client, request_id="regenerate", rerun_of_run_id=receipt["run_id"])
    await finish(client, rerun)
    turns = (await history(client))["items"][0]["turns"]
    assert len(turns) == 1 and turns[0]["run_id"] == rerun["run_id"]


@pytest.mark.asyncio
async def test_existing_account_records_are_backfilled_once_and_paginated(context):
    _, client, store = context
    for index in range(12):
        receipt, _ = await submit(client, session_id=f"old-{index}")
        await finish(client, receipt)
    with store._lock, store._connection:
        store._connection.execute("DELETE FROM account_chat_turns")
        store._connection.execute("DELETE FROM account_chat_conversations")
        raw, session_id = store._connection.execute("SELECT payload,session_id FROM agent_runs LIMIT 1").fetchone()
        trace = json.loads(raw)
        trace.update(run_id="evaluation-only", source="evaluation")
        store._connection.execute("INSERT INTO agent_runs VALUES (?,?,?,?,?,?,?)",
            (trace["run_id"], trace["started_at"], trace["conversation_ref"], "ok", json.dumps(trace), session_id, "a"))
    page = await history(client, limit=5)
    assert page["total"] == 12 and len(page["items"]) == 5
    assert all(item["id"].startswith("saved_") for item in page["items"])
    assert all(not turn["recoverable"] for item in page["items"] for turn in item["turns"])
    assert (await history(client, offset=5, limit=10))["total"] == 12
    assert (await history(client, "b"))["items"] == []
    # Continue one imported transcript; the next import must not split it.
    imported = page["items"][0]
    follow, _ = await submit(client, session_id=imported["id"], turn_id="continued", request_id="continued")
    await finish(client, follow)
    assert (await history(client))["total"] == 12
