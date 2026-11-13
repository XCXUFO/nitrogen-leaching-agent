"""Original attachments retained with run history, separate from live file leases."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path
from tempfile import TemporaryDirectory

from src.api.session_documents import inspect_document
from src.model_tools.workbooks import read_workbook


class RunAttachments:
    def __init__(self, connection, lock):
        self.db, self.lock = connection, lock
        with self.lock, self.db:
            self.db.execute("""CREATE TABLE IF NOT EXISTS run_attachment_blobs (
                sha256 TEXT PRIMARY KEY, content BLOB NOT NULL)""")

    def put(self, raw: bytes, sha256: str):
        if hashlib.sha256(raw).hexdigest() != sha256:
            raise ValueError("Attachment fingerprint mismatch")
        with self.lock, self.db:
            self.db.execute("INSERT OR IGNORE INTO run_attachment_blobs VALUES (?,?)", (sha256, raw))

    def get(self, sha256: str) -> bytes | None:
        with self.lock:
            row = self.db.execute("SELECT content FROM run_attachment_blobs WHERE sha256=?", (sha256,)).fetchone()
        return row[0] if row else None


def preview_attachment(raw: bytes, filename: str, file_format: str, *, page=1, sheet=0, offset=0, limit=100):
    if file_format == "pdf":
        import pymupdf
        with pymupdf.open(stream=raw, filetype="pdf") as document:
            if not 1 <= page <= len(document):
                raise ValueError("所选页不存在。")
            selected = document[page - 1]
            scale = min(1.5, 1200 / max(selected.rect.width, selected.rect.height, 1))
            pixmap = selected.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return {"kind": "pdf", "filename": filename, "page": page, "page_count": len(document),
                    "image": "data:image/png;base64," + base64.b64encode(pixmap.tobytes("png")).decode("ascii")}
    if file_format in {"xls", "xlsx"}:
        with TemporaryDirectory(prefix="run-attachment-preview-") as directory:
            path = Path(directory) / ("attachment." + file_format)
            path.write_bytes(raw)
            book = read_workbook(path, reject_cell_errors=False)
        if not 0 <= sheet < len(book["sheets"]):
            raise ValueError("所选工作表不存在。")
        selected = book["sheets"][sheet]
        return {"kind": "table", "filename": filename, "sheet": sheet,
                "sheets": [item["name"] for item in book["sheets"]], "offset": offset,
                "total_rows": selected["nrows"], "total_columns": selected["ncols"],
                "rows": [row[:50] for row in selected["rows"][offset:offset + limit]],
                "columns_truncated": selected["ncols"] > 50}
    profile = inspect_document(raw, "attachment." + file_format)
    return {"kind": "text", "filename": filename, "text": profile["text"]}
