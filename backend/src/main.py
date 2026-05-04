from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src import __version__
from src.api import health
from src.config import settings
from src.utils.logging import configure_logging


configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not settings.deepseek_api_key:
        raise RuntimeError("DEEPSEEK_API_KEY 未配置；请检查 backend/.env")
    logger.info(
        "Backend starting | env={} | model={} | cors_origins={}",
        settings.app_env,
        settings.deepseek_model,
        settings.cors_origin_list,
    )
    yield
    logger.info("Backend shutting down")


app = FastAPI(
    title="Nitrogen Leaching Agent API",
    description="Backend for the farmland nitrogen leaching risk decision AI agent.",
    version=__version__,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health.router, prefix="/api", tags=["health"])
