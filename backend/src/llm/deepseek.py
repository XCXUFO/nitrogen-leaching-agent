from openai import AsyncOpenAI

from src.llm.base import ChatMessage, ChatResult, ChatUsage, LLMClient


class DeepSeekClient(LLMClient):
    def __init__(self, api_key: str, base_url: str, model: str) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult:
        request_kwargs = {
            "model": self._model,
            "messages": [m.model_dump() for m in messages],
            "temperature": temperature,
        }
        if max_tokens is not None:
            request_kwargs["max_tokens"] = max_tokens

        response = await self._client.chat.completions.create(**request_kwargs)
        choice = response.choices[0]
        return ChatResult(
            content=choice.message.content or "",
            model=response.model,
            usage=ChatUsage(
                prompt_tokens=response.usage.prompt_tokens,
                completion_tokens=response.usage.completion_tokens,
                total_tokens=response.usage.total_tokens,
            ),
        )
