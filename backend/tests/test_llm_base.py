import pytest

from src.llm import ChatMessage, ChatResult, ChatUsage, LLMClient


def test_llm_client_cannot_be_instantiated_without_chat():
    with pytest.raises(TypeError):
        LLMClient()  # type: ignore[abstract]


def test_chat_message_validates_role():
    with pytest.raises(ValueError):
        ChatMessage(role="developer", content="hi")  # type: ignore[arg-type]


def test_fake_llm_client_satisfies_contract():
    class FakeLLMClient(LLMClient):
        async def chat(self, messages, *, temperature=0.3, max_tokens=None):
            return ChatResult(
                content="ok",
                model="fake-1",
                usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2),
            )

    client = FakeLLMClient()
    assert isinstance(client, LLMClient)
