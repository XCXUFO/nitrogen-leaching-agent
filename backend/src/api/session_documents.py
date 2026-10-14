"""Extract bounded plain text from documents attached to a visitor conversation."""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import xml.etree.ElementTree as ET
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import BadZipFile, ZipFile

from src.rag.ingest import normalize_text
from src.api.legacy_word import LegacyWordError, read_legacy_word

DOCUMENT_SUFFIXES = frozenset({".txt", ".md", ".pdf", ".doc", ".docx"})
MAX_TEXT_CHARS = 300_000
WORD_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class DocumentError(ValueError):
    pass


def inspect_document(raw: bytes, filename: str) -> dict:
    suffix = Path(filename).suffix.lower()
    try:
        if suffix in {".txt", ".md"}:
            text = raw.decode("utf-8-sig")
        elif suffix == ".pdf":
            text = _pdf_text(raw)
        elif suffix == ".docx":
            text = _docx_text(raw)
        elif suffix == ".doc":
            text = _doc_text(raw)
        else:
            raise DocumentError("不支持的文档格式。")
    except UnicodeError as exc:
        raise DocumentError("文本文件需使用 UTF-8 编码。") from exc
    text = normalize_text(text).strip()
    if not text:
        raise DocumentError("未读取到文字内容，请检查文件或上传可复制文字的版本。")
    if len(text) > MAX_TEXT_CHARS:
        raise DocumentError("文档文字过长，请拆分后上传。")
    return {"file": filename, "sha256": hashlib.sha256(raw).hexdigest(),
            "format": suffix.removeprefix("."), "kind": "document", "rows": None, "text": text}


def _pdf_text(raw: bytes) -> str:
    try:
        import pymupdf
        with pymupdf.open(stream=raw, filetype="pdf") as document:
            if document.needs_pass:
                raise DocumentError("PDF 已加密，请上传未加密版本。")
            if len(document) > 300:
                raise DocumentError("PDF 页数超过 300 页，请拆分后上传。")
            return "\n\n".join(page.get_text("text") for page in document)
    except DocumentError:
        raise
    except Exception as exc:
        raise DocumentError("PDF 无法读取，请检查文件是否损坏。") from exc


def _docx_text(raw: bytes) -> str:
    try:
        with ZipFile(BytesIO(raw)) as archive:
            if len(archive.infolist()) > 2000 or sum(item.file_size for item in archive.infolist()) > 40 * 1024 * 1024:
                raise DocumentError("Word 文件内容过大，请拆分后上传。")
            xml = archive.read("word/document.xml")
        if b"<!DOCTYPE" in xml.upper():
            raise DocumentError("Word 文件包含不支持的 XML 声明。")
        root = ET.fromstring(xml)
        paragraphs = []
        for paragraph in root.iter(f"{WORD_NS}p"):
            pieces = []
            for node in paragraph.iter():
                if node.tag == f"{WORD_NS}t" and node.text:
                    pieces.append(node.text)
                elif node.tag == f"{WORD_NS}tab":
                    pieces.append("\t")
                elif node.tag == f"{WORD_NS}br":
                    pieces.append("\n")
            if pieces:
                paragraphs.append("".join(pieces))
        return "\n".join(paragraphs)
    except DocumentError:
        raise
    except (BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        raise DocumentError("Word 文件无法读取，请检查 .docx 是否损坏。") from exc


def _doc_text(raw: bytes) -> str:
    converter = shutil.which("antiword")
    if converter:
        with TemporaryDirectory(prefix="session-doc-") as directory:
            path = Path(directory) / "document.doc"
            path.write_bytes(raw)
            try:
                result = subprocess.run([converter, "-m", "UTF-8.txt", str(path)], capture_output=True,
                                        timeout=20, check=False, cwd=directory)
                if result.returncode == 0 and result.stdout.strip():
                    return result.stdout.decode("utf-8", errors="replace")
            except (OSError, subprocess.TimeoutExpired):
                pass
    try:
        return read_legacy_word(raw)
    except LegacyWordError as exc:
        raise DocumentError(".doc 文件无法读取，请检查文件或另存为 .docx 后重试。") from exc
