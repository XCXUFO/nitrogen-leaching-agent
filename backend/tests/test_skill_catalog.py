"""Catalog contracts, access control and truthful read-only availability."""
from __future__ import annotations

import hashlib
from datetime import datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.agent import skill_catalog
from src.agent.skills import build_registry
from src.api import evaluation
from src.evaluation.contracts import AccessFile
from src.storage.case_library import CaseInput, CaseStore

TOKENS = {role: role * 8 for role in ("developer", "tester", "reviewer")}


def auth(role="tester"):
    return {"Authorization": "Bearer " + TOKENS[role]}


@pytest.fixture
def client():
    app = FastAPI()
    app.state.eval_access = AccessFile(users=[
        {"tester_id": role, "role": role, "token_sha256": hashlib.sha256(token.encode()).hexdigest()}
        for role, token in TOKENS.items()
    ])
    app.include_router(evaluation.router, prefix="/api")
    with TestClient(app) as candidate:
        yield candidate


@pytest.mark.parametrize("path", ["/skills", "/skills/case_explanation"])
def test_catalog_needs_an_enabled_authenticated_workbench(client, path):
    assert client.get("/api/eval" + path).status_code == 401
    assert client.get("/api/eval" + path, headers={"Authorization": "Bearer " + "x" * 40}).status_code == 401
    client.app.state.eval_access = None
    assert client.get("/api/eval" + path, headers=auth()).status_code == 404


@pytest.mark.parametrize("role", TOKENS)
def test_all_workbench_roles_can_inspect_exactly_the_registered_capabilities(client, role):
    response = client.get("/api/eval/skills", headers=auth(role))
    assert response.status_code == 200
    items = {item["name"]: item for item in response.json()}
    registry = build_registry(None, skill_catalog._unused_report).describe()
    assert set(items) == {item["name"] for item in registry}
    assert len(items) == 7
    assert all(item["registered"] and item["configuration"] == ("limited" if item["name"] == "case_assistant" else "read_only") for item in items.values())
    assert all("input_schema" not in item for item in items.values())
    assert items["case_assistant"]["availability"] == "unavailable"
    assert items["knowledge_search"]["availability"] == "unavailable"
    assert items["clarification"]["availability"] == "available"
    assert items["whcns_analyzer"]["generation"] == "local"


def test_detail_exposes_real_schemas_and_unknown_versions_without_current_config_fabrication(client):
    registry = build_registry(None, skill_catalog._unused_report).describe()
    for registered in registry:
        response = client.get("/api/eval/skills/" + registered["name"], headers=auth())
        assert response.status_code == 200
        item = response.json()
        assert item["input_schema"] == registered["input_schema"]
        assert item["output_schema"] == registered["output_schema"]
        assert item["registry_description"] == registered["description"]
        assert item["skill_version"] is None and item["runtime_config_version"] is None
        assert item["scenarios"] and item["examples"] and item["limitations"]
        assert datetime.fromisoformat(item["checked_at"]).tzinfo is not None
    assert client.get("/api/eval/skills/not-a-skill", headers=auth()).status_code == 404
    analyzer = client.get("/api/eval/skills/whcns_analyzer", headers=auth()).json()
    assert "不是通用 Excel" in "".join(analyzer["limitations"])
    assert "不执行 WHCNS" in "".join(analyzer["limitations"])


class NeverCallModel:
    async def chat(self, *args, **kwargs):
        raise AssertionError("A catalog probe must not invoke the model")

    chat_json = chat


def test_initialized_model_is_unknown_not_online_healthy_and_no_private_material_is_returned(client):
    store = CaseStore(":memory:")
    try:
        store.create(CaseInput(title="private-title", body="private-case-body", enabled=True), "operator")
        before = store.db.total_changes
        llm = NeverCallModel()
        client.app.state.llm = llm
        client.app.state.chat_service = SimpleNamespace(_llm=llm)
        client.app.state.case_library = store
        client.app.state.agent_runtime = SimpleNamespace(config_version="test-build:version-1", config_manifest={
            "agent_code_sha256": "a" * 64, "api_key": "secret-never-return", "index_path": "/private/index"})
        response = client.get("/api/eval/skills/knowledge_search", headers=auth())
        assert response.status_code == 200
        item = response.json()
        assert item["availability"] == "unknown"
        assert item["runtime_config_version"] == "test-build:version-1" and item["code_sha256"] == "a" * 64
        assert item["skill_version"] is None
        assert "private-case-body" not in response.text and "private-title" not in response.text
        assert "secret-never-return" not in response.text and "/private/index" not in response.text
        assert store.db.total_changes == before
    finally:
        store.close()


def test_pasted_text_explanation_does_not_require_the_case_library(client):
    client.app.state.llm = NeverCallModel()
    reference = client.get("/api/eval/skills/case_reference", headers=auth()).json()
    explanation = client.get("/api/eval/skills/case_explanation", headers=auth()).json()
    assert reference["availability"] == "unavailable"
    assert explanation["availability"] == "unknown"
    case_dependency = next(item for item in explanation["dependencies"] if item["name"] == "开放案例材料")
    assert not case_dependency["required"]


def test_reference_status_refreshes_after_opening_closing_and_capacity_changes(client):
    store = CaseStore(":memory:")
    client.app.state.case_library = store
    client.app.state.llm = NeverCallModel()
    try:
        def materials():
            value = client.get("/api/eval/skills/case_reference", headers=auth()).json()
            return next(item for item in value["dependencies"] if item["name"] == "开放案例材料")

        assert materials()["status"] == "unavailable"
        first = store.create(CaseInput(title="case-0", body="body-0", enabled=True), "operator")
        assert materials()["status"] == "available"
        store.change(first["id"], 1, {"enabled": False}, "operator")
        assert materials()["status"] == "unavailable"
        for number in range(31):
            store.create(CaseInput(title=f"case-{number}", body=f"independent-body-{number}", enabled=True), "operator")
        limited = materials()
        assert limited["status"] == "available"
        assert "候选" in limited["message"] and "预算" in limited["message"]
    finally:
        store.close()


def test_probe_errors_are_unknown_and_do_not_expose_internal_failures(client):
    def broken():
        raise RuntimeError("private database /private/cases.sqlite3")

    client.app.state.llm = NeverCallModel()
    client.app.state.case_library = SimpleNamespace(available=broken)
    response = client.get("/api/eval/skills/case_reference", headers=auth())
    assert response.status_code == 200 and response.json()["availability"] == "unknown"
    assert "/private/" not in response.text


def test_parser_dependencies_are_reported_per_format_without_a_fake_full_format_guarantee(client, monkeypatch):
    monkeypatch.setattr(skill_catalog, "find_spec", lambda module: object() if module == "xlrd" else None)
    item = client.get("/api/eval/skills/file_inspector", headers=auth()).json()
    dependencies = {item["name"]: item for item in item["dependencies"]}
    assert dependencies["XLS 解析"]["status"] == "available"
    assert dependencies["XLSX 解析"]["status"] == "unavailable"
    assert "新表格" in item["availability_note"]
    monkeypatch.setattr(skill_catalog, "find_spec", lambda module: None)
    item = client.get("/api/eval/skills/file_inspector", headers=auth()).json()
    assert item["availability"] == "unknown"
    assert "已缓存摘要" in item["availability_note"]


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_read_only_endpoint_has_no_configuration_mutation(client, method):
    assert getattr(client, method)("/api/eval/skills/case_explanation", headers=auth("developer")).status_code == 405


def test_case_catalog_is_canonical_but_old_details_keep_alias_metadata(client):
    items = client.get('/api/eval/skills', headers=auth()).json()
    names = {item['name'] for item in items}
    assert 'case_assistant' in names and not names & {'case_reference', 'case_explanation'}
    for alias in ('case_reference', 'case_explanation'):
        detail = client.get('/api/eval/skills/' + alias, headers=auth()).json()
        assert detail['name'] == alias and detail['alias_of'] == 'case_assistant'
    detail = client.get('/api/eval/skills/case_assistant', headers=auth()).json()
    assert set(detail['input_schema']['properties']['mode']['enum']) == {'search', 'explain', 'compare', 'evidence'}
