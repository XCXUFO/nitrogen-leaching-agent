"""Small, versioned extractive evidence set for reviewed maize questions."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


PATH = Path(__file__).resolve().parents[3] / "data/eval/maize-mechanism-excerpts.v1.json"


@lru_cache(maxsize=1)
def excerpts() -> dict:
    return json.loads(PATH.read_text(encoding="utf-8"))
