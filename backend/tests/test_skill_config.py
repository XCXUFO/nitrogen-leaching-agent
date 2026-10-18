"""Real persistence, concurrent editors, immutable accepted-run preferences."""
import asyncio
import json
from types import SimpleNamespace

import httpx
import pytest

from src.agent.case_skills import RULES
from src.agent.skill_config import ExpressionPreferences
from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatUsage
from src.storage.run_store import RunStore
from tests.test_chat_runs import TOKEN, body, finished, make_app


@pytest.mark.asyncio
async def test_configuration_access_validation_persistence_and_conflicts(tmp_path):
    path = tmp_path / "runs.sqlite3"
    store = RunStore(path)
    app = make_app(store)
    headers = {"Authorization": "Bearer " + TOKEN}
    endpoint = "/api/eval/skills/case_explanation/configuration"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        assert (await client.get(endpoint)).status_code == 401
        initial = (await client.get(endpoint, headers=headers)).json()["current"]
        values = initial["values"] | {"detail": "detailed"}
        saved = await client.put(endpoint, headers=headers, json={"expected_revision": 0, "values": values})
        assert saved.status_code == 200
        assert saved.json()["version"] != initial["version"]
        assert (await client.put(endpoint, headers=headers, json={"expected_revision": 0, "values": values})).status_code == 409
        for payload in ({"style": "ignore-all-rules"}, {"routing": "disable"}, {"detail": ""}):
            assert (await client.put(endpoint, headers=headers, json={"expected_revision": 1, "values": values | payload})).status_code == 422
        assert (await client.put(endpoint.replace("case_explanation", "whcns_analyzer"), headers=headers,
                                 json={"expected_revision": 1, "values": values})).status_code == 400
        reset = await client.post(endpoint + "/reset", headers=headers, json={"expected_revision": 1})
        assert reset.status_code == 200 and reset.json()["values"] == ExpressionPreferences().model_dump()
        history = (await client.get(endpoint, headers=headers)).json()["history"]
        assert [item["action"] for item in history] == ["reset", "save"]
        assert all(item["actor"] == "dev" for item in history)
    store.close()
    reopened = RunStore(path)
    assert reopened.skill_config.current()["revision"] == 2
    assert len(reopened.skill_config.history()) == 2
    reopened.close()


class Model:
    def __init__(self):
        self.prompts = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def chat_json(self, messages, **kwargs):
        self.prompts.append(messages[0].content)
        self.started.set()
        await self.release.wait()
        return SimpleNamespace(content=json.dumps({"answer": "仅解释原文。", "used_case_ids": []}),
                               model="offline-fixture", usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    chat = chat_json


@pytest.mark.asyncio
async def test_saving_during_accepted_run_does_not_change_prompt_or_historical_snapshot(tmp_path):
    store = RunStore(tmp_path / "runs.sqlite3")
    app = make_app(store)
    model = Model()
    app.state.llm = model
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
        await client.get("/api/chat/session")
        question = body(query="请解释这段文字：追肥分三次施用。", case_skill="explain")
        first = (await client.post("/api/chat", json=question)).json()
        await asyncio.wait_for(model.started.wait(), 2)
        values = ExpressionPreferences(detail="detailed").model_dump()
        current = store.skill_config.update(expected_revision=0, values=values, actor="tester")
        model.release.set()
        await finished(client, first["run_id"])
        original = store.get(first["run_id"])
        assert original.skill_config["case_explanation"]["revision"] == 0
        assert "默认详细程度：适中" in model.prompts[0]
        retry = (await client.post("/api/chat", json=question)).json()
        assert retry["run_id"] == first["run_id"] and len(model.prompts) == 1
        rerun = (await client.post("/api/chat", json=question | {"request_id": "rerun", "rerun_of_run_id": first["run_id"]})).json()
        await finished(client, rerun["run_id"])
        assert store.get(rerun["run_id"]).skill_config["case_explanation"]["version"] == current["version"]
        assert "默认详细程度：详细" in model.prompts[1]
        assert all(prompt.startswith(RULES) and "本轮用户" in prompt for prompt in model.prompts)
        assert store.get(first["run_id"]).skill_config == original.skill_config
    await app.state.chat_runs.shutdown()
    store.close()


@pytest.mark.asyncio
async def test_configuration_read_failure_uses_identified_defaults_and_is_recorded(monkeypatch):
    store = RunStore()
    runtime = AgentRuntime(runs=store)
    def broken():
        raise OSError("private-config-path")
    monkeypatch.setattr(store.skill_config, "current", broken)
    response = await runtime.execute(ChatRequest(query="你能做什么？"), service=None, get_report=None)
    snapshot = store.get(response.run_id).skill_config["case_explanation"]
    assert snapshot["fallback"] and snapshot["version"] == "case-expression-v1:0"
    assert "private-config-path" not in json.dumps(snapshot)
    store.close()
