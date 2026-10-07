"""Presentation metadata and allowlisted local originals; independent of retrieval."""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from src.rag.source_labels import article_label

PAPERS_DIR = Path(__file__).resolve().parents[3] / "data/papers"
CATALOG = PAPERS_DIR / "catalog_m16.json"


@lru_cache(maxsize=1)
def documents() -> dict[str, dict]:
    try:
        rows = json.loads(CATALOG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    result = {}
    for row in rows:
        filename = row["file"]
        if Path(filename).name != filename or not filename.endswith(".pdf"):
            continue
        # IDs identify catalog entries, never client-supplied filesystem paths.
        document_id = hashlib.sha256(filename.encode()).hexdigest()[:24]
        try:
            author = article_label(filename)[1]
        except (OSError, ValueError):
            author = None
        # Legacy English download names can end in an article number such as
        # "_022170". Only the Chinese author labels in that manifest are curated.
        if author and not re.search(r"[\u3400-\u9fff]", author):
            author = None
        lead = row.get("lead_author") or ""
        pdf_author = row.get("pdf_meta_author") or ""
        if not author:
            author = pdf_author if lead and lead.casefold() in pdf_author.casefold() else lead
        result[document_id] = {"filename": filename, "title": row.get("title") or None,
                               "author_hint": author or None, "year": row.get("year") or None}
    return result


def document_path(document: dict) -> Path | None:
    root = PAPERS_DIR.resolve()
    path = (root / document["filename"]).resolve()
    if path.parent != root or not path.is_file():
        return None
    return path


def citation_metadata(source: str) -> dict:
    filename = source.replace("\\", "/").rsplit("/", 1)[-1]
    for document_id, document in documents().items():
        if document["filename"] == filename:
            return {key: document[key] for key in ("title", "author_hint", "year")} | {
                "document_id": document_id,
                "document_available": document_path(document) is not None,
            }
    # Never present filename-derived labels as verified article titles.
    return dict(title=None, author_hint=None, year=None, document_id=None, document_available=False)
