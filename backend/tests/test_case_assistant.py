"""Case orchestration contracts use synthetic records, never agricultural gold answers."""
import json

import pytest
from pydantic import ValidationError

from src.agent.runtime import AgentRuntime
from src.agent.skills import build_registry
from src.api.chat_schema import ChatRequest
from src.agent.contracts import RunTrace, StateSnapshot
from src.storage.case_library import CaseStore, CaseInput
from tests.test_case_library import FakeLLM


@pytest.fixture
def setup(tmp_path):
    store = CaseStore(str(tmp_path / 'cases.sqlite3'))
    runtime = AgentRuntime()
    records = [store.create(CaseInput(title=f'{name}测试记录', body=f'{name}措施为分次施用，未提供产量和效果数据。', enabled=True), 'test') for name in ('甲地', '乙地', '隐藏对象')]
    yield runtime, store, records
    runtime.runs.close()


async def ask(setup, query, model, session='case-test', **kwargs):
    runtime, store, _ = setup
    return await runtime.execute(ChatRequest(query=query, session_id=session, **kwargs), service=None, get_report=None, case_store=store, llm=model)


@pytest.mark.asyncio
async def test_keep_trajectory_only_displayed_cases_reloaded_and_modes_recorded(setup):
    runtime, store, items = setup
    shown = items[0]['id']
    model = FakeLLM([shown], answer='甲地测试记录记载了做法，未提供效果数据。')
    first = await ask(setup, '有哪些水氮管理相关的案例与措施可以参考？', model)
    trace = runtime.runs.get(first.run_id)
    assert len(trace.case_context['retrieved_case_ids']) == 3
    assert trace.case_context['displayed_case_ids'] == [shown]
    history = [{'role': 'user', 'content': '有哪些水氮管理相关的案例与措施可以参考？'}, {'role': 'assistant', 'content': first.answer}]
    store.change(shown, 1, {'body': '最新合成正文，仍未提供产量和对照。'}, 'editor')
    second = await ask(setup, '上面案例中的关键措施是什么，为什么这样做？', model, history=history)
    payload = json.loads(model.messages[-1].content)
    assert [r['id'] for r in payload['available_cases']] == [shown]
    assert payload['available_cases'][0]['body'].startswith('最新合成正文')
    assert second.case_mode == 'explain'
    history += [{'role': 'user', 'content': '上面案例中的关键措施是什么，为什么这样做？'}, {'role': 'assistant', 'content': second.answer}]
    third = await ask(setup, '案例中的效果有哪些证据，还不能得出哪些结论？', model, history=history)
    payload = json.loads(model.messages[-1].content)
    assert [r['id'] for r in payload['available_cases']] == [shown]
    assert third.case_mode == 'evidence'
    assert payload['recent_dialogue'] == history
    assert payload['recent_dialogue'][-1]['content'] == second.answer
    assert '效果证据' in model.messages[0].content
    assert len({first.run_id, second.run_id, third.run_id}) == 3
    for response, mode in [(first, 'search'), (second, 'explain'), (third, 'evidence')]:
        trace = runtime.runs.get(response.run_id)
        assert trace.decision.skills == ['case_assistant']
        assert [t.skill for t in trace.tool_calls] == ['case_assistant']
        assert trace.tool_calls[0].case_mode == mode
        assert response.case_route == ['case_assistant']
        assert trace.skill_config['task_prompt_usage'][0]['scope'] == 'case_assistant'


@pytest.mark.asyncio
async def test_narrowed_display_cannot_resurrect_older_candidates(setup):
    runtime, store, items = setup
    ids = [x['id'] for x in items[:2]]
    await ask(setup, '找两个案例并比较措施差异', FakeLLM(ids))
    model = FakeLLM([ids[0]])
    result = await ask(setup, '详细解释第一个', model)
    assert [x['id'] for x in json.loads(model.messages[-1].content)['available_cases']] == [ids[0]]
    never = FakeLLM(error=True)
    result = await ask(setup, '这两者的区别呢', never)
    assert result.outcome == 'clarification' and not never.messages
    assert runtime.states.entries['case-test'].current_case_ids == [ids[0]]


@pytest.mark.asyncio
async def test_pasted_table_and_comparison_need_no_case_store_and_followup_keeps_text():
    runtime = AgentRuntime()
    table = '比较以下材料：\n|对象|用量口径|效果|\n|甲|三次合计|未填写|\n|乙|单次|未填写|'
    model = FakeLLM(answer='两份材料的用量口径不同，空白不是零；没有效果证据。')
    first = await runtime.execute(ChatRequest(query=table, session_id='pasted'), service=None, get_report=None, case_store=None, llm=model)
    assert first.case_mode == 'compare'
    payload = json.loads(model.messages[-1].content)
    assert payload['available_cases'] == [] and payload['source_type'] == 'user_text'
    second = await runtime.execute(ChatRequest(query='这个材料还不能得出哪些结论？', session_id='pasted'), service=None, get_report=None, case_store=None, llm=model)
    assert second.case_mode == 'evidence'
    assert table in json.loads(model.messages[-1].content)['previous_user_text']
    assert not second.case_references
    runtime.runs.close()


@pytest.mark.asyncio
async def test_closed_selected_case_stays_selected_and_does_not_fall_back_to_all(setup):
    runtime, store, items = setup
    selected = items[0]['id']
    store.change(selected, 1, {'enabled': False}, 'editor')
    never = FakeLLM(error=True)
    result = await ask(setup, '解释指定案例', never, case_ids=[selected])
    assert result.case_match == 'unavailable'
    result = await ask(setup, '这个案例的措施是什么？', never)
    assert result.case_match == 'unavailable' and not never.messages
    assert runtime.runs.get(result.run_id).case_context['requested_case_ids'] == [selected]


@pytest.mark.asyncio
async def test_session_isolation_and_new_object_selection(setup):
    _, _, items = setup
    first, second = items[0]['id'], items[1]['id']
    await ask(setup, '找案例', FakeLLM([first]), session='one')
    never = FakeLLM(error=True)
    result = await ask(setup, '上面案例的效果证据呢？', never, session='two')
    assert result.outcome == 'clarification' and not never.messages
    model = FakeLLM([second])
    result = await ask(setup, '解释这个案例', model, session='one', case_ids=[second])
    assert [r.id for r in result.case_references] == [second]
    assert [r['id'] for r in json.loads(model.messages[-1].content)['available_cases']] == [second]


@pytest.mark.asyncio
async def test_legacy_registry_and_http_entries_record_canonical_skill_without_rewriting_history(setup):
    runtime, store, items = setup
    selected = items[0]['id']
    model = FakeLLM([selected])
    registry = build_registry(None, None, case_store=store, llm=model)
    assert 'case_reference' not in {s['name'] for s in registry.describe()}
    for old, mode in [('case_reference', 'search'), ('case_explanation', 'explain')]:
        result = await registry.invoke(old, {'query': '测试材料', 'case_ids': [selected]})
        assert result.case_route == ['case_assistant'] and result.case_mode == mode
    old_trace = RunTrace(run_id='original', input='旧问题', conversation_ref='old', started_at='2026-10-19',
        state_before=StateSnapshot(), config_version='historical', tool_calls=[{'skill': 'case_reference', 'status': 'ok', 'latency_ms': 0}])
    runtime.runs.append(old_trace)
    result = await ask(setup, '解释材料', model, case_skill='explain', case_ids=[selected])
    assert runtime.runs.get(result.run_id).tool_calls[0].skill == 'case_assistant'
    assert runtime.runs.get('original').model_dump() == old_trace.model_dump()
    with pytest.raises(ValidationError):
        ChatRequest(query='test', case_skill='explain', case_mode='evidence')


@pytest.mark.asyncio
async def test_explicit_mode_changes_keep_displayed_subject_and_missing_material_never_calls_model(setup):
    runtime, _, items = setup
    selected = items[0]['id']
    model = FakeLLM([selected])
    first = await ask(setup, '有哪些案例？', model, case_mode='search')
    second = await ask(setup, '案例中的效果证据有哪些？', model, case_mode='evidence')
    assert second.case_mode == 'evidence'
    assert [r['id'] for r in json.loads(model.messages[-1].content)['available_cases']] == [selected]
    never = FakeLLM(error=True)
    missing = await ask(setup, '解释这份材料', never, session='missing-material')
    assert missing.outcome == 'clarification' and not never.messages


@pytest.mark.asyncio
async def test_plain_reason_followup_after_pasted_table_keeps_source():
    runtime = AgentRuntime()
    model = FakeLLM(answer='这是一般理由，原材料没有说明设计依据。')
    original = '解释以下表格：\n|阶段|安排|\n|甲|分次施用|'
    await runtime.execute(ChatRequest(query=original, session_id='text'), service=None, get_report=None, llm=model)
    result = await runtime.execute(ChatRequest(query='为什么这样做？', session_id='text'), service=None, get_report=None, llm=model)
    assert result.case_mode == 'explain'
    assert original in json.loads(model.messages[-1].content)['previous_user_text']
    runtime.runs.close()


@pytest.mark.asyncio
async def test_legacy_reference_searches_when_the_query_requests_an_explanation(setup):
    runtime, store, items = setup
    selected = items[0]['id']
    model = FakeLLM([selected])
    result = await ask(setup, '解释水氮管理措施', model, case_skill='reference')
    assert result.case_match == 'matched'
    assert runtime.runs.get(result.run_id).retrieval
    assert selected in {case['id'] for case in json.loads(model.messages[-1].content)['available_cases']}

    registry = build_registry(None, None, case_store=store, llm=model)
    result = await registry.invoke('case_reference', {'query': '解释水氮管理措施'})
    assert result.case_match == 'matched'

    await ask(setup, '解释这段文字：这个地块分次施肥。', FakeLLM(), session='from-text')
    result = await ask(setup, '为什么这样安排？', model, session='from-text', case_skill='reference')
    assert result.case_match == 'matched'
    assert runtime.runs.get(result.run_id).retrieval
