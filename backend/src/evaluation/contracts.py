from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator, model_validator

from src.agent.contracts import Contract, EvalCase


class Principal(Contract):
    tester_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    role: Literal["tester", "developer", "reviewer"]


class AccessEntry(Principal):
    token_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class AccessFile(Contract):
    users: list[AccessEntry] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_users_and_keys(self):
        if len({u.tester_id for u in self.users}) != len(self.users) or len({u.token_sha256 for u in self.users}) != len(self.users):
            raise ValueError("identities and access keys must be unique")
        return self


class StartExecution(Contract):
    case_id: str = Field(min_length=1, max_length=80)
    case_version: int = Field(ge=1)
    task_id: str | None = None


class CaseVersion(Contract):
    case_id: str = Field(min_length=1, max_length=80)
    case_version: int = Field(ge=1)


class TaskInput(Contract):
    title: str = Field(min_length=1, max_length=200)
    case_versions: list[CaseVersion] = Field(min_length=1, max_length=50)
    build_version: str = Field(min_length=1, max_length=160)
    knowledge_version: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=3000)

    @model_validator(mode="after")
    def unique_cases(self):
        if len({(c.case_id, c.case_version) for c in self.case_versions}) != len(self.case_versions):
            raise ValueError("task cases must be unique")
        return self


class IssueInput(Contract):
    execution_id: str
    event_sequence: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=200)
    assignee: str = Field(min_length=1, max_length=80)
    evidence_note: str = Field(min_length=1, max_length=3000)


class RetestInput(Contract):
    execution_id: str
    fix_version: str = Field(min_length=1, max_length=160)
    notes: str = Field(default="", max_length=3000)


class IssueUpdateInput(Contract):
    expected_revision: int = Field(ge=1)
    status: Literal["open", "in_progress", "ready_for_retest", "closed"]
    assignee: str = Field(min_length=1, max_length=80)
    note: str = Field(min_length=1, max_length=3000)


class AssessmentInput(Contract):
    case_id: str
    case_version: int = Field(ge=1)
    kind: Literal["ai_assisted", "domain_expert"]
    overall: Literal["pass", "partial", "fail", "blocked"]
    source_path: str = Field(min_length=1, max_length=500)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    notes: str = Field(min_length=1, max_length=5000)
    execution_id: str | None = None


class ReviewAssignmentInput(Contract):
    reviewer_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    note: str = Field(default="", max_length=3000)


class ReviewResolutionInput(Contract):
    assessment_ids: list[str] = Field(min_length=2)
    conclusion: Literal["pass", "partial", "fail", "blocked", "unresolved"]
    rationale: str = Field(min_length=1, max_length=5000)


class AssetInput(Contract):
    kind: Literal["paper", "model_input", "model_output", "result_fixture", "evidence"]
    path: str = Field(min_length=1, max_length=500)
    source: str = Field(min_length=1, max_length=500)
    source_date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    notes: str = Field(default="", max_length=3000)


class AssetPairInput(Contract):
    input_asset_id: str
    output_asset_id: str
    status: Literal["candidate", "verified"]
    evidence_asset_id: str | None = None
    supersedes_pair_id: str | None = None
    notes: str = Field(default="", max_length=3000)


class CaseDraftInput(Contract):
    case: EvalCase
    fixture_asset_ids: list[str] = Field(default_factory=list, max_length=20)
    notes: str = Field(default="", max_length=3000)


class CaseDraftBatchInput(Contract):
    drafts: list[CaseDraftInput] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique_case_versions(self):
        keys = [(item.case.case_id, item.case.version) for item in self.drafts]
        if len(set(keys)) != len(keys):
            raise ValueError("batch draft case versions must be unique")
        return self


class CaseDraftRevision(CaseDraftInput):
    expected_revision: int = Field(ge=1)


class CasePublishInput(Contract):
    expected_revision: int = Field(ge=1)


class RegressionInput(Contract):
    execution_id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    notes: str = Field(default="", max_length=3000)

    @field_validator("title")
    @classmethod
    def title_not_blank(cls, value):
        if not value.strip():
            raise ValueError("title must not be blank")
        return value.strip()


class EvaluationQuery(Contract):
    query: str = Field(min_length=1, max_length=1000)

    @field_validator("query")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("query must not be blank")
        return value.strip()


class ManualAction(Contract):
    action: Literal["clear", "remove_attachment", "manual"]
    note: str = Field(default="", max_length=2000)


class ReviewInput(Contract):
    overall: Literal["pass", "partial", "fail", "blocked"]
    route_correct: Literal["yes", "no", "n.a."]
    tool_correct: Literal["yes", "no", "n.a."]
    evidence_correct: Literal["yes", "partial", "no", "n.a."]
    answer_correct: Literal["yes", "partial", "no", "n.a."]
    usability: int | None = Field(default=None, ge=1, le=5)
    tags: list[str] = Field(default_factory=list, max_length=10)
    notes: str = Field(default="", max_length=5000)

    @model_validator(mode="after")
    def explicit_judgment(self):
        layers = (self.route_correct, self.tool_correct, self.evidence_correct, self.answer_correct)
        if self.overall == "blocked" and (any(v != "n.a." for v in layers) or not self.notes.strip()):
            raise ValueError("blocked requires a reason and n.a. for all four layers")
        if self.overall == "pass" and any(v in {"no", "partial"} for v in layers):
            raise ValueError("pass cannot contain failed or partial layers")
        if self.overall != "blocked" and all(v == "n.a." for v in layers):
            raise ValueError("at least one layer must be judged")
        if self.overall in {"partial", "fail"} and not self.notes.strip():
            raise ValueError("partial/fail requires a concrete note")
        if any(not tag.strip() or len(tag) > 80 for tag in self.tags):
            raise ValueError("tags must contain 1–80 characters")
        return self
