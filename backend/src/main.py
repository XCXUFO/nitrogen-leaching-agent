from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src.api import health
from src.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "Backend starting | env={} | cors_origins={}",
        settings.app_env,
        settings.cors_origin_list,
    )
    yield
    logger.info("Backend shutting down")


app = FastAPI(
    title="Nitrogen Leaching Agent API",
    description="Backend for the farmland nitrogen leaching risk decision AI agent.",
    version="0.1.0",
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
