from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "nitrogen-leaching-agent-backend",
        "version": "0.1.0",
    }
