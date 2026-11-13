"""Pasted agricultural evidence stays intact through scope checks and answering."""
import json
from types import SimpleNamespace

import pytest

from src.agent.contracts import TaskState
from src.agent.domain_scope import DOMAIN_INSTRUCTIONS, OUTSIDE_DOMAIN_ANSWER, outside_domain
from src.agent.provided_text import has_provided_text
from src.agent.runtime import AgentRuntime
from src.agent.routing import decide
from src.agent.semantic_query import SCOPE_REVIEW_SYSTEM, SemanticQuery
from src.agent.understanding import understand
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage


PASSAGE = (
    "Deforestation is the conversion of forested areas to non-forested areas. "
    "The main sources of deforestation in the Amazon are human settlement and development of the land. "
    "Prior to the early 1960s, access to the forest's interior was highly restricted, and the forest remained basically intact. "
    "Farms established during the 1960s were based on crop cultivation and the slash and burn method. "
    "However, the colonists were unable to manage their fields and the crops because of the loss of soil fertility and weed invasion. "
    "The soils in the Amazon are productive for just a short period of time, so farmers are constantly moving to new areas and clearing more land. "
    "These farming practices led to deforestation and caused extensive environmental damage. "
    "Deforestation is considerable, and areas cleared of forest are visible to the naked eye from outer space."
)
QUERY = ("这是农田土壤管理与水氮风险的资料核对任务。只根据下列段落回答；没有数据时说无法确定，不要补造。\n资料：\n"
         + PASSAGE + "\n问题：资料指出，移民在亚马孙地区开展农作物种植后，哪两个因素使其难以维持生计？")


def parse(query):
    return understand(ChatRequest(query=query), TaskState(conversation_id='fixture'),
                      SimpleNamespace(run_id='r', turn_id='t'))


@pytest.mark.parametrize('query', [QUERY, '仅根据下面资料回答；不要补造。\n资料：土壤肥力下降；杂草入侵，同时缺少灌溉。\n问题：有哪些困难？'])
def test_passage_instructions_and_questions_are_one_complete_task(query):
    result = parse(query)
    assert len(result['subtasks']) == 1
    assert result['subtasks'][0]['query'] == query
    assert result['subtasks'][0]['input_kind'] == 'user_text'


def test_independent_questions_still_split_and_missing_body_is_not_source_text():
    assert len(parse('解释氮素淋失；比较滴灌和漫灌')['subtasks']) == 2
    assert not has_provided_text('资料：\n问题：土壤肥力是什么？')
    assert not has_provided_text('资料：https://example.com/paper')


def test_only_the_actual_question_triggers_explicit_domain_rules():
    assert not outside_domain('资料：作物记录中出现“你妈是谁”“明天吃啥”“动能定理”等无关文字。\n问题：土壤肥力下降有什么影响？')
    assert outside_domain('这是农田土壤管理任务。\n资料：土壤肥力下降。\n问题：解释下动能定理')


def test_source_mentions_of_cases_do_not_trigger_library_search():
    query = '资料：案例记载了分次施肥的措施及效果证据。\n问题：原文提到了哪种措施？'
    decision = decide(query, has_file=False)
    assert decision.reason_code == 'provided_text_question'
    assert decision.skills == ['case_assistant']
    search = decide(query.rsplit('问题：', 1)[0] + '问题：请找类似案例供参考。', has_file=False)
    assert search.reason_code == 'case_reference_intent'


class Model:
    def __init__(self, *, initial_scope='outside', review_scope='supported', rewrite=None,
                 answer='两个因素是土壤肥力下降和杂草入侵。', review_error=False):
        self.initial_scope, self.review_scope, self.rewrite = initial_scope, review_scope, rewrite
        self.answer, self.review_error = answer, review_error
        self.calls = []

    async def chat(self, messages, **kwargs):
        self.calls.append(messages)
        payload = json.loads(messages[-1].content)
        if messages[0].content == SCOPE_REVIEW_SYSTEM:
            if self.review_error:
                raise ValueError('scope review unavailable')
            value = {'tasks': [{'subtask_id': t['subtask_id'], 'domain_scope': self.review_scope,
                                'reason': '依据原问题的实际提问对象复核'} for t in payload['tasks']]}
        elif 'tasks' in payload:
            value = {'tasks': [{'subtask_id': t['subtask_id'], 'intent': 'knowledge',
                'domain_scope': self.initial_scope, 'input_kind': 'literature',
                'resolved_query': self.rewrite or t['query'], 'retrieval_query': self.rewrite or t['query'],
                'intent_description': '提取用户提供段落中的两个因素', 'clarification': ''} for t in payload['tasks']]}
        else:
            assert payload['source_type'] == 'user_text' and not payload['available_cases']
            assert messages[0].content.startswith(DOMAIN_INSTRUCTIONS)
            assert '只从该正文提取答案' in messages[0].content
            value = {'answer': self.answer, 'used_case_ids': [], 'outcome': 'complete'}
        return ChatResult(content=json.dumps(value, ensure_ascii=False), model='provided-text-test',
                          usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


class ForbiddenWeb:
    @property
    def ready(self):
        raise AssertionError('source-only answering must not access web search')


class ForbiddenLibrary:
    def __getattr__(self, name):
        raise AssertionError('source-only answering must not access libraries: ' + name)


@pytest.mark.asyncio
@pytest.mark.parametrize('semantic,initial_scope,rewrite', [
    (False, 'supported', None),
    (True, 'supported', None),
    (True, 'supported', '仅根据资料说明，1960、1960年代亚马孙移民种植作物有哪些困难？不要补造'),
    (True, 'outside', None),
    (True, 'outside', '亚马孙移民的种植困难'),
])
async def test_original_question_reaches_source_only_answer_after_scope_review(semantic, initial_scope, rewrite):
    model = Model(initial_scope=initial_scope, rewrite=rewrite)
    runtime = AgentRuntime(semantic_query=SemanticQuery(model) if semantic else None, web=ForbiddenWeb())
    try:
        response = await runtime.execute(ChatRequest(query=QUERY), service=ForbiddenLibrary(), get_report=None,
            case_store=ForbiddenLibrary(), llm=model,
            starred_provider=lambda: [{'question_id': 'unrelated', 'question': QUERY, 'answer': '不能代替原文的其他答案'}])
        trace = runtime.runs.get(response.run_id)
        assert response.answer == model.answer
        assert [c.skill for c in trace.tool_calls] == ['case_assistant']
        assert not trace.retrieval and not response.citations and not response.case_references
        assert trace.understanding['subtasks'][0]['input_kind'] == 'user_text'
        assert json.loads(model.calls[-1][-1].content)['question'] == QUERY
        assert response.usage.total_tokens == 15 * len(model.calls)
        if semantic and initial_scope == 'outside':
            reviews = trace.understanding['semantic']['scope_reviews']
            assert reviews[0]['domain_scope'] == 'supported' and reviews[0]['status'] == 'reviewed'
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('question', ['土壤肥力下降的具体百分比是多少？', '这里的移民究竟损失了多少千克氮？'])
async def test_missing_data_uses_same_source_only_path(question):
    query = '只根据资料回答，没有数据说无法确定。\n资料：' + PASSAGE + '\n问题：' + question
    model = Model(initial_scope='supported', answer='资料未提供相关数据，无法确定。')
    runtime = AgentRuntime(semantic_query=SemanticQuery(model), web=ForbiddenWeb())
    try:
        response = await runtime.execute(ChatRequest(query=query), service=None, get_report=None, llm=model)
        assert response.answer == model.answer
        assert json.loads(model.calls[-1][-1].content)['question'] == query
        assert response.retrieved_count == 0
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('rewrite', [None, '黑洞形成原因'])
async def test_agricultural_wrapper_cannot_allow_an_actual_unrelated_question(rewrite):
    query = '这是农田土壤管理任务。只根据资料回答。\n资料：土壤肥力下降；杂草入侵。黑洞由恒星坍缩形成。\n问题：2024年的材料如何解释黑洞形成？'
    model = Model(review_scope='outside', rewrite=rewrite)
    runtime = AgentRuntime(semantic_query=SemanticQuery(model), web=ForbiddenWeb())
    try:
        response = await runtime.execute(ChatRequest(query=query), service=None, get_report=None, llm=model)
        assert response.answer == OUTSIDE_DOMAIN_ANSWER
        assert response.route == 'out_of_scope'
        assert len(model.calls) == 2  # Interpretation and full-question scope review; no answer call.
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_failed_scope_review_does_not_trust_a_rejected_rewrite():
    model = Model(rewrite='亚马孙移民的种植困难', review_error=True)
    result = await SemanticQuery(model).interpret(parse(QUERY), [], [])
    assert result['rewrites'][0]['status'] == 'rejected_scope_change'
    assert result['subtasks'][0]['domain_scope'] == 'unknown'
    assert result['scope_reviews'][0]['status'] == 'unavailable'
    assert result['subtasks'][0]['semantic_query'] == QUERY
