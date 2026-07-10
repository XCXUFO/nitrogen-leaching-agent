from __future__ import annotations

import httpx
from fastapi import FastAPI
from openai import APIConnectionError, APITimeoutError
import pytest

from src.agent.chat_service import ChatServiceResult, Citation, RAGQueryError
from src.agent.prompt import DialogueTurn
from src.api import chat
from src.llm.base import ChatUsage


class FakeChatService:
    def __init__(self, *, error: Exception | None = None) -> None:
        self._error = error
        self.calls: list[tuple[str, int | None, list[DialogueTurn]]] = []

    async def answer(
        self,
        query: str,
        k: int | None = None,
        *,
        history: list[DialogueTurn] | None = None,
    ) -> ChatServiceResult:
        self.calls.append((query, k, history or []))
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


async def _post(
    app: FastAPI,
    payload: dict[str, object],
    *,
    raise_app_exceptions: bool = True,
) -> httpx.Response:
    transport = httpx.ASGITransport(
        app=app,
        raise_app_exceptions=raise_app_exceptions,
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        return await client.post("/api/chat", json=payload)


@pytest.mark.asyncio
async def test_chat_503_when_service_none() -> None:
    app = _app_with_service(None)

    response = await _post(app, {"query": "q"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_not_configured"


@pytest.mark.asyncio
async def test_chat_200_happy_path() -> None:
    service = FakeChatService()
    app = _app_with_service(service)

    response = await _post(app, {"query": "  q  ", "k": 3})

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "fake answer"
    assert body["citations"][0]["chunk_id"] == "c1"
    assert body["usage"]["total_tokens"] == 3
    assert service.calls == [("q", 3, [])]


@pytest.mark.asyncio
async def test_chat_200_passes_history() -> None:
    service = FakeChatService()
    app = _app_with_service(service)

    response = await _post(
        app,
        {
            "query": "那侧向渗漏贡献多少？",
            "history": [
                {"role": "user", "content": "湖北荆州稻田地下径流"},
                {"role": "assistant", "content": "地下径流约为地表径流 2 倍"},
            ],
        },
    )

    assert response.status_code == 200
    assert service.calls == [
        (
            "那侧向渗漏贡献多少？",
            None,
            [
                DialogueTurn(role="user", content="湖北荆州稻田地下径流"),
                DialogueTurn(role="assistant", content="地下径流约为地表径流 2 倍"),
            ],
        )
    ]


@pytest.mark.asyncio
async def test_chat_422_when_query_missing() -> None:
    app = _app_with_service(FakeChatService())

    response = await _post(app, {})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_422_when_query_too_long() -> None:
    app = _app_with_service(FakeChatService())

    response = await _post(app, {"query": "x" * 1001})

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_422_when_k_out_of_range() -> None:
    app = _app_with_service(FakeChatService())

    assert (await _post(app, {"query": "q", "k": 0})).status_code == 422
    assert (await _post(app, {"query": "q", "k": 21})).status_code == 422


@pytest.mark.asyncio
async def test_chat_503_on_rag_query_error() -> None:
    app = _app_with_service(FakeChatService(error=RAGQueryError("boom")))

    response = await _post(app, {"query": "q"})

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_query_failed"


@pytest.mark.asyncio
async def test_chat_502_on_llm_connection_error() -> None:
    error = APIConnectionError(
        message="network down",
        request=httpx.Request("POST", "https://example.test"),
    )
    app = _app_with_service(FakeChatService(error=error))

    response = await _post(app, {"query": "q"})

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "llm_unreachable"


@pytest.mark.asyncio
async def test_chat_504_on_llm_timeout() -> None:
    # M1.5-a 场景 B：第 2 步的有界超时触顶 → 明确 504 llm_timeout，
    # 不被误归为 llm_unreachable（APITimeoutError 是 APIConnectionError 子类）。
    error = APITimeoutError(request=httpx.Request("POST", "https://example.test"))
    app = _app_with_service(FakeChatService(error=error))

    response = await _post(app, {"query": "q"})

    assert response.status_code == 504
    assert response.json()["detail"]["code"] == "llm_timeout"


@pytest.mark.asyncio
async def test_chat_500_on_unexpected_error_stays_controlled() -> None:
    # M1.5-a 场景 B：未预期异常也走稳定契约（前端始终拿得到 code），不裸崩，
    # 且不把内部异常细节回显给前端（防泄露），完整异常只进日志。
    app = _app_with_service(
        FakeChatService(error=RuntimeError("boom: /secret/path"))
    )

    response = await _post(app, {"query": "q"}, raise_app_exceptions=False)

    assert response.status_code == 500
    detail = response.json()["detail"]
    assert detail["code"] == "internal_error"
    assert detail["message"] == "服务内部异常，请稍后重试"
    assert "boom" not in detail["message"]
    assert "/secret/path" not in detail["message"]
