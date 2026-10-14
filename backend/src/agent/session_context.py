"""Select small, traceable excerpts from documents in the current chat session."""
from __future__ import annotations

import re

from src.rag.chunker import chunk_text
from src.rag.retriever import RetrievalResult


def _terms(query: str) -> set[str]:
    words = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]+", query.casefold())
    terms = {word for word in words if len(word) > 1}
    for word in words:
        if re.fullmatch(r"[\u3400-\u9fff]+", word):
            terms.update(word[index:index + 2] for index in range(len(word) - 1))
    return terms


def select_session_chunks(query: str, documents: list[dict], *, limit: int = 18) -> list[RetrievalResult]:
    """Include one passage per file, then use the remaining budget for matching passages."""
    terms = _terms(query)
    selected = []
    extra = []
    for document in documents[:10]:
        source = f"session://{document['sha256']}/{document['file']}"
        chunks = chunk_text(document["text"], document["sha256"], source,
                            target_size=350, max_size=500, overlap=50)
        ranked = sorted(enumerate(chunks), key=lambda pair: (
            -sum(term in pair[1].text.casefold() for term in terms), pair[0]))
        for position, (_, chunk) in enumerate(ranked):
            score = sum(term in chunk.text.casefold() for term in terms)
            hit = RetrievalResult(chunk_id=chunk.chunk_id, document=chunk.text,
                                  score=float(score), metadata=chunk.metadata)
            (selected if position == 0 else extra).append(hit)
    extra.sort(key=lambda hit: -hit.score)
    return (selected + extra)[:limit]
