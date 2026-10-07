from __future__ import annotations

import asyncio
import json
import sqlite3
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent.contracts import Route
from src.agent.runtime import AgentRuntime
from src.agent.skills import build_registry
from src.agent.state import StateStore
from src.api import chat, files
from src.storage.run_store import RunStore
from tests.test_chat_route import FakeChatService
from tests.test_whcns_results import make_nitrogen


@pytest.fixture
def client():
    app = FastAPI()
    app.state.chat_service = FakeChatService()
    app.state.file_store = files.FileStore()
    app.state.agent_runtime = AgentRuntime(config_version="test-build:test-config")
    app.include_router(chat.router, prefix="/api")
    app.include_router(files.router, prefix="/api")
    with TestClient(app) as value:
        yield value
    app.state.agent_runtime.runs.close()


def upload(client, tmp_path, *, name="Nbal_out.xlsx", edit=None):
    data = make_nitrogen(tmp_path / name, edit=edit).read_bytes()
    result = client.post("/api/files", params={"filename": name}, content=data)
    assert result.status_code == 200, result.text
    return result.json()["file_id"]


def ask(client, query, *, session="test-session", file=None, history=None):
    payload = {"query": query, "session_id": session}
    if file is not None:
        payload["file_id"] = file
    if history is not None:
        payload["history"] = history
    return client.post("/api/chat", json=payload)


@pytest.mark.parametrize("query", ["氮素淋失主要受哪些因素影响？", "论文中硝态氮淋失最大值是多少", "leak_NO3 是什么？", "灌溉管理需要关注什么？", "说说土壤质地", "解释硝态氮最大值的意义"])
def test_attached_file_does_not_override_knowledge_intent(client, query):
    # Even an expired token must not block a question which does not need that file.
    result = ask(client, query, file="expired-token")
    assert result.status_code == 200
    body = result.json()
    assert body["agent_route"] == "KNOWLEDGE"
    assert body["file_evidence"] == []
    assert client.app.state.chat_service.calls[0][0] == query
    trace = client.app.state.agent_runtime.runs.get(body["run_id"])
    assert [call.skill for call in trace.tool_calls] == ["knowledge_search"]
    assert "expired-token" not in trace.model_dump_json()


def test_absent_session_id_is_stateless_unless_returned_id_is_reused(client, tmp_path):
    token = upload(client, tmp_path)
    first = client.post("/api/chat", json={"query": "leak_NO3 最大值", "file_id": token}).json()
    independent = client.post("/api/chat", json={"query": "那最小值呢", "file_id": token}).json()
    assert independent["route"] == "clarification"
    followup = ask(client, "那最小值呢", session=first["conversation_id"], file=token).json()
    assert followup["route"] == "file"


def test_file_followup_inherits_verified_metric_and_keeps_provenance(client, tmp_path):
    token = upload(client, tmp_path)
    first = ask(client, "硝态氮淋失最大值及对应日序", file=token).json()
    result = ask(client, "那最小值呢？", file=token).json()
    assert result["agent_route"] == "FILE_ANALYSIS"
    value = result["file_evidence"][0]
    assert (value["value"], value["cell"], value["day_cell"]) == (0.5, "Nbal_out!C2", "Nbal_out!A2")
    assert value["sha256"] == first["file_evidence"][0]["sha256"]
    assert result["usage"]["total_tokens"] == 0
    assert client.app.state.chat_service.calls == []
    trace = client.app.state.agent_runtime.runs.get(result["run_id"])
    assert trace.decision.reason_code == "inherited_metric"
    assert trace.evidence[0].evidence_id == result["evidence"][0]["evidence_id"]
    assert trace.evidence[0].location["cell"] == value["cell"]
    assert trace.config_version == "test-build:test-config"
    assert token not in trace.model_dump_json()


@pytest.mark.parametrize("query", [
    "硝态氮最大值及日序",
    "硝态氮淋失的最大值及对应模型日序",
    "请查看 Nbal_out.xls 中硝态氮最大值及日序",
    "leak_NO3 的最大值及对应日序",
])
def test_real_nitrogen_table_phrasings_keep_numeric_evidence(client, query):
    from pathlib import Path
    source = Path(__file__).resolve().parents[2] / "data/demo/Nbal_out.xls"
    uploaded = client.post("/api/files", params={"filename": "Nbal_out.xls"}, content=source.read_bytes())
    assert uploaded.status_code == 200
    result = ask(client, query, file=uploaded.json()["file_id"])
    assert result.status_code == 200
    body = result.json()
    assert body["agent_route"] == "FILE_ANALYSIS"
    assert "352 条记录" in body["answer"]
    assert "手册第 26 页" in body["answer"]
    assert "不换算日历日期或指定边界深度" in body["answer"]
    assert "2008-" not in body["answer"] and "180 cm" not in body["answer"]
    evidence = body["file_evidence"][0]
    assert evidence["value"] == pytest.approx(3.659263849258423)
    assert (evidence["model_day"], evidence["cell"], evidence["day_cell"]) == (283, "Nbal_out!C284", "Nbal_out!A284")
    trace = client.app.state.agent_runtime.runs.get(body["run_id"])
    assert trace.decision.reason_code == "file_intent"
    assert [call.skill for call in trace.tool_calls] == ["file_inspector", "whcns_analyzer"]


@pytest.mark.parametrize("query", ["那最大值呢？", "那么最小值呢", "它的最低值是多少", "再看最高值"])
def test_supported_followup_phrasings(client, tmp_path, query):
    token = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=token)
    assert ask(client, query, file=token).json()["route"] == "file"


def test_new_session_never_inherits_old_file_state_or_history_facts(client, tmp_path):
    token = upload(client, tmp_path)
    first = ask(client, "leak_NO3 最大值", file=token).json()
    result = ask(client, "那最小值呢？", session="new-session", file=token,
                 history=[{"role": "assistant", "content": first["answer"]}]).json()
    assert result["route"] == "clarification"
    assert result["file_evidence"] == []


def test_removal_and_replacement_invalidate_metric(client, tmp_path):
    token = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=token)
    assert ask(client, "那最小值呢？").json()["route"] == "clarification"
    assert ask(client, "那最小值呢？", file=token).json()["route"] == "clarification"
    ask(client, "leak_NO3 最大值", file=token)
    replacement = upload(client, tmp_path, name="replacement.xlsx")
    assert ask(client, "那最小值呢？", file=replacement).json()["route"] == "clarification"


def test_explicit_filename_never_uses_the_other_selected_workbook(client, tmp_path):
    first = upload(client, tmp_path, name="A.xlsx")
    second = upload(client, tmp_path, name="B.xlsx")
    mismatch = ask(client, "请查 B.xlsx 的 leak_NO3 最大值", file=first).json()
    assert mismatch["agent_route"] == "CLARIFY" and mismatch["file_evidence"] == []
    trace = client.app.state.agent_runtime.runs.get(mismatch["run_id"])
    assert trace.decision.reason_code == "attachment_name_mismatch"
    assert [call.skill for call in trace.tool_calls] == ["file_inspector"]
    assert ask(client, "请查 B.xlsx 的 leak_NO3 最大值", file=second).json()["route"] == "file"
    multiple = ask(client, "比较 A.xlsx 和 B.xlsx 的 leak_NO3 最大值", file=second).json()
    assert multiple["agent_route"] == "CLARIFY" and multiple["file_evidence"] == []


@pytest.mark.parametrize("query", ["PREC 最大值及日序", "IRRI 最大值", "降水最小值"])
def test_water_field_without_selected_file_requests_attachment(client, query):
    result = ask(client, query).json()
    assert result["agent_route"] == "CLARIFY" and result["file_evidence"] == []
    trace = client.app.state.agent_runtime.runs.get(result["run_id"])
    assert trace.decision.reason_code == "missing_attachment"


@pytest.mark.parametrize("interruption", ["硝态氮和铵态氮最大值", "磷的最大值", "帮我看看", "1", "铵态氮淋失受哪些因素影响？"])
def test_ambiguous_or_changed_subject_does_not_reuse_previous_metric(client, tmp_path, interruption):
    token = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=token)
    ask(client, interruption, file=token)
    result = ask(client, "那最小值呢？", file=token).json()
    assert result["route"] == "clarification"
    assert result["file_evidence"] == []


@pytest.mark.parametrize("query", ["前10天最小值", "浓度最大值", "硝态氮最大值并比较施肥方案", "它的季节总量"])
def test_followup_does_not_silently_drop_unsupported_constraints(client, tmp_path, query):
    token = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=token)
    result = ask(client, query, file=token).json()
    assert result["route"] == "clarification"
    assert result["file_evidence"] == []


def test_expired_file_is_recorded_and_clears_metric(client, tmp_path):
    token = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=token)
    store = client.app.state.file_store
    store.entries[token].expires_at = time.monotonic() - 1
    result = ask(client, "那最小值呢？", file=token)
    assert result.status_code == 404
    detail = result.json()["detail"]
    trace = client.app.state.agent_runtime.runs.get(detail["run_id"])
    assert trace.error_code == "file_not_found"
    assert trace.tool_calls[0].status == "error"
    assert trace.state_after.current_metric is None
    assert trace.answer is None


def test_state_ttl_expires_independently_of_a_still_valid_file(client, tmp_path):
    token = upload(client, tmp_path)
    ask(client, "leak_NO3 最大值", file=token)
    client.app.state.agent_runtime.states.entries["test-session"].expires_at = time.monotonic() - 1
    assert ask(client, "那最小值呢？", file=token).json()["route"] == "clarification"


@pytest.mark.parametrize("query,route", [("1", "DIRECT"), ("你好", "DIRECT"), ("你能做什么？", "DIRECT"), ("写一首诗", "OUT_OF_SCOPE")])
def test_guidance_needs_neither_rag_nor_file_and_has_no_fake_citations(client, query, route):
    client.app.state.chat_service = None
    body = ask(client, query, file="expired").json()
    assert body["agent_route"] == route
    assert body["citations"] == body["file_evidence"] == body["evidence"] == []
    assert "WHCNS" in body["answer"]
    assert body["usage"]["total_tokens"] == 0


def test_crop_constraint_overrides_history_and_persists_within_session(client):
    service = client.app.state.chat_service
    ask(client, "接下来只讨论玉米农田，不讨论水稻。有哪些影响氮淋失的因素？",
        history=[{"role": "user", "content": "水稻灌溉管理"}])
    assert service.calls[-1][2] == []
    ask(client, "对上述作物，灌溉管理需要关注什么？")
    assert "当前作物约束：玉米" in service.calls[-1][0]
    ask(client, "改为小麦")
    ask(client, "氮淋失受哪些因素影响？")
    assert "当前作物约束：小麦" in service.calls[-1][0]
    ask(client, "氮淋失受哪些因素影响？", session="another-session")
    assert "当前作物约束" not in service.calls[-1][0]


def test_natural_crop_question_sets_scope_without_restricting_multi_crop_questions(client):
    service = client.app.state.chat_service
    ask(client, "玉米农田氮素淋失主要受哪些因素影响？")
    assert "当前作物约束：玉米" in service.calls[-1][0]
    ask(client, "对上述作物，灌溉管理需要关注什么？")
    assert "当前作物约束：玉米" in service.calls[-1][0]
    ask(client, "水稻农田呢？")
    assert "当前作物约束：水稻" in service.calls[-1][0]
    ask(client, "小麦和玉米轮作对氮淋失的影响？")
    assert "当前作物约束" not in service.calls[-1][0]
    ask(client, "有哪些影响因素？")
    assert "当前作物约束" not in service.calls[-1][0]


def test_unexpected_errors_have_a_trace_without_sensitive_exception_text(client):
    client.app.state.chat_service = FakeChatService(error=RuntimeError("secret /private/key"))
    response = ask(client, "氮淋失因素")
    assert response.status_code == 500
    detail = response.json()["detail"]
    trace = client.app.state.agent_runtime.runs.get(detail["run_id"])
    assert trace.status == "error"
    assert trace.error_code == "internal_error"
    assert "secret" not in trace.model_dump_json()
    assert "secret" not in json.dumps(detail)


def test_trace_write_failure_does_not_report_saved_run(client, monkeypatch):
    def fail(trace):
        raise sqlite3.OperationalError("disk full")
    monkeypatch.setattr(client.app.state.agent_runtime.runs, "append", fail)
    response = ask(client, "你好")
    assert response.status_code == 200
    assert response.json()["trace_saved"] is False


def test_trace_store_survives_reopen_and_refuses_overwriting_run(client, tmp_path):
    result = ask(client, "你好").json()
    trace = client.app.state.agent_runtime.runs.get(result["run_id"])
    path = tmp_path / "runs.sqlite3"
    store = RunStore(path)
    store.append(trace)
    with pytest.raises(sqlite3.IntegrityError):
        store.append(trace)
    store.close()
    reopened = RunStore(path)
    assert reopened.get(trace.run_id) == trace
    reopened.close()


def test_state_capacity_is_bounded_and_reported(client):
    client.app.state.agent_runtime.states = StateStore(max_sessions=1)
    assert ask(client, "你好", session="one").status_code == 200
    response = ask(client, "你好", session="two")
    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "conversation_capacity"


def test_registry_publishes_validated_contracts():
    registry = build_registry(None, lambda token: {})
    descriptions = registry.describe()
    assert {item["name"] for item in descriptions} == {
        "knowledge_search", "whcns_analyzer", "file_inspector", "clarification", "capability_guidance"}
    assert all(item["input_schema"]["additionalProperties"] is False for item in descriptions)


@pytest.mark.asyncio
async def test_same_conversation_cannot_race_while_other_conversation_can_proceed():
    started, release = asyncio.Event(), asyncio.Event()

    class SlowService(FakeChatService):
        async def answer(self, *args, **kwargs):
            started.set()
            await release.wait()
            return await super().answer(*args, **kwargs)

    app = FastAPI()
    app.state.chat_service = SlowService()
    app.state.agent_runtime = AgentRuntime()
    app.include_router(chat.router, prefix="/api")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as session:
        first = asyncio.create_task(session.post("/api/chat", json={"query": "氮淋失因素", "session_id": "same"}))
        await asyncio.wait_for(started.wait(), timeout=3)
        try:
            second = await session.post("/api/chat", json={"query": "你好", "session_id": "same"})
            assert second.status_code == 409
            assert second.json()["detail"]["code"] == "conversation_busy"
            separate = await session.post("/api/chat", json={"query": "你好", "session_id": "different"})
            assert separate.status_code == 200
        finally:
            release.set()
            await first
    app.state.agent_runtime.runs.close()
