from __future__ import annotations

import threading

import pytest

from src.agent.chat_service import ChatService, RAGQueryError
from src.llm.base import ChatMessage, ChatResult, ChatUsage, LLMClient
from src.rag.retriever import RetrievalResult


class FakeRetriever:
    def __init__(
        self,
        results: list[RetrievalResult],
        *,
        error: Exception | None = None,
    ) -> None:
        self._results = results
        self._error = error
        self.calls: list[tuple[str, int]] = []
        self.thread_ids: list[int] = []

    def retrieve(self, query: str, k: int) -> list[RetrievalResult]:
        self.calls.append((query, k))
        self.thread_ids.append(threading.get_ident())
        if self._error is not None:
            raise self._error
        return self._results[:k]


class FakeLLMClient(LLMClient):
    def __init__(
        self,
        content: str = "fake answer",
        *,
        error: Exception | None = None,
    ) -> None:
        self._content = content
        self._error = error
        self.last_messages: list[ChatMessage] | None = None
        self.last_temperature: float | None = None

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult:
        self.last_messages = messages
        self.last_temperature = temperature
        if self._error is not None:
            raise self._error
        return ChatResult(
            content=self._content,
            model="fake-model",
            usage=ChatUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )


def _result(index: int, document: str | None = None) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=f"c{index}",
        document=document or f"document {index}",
        score=0.9,
        metadata={"source": f"paper-{index}.txt"},
    )


@pytest.mark.asyncio
async def test_answer_uses_top_k_default_when_k_none() -> None:
    retriever = FakeRetriever([_result(1), _result(2)])
    service = ChatService(
        retriever,  # type: ignore[arg-type]
        FakeLLMClient(),
        top_k=2,
        max_context_chars=500,
        temperature=0.3,
    )

    await service.answer("query")

    assert retriever.calls == [("query", 2)]


@pytest.mark.asyncio
async def test_answer_overrides_top_k_when_k_explicit() -> None:
    retriever = FakeRetriever([_result(1), _result(2), _result(3)])
    service = ChatService(
        retriever,  # type: ignore[arg-type]
        FakeLLMClient(),
        top_k=5,
        max_context_chars=500,
        temperature=0.3,
    )

    await service.answer("query", k=3)

    assert retriever.calls == [("query", 3)]


@pytest.mark.asyncio
async def test_answer_passes_temperature_to_llm() -> None:
    llm = FakeLLMClient()
    service = ChatService(
        FakeRetriever([_result(1)]),  # type: ignore[arg-type]
        llm,
        top_k=1,
        max_context_chars=500,
        temperature=0.7,
    )

    await service.answer("query")

    assert llm.last_temperature == 0.7


@pytest.mark.asyncio
async def test_answer_returns_citations_for_each_retrieved() -> None:
    service = ChatService(
        FakeRetriever([_result(1), _result(2), _result(3)]),  # type: ignore[arg-type]
        FakeLLMClient(),
        top_k=3,
        max_context_chars=500,
        temperature=0.3,
    )

    result = await service.answer("query")

    assert [c.index for c in result.citations] == [1, 2, 3]
    assert [c.chunk_id for c in result.citations] == ["c1", "c2", "c3"]
    assert result.retrieved_count == 3


@pytest.mark.asyncio
async def test_answer_snippet_truncates_to_100_chars() -> None:
    service = ChatService(
        FakeRetriever([_result(1, document="x" * 200)]),  # type: ignore[arg-type]
        FakeLLMClient(),
        top_k=1,
        max_context_chars=500,
        temperature=0.3,
    )

    result = await service.answer("query")

    assert len(result.citations[0].snippet) == 100


@pytest.mark.asyncio
async def test_answer_handles_empty_retrieval() -> None:
    llm = FakeLLMClient()
    service = ChatService(
        FakeRetriever([]),  # type: ignore[arg-type]
        llm,
        top_k=5,
        max_context_chars=500,
        temperature=0.3,
    )

    result = await service.answer("query")

    assert result.citations == []
    assert result.retrieved_count == 0
    assert llm.last_messages is not None
    assert "未检索到相关参考资料" in llm.last_messages[0].content


@pytest.mark.asyncio
async def test_answer_propagates_llm_exceptions() -> None:
    service = ChatService(
        FakeRetriever([_result(1)]),  # type: ignore[arg-type]
        FakeLLMClient(error=RuntimeError("llm failed")),
        top_k=1,
        max_context_chars=500,
        temperature=0.3,
    )

    with pytest.raises(RuntimeError, match="llm failed"):
        await service.answer("query")


@pytest.mark.asyncio
async def test_answer_wraps_retriever_exceptions() -> None:
    service = ChatService(
        FakeRetriever([], error=RuntimeError("store failed")),  # type: ignore[arg-type]
        FakeLLMClient(),
        top_k=1,
        max_context_chars=500,
        temperature=0.3,
    )

    with pytest.raises(RAGQueryError):
        await service.answer("query")


@pytest.mark.asyncio
async def test_answer_runs_retriever_in_thread() -> None:
    main_thread_id = threading.get_ident()
    retriever = FakeRetriever([_result(1)])
    service = ChatService(
        retriever,  # type: ignore[arg-type]
        FakeLLMClient(),
        top_k=1,
        max_context_chars=500,
        temperature=0.3,
    )

    await service.answer("query")

    assert retriever.thread_ids
    assert retriever.thread_ids[0] != main_thread_id
