"""Versioned, provider-independent contracts for the bounded agent runtime."""
from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

HARNESS_VERSION = "0.2.0"
SkillName = Literal["knowledge_search", "whcns_analyzer", "file_inspector", "clarification", "capability_guidance"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Route(str, Enum):
    DIRECT = "DIRECT"
    KNOWLEDGE = "KNOWLEDGE"
    FILE_ANALYSIS = "FILE_ANALYSIS"
    COMPOSED = "COMPOSED"
    CLARIFY = "CLARIFY"
    OUT_OF_SCOPE = "OUT_OF_SCOPE"


class RouteDecision(Contract):
    route: Route
    reason_code: str
    skills: list[SkillName] = Field(default_factory=list, max_length=3)


class TaskState(Contract):
    conversation_id: str
    crop: str | None = None
    current_attachment_id: str | None = None
    session_file_ids: list[str] = Field(default_factory=list)
    session_files_enabled: bool = False
    current_metric: str | None = None
    current_operation: list[Literal["min", "max"]] = Field(default_factory=list)
    last_tool: SkillName | None = None
    expires_at: float = 0


class Evidence(Contract):
    evidence_id: str
    source_type: Literal["file", "literature"]
    source_id: str
    claim_or_value: str | float
    unit: str | None = None
    location: dict[str, str | int] = Field(default_factory=dict)
    provenance: dict[str, str] = Field(default_factory=dict)
    # A retrieved passage is not an assertion that it supports the whole answer.
    status: Literal["computed", "retrieved", "curated"]


class ToolCall(Contract):
    skill: SkillName
    status: Literal["ok", "clarification", "error", "cancelled"]
    latency_ms: int = Field(ge=0)
    error_code: str | None = None


class AttachmentState(Contract):
    file_id: str | None = None
    filename: str
    status: Literal["pending", "ready", "invalid", "expired"]
    rows: int | None = None
    kind: str | None = None


class AnswerSection(Contract):
    kind: Literal["file_observation", "literature_inference", "limitation"]
    content: str
    citation_indices: list[int] = Field(default_factory=list)
    file_evidence_indices: list[int] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)


class RunWarning(Contract):
    code: str
    message: str


class StateSnapshot(Contract):
    crop: str | None = None
    attachment_ref: str | None = None  # Digest; never persist the bearer file token.
    current_metric: str | None = None
    current_operation: list[Literal["min", "max"]] = Field(default_factory=list)
    last_tool: SkillName | None = None


class RunTrace(Contract):
    schema_version: str = "1"
    harness_version: str = HARNESS_VERSION
    run_id: str
    conversation_ref: str
    started_at: str
    input: str
    history_count: int = 0
    state_before: StateSnapshot
    state_after: StateSnapshot | None = None
    decision: RouteDecision | None = None
    tool_calls: list[ToolCall] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    answer: str | None = None
    model: str | None = None
    config_version: str
    config_manifest: dict = Field(default_factory=dict)
    latency_ms: int = Field(default=0, ge=0)
    status: Literal["running", "ok", "error", "cancelled"] = "running"
    error_code: str | None = None
    outcome: Literal["complete", "partial", "clarification"] | None = None
    warnings: list[RunWarning] = Field(default_factory=list)
    sections: list[AnswerSection] = Field(default_factory=list)


class CaseStep(Contract):
    action: Literal["query", "upload", "remove_attachment", "clear", "refresh", "wait", "manual"]
    instruction: str
    input: str | None = None
    attachment: str | None = None


class EvalCase(Contract):
    case_id: str
    version: int = Field(ge=1)
    category: Literal["A", "K", "F", "B", "X", "O", "NEW"]
    title: str
    steps: list[CaseStep] = Field(min_length=1)
    preconditions: str
    attachment_requirements: list[str] = Field(default_factory=list)
    expected: list[str] = Field(min_length=1)
    priority: Literal["P0", "P1", "P2"]
    source: str
    supersedes: str | None = None


class Review(Contract):
    review_id: str
    case_id: str
    case_version: int = Field(ge=1)
    run_ids: list[str] = Field(min_length=1)
    tester_id: str
    overall: Literal["pass", "partial", "fail", "blocked"]
    route_correct: Literal["yes", "no", "n.a."]
    tool_correct: Literal["yes", "no", "n.a."]
    evidence_correct: Literal["yes", "partial", "no", "n.a."]
    answer_correct: Literal["yes", "partial", "no", "n.a."]
    usability: int = Field(ge=1, le=5)
    tags: list[str] = Field(default_factory=list)
    notes: str = ""
    created_at: str
