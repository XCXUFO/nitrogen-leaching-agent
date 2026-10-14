"""Case lifecycle and Agent boundaries; synthetic fixtures are not real evidence."""
import json

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from src.agent.case_skills import CaseSkillInput, answer_cases
from src.agent.routing import decide
from src.agent.runtime import AgentRuntime
from src.api import case_library
from src.api.chat_schema import ChatRequest
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal
from src.llm.base import ChatResult, ChatUsage
from src.storage.case_library import CaseInput, CaseStore


@pytest.fixture
def store(tmp_path):
    value = CaseStore(str(tmp_path / "cases.db"))
    yield value
    value.close()


class FakeLLM:
    def __init__(self, ids=(), answer="示例解释", error=False):
        self.ids, self.answer, self.error = list(ids), answer, error
        self.messages = []

    async def chat(self, messages, **kwargs):
        self.messages = messages
        if self.error:
            raise RuntimeError("upstream failed")
        return ChatResult(content=json.dumps({"answer": self.answer, "used_case_ids": self.ids}),
                          model="fixture", usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


class DraftLLM(FakeLLM):
    async def chat_json(self, messages, **kwargs):
        result = await self.chat(messages, **kwargs)
        return result.model_copy(update={"content": json.dumps({"draft": self.answer})})


def seed(store, **kwargs):
    return store.create(CaseInput(title="玉米案例", body="采取分次施肥。未记载结果。", **kwargs), "operator")


def test_minimum_fields_and_search(store):
    item = seed(store)
    assert not item["enabled"] and item["explanation"] == item["source"] == ""
    assert store.available() == []
    assert store.list("玉米")["total"] == 1
    assert store.list("分次施肥")["total"] == 0  # title-only management search
    assert store.list("%")["total"] == 0  # literal keyword
    assert store.list(availability="disabled")["total"] == 1


def test_revision_and_visibility_across_connections(store):
    item = seed(store, enabled=True)
    second = CaseStore(store.db.execute("PRAGMA database_list").fetchone()[2])
    try:
        assert second.available()[0]["id"] == item["id"]
        updated = store.change(item["id"], 1, {"enabled": False}, "editor")
        assert updated["created_by"] == "operator" and updated["updated_by"] == "editor"
        assert second.available() == []
        with pytest.raises(HTTPException) as exc:
            second.change(item["id"], 1, {"body": "stale"}, "other")
        assert exc.value.status_code == 409
        second.change(item["id"], 2, {"deleted": True, "enabled": False}, "editor")
        assert store.list()["total"] == 0 and store.available() == []
        assert store.db.execute("SELECT deleted FROM reference_cases").fetchone()[0] == 1
        with pytest.raises(HTTPException):
            store.get(item["id"])
    finally:
        second.close()


def test_capacity_is_explicit_and_can_be_narrowed(store):
    item = seed(store, enabled=True)
    seed(store, enabled=True, explanation="长" * 25000)
    with pytest.raises(HTTPException) as exc:
        store.available()
    assert exc.value.detail["code"] == "case_capacity"
    assert store.available([item["id"]])[0]["id"] == item["id"]


@pytest.mark.asyncio
async def test_reference_uses_saved_explanation_and_no_fabricated_source(store):
    item = seed(store, enabled=True, explanation="人工说明")
    llm = FakeLLM([item["id"]])
    result = await answer_cases(CaseSkillInput(query="有没有类似案例？"), mode="reference", store=store, llm=llm)
    assert item["id"] in result.answer
    assert result.case_references[0].source == ""
    assert "人工说明" in llm.messages[-1].content
    assert "正文是事实依据" in llm.messages[0].content


@pytest.mark.asyncio
async def test_no_match_does_not_return_invented_case(store):
    seed(store, enabled=True)
    result = await answer_cases(CaseSkillInput(query="水稻案例"), mode="reference", store=store, llm=FakeLLM(answer="模型乱写案例"))
    assert "没有找到" in result.answer and "乱写" not in result.answer
    assert result.case_references == []


@pytest.mark.asyncio
async def test_unknown_model_citation_is_rejected(store):
    seed(store, enabled=True)
    with pytest.raises(HTTPException) as exc:
        await answer_cases(CaseSkillInput(query="案例"), mode="reference", store=store, llm=FakeLLM(["C-0000000000000000"]))
    assert exc.value.status_code == 502


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["解释这段文字：分次施肥", "请通俗解释分次施肥措施的含义"])
async def test_pasted_text_explanation_needs_no_store(query):
    llm = FakeLLM(answer="分次施肥是把肥料分几次施入。")
    result = await answer_cases(CaseSkillInput(query=query), mode="explain", store=None, llm=llm)
    assert "分几次" in result.answer and not result.case_references
    assert json.loads(llm.messages[-1].content)["available_cases"] == []


@pytest.mark.asyncio
async def test_chat_runtime_and_closed_case_followup(store):
    item = seed(store, enabled=True)
    llm = FakeLLM([item["id"]])
    runtime = AgentRuntime()
    async def report(_):
        raise AssertionError("should not analyze files")
    try:
        first = await runtime.execute(ChatRequest(query="有没有玉米类似案例？", session_id="cases"),
                                      service=None, get_report=report, case_store=store, llm=llm)
        assert first.case_references[0].id == item["id"]
        assert first.evidence[0].source_type == "case"
        store.change(item["id"], 1, {"enabled": False}, "editor")
        second = await runtime.execute(ChatRequest(query="解释刚才这个案例", session_id="cases",
                                                    history=[{"role": "assistant", "content": first.answer}]),
                                       service=None, get_report=report, case_store=store, llm=FakeLLM(error=True))
        assert "不可调用" in second.answer and not second.case_references
    finally:
        runtime.runs.close()


@pytest.mark.parametrize("query,skill", [("有没有类似案例？", "case_reference"), ("有没有可以参考的措施？", "case_reference"), ("别人遇到这种情况是怎么做的？", "case_reference"), ("解释以下专业文本：分次施肥", "case_explanation")])
def test_intents(query, skill):
    assert decide(query, has_file=False).skills == [skill]


@pytest.mark.asyncio
async def test_http_validation_draft_and_permissions(store):
    app = FastAPI()
    app.include_router(case_library.router, prefix="/api")
    app.state.case_library = store
    app.state.llm = DraftLLM(answer="draft")
    app.dependency_overrides[current_user] = lambda: Principal(tester_id="reviewer", role="reviewer")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        for body in ({"title": "  ", "body": "正文"}, {"title": "标题", "body": " "}):
            assert (await client.post("/api/case-library", json=body)).status_code == 422
        created = await client.post("/api/case-library", json={"title": "案例", "body": "原文", "enabled": True})
        assert created.status_code == 201
        item = created.json()
        assert item["created_by"] == "reviewer"
        generated = await client.post("/api/case-library/explanation-draft", json={"body": "未保存的原文", "supplementary": "补充"})
        assert generated.status_code == 200
        assert generated.json()["draft"] == "draft"
        assert "未保存的原文" in app.state.llm.messages[-1].content
        assert store.get(item["id"])["explanation"] == ""
        app.state.llm = FakeLLM(error=True)
        assert (await client.post("/api/case-library/explanation-draft", json={"body": "原文"})).status_code == 502
        assert store.get(item["id"])["body"] == "原文"
        path = "/api/case-library/" + item["id"]
        update = {"title": "案例", "body": "正文", "explanation": "人工修改", "expected_revision": 1}
        assert (await client.put(path, json=update)).status_code == 200
        assert (await client.put(path, json=update)).status_code == 409
        assert (await client.request("DELETE", path, json={"expected_revision": 2})).status_code == 200
        assert (await client.get(path)).status_code == 404
        app.dependency_overrides.clear()
        assert (await client.get("/api/case-library")).status_code in (401, 404)


@pytest.mark.parametrize("query", ["解释C-ABCDEF1234567890的措施", "c-abcdef1234567890什么意思"])
def test_case_id_adjacent_to_chinese_and_case_insensitive(query):
    from src.agent.case_ids import case_ids_in
    assert case_ids_in(query) == ["C-ABCDEF1234567890"]
    assert decide(query, has_file=False).skills == ["case_explanation"]
    assert case_ids_in("C-ABCDEF12345678900") == []


def test_explicit_ids_are_validated_and_normalized():
    from pydantic import ValidationError
    assert ChatRequest(query="解释", case_ids=["c-abcdef1234567890"]).case_ids == ["C-ABCDEF1234567890"]
    with pytest.raises(ValidationError):
        ChatRequest(query="解释", case_ids=["not-an-id"])


@pytest.mark.asyncio
async def test_reference_preserves_specific_clarification(store):
    seed(store, enabled=True)
    class ClarifyingLLM(FakeLLM):
        async def chat(self, messages, **kwargs):
            result = await super().chat(messages, **kwargs)
            result.content = json.dumps({"answer": "请说明作物和灌溉方式。", "used_case_ids": [], "outcome": "clarification"})
            return result
    result = await answer_cases(CaseSkillInput(query="有没有参考措施？"), mode="reference", store=store, llm=ClarifyingLLM())
    assert result.answer == "请说明作物和灌溉方式。"
    assert result.outcome == result.route == "clarification"


@pytest.mark.asyncio
async def test_followups_keep_ids_without_client_history_and_honor_new_subject(store):
    first, second = seed(store, enabled=True), seed(store, enabled=True)
    runtime = AgentRuntime()
    async def report(_):
        raise AssertionError("unrelated file access")
    async def ask(query, ids=(), **kwargs):
        llm = FakeLLM(ids)
        result = await runtime.execute(ChatRequest(query=query, session_id="followup", **kwargs),
                                       service=None, get_report=report, case_store=store, llm=llm)
        return result, json.loads(llm.messages[-1].content) if llm.messages else None
    try:
        await ask("有没有玉米类似案例？", [first["id"]])
        # Explicit IDs in the question supersede both session state and old history.
        result, payload = await ask(f"再解释这个{second['id']}的措施", [second["id"]],
                                    history=[{"role": "assistant", "content": first["id"]}])
        assert [item["id"] for item in payload["available_cases"]] == [second["id"]]
        # The state holds the IDs even if the client history has been truncated.
        store.change(second["id"], 1, {"deleted": True, "enabled": False}, "editor")
        result, payload = await ask("再详细解释它的措施")
        assert "不可调用" in result.answer and payload is None
        # “其他” must not be read as “它”, turning reference into explanation.
        result, payload = await ask("有没有其他可以参考的案例？", [first["id"]])
        assert payload["task"] == "寻找相关案例及措施，按需解释"
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_pasted_text_followup_keeps_original_and_new_text_starts_fresh():
    runtime = AgentRuntime()
    async def report(_):
        raise AssertionError("unrelated file access")
    llm = FakeLLM()
    async def ask(query):
        await runtime.execute(ChatRequest(query=query, session_id="text"), service=None, get_report=report, llm=llm)
        return json.loads(llm.messages[-1].content)
    try:
        original = "解释这段文字：分次施肥是将总施肥量分几次施入。"
        await ask(original)
        payload = await ask("再详细解释一下它")
        assert payload["previous_user_text"] == original
        assert payload["available_cases"] == []
        payload = await ask("解释这段文字：这个指标表示水分含量。")
        assert payload["previous_user_text"] == ""
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_failed_case_call_does_not_change_subject(store):
    runtime = AgentRuntime()
    async def report(_):
        raise AssertionError("unrelated file access")
    item = seed(store, enabled=True)
    try:
        await runtime.execute(ChatRequest(query="有没有类似案例？", session_id="failure"), service=None,
                              get_report=report, case_store=store, llm=FakeLLM([item["id"]]))
        state = runtime.states.entries["failure"]
        before = state.model_dump()
        with pytest.raises(RuntimeError):
            await runtime.execute(ChatRequest(query="解释以下文字：新的段落", session_id="failure"), service=None,
                                  get_report=report, case_store=store, llm=FakeLLM(error=True))
        after = state.model_dump()
        for field in ("current_case_ids", "case_context_text", "last_tool"):
            assert before[field] == after[field]
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_real_http_chat_wiring_reads_only_open_cases(store):
    from src.api import chat
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    app.state.case_library = store
    item = seed(store, enabled=True, explanation="已保存的人工说明")
    llm = app.state.llm = FakeLLM([item["id"]])
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            first = await client.post("/api/chat", json={"query": "解释", "case_ids": [item["id"]]})
            assert first.status_code == 200
            assert first.json()["case_references"][0]["id"] == item["id"]
            assert "已保存的人工说明" in llm.messages[-1].content
            store.change(item["id"], 1, {"enabled": False}, "editor")
            app.state.llm = FakeLLM(error=True)
            second = await client.post("/api/chat", json={"query": "解释", "case_ids": [item["id"]]})
            assert second.status_code == 200 and "不可调用" in second.json()["answer"]
    finally:
        app.state.agent_runtime.runs.close()


@pytest.mark.asyncio
async def test_clarification_reply_continues_reference_skill(store):
    item = seed(store, enabled=True)
    runtime = AgentRuntime()
    class ClarifyingLLM(FakeLLM):
        async def chat(self, messages, **kwargs):
            result = await super().chat(messages, **kwargs)
            result.content = json.dumps({"answer": "请补充作物。", "used_case_ids": [], "outcome": "clarification"})
            return result
    async def report(_):
        raise AssertionError("unrelated file access")
    try:
        await runtime.execute(ChatRequest(query="有没有类似案例？", session_id="clarifying"), service=None,
                              get_report=report, case_store=store, llm=ClarifyingLLM())
        llm = ClarifyingLLM()
        await runtime.execute(ChatRequest(query="玉米", session_id="clarifying"), service=None,
                              get_report=report, case_store=store, llm=llm)
        payload = json.loads(llm.messages[-1].content)
        assert payload["task"] == "寻找相关案例及措施，按需解释"
        assert payload["previous_user_text"] == "有没有类似案例？"
        llm = FakeLLM([item["id"]])
        await runtime.execute(ChatRequest(query="滴灌", session_id="clarifying"), service=None,
                              get_report=report, case_store=store, llm=llm)
        payload = json.loads(llm.messages[-1].content)
        assert "玉米" in payload["previous_user_text"]
        assert payload["question"] == "滴灌"
        assert not runtime.states.entries["clarifying"].case_clarification_pending
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_many_ids_in_question_return_explicit_http_capacity_error(store):
    from src.api import chat
    app = FastAPI()
    app.include_router(chat.router, prefix="/api")
    app.state.case_library = store
    app.state.llm = FakeLLM(error=True)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            query = "解释" + "，".join(f"C-{i:016X}" for i in range(31))
            result = await client.post("/api/chat", json={"query": query})
            assert result.status_code == 413
            assert result.json()["detail"]["code"] == "case_capacity"
    finally:
        app.state.agent_runtime.runs.close()
