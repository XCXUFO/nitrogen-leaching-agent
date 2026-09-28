"""Create a local material inventory and page-addressable manual extraction.

Does not extract or execute the archive, index into RAG, or publish its contents.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path, PurePosixPath
from zipfile import ZipFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.model_tools.workbooks import read_workbook


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    import fitz

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    raw = args.raw_dir
    archive = raw / "模型.zip"
    manual = raw / "WHCNS用户手册202508.pdf"
    package = raw / "package" / "模型"
    members = []
    with ZipFile(archive) as zipped:
        for member in zipped.infolist():
            if member.is_dir():
                continue
            contents = zipped.read(member)
            members.append({"path": member.filename, "bytes": len(contents),
                            "sha256": hashlib.sha256(contents).hexdigest(),
                            "archive_modified_at": list(member.date_time)})
    expected = {PurePosixPath(m["path"]).name: m for m in members
                if PurePosixPath(m["path"]).parent == PurePosixPath("模型")
                and PurePosixPath(m["path"]).suffix.lower() in (".xls", ".xlsx")}
    if not expected:
        raise ValueError("archive contains no workbooks in 模型/")
    missing = [name for name in expected if not (package / name).is_file()]
    if missing:
        raise ValueError(f"extract the original archive first; missing workbooks: {', '.join(missing)}")
    books = []
    for name, member in sorted(expected.items()):
        path = package / name
        book = read_workbook(path)
        if member["sha256"] != book["sha256"]:
            raise ValueError(f"extracted file differs from archive: {path.name}")
        for sheet in book["sheets"]:
            rows = sheet.pop("rows")
            sheet["preview_rows"] = rows[:3]
        books.append(book)
    with fitz.open(manual) as pdf:
        pages = [{"source_id": "whcns-manual-202508", "pdf_page": i + 1,
                  "text": page.get_text()} for i, page in enumerate(pdf)]
    manifest = {
        "schema_version": 1, "review_status": "pending", "public_display_permission": "pending",
        "archive": {"file": archive.name, "sha256": digest(archive), "members": members},
        "manual": {"file": manual.name, "source_id": "whcns-manual-202508",
                   "sha256": digest(manual), "pdf_pages": len(pages)},
        "workbooks": books, "executable_run": False,
        "case_pairing": "unconfirmed; archive timestamps alone do not establish shared run origin",
    }
    # A run directory is immutable: a second invocation must choose a new path.
    args.out.mkdir(parents=True, exist_ok=False)
    for filename, value in (("manifest.json", manifest), ("manual.pages.json", pages)):
        with (args.out / filename).open("x", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
    print(f"Inventoried {len(members)} archive files, {len(books)} workbooks, {len(pages)} PDF pages into {args.out}")


if __name__ == "__main__":
    main()
