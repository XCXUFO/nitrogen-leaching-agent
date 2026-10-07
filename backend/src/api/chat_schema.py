from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.agent.chat_service import Citation
from src.agent.contracts import AnswerSection, AttachmentState, Evidence, Route, RunWarning
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
    session_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    operator_id: str | None = Field(default=None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    file_id: str | None = Field(default=None, min_length=1, max_length=100)
    file_ids: list[str] | None = Field(default=None, max_length=5)
    history: list[ChatHistoryMessage] = Field(default_factory=list, max_length=12)

    @field_validator("file_ids")
    @classmethod
    def validate_file_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is not None and any(not token or len(token) > 100 for token in value):
            raise ValueError("invalid file token")
        return value

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


class FileEvidence(BaseModel):
    filename: str
    sha256: str
    sheet: str
    field: str
    unit: str
    operation: Literal["min", "max"]
    value: float
    model_day: int
    cell: str
    day_cell: str
    occurrences: int
    data_range: str
    tool_version: str
    schema_id: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    usage: ChatUsage
    retrieved_count: int = Field(..., ge=0)
    model: str
    route: Literal["knowledge", "file", "clarification", "direct", "out_of_scope", "composed"] = "knowledge"
    file_evidence: list[FileEvidence] = Field(default_factory=list)
    run_id: str | None = None
    conversation_id: str | None = None
    agent_route: Route | None = None
    evidence: list[Evidence] = Field(default_factory=list)
    trace_saved: bool = False
    outcome: Literal["complete", "partial", "clarification"] = "complete"
    attachment: AttachmentState | None = None
    attachments: list[AttachmentState] = Field(default_factory=list)
    sections: list[AnswerSection] = Field(default_factory=list)
    warnings: list[RunWarning] = Field(default_factory=list)
