from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from src import __version__
from src.config import settings

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "nitrogen-leaching-agent-backend",
        "version": __version__,
    }


@router.get("/ready")
async def ready(request: Request) -> JSONResponse:
    """Report whether the configured public knowledge service is usable."""
    if (settings.rag_enabled or settings.public_demo_enabled) and getattr(request.app.state, "chat_service", None) is None:
        return JSONResponse({"status": "not_ready", "reason": "knowledge_unavailable"}, status_code=503)
    return JSONResponse({"status": "ready"})
