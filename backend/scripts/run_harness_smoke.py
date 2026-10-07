"""Run the current app with real fixtures; --live additionally calls configured RAG/LLM.

Writes an isolated trace database and JSON report under var/eval/. No running
server is restarted. No upload/session bearer tokens are saved in the report.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    backend = Path(__file__).resolve().parents[1]
    output = args.out or backend / "var/eval" / datetime.now(timezone.utc).strftime("harness-%Y%m%d-%H%M%S")
    output.mkdir(parents=True, exist_ok=False)
    from fastapi.testclient import TestClient
    from src.main import app, settings

    snapshot = hashlib.sha256()
    for path in sorted((backend / "src").rglob("*.py")):
        snapshot.update(str(path.relative_to(backend)).encode())
        snapshot.update(path.read_bytes())
    settings.agent_build_version = f"harness-smoke-{snapshot.hexdigest()[:16]}"
    settings.agent_trace_db = str(output / "runs.sqlite3")
    settings.rag_enabled = args.live
    settings.rag_reranker_enabled = False  # Match the manual-review baseline.
    fixture = backend.parent / "data/demo/Nbal_out.xls"
    raw = fixture.read_bytes()
    report = {"live": args.live, "build": settings.agent_build_version, "reranker_enabled": False,
              "fixture_sha256": hashlib.sha256(raw).hexdigest(), "runs": [],
              "professional_review": "not_performed"}

    def post(client, query, token=None):
        body = {"query": query, "session_id": "harness-smoke-session"}
        if token:
            body["file_id"] = token
        response = client.post("/api/chat", json=body)
        data = response.json()
        if response.is_success:
            data.pop("conversation_id", None)
            report["runs"].append({"input": query, "http_status": response.status_code, "response": data})
        else:
            detail = data.get("detail", {})
            report["runs"].append({"input": query, "http_status": response.status_code,
                                   "error_code": detail.get("code"), "run_id": detail.get("run_id")})
        print(json.dumps({"http_status": response.status_code, "route": data.get("agent_route"),
                          "outcome": data.get("outcome"), "warnings": [w["code"] for w in data.get("warnings", [])]}, ensure_ascii=False), flush=True)
        return data

    success = False
    try:
        with TestClient(app) as client:
            receipt = client.post("/api/files?filename=Nbal_out.xls", content=raw)
            receipt.raise_for_status()
            assert receipt.json()["status"] == "pending"
            token = receipt.json()["file_id"]
            if args.live:
                knowledge = post(client, "接下来只讨论玉米农田。氮素淋失主要受哪些因素影响？", token)
            combined = post(client, "硝态氮最大值是多少，为什么可能这么高？", token)
            minimum = post(client, "那最小值呢？", token)
            guidance = post(client, "1", token)
            # Independent read of original cells, not the tool summary.
            import xlrd
            book = xlrd.open_workbook(file_contents=raw)
            try:
                sheet = book.sheet_by_name("Nbal_out")
                values = [sheet.cell_value(row, 2) for row in range(1, sheet.nrows)]
                assert combined["file_evidence"][0]["value"] == max(values)
                assert minimum["file_evidence"][0]["value"] == min(values)
            finally:
                book.release_resources()
            assert guidance["citations"] == [] and guidance["route"] == "direct"
            assert combined["outcome"] == ("complete" if args.live else "partial")
            assert combined["agent_route"] == "COMPOSED"
            assert combined["attachment"]["status"] == "ready"
            assert combined["file_evidence"][0]["cell"] == "Nbal_out!C284"
            assert minimum["file_evidence"][0]["occurrences"] == 191
            if args.live:
                assert knowledge["agent_route"] == "KNOWLEDGE" and knowledge["citations"]
                assert combined["citations"] and not combined["warnings"]
                assert any(section["kind"] == "literature_inference" and section["evidence_ids"]
                           for section in combined["sections"])
            for run in report["runs"]:
                response = run["response"]
                assert response["trace_saved"]
                trace = app.state.agent_runtime.runs.get(response["run_id"])
                assert trace and trace.outcome == response["outcome"]
            if args.live:
                assert app.state.agent_runtime.runs.get(combined["run_id"]).state_before.crop == "玉米"
            success = True
    except Exception as exc:
        # Preserve diagnostics without printing secrets or upstream exception text.
        report["failure_type"] = type(exc).__name__
    finally:
        report["smoke_passed"] = success
        report["source_unchanged"] = hashlib.sha256(fixture.read_bytes()).hexdigest() == report["fixture_sha256"]
        (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"Report: {output / 'report.json'}; smoke_passed={success}", flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
