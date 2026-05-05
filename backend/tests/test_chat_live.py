from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.getenv("RUN_LIVE_RAG_CHAT"),
    reason="set RUN_LIVE_RAG_CHAT=1 to run real DeepSeek + BGE + Chroma chat",
)


@pytest.mark.asyncio
async def test_live_chat_with_indexed_sample(tmp_path: Path) -> None:
    from src.agent.chat_service import ChatService
    from src.llm.deepseek import DeepSeekClient
    from src.rag import BGEEmbedder, Retriever
    from src.storage import ChromaStore

    store = ChromaStore(tmp_path / "chroma", "live-rag-chat")
    embedder = BGEEmbedder()
    docs = ["氮素淋失主要受降雨量、土壤质地和施肥方式影响。"]
    store.upsert(
        ids=["sample::0000"],
        documents=docs,
        embeddings=embedder.embed_documents(docs),
        metadatas=[
            {
                "source": "data/papers/sample.txt",
                "document_id": "sample",
                "chunk_index": 0,
                "char_start": 0,
                "char_end": len(docs[0]),
            }
        ],
    )
    service = ChatService(
        Retriever(embedder, store),
        DeepSeekClient(
            api_key=os.environ["DEEPSEEK_API_KEY"],
            base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            model=os.environ.get("DEEPSEEK_MODEL", "deepseek-chat"),
        ),
        top_k=1,
        max_context_chars=1000,
        temperature=0.3,
    )

    result = await service.answer("氮素淋失主要受什么因素影响？", k=1)

    assert result.answer
    assert result.citations
    assert result.retrieved_count == 1
