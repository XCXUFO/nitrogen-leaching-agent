"""Receive a supplemental export and write a local independent audit receipt."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from src.evaluation.material_handoff import audit_materials, digest, receive_archive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archive", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/var/handoff/2026-11-10-materials")
    args = parser.parse_args()
    created = receive_archive(args.archive, args.output / "source")
    receipt = audit_materials(args.output / "source", ROOT / "docs/iterations/2026-11-09-prd-handoff/source")
    receipt.update(archive_sha256=digest(args.archive), source_directory=str((args.output / "source").resolve()))
    target = args.output / "receipt.json"
    raw = json.dumps(receipt, ensure_ascii=False, indent=2)
    if target.exists() and target.read_text(encoding="utf-8") != raw:
        raise ValueError("immutable receipt changed")
    if not target.exists():
        target.write_text(raw, encoding="utf-8")
    print(json.dumps({"created": created, "receipt": str(target), **{key: receipt[key] for key in (
        "verified_files", "original_conversations", "original_runs", "pdfs", "pdf_pages", "cases", "new_model_runs")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
