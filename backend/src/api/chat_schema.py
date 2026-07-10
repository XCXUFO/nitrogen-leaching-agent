from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.agent.chat_service import Citation
from src.llm.base import ChatUsage


class ChatHistoryMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1, max_length=4000)

    @field_validator("content")
    @classmethod
    def strip_and_validate_content(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("history content must not be blank")
        return stripped


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=20)
    session_id: str | None = None
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=12)

    @field_validator("query")
    @classmethod
    def strip_and_validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped

    @model_validator(mode="after")
    def trim_history_to_previous_turns(self) -> "ChatRequest":
        # The active query is sent separately. If a client accidentally includes
        # it as the last history item, keep the API forgiving but deterministic.
        if (
            self.history
            and self.history[-1].role == "user"
            and self.history[-1].content == self.query
        ):
            self.history = self.history[:-1]
        return self


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    usage: ChatUsage
    retrieved_count: int = Field(..., ge=0)
    model: str
