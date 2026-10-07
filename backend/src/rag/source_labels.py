"""Human-readable article labels from the versioned source rename manifest."""
from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[3] / "data/papers/rename_manifest_m16.json"


@lru_cache(maxsize=1)
def labels() -> dict[str, tuple[str, str | None]]:
    items = json.loads(MANIFEST.read_text(encoding="utf-8"))
    result = {}
    for item in items:
        old = Path(item.get("from", "")).stem
        canonical = Path(item.get("to", "")).name
        if not old or not canonical:
            continue
        original = re.sub(r"^\[\d+\]", "", old)
        title, separator, author = original.rpartition("_")
        result[canonical] = (title if separator else original, author if separator else None)
    return result


def article_label(source: str) -> tuple[str | None, str | None]:
    return labels().get(Path(source).name, (None, None))
