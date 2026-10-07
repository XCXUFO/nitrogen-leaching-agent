import httpx
from openai import AsyncOpenAI

from src.llm.base import ChatMessage, ChatResult, ChatUsage, LLMClient


class DeepSeekClient(LLMClient):
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model: str,
        *,
        timeout_s: float = 60.0,
        max_retries: int = 2,
        proxy: str | None = None,
        output_token_limit: int | None = None,
    ) -> None:
        # 运行时权威值来自 Settings（config.py）→ main.py 显式传入；这里的默认仅
        # 作为直接构造（脚本/测试）时的安全兜底，不再吃 SDK 的 600s 默认超时。
        # Demo 环境里常见代理变量被终端/IDE 注入；这里关闭 env proxy 继承，避免
        # malformed HTTP(S)_PROXY 让后端在构造 client 阶段直接启动失败。
        # Only use an explicitly configured proxy; malformed shell proxy values
        # must still be ignored when a proxy is needed for the upstream API.
        http_client = httpx.AsyncClient(trust_env=False, proxy=proxy or None)
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout_s,
            max_retries=max_retries,
            http_client=http_client,
        )
        self._model = model
        self._output_token_limit = output_token_limit

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
        if self._output_token_limit is not None:
            max_tokens = min(max_tokens or self._output_token_limit, self._output_token_limit)
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
