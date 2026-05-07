from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src import __version__
from src.agent.chat_service import ChatService
from src.api import chat, health
from src.config import settings
from src.llm.deepseek import DeepSeekClient
from src.rag import BGEEmbedder, Reranker, Retriever
from src.storage import ChromaStore
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
    llm = DeepSeekClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
    )
    app.state.llm = llm
    app.state.chat_service = None

    if settings.rag_enabled:
        chroma_dir = settings.rag_chroma_dir or settings.chroma_persist_dir
        try:
            embedder = BGEEmbedder(model_id=settings.embedding_model)
            store = ChromaStore(chroma_dir, settings.rag_collection)

            reranker: Reranker | None = None
            if settings.rag_reranker_enabled:
                reranker = Reranker(model_id=settings.rag_reranker_model)

            retriever = Retriever(
                embedder,
                store,
                reranker=reranker,
                top_k_recall=settings.rag_reranker_top_k_recall,
            )
            chat_top_k = (
                settings.rag_reranker_top_n
                if settings.rag_reranker_enabled
                else settings.chat_top_k
            )
            app.state.chat_service = ChatService(
                retriever,
                llm,
                top_k=chat_top_k,
                max_context_chars=settings.chat_max_context_chars,
                temperature=settings.chat_temperature,
            )
            logger.info(
                "RAG enabled | chroma_dir={} | collection={} | "
                "reranker={} | top_k_recall={} | top_k={}",
                chroma_dir,
                settings.rag_collection,
                settings.rag_reranker_model if reranker else "off",
                settings.rag_reranker_top_k_recall if reranker else "n/a",
                chat_top_k,
            )
        except Exception:
            logger.warning(
                "RAG enabled in config but failed to initialize; /api/chat will return 503",
                exc_info=True,
            )
    else:
        logger.info("RAG disabled (rag_enabled=False); /api/chat returns 503")

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
app.include_router(chat.router, prefix="/api", tags=["chat"])
