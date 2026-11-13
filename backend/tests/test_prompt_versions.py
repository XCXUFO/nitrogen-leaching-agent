import asyncio

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.agent.explanation_method import METHOD_PROMPT, active_communication
from src.agent.runtime import AgentRuntime
from src.agent.skill_config import ExpressionPreferences, expression_instructions
from src.api import explanation_trials
from src.api.chat_schema import ChatRequest
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal, AccessFile
from src.evaluation.explanation_trials import ExplanationTrials, TrialInput, TrialPrompt, TrialPrompts
from src.storage.run_store import RunStore
from tests.test_case_library import FakeLLM
from tests.test_chat_service import FakeLLMClient, FakeRetriever
from src.agent.chat_service import ChatService
from src.rag.retriever import RetrievalResult
from tests.test_composition import DOCUMENT, payload


def test_original_two_versions_and_single_active_selection_survive_restart(tmp_path):
    path = tmp_path / "runs.sqlite3"
    store = RunStore(path)
    original = {item["label"]: item for item in store.prompts.list()}
    baseline = expression_instructions({"values": ExpressionPreferences().model_dump()})
    assert original["原版解释 v1"]["text"] == baseline
    assert original["增强解释 v2"]["text"] == baseline + METHOD_PROMPT
    assert store.prompts.active()["prompt_id"] == original["增强解释 v2"]["prompt_id"]
    saved = store.prompts.save("自定义 v3", "先解释术语再给结论。", "tester")
    assert store.prompts.save("自定义 v3", saved["text"], "tester") == saved
    assert store.prompts.active()["prompt_id"] != saved["prompt_id"]
    store.prompts.activate(saved["prompt_id"], "tester")
    with pytest.raises(HTTPException):
        store.prompts.activate("unknown", "tester")
    assert store.prompts.active()["prompt_id"] == saved["prompt_id"]
    store.close()
    reopened = RunStore(path)
    assert reopened.prompts.active()["prompt_id"] == saved["prompt_id"]
    assert reopened._connection.execute("SELECT COUNT(*) FROM active_prompt").fetchone()[0] == 1
    assert {item["label"]: item for item in reopened.prompts.list() if item["actor"] == "builtin"} == original
    reopened.close()


@pytest.mark.asyncio
async def test_save_and_activate_are_authenticated_and_need_no_model():
    store = RunStore()
    app = FastAPI()
    app.state.agent_runtime = AgentRuntime(runs=store)
    app.state.eval_access = AccessFile(users=[{"tester_id": "tester", "role": "tester", "token_sha256": "a" * 64}])
    app.include_router(explanation_trials.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for endpoint in ("/prompt-versions", "/active-prompt"):
            assert (await client.get("/api/eval" + endpoint)).status_code == 401
        app.dependency_overrides[current_user] = lambda: Principal(tester_id="tester", role="tester")
        before = (await client.get("/api/eval/active-prompt")).json()
        versions = (await client.get("/api/eval/prompt-versions")).json()
        assert len(versions) == 2
        for role in ("tester", "reviewer"):
            app.dependency_overrides[current_user] = lambda role=role: Principal(tester_id=role, role=role)
            denied = await client.post("/api/eval/prompt-versions", json={"label": "forbidden", "text": "不得保存。"})
            assert denied.status_code == 403
            assert (await client.get("/api/eval/prompt-versions")).json() == versions
        app.dependency_overrides[current_user] = lambda: Principal(tester_id="dev", role="developer")
        assert (await client.post("/api/eval/prompt-versions", json={"label": "  ", "text": "规则"})).status_code == 422
        response = await client.post("/api/eval/prompt-versions", json={"label": "v3", "text": "专业表达。"})
        assert response.status_code == 201
        saved = response.json()
        assert (await client.get("/api/eval/active-prompt")).json() == before
        chosen = await client.put("/api/eval/active-prompt", json={"prompt_id": saved["prompt_id"]})
        assert chosen.status_code == 200 and chosen.json()["text"] == saved["text"]
        assert (await client.put("/api/eval/active-prompt", json={"prompt_id": "missing"})).status_code == 404
    store.close()


@pytest.mark.asyncio
async def test_selected_prompt_reaches_case_rag_and_mechanisms_and_accepted_run_is_pinned(monkeypatch):
    async def inline(func, /, *args, **kwargs):
        return func(*args, **kwargs)
    monkeypatch.setattr(asyncio, "to_thread", inline)
    store = RunStore()
    runtime = AgentRuntime(runs=store)
    first = store.prompts.save("A", "表达规则 A：短句并解释术语。", "dev")
    second = store.prompts.save("B", "表达规则 B：详细描述证据边界。", "dev")
    store.prompts.activate(first["prompt_id"], "dev")
    pinned = runtime.expression_snapshot()
    store.prompts.activate(second["prompt_id"], "dev")
    case_model = FakeLLM()
    response = await runtime.execute(ChatRequest(query="解释这段文字：分次施肥", session_id="pinned", case_skill="explain"),
        service=None, get_report=None, llm=case_model, expression_config=pinned)
    assert first["text"] in case_model.messages[0].content and second["text"] not in case_model.messages[0].content
    assert store.get(response.run_id).skill_config["communication"]["prompt_id"] == first["prompt_id"]
    response = await runtime.execute(ChatRequest(query="解释这段文字：分次施肥", session_id="next", case_skill="explain"),
        service=None, get_report=None, llm=case_model)
    assert second["text"] in case_model.messages[0].content
    assert store.get(response.run_id).skill_config["communication"]["prompt_id"] == second["prompt_id"]
    rag_model = FakeLLMClient("材料表明硝态氮可随水迁移。[1]")
    rag = ChatService(FakeRetriever([RetrievalResult("one", DOCUMENT, .9, {"source": "synthetic.txt"})]),
                     rag_model, top_k=1, max_context_chars=4000, temperature=0)
    await runtime.execute(ChatRequest(query="氮淋失是什么？", session_id="rag"), service=rag, get_report=None)
    assert second["text"] in rag_model.last_messages[0].content
    assert "参考资料" in rag_model.last_messages[0].content
    rag_model._content = payload()
    await runtime.execute(ChatRequest(query="文献中氮素淋失的主要影响因素", session_id="mechanism"), service=rag, get_report=None)
    assert second["text"] in rag_model.last_messages[0].content
    assert "supporting_quote" in rag_model.last_messages[0].content
    assert active_communication.get() is None
    store.close()


@pytest.mark.asyncio
async def test_arbitrary_candidate_is_frozen_and_does_not_activate_or_mutate_history():
    runtime = AgentRuntime()
    trials = ExplanationTrials(runtime)
    user = Principal(tester_id="dev", role="developer")
    original = runtime.runs.prompts.active()
    baseline = next(item for item in trials.list_prompts(user) if item["label"] == "原版解释 v1")
    class Recording(FakeLLM):
        def __init__(self):
            super().__init__(); self.calls = []
        async def chat(self, messages, **kwargs):
            self.calls.append(messages)
            response = await super().chat(messages, **kwargs)
            return response.model_copy(update={"content": "这是直接生成的解释。"})
    model = Recording()
    body = TrialInput(submission_id="custom", query="这个案例如何解释？", material="C-0000000000000000 是材料中的编号。",
        prompts=TrialPrompts(baseline=TrialPrompt(label=baseline["label"], text=baseline["text"]),
                             candidate=TrialPrompt(label="新增 v3", text="请用两句话作答。")))
    receipt = trials.submit(body, user, llm=model)
    await trials.tasks[receipt["trial_id"]]
    result = trials.get(receipt["trial_id"], user)
    assert result["status"] == "completed" and len(model.calls) == 2
    assert model.calls[0][1].content == model.calls[1][1].content
    assert model.calls[1][0].content.endswith("请用两句话作答。")
    assert result["variants"]["candidate"]["answer"] == "这是直接生成的解释。"
    assert result["prompts"]["candidate"]["prompt_id"] in {item["prompt_id"] for item in runtime.runs.prompts.list()}
    runtime.runs.prompts.save("新增 v3", "另一个版本。", "dev")
    assert trials.get(receipt["trial_id"], user)["prompts"]["candidate"]["text"] == "请用两句话作答。"
    assert runtime.runs.prompts.active() == original
    changed = body.model_copy(update={"prompts": TrialPrompts(baseline=body.prompts.baseline, candidate=TrialPrompt(label="v4", text="改变了规则。"))})
    with pytest.raises(HTTPException) as conflict:
        trials.submit(changed, user, llm=model)
    assert conflict.value.status_code == 409
    await trials.shutdown()
    runtime.runs.close()
