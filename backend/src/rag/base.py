from abc import ABC, abstractmethod


class Embedder(ABC):
    """Text embedding abstraction.

    Sync interface: implementations are CPU/GPU bound, not I/O. Async callers
    must dispatch via ``asyncio.to_thread(...)`` (see spec M1.2.1 §6).
    """

    @property
    @abstractmethod
    def dim(self) -> int:
        """Embedding dimension.

        Contract: must be available without triggering model load or a probe
        embed. Implementations should expose a static constant or a value
        derived from configuration, never ``len(embed_query("x"))``.
        """

    @abstractmethod
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        """Vectorize a batch of documents. Returned order matches input."""

    @abstractmethod
    def embed_query(self, text: str) -> list[float]:
        """Vectorize a single query. Kept separate from ``embed_documents`` so
        future implementations can apply asymmetric query/passage prefixes."""
