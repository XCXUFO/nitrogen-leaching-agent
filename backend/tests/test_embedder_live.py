import os

import pytest

from src.config import settings
from src.rag import BGEEmbedder


pytestmark = pytest.mark.skipif(
    not os.environ.get("RUN_LIVE_EMBED"),
    reason=(
        "set RUN_LIVE_EMBED=1 to run live BGE smoke "
        "(requires `uv sync --extra rag`; downloads ~1.3GB on first run)"
    ),
)


def test_bge_embedder_live_embed_query_returns_1024_dim_vector() -> None:
    embedder = BGEEmbedder(model_id=settings.embedding_model)
    vector = embedder.embed_query("稻田氮素淋失风险评估")
    assert len(vector) == embedder.dim == 1024
    assert any(abs(x) > 1e-6 for x in vector)
