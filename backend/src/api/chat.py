from __future__ import annotations

import time
import hashlib
import asyncio
import json

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from loguru import logger
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from src.agent.chat_service import RAGQueryError
from src.agent.runtime import AgentRuntime
from src.agent.skills import KnowledgeUnavailable
from src.agent.state import ConversationBusy, StateCapacityError
from src.agent.submissions import ChatRunManager
from src.config import settings
from src.api.chat_schema import ChatRequest, ChatResponse, ChatRunView
from src.api.files import file_store
from src.evaluation.auth import current_user, front_principal
from src.rag.documents import citation_metadata
from src.evaluation.conversation_cases import FeedbackInput, IssueInput

router = APIRouter()
CHAT_REQUEST_TIMEOUT_S = 240.0


@router.post('/chat/feedback', status_code=201)
def feedback(request: Request, body: FeedbackInput):
    user = front_principal(request)
    visitor = getattr(request.state, 'public_visitor', None)
    actor = user.tester_id if user else 'visitor_' + visitor if visitor else None
    if actor is None:
        raise HTTPException(401, detail={'code': 'feedback_identity_required', 'message': '请恢复登录或刷新页面后提交反馈。'})
    runs = request.app.state.agent_runtime.runs
    session = runs.session(body.run_id)
    if not session or session['operator_id'] != actor:
        raise HTTPException(404, detail={'code': 'feedback_run_missing', 'message': '未找到你的这条回答。'})
    issue = runs.conversation_cases.create_issue(IssueInput(session_id=session['session_id'],
        run_id=body.run_id, note=body.note), actor, source='feedback', submission_id=body.submission_id)
    return {'issue_id': issue['issue_id'], 'status': 'received'}


def run_manager(request: Request) -> ChatRunManager:
    if not hasattr(request.app.state, "agent_runtime"):
        request.app.state.agent_runtime = AgentRuntime()
    if not hasattr(request.app.state, "chat_runs"):
        public = getattr(request.app.state, "public_settings", None)
        capacity = public.public_max_concurrent if public and public.public_demo_enabled else settings.chat_run_max_active
        request.app.state.chat_runs = ChatRunManager(request.app.state.agent_runtime.runs.live,
                                                   retention_seconds=settings.chat_run_retention_seconds, max_active=capacity)
    return request.app.state.chat_runs


def recovery_owner(request: Request):
    user = front_principal(request)
    owner = "internal_" + user.tester_id if user else getattr(request.state, "public_visitor", None)
    if owner is None:
        raise HTTPException(401, detail={"code": "chat_session_required", "message": "请先初始化会话后再提交。"})
    return owner


@router.get("/chat/session")
def chat_session(request: Request):
    recovery_owner(request)
    manager = run_manager(request)
    return JSONResponse({"protocol": "chat-runs-v1", "recovery_window_seconds": manager.retention_seconds}, headers={"Cache-Control": "no-store"})


@router.get("/chat/history")
def account_chat_history(request: Request, limit: int = Query(30, ge=1, le=100), offset: int = Query(0, ge=0)):
    user = current_user(request)
    run_manager(request)
    return JSONResponse(request.app.state.agent_runtime.runs.history.list(user.tester_id, limit=limit, offset=offset),
                        headers={"Cache-Control": "no-store"})


@router.get("/chat/requests/{request_id}", response_model=ChatRunView)
def find_submission(request: Request, request_id: str,
                    session_id: str = Query(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")):
    owner = recovery_owner(request)
    session = hashlib.sha256((owner + ":" + session_id).encode()).hexdigest()
    return JSONResponse(run_manager(request).lookup(owner, session, request_id), headers={"Cache-Control": "no-store"})


@router.get("/chat/runs/{run_id}", response_model=ChatRunView)
def get_chat_run(request: Request, run_id: str, after: int = Query(default=0, ge=0)):
    return JSONResponse(run_manager(request).get(recovery_owner(request), run_id, after), headers={"Cache-Control": "no-store"})


def _ms(t0: float) -> int:
    return int((time.perf_counter() - t0) * 1000)


def _fail(
    *,
    status_code: int,
    code: str,
    layer: str,
    exc: Exception,
    elapsed_ms: int,
    message: str | None = None,
    with_traceback: bool = False,
) -> HTTPException:
    """统一降级契约：稳定 {code, message} + 一眼可辨 layer/code/耗时的日志。

    layer 区分上游故障（llm_upstream）/ 检索故障（retrieval）/ 后端内部
    （internal），便于 demo 现场从日志直接定位失败发生在哪一层，而非把所有
    异常都当成「后端坏了」。

    message=None 时回显 str(exc)（已分类的 LLM/RAG 错误沿用原行为）；未知异常
    应显式传固定通用文案，避免把内部路径/配置/三方错误细节泄露给前端——完整
    异常只进日志。
    """
    log = logger.opt(exception=exc) if with_traceback else logger
    log.warning(
        "chat failed | layer={} | code={} | elapsed_ms={} | {}",
        layer,
        code,
        elapsed_ms,
        exc,
    )
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message if message is not None else str(exc),
                "run_id": getattr(exc, "agent_run_id", None),
                "trace_saved": getattr(exc, "agent_trace_saved", False)},
    )


@router.post("/chat", response_model=ChatResponse, responses={202: {"model": ChatRunView, "description": "已受理的可恢复运行"}})
async def chat(request: Request, body: ChatRequest) -> ChatResponse | JSONResponse:
    client_session_id = body.session_id or "default"
    visitor = getattr(request.state, "public_visitor", None)
    internal = front_principal(request)
    if internal:
        visitor = "internal_" + internal.tester_id
        body = body.model_copy(update={"operator_id": internal.tester_id,
            "session_id": hashlib.sha256((visitor + ":" + (body.session_id or "default")).encode()).hexdigest()})
    elif visitor:
        # Namespace client-selected conversation IDs by the signed visitor.
        body = body.model_copy(update={"operator_id": "visitor_" + visitor,
            "session_id": hashlib.sha256((visitor + ":" + (body.session_id or "default")).encode()).hexdigest()})
    elif not request.url.path.startswith("/api/eval/") and body.operator_id and not body.operator_id.startswith("visitor_"):
        body = body.model_copy(update={"operator_id": None})
    for token in ([body.file_id] if body.file_id else []) + (body.file_ids or []):
        # Expiration is handled by the runtime so other valid files still work.
        entry = file_store(request).entries.get(token)
        if entry is not None and ((entry.owner is not None and entry.owner != visitor)
                                  or (entry.session_id is not None and entry.session_id != body.session_id)):
            raise HTTPException(404, detail={"code": "file_not_found", "message": "文件已过期或不可用，请重新上传。"})
    if not hasattr(request.app.state, "agent_runtime"):
        # Minimal ASGI embedders/tests use an isolated in-memory store. The real
        # application configures persistent traces in its lifespan.
        request.app.state.agent_runtime = AgentRuntime()
    runtime: AgentRuntime = request.app.state.agent_runtime
    attachments = []
    if internal:
        for token in ([body.file_id] if body.file_id else []) + (body.file_ids or []):
            entry = file_store(request).entries.get(token)
            if entry is not None:
                attachments.append({"file_id": token, "filename": entry.filename, "sha256": entry.sha256,
                    "format": entry.format, "status": "pending", "kind": None, "rows": None, "expires_in_seconds": 0})
    if body.request_id:
        owner = recovery_owner(request)
        expression_config = runtime.expression_snapshot()
        fingerprint_input = body.model_dump(exclude={"request_id", "turn_id", "rerun_of_run_id", "operator_id"})
        fingerprint = hashlib.sha256(json.dumps(fingerprint_input, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

        async def execute(record, observer):
            context = {key: record[key] for key in ("turn_id", "request_id", "primary_run_id", "rerun_of_run_id", "source", "mode")}
            return await execute_chat(request, body, runtime, run_id=record["run_id"], observer=observer, run_context=context, expression_config=expression_config)

        guard = getattr(request.app.state, "public_access", None)
        slot = getattr(request.state, "public_slot_acquired", False)

        def transfer_slot():
            request.state.public_slot_transferred = True

        def release_slot():
            guard.active -= 1

        receipt = run_manager(request).submit(execute=execute, owner=owner, session_id=body.session_id,
                                             turn_id=body.turn_id, request_id=body.request_id,
                                             fingerprint=fingerprint, rerun_of_run_id=body.rerun_of_run_id,
                                             config_version=runtime.config_version + ":" + expression_config["version"] + ":" + expression_config["communication"]["version"], mode="specified" if (body.case_skill or body.case_mode) else "auto",
                                             on_created=transfer_slot if slot else None, on_finished=release_slot if slot else None)
        if internal:
            runtime.runs.history.record(internal.tester_id, client_session_id, body.session_id,
                                        body.model_dump(), receipt, attachments)
        return JSONResponse(receipt, status_code=202, headers={"Cache-Control": "no-store"})
    # This function also serves the authenticated evaluation query endpoint.
    # Stamp its trusted origin before execution so failed runs keep it as well;
    # the client cannot choose this through ChatRequest.
    context = {"source": "evaluation", "mode": "auto"} if request.url.path.startswith("/api/eval/") else {"source": "formal", "mode": "auto"} if internal else None
    response = await execute_chat(request, body, runtime, run_context=context)
    if internal:
        runtime.runs.history.record(internal.tester_id, client_session_id, body.session_id, body.model_dump(),
            {"run_id": response.run_id, "turn_id": response.run_id, "request_id": response.run_id,
             "status": "succeeded", "result": response.model_dump(mode="json")}, attachments)
    return response


async def execute_chat(request: Request, body: ChatRequest, runtime: AgentRuntime, **execution_options) -> ChatResponse:
    t0 = time.perf_counter()
    attachments = []
    for token in dict.fromkeys(([body.file_id] if body.file_id else []) + (body.file_ids or [])):
        entry = file_store(request).entries.get(token)
        if entry is not None:
            if entry.original_path is not None:
                runtime.runs.attachments.put(entry.original_path.read_bytes(), entry.sha256)
            attachments.append({"filename": entry.filename, "sha256": entry.sha256, "format": entry.format})
    try:
        response = await asyncio.wait_for(runtime.execute(body, service=getattr(request.app.state, "chat_service", None),
                                         attachment_metadata=attachments,
                                         get_report=file_store(request).inspect,
                                         get_documents=file_store(request).documents,
                                         case_store=getattr(request.app.state, "case_library", None),
                                         taxonomy_provider=getattr(getattr(request.app.state, "literature", None), "matching_taxonomy", None),
                                         starred_provider=getattr(getattr(getattr(request.app.state, "evaluation", None), "store", None), "starred_questions", None),
                                         llm=getattr(request.app.state, "llm", None), **execution_options), timeout=CHAT_REQUEST_TIMEOUT_S)
        library = getattr(request.app.state, "literature", None)
        enriched = []
        for citation in response.citations:
            if citation.source_type == "web":
                metadata = {}
            elif citation.source.startswith("session://"):
                metadata = {"title": citation.source.rsplit("/", 1)[-1], "author_hint": None, "year": None,
                            "document_id": citation.source.split("/", 3)[2], "document_available": False}
            else:
                metadata = library.search_index.citation_metadata(citation.source) if library else None
                if metadata is None:
                    metadata = citation_metadata(citation.source)
            enriched.append(citation.model_copy(update=metadata))
        response.citations = enriched
        return response
    except HTTPException as exc:
        if isinstance(exc.detail, dict):
            exc.detail = {**exc.detail, "run_id": getattr(exc, "agent_run_id", None),
                          "trace_saved": getattr(exc, "agent_trace_saved", False)}
        raise
    except TimeoutError as exc:
        # Runtime cancellation releases the conversation lease before wait_for returns.
        for name in ("agent_run_id", "agent_trace_saved"):
            setattr(exc, name, getattr(exc.__cause__, name, None))
        raise _fail(status_code=504, code="request_timeout", layer="runtime", exc=exc,
                    elapsed_ms=_ms(t0), message="本次处理超时，请稍后重试。") from exc
    except KnowledgeUnavailable as exc:
        raise _fail(status_code=503, code="rag_not_configured", layer="retrieval", exc=exc,
                    elapsed_ms=_ms(t0), message="文献服务未启用或初始化失败；请检查 RAG 配置与离线索引。文件分析仍可使用。") from exc
    except ConversationBusy as exc:
        raise _fail(status_code=409, code="conversation_busy", layer="state", exc=exc,
                    elapsed_ms=_ms(t0), message="当前对话仍有请求正在处理，请等待完成后再发送。") from exc
    except StateCapacityError as exc:
        raise _fail(status_code=503, code="conversation_capacity", layer="state", exc=exc,
                    elapsed_ms=_ms(t0), message="当前对话数量已达上限，请稍后重试。") from exc
    except RAGQueryError as exc:
        raise _fail(
            status_code=503,
            code="rag_query_failed",
            layer="retrieval",
            exc=exc,
            elapsed_ms=_ms(t0),
            with_traceback=True,
        ) from exc
    except AuthenticationError as exc:
        raise _fail(
            status_code=500,
            code="llm_auth_failed",
            layer="llm_upstream",
            exc=exc,
            elapsed_ms=_ms(t0),
        ) from exc
    except RateLimitError as exc:
        raise _fail(
            status_code=429,
            code="llm_rate_limited",
            layer="llm_upstream",
            exc=exc,
            elapsed_ms=_ms(t0),
        ) from exc
    except APITimeoutError as exc:
        # 必须排在 APIConnectionError 之前（前者是后者子类）。对应第 2 步的有界
        # 超时：60s 触顶时返回明确的 504 llm_timeout，而非误报「无法连接」。
        raise _fail(
            status_code=504,
            code="llm_timeout",
            layer="llm_upstream",
            exc=exc,
            elapsed_ms=_ms(t0),
        ) from exc
    except APIConnectionError as exc:
        raise _fail(
            status_code=502,
            code="llm_unreachable",
            layer="llm_upstream",
            exc=exc,
            elapsed_ms=_ms(t0),
        ) from exc
    except APIError as exc:
        raise _fail(
            status_code=502,
            code="llm_upstream_error",
            layer="llm_upstream",
            exc=exc,
            elapsed_ms=_ms(t0),
        ) from exc
    except Exception as exc:
        # 兜底：任何未预期异常也走稳定契约（前端始终能拿到 code），但带 traceback
        # 记录，避免掩盖真实 bug。守住「异常不导致 demo 接口不可控失败」。
        raise _fail(
            status_code=500,
            code="internal_error",
            layer="internal",
            exc=exc,
            elapsed_ms=_ms(t0),
            message="服务内部异常，请稍后重试",
            with_traceback=True,
        ) from exc
