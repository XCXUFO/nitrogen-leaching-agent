from __future__ import annotations

import hashlib
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

pytest.importorskip("openpyxl")
from tests.test_whcns_results import make_nitrogen
from src.api import chat, files
from src.api.files import FileStore


@pytest.fixture
def client():
    app = FastAPI()
    app.state.chat_service = None  # File flow must work without RAG or an LLM.
    app.state.file_store = FileStore()
    app.include_router(files.router, prefix="/api")
    app.include_router(chat.router, prefix="/api")
    return TestClient(app)


def upload(client, tmp_path, edit=None):
    raw = make_nitrogen(tmp_path / "Nbal_out.xls", edit=edit).read_bytes()
    response = client.post("/api/files", params={"filename": "Nbal_out.xls"}, content=raw)
    assert response.status_code == 200, response.text
    return response.json()["file_id"], raw


def test_upload_chat_max_and_followup_are_traceable(client, tmp_path):
    def edit(sheet):
        sheet["A2"], sheet["A3"] = 100, 101
    token, raw = upload(client, tmp_path, edit)
    response = client.post("/api/chat", json={"query": "硝态氮淋失最大值及对应日序", "file_id": token})
    assert response.status_code == 200
    body = response.json()
    assert body["route"] == "file"
    assert "1.5 kg N ha-1" in body["answer"]
    assert "101" in body["answer"]
    assert body["citations"] == []
    assert body["usage"]["total_tokens"] == 0
    evidence = body["file_evidence"][0]
    assert evidence["sha256"] == hashlib.sha256(raw).hexdigest()
    assert (evidence["cell"], evidence["day_cell"], evidence["model_day"]) == ("Nbal_out!C3", "Nbal_out!A3", 101)
    followup = client.post("/api/chat", json={"query": "leak_NO3 最小值", "file_id": token}).json()
    assert followup["file_evidence"][0]["value"] == 0.5


def test_ties_explicitly_report_first_occurrence(client, tmp_path):
    token, _ = upload(client, tmp_path, lambda s: setattr(s["C2"], "value", 1.5))
    body = client.post("/api/chat", json={"query": "leak_NO3 最大值和最小值", "file_id": token}).json()
    assert len(body["file_evidence"]) == 2
    assert "并列" in body["answer"]
    assert body["file_evidence"][0]["occurrences"] == 2
    assert body["file_evidence"][0]["cell"] == "Nbal_out!C2"


# v2 supports extrema + possible mechanisms; unsupported extra tasks still clarify.
@pytest.mark.parametrize("query", ["帮我看看", "氮淋失最大值", "硝态氮和铵态氮最大值", "硝态氮季节总量", "前10天硝态氮最大值", "硝态氮最大值并比较施肥方案", "第20日硝态氮最大值", "硝态氮浓度最大值", "硝态氮和磷最大值", "硝态氮在灌溉当天最大值", "N-mine"])
def test_ambiguous_or_unsupported_requests_clarify(client, tmp_path, query):
    token, _ = upload(client, tmp_path)
    body = client.post("/api/chat", json={"query": query, "file_id": token}).json()
    assert body["route"] == "clarification"
    assert body["file_evidence"] == []


def test_missing_and_expired_files_never_fall_back_to_rag(client, tmp_path):
    body = client.post("/api/chat", json={"query": "Nbal_out.xls 硝态氮最大值"}).json()
    assert body["route"] == "clarification"
    assert "上传" in body["answer"]
    token, _ = upload(client, tmp_path)
    store = client.app.state.file_store
    store.entries[token].expires_at = time.monotonic() - 1
    for invalid in (token, "not-a-real-token"):
        result = client.post("/api/chat", json={"query": "最大值", "file_id": invalid})
        assert result.status_code == 404
        assert result.json()["detail"]["code"] == "file_not_found"


@pytest.mark.parametrize("filename,raw,status", [("model.exe", b"MZ", 415), ("bad.xlsx", b"bad", 422), ("bad.xls", b"", 422), ("bad.xlsx", b"PK\x03\x04broken", 422)])
def test_invalid_upload_contract(client, filename, raw, status):
    response = client.post("/api/files", params={"filename": filename}, content=raw)
    assert response.status_code == status
    assert "code" in response.json()["detail"]
    assert client.app.state.file_store.entries == {}


def test_v2_schema_error_is_reported_on_use_and_keeps_cell(client, tmp_path):
    raw = make_nitrogen(tmp_path / "invalid.xlsx", edit=lambda s: setattr(s["C3"], "value", "=1+1")).read_bytes()
    result = client.post("/api/files?filename=invalid.xlsx", content=raw)
    assert result.status_code == 200
    assert result.json()["status"] == "pending"
    token = result.json()["file_id"]
    answer = client.post("/api/chat", json={"query": "leak_NO3 最大值", "file_id": token}).json()
    assert answer["outcome"] == "clarification"
    assert "Nbal_out!C3" in answer["answer"]
    assert answer["attachment"]["status"] == "invalid"
    assert answer["file_evidence"] == []
    assert client.app.state.file_store.entries[token].raw is None


def test_upload_size_and_capacity_limits(client, tmp_path, monkeypatch):
    monkeypatch.setattr(files, "MAX_UPLOAD_BYTES", 8)
    assert client.post("/api/files?filename=huge.xls", content=b"123456789").status_code == 413
    monkeypatch.setattr(files, "MAX_UPLOAD_BYTES", 10 * 1024 * 1024)
    monkeypatch.setattr(files, "MAX_FILES", 1)
    token, raw = upload(client, tmp_path)
    assert client.post("/api/files?filename=second.xls", content=raw).status_code == 503
    assert token in client.app.state.file_store.entries


def test_filename_paths_are_stripped(client, tmp_path):
    raw = make_nitrogen(tmp_path / "test.xlsx").read_bytes()
    result = client.post("/api/files", params={"filename": "../../evil/Nbal_out.xlsx"}, content=raw)
    assert result.status_code == 200
    assert result.json()["filename"] == "Nbal_out.xlsx"


def test_temporary_file_is_removed_after_parsing(tmp_path, monkeypatch):
    seen = []
    real = files.summarize_result
    def capture(path):
        seen.append(path)
        return real(path)
    monkeypatch.setattr(files, "summarize_result", capture)
    files.parse_upload(make_nitrogen(tmp_path / "test.xlsx").read_bytes(), "test.xlsx")
    assert seen and not seen[0].exists()


def test_app_can_start_without_llm_key(monkeypatch):
    from src.main import app, settings
    monkeypatch.setattr(settings, "deepseek_api_key", "")
    monkeypatch.setattr(settings, "rag_enabled", False)
    with TestClient(app) as running:
        assert running.get("/api/health").status_code == 200
        assert running.post("/api/chat", json={"query": "分析这个文件"}).json()["route"] == "clarification"


@pytest.mark.parametrize("filename,field,query", [
    ("Nbal_out.xls", "leak_NO3(kg N ha-1)", "硝态氮淋失最大值及对应日序"),
    ("waterbal_out.xls", "Draining(mm)", "Draining最大值及对应日序"),
])
def test_received_files_against_independent_cell_read(client, filename, field, query):
    """Optional local acceptance: source materials are never committed or modified."""
    xlrd = pytest.importorskip("xlrd")
    path = Path(__file__).resolve().parents[2] / "data/raw/whcns/received-2026-09-26/package/模型" / filename
    if not path.exists():
        pytest.skip("Received WHCNS files are only available locally")
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    uploaded = client.post("/api/files", params={"filename": filename}, content=raw)
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["status"] == "pending"
    assert uploaded.json()["rows"] is None
    response = client.post("/api/chat", json={"query": query, "file_id": uploaded.json()["file_id"]})
    assert response.status_code == 200, response.text
    assert response.json()["attachment"]["rows"] == 352
    assert response.json()["attachment"]["status"] == "ready"
    evidence = response.json()["file_evidence"][0]
    book = xlrd.open_workbook(file_contents=raw)
    try:
        sheet = book.sheet_by_name(evidence["sheet"])
        col = sheet.row_values(0).index(field)
        row = max(range(1, sheet.nrows), key=lambda r: sheet.cell_value(r, col))
        assert evidence["value"] == sheet.cell_value(row, col)
        assert evidence["model_day"] == sheet.cell_value(row, 0)
        assert evidence["cell"] == f"{sheet.name}!{xlrd.colname(col)}{row + 1}"
        assert evidence["day_cell"] == f"{sheet.name}!A{row + 1}"
        assert digest == hashlib.sha256(path.read_bytes()).hexdigest() == evidence["sha256"]
        print(f"\n{filename}: {evidence['value']} {evidence['unit']}, day={evidence['model_day']}, "
              f"cell={evidence['cell']}, day_cell={evidence['day_cell']}")
    finally:
        book.release_resources()


def test_explicit_statistic_without_file_clarifies(client):
    body = client.post("/api/chat", json={"query": "硝态氮淋失最大值及对应日序"}).json()
    assert body["route"] == "clarification"


def test_statistics_in_literature_questions_preserve_rag(client):
    response = client.post("/api/chat", json={"query": "论文中硝态氮淋失最大值是多少"})
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "rag_not_configured"
