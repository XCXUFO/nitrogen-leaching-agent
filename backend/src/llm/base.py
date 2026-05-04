from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel


class ChatUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatResult(BaseModel):
    content: str
    model: str
    usage: ChatUsage


class LLMClient(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.3,
        max_tokens: int | None = None,
    ) -> ChatResult: ...
