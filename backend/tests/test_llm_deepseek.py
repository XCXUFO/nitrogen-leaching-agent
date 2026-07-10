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


def test_client_forwards_timeout_and_max_retries():
    # M1.5-a DoD #2: 断「透传生效」而非策略值——用非默认值构造，验证传入的
    # timeout/max_retries 确实落到底层 AsyncOpenAI（不硬编 60/2）。
    client = DeepSeekClient(
        api_key="x",
        base_url="https://example",
        model="deepseek-chat",
        timeout_s=42.0,
        max_retries=5,
    )

    assert client._client.timeout == 42.0
    assert client._client.max_retries == 5


def test_client_ignores_malformed_proxy_env(monkeypatch):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:\n7890")

    client = DeepSeekClient(
        api_key="x",
        base_url="https://example",
        model="deepseek-chat",
    )

    assert client._client is not None
