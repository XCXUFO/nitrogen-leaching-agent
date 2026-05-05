"""Unit tests for index_papers.derive_document_id.

The script is invoked as ``python scripts/index_papers.py`` so it lives
outside ``src/``. We import it via the same sys.path injection the script
itself uses at startup.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_ROOT = Path(__file__).resolve().parents[1]
_SCRIPTS = _BACKEND_ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

from index_papers import derive_document_id  # noqa: E402


def test_derive_document_id_strips_suffix(tmp_path: Path) -> None:
    f = tmp_path / "papers" / "sample.txt"
    f.parent.mkdir()
    f.write_text("x", encoding="utf-8")
    assert derive_document_id(f, tmp_path) == "papers/sample"


def test_derive_document_id_is_stable_across_calls(tmp_path: Path) -> None:
    f = tmp_path / "a" / "b.pdf"
    f.parent.mkdir()
    f.write_text("x", encoding="utf-8")
    ids = {derive_document_id(f, tmp_path) for _ in range(5)}
    assert len(ids) == 1


def test_derive_document_id_normalizes_unsafe_chars(tmp_path: Path) -> None:
    f = tmp_path / "a b" / "c@d#e.txt"
    f.parent.mkdir()
    f.write_text("x", encoding="utf-8")
    # Spaces, '@', '#' must be replaced; '/', '-', '_' kept; ascii letters kept
    assert derive_document_id(f, tmp_path) == "a_b/c_d_e"


def test_derive_document_id_keeps_chinese_chars(tmp_path: Path) -> None:
    f = tmp_path / "论文" / "氮素淋失_2024.pdf"
    f.parent.mkdir()
    f.write_text("x", encoding="utf-8")
    assert derive_document_id(f, tmp_path) == "论文/氮素淋失_2024"


def test_derive_document_id_distinct_paths_distinct_ids(tmp_path: Path) -> None:
    a = tmp_path / "a" / "x.txt"
    b = tmp_path / "b" / "x.txt"
    a.parent.mkdir()
    b.parent.mkdir()
    a.write_text("x", encoding="utf-8")
    b.write_text("y", encoding="utf-8")
    assert derive_document_id(a, tmp_path) != derive_document_id(b, tmp_path)


def test_derive_document_id_outside_repo_root_raises(tmp_path: Path) -> None:
    """Paths outside repo_root must be rejected to avoid '..'-based id pollution."""
    repo = tmp_path / "repo"
    outside = tmp_path / "elsewhere" / "x.txt"
    repo.mkdir()
    outside.parent.mkdir()
    outside.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        derive_document_id(outside, repo)
