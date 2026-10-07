from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from src.agent.contracts import EvalCase

ROOT = Path(__file__).resolve().parents[2]


def test_historical_case_import_preserves_ids_instructions_and_expectations():
    dataset = json.loads((ROOT / "data/eval/manual_cases.v1.json").read_text())
    source = ROOT / dataset["source"]
    assert dataset["source_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    with source.open(encoding="utf-8-sig", newline="") as handle:
        rows = {row["ID"]: row for row in csv.DictReader(handle)}
    cases = [EvalCase.model_validate(case) for case in dataset["cases"]]
    assert {case.case_id for case in cases} == set(rows)
    for case in cases:
        assert case.version == 1
        assert case.steps[0].instruction == rows[case.case_id]["操作或输入"]
        assert case.expected == [rows[case.case_id]["通过标准"]]
    assert "reviews" not in dataset


@pytest.mark.parametrize("version", [2, 3])
def test_upgraded_cases_are_versioned_and_fixture_references_resolve(version):
    original = json.loads((ROOT / "data/eval/manual_cases.v1.json").read_text())
    upgrade = json.loads((ROOT / f"data/eval/harness_cases.v{version}.json").read_text())
    previous = {f"{case['case_id']}@{case['version']}" for case in original["cases"]}
    fixtures = {fixture["filename"] for fixture in original["fixtures"]}
    for raw in upgrade["cases"]:
        case = EvalCase.model_validate(raw)
        assert case.version == version
        if case.supersedes:
            assert case.supersedes in previous
        assert set(case.attachment_requirements) <= fixtures
        assert all(step.attachment is None or step.attachment in fixtures for step in case.steps)


def test_locally_available_acceptance_files_match_frozen_fingerprints():
    dataset = json.loads((ROOT / "data/eval/manual_cases.v1.json").read_text())
    for fixture in dataset["fixtures"]:
        path = ROOT / fixture["path"]
        if path.exists() and fixture["sha256"]:
            assert hashlib.sha256(path.read_bytes()).hexdigest() == fixture["sha256"]
