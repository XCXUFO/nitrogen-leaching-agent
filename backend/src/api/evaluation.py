from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from src.api.chat import chat
from src.api.chat_schema import ChatHistoryMessage, ChatRequest
from src.api.files import file_store, upload_file
from src.evaluation.auth import current_user, require_developer
from src.evaluation.contracts import AssetInput, AssetPairInput, AssessmentInput, CaseDraftBatchInput, CaseDraftInput, CaseDraftRevision, CasePublishInput, EvaluationQuery, IssueInput, IssueUpdateInput, ManualAction, Principal, RegressionInput, RetestInput, ReviewAssignmentInput, ReviewResolutionInput, ReviewInput, StartExecution, TaskInput
from src.evaluation.service import EvaluationService
from src.evaluation.store import fail
from src.config import settings

router = APIRouter(prefix="/eval")


def service(request: Request) -> EvaluationService:
    return request.app.state.evaluation


def knowledge_config() -> dict:
    return {"rag_enabled": settings.rag_enabled,
            "index_path": settings.rag_chroma_dir or settings.chroma_persist_dir,
            "collection": settings.rag_collection,
            "embedding_model": settings.embedding_model,
            "reranker_model": settings.rag_reranker_model}


@router.get("/me")
def me(user: Principal = Depends(current_user)):
    return user


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
             offset: int = Query(0, ge=0), user: Principal = Depends(current_user)):
    require_developer(user)
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
        operator_id=operator_id.strip(), limit=limit, offset=offset)


@router.get("/sessions/{session_id}")
def session_detail(request: Request, session_id: str, user: Principal = Depends(current_user)):
    require_developer(user)
    result = service(request).store.runs.session(session_id)
    if result is None:
        raise fail("session_not_found", "未找到会话记录。", 404)
    return result


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


@router.get("/assets")
def assets(request: Request, user: Principal = Depends(current_user)):
    if user.role not in {"developer", "reviewer"}:
        raise fail("evaluation_forbidden", "资产目录仅供开发者或专家审核人查看。", 403)
    return service(request).catalog.assets()


@router.post("/assets", status_code=201)
def register_asset(request: Request, body: AssetInput, user: Principal = Depends(current_user)):
    require_developer(user)
    return service(request).catalog.register_asset(body, user)


@router.post("/assets/upload", status_code=201)
async def upload_asset(request: Request, filename: str = Query(..., min_length=1, max_length=200),
                       kind: Literal["paper", "model_input", "model_output", "result_fixture", "evidence"] = Query(...),
                       source: str = Query(..., min_length=1, max_length=500),
                       notes: str = Query("", max_length=3000), user: Principal = Depends(current_user)):
    require_developer(user)
    body = AssetInput(kind=kind, path="data/eval/uploads/pending", source=source, notes=notes)
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 40 * 1024 * 1024:
            raise fail("asset_upload_too_large", "资产超过 40 MiB，请使用本地路径登记或较小原件。", 413)
        raw.extend(chunk)
    return service(request).catalog.upload_asset(bytes(raw), filename, body, user)


@router.get("/asset-pairs")
def asset_pairs(request: Request, user: Principal = Depends(current_user)):
    if user.role not in {"developer", "reviewer"}:
        raise fail("evaluation_forbidden", "资产配对仅供开发者或专家审核人查看。", 403)
    return service(request).catalog.pairs()


@router.post("/asset-pairs", status_code=201)
def register_asset_pair(request: Request, body: AssetPairInput, user: Principal = Depends(current_user)):
    return service(request).catalog.register_pair(body, user)


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
