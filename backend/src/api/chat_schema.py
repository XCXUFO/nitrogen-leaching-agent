from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from src.agent.chat_service import Citation
from src.llm.base import ChatUsage


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1000)
    k: int | None = Field(default=None, ge=1, le=20)
    session_id: str | None = None

    @field_validator("query")
    @classmethod
    def strip_and_validate_query(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("query must not be blank")
        return stripped


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    usage: ChatUsage
    retrieved_count: int = Field(..., ge=0)
    model: str
