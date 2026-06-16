from __future__ import annotations

import time

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from openai import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    RateLimitError,
)

from src.agent.chat_service import ChatService, RAGQueryError
from src.api.chat_schema import ChatRequest, ChatResponse

router = APIRouter()


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
        detail={"code": code, "message": message if message is not None else str(exc)},
    )


@router.post("/chat", response_model=ChatResponse)
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    service: ChatService | None = getattr(request.app.state, "chat_service", None)
    if service is None:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "rag_not_configured",
                "message": (
                    "RAG 未启用或初始化失败；请检查 RAG_ENABLED、"
                    "RAG_CHROMA_DIR 与离线索引是否已生成。"
                ),
            },
        )

    t0 = time.perf_counter()
    try:
        result = await service.answer(body.query, k=body.k)
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

    return ChatResponse(
        answer=result.answer,
        citations=result.citations,
        usage=result.usage,
        retrieved_count=result.retrieved_count,
        model=result.model,
    )
