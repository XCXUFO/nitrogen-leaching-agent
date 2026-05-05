from pydantic import ValidationError
import pytest

from src.agent.chat_service import Citation
from src.api.chat_schema import ChatRequest, ChatResponse
from src.llm.base import ChatUsage


def test_chat_request_query_required() -> None:
    with pytest.raises(ValidationError):
        ChatRequest.model_validate({})


def test_chat_request_query_must_not_be_blank() -> None:
    with pytest.raises(ValidationError):
        ChatRequest(query="   \n\t")


def test_chat_request_query_max_length() -> None:
    ChatRequest(query="x" * 1000)
    with pytest.raises(ValidationError):
        ChatRequest(query="x" * 1001)


def test_chat_request_strips_query() -> None:
    request = ChatRequest(query="  氮素淋失  ")
    assert request.query == "氮素淋失"


def test_chat_request_k_optional_and_bounded() -> None:
    assert ChatRequest(query="q").k is None
    assert ChatRequest(query="q", k=5).k == 5
    for k in (0, 21):
        with pytest.raises(ValidationError):
            ChatRequest(query="q", k=k)


def test_chat_request_session_id_optional() -> None:
    assert ChatRequest(query="q").session_id is None
    assert ChatRequest(query="q", session_id="s1").session_id == "s1"


def test_citation_index_must_be_positive() -> None:
    Citation(index=1, chunk_id="c1", source="s", score=0.9, snippet="x")
    with pytest.raises(ValidationError):
        Citation(index=0, chunk_id="c1", source="s", score=0.9, snippet="x")


def test_chat_response_serializes_citations() -> None:
    response = ChatResponse(
        answer="answer",
        citations=[Citation(index=1, chunk_id="c1", source="s", score=0.9, snippet="x")],
        usage=ChatUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
        retrieved_count=1,
        model="fake-model",
    )

    body = response.model_dump()
    assert body["citations"][0]["chunk_id"] == "c1"
    assert body["usage"]["total_tokens"] == 3
