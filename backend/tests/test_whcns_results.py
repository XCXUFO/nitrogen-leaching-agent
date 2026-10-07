from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from src.model_tools.whcns_results import summarize_result
from src.model_tools.workbooks import WorkbookError, read_workbook


def make_nitrogen(path: Path, *, edit=None) -> Path:
    """Synthetic fixture, not a real WHCNS simulation or agronomic reference."""
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Nbal_out"
    sheet.append(["day", "Upt_N(kg N ha-1)", "leak_NO3(kg N ha-1)", "leak_NH4(kg N ha-1)",
                  "N-Gas(kg N ha-1)", "N-Nitr(kg N ha-1)", "N-Vola(kg N ha-1)",
                  "N-mine(kg N ha-1)", "N2O emission(kg N ha-1)"])
    sheet.append([1, 2, 0.5, 0.25, 0, 0, 0, -1, 0])
    sheet.append([2, 3, 1.5, 0.75, 0, 0, 0, 2, 0])
    if edit:
        edit(sheet)
    book.save(path)
    return path


def test_mislabeled_xls_read_by_content_and_statistics_are_traceable(tmp_path):
    path = make_nitrogen(tmp_path / "Nbal_out.xls")
    report = summarize_result(path, kind="nitrogen")
    assert report["format"] == "xlsx"
    assert report["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    nitrate = next(c for c in report["columns"] if c["header"].startswith("leak_NO3"))
    assert nitrate["raw_column_sum"] == 2
    assert nitrate["max"] == {"value": 1.5, "cell": "Nbal_out!C3", "model_day": 2,
                              "day_cell": "Nbal_out!A3", "occurrences": 1}
    assert nitrate["range"] == "Nbal_out!C2:C3"
    mineralization = next(c for c in report["columns"] if c["header"].startswith("N-mine"))
    assert mineralization["min"]["value"] == -1  # Do not blindly reject negative net values.
    assert report["manual_reference"]["version_match"] == "unconfirmed"


@pytest.mark.parametrize("cell,value,message", [
    ("C1", "leak_NO3(mg L-1)", "units missing"),
    ("C1", "leak_NO3", "units missing"),
    ("C3", None, "Nbal_out!C3"),
    ("C3", "=1+1", "Nbal_out!C3"),
    ("C3", "not a number", "Nbal_out!C3"),
    ("C3", True, "Nbal_out!C3"),
    ("A3", 1, "Nbal_out!A3"),
    ("A3", 4, "Nbal_out!A3"),
    ("A3", 2.5, "Nbal_out!A3"),
    ("A2", 0, "Nbal_out!A2"),
    ("C1", "Upt_N(kg N ha-1)", "duplicate headers"),
    ("C3", "#DIV/0!", "Excel error"),
])
def test_invalid_values_and_schema_fail_with_location(tmp_path, cell, value, message):
    path = make_nitrogen(tmp_path / "test.xlsx", edit=lambda sheet: setattr(sheet[cell], "value", value))
    with pytest.raises(WorkbookError, match=message):
        summarize_result(path, kind="nitrogen")


def test_wrong_sheet_and_unknown_output_version_are_not_silently_accepted(tmp_path):
    path = make_nitrogen(tmp_path / "test.xlsx", edit=lambda sheet: setattr(sheet, "title", "other"))
    with pytest.raises(WorkbookError, match="required sheet missing"):
        summarize_result(path, kind="nitrogen")
    path = make_nitrogen(tmp_path / "test.xlsx", edit=lambda sheet: setattr(sheet["J1"], "value", "new_field"))
    with pytest.raises(WorkbookError, match="unrecognized columns"):
        summarize_result(path, kind="nitrogen")


def test_non_workbook_and_corrupt_zip_are_rejected(tmp_path):
    path = tmp_path / "bad.xls"
    path.write_bytes(b"not Excel")
    with pytest.raises(WorkbookError, match="unsupported file content"):
        read_workbook(path)
    path.write_bytes(b"PK\x03\x04broken")
    with pytest.raises(WorkbookError, match="invalid XLSX"):
        read_workbook(path)


def test_water_output_uses_its_own_units_and_original_column_coordinates(tmp_path):
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "WtaBal_out"
    sheet.append(["day", "PREC(mm)", "IRRI(mm)", "Draining(mm)", "ET0(mm)", "ETp(mm)",
                  "ETa(mm)", "Ep(mm)", "Ea(mm)", "Tp(mm)", "Ta(mm)", "runoff(mm)"])
    sheet.append([10, 4, 5, 2, 0, 0, 0, 0, 0, 0, 0, 0])
    sheet.append([11, 6, 0, 3, 0, 0, 0, 0, 0, 0, 0, 0])
    path = tmp_path / "water.xlsx"
    book.save(path)
    report = summarize_result(path, kind="water")
    precipitation = next(c for c in report["columns"] if c["header"] == "PREC(mm)")
    assert precipitation["raw_column_sum"] == 10
    assert precipitation["range"] == "WtaBal_out!B2:B3"
    assert report["model_day"] == {"first": 10, "last": 11}


def test_cli_error_and_no_overwrite_contract(tmp_path):
    import json
    import subprocess
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts/read_whcns_results.py"
    source = make_nitrogen(tmp_path / "test.xlsx")
    target = tmp_path / "report.json"
    command = [sys.executable, str(script), str(source), "--kind", "nitrogen", "--out", str(target)]
    first = subprocess.run(command, capture_output=True, text=True)
    assert first.returncode == 0, first.stderr
    saved = target.read_bytes()
    second = subprocess.run(command, capture_output=True, text=True)
    assert second.returncode == 2
    assert json.loads(second.stderr)["error"] == "invalid_result_file"
    assert target.read_bytes() == saved
    source.write_bytes(b"not a spreadsheet")
    invalid = subprocess.run(command[:-2], capture_output=True, text=True)
    assert invalid.returncode == 2
    assert json.loads(invalid.stderr)["error"] == "invalid_result_file"
