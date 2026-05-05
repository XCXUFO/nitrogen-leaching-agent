from pathlib import Path
from typing import Any


class ChromaStore:
    """Thin wrapper around ``chromadb.PersistentClient``.

    Does not own an Embedder: callers in ``rag/`` must embed first and pass
    raw vectors to :meth:`add` / :meth:`query`. See spec M1.2.1 §3.5.
    """

    def __init__(self, persist_dir: str | Path, collection_name: str) -> None:
        try:
            import chromadb
        except ImportError as exc:
            raise RuntimeError(
                "chromadb is not installed. "
                "Run `uv sync --extra rag` in backend/ before using ChromaStore."
            ) from exc

        self._persist_dir = Path(persist_dir)
        self._persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self._persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=collection_name,
        )

    @property
    def persist_dir(self) -> Path:
        return self._persist_dir

    def add(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        kwargs: dict[str, Any] = {
            "ids": ids,
            "documents": documents,
            "embeddings": embeddings,
        }
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        self._collection.add(**kwargs)

    def upsert(
        self,
        ids: list[str],
        documents: list[str],
        embeddings: list[list[float]],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        """Insert-or-replace by id. Required for idempotent re-indexing —
        ``add`` raises on duplicate ids, ``upsert`` does not.
        """
        kwargs: dict[str, Any] = {
            "ids": ids,
            "documents": documents,
            "embeddings": embeddings,
        }
        if metadatas is not None:
            kwargs["metadatas"] = metadatas
        self._collection.upsert(**kwargs)

    def query(
        self,
        embedding: list[float],
        k: int = 5,
    ) -> dict[str, Any]:
        return self._collection.query(
            query_embeddings=[embedding],
            n_results=k,
        )

    def count(self) -> int:
        return self._collection.count()
