"""Authenticated conversation metrics; turn details live in evaluation."""
from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import Field, ValidationError, field_validator

from src.agent.contracts import Contract
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal

router = APIRouter(prefix="/eval")


def metrics_reader(user: Principal = Depends(current_user)):
    if user.role not in {"developer", "reviewer"}:
        raise HTTPException(403, detail={"code": "metrics_forbidden", "message": "线上看板仅供审核者与开发者使用。"})
    return user


class RunFilters(Contract):
    source: Literal["formal", "test", "evaluation", "legacy"] = "formal"
    mode: Literal["auto", "specified"] | None = None
    status: Literal["normal", "abnormal", "running", "unknown"] | None = None
    skill: str | None = Field(default=None, max_length=100)
    task_type: str | None = Field(default=None, max_length=100)
    config_version: str | None = Field(default=None, max_length=300)
    start: str | None = Field(default=None, alias="from")
    end: str | None = Field(default=None, alias="to")

    @field_validator("start", "end")
    @classmethod
    def iso_timestamp(cls, value):
        if value is not None:
            date = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if date.tzinfo is None: raise ValueError("时间范围请包含时区")
            return date.astimezone(timezone.utc).isoformat()
        return value


def filters(request):
    values = {key: value for key, value in request.query_params.items() if key in {"source", "mode", "status", "skill", "task_type", "config_version", "from", "to"} and value != ""}
    try:
        result = RunFilters.model_validate(values).model_dump(by_alias=True, exclude_none=True)
        if result.get("from") and result.get("to") and result["from"] > result["to"]: raise ValueError("起始时间晚于结束时间")
        return result
    except (ValidationError, ValueError) as exc:
        raise HTTPException(422, detail={"code": "invalid_run_filters", "message": "筛选范围无效，请核对来源、模式和时间。"}) from exc


@router.get("/online-metrics")
def online_metrics(request: Request, user: Principal = Depends(metrics_reader)):
    return request.app.state.agent_runtime.runs.online_metrics.summary(filters(request), include_sessions=user.role == "developer")
