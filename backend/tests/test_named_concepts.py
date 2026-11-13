"""A recognized standalone term asks for its meaning, even without a question."""
import json

import pytest

from src.agent.concept_intent import concept_intent, named_concept_intent
from src.agent.domain_scope import DOMAIN_GUIDANCE_ANSWER, DOMAIN_INSTRUCTIONS
from src.agent.routing import decide
from src.agent.runtime import AgentRuntime
from src.agent.semantic_query import SemanticQuery
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage


ANSWER = 'WHCNS 是用于农田土壤水分、热量、碳氮循环和作物生长模拟的过程模型，可用于分析水氮管理措施。'
CLARIFICATION = '请说明“WHCNS”具体指什么，或补充相关背景。'


@pytest.mark.parametrize('query', [
    'WHCNS', ' whcns？ ', 'WHCNS 模型', 'WHCNS model', 'WHCNS_Rice', 'ＷＨＣＮＳ',
    'APSIM', 'DSSAT模型', 'HYDRUS-1D', 'RZWQM2', 'DNDC',
    '氮素淋失', '农田氮淋溶', '硝态氮', '反硝化作用', '光合作用', '植物呼吸作用',
    'nitrogen leaching', 'photosynthesis',
])
def test_complete_known_terms_are_introductory_questions(query):
    assert named_concept_intent(query)
    assert concept_intent(query)
    assert decide(query, has_file=False).skills == ['concept_explanation']


@pytest.mark.parametrize('query', [
    '模型', '这个模型', 'XYZ', 'WHCNS参数率定', 'WHCNS模型的适用深度',
    'WHCNS输出表最大值', 'WHCNS论文', 'WHCNS，解释黑洞的形成', '动能定理', '你好', '123',
])
def test_known_term_default_requires_the_entire_input_to_be_a_term(query):
    assert not named_concept_intent(query)


class UncertainConceptModel:
    def __init__(self, *, scope='unknown', intent='knowledge', input_kind='literature', rewrite=None, maintained=None,
                 answer=ANSWER, clarification=CLARIFICATION):
        self.scope, self.intent, self.input_kind = scope, intent, input_kind
        self.rewrite, self.maintained = rewrite, maintained
        self.answer = answer
        self.clarification = clarification
        self.answer_messages = []

    async def chat(self, messages, **kwargs):
        if messages[0].content.startswith(DOMAIN_INSTRUCTIONS):
            self.answer_messages.append(messages)
            content = self.answer
        else:
            payload = json.loads(messages[-1].content)
            if 'tasks' in payload:
                value = {'tasks': [{'subtask_id': task['subtask_id'], 'domain_scope': self.scope,
                    'intent': self.intent, 'input_kind': self.input_kind,
                    'resolved_query': self.rewrite or task['query'], 'retrieval_query': self.rewrite or task['query'],
                    'intent_description': '用户只输入了一个术语，需要补充背景。',
                    'clarification': self.clarification} for task in payload['tasks']]}
            else:
                value = {'assessments': [{'aspect_id': aspect['aspect_id'], 'matches': [
                    {'question_id': self.maintained, 'coverage': 'complete', 'reason': '覆盖模型的概念与用途'}
                ] if self.maintained else []} for aspect in payload['aspects']]}
            content = json.dumps(value, ensure_ascii=False)
        return ChatResult(content=content, model='uncertain-concept-test',
                          usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


@pytest.mark.asyncio
@pytest.mark.parametrize('scope,intent,input_kind', [
    ('unknown', 'knowledge', 'literature'),
    ('supported', 'knowledge', 'literature'),
    ('supported', 'capability', 'literature'),
    ('outside', 'knowledge', 'literature'),
    ('unknown', 'case_search', 'case'),
])
async def test_named_model_answers_despite_semantic_misclassification(scope, intent, input_kind):
    model = UncertainConceptModel(scope=scope, intent=intent, input_kind=input_kind)
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        response = await runtime.execute(ChatRequest(query='WHCNS'), service=None, get_report=None, llm=model)
        trace = runtime.runs.get(response.run_id)
        assert response.answer == ANSWER
        assert response.route == 'knowledge'
        assert [call.skill for call in trace.tool_calls] == ['concept_explanation']
        assert not trace.understanding['unresolved']
        task = trace.understanding['subtasks'][0]
        assert task['domain_scope'] == 'supported' and task['intent'] == 'explanation'
        rewrite = trace.understanding['semantic']['rewrites'][0]
        assert rewrite['clarification'] == ''
        assert rewrite['model_interpretation']['clarification'] == CLARIFICATION
        assert not response.citations and not response.file_evidence
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_named_model_does_not_inherit_an_invented_specialist_request():
    model = UncertainConceptModel(rewrite='WHCNS模型的参数率定方法')
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        response = await runtime.execute(ChatRequest(query='WHCNS', file_id='unused-attachment', history=[
            {'role': 'user', 'content': '你好'}, {'role': 'assistant', 'content': DOMAIN_GUIDANCE_ANSWER}]),
            service=None, get_report=None, llm=model)
        trace = runtime.runs.get(response.run_id)
        assert response.answer == ANSWER
        assert trace.understanding['subtasks'][0]['semantic_query'] == 'WHCNS'
        assert trace.decision.skills == ['concept_explanation']
        assert '【当前问题】\nWHCNS' in model.answer_messages[0][-1].content
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('semantic_enabled', [False, True])
@pytest.mark.parametrize('query', ['WHCNS', 'WHCNS是什么？', '介绍一下WHCNS模型'])
async def test_introductory_model_question_generates_explanation_instead_of_copying_project_qa(query, semantic_enabled):
    model = UncertainConceptModel(maintained='whcns-intro', intent='explanation', scope='supported', clarification='')
    runtime = AgentRuntime(semantic_query=SemanticQuery(model) if semantic_enabled else None)
    stored_answer = '课题材料选择它的理由是与项目目标相符。具体版本需结合项目实现说明。'
    try:
        response = await runtime.execute(ChatRequest(query=query), service=None, get_report=None, llm=model,
            starred_provider=lambda: [{'question_id': 'whcns-intro', 'question': query, 'answer': stored_answer,
                'reuse': {'profile': 'whcns_intro', 'reuse_status': 'reference', 'source_refs': ['课题4 · P2']}}])
        trace = runtime.runs.get(response.run_id)
        assert response.answer == ANSWER and stored_answer not in response.answer
        assert trace.starred_match['status'] == 'not_applicable'
        assert trace.starred_match['tasks'][0]['reason'] == 'concept_explanation_required'
        assert not trace.starred_match['adopted']
        assert [call.skill for call in trace.tool_calls] == ['concept_explanation']
        assert len(model.answer_messages) == 1
        assert trace.skill_config['task_prompt_usage'][0]['scope'] == 'concept_explanation'
        assert not any(item.source_type == 'starred' for item in response.evidence)
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_model_overview_uses_retrieved_evidence_through_concept_generation():
    from src.agent.chat_service import ChatService
    from src.rag.retriever import RetrievalResult
    from tests.test_chat_service import FakeLLMClient, FakeRetriever

    model = FakeLLMClient(ANSWER + ' [1]')
    retriever = FakeRetriever([RetrievalResult(chunk_id='whcns-paper', document=ANSWER, score=0.9,
        metadata={'source': 'whcns-paper.txt', 'title': 'WHCNS model description'})])
    service = ChatService(retriever, model, top_k=5, max_context_chars=4000, temperature=0)
    runtime = AgentRuntime()
    try:
        response = await runtime.execute(ChatRequest(query='WHCNS'), service=service, get_report=None,
            starred_provider=lambda: [{'question_id': 'intro', 'question': 'WHCNS', 'answer': '课题选型说明。'}])
        trace = runtime.runs.get(response.run_id)
        assert [call.skill for call in trace.tool_calls] == ['concept_explanation']
        assert retriever.calls and response.citations[0].chunk_id == 'whcns-paper'
        assert response.citations[0].snippet == ANSWER and '[1]' in response.answer
        assert '课题选型说明' not in response.answer
        assert trace.skill_config['task_prompt_usage'][0]['scope'] == 'concept_explanation'
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_named_concept_still_obeys_the_existing_source_restriction():
    model = UncertainConceptModel()
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        response = await runtime.execute(ChatRequest(query='WHCNS', history=[
            {'role': 'user', 'content': '后续只用本地材料'}, {'role': 'assistant', 'content': '好的'}]),
            service=None, get_report=None, llm=model)
        assert '本地资料服务当前不可用' in response.answer
        assert not model.answer_messages and not response.citations
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('query', ['这个模型', 'XYZ', 'WHCNS参数率定', 'WHCNS模型的适用深度'])
async def test_incomplete_referents_and_specialist_requests_keep_semantic_clarification(query):
    model = UncertainConceptModel(scope='supported')
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        response = await runtime.execute(ChatRequest(query=query), service=None, get_report=None, llm=model)
        assert response.route == 'clarification' and response.answer == CLARIFICATION
        assert not model.answer_messages
    finally:
        runtime.runs.close()


@pytest.mark.parametrize('query,skill', [
    ('WHCNS参数率定', 'knowledge_search'),
    ('请查WHCNS的文献', 'knowledge_search'),
    ('WHCNS输出表中淋失量最大值', 'clarification'),
    ('WHCNS 的案例有哪些？', 'case_assistant'),
    ('你是谁', 'capability_guidance'),
])
def test_named_term_in_a_larger_request_keeps_the_requested_task(query, skill):
    assert decide(query, has_file=False).skills == [skill]
