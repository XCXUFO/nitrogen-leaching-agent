"""Basic plant physiology is supported in either language and across turns."""
import json

import pytest

from src.agent.concept_intent import concept_intent
from src.agent.domain_scope import DOMAIN_INSTRUCTIONS, OUTSIDE_DOMAIN_ANSWER
from src.agent.runtime import AgentRuntime
from src.agent.semantic_query import SCOPE_REVIEW_SYSTEM, SemanticQuery
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage


FIRST = 'How do plants produce oxygen?'
FOLLOWUP = "But don't plants need oxygen for respiration too? How can they produce it?"


class PlantModel:
    def __init__(self, *, initial_scope='outside', review_scope='supported'):
        self.initial_scope, self.review_scope = initial_scope, review_scope
        self.answer_messages = []

    async def chat(self, messages, **kwargs):
        if messages[0].content.startswith(DOMAIN_INSTRUCTIONS):
            self.answer_messages.append(messages)
            content = 'Plants release oxygen during photosynthesis and consume oxygen during respiration.'
        else:
            payload = json.loads(messages[-1].content)
            if messages[0].content == SCOPE_REVIEW_SYSTEM:
                value = {'tasks': [{'subtask_id': task['subtask_id'], 'domain_scope': self.review_scope,
                                   'reason': '复核实际需求，植物生理属于农业相关基础知识'} for task in payload['tasks']]}
            else:
                value = {'tasks': [{'subtask_id': task['subtask_id'], 'domain_scope': self.initial_scope,
                    'intent': 'knowledge', 'input_kind': 'literature', 'resolved_query': task['query'],
                    'retrieval_query': task['query'], 'intent_description': '解释植物产氧与呼吸作用',
                    'clarification': ''} for task in payload['tasks']]}
            content = json.dumps(value, ensure_ascii=False)
        return ChatResult(content=content, model='plant-scope-test',
                          usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


@pytest.mark.parametrize('query', [
    FIRST, FOLLOWUP, '植物如何产生氧气？', '植物为什么既消耗氧气又产生氧气？',
    'How does photosynthesis work?', 'Explain transpiration in plants.',
])
def test_basic_plant_questions_use_concept_explanation(query):
    assert concept_intent(query)


def test_quantitative_research_question_keeps_the_professional_path():
    assert not concept_intent('What is the measured oxygen concentration in plants in this research paper?')


@pytest.mark.asyncio
@pytest.mark.parametrize('initial_scope', ['supported', 'outside'])
@pytest.mark.parametrize('old_refusal', [False, True])
async def test_english_plant_question_and_followup_answer_without_a_case_library(initial_scope, old_refusal):
    model = PlantModel(initial_scope=initial_scope)
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        first = await runtime.execute(ChatRequest(query=FIRST, session_id='plants'),
            service=None, get_report=None, llm=model)
        second = await runtime.execute(ChatRequest(query=FOLLOWUP, session_id='plants', history=[
            {'role': 'user', 'content': FIRST},
            {'role': 'assistant', 'content': OUTSIDE_DOMAIN_ANSWER if old_refusal else first.answer}]),
            service=None, get_report=None, llm=model)
        for response in (first, second):
            trace = runtime.runs.get(response.run_id)
            assert response.route == 'knowledge'
            assert 'photosynthesis' in response.answer and 'respiration' in response.answer
            assert [call.skill for call in trace.tool_calls] == ['concept_explanation']
            assert trace.understanding['subtasks'][0]['domain_scope'] == 'supported'
            assert not trace.retrieval and not response.citations
            if initial_scope == 'outside':
                assert trace.understanding['semantic']['scope_reviews'][0]['domain_scope'] == 'supported'
        assert FIRST in model.answer_messages[-1][-1].content
        assert FOLLOWUP in model.answer_messages[-1][-1].content
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_agricultural_keyword_only_requests_review_and_does_not_grant_access():
    model = PlantModel(review_scope='outside')
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        response = await runtime.execute(ChatRequest(query='Plants aside, explain how black holes form.'),
            service=None, get_report=None, llm=model)
        assert response.answer == OUTSIDE_DOMAIN_ANSWER
        assert not model.answer_messages
        trace = runtime.runs.get(response.run_id)
        assert trace.understanding['semantic']['scope_reviews'][0]['domain_scope'] == 'outside'
    finally:
        runtime.runs.close()
