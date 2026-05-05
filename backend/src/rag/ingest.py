from __future__ import annotations

import re
from pathlib import Path

SUPPORTED_SUFFIXES = frozenset({".txt", ".md", ".pdf"})

_BOM = "﻿"
_MULTI_NEWLINE = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    """Apply minimal normalization: BOM, line endings, paragraph collapse.

    Three operations only — see M1.2.3 spec §3.3 for what is intentionally
    NOT done (no NFC/NFD, no full-width conversion, no whitespace trim,
    no header/footer/citation cleanup). Idempotent by construction.
    """
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _MULTI_NEWLINE.sub("\n\n", text)
    return text


def load_text(path: str | Path) -> str:
    """Read a local file and return normalized plain text.

    Suffix dispatch:
      - .txt / .md → utf-8 read
      - .pdf       → PyMuPDF (lazy-imported; requires `uv sync --extra rag`)
      - other      → ValueError
    """
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"file not found: {p}")

    suffix = p.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(
            f"unsupported file suffix: {suffix!r}; "
            f"supported = {sorted(SUPPORTED_SUFFIXES)}"
        )

    if suffix in {".txt", ".md"}:
        raw = p.read_text(encoding="utf-8")
    else:  # .pdf
        raw = _load_pdf_text(p)

    return normalize_text(raw)


def _load_pdf_text(path: Path) -> str:
    try:
        import pymupdf
    except ImportError as exc:
        raise RuntimeError(
            "pymupdf is not installed. "
            "Run `uv sync --extra rag` in backend/ before loading PDF files."
        ) from exc

    doc = pymupdf.open(str(path))
    try:
        pages = [page.get_text("text") for page in doc]
    finally:
        doc.close()
    return "\n\n".join(pages)
