from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.rag.retriever import RetrievalResult

_AUTHOR_LINE_RE = re.compile(
    r"^\s*(?:\d{1,3}[\.\)]\s*)?[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'`-]+,\s*"
    r"(?:[A-Z]\.|[A-Z][A-Za-zÀ-ÖØ-öø-ÿ'`-]+)"
)
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}[a-z]?\b")
_PAGE_RANGE_RE = re.compile(r"\b\d{1,5}\s*[–-]\s*\d{1,5}\b")
_DOI_OR_URL_RE = re.compile(r"(?:https?://|doi\.org/|10\.\d{4,9}/)", re.IGNORECASE)
_JOURNAL_HINT_RE = re.compile(
    r"\b(?:Agric\.|Agricultural|Water Manage\.|Environ\.|Environment|"
    r"Hydrol\.|Hydrology|J\.|Journal|Soil|Sci\.|Science|Res\.|Research|"
    r"Commun\.|Phys\.|Chem\.|Earth|Field Crops Res\.)\b",
    re.IGNORECASE,
)
_BODY_EVIDENCE_HINT_RE = re.compile(
    r"\b(?:Fig\.|Figure|Table|Results|Discussion|Materials and methods|"
    r"kg\s+N\s+ha|mg\s+N\s+L|treatment|observed|measured|simulated|"
    r"leaching|runoff|seepage|drainage)\b",
    re.IGNORECASE,
)


def is_reference_chunk(text: str) -> bool:
    """Heuristically detect bibliography/reference-list chunks.

    The classifier intentionally requires multiple bibliography signals. Body
    paragraphs often cite papers too, so a single year or journal abbreviation
    is not enough to drop a chunk.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return False

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    author_lines = sum(1 for line in lines if _AUTHOR_LINE_RE.search(line))
    years = len(_YEAR_RE.findall(normalized))
    page_ranges = len(_PAGE_RANGE_RE.findall(normalized))
    journal_hints = len(_JOURNAL_HINT_RE.findall(normalized))
    doi_or_url = bool(_DOI_OR_URL_RE.search(normalized))
    body_hints = len(_BODY_EVIDENCE_HINT_RE.findall(normalized))

    starts_in_reference_section = normalized.lower().startswith(
        ("references ", "reference ")
    )

    if starts_in_reference_section and (years >= 1 or journal_hints >= 1):
        return True
    # Chinese bibliographies often use [10] rather than an English author line.
    # A title containing "leaching" is not a body observation.
    if re.search(r"(?m)^\s*\[\d{1,3}\]", text) and years >= 2 and (journal_hints >= 1 or "[J]" in text):
        return True
    if doi_or_url and (years >= 1 or journal_hints >= 1 or author_lines >= 1):
        return True
    if author_lines >= 1 and years >= 1 and (journal_hints >= 1 or page_ranges >= 1):
        return True
    if author_lines >= 2 and years >= 2:
        return True
    if years >= 3 and journal_hints >= 2 and page_ranges >= 1:
        return True
    if years >= 2 and journal_hints >= 2 and body_hints == 0:
        return True

    return False


def filter_reference_chunks(
    results: list["RetrievalResult"],
    *,
    min_keep: int,
) -> tuple[list["RetrievalResult"], list["RetrievalResult"]]:
    """Drop likely reference-list chunks while preserving a minimum candidate set."""
    if not results:
        return [], []
    if min_keep <= 0:
        raise ValueError(f"min_keep must be positive, got {min_keep}")

    classifications: list[tuple[RetrievalResult, bool]] = []
    for result in results:
        classifications.append((result, is_reference_chunk(result.document)))

    kept = [result for result, is_ref in classifications if not is_ref]
    removed = [result for result, is_ref in classifications if is_ref]
    if len(kept) >= min_keep:
        return kept, removed

    restore_count = min_keep - len(kept)
    restored_ids = {id(result) for result in removed[:restore_count]}
    final: list[RetrievalResult] = []
    still_removed: list[RetrievalResult] = []
    for result, is_ref in classifications:
        if not is_ref or id(result) in restored_ids:
            final.append(result)
        else:
            still_removed.append(result)
    return final, still_removed
