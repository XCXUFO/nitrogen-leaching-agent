from __future__ import annotations

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openai import APIConnectionError

from src.agent.chat_service import ChatServiceResult, Citation, RAGQueryError
from src.api import chat
from src.llm.base import ChatUsage


class FakeChatService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[tuple[str, int | None]] = []

    async def answer(self, query: str, k: int | None = None) -> ChatServiceResult:
        self.calls.append((query, k))
        if self._error is not None:
            raise self._error
        return ChatServiceResult(
            answer="fake answer",
            citations=[
                Citation(
                    index=1,
                    chunk_id="c1",
                    source="paper.txt",
                    score=0.9,
                    snippet="snippet",
                )
            ],
            usage=ChatUsage(prompt_tokens=1, completion_tokens=2, total_tokens=3),
            retrieved_count=1,
            model="fake-model",
        )


def _app_with_service(service: object | None) -> FastAPI:
    app = FastAPI()
    app.state.chat_service = service
    app.include_router(chat.router, prefix="/api")
    return app


def test_chat_503_when_service_none() -> None:
    client = TestClient(_app_with_service(None))

    response = client.post("/api/chat", json={"query": "q"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_not_configured"


def test_chat_200_happy_path() -> None:
    service = FakeChatService()
    client = TestClient(_app_with_service(service))

    response = client.post("/api/chat", json={"query": "  q  ", "k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "fake answer"
    assert body["citations"][0]["chunk_id"] == "c1"
    assert body["usage"]["total_tokens"] == 3
    assert service.calls == [("q", 3)]


def test_chat_422_when_query_missing() -> None:
    client = TestClient(_app_with_service(FakeChatService()))

    response = client.post("/api/chat", json={})

    assert response.status_code == 422


def test_chat_422_when_query_too_long() -> None:
    client = TestClient(_app_with_service(FakeChatService()))

    response = client.post("/api/chat", json={"query": "x" * 1001})

    assert response.status_code == 422


def test_chat_422_when_k_out_of_range() -> None:
    client = TestClient(_app_with_service(FakeChatService()))

    assert client.post("/api/chat", json={"query": "q", "k": 0}).status_code == 422
    assert client.post("/api/chat", json={"query": "q", "k": 21}).status_code == 422


def test_chat_503_on_rag_query_error() -> None:
    client = TestClient(_app_with_service(FakeChatService(error=RAGQueryError("boom"))))

    response = client.post("/api/chat", json={"query": "q"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_query_failed"


def test_chat_502_on_llm_connection_error() -> None:
    error = APIConnectionError(
        message="network down",
        request=httpx.Request("POST", "https://example.test"),
    )
    client = TestClient(_app_with_service(FakeChatService(error=error)))

    response = client.post("/api/chat", json={"query": "q"})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "llm_unreachable"
