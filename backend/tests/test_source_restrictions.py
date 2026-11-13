"""Source limits hold across languages, retrieval gaps and later turns."""
import pytest

from src.agent.chat_service import ChatService, RAGQueryError
from src.agent.concept_intent import local_only
from src.agent.prompt import DialogueTurn
from src.agent.runtime import AgentRuntime
from src.api.chat_schema import ChatRequest
from src.llm.base import ChatResult, ChatUsage
from tests.test_chat_service import FakeRetriever, _result
from tests.test_provided_text import ForbiddenWeb


@pytest.mark.parametrize('query', [
    'Explain photosynthesis using only local materials.',
    'Use only the uploaded document.',
    'Answer based only on the provided text.',
    'Rely exclusively on supplied sources.',
    'Use local documents only.',
    'Do not use general knowledge or the web.',
    "Don't use external sources.",
    'No web search.',
    'Do not search online.',
    'Search only within the local corpus.',
    '请只用本地材料。',
])
def test_source_restrictions_are_recognized(query):
    assert local_only(query)


@pytest.mark.parametrize('permission', [
    'You may search online now.', 'Allow general knowledge.',
    'Remove the source restriction.', '现在可以补充一般知识。',
])
def test_user_can_explicitly_lift_a_previous_source_restriction(permission):
    history = [DialogueTurn(role='user', content='Use only local materials.'),
               DialogueTurn(role='assistant', content='Do not use external sources.')]
    assert local_only('Explain photosynthesis.', history)
    assert not local_only(permission, history)


def test_ordinary_requests_and_assistant_text_do_not_set_a_source_limit():
    assert not local_only('Explain only one example of photosynthesis.')
    assert not local_only('Explain photosynthesis.', [
        DialogueTurn(role='assistant', content='Use only local materials.')])


@pytest.mark.asyncio
@pytest.mark.parametrize('retrieval', ['unconfigured', 'empty', 'failed'])
@pytest.mark.parametrize('query', [
    'Explain photosynthesis using only local materials.',
    'Use only local sources to describe nitrate leaching research.',
])
async def test_missing_local_evidence_never_generates_general_knowledge_or_searches_web(retrieval, query):
    class ForbiddenModel:
        async def chat(self, *args, **kwargs):
            raise AssertionError('A source-only evidence gap must not invoke generation or translation')

    model = ForbiddenModel()
    retriever = FakeRetriever([], error=RAGQueryError('test failure') if retrieval == 'failed' else None)
    service = ChatService(retriever, model, top_k=5, max_context_chars=4000,
                          temperature=0) if retrieval != 'unconfigured' else None
    runtime = AgentRuntime(web=ForbiddenWeb())
    try:
        response = await runtime.execute(ChatRequest(query=query), service=service,
                                         get_report=None, llm=model)
        assert response.outcome == 'clarification'
        assert not response.citations and response.usage.total_tokens == 0
        assert 'materials' in response.answer
    finally:
        runtime.runs.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [
    'Explain photosynthesis using only local materials.',
    'Use only local sources to describe nitrate leaching research.',
])
async def test_available_local_evidence_still_supports_a_source_only_answer(query):
    text = 'Photosynthesis uses light energy. Nitrate can move downward with water.'

    class GroundedModel:
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert text in messages[0].content
            assert '本次仅允许使用提供的材料，不补充一般知识' in messages[0].content
            return ChatResult(content='The supplied material describes the process. [1]', model='fixture',
                              usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))

    model = GroundedModel()
    service = ChatService(FakeRetriever([_result(1, text)]), model,
                          top_k=5, max_context_chars=4000, temperature=0)
    runtime = AgentRuntime(web=ForbiddenWeb())
    try:
        response = await runtime.execute(ChatRequest(query=query), service=service, get_report=None, llm=model)
        assert response.outcome == 'complete' and model.calls == 1
        assert len(response.citations) == 1 and response.citations[0].snippet == text
        assert response.web_retrieval['status'] == 'restricted'
    finally:
        runtime.runs.close()
