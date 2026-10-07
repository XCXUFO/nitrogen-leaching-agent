from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from loguru import logger

from src import __version__
from src.agent.chat_service import ChatService
from src.agent.runtime import AgentRuntime
from src.storage.run_store import RunStore
from src.api import chat, demo, documents, evaluation, files, health
from src.operations.public_access import PublicAccess, public_access
from src.evaluation.auth import load_access
from src.evaluation.service import EvaluationService
from src.evaluation.store import EvaluationStore
from src.evaluation.regression import RegressionService
from src.evaluation.versioning import build_manifest
from pathlib import Path
from src.config import settings
from src.llm.deepseek import DeepSeekClient
from src.rag import BGEEmbedder, Reranker, Retriever
from src.storage import ChromaStore
from src.utils.logging import configure_logging


configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.public_demo_enabled:
        app.state.public_access = PublicAccess(settings)
    # Freeze non-secret code, config, index, and model identities before any run.
    app.state.version_manifest = build_manifest(settings)
    config_hash = app.state.version_manifest["manifest_sha256"][:16]
    run_store = RunStore(settings.agent_trace_db)
    app.state.eval_access = None
    if settings.eval_enabled:
        try:
            access = load_access(settings.eval_access_file)
            evaluation_store = EvaluationStore(run_store)
            evaluation_store.seed(Path(__file__).resolve().parents[2] / "data/eval")
            app.state.evaluation = EvaluationService(evaluation_store)
            app.state.regressions = RegressionService(app.state.evaluation)
            app.state.eval_access = access
        except Exception:
            run_store.close()
            raise RuntimeError("Evaluation initialization failed; check access file and versioned cases") from None
    app.state.agent_runtime = AgentRuntime(
        runs=run_store,
        config_version=f"{settings.agent_build_version}:{config_hash}",
        config_manifest=app.state.version_manifest,
    )
    logger.info(
        "Backend starting | env={} | model={} | cors_origins={} | "
        "llm_timeout_s={} | llm_max_retries={}",
        settings.app_env,
        settings.deepseek_model,
        settings.cors_origin_list,
        settings.deepseek_timeout_s,
        settings.deepseek_max_retries,
    )
    llm = DeepSeekClient(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model,
        timeout_s=settings.deepseek_timeout_s,
        max_retries=settings.deepseek_max_retries,
        proxy=settings.deepseek_proxy,
        output_token_limit=settings.public_max_output_tokens if settings.public_demo_enabled else None,
    ) if settings.deepseek_api_key else None
    app.state.llm = llm
    app.state.chat_service = None

    if settings.rag_enabled and llm is not None:
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
                reference_filter_enabled=settings.rag_reference_filter_enabled,
                reference_filter_min_keep=settings.rag_reference_filter_min_keep,
                reference_filter_overfetch=settings.rag_reference_filter_overfetch,
                numeric_boost_enabled=settings.rag_numeric_boost_enabled,
                numeric_boost_weight=settings.rag_numeric_boost_weight,
                numeric_boost_band=settings.rag_numeric_boost_band,
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
                "reranker={} | top_k_recall={} | top_k={} | "
                "reference_filter={} | overfetch={} | numeric_boost={}",
                chroma_dir,
                settings.rag_collection,
                settings.rag_reranker_model if reranker else "off",
                settings.rag_reranker_top_k_recall if reranker else "n/a",
                chat_top_k,
                "on" if settings.rag_reference_filter_enabled else "off",
                settings.rag_reference_filter_overfetch
                if settings.rag_reference_filter_enabled
                else "n/a",
                # boost only matters on the reranker path
                f"on(w={settings.rag_numeric_boost_weight},"
                f"b={settings.rag_numeric_boost_band})"
                if (reranker and settings.rag_numeric_boost_enabled)
                else "off",
            )
        except Exception:
            logger.warning(
                "RAG failed to initialize; knowledge chat returns 503, file chat remains available",
                exc_info=True,
            )
    else:
        logger.info("RAG or API key unavailable; file chat remains available")

    try:
        yield
    finally:
        if settings.eval_enabled:
            await app.state.regressions.shutdown()
        run_store.close()
        if settings.public_demo_enabled:
            app.state.public_access.db.close()
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
app.include_router(demo.router, prefix="/api", tags=["public-demo"])
app.include_router(chat.router, prefix="/api", tags=["chat"])
app.include_router(files.router, prefix="/api", tags=["files"])
app.include_router(documents.router, prefix="/api", tags=["documents"])
app.include_router(evaluation.router, prefix="/api", tags=["evaluation"])
app.state.public_settings = settings
app.middleware("http")(public_access)


@app.middleware("http")
async def evaluation_no_cache(request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/eval"):
        response.headers["Cache-Control"] = "no-store"
    return response
