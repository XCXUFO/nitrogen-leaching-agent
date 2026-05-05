from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.agent.prompt import build_messages
from src.llm.base import ChatUsage, LLMClient
from src.rag.retriever import RetrievalResult, Retriever

_SNIPPET_LEN = 100


class RAGQueryError(RuntimeError):
    """Raised when retrieval fails before prompt construction."""


class Citation(BaseModel):
    index: int = Field(..., ge=1)
    chunk_id: str
    source: str
    score: float
    snippet: str


@dataclass(frozen=True, slots=True)
class ChatServiceResult:
    answer: str
    citations: list[Citation]
    usage: ChatUsage
    retrieved_count: int
    model: str


class ChatService:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        *,
        top_k: int,
        max_context_chars: int,
        temperature: float,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._top_k = top_k
        self._max_context_chars = max_context_chars
        self._temperature = temperature

    async def answer(self, query: str, k: int | None = None) -> ChatServiceResult:
        effective_k = k if k is not None else self._top_k
        try:
            retrieved = await asyncio.to_thread(
                self._retriever.retrieve,
                query,
                effective_k,
            )
        except Exception as exc:
            raise RAGQueryError("retriever query failed") from exc

        messages = build_messages(
            query,
            retrieved,
            max_context_chars=self._max_context_chars,
        )
        chat = await self._llm.chat(messages, temperature=self._temperature)
        return ChatServiceResult(
            answer=chat.content,
            citations=_make_citations(retrieved),
            usage=chat.usage,
            retrieved_count=len(retrieved),
            model=chat.model,
        )


def _make_citations(retrieved: list[RetrievalResult]) -> list[Citation]:
    return [
        Citation(
            index=index,
            chunk_id=result.chunk_id,
            source=str(result.metadata.get("source", "unknown")),
            score=result.score,
            snippet=result.document[:_SNIPPET_LEN],
        )
        for index, result in enumerate(retrieved, start=1)
    ]
