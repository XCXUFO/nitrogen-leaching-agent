from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from loguru import logger
from openai import APIConnectionError, APIError, AuthenticationError, RateLimitError

from src.agent.chat_service import ChatService, RAGQueryError
from src.api.chat_schema import ChatRequest, ChatResponse

router = APIRouter()


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

    try:
        result = await service.answer(body.query, k=body.k)
    except RAGQueryError as exc:
        logger.exception("RAG query failed")
        raise HTTPException(
            status_code=503,
            detail={"code": "rag_query_failed", "message": str(exc)},
        ) from exc
    except AuthenticationError as exc:
        logger.exception("LLM auth failed")
        raise HTTPException(
            status_code=500,
            detail={"code": "llm_auth_failed", "message": str(exc)},
        ) from exc
    except RateLimitError as exc:
        logger.warning("LLM rate limited: {}", exc)
        raise HTTPException(
            status_code=429,
            detail={"code": "llm_rate_limited", "message": str(exc)},
        ) from exc
    except APIConnectionError as exc:
        logger.warning("LLM unreachable: {}", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_unreachable", "message": str(exc)},
        ) from exc
    except APIError as exc:
        logger.warning("LLM upstream error: {}", exc)
        raise HTTPException(
            status_code=502,
            detail={"code": "llm_upstream_error", "message": str(exc)},
        ) from exc

    return ChatResponse(
        answer=result.answer,
        citations=result.citations,
        usage=result.usage,
        retrieved_count=result.retrieved_count,
        model=result.model,
    )
