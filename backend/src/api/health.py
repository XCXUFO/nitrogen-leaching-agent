from fastapi import APIRouter

from src import __version__

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "nitrogen-leaching-agent-backend",
        "version": __version__,
    }
