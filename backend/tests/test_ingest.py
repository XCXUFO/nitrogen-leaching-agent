from __future__ import annotations

import sys
from pathlib import Path

import pytest

from src.rag.ingest import (
    SUPPORTED_SUFFIXES,
    _load_pdf_text,
    load_text,
    normalize_text,
)


def test_normalize_text_strips_bom() -> None:
    assert normalize_text("﻿hello") == "hello"
    # Non-leading BOM stays untouched (we don't scrub mid-text)
    assert normalize_text("hello﻿world") == "hello﻿world"


def test_normalize_text_unifies_line_endings() -> None:
    assert normalize_text("a\r\nb") == "a\nb"
    assert normalize_text("a\rb") == "a\nb"
    assert normalize_text("a\r\nb\rc\nd") == "a\nb\nc\nd"


def test_normalize_text_collapses_3plus_newlines() -> None:
    assert normalize_text("a\n\n\nb") == "a\n\nb"
    assert normalize_text("a\n\n\n\n\n\nb") == "a\n\nb"
    # Two newlines stay as paragraph break
    assert normalize_text("a\n\nb") == "a\n\nb"
    # Single newline stays as soft break
    assert normalize_text("a\nb") == "a\nb"


def test_normalize_text_does_not_strip_whitespace() -> None:
    # Inline spaces, leading indentation, trailing spaces all preserved
    text = "  leading\n   indented line  \n\ntrailing  "
    assert normalize_text(text) == text


def test_normalize_text_is_idempotent() -> None:
    samples = [
        "",
        "plain text",
        "﻿with bom\r\n\r\nand crlf\n\n\n\nand multi-newline",
        "  spaces  \r\n\r\n\r\nand  more",
        "中文段落一。\n\n\n中文段落二。\r\n\r\n中文段落三。",
    ]
    for s in samples:
        once = normalize_text(s)
        twice = normalize_text(once)
        assert once == twice, f"not idempotent for {s!r}"


def test_load_text_reads_txt(tmp_path: Path) -> None:
    p = tmp_path / "a.txt"
    p.write_text("hello\r\nworld", encoding="utf-8")
    assert load_text(p) == "hello\nworld"


def test_load_text_reads_md_as_plain_text(tmp_path: Path) -> None:
    p = tmp_path / "a.md"
    p.write_text("# Title\n\n- item\n\n```\ncode\n```\n", encoding="utf-8")
    # No markdown parsing — content returned as-is after normalize
    assert load_text(p) == "# Title\n\n- item\n\n```\ncode\n```\n"


def test_load_text_unsupported_suffix_raises(tmp_path: Path) -> None:
    p = tmp_path / "a.docx"
    p.write_bytes(b"fake")
    with pytest.raises(ValueError) as exc_info:
        load_text(p)
    msg = str(exc_info.value)
    assert ".docx" in msg
    for s in SUPPORTED_SUFFIXES:
        assert s in msg


def test_load_text_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_text(tmp_path / "nope.txt")


def test_pdf_path_lazy_imports_pymupdf(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When pymupdf is unavailable, _load_pdf_text raises RuntimeError with
    the standard rag-extra hint. Achieved by inserting a sentinel into
    sys.modules whose attribute access fails, since real `import pymupdf`
    must be the trigger we are gating."""
    # Ensure any cached real import is removed first
    monkeypatch.delitem(sys.modules, "pymupdf", raising=False)
    # Block the import: poison the entry so `import pymupdf` raises ImportError
    monkeypatch.setitem(sys.modules, "pymupdf", None)

    p = tmp_path / "fake.pdf"
    p.write_bytes(b"%PDF-1.4\n")

    with pytest.raises(RuntimeError) as exc_info:
        _load_pdf_text(p)
    msg = str(exc_info.value)
    assert "pymupdf" in msg
    assert "uv sync --extra rag" in msg
