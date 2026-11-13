"""User-provided observations and plans do not require unrelated literature."""
import json

import pytest

from src.agent.runtime import AgentRuntime
from src.agent.provided_text import has_provided_text
from src.agent.case_intent import case_mode
from src.agent.semantic_query import SemanticQuery
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage
from tests.test_provided_text import ForbiddenLibrary

PLAN = "请记录本轮农田水氮试验条件：代号 MT-N7，夏玉米，砂壤土，滴灌，总施氮量180 kg N/ha，分3次等量施用。仅复述这些测试条件，不评价效果。"
OBSERVATIONS = "现在只根据本条提供的合成农田观测记录回答：第1天硝态氮淋失1.2，第2天0.4，第3天2.0，单位均为kg N/ha。最大值是哪天、多少？"


class RecordModel:
    def __init__(self):
        self.payloads = []

    async def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1].content)
        assert payload['source_type'] == 'user_text' and not payload['available_cases']
        self.payloads.append(payload)
        return ChatResult(content=json.dumps({'answer': '已核对本轮用户给出的测试记录，未补入其他观测。',
            'used_case_ids': [], 'outcome': 'complete'}, ensure_ascii=False), model='record-test',
            usage=ChatUsage(prompt_tokens=2, completion_tokens=1, total_tokens=3))


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [PLAN, OBSERVATIONS,
    '这是农田水氮试验方案记录：A地块为玉米、砂壤土、施氮160 kg N/ha；B地块为冬小麦、黏壤土、施氮120 kg N/ha。请只复述两个地块条件，不评价施肥效果。',
    '本轮农田试验代号 MT-RETURN，作物玉米，计划施氮180 kg N/ha。请只复述记录，不提出新方案。'])
async def test_explicit_user_records_reach_text_answering_without_a_file_or_retrieval(query):
    model = RecordModel()
    runtime = AgentRuntime()
    try:
        response = await runtime.execute(ChatRequest(query=query), service=ForbiddenLibrary(), get_report=None,
            case_store=ForbiddenLibrary(), llm=model)
        assert response.route == 'knowledge' and response.case_match == 'text_only'
        assert response.outcome == 'complete'
        assert model.payloads[-1]['mode'] == 'explain'
        assert model.payloads[-1]['question'] == query
        assert not response.citations and not response.file_evidence
        assert not runtime.runs.get(response.run_id).retrieval
    finally:
        runtime.runs.close()


@pytest.mark.parametrize('query,expected', [
    ('请只复述条件，不评价效果。', 'explain'),
    ('不要评价施肥效果，请复述记录。', 'explain'),
    ('不评价效果，但请列出实际测定的效果证据。', 'evidence'),
    ('这个措施效果如何？', 'evidence'),
])
def test_negated_effect_evaluation_does_not_select_evidence_mode(query, expected):
    assert case_mode(query, 'explain') == expected


@pytest.mark.asyncio
async def test_source_followup_does_not_receive_new_concept_questions_from_a_rewrite():
    from tests.test_provided_text import Model

    class RewritingModel(RecordModel):
        async def chat(self, messages, **kwargs):
            payload = json.loads(messages[-1].content)
            if 'tasks' in payload:
                return await Model(initial_scope='supported', rewrite='说明更正后的总量，并解释玉米是什么。').chat(messages, **kwargs)
            return await super().chat(messages, **kwargs)

    model = RewritingModel()
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    correction = '更正：总施氮量改成150 kg N/ha，其他条件不变。每次又是多少？'
    try:
        first = await runtime.execute(ChatRequest(query=PLAN, session_id='source-rewrite'),
            service=ForbiddenLibrary(), get_report=None, llm=model)
        await runtime.execute(ChatRequest(query=correction, session_id='source-rewrite', history=[
            {'role': 'user', 'content': PLAN}, {'role': 'assistant', 'content': first.answer}]),
            service=ForbiddenLibrary(), get_report=None, llm=model)
        assert model.payloads[-1]['question'] == correction
        assert PLAN in model.payloads[-1]['previous_user_text']
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_record_corrections_and_summary_keep_verified_user_material():
    model = RecordModel()
    runtime = AgentRuntime()
    history = []
    queries = [PLAN, '那每次是多少？仍以纯氮计。',
        '更正：总施氮量改成150 kg N/ha，其他条件不变。每次又是多少？',
        '请汇总最终采用的作物、土壤、灌溉方式、总施氮量、次数和每次用量。']
    try:
        for query in queries:
            response = await runtime.execute(ChatRequest(query=query, session_id='record', history=history),
                service=ForbiddenLibrary(), get_report=None, case_store=ForbiddenLibrary(), llm=model)
            assert response.case_match == 'text_only'
            history += [{'role': 'user', 'content': query}, {'role': 'assistant', 'content': response.answer}]
        payload = model.payloads[-1]
        assert PLAN in payload['previous_user_text']
        assert '150 kg N/ha' in payload['previous_user_text']
        assert not runtime.runs.get(response.run_id).retrieval
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_inline_observation_correction_retains_previous_days_without_an_upload():
    model = RecordModel()
    runtime = AgentRuntime()
    try:
        first = await runtime.execute(ChatRequest(query=OBSERVATIONS, session_id='observations'),
            service=ForbiddenLibrary(), get_report=None, llm=model)
        await runtime.execute(ChatRequest(query='更正这组观测记录：第2天应为2.5，其他不变。重新给出最大值及日序。',
            session_id='observations', history=[{'role': 'user', 'content': OBSERVATIONS},
                {'role': 'assistant', 'content': first.answer}]), service=ForbiddenLibrary(), get_report=None, llm=model)
        assert OBSERVATIONS in model.payloads[-1]['previous_user_text']
    finally:
        runtime.runs.close()


@pytest.mark.parametrize('query', ['农田观测记录是什么？', '请帮我设计农田试验方案。',
    '试验条件：', '观测记录：https://example.com', '本轮农田试验请只复述记录。'])
def test_no_pasted_record_is_invented_from_a_topic_or_link(query):
    assert not has_provided_text(query)


@pytest.mark.asyncio
async def test_verified_record_survives_unrelated_refusal_but_does_not_answer_it():
    model = RecordModel()
    runtime = AgentRuntime()
    history = []
    try:
        for query in [PLAN, '那我明天晚餐吃什么？给个菜单。', '回到刚才的农田试验，代号和总施氮量是多少？']:
            result = await runtime.execute(ChatRequest(query=query, session_id='return-record', history=history),
                service=ForbiddenLibrary(), get_report=None, llm=model)
            if '菜单' in query:
                assert result.route == 'out_of_scope'
                assert len(model.payloads) == 1
            history += [{'role': 'user', 'content': query}, {'role': 'assistant', 'content': result.answer}]
        assert PLAN in model.payloads[-1]['previous_user_text']
    finally:
        runtime.runs.close()
