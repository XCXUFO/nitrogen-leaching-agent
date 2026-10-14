from __future__ import annotations

import struct
import time
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.testclient import TestClient

from src.agent.chat_service import ChatService
from src.api import chat, files
from src.api.files import FileStore
from src.api.session_documents import inspect_document
from src.api.legacy_word import LegacyWordError, read_legacy_word
from src.llm.base import ChatResult, ChatUsage


def docx_bytes(text: str) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                         f"<w:body><w:p><w:r><w:t>{text}</w:t></w:r></w:p></w:body></w:document>")
    return buffer.getvalue()


def doc_bytes(text: str) -> bytes:
    """A small Word 97 compound file with one UTF-16 text piece."""
    sector = 512
    word = bytearray(sector * 8)
    struct.pack_into("<H", word, 0, 0xA5EC)
    struct.pack_into("<H", word, 6, 0x0804)
    struct.pack_into("<II", word, 0x1A2, 0, 21)
    word[sector:sector + len(text) * 2] = text.encode("utf-16-le")
    table = bytearray(sector * 8)
    table[0] = 2
    struct.pack_into("<I", table, 1, 16)
    struct.pack_into("<II", table, 5, 0, len(text))
    struct.pack_into("<I", table, 15, sector)
    fat = [0xFFFFFFFD, 0xFFFFFFFE, *range(3, 10), 0xFFFFFFFE, *range(11, 18), 0xFFFFFFFE]
    fat_block = struct.pack("<128I", *(fat + [0xFFFFFFFF] * (128 - len(fat))))

    def entry(name: str, kind: int, start: int, size: int) -> bytes:
        data = bytearray(128)
        encoded = (name + "\0").encode("utf-16-le")
        data[:len(encoded)] = encoded
        struct.pack_into("<H", data, 64, len(encoded))
        data[66] = kind
        struct.pack_into("<I", data, 116, start)
        struct.pack_into("<Q", data, 120, size)
        return bytes(data)

    directory = (entry("Root Entry", 5, 0xFFFFFFFE, 0)
                 + entry("WordDocument", 2, 2, len(word))
                 + entry("0Table", 2, 10, len(table)) + bytes(128))
    header = bytearray(sector)
    header[:8] = bytes.fromhex("D0CF11E0A1B11AE1")
    for offset, value in ((26, 3), (28, 0xFFFE), (30, 9), (32, 6)):
        struct.pack_into("<H", header, offset, value)
    for offset, value in ((44, 1), (48, 1), (56, 4096), (60, 0xFFFFFFFE), (68, 0xFFFFFFFE), (76, 0)):
        struct.pack_into("<I", header, offset, value)
    for index in range(1, 109):
        struct.pack_into("<I", header, 76 + 4 * index, 0xFFFFFFFF)
    return bytes(header) + fat_block + directory + word + table


def test_extracts_all_new_document_formats():
    import pymupdf
    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "nitrate leaching evidence")
    samples = {
        "note.txt": ("硝态氮淋失依据".encode(), "硝态氮淋失依据"),
        "note.md": ("# 硝态氮淋失依据".encode(), "硝态氮淋失依据"),
        "paper.pdf": (pdf.tobytes(), "nitrate leaching evidence"),
        "paper.docx": (docx_bytes("硝态氮淋失依据"), "硝态氮淋失依据"),
        "paper.doc": (doc_bytes("硝态氮淋失依据\r"), "硝态氮淋失依据"),
    }
    pdf.close()
    for filename, (raw, expected) in samples.items():
        report = inspect_document(raw, filename)
        assert expected in report["text"]
        assert report["kind"] == "document"


class EmptyRetriever:
    def retrieve(self, _query, _k):
        return []


class RecordingLLM:
    def __init__(self):
        self.messages = []

    async def chat(self, messages, *, temperature=0.3, max_tokens=None):
        self.messages = messages
        return ChatResult(content="文件指出硝态氮淋失值得关注 [1]。", model="test",
                          usage=ChatUsage(prompt_tokens=1, completion_tokens=1, total_tokens=2))


def client_with_documents() -> tuple[TestClient, RecordingLLM]:
    app = FastAPI()
    app.state.file_store = FileStore()
    llm = RecordingLLM()
    app.state.chat_service = ChatService(EmptyRetriever(), llm, top_k=5,
                                         max_context_chars=4000, temperature=0)
    app.include_router(files.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    return TestClient(app), llm


def test_uploaded_text_is_in_next_answer_context_and_cited():
    client, llm = client_with_documents()
    uploaded = client.post("/api/files", params={"filename": "evidence.txt", "session_id": "tab-A"},
                           content="硝态氮淋失值得关注。".encode()).json()
    assert uploaded["status"] == "ready"
    response = client.post("/api/chat", json={"query": "这份文件主要说什么？", "session_id": "tab-A",
                                               "file_ids": [uploaded["file_id"]]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["route"] == "knowledge"
    assert "硝态氮淋失值得关注" in llm.messages[0].content
    assert body["citations"][0]["title"] == "evidence.txt"
    assert body["citations"][0]["document_available"] is False


def test_ten_files_across_uploads_and_session_release():
    client, _ = client_with_documents()
    tokens = []
    for index in range(10):
        response = client.post("/api/files", params={"filename": f"note-{index}.txt", "session_id": "tab-A"},
                               content=f"文件内容 {index}".encode())
        assert response.status_code == 200, response.text
        tokens.append(response.json()["file_id"])
    denied = client.post("/api/files", params={"filename": "extra.txt", "session_id": "tab-A"}, content=b"extra")
    assert denied.status_code == 422
    assert denied.json()["detail"]["code"] == "too_many_files"
    status = client.post("/api/files/status", json={"file_ids": tokens, "session_id": "tab-A"}).json()
    assert all(item["status"] == "available" for item in status["files"])
    wrong = client.post("/api/chat", json={"query": "这份文件主要说什么？", "session_id": "tab-B",
                                            "file_ids": [tokens[0]]})
    assert wrong.status_code == 404
    assert client.post("/api/files/release", json={"file_ids": tokens, "session_id": "tab-B"}).json()["released"] == 0
    assert client.post("/api/files/release", json={"file_ids": tokens, "session_id": "tab-A"}).json()["released"] == 10
    assert client.post("/api/files/status", json={"file_ids": tokens, "session_id": "tab-A"}).json()["files"][0]["status"] == "expired"


def test_status_renews_live_tab_file():
    client, _ = client_with_documents()
    token = client.post("/api/files", params={"filename": "note.txt", "session_id": "tab-A"},
                        content=b"active document").json()["file_id"]
    entry = client.app.state.file_store.entries[token]
    entry.expires_at = time.monotonic() + 1
    assert client.post("/api/files/status", json={"file_ids": [token], "session_id": "tab-A"}).json()["files"][0]["status"] == "available"
    assert entry.expires_at > time.monotonic() + 60


@pytest.mark.parametrize("count", [2, 0xFFFFFFFF])
def test_legacy_word_rejects_cyclic_or_oversized_difat(count):
    raw = bytearray(doc_bytes("test document"))
    # The first FAT sector also claims to be a DIFAT sector pointing to itself.
    struct.pack_into("<II", raw, 68, 0, count)
    struct.pack_into("<I", raw, 1020, 0)
    with pytest.raises(LegacyWordError, match="FAT"):
        read_legacy_word(bytes(raw))


def test_document_capacity_counts_extracted_text_and_releases_it(monkeypatch):
    monkeypatch.setattr(files, "MAX_STORED_BYTES", 1000)
    store = FileStore()
    raw = docx_bytes("证据" * 100)
    profile = inspect_document(raw, "paper.docx")
    token = store.put(raw, profile)
    assert store.entries[token].raw is None
    with pytest.raises(HTTPException) as error:
        store.put(raw, profile)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "file_store_full"
    store.entries[token].expires_at = time.monotonic() - 1
    assert store.put(raw, profile) in store.entries
