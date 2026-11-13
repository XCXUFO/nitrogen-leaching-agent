"""Service scope must not expand when unrelated answers exist in the corpus."""
import json

import pytest

from src.agent.chat_service import ChatService
from src.agent.contracts import Route
from src.agent.domain_scope import DOMAIN_GUIDANCE_ANSWER, DOMAIN_INSTRUCTIONS, OUTSIDE_DOMAIN_ANSWER
from src.agent.domain_scope import DOMAIN_GUIDANCE_ANSWER_EN
from src.agent.prompt import build_messages
from src.agent.routing import decide
from src.agent.runtime import AgentRuntime
from src.agent.semantic_query import SemanticQuery
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage
from src.rag.retriever import RetrievalResult
from tests.test_chat_service import FakeLLMClient, FakeRetriever


@pytest.mark.parametrize("query", [
    "解释下动能定理", "请推导动能定理", "根据上传资料解释动能定理",
    "文献里有动能定理，请回答", "Explain the work-energy theorem",
    "帮我讲个笑话", "请推荐电影",
    "明天吃啥", "今天吃什么？", "今晚吃点什么好", "中午吃点啥", "早餐推荐一下",
    "帮我安排一周食谱", "给我推荐几道家常菜", "怎么搭配饮食", "玉米怎么做好吃",
    "What should I eat tomorrow?", "Suggest a dinner recipe",
    "前面谈的是土壤中的氮素，明天我吃什么？",
    "你妈是谁", "你妈妈叫什么名字", "你的父母是谁？", "你有兄弟姐妹吗？", "Who is your mother?",
])
def test_unrelated_requests_route_outside_the_domain(query):
    decision = decide(query, has_file=True)
    assert decision.route == Route.OUT_OF_SCOPE
    assert decision.skills == ["capability_guidance"]


@pytest.mark.parametrize("query", [
    "解释土壤水热平衡", "农田灌溉优化中动态规划怎么用？", "溶解性有机氮迁移方程是什么？",
    "动能定理在土壤侵蚀分析中的适用性如何？", "土壤水流中的能量守恒是什么？",
    "土壤微生物吃什么？", "玉米吃什么肥料？", "农田水氮管理能做什么？",
    "土壤氮素淋失研究要做什么？", "土壤微生物的营养来源是什么？",
])
def test_related_principles_stay_in_scope(query):
    assert decide(query, has_file=False).route == Route.KNOWLEDGE


@pytest.mark.asyncio
@pytest.mark.parametrize("task_scope", ["knowledge_search", "concept_explanation"])
async def test_answer_is_rejected_even_when_evidence_contains_the_answer(task_scope):
    evidence = RetrievalResult(chunk_id="physics", document="动能定理：合外力做功等于动能的变化。",
                               score=1, metadata={"source": "physics.txt"})
    retriever = FakeRetriever([evidence])
    llm = FakeLLMClient("合外力做功等于动能变化。[1]")
    service = ChatService(retriever, llm, top_k=6, max_context_chars=1000, temperature=0)
    result = await service.answer("解释下动能定理", task_scope=task_scope,
        session_documents=[{"filename": "physics.txt", "text": evidence.document}], allow_general_knowledge=True)
    assert result.answer == OUTSIDE_DOMAIN_ANSWER
    assert not result.citations and result.retrieved_count == 0
    assert not retriever.calls and llm.last_messages is None


class ForbiddenWeb:
    @property
    def ready(self):
        raise AssertionError("outside-domain reply must not inspect web availability")


def forbidden(*args, **kwargs):
    raise AssertionError("outside-domain reply must not retrieve evidence or generate answers")


class ForbiddenSemantic:
    async def interpret(self, *args, **kwargs):
        raise AssertionError("greetings and bare numbers must not enter semantic clarification")


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["1", "123", "你好", "晚上好", "晚上好！", "早上好", "Good evening", "？", "?", "？？？", "？！", "...", "……", "👏"])
async def test_inputs_without_a_task_offer_domain_examples_without_clarification(query):
    runtime = AgentRuntime(semantic_query=ForbiddenSemantic(), web=ForbiddenWeb())
    try:
        response = await runtime.execute(ChatRequest(query=query, file_id="expired-token"), service=None,
            get_report=forbidden, taxonomy_provider=forbidden, starred_provider=forbidden)
        trace = runtime.runs.get(response.run_id)
        assert response.route == "direct" and response.agent_route == Route.DIRECT
        if query == "Good evening":
            assert response.answer == "Good evening! " + DOMAIN_GUIDANCE_ANSWER_EN
        else:
            assert "农田氮素淋失与农田水氮管理领域的智能体助手" in response.answer
            assert "发生机理和影响因素" in response.answer and "作物养分吸收" in response.answer
            assert "你可以这样问我" in response.answer
            assert "灌溉和施肥怎样影响氮素淋失" in response.answer
        assert response.answer.count("\n- ") >= 3
        assert "请说明您具体" not in response.answer and "需要咨询或了解什么" not in response.answer
        if query.startswith("晚上好"):
            assert response.answer.startswith("晚上好！")
        assert response.usage.total_tokens == 0 and not response.citations and not trace.retrieval
        assert trace.understanding["semantic"]["status"] == "skipped"
        assert [call.skill for call in trace.tool_calls] == ["capability_guidance"]
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("specified", [False, True])
@pytest.mark.parametrize("query", ["解释下动能定理", "明天吃啥", "帮我推荐一周食谱", "你妈是谁"])
async def test_runtime_rejects_before_reuse_retrieval_or_forced_case_execution(specified, query):
    runtime = AgentRuntime(web=ForbiddenWeb())
    try:
        body = ChatRequest(query=query, file_id="expired-token",
                           history=[{"role": "user", "content": "解释一下土壤水氮管理"},
                                    {"role": "assistant", "content": "土壤水氮管理包括灌溉与施肥。"}],
                           **({"case_skill": "explain"} if specified else {}))
        response = await runtime.execute(body, service=None, get_report=forbidden,
            taxonomy_provider=forbidden, starred_provider=forbidden)
        trace = runtime.runs.get(response.run_id)
        assert response.answer == OUTSIDE_DOMAIN_ANSWER
        assert response.route == "out_of_scope" and response.agent_route == Route.OUT_OF_SCOPE
        assert not response.citations and not response.evidence and not response.file_evidence
        assert trace.starred_match["reason"] == "outside_supported_domain"
        assert [call.skill for call in trace.tool_calls] == ["capability_guidance"]
    finally:
        runtime.runs.close()


class ScopeModel:
    def __init__(self, *, scope="outside", clarification=""):
        self.scope, self.clarification = scope, clarification

    async def chat(self, messages, **kwargs):
        payload = json.loads(messages[-1].content)
        assert "tasks" in payload, "unrelated questions must not be reviewed for starred coverage"
        return ChatResult(content=json.dumps({"tasks": [
            {"subtask_id": task["subtask_id"], "intent": "knowledge", "domain_scope": self.scope,
             "input_kind": "literature", "resolved_query": task["query"], "retrieval_query": task["query"],
             "intent_description": "独立的天体物理问题", "clarification": self.clarification}
            for task in payload["tasks"]]}, ensure_ascii=False), model="scope-test",
            usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15))


@pytest.mark.asyncio
@pytest.mark.parametrize("clarification", ["", "请明确想了解哪类天体物理知识。"])
@pytest.mark.parametrize("question", ["解释下黑洞的形成", "今天我的运势怎么样"])
async def test_semantic_scope_rejects_an_unlisted_topic_before_reusing_an_existing_answer(clarification, question):
    runtime = AgentRuntime(semantic_query=SemanticQuery(ScopeModel(clarification=clarification)), web=ForbiddenWeb())
    try:
        response = await runtime.execute(ChatRequest(query=question), service=None, get_report=forbidden,
            starred_provider=lambda: [{"question_id": "unrelated", "question": question, "answer": "已有天体物理答案"}])
        trace = runtime.runs.get(response.run_id)
        assert response.answer == OUTSIDE_DOMAIN_ANSWER
        assert response.usage.total_tokens == 15
        assert trace.understanding["subtasks"][0]["domain_scope"] == "outside"
        assert trace.starred_match["adopted"] == [] and not trace.retrieval
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
async def test_uncertain_domain_cannot_send_an_unrelated_clarification_to_the_user():
    unrelated = "请明确想了解哪类饮食建议（如家常菜、营养搭配、地区口味等）。"
    runtime = AgentRuntime(semantic_query=SemanticQuery(ScopeModel(scope="unknown", clarification=unrelated)))
    try:
        response = await runtime.execute(ChatRequest(query="给我一些建议"), service=None, get_report=forbidden)
        assert response.route == "clarification"
        assert "农田氮素淋失与农田水氮管理领域" in response.answer
        assert response.answer == DOMAIN_GUIDANCE_ANSWER
        assert unrelated not in response.answer
        assert not response.citations
    finally:
        runtime.runs.close()


@pytest.mark.parametrize("task_scope,general", [("knowledge_search", False), ("knowledge_search", True), ("concept_explanation", False)])
@pytest.mark.parametrize("with_context", [False, True])
def test_every_answer_prompt_keeps_domain_identity_before_evidence_rules(task_scope, general, with_context):
    hits = [RetrievalResult(chunk_id="1", document="研究正文", score=1, metadata={"source": "paper.txt"})] if with_context else []
    messages = build_messages("问题", hits, max_context_chars=1000, task_scope=task_scope, allow_general_knowledge=general)
    assert messages[0].content.startswith(DOMAIN_INSTRUCTIONS)
