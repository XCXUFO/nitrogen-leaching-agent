"""PRD examples exercise the real interpreter, selector and orchestrator."""
import json

import pytest

from src.agent.contracts import TaskState
from src.agent.runtime import AgentRuntime
from src.agent.understanding import assess_conditions, map_tags, understand
from src.agent.case_retrieval import select_materials
from src.api.chat_schema import ChatRequest
from src.storage.case_library import CaseInput, CaseStore
from tests.test_case_library import FakeLLM
from tests.test_chat_runs import Service


def context(query, state=None):
    from types import SimpleNamespace
    return understand(ChatRequest(query=query), state or TaskState(conversation_id="test"), SimpleNamespace(run_id="run", turn_id="turn"))


def taxonomy():
    return {"dimensions": [{"id": "crop", "enabled": True}], "tags": [
        {"id": "tomato", "name": "番茄", "dimension_id": "crop", "parent_id": None, "path": "作物 / 番茄", "enabled": True}]}


def test_negation_corrections_switch_and_controlled_aliases():
    original = context("找没有灌溉条件的玉米案例，不要扩展到其他地区")
    assert original["resolved_query"] == original["raw_query"]
    assert "没有灌溉" in original["queries"][0]
    state = TaskState(conversation_id="test", understanding_context=original)
    corrected = context("刚才说错了，是西红柿", state)
    assert [item["value"] for item in corrected["conditions"] if item["category"] == "crop"] == ["番茄"]
    mapped = map_tags(corrected, taxonomy())
    assert mapped["mappings"][0]["candidates"][0]["id"] == "tomato"
    switched = context("另外，折氮量是什么意思？", state)
    assert switched["conditions"] == [] and switched["context_relation"] == "topic_switch"
    assert "玉米" not in switched["resolved_query"]


@pytest.mark.asyncio
@pytest.mark.parametrize("followup", ["它有哪些迁移过程？", "它的迁移过程呢？", "那侧向渗漏呢？", "那侧向渗漏贡献多少？"])
async def test_real_knowledge_followup_keeps_subject_and_topic_switch_drops_history(followup):
    from src.agent.chat_service import ChatService
    from tests.test_chat_service import FakeLLMClient, FakeRetriever

    runtime = AgentRuntime()
    retriever = FakeRetriever([])
    service = ChatService(retriever, FakeLLMClient(), top_k=5, max_context_chars=3000, temperature=0)
    history = [{"role": "user", "content": "硝态氮淋失是什么？"},
               {"role": "assistant", "content": "这是前一轮回答。"}]
    first = await runtime.execute(ChatRequest(query=history[0]["content"], session_id="subject"), service=service, get_report=None)
    assert "nitrate" in retriever.calls[-1][0]
    result = await runtime.execute(ChatRequest(query=followup, history=history, session_id="subject"), service=service, get_report=None)
    assert "硝态氮淋失" in retriever.calls[-1][0]
    assert followup in retriever.calls[-1][0]
    assert runtime.runs.get(result.run_id).understanding["context_relation"] == "followup"
    switched_query = "另外，折氮量是什么意思？"
    await runtime.execute(ChatRequest(query=switched_query, history=history, session_id="subject"), service=service, get_report=None)
    switched_history = history + [{"role": "user", "content": switched_query}, {"role": "assistant", "content": "这是新话题的回答。"}]
    await runtime.execute(ChatRequest(query="它怎么算？", history=switched_history, session_id="subject"), service=service, get_report=None)
    assert "折氮量" in retriever.calls[-1][0] and "硝态氮" not in retriever.calls[-1][0]
    for query in ("另外，水稻需水规律是什么？", "水稻需水规律是什么？"):
        await runtime.execute(ChatRequest(query=query, history=history, session_id="subject"), service=service, get_report=None)
        assert "硝态氮" not in retriever.calls[-1][0]
        assert "rice" in retriever.calls[-1][0]
    assert runtime.runs.get(first.run_id).understanding["context_relation"] == "independent"
    runtime.runs.close()


def test_mapping_ambiguity_inactive_ancestors_and_condition_three_states():
    parsed = context("只找番茄案例")
    duplicate = taxonomy()
    duplicate["tags"].append(duplicate["tags"][0] | {"id": "other"})
    mapped = map_tags(parsed, duplicate)
    assert mapped["mappings"][0]["status"] == "ambiguous"
    mapping = map_tags(parsed, taxonomy())
    for text, ids, expected, eligible in (("本试验采用番茄，分次施肥。", [], "satisfied", True),
                                          ("本试验采用玉米。", ["tomato"], "not_satisfied", False),
                                          ("仅记载施肥步骤，作物未知。", [], "unknown", False)):
        checks, actual = assess_conditions(text, ids, parsed, mapping)
        assert checks[0]["state"] == expected and actual == eligible
        if ids: assert checks[0]["conflict"]
    explicit = context("只查带番茄标签的案例")
    _, eligible = assess_conditions("本试验采用番茄。", [], explicit, map_tags(explicit, taxonomy()))
    assert not eligible


@pytest.mark.asyncio
async def test_actual_case_anchors_ambiguity_and_stable_comparison(tmp_path):
    store = CaseStore(str(tmp_path / "cases.sqlite3"))
    items = [store.create(CaseInput(title=f"玉米案例{i}", body=f"玉米分组{i}，施肥分两次。", enabled=True), "operator") for i in range(3)]
    runtime = AgentRuntime()
    async def ask(query, selected):
        return await runtime.execute(ChatRequest(query=query, session_id="session"), service=None, get_report=None,
                                     case_store=store, llm=FakeLLM(selected))
    first = await ask("找三个玉米案例", [item["id"] for item in items])
    ambiguous = await ask("这两个追肥有什么区别？", [])
    assert ambiguous.outcome == "clarification" and "哪两个" in ambiguous.answer
    trace = runtime.runs.get(ambiguous.run_id)
    assert {item["source_run_id"] for item in trace.understanding["anchors"]} == {first.run_id}
    runtime.runs.close(); store.close()


@pytest.mark.parametrize("position", [0, 30])
def test_all_candidates_reachable_before_budget_including_late_relevant_record(tmp_path, position):
    store = CaseStore(str(tmp_path / "cases.sqlite3"))
    ids = []
    for index in range(31):
        title = "目标番茄滴灌案例" if index == position else f"水稻案例{index}"
        ids.append(store.create(CaseInput(title=title, body=("番茄滴灌，保留完整条件。" if index == position else f"水稻分组{index}的完整案例。"), enabled=True), "operator")["id"])
    parsed = context("找番茄滴灌案例")
    materials, selection = select_materials(store, parsed["resolved_query"], understanding=parsed)
    assert selection["pool_size"] == 31 and [item["id"] for item in materials] == [ids[position]]
    assert all(item["checks"][0]["state"] == "not_satisfied" for item in selection["candidates"] if item["id"] != ids[position])
    store.close()


def test_char_budget_atomic_comparison_and_oversized_material(tmp_path):
    store = CaseStore(str(tmp_path / "cases.sqlite3"))
    big = store.create(CaseInput(title="大表", body="表头 kg/ha，三次合计\n" + "完整数据"*6500, enabled=True), "operator")
    small = store.create(CaseInput(title="小表", body="表头、单位和分组完整。", enabled=True), "operator")
    materials, selection = select_materials(store, "大表 小表")
    assert [item["id"] for item in materials] == [small["id"]]
    assert next(item for item in selection["candidates"] if item["id"] == big["id"])["reason"] == "material_budget"
    assert select_materials(store, "解释大表", ids=[big["id"]])[1]["status"] == "budget_exceeded"
    assert select_materials(store, "比较", ids=[small["id"], big["id"]])[0] == []
    store.close()


@pytest.mark.asyncio
async def test_full_empty_partial_starred_coverage_and_matching_failure():
    runtime = AgentRuntime()
    service = Service()
    questions = [{"question_id": "qa", "question": "什么是折氮量？", "answer": "折氮量是换算成氮元素的量。", "revision": 1}]
    async def ask(query, provider=lambda: questions):
        return await runtime.execute(ChatRequest(query=query), service=service, get_report=None, starred_provider=provider)
    first = await ask("折纯氮是什么意思？")
    assert "换算成氮元素" in first.answer and service.calls == 0
    assert first.evidence[0].source_type == "starred"
    old = runtime.runs.get(first.run_id).starred_match
    questions[0]["answer"] = "新的人工内容"
    newer = await ask("什么是折氮量？")
    assert "新的人工内容" in newer.answer and runtime.runs.get(first.run_id).starred_match == old
    partial = await ask("折氮量是什么意思，同时土壤中的氮有哪些迁移过程？")
    assert "新的人工内容" in partial.answer and "固定回答" in partial.answer and service.calls == 1
    trace = runtime.runs.get(partial.run_id)
    assert trace.starred_match["status"] == "partial" and len(trace.starred_match["remaining_subtask_ids"]) == 1
    questions[0]["answer"] = "  "
    empty = await ask("折氮量是什么意思？")
    assert runtime.runs.get(empty.run_id).starred_match["status"] == "empty_answer" and service.calls == 2
    def broken(): raise RuntimeError("offline")
    failure = await ask("折氮量是什么意思？", broken)
    assert runtime.runs.get(failure.run_id).starred_match["status"] == "failed" and service.calls == 3
    runtime.runs.close()


@pytest.mark.asyncio
async def test_case_closed_while_model_is_working_never_becomes_new_evidence(tmp_path):
    store = CaseStore(str(tmp_path / "cases.sqlite3"))
    item = store.create(CaseInput(title="番茄案例", body="番茄分次施肥。", enabled=True), "operator")
    class ClosingModel(FakeLLM):
        async def chat(self, *args, **kwargs):
            result = await super().chat(*args, **kwargs)
            store.change(item["id"], 1, {"enabled": False}, "editor")
            return result
    from src.agent.case_skills import CaseSkillInput, answer_cases
    response = await answer_cases(CaseSkillInput(query="番茄案例"), mode="reference", store=store, llm=ClosingModel([item["id"]]))
    assert response.case_references == [] and response.outcome == "clarification"
    store.close()
