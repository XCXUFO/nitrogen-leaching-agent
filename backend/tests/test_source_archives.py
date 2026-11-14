"""Shipped source snapshots retain their original package checksums."""
import hashlib
import json
from pathlib import Path

import pytest


@pytest.mark.parametrize("relative", [
    "2026-11-09-prd-handoff/source/manifest.json",
    "2026-11-11-retrieval-skills-v02/source/文件校验清单_V0.2.json",
])
def test_shipped_source_archive_checksums(relative):
    manifest_path = Path(__file__).resolve().parents[2] / "docs/iterations" / relative
    manifest = json.loads(manifest_path.read_text())
    for entry in manifest["files"]:
        path = manifest_path.parent / entry.get("path", entry.get("file"))
        # Finder metadata from the original package is intentionally Git-ignored.
        if path.name == ".DS_Store":
            continue
        raw = path.read_bytes()
        assert hashlib.sha256(raw).hexdigest() == entry["sha256"], path
        if "bytes" in entry:
            assert len(raw) == entry["bytes"], path
