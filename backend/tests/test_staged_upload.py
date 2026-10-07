from __future__ import annotations

import asyncio
import time

import pytest

from src.api import files
from src.model_tools.whcns_results import summarize_result
from tests.test_agent_runtime import ask, client, upload
from tests.test_whcns_results import make_nitrogen


def test_upload_is_pending_and_knowledge_does_not_trigger_domain_validation(client, tmp_path, monkeypatch):
    def unexpected(*args):
        pytest.fail("knowledge question must not validate an unused attachment")
    monkeypatch.setattr(files, "parse_upload", unexpected)
    token = upload(client, tmp_path, edit=lambda s: setattr(s["C1"], "value", "leak_NO3(mg L-1)"))
    entry = client.app.state.file_store.entries[token]
    assert entry.report is None and entry.error is None and entry.raw
    assert ask(client, "氮素淋失有哪些影响因素？", file=token).json()["route"] == "knowledge"
    assert entry.state()["status"] == "pending"


@pytest.mark.parametrize("cell,value,location", [("C1", "leak_NO3(mg L-1)", "单位不匹配"), ("C3", "text", "Nbal_out!C3"), ("C3", "=1+1", "Nbal_out!C3"), ("C3", "#DIV/0!", "Nbal_out!C3")])
def test_invalid_content_is_explained_on_use_and_cached(client, tmp_path, monkeypatch, cell, value, location):
    calls = []
    real = files.parse_upload
    def parse(*args):
        calls.append(1)
        return real(*args)
    monkeypatch.setattr(files, "parse_upload", parse)
    token = upload(client, tmp_path, edit=lambda s: setattr(s[cell], "value", value))
    assert calls == []
    for _ in range(2):
        result = ask(client, "leak_NO3 最大值", file=token).json()
        assert result["route"] == "clarification"
        assert location in result["answer"]
        assert result["attachment"]["status"] == "invalid"
        assert result["file_evidence"] == []
    assert len(calls) == 1
    assert client.app.state.file_store.entries[token].raw is None


def test_ready_summary_is_reused_and_pending_raw_bytes_are_released(client, tmp_path, monkeypatch):
    calls = []
    real = files.parse_upload
    def parse(*args):
        calls.append(1)
        return real(*args)
    monkeypatch.setattr(files, "parse_upload", parse)
    token = upload(client, tmp_path)
    first = ask(client, "leak_NO3 最大值", file=token).json()
    second = ask(client, "那最小值呢？", file=token).json()
    assert first["attachment"]["status"] == second["attachment"]["status"] == "ready"
    assert first["attachment"]["rows"] == 2
    assert len(calls) == 1 and client.app.state.file_store.entries[token].raw is None


def test_new_invalid_attachment_cannot_fall_back_to_old_valid_one(client, tmp_path):
    old = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=old)
    new = upload(client, tmp_path, name="bad.xlsx", edit=lambda s: setattr(s["C3"], "value", "text"))
    result = ask(client, "那最小值呢？", file=new).json()
    assert result["file_evidence"] == [] and result["attachment"]["status"] == "invalid"


def test_aggregate_pending_bytes_are_bounded_and_expiry_reclaims_capacity(client, tmp_path, monkeypatch):
    raw = make_nitrogen(tmp_path / "test.xlsx").read_bytes()
    monkeypatch.setattr(files, "MAX_STORED_BYTES", len(raw))
    first = client.post("/api/files?filename=first.xlsx", content=raw)
    assert first.status_code == 200
    token = first.json()["file_id"]
    assert client.post("/api/files?filename=second.xlsx", content=raw).status_code == 503
    client.app.state.file_store.entries[token].expires_at = time.monotonic() - 1
    assert client.post("/api/files?filename=second.xlsx", content=raw).status_code == 200
    assert token not in client.app.state.file_store.entries


def test_expiry_during_validation_cannot_revive_the_attachment(client, tmp_path, monkeypatch):
    token = upload(client, tmp_path)
    real = files.parse_upload
    def parse(*args):
        report = real(*args)
        client.app.state.file_store.entries[token].expires_at = time.monotonic() - 1
        return report
    monkeypatch.setattr(files, "parse_upload", parse)
    response = ask(client, "leak_NO3 最大值", file=token)
    assert response.status_code == 404
    assert token not in client.app.state.file_store.entries


def test_process_restart_invalidates_old_file_capability(client, tmp_path):
    token = upload(client, tmp_path)
    assert client.app.state.file_store.get(token).filename.endswith('.xlsx')
    client.app.state.file_store = files.FileStore()  # New process has no old bearer capabilities.
    response = ask(client, "那最小值呢？", file=token)
    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "file_not_found"


@pytest.mark.asyncio
async def test_concurrent_inspection_of_one_file_is_computed_once(tmp_path, monkeypatch):
    path = make_nitrogen(tmp_path / "test.xlsx")
    raw = path.read_bytes()
    store = files.FileStore()
    token = store.put(raw, files.inspect_upload(raw, path.name))
    started, release = asyncio.Event(), asyncio.Event()
    calls = []
    async def slow(*args):
        calls.append(1)
        started.set()
        await release.wait()
        return summarize_result(path)
    monkeypatch.setattr(files, "finish_thread", slow)
    one = asyncio.create_task(store.inspect(token))
    await asyncio.wait_for(started.wait(), 3)
    two = asyncio.create_task(store.inspect(token))
    release.set()
    results = await asyncio.gather(one, two)
    assert results[0] == results[1] and len(calls) == 1


def test_status_uses_server_expiry_without_parsing_renewing_or_creating_runs(client, tmp_path, monkeypatch):
    from types import SimpleNamespace
    tick = [100.0]
    monkeypatch.setattr(files, 'time', SimpleNamespace(monotonic=lambda: tick[0]))
    token = upload(client, tmp_path)
    store = client.app.state.file_store
    tick[0] += 29 * 60
    store.get(token)  # A successful use extends the server deadline.
    deadline = store.entries[token].expires_at
    tick[0] += 2 * 60
    result = client.post('/api/files/status', json={'file_ids': [token, 'missing']})
    assert result.status_code == 200 and result.headers['cache-control'] == 'no-store'
    assert result.json()['files'] == [{'file_id': token, 'status': 'available'}, {'file_id': 'missing', 'status': 'expired'}]
    assert store.entries[token].expires_at == deadline and store.entries[token].report is None
    tick[0] = deadline + 1
    assert client.post('/api/files/status', json={'file_ids': [token]}).json()['files'][0]['status'] == 'expired'
    assert token not in store.entries
    assert client.post('/api/files/status', json={'file_ids': ['x'] * 6}).status_code == 422
    assert client.post('/api/files/status', json={'file_ids': ['']}).status_code == 422
