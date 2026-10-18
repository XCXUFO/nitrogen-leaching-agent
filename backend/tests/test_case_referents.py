"""Qualified comparison follow-ups bind only to previously displayed cases."""
import json
from types import SimpleNamespace

import pytest

from src.agent.contracts import TaskState
from src.agent.runtime import AgentRuntime
from src.agent.understanding import understand
from src.api.chat_schema import ChatRequest
from src.storage.case_library import CaseInput, CaseStore
from tests.test_case_library import FakeLLM


TITLES = [
    "山西清徐示范区高粱试验种植记录",
    "天津武清示范区设施黄瓜水肥记录",
    "黑龙江肇东示范区玉米水肥记录",
    "山西清徐示范区玉米水肥记录",
    "天津武清示范区设施番茄水肥记录",
    "山东庆云示范区冬小麦—夏玉米轮作水肥记录",
]


def displayed_state():
    ids = [f"C-{index:016X}" for index in range(len(TITLES))]
    return TaskState(conversation_id="cases", current_case_ids=ids, material_anchors=[
        {"source_type": "case", "source_id": case_id, "title": title, "source_run_id": "previous"}
        for case_id, title in zip(ids, TITLES)
    ])


def parse(query, state, **kwargs):
    return understand(ChatRequest(query=query, **kwargs), state, SimpleNamespace(run_id="run", turn_id="turn"))


@pytest.mark.parametrize("query,indices", [
    ("山西的这两个案例的区别是什么，比对一下？", [0, 3]),
    ("请比较山西的这两个案例的追肥有什么区别？", [0, 3]),
    ("这两个山西案例有什么区别？", [0, 3]),
    ("天津的这两个案例有什么区别？", [1, 4]),
    ("高粱和番茄这两个案例有什么区别？", [0, 4]),
])
def test_pair_qualifiers_resolve_without_taxonomy_and_preserve_display_order(query, indices):
    state = displayed_state()
    parsed = parse(query, state)
    assert parsed["resolved_case_ids"] == [state.current_case_ids[index] for index in indices]
    assert parsed["unresolved"] == []
    assert query in parsed["resolved_query"]
    for index in indices:
        assert TITLES[index] in parsed["resolved_query"]
    assert parsed["anchors"] == state.material_anchors


@pytest.mark.parametrize("query", [
    "这两个案例有什么区别？",
    "玉米的这两个案例有什么区别？",  # Three displayed maize cases.
    "黄瓜的这两个案例有什么区别？",  # Only one displayed cucumber case.
    "湖北的这两个案例有什么区别？",  # No displayed Hubei cases.
])
def test_uncertain_pairs_still_clarify(query):
    parsed = parse(query, displayed_state())
    assert parsed["resolved_case_ids"] == []
    assert parsed["unresolved"][0]["field"] == "comparison_objects"


def test_non_case_anchors_and_out_of_scope_anchors_cannot_complete_a_pair():
    state = displayed_state()
    state.current_case_ids = state.current_case_ids[:3]
    state.material_anchors += [{"source_type": "literature", "source_id": "paper", "title": "山西研究"}]
    parsed = parse("山西的这两个案例有什么区别？", state)
    assert parsed["resolved_case_ids"] == [] and parsed["unresolved"]


@pytest.mark.parametrize("inline", [True, False])
def test_explicit_ids_override_ambiguous_previous_scope(inline):
    state = displayed_state()
    ids = [state.current_case_ids[0], state.current_case_ids[3]]
    query = "比较这两个案例" + ("、".join(ids) if inline else "")
    assert parse(query, state, case_ids=[] if inline else ids)["unresolved"] == []
    assert parse(query, TaskState(conversation_id="empty"), case_ids=[] if inline else ids)["unresolved"] == []


def test_topic_switch_does_not_reuse_case_scope():
    parsed = parse("另外，这两个案例有什么区别？", displayed_state())
    assert parsed["resolved_case_ids"] == [] and parsed["anchors"] == []


@pytest.mark.asyncio
async def test_six_case_followup_passes_only_resolved_pair_and_reloads_current_content(tmp_path):
    store = CaseStore(str(tmp_path / "cases.sqlite3"))
    runtime = AgentRuntime()
    # Synthetic bodies test routing and freshness, not agricultural conclusions.
    items = [store.create(CaseInput(title=title, body=f"合成测试记录{index}，未记载效果。", enabled=True), "test")
             for index, title in enumerate(TITLES)]
    ids = [item["id"] for item in items]
    selected = [ids[0], ids[3]]

    async def ask(query, model, **kwargs):
        return await runtime.execute(ChatRequest(query=query, session_id="cases", **kwargs),
                                     service=None, get_report=None, case_store=store, llm=model)

    try:
        first = await ask("现在有别的案例吗", FakeLLM(ids))
        # A further Shanxi record in the library was never displayed.
        hidden = store.create(CaseInput(title="山西其他示范区高粱案例", body="未展示记录。", enabled=True), "test")
        store.change(ids[0], 1, {"body": "最新合成记录，补充了施肥条件。"}, "test")
        query = "山西的这两个案例的区别是什么，比对一下？"
        model = FakeLLM(selected, answer="两份记录的作物和施肥安排不同。")
        result = await ask(query, model)
        payload = json.loads(model.messages[-1].content)
        assert result.outcome == "complete" and result.case_route == ["case_explanation"]
        assert [item["id"] for item in payload["available_cases"]] == selected
        assert payload["available_cases"][0]["body"] == "最新合成记录，补充了施肥条件。"
        assert all(case_id not in payload["question"] for case_id in ids)
        assert TITLES[0] in payload["question"] and TITLES[3] in payload["question"]
        assert [item.id for item in result.case_references] == selected
        assert runtime.states.entries["cases"].current_case_ids == selected
        trace = runtime.runs.get(result.run_id)
        assert trace.understanding["raw_query"] == query
        assert trace.understanding["resolved_case_ids"] == selected
        assert {item["source_run_id"] for item in trace.understanding["anchors"]} == {first.run_id}
        assert trace.retrieval[0]["scope"] == "explicit"
        assert [item["id"] for item in trace.retrieval[0]["candidates"]] == selected
        assert hidden["id"] not in [item["id"] for item in trace.retrieval[0]["candidates"]]

        repeated = await ask("这两者的施肥安排有什么区别？", FakeLLM(selected))
        assert [item.id for item in repeated.case_references] == selected
        store.change(ids[3], 1, {"enabled": False}, "test")
        closed_model = FakeLLM(error=True)
        closed = await ask("山西的这两个案例再比较一下", closed_model)
        assert closed.case_match == "unavailable" and closed.case_references == []
        assert closed_model.messages == []
    finally:
        runtime.runs.close()
        store.close()
