"""Convert the original acceptance CSV without inventing execution/review results.

Run from backend/: .venv/bin/python scripts/import_acceptance_cases.py
The original instructions and assertions remain verbatim in version 1. Updated
behavior lives in a separate v2 file, not in this historical import.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.agent.contracts import CaseStep, EvalCase

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "docs/iterations/2026-09-26-m2-0-model-assistant/manual-acceptance-results.csv"
FIXTURE_DIRS = {
    "Nbal_out.xls": "data/raw/whcns/received-2026-09-26/package/模型",
    "waterbal_out.xls": "data/raw/whcns/received-2026-09-26/package/模型",
    **{name: "backend/var/manual_acceptance/20260928" for name in (
        "synthetic_ties.xlsx", "synthetic_bad_unit.xlsx", "synthetic_bad_value.xlsx", "synthetic_not_excel.xlsx")},
}
ATTACHMENTS = {
    "F02": ["Nbal_out.xls"], "F03": ["Nbal_out.xls"], "F04": ["Nbal_out.xls"], "F05": ["Nbal_out.xls"],
    "F06": ["Nbal_out.xls", "waterbal_out.xls"], "F07": ["synthetic_ties.xlsx"],
    "B01": ["Nbal_out.xls"], "B02": ["Nbal_out.xls", "synthetic_bad_unit.xlsx"],
    "B03": ["synthetic_bad_value.xlsx"], "B04": ["synthetic_not_excel.xlsx"],
    **{case_id: ["Nbal_out.xls"] for case_id in ("X01", "X02", "X03", "O01", "O03")},
}


def convert(source: Path, fixture_root: Path) -> dict:
    cases = []
    with source.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            case_id = row["ID"]
            case = EvalCase(
                case_id=case_id, version=1, category=case_id[0], title=row["核验内容"],
                steps=[CaseStep(action="manual", instruction=row["操作或输入"])],
                preconditions="遵循原核验单顺序及本项清空、重传要求。知识链路：RAG 开启，重排序关闭。",
                attachment_requirements=ATTACHMENTS.get(case_id, []),
                expected=[row["通过标准"]], priority="P0" if row["级别"] == "必做" else "P1", source=SOURCE,
            )
            cases.append(case.model_dump(mode="json"))
    if len({case["case_id"] for case in cases}) != len(cases):
        raise ValueError("duplicate acceptance case ID")
    fixtures = []
    for name, directory in FIXTURE_DIRS.items():
        path = fixture_root / directory / name
        fixtures.append({"filename": name, "path": f"{directory}/{name}",
                         "sha256": hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None})
    return {"schema_version": 1, "dataset_id": "manual-acceptance-20260928-v1", "source": SOURCE,
            "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "note": "历史验收标准；保留原文。CSV 的待执行状态不代表 PDF 人工观察。本文件不导入或创建 Review。",
            "fixtures": fixtures, "cases": cases}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / SOURCE)
    parser.add_argument("--fixture-root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "data/eval/manual_cases.v1.json")
    args = parser.parse_args()
    dataset = convert(args.source, args.fixture_root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Imported {len(dataset['cases'])} historical cases; created no reviews. Output: {args.out}")


if __name__ == "__main__":
    main()
