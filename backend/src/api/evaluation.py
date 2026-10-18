from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from pydantic import BaseModel, Field, field_validator

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.agent.skill_catalog import SkillDetail, SkillSummary, describe_skills
from src.agent.skill_config import ExpressionUpdate, ExpressionReset
from src.api.chat import chat
from src.api.chat_schema import ChatHistoryMessage, ChatRequest
from src.api.files import file_store, upload_file
from src.evaluation.auth import current_user, login, require_developer, sessions as login_sessions
from src.evaluation.contracts import LoginInput
from src.evaluation.contracts import AssessmentInput, CaseDraftBatchInput, CaseDraftInput, CaseDraftRevision, CasePublishInput, EvaluationQuery, IssueInput, IssueUpdateInput, ManualAction, Principal, RegressionInput, RetestInput, ReviewAssignmentInput, ReviewResolutionInput, ReviewInput, StartExecution, TaskInput
from src.evaluation.service import EvaluationService
from src.evaluation.session_reviews import SessionReviewInput, SessionRetestInput
from src.evaluation.store import fail
from src.config import settings

router = APIRouter(prefix="/eval")


def service(request: Request) -> EvaluationService:
    return request.app.state.evaluation


def skill_catalog(request: Request) -> list[SkillDetail]:
    state = request.app.state
    return describe_skills(service=getattr(state, "chat_service", None), llm=getattr(state, "llm", None),
                           case_store=getattr(state, "case_library", None), runtime=getattr(state, "agent_runtime", None))


@router.get("/skills", response_model=list[SkillSummary])
def skills(request: Request, user: Principal = Depends(current_user)):
    return skill_catalog(request)


@router.get("/skills/{name}", response_model=SkillDetail)
def skill(request: Request, name: str, user: Principal = Depends(current_user)):
    item = next((item for item in skill_catalog(request) if item.name == name), None)
    if item is None:
        raise HTTPException(404, detail={"code": "skill_not_found", "message": "未找到该能力，请返回能力列表。"})
    return item


def expression_store(request, name):
    if name != "case_explanation":
        raise HTTPException(400, detail={"code": "skill_read_only", "message": "此能力不支持配置编辑。"})
    return request.app.state.agent_runtime.runs.skill_config


@router.get("/skills/{name}/configuration")
def expression_configuration(request: Request, name: str, user: Principal = Depends(current_user)):
    store = expression_store(request, name)
    return {"current": store.current(), "history": store.history()}


@router.put("/skills/{name}/configuration")
def save_expression_configuration(request: Request, name: str, body: ExpressionUpdate, user: Principal = Depends(current_user)):
    return expression_store(request, name).update(expected_revision=body.expected_revision, values=body.values.model_dump(), actor=user.tester_id)


@router.post("/skills/{name}/configuration/reset")
def reset_expression_configuration(request: Request, name: str, body: ExpressionReset, user: Principal = Depends(current_user)):
    return expression_store(request, name).update(expected_revision=body.expected_revision, values={}, actor=user.tester_id, reset=True)


class StarredQuestionInput(BaseModel):
    question: str = Field(max_length=20000)
    answer: str = Field(default="", max_length=100000)

    @field_validator("question")
    @classmethod
    def question_required(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("问题不能为空")
        return value

    @field_validator("answer")
    @classmethod
    def blank_answer(cls, value: str) -> str:
        return value if value.strip() else ""


@router.get("/starred-questions")
def starred_questions(request: Request, user: Principal = Depends(current_user)):
    return service(request).store.starred_questions()


@router.post("/starred-questions", status_code=201)
def create_starred_question(request: Request, body: StarredQuestionInput, user: Principal = Depends(current_user)):
    return service(request).store.create_starred_question(body.question, body.answer)


class StarredQuestionUpdate(StarredQuestionInput):
    expected_revision: int = Field(ge=1)


@router.put("/starred-questions/{question_id}")
def update_starred_question(request: Request, question_id: str, body: StarredQuestionUpdate, user: Principal = Depends(current_user)):
    return service(request).store.update_starred_question(question_id, body.question, body.answer, body.expected_revision)


def knowledge_config() -> dict:
    return {"rag_enabled": settings.rag_enabled,
            "index_path": settings.rag_chroma_dir or settings.chroma_persist_dir,
            "collection": settings.rag_collection,
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.rag_reranker_model}


@router.get("/me")
def me(user: Principal = Depends(current_user)):
    return user


@router.post("/login")
def account_login(request: Request, body: LoginInput):
    return login(request, body)


@router.post("/logout", status_code=204)
def account_logout(request: Request):
    login_sessions(request).revoke(request.headers.get("authorization", "").partition(" ")[2])


@router.get("/config")
def config(request: Request, user: Principal = Depends(current_user)):
    version = request.app.state.agent_runtime.config_version
    return {"build_version": version.split(":", 1)[0], "runtime_config_version": version,
            "knowledge_config": knowledge_config(),
            "version_manifest": getattr(request.app.state, "version_manifest", {})}


@router.get("/cases")
def cases(request: Request, latest: bool = True, user: Principal = Depends(current_user)):
    return service(request).store.cases(latest)


@router.get("/executions")
def executions(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: Principal = Depends(current_user)):
    return service(request).store.list_executions(user, limit, offset)


@router.post("/executions", status_code=201)
async def start(request: Request, body: StartExecution, user: Principal = Depends(current_user)):
    svc = service(request)
    # Reserve ephemeral capacity before creating the persistent execution.
    svc.prune()
    if len(svc.contexts) >= 256:
        raise fail("evaluation_capacity", "活动测试过多，请稍后再试。", 503)
    execution = svc.store.create(body.case_id, body.case_version, user, body.task_id,
                                 request.app.state.agent_runtime.config_version)
    svc.reset(execution["execution_id"])
    return svc.view(execution["execution_id"], user)


@router.get("/executions/{eid}")
async def execution(request: Request, eid: str, user: Principal = Depends(current_user)):
    return service(request).view(eid, user)


@router.post("/executions/{eid}/query")
async def query(request: Request, eid: str, body: EvaluationQuery, user: Principal = Depends(current_user)):
    svc = service(request)
    with svc.guard(eid, user) as execution:
        svc.check_task_config(execution, request.app.state.agent_runtime.config_version)
        svc.check_capacity(execution)
        ctx = svc.context(eid, execution)
        if ctx.file_id:
            try:
                # Knowledge turns also count as activity in this file's session.
                file_store(request).get(ctx.file_id)
            except HTTPException:
                # An unavailable file must not block unrelated knowledge turns;
                # file analysis will report expiry through the normal Run path.
                pass
        # The browser cannot choose session/history, attach somebody else's run,
        # or provide a different tester identity.
        chat_body = ChatRequest(query=body.query, session_id=ctx.session_id, operator_id=user.tester_id,
                                file_id=ctx.file_id, history=ctx.history)
        try:
            response = await chat(request, chat_body)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            saved = detail.get("trace_saved", False)
            svc.store.event(eid, {"action": "query", "input": body.query,
                                 "error": {"code": detail.get("code", "request_failed"), "http_status": exc.status_code},
                                 "trace_missing": not saved}, run_id=detail.get("run_id") if saved else None)
            if detail.get("code") == "file_not_found":
                ctx.file_id, ctx.attachment = None, None
        else:
            result = response.model_dump(mode="json", exclude={"conversation_id"})
            svc.store.event(eid, {"action": "query", "input": body.query, "response": result,
                                 "trace_missing": not response.trace_saved},
                            run_id=response.run_id if response.trace_saved else None)
            ctx.history.append(ChatHistoryMessage(role="user", content=body.query))
            if response.answer.strip():
                ctx.history.append(ChatHistoryMessage(role="assistant", content=response.answer[:4000]))
            ctx.history = ctx.history[-12:]
            if response.attachment:
                ctx.attachment = response.attachment.model_dump()
                if response.attachment.status == "expired":
                    ctx.file_id = None
        return svc.view(eid, user)


@router.post("/executions/{eid}/files")
async def upload(request: Request, eid: str, filename: str = Query(..., min_length=1, max_length=200), user: Principal = Depends(current_user)):
    svc = service(request)
    with svc.guard(eid, user) as execution:
        svc.check_task_config(execution, request.app.state.agent_runtime.config_version)
        svc.check_capacity(execution)
        ctx = svc.context(eid, execution)
        try:
            receipt = await upload_file(request, filename)
            expected = svc.store.case(execution["case_id"], execution["case_version"])["fixtures"]
            if expected:
                match = next((f for f in expected if f["filename"] == receipt.filename), None)
                if not match or (match.get("sha256") and match["sha256"] != receipt.sha256):
                    file_store(request).entries.pop(receipt.file_id, None)
                    raise fail("evaluation_fixture_mismatch", "附件名称或指纹与此用例不符，请使用用例指定文件。", 422)
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            svc.store.event(eid, {"action": "upload", "error": {"code": detail.get("code", "upload_failed"),
                                 "http_status": exc.status_code, "message": detail.get("message", "上传失败。")}})
        else:
            # Replace only after the new upload passes the frozen fixture check.
            ctx.file_id = receipt.file_id
            ctx.attachment = receipt.model_dump(exclude={"file_id"})
            svc.store.event(eid, {"action": "upload", "attachment": ctx.attachment})
        return svc.view(eid, user)


@router.post("/executions/{eid}/actions")
async def action(request: Request, eid: str, body: ManualAction, user: Principal = Depends(current_user)):
    svc = service(request)
    with svc.guard(eid, user) as execution:
        if body.action != "manual":
            svc.check_task_config(execution, request.app.state.agent_runtime.config_version)
        svc.check_capacity(execution)
        if body.action == "clear":
            svc.reset(eid)
        elif body.action == "remove_attachment":
            ctx = svc.context(eid, execution)
            ctx.file_id, ctx.attachment = None, None
        elif not body.note.strip():
            raise fail("evaluation_note_required", "请记录手动操作或受阻情况。", 422)
        svc.store.event(eid, body.model_dump())
        return svc.view(eid, user)


@router.post("/executions/{eid}/reviews", status_code=201)
async def review(request: Request, eid: str, body: ReviewInput, user: Principal = Depends(current_user)):
    svc = service(request)
    with svc.guard(eid, user):
        svc.store.review(eid, user, body)
        svc.contexts.pop(eid, None)
        return svc.view(eid, user)


@router.get("/runs")
def runs(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).store.list_runs(limit, offset)


@router.get("/sessions")
def sessions(request: Request, information: str = Query("", max_length=100),
             created_from: datetime | None = None, created_to: datetime | None = None,
             status: Literal["正常", "异常"] | None = None,
             duration_mode: Literal["gt", "lt", "eq", "between"] | None = None,
             duration_ms: int | None = Query(None, ge=0), duration_max_ms: int | None = Query(None, ge=0),
             operator_id: str = Query("", max_length=100), limit: int = Query(20, ge=1, le=100),
             review_status: Literal["pending", "passed", "needs_changes"] | None = None,
             offset: int = Query(0, ge=0), user: Principal = Depends(current_user)):
    if duration_mode and (duration_ms is None or (duration_mode == "between" and
       (duration_max_ms is None or duration_max_ms < duration_ms))):
        raise fail("invalid_duration_filter", "请填写有效的耗时条件。", 422)
    def utc(value: datetime | None) -> str | None:
        return value.astimezone(timezone.utc).isoformat() if value and value.tzinfo else value.replace(tzinfo=timezone.utc).isoformat() if value else None
    start, end = utc(created_from), utc(created_to)
    if start and end and start > end:
        raise fail("invalid_date_filter", "结束时间不能早于起始时间。", 422)
    return service(request).store.runs.sessions(information=information.strip(), created_from=start,
        created_to=end, status=status, duration_mode=duration_mode,
        duration_ms=duration_ms, duration_max_ms=duration_max_ms,
        operator_id=operator_id.strip(), review_status=review_status, limit=limit, offset=offset)


@router.get("/sessions/{session_id}")
def session_detail(request: Request, session_id: str, user: Principal = Depends(current_user)):
    result = service(request).store.runs.session(session_id)
    if result is None:
        raise fail("session_not_found", "未找到会话记录。", 404)
    return result


@router.post("/sessions/{session_id}/reviews")
def review_session(request: Request, session_id: str, body: SessionReviewInput, user: Principal = Depends(current_user)):
    store = service(request).store.runs
    session = store.session(session_id)
    if session is None:
        raise fail("session_not_found", "未找到会话记录。", 404)
    store.reviews.apply(session["session_id"], body, user.tester_id)
    return store.session(session["session_id"])


@router.post("/sessions/{session_id}/retests", status_code=202)
async def retest_session(request: Request, session_id: str, body: SessionRetestInput, user: Principal = Depends(current_user)):
    import hashlib
    import json

    from src.api.chat import execute_chat, run_manager

    store = service(request).store.runs
    session = store.session(session_id)
    original = next((turn for turn in (session or {}).get("turns", []) if turn["run_id"] == body.source_run_id), None)
    if original is None:
        raise fail("review_run_mismatch", "未找到当前会话的原回答。", 404)
    if body.issue_id and not any(issue["issue_id"] == body.issue_id and issue["run_id"] == body.source_run_id for issue in session["review"]["issues"]):
        raise fail("review_issue_not_found", "该问题与原回答不匹配。", 422)
    snapshot = original.get("request_snapshot") or {}
    if not snapshot or snapshot.get("query") != original["input"]:
        raise fail("retest_input_missing", "这条历史记录缺少原请求，请复制问题到前台补充上下文后验证。", 422)
    if (snapshot.get("has_attachments") or (original.get("state_before") or {}).get("attachment_ref")
            or any(item.get("source_type") == "file" for item in original.get("evidence", []))):
        raise fail("retest_files_required", "原问题使用了附件，请到前台重新上传原文件后验证，并在此填写确认依据。", 422)
    owner = "internal_" + user.tester_id
    isolated_session = hashlib.sha256((owner + ":review:" + body.submission_id).encode()).hexdigest()
    replay = ChatRequest.model_validate({key: value for key, value in snapshot.items()
        if key not in {"has_attachments", "request_id", "turn_id", "rerun_of_run_id"}}).model_copy(
            update={"session_id": isolated_session, "operator_id": user.tester_id})
    fingerprint = hashlib.sha256(json.dumps({"source": body.source_run_id, "issue": body.issue_id, "request": snapshot}, sort_keys=True).encode()).hexdigest()
    manager = run_manager(request)
    expression_config = request.app.state.agent_runtime.expression_snapshot()

    async def execute(record, observer):
        return await execute_chat(request, replay, request.app.state.agent_runtime, run_id=record["run_id"], observer=observer, expression_config=expression_config,
            run_context={"source": "test", "mode": original.get("mode") or "auto", "replay_of_run_id": body.source_run_id,
                         "replay_comparability": "current_materials_with_original_text_context"})

    result = manager.submit(owner=owner, session_id=isolated_session, turn_id=body.submission_id,
        request_id=body.submission_id, fingerprint=fingerprint, rerun_of_run_id=None,
        config_version=request.app.state.agent_runtime.config_version, source="test", mode=original.get("mode") or "auto", execute=execute)
    store.reviews.record_retest(session["session_id"], body, result["run_id"], user.tester_id)
    return store.session(session["session_id"])


@router.get("/runs/{run_id}")
def trace(request: Request, run_id: str, user: Principal = Depends(current_user)):
    require_developer(user)
    result = service(request).store.runs.get(run_id)
    if result is None:
        raise fail("run_not_found", "未找到运行记录。", 404)
    return result


@router.get("/statistics")
def statistics(request: Request, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).store.statistics()


@router.get("/tasks")
def tasks(request: Request, user: Principal = Depends(current_user)):
    return service(request).workflow.tasks()


@router.post("/tasks", status_code=201)
def create_task(request: Request, body: TaskInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.create_task(body, user, request.app.state.agent_runtime.config_version,
                                                 knowledge_config(),
                                                 getattr(request.app.state, "version_manifest", {}))


@router.get("/tasks/{task_id}")
def task(request: Request, task_id: str, user: Principal = Depends(current_user)):
    return service(request).workflow.task_progress(task_id, user)["task"]


@router.get("/tasks/{task_id}/progress")
def task_progress(request: Request, task_id: str, user: Principal = Depends(current_user)):
    return service(request).workflow.task_progress(task_id, user)


@router.get("/tasks/{task_id}/evidence")
def task_evidence(request: Request, task_id: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.task_evidence(task_id, user)


@router.post("/tasks/{task_id}/prepare")
def prepare_task(request: Request, task_id: str, user: Principal = Depends(current_user)):
    return service(request).workflow.prepare_task(task_id, user, request.app.state.agent_runtime.config_version)


@router.get("/tasks/{task_id}/dashboard")
def task_dashboard(request: Request, task_id: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.dashboard(task_id)


@router.get("/case-drafts")
def case_drafts(request: Request, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.drafts()


@router.post("/case-drafts", status_code=201)
def create_case_draft(request: Request, body: CaseDraftInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.create_draft(body, user)


@router.post("/case-drafts/import", status_code=201)
def import_case_drafts(request: Request, body: CaseDraftBatchInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.import_drafts(body, user)


@router.get("/case-drafts/{draft_id}")
def case_draft(request: Request, draft_id: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.draft(draft_id)


@router.get("/case-drafts/{draft_id}/history")
def case_draft_history(request: Request, draft_id: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.draft_history(draft_id)


@router.put("/case-drafts/{draft_id}")
def update_case_draft(request: Request, draft_id: str, body: CaseDraftRevision, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.update_draft(draft_id, body, user)


@router.post("/case-drafts/{draft_id}/publish", status_code=201)
def publish_case_draft(request: Request, draft_id: str, body: CasePublishInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.publish(draft_id, user, body.expected_revision)


@router.get("/issues")
def issues(request: Request, status: str | None = None, assignee: str | None = None, task_id: str | None = None,
           user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.issues(status=status, assignee=assignee, task_id=task_id)


@router.post("/issues", status_code=201)
def create_issue(request: Request, body: IssueInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.create_issue(body, user)


@router.get("/issues/{issue_id}")
def issue(request: Request, issue_id: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.issue(issue_id)


@router.patch("/issues/{issue_id}")
def update_issue(request: Request, issue_id: str, body: IssueUpdateInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.update_issue(issue_id, body, user)


@router.post("/issues/{issue_id}/retests", status_code=201)
def record_retest(request: Request, issue_id: str, body: RetestInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).workflow.record_retest(issue_id, body, user)


@router.get("/assessments")
def assessments(request: Request, case_id: str | None = None, user: Principal = Depends(current_user)):
    if user.role not in {"developer", "reviewer"}:
        raise fail("evaluation_forbidden", "此功能仅供开发者或专家审核人使用。", 403)
    return service(request).workflow.assessments(case_id)


@router.post("/assessments", status_code=201)
def record_assessment(request: Request, body: AssessmentInput, user: Principal = Depends(current_user)):
    return service(request).workflow.record_assessment(body, user)


@router.get("/review-queue")
def review_queue(request: Request, status: str | None = None, user: Principal = Depends(current_user)):
    if user.role not in {"developer", "reviewer"}:
        raise fail("evaluation_forbidden", "审核队列仅供开发者或专家审核人查看。", 403)
    return service(request).workflow.review_queue(status)


@router.get("/reviewers")
def reviewers(request: Request, user: Principal = Depends(current_user)):
    require_developer(user)
    return [{"tester_id": item.tester_id} for item in request.app.state.eval_access.users
            if item.role == "reviewer"]


@router.post("/review-queue/{eid}/assignments", status_code=201)
def assign_review(request: Request, eid: str, body: ReviewAssignmentInput, user: Principal = Depends(current_user)):
    require_developer(user)
    access = request.app.state.eval_access
    if not any(item.tester_id == body.reviewer_id and item.role == "reviewer" for item in access.users):
        raise fail("reviewer_identity_required", "只能分派给已配置的专家审核身份。", 422)
    return service(request).workflow.assign_review(eid, body, user)


@router.post("/review-queue/{eid}/resolutions", status_code=201)
def resolve_review(request: Request, eid: str, body: ReviewResolutionInput, user: Principal = Depends(current_user)):
    if user.role != "reviewer":
        raise fail("expert_reviewer_required", "分歧处理需专家审核身份。", 403)
    return service(request).workflow.resolve_review(eid, body, user)


# These endpoints are developer-only: replay can invoke the configured LLM.
@router.get("/regressions")
def regressions(request: Request, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0), user: Principal = Depends(current_user)):
    require_developer(user)
    return request.app.state.regressions.list(limit, offset)


@router.post("/regressions", status_code=201)
async def save_regression(request: Request, body: RegressionInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return request.app.state.regressions.create(body.execution_id, body.title, body.notes, user)


@router.get("/regressions/{rid}")
def regression(request: Request, rid: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return request.app.state.regressions.get(rid)


@router.post("/regressions/{rid}/replays", status_code=202)
async def replay(request: Request, rid: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return request.app.state.regressions.start(rid, request, user)


@router.get("/replays/{rid}")
def replay_state(request: Request, rid: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return request.app.state.regressions.replay(rid)


@router.post("/replays/{rid}/cancel")
async def cancel_replay(request: Request, rid: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return request.app.state.regressions.cancel(rid)


@router.get("/replays/{rid}/comparison")
def comparison(request: Request, rid: str, user: Principal = Depends(current_user)):
    require_developer(user)
    return request.app.state.regressions.compare(rid, user)
