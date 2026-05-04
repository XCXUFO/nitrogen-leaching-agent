from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.llm import ChatMessage, DeepSeekClient


def _make_response(content: str | None, model: str = "deepseek-chat"):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        model=model,
        usage=SimpleNamespace(
            prompt_tokens=10, completion_tokens=20, total_tokens=30
        ),
    )


@pytest.mark.asyncio
async def test_chat_maps_response_into_chat_result(monkeypatch):
    client = DeepSeekClient(api_key="x", base_url="https://example", model="deepseek-chat")
    create_mock = AsyncMock(return_value=_make_response("hello"))
    monkeypatch.setattr(client._client.chat.completions, "create", create_mock)

    result = await client.chat(
        [ChatMessage(role="user", content="hi")],
        temperature=0.5,
        max_tokens=128,
    )

    assert result.content == "hello"
    assert result.model == "deepseek-chat"
    assert result.usage.prompt_tokens == 10
    assert result.usage.completion_tokens == 20
    assert result.usage.total_tokens == 30

    create_mock.assert_awaited_once_with(
        model="deepseek-chat",
        messages=[{"role": "user", "content": "hi"}],
        temperature=0.5,
        max_tokens=128,
    )


@pytest.mark.asyncio
async def test_chat_treats_none_content_as_empty_string(monkeypatch):
    client = DeepSeekClient(api_key="x", base_url="https://example", model="deepseek-chat")
    monkeypatch.setattr(
        client._client.chat.completions,
        "create",
        AsyncMock(return_value=_make_response(None)),
    )

    result = await client.chat([ChatMessage(role="user", content="hi")])

    assert result.content == ""


@pytest.mark.asyncio
async def test_chat_omits_max_tokens_when_not_provided(monkeypatch):
    client = DeepSeekClient(api_key="x", base_url="https://example", model="deepseek-chat")
    create_mock = AsyncMock(return_value=_make_response("hello"))
    monkeypatch.setattr(client._client.chat.completions, "create", create_mock)

    await client.chat([ChatMessage(role="user", content="hi")])

    assert "max_tokens" not in create_mock.await_args.kwargs
