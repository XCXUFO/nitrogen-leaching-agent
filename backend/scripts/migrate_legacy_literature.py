"""One-time legacy PDF migration; dry run by default, safely resumable by SHA-256.

Run from backend with: .venv/bin/python -m scripts.migrate_legacy_literature
This local maintenance command reuses upload/registration validation. It does
not expose a bulk import API or copy legacy machine tags into the taxonomy.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import fitz
from fastapi import HTTPException
from starlette.requests import Request

from src.api.literature import LiteratureStore, PaperInput, create_paper, now, upload
from src.config import settings
from src.evaluation.contracts import Principal

ROOT = Path(__file__).resolve().parents[2]
ACTOR = Principal(tester_id="legacy-migration", role="developer")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def preflight(catalog: Path, source: Path) -> list[dict]:
    """Validate the entire input before creating a database or importing a row."""
    rows = json.loads(catalog.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not rows:
        raise ValueError("Catalog must be a nonempty list")
    filenames = [row["file"] for row in rows]
    if len(set(filenames)) != len(filenames):
        raise ValueError("Duplicate catalog filenames")
    actual = {p.name for p in source.iterdir() if p.suffix.lower() == ".pdf"}
    if set(filenames) != actual:
        raise ValueError("Catalog and source PDF file lists differ")
    prepared = []
    for row in rows:
        name = row["file"]
        path = source / name
        if Path(name).name != name or "\\" in name or path.is_symlink() or not path.is_file():
            raise ValueError(f"Invalid source path: {name}")
        size = path.stat().st_size
        if size > settings.literature_max_pdf_mb * 1024 * 1024:
            raise ValueError(f"PDF exceeds configured upload limit: {name}")
        with path.open("rb") as stream:
            if stream.read(5) != b"%PDF-":
                raise ValueError(f"Invalid PDF signature: {name}")
        sha = digest(path)
        if row.get("sha256") and row["sha256"] != sha:
            raise ValueError(f"Catalog checksum mismatch: {name}")
        with fitz.open(path) as pdf:
            if pdf.needs_pass or not pdf.page_count:
                raise ValueError(f"Unreadable or protected PDF: {name}")
            # Check page structures without OCR or extracting academic content.
            for number in range(pdf.page_count):
                pdf.load_page(number)
            pages = pdf.page_count
        year = str(row.get("year", ""))
        body = PaperInput(
            title=str(row.get("title") or path.stem).strip(),
            year=int(year) if year.isdigit() and 1000 <= int(year) <= 3000 else None,
            source_note=f"历史文献库迁移；原文件：{name}；旧目录编号：{row.get('ref_id', '未记录')}。",
            internal_note="标题及年份沿用旧目录，待逐篇核对；作者、发表信息及分类标签待补充。",
            action="draft",
        )
        prepared.append({"file": name, "sha256": sha, "size": size,
                         "pages": pages, "legacy_metadata": row, "body": body})
    return prepared


async def migrate(prepared: list[dict], source: Path, database: Path, files: Path, report: Path) -> dict:
    # Preserve each run's mapping, including partial runs, for diagnosis/resume.
    report.parent.mkdir(parents=True, exist_ok=True)
    if report.exists():
        raise ValueError("Report already exists; choose a new report path")
    result = {"started_at": now(), "database": str(database.resolve()),
              "source": str(source.resolve()), "source_count": len(prepared),
              "created": 0, "existing": 0, "failed": 0, "items": []}
    def save_report():
        staging = report.with_suffix(report.suffix + ".tmp")
        staging.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        staging.replace(report)
    save_report()
    db = LiteratureStore(str(database), str(files))
    app = SimpleNamespace(state=SimpleNamespace(literature=db))
    try:
        for entry in prepared:
            item = {k: v for k, v in entry.items() if k != "body"}
            try:
                existing = db.db.execute("SELECT id FROM papers WHERE sha256=? AND deleted=0", (entry["sha256"],)).fetchone()
                if existing:
                    paper = db.get_paper(existing["id"])
                    outcome = "existing"
                else:
                    path = source / entry["file"]
                    with path.open("rb") as stream:
                        async def receive():
                            chunk = stream.read(1024 * 1024)
                            return {"type": "http.request", "body": chunk, "more_body": bool(chunk)}
                        request = Request({"type": "http", "app": app, "headers": []}, receive)
                        uploaded = await upload(request, filename=entry["file"], user=ACTOR)
                    if uploaded["sha256"] != entry["sha256"]:
                        raise ValueError("Source changed after preflight")
                    paper = create_paper(request, entry["body"].model_copy(update={"upload_id": uploaded["upload_id"]}), ACTOR)
                    outcome = "created"
                    # A committed immutable blob now holds the original bytes.
                    (db.root / f"upload-{uploaded['upload_id']}").unlink(missing_ok=True)
                stored = db.root / f"blob-{entry['sha256']}.pdf"
                if not stored.exists():
                    stored = db.root / f"{paper['id']}.pdf"
                if digest(stored) != entry["sha256"]:
                    raise ValueError("Stored PDF checksum mismatch")
                item.update(outcome=outcome, paper_id=paper["id"], registration=paper["registration"], usage=paper["usage"])
                result[outcome] += 1
            except Exception as error:
                detail = error.detail if isinstance(error, HTTPException) else str(error)
                item.update(outcome="failed", error=detail)
                result["failed"] += 1
            result["items"].append(item)
            save_report()
        result["finished_at"] = now()
        result["integrity"] = db.db.execute("PRAGMA integrity_check").fetchone()[0]
        save_report()
        return result
    finally:
        db.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/papers/catalog_m16.json")
    parser.add_argument("--source", type=Path, default=ROOT / "data/papers")
    parser.add_argument("--db", type=Path, default=Path(settings.literature_db))
    parser.add_argument("--files", type=Path, default=Path(settings.literature_files_dir))
    parser.add_argument("--report", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.apply and not args.report:
        parser.error("--apply requires --report")
    prepared = preflight(args.catalog, args.source)
    if not args.apply:
        print(json.dumps({"dry_run": True, "source_count": len(prepared),
                          "unique_files": len({p['sha256'] for p in prepared}),
                          "total_bytes": sum(p["size"] for p in prepared),
                          "database": str(args.db), "registration": "draft", "usage": "normal", "tag_ids": []}))
        return
    result = asyncio.run(migrate(prepared, args.source, args.db, args.files, args.report))
    print(json.dumps({k: v for k, v in result.items() if k != "items"}, ensure_ascii=False))
    if result["failed"] or result["integrity"] != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
