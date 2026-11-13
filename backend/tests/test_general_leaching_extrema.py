"""General extrema questions explain context before asking for data."""
import pytest

from src.agent.concept_intent import CONCEPT_SYSTEM
from src.agent.domain_scope import OUTSIDE_DOMAIN_ANSWER_EN
from src.agent.file_chat import needs_file
from src.agent.query_intent import general_leaching_extrema
from src.agent.routing import decide
from src.agent.runtime import AgentRuntime
from src.agent.semantic_query import SemanticQuery
from src.api.chat_schema import ChatRequest
from tests.test_named_concepts import UncertainConceptModel
from tests.test_plant_scope import PlantModel


QUESTION = 'What is the maximum nitrate leaching?'
ANSWER = ('There is no universal maximum nitrate leaching value: rainfall, irrigation, nitrogen supply, soil and crop uptake '
          'all affect it. Nitrate leaching is nitrate transported downward by draining water. A maximum also depends '
          'on whether you mean a daily or seasonal mass loss, a flux or a concentration. '
          'Are you asking about general ranges or a particular crop and season?')


@pytest.mark.parametrize('query', [
    QUESTION, 'Maximum nitrate leaching?', 'What is the maximum amount of nitrogen leaching?',
    'What is the minimum nitrate leaching?', '硝态氮淋失最大值是多少？', '氮素淋失量最高是多少？',
    '硝态氮淋失的最大值为什么没有统一上限？',
    'What is the maximum nitrate leaching in typical cropland?',
    'What is the maximum daily nitrate leaching for maize?',
    'What is the theoretical maximum nitrate leaching in WHCNS?',
    '硝态氮淋失在玉米生长季最高能达到多少？',
])
def test_extrema_without_a_source_are_general_questions(query):
    assert general_leaching_extrema(query)
    assert not needs_file(query)
    decision = decide(query, has_file=False)
    assert decision.skills == ['concept_explanation']
    assert decision.reason_code == 'general_leaching_extrema'


@pytest.mark.asyncio
@pytest.mark.parametrize('semantic', [False, True])
@pytest.mark.parametrize('attachment_mode', ['none', 'empty_session'])
async def test_original_question_explains_in_english_without_demanding_an_attachment(semantic, attachment_mode):
    model = UncertainConceptModel(intent='file_calculation', rewrite='WHCNS nitrate leaching maximum', answer=ANSWER)
    runtime = AgentRuntime(semantic_query=SemanticQuery(model) if semantic else None)
    try:
        response = await runtime.execute(ChatRequest(query=QUESTION, **({'file_ids': []} if attachment_mode == 'empty_session' else {})),
            service=None, get_report=None, llm=model)
        trace = runtime.runs.get(response.run_id)
        assert response.route == 'knowledge' and response.answer == ANSWER
        assert trace.understanding['intents'] == ['explanation']
        assert [call.skill for call in trace.tool_calls] == ['concept_explanation']
        assert not response.file_evidence and not response.citations
        assert 'WHCNS' not in response.answer and 'upload' not in response.answer.lower()
        assert QUESTION in model.answer_messages[0][-1].content
        assert CONCEPT_SYSTEM in model.answer_messages[0][0].content
        if semantic:
            rewrite = trace.understanding['semantic']['rewrites'][0]
            assert rewrite['intent_basis'] == 'general_leaching_extrema'
            assert rewrite['model_interpretation']['intent'] == 'file_calculation'
            assert not rewrite['clarification']
    finally:
        runtime.runs.close()


@pytest.mark.parametrize('query,has_file,skill', [
    ('Nbal_out.xls 硝态氮淋失最大值', False, 'clarification'),
    ('What is the maximum nitrate leaching in the uploaded table?', False, 'clarification'),
    ('leak_NO3 maximum', False, 'clarification'),
    ('硝态氮淋失最大值及对应日序', False, 'clarification'),
    (QUESTION, True, 'file_inspector'),
    ('In general, what is the maximum nitrate leaching?', True, 'concept_explanation'),
    ('论文中硝态氮淋失最大值是多少？', False, 'knowledge_search'),
])
def test_explicit_data_requests_and_attached_calculations_keep_their_source(query, has_file, skill):
    assert decide(query, has_file=has_file).skills[0] == skill


@pytest.mark.asyncio
async def test_missing_explicit_table_requests_the_table_without_inventing_a_model():
    runtime = AgentRuntime()
    try:
        response = await runtime.execute(ChatRequest(query='What is the maximum nitrate leaching in this table?'),
            service=None, get_report=None)
        assert response.route == 'clarification'
        assert 'upload' in response.answer.lower() and 'WHCNS' not in response.answer
    finally:
        runtime.runs.close()


@pytest.mark.parametrize('query', [
    'What is the maximum nitrate leaching in this dataset?',
    'What is the maximum nitrate leaching reported in the literature?',
    'WHCNS输出表中硝态氮淋失最大值',
])
def test_a_leaching_keyword_does_not_override_other_requested_work(query):
    assert not general_leaching_extrema(query)


@pytest.mark.asyncio
async def test_general_extrema_cannot_override_a_reviewed_outside_domain_request():
    model = PlantModel(initial_scope='outside', review_scope='outside')
    runtime = AgentRuntime(semantic_query=SemanticQuery(model))
    try:
        response = await runtime.execute(ChatRequest(query='Explain how black holes form, setting the maximum nitrate leaching aside.'),
            service=None, get_report=None, llm=model)
        assert response.answer == OUTSIDE_DOMAIN_ANSWER_EN
        trace = runtime.runs.get(response.run_id)
        assert trace.understanding['semantic']['scope_reviews'][0]['domain_scope'] == 'outside'
        assert not model.answer_messages
    finally:
        runtime.runs.close()
