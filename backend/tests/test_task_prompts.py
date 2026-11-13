import asyncio
from pathlib import Path

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.agent.task_prompts import TaskPromptInput, active_task_prompts, active_task_usage
from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.storage.run_store import RunStore
from src.evaluation.handoff_retests import HandoffRetests, HandoffRetestInput, HandoffJudgment
from src.evaluation.handoff import import_package
from src.evaluation.contracts import Principal
from tests.test_prd_handoff import SOURCE
from tests.test_case_library import FakeLLM as CaseFakeLLM
from tests.test_chat_service import FakeRetriever, FakeLLMClient, _result
from src.agent.chat_service import ChatService

DEV = Principal(tester_id='dev', role='developer')


class FakeLLM(CaseFakeLLM):
    """Concept calls return prose; case calls retain their structured contract."""
    async def chat(self, messages, **kwargs):
        result = await super().chat(messages, **kwargs)
        if '【任务策略：concept_explanation】' in messages[0].content:
            return result.model_copy(update={'content': self.answer})
        return result


def task(scope='concept_explanation', text='先介绍用途，再引导。', **extra):
    return TaskPromptInput(scope=scope, label='candidate', text=text, **extra)


def test_versions_scope_activation_audit_and_examples(tmp_path):
    path = tmp_path / 'runs.sqlite3'
    store = RunStore(path)
    before = store.task_prompts.active()
    communication = store.prompts.active()
    example = {'source_case': 'reviewed-local', 'source_revision': 'v2', 'review_scope': '流程与表达已核对', 'confirmed': True, 'query': '术语如何解释？', 'answer': '先解释概念，再说明边界。'}
    saved = store.task_prompts.save(task(examples=[example]), 'dev')
    changed = store.task_prompts.save(task(text='先介绍再举例。'), 'dev')
    assert saved['prompt_id'] != changed['prompt_id']
    assert store.task_prompts.active() == before
    assert store.task_prompts.get(saved['prompt_id'])['examples'] == [example]
    with pytest.raises(HTTPException):
        store.task_prompts.activate('knowledge_search', saved['prompt_id'], 'dev')
    store.task_prompts.activate('concept_explanation', saved['prompt_id'], 'dev')
    assert store.task_prompts.active()['knowledge_search'] == before['knowledge_search']
    assert store.prompts.active() == communication
    assert store._connection.execute('SELECT COUNT(*) FROM task_prompt_activations').fetchone()[0] == 1
    store.close()
    reopened = RunStore(path)
    assert reopened.task_prompts.active()['concept_explanation']['prompt_id'] == saved['prompt_id']
    assert reopened.task_prompts.get(saved['prompt_id'])['text'] != changed['text']
    reopened.close()
    with pytest.raises(ValidationError):
        task(examples=[{**example, 'confirmed': False}])
    with pytest.raises(ValidationError):
        task(text='{{missing_evidence}}')


@pytest.mark.parametrize('query', ['WHCNS模型', '请介绍WHCNS这个模型', '氮素淋失', '硝化作用是什么意思', '解释下光合作用', '我是新手，模型有哪些工作应用场景？'])
@pytest.mark.asyncio
async def test_introductory_phrases_call_concept_with_real_task_layer(query):
    runtime = AgentRuntime()
    model = FakeLLMClient('这是入门用途说明。')
    result = await runtime.execute(ChatRequest(query=query), service=None, llm=model, get_report=None)
    trace = runtime.runs.get(result.run_id)
    assert [c.skill for c in trace.tool_calls] == ['concept_explanation']
    assert result.answer == '这是入门用途说明。'
    assert '面向用户的表达规则' in model.last_messages[0].content
    assert '每轮至多一个引导问题' in model.last_messages[0].content
    assert 'concept_explanation' in model.last_messages[0].content
    assert trace.skill_config['task_prompt_usage'][0]['scope'] == 'concept_explanation'
    runtime.runs.close()


@pytest.mark.asyncio
async def test_local_only_never_turns_into_unsourced_concept_and_history_is_kept():
    runtime = AgentRuntime()
    model = FakeLLM(answer='应当不会调用')
    history = [{'role': 'user', 'content': '后续只用本地材料'}, {'role': 'assistant', 'content': '好的'}]
    response = await runtime.execute(ChatRequest(query='解释下光合作用', history=history), service=None, llm=model, get_report=None)
    assert '本地资料服务当前不可用' in response.answer
    assert not model.messages
    retriever = FakeRetriever([])
    service = ChatService(retriever, FakeLLMClient(), top_k=5, max_context_chars=4000, temperature=0)
    response = await runtime.execute(ChatRequest(query='只用本地资料解释光合作用', history=history), service=service, llm=model, get_report=None)
    assert response.model == 'source-policy' and not response.citations
    runtime.runs.close()


@pytest.mark.asyncio
async def test_task_candidate_reaches_model_pinned_in_retest_and_unused_candidate_cannot_pass(tmp_path):
    source = tmp_path / 'source.sqlite3'
    import_package(SOURCE, source)
    runtime = AgentRuntime()
    engine = HandoffRetests(runtime, source)
    cid = 'handoff-2026-11-09-v1.0-FIX-02'
    original = runtime.runs.task_prompts.active()
    saved = runtime.runs.task_prompts.save(task(text='独立任务候选：先介绍，再引导。'), 'dev')
    model = FakeLLM(answer='模型用途说明。')
    async def execute(query, run_id, config):
        return await runtime.execute(query, service=None, get_report=None, llm=model, run_id=run_id, expression_config=config, run_context={'source': 'test', 'mode': 'auto'})
    body = HandoffRetestInput(submission_id='candidate', prompt_id=runtime.runs.prompts.active()['prompt_id'], task_prompt_ids={'concept_explanation': saved['prompt_id']})
    item = engine.submit(cid, body, DEV, execute)
    # Changing active while queued must not change accepted candidates.
    newer = runtime.runs.task_prompts.save(task(text='另一个生效版本'), 'dev')
    runtime.runs.task_prompts.activate('concept_explanation', newer['prompt_id'], 'dev')
    await engine.tasks[item['attempt_id']]
    result = engine.get(item['attempt_id'])
    assert result['status'] == 'completed' and result['unused_task_scopes'] == []
    assert saved['text'] in model.messages[0].content and newer['text'] not in model.messages[0].content
    assert result['steps'][0]['task_prompt_usage'][0]['prompt_id'] == saved['prompt_id']
    other = runtime.runs.task_prompts.save(task(scope='knowledge_search', text='专业候选'), 'dev')
    unused = engine.submit(cid, body.model_copy(update={'submission_id': 'unused', 'task_prompt_ids': {'knowledge_search': other['prompt_id']}}), DEV, execute)
    await engine.tasks[unused['attempt_id']]
    assert engine.get(unused['attempt_id'])['unused_task_scopes'] == ['knowledge_search']
    with pytest.raises(HTTPException):
        engine.judge(unused['attempt_id'], HandoffJudgment(conclusion='pass', basis='未调用不应通过'), DEV)
    assert runtime.runs.task_prompts.active()['knowledge_search'] == original['knowledge_search']
    assert active_task_prompts.get() is None and active_task_usage.get() is None
    runtime.runs.close()


def test_public_request_cannot_choose_private_candidates():
    for name in ('task_prompt_ids', 'expression_config', 'prompt_id', 'candidate_id'):
        with pytest.raises(ValidationError):
            ChatRequest.model_validate({'query': 'WHCNS模型', name: 'private'})


@pytest.mark.asyncio
async def test_novice_target_has_history_in_model_and_guidance_reflects_dependencies():
    import json
    record = json.loads((SOURCE / 'data/reviewed-cases.json').read_text())['records'][4]
    runtime = AgentRuntime()
    model = FakeLLM(answer='本助手可以解释文献和分析受支持的输出表；模拟模型用于研究过程，不预测就业。')
    response = await runtime.execute(ChatRequest(query=record['user_input'], history=record['seed_history']), service=None, get_report=None, llm=model)
    assert runtime.runs.get(response.run_id).history_count == 2
    assert record['seed_history'][0]['content'] in model.messages[1].content
    assert record['user_input'] in model.messages[1].content
    assert runtime.runs.get(response.run_id).decision.skills == ['concept_explanation']
    guide = await runtime.execute(ChatRequest(query='你能做什么'), service=None, get_report=None, llm=None)
    assert '查询本地文献' not in guide.answer and '检索已开放案例' not in guide.answer
    guide = await runtime.execute(ChatRequest(query='你能做什么'), service=None, get_report=None, llm=model)
    assert '解释农业、水氮及相关基础概念' in guide.answer
    runtime.runs.close()


@pytest.mark.asyncio
async def test_two_task_candidates_and_normal_concept_request_do_not_mix(tmp_path):
    source = tmp_path / 'source.sqlite3'
    import_package(SOURCE, source)
    runtime = AgentRuntime()
    engine = HandoffRetests(runtime, source)
    class Recording(FakeLLM):
        def __init__(self):
            super().__init__(answer='概念说明')
            self.systems = []
        async def chat(self, messages, **kwargs):
            await asyncio.sleep(0)
            self.systems.append(messages[0].content)
            return await super().chat(messages, **kwargs)
    model = Recording()
    current = runtime.runs.task_prompts.active()
    candidates = [runtime.runs.task_prompts.save(task(text=f'并发候选规则{i}'), 'dev') for i in range(2)]
    async def execute(query, run_id, config):
        return await runtime.execute(query, service=None, llm=model, get_report=None, expression_config=config, run_id=run_id)
    attempts = [engine.submit('handoff-2026-11-09-v1.0-FIX-02', HandoffRetestInput(
        submission_id=f'parallel{i}', prompt_id=runtime.runs.prompts.active()['prompt_id'], task_prompt_ids={'concept_explanation': candidate['prompt_id']}), DEV, execute)
        for i, candidate in enumerate(candidates)]
    await asyncio.gather(*(engine.tasks[a['attempt_id']] for a in attempts),
        runtime.execute(ChatRequest(query='WHCNS模型', session_id='normal'), service=None, get_report=None, llm=model))
    assert len(model.systems) == 3
    for candidate in candidates:
        assert sum(candidate['text'] in system for system in model.systems) == 1
    assert sum(current['concept_explanation']['text'] in system for system in model.systems) == 1
    assert runtime.runs.task_prompts.active() == current
    runtime.runs.close()


def test_latest_user_can_release_earlier_source_limit():
    from src.agent.concept_intent import local_only
    from src.agent.prompt import DialogueTurn
    history = [DialogueTurn(role='user', content='只用本地材料')]
    assert local_only('解释光合作用', history)
    assert not local_only('现在允许补充一般知识，请介绍光合作用', history)


@pytest.mark.asyncio
async def test_concept_usage_followup_reuses_subject_even_after_reloading_history():
    runtime = AgentRuntime()
    model = FakeLLM(answer='用途介绍')
    first = await runtime.execute(ChatRequest(query='WHCNS模型', session_id='intro'), service=None, llm=model, get_report=None)
    history = [{'role': 'user', 'content': 'WHCNS模型'}, {'role': 'assistant', 'content': first.answer}]
    second = await runtime.execute(ChatRequest(query='它有什么用？', session_id='reloaded', history=history), service=None, llm=model, get_report=None)
    trace = runtime.runs.get(second.run_id)
    assert trace.decision.reason_code == 'concept_followup'
    assert trace.decision.skills == ['concept_explanation']
    assert 'WHCNS模型' in model.messages[1].content and trace.history_count == 2
    runtime.runs.close()
