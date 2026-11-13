"""Semantic entry contracts; actual language quality is checked by live replay."""
import asyncio
import json

import pytest

from src.agent.chat_service import ChatService
from src.agent.runtime import AgentRuntime
from src.agent.semantic_query import SemanticQuery
from src.agent.starred_match import match_starred
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage
from src.retrieval.local_index import retrieval_requests
from tests.test_starred_upgrade import parse
from tests.test_chat_runs import Service
from tests.test_case_library import FakeLLM

QUESTION = {'question_id': 'maintained', 'question': '怎样把数据模型应用衔接起来用于氮淋失管控？',
            'answer': '项目计划用情景数据驱动模型，评价措施后再验证推广，尚不代表已验证效果。',
            'reuse': {'reuse_status': 'reference', 'profile': 'project_plan',
                      'coverage_scope': '项目计划流程', 'excluded_scope': '已验证效果'}}
QUERY = '观测信息到模拟预测再到治理决策，这条技术路线准备怎么贯通？'
REWRITE = '氮素淋溶管控的情景数据、模型模拟、措施评价与验证推广计划流程'


class Model:
    def __init__(self, *, rewrite=REWRITE, matches=None, mutate=None):
        self.rewrite, self.matches, self.mutate = rewrite, matches, mutate
        self.payloads = []

    async def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1].content)
        self.payloads.append(payload)
        value = {'tasks': [{'subtask_id': t['subtask_id'], 'intent':'knowledge','domain_scope':'supported','input_kind':'literature', 'resolved_query': self.rewrite or t['query'],
                            'retrieval_query': self.rewrite or t['query'], 'intent_description': '理解技术路线的衔接与计划范围',
                            'clarification': ''} for t in payload['tasks']]} if 'tasks' in payload else {
                 'assessments': [{'aspect_id': a['aspect_id'], 'matches': self.matches if self.matches is not None else [
                     {'question_id': 'maintained', 'coverage': 'complete', 'reason': '语义相同，且仅询问项目计划流程'}]}
                                 for a in payload['aspects']]}
        if self.mutate:
            try:
                self.mutate(value)
            except KeyError:
                pass  # A mutation targets one of the two independently validated stages.
        return ChatResult(content=json.dumps(value, ensure_ascii=False), model='semantic-test',
                          usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


class ForbiddenWeb:
    @property
    def ready(self):
        raise AssertionError('fully covered tasks must not reach web retrieval')


@pytest.mark.asyncio
async def test_semantic_paraphrase_has_no_literal_match_but_reuses_answer_without_search():
    assert match_starred(parse(QUERY), [QUESTION])['status'] == 'no_match'
    model = Model()
    runtime = AgentRuntime(semantic_query=SemanticQuery(model), web=ForbiddenWeb())
    service = Service()
    try:
        response = await runtime.execute(ChatRequest(query=QUERY), service=service, get_report=None,
                                         starred_provider=lambda: [QUESTION])
        trace = runtime.runs.get(response.run_id)
        assert trace.starred_match['status'] == 'full'
        assert QUESTION['answer'] in response.answer
        assert not service.calls and not trace.tool_calls
        assert response.usage.total_tokens == 30
        assert 'starred_questions' not in model.payloads[0]
        assert 'input_kind' not in model.payloads[0]['tasks'][0]
        assert 'intent' not in model.payloads[0]['tasks'][0]
        assert model.payloads[1]['interpretations'][0]['effective_retrieval_query'] == REWRITE
        assert trace.understanding['semantic']['candidate_recall'] == 'full_library_semantic_review'
        assert any(c['match_method'] == 'semantic_coverage' for c in trace.starred_match['tasks'][0]['candidates'])
        steps = [s['service'] for s in trace.execution_steps if s['type'] == 'step_started']
        assert steps.index('semantic_query') < steps.index('starred_match')
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_generic_prevention_measures_are_not_prematurely_excluded_as_case_work():
    query='以数据为依据，借助模拟工具筛选并推广氮素淋溶防治措施，项目准备走怎样一条路线？'
    assert parse(query)['subtasks'][0]['input_kind']=='case'  # Legacy heuristic guess.
    runtime=AgentRuntime(semantic_query=SemanticQuery(Model()))
    service=Service()
    try:
        response=await runtime.execute(ChatRequest(query=query),service=service,get_report=None,starred_provider=lambda:[QUESTION])
        trace=runtime.runs.get(response.run_id)
        assert trace.understanding['subtasks'][0]['input_kind']=='literature'
        assert trace.starred_match['status']=='full' and service.calls==0
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['WHCNS模型是什么？', '请查文献里的氮素迁移过程', '把这段材料解释一下：研究发现土壤水分影响氮迁移'])
async def test_professional_requests_are_interpreted_even_without_starred_candidates(query):
    model = Model(rewrite=None, matches=[])
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        await runtime.execute(ChatRequest(query=query), service=Service(), get_report=None, llm=FakeLLM())
        assert model.payloads[0]['raw_query'] == query
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_single_question_rewrite_reaches_actual_vector_and_managed_retrieval():
    understanding = parse(QUERY)
    interpretation = await SemanticQuery(Model(matches=[])).interpret(understanding, [], [])
    understanding.update(subtasks=interpretation['subtasks'], semantic=interpretation)
    vector_calls, text_calls = [], []
    class Retriever:
        def retrieve(self, query, k):
            vector_calls.append(query)
            return []
    class Index:
        def search(self, query, **kwargs):
            text_calls.append(query)
            return [], []
    class AnswerModel:
        async def chat(self, *args, **kwargs):
            return ChatResult(content='本次没有找到足够资料。', model='answer-test',
                              usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))
    service = ChatService(Retriever(), AnswerModel(), top_k=3, max_context_chars=1000, temperature=0, literature_index=Index())
    await service.answer(QUERY, understanding=understanding)
    assert vector_calls == text_calls == [REWRITE]
    assert retrieval_requests(QUERY, understanding)['full_text'] == REWRITE


@pytest.mark.asyncio
@pytest.mark.parametrize('query,rewrite', [
    ('陕西玉米施氮180千克，排除滴灌的淋溶研究', '小麦滴灌淋溶研究'),
    ('2024年研究的氮素淋溶量', '氮素淋溶研究'),
    ('仅使用本地材料解释氮淋失', '解释氮淋失'),
])
async def test_scope_changing_rewrite_is_rejected(query, rewrite):
    understanding = parse(query)
    result = await SemanticQuery(Model(rewrite=rewrite, matches=[])).interpret(understanding, [], [])
    assert all(r['status'] == 'rejected_scope_change' for r in result['rewrites'])
    assert all(t['retrieval_query'] == old['query'] for t, old in zip(result['subtasks'], understanding['subtasks']))


@pytest.mark.asyncio
@pytest.mark.parametrize('mutate', [
    lambda v: v['tasks'][0].pop('domain_scope'),
    lambda v: v['tasks'].clear(),
    lambda v: v['assessments'].clear(),
    lambda v: v['assessments'][0]['matches'][0].update(question_id='invented'),
    lambda v: v['tasks'].append(v['tasks'][0]),
])
async def test_invalid_model_output_falls_back_and_is_visible(mutate):
    runtime = AgentRuntime(semantic_query=SemanticQuery(Model(mutate=mutate)))
    service = Service()
    try:
        response = await runtime.execute(ChatRequest(query=QUERY), service=service, get_report=None,
                                         starred_provider=lambda: [QUESTION])
        trace = runtime.runs.get(response.run_id)
        assert trace.understanding['semantic']['status'] == 'degraded'
        assert not trace.starred_match['adopted'] and service.calls == 1
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_timeout_does_not_abort_original_request():
    class Slow:
        async def chat(self, *args, **kwargs):
            await asyncio.sleep(1)
    runtime = AgentRuntime(semantic_query=SemanticQuery(Slow(), timeout_s=.001))
    try:
        response = await runtime.execute(ChatRequest(query=QUERY), service=Service(), get_report=None)
        assert runtime.runs.get(response.run_id).understanding['semantic']['reason'] == 'semantic_timeout'
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('answer,status', [('', 'reference'), ('待审核', 'reference'), ('不确定结论', 'conflict'), ('未审核答案', 'pending')])
async def test_model_cannot_override_answer_readiness(answer, status):
    understanding = parse(QUERY)
    question = {**QUESTION, 'answer': answer, 'reuse': {**QUESTION['reuse'], 'reuse_status': status}}
    result = await SemanticQuery(Model()).interpret(understanding, [question], [])
    assert not match_starred(understanding, [question], semantic=result)['adopted']


@pytest.mark.asyncio
async def test_partial_coverage_keeps_remaining_request_and_conflicts_are_not_selected():
    understanding = parse(QUERY)
    partial = [{'question_id': 'maintained', 'coverage': 'partial', 'reason': '不含已验证效果'}]
    result = await SemanticQuery(Model(matches=partial)).interpret(understanding, [QUESTION], [])
    matched = match_starred(understanding, [QUESTION], semantic=result)
    assert matched['status'] == 'partial' and matched['remaining_tasks']
    assert '已验证效果' in matched['remaining_tasks'][0]['retrieval_query']
    second = {**QUESTION, 'question_id': 'other', 'answer': '不同的结论'}
    matches = [{'question_id': q['question_id'], 'coverage': 'complete', 'reason': '覆盖同一个需求'} for q in (QUESTION, second)]
    result = await SemanticQuery(Model(matches=matches)).interpret(understanding, [QUESTION, second], [])
    assert match_starred(understanding, [QUESTION, second], semantic=result)['status'] == 'conflict'


@pytest.mark.asyncio
async def test_complete_coverage_wins_over_related_partial_without_false_conflict():
    understanding = parse(QUERY)
    second = {**QUESTION, 'question_id': 'other', 'answer': '项目仅有模型选型方面的说明'}
    matches = [{'question_id': 'maintained', 'coverage': 'complete', 'reason': '完整覆盖路线概述'},
               {'question_id': 'other', 'coverage': 'partial', 'reason': '只涉及模型一环'}]
    result = await SemanticQuery(Model(matches=matches)).interpret(understanding, [QUESTION, second], [])
    matched = match_starred(understanding, [QUESTION, second], semantic=result)
    assert matched['status'] == 'full'
    assert [q['question_id'] for q in matched['adopted']] == ['maintained']
    for match in matches:
        match['coverage']='partial'
    result = await SemanticQuery(Model(matches=matches)).interpret(understanding, [QUESTION, second], [])
    matched = match_starred(understanding, [QUESTION, second], semantic=result)
    assert matched['status'] == 'partial' and matched['remaining_tasks']


@pytest.mark.asyncio
async def test_plan_answer_cannot_cover_already_verified_effect_even_if_model_says_partial():
    understanding = parse('通过数据模型应用对氮素淋溶的防控，已经验证的减排效果是多少？')
    matches = [{'question_id': 'maintained', 'coverage': 'partial', 'reason': '仅说明计划'}]
    result = await SemanticQuery(Model(rewrite=None, matches=matches)).interpret(understanding, [QUESTION], [])
    assert not match_starred(understanding, [QUESTION], semantic=result)['adopted']


@pytest.mark.asyncio
async def test_recall_failure_still_runs_model_interpretation():
    model = Model(matches=[])
    result = await SemanticQuery(model).interpret(parse(QUERY), [QUESTION]*49, [])
    assert result['status'] == 'applied' and model.payloads
    assert result['candidate_recall'] == 'semantic_candidate_recall_unavailable'


@pytest.mark.asyncio
async def test_json_mode_format_label_does_not_discard_valid_interpretation():
    result = await SemanticQuery(Model(matches=[], mutate=lambda v: v.update(type='json_object'))).interpret(parse(QUERY), [], [])
    assert result['status'] == 'applied'


@pytest.mark.asyncio
async def test_embedding_recall_has_no_literal_overlap_gate_for_large_library():
    questions = [{**QUESTION, 'question_id': str(i), 'question': '另一种表述'+chr(0x4e00+i)} for i in range(49)]
    class Embedder:
        def embed_documents(self, texts):
            return [[1, 0] if i == 48 else [0, 1] for i in range(len(texts))]
        def embed_query(self, text):
            return [1, 0]
    model = Model(matches=[])
    result = await SemanticQuery(model, embedder=Embedder()).interpret(parse(QUERY), questions, [])
    assert result['candidate_recall'] == 'embedding_semantic_recall'
    assert '48' in result['candidate_ids']
    assert len(result['candidate_ids']) == 12
