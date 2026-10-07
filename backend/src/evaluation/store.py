"""Immutable cases, ordered execution events, and append-only human reviews.

Uses the run store's connection/lock so run bindings and review snapshots share
one database. No attachment/session bearer tokens are persisted here.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException

from src.agent.contracts import EvalCase
from src.evaluation.contracts import Principal, ReviewInput
from src.storage.run_store import RunStore


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def fail(code: str, message: str, status: int = 409):
    return HTTPException(status, detail={"code": code, "message": message})


class EvaluationStore:
    def __init__(self, runs: RunStore):
        self.runs = runs
        self.db, self.lock = runs._connection, runs._lock
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS eval_cases (
                  case_id TEXT NOT NULL, version INTEGER NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(case_id, version));
                CREATE TABLE IF NOT EXISTS eval_executions (
                  execution_id TEXT PRIMARY KEY, case_id TEXT NOT NULL, case_version INTEGER NOT NULL,
                  tester_id TEXT NOT NULL, created_at TEXT NOT NULL, status TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_events (
                  execution_id TEXT NOT NULL, sequence INTEGER NOT NULL, payload TEXT NOT NULL,
                  run_id TEXT UNIQUE, PRIMARY KEY(execution_id, sequence));
                CREATE TABLE IF NOT EXISTS eval_reviews (
                  review_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL UNIQUE, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_tasks (
                  task_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_task_executions (
                  execution_id TEXT PRIMARY KEY, task_id TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_issues (
                  issue_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_issue_retests (
                  retest_id TEXT PRIMARY KEY, issue_id TEXT NOT NULL, execution_id TEXT NOT NULL UNIQUE,
                  payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_assessments (
                  assessment_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS eval_execution_owner ON eval_executions(tester_id, created_at);
            """)

    def seed(self, directory: Path):
        original = json.loads((directory / "manual_cases.v1.json").read_text())
        self.fixtures = {f["filename"]: f for f in original["fixtures"]}
        rows = []
        for filename in ("manual_cases.v1.json", "harness_cases.v2.json", "harness_cases.v3.json", "harness_cases.v4.json"):
            data = json.loads((directory / filename).read_text())
            for raw in data["cases"]:
                case = EvalCase.model_validate(raw)
                payload = {"case": case.model_dump(), "dataset_id": data["dataset_id"],
                           "professional_review": "pending",
                           "fixtures": [{k: v for k, v in self.fixtures[name].items() if k != "path"}
                                        for name in case.attachment_requirements]}
                rows.append((case.case_id, case.version, json.dumps(payload, ensure_ascii=False, sort_keys=True)))
        with self.lock, self.db:
            for cid, version, payload in rows:
                existing = self.db.execute("SELECT payload FROM eval_cases WHERE case_id=? AND version=?", (cid, version)).fetchone()
                if existing and existing[0] != payload:
                    raise ValueError(f"immutable case changed: {cid}@{version}; create a new version")
                self.db.execute("INSERT OR IGNORE INTO eval_cases VALUES (?,?,?)", (cid, version, payload))

    def cases(self, latest=True):
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_cases ORDER BY case_id,version DESC").fetchall()
            assessment_rows = self.db.execute("SELECT payload FROM eval_assessments ORDER BY rowid").fetchall()
        assessments = [json.loads(row[0]) for row in assessment_rows]
        items, seen = [], set()
        for row in rows:
            item = json.loads(row[0])
            cid = item["case"]["case_id"]
            if not latest or cid not in seen:
                relevant = [a for a in assessments if (a["case_id"], a["case_version"]) == (cid, item["case"]["version"])]
                experts = [a for a in relevant if a["kind"] == "domain_expert"]
                item["professional_review"] = "domain_expert_reviewed" if experts else "pending"
                item["professional_outcome"] = experts[-1]["overall"] if experts else None
                item["ai_assisted_review_count"] = sum(a["kind"] == "ai_assisted" for a in relevant)
                item["domain_expert_review_count"] = len(experts)
                items.append(item)
            seen.add(cid)
        return items

    def case(self, cid, version):
        with self.lock:
            row = self.db.execute("SELECT payload FROM eval_cases WHERE case_id=? AND version=?", (cid, version)).fetchone()
        if not row:
            raise fail("case_not_found", "未找到该版本用例。", 404)
        return json.loads(row[0])

    def create(self, cid, version, user: Principal, task_id: str | None = None,
               runtime_config_version: str | None = None):
        self.case(cid, version)
        eid = str(uuid4())
        with self.lock, self.db:
            if task_id:
                task = self.db.execute("SELECT payload FROM eval_tasks WHERE task_id=?", (task_id,)).fetchone()
                if not task:
                    raise fail("task_not_found", "未找到该测评任务。", 404)
                task_payload = json.loads(task[0])
                allowed = task_payload["case_versions"]
                if {"case_id": cid, "case_version": version} not in allowed:
                    raise fail("task_case_mismatch", "用例版本不在任务冻结集合内。", 422)
                if task_payload["runtime_config_version"] != runtime_config_version:
                    raise fail("task_config_mismatch", "当前运行配置与任务冻结版本不同，请新建对应任务。", 422)
            self.db.execute("INSERT INTO eval_executions VALUES (?,?,?,?,?,?)", (eid, cid, version, user.tester_id, now(), "open"))
            if task_id:
                self.db.execute("INSERT INTO eval_task_executions VALUES (?,?)", (eid, task_id))
        return self.execution(eid, user)

    def execution(self, eid, user: Principal):
        with self.lock:
            row = self.db.execute("SELECT * FROM eval_executions WHERE execution_id=?", (eid,)).fetchone()
            if not row or (user.role not in {"developer", "reviewer"} and row[3] != user.tester_id):
                raise fail("execution_not_found", "未找到可访问的用例执行。", 404)
            events = self.db.execute("SELECT payload FROM eval_events WHERE execution_id=? ORDER BY sequence", (eid,)).fetchall()
            review = self.db.execute("SELECT payload FROM eval_reviews WHERE execution_id=?", (eid,)).fetchone()
            task = self.db.execute("SELECT task_id FROM eval_task_executions WHERE execution_id=?", (eid,)).fetchone()
        return dict(zip(("execution_id", "case_id", "case_version", "tester_id", "created_at", "status"), row),
                    task_id=task[0] if task else None, events=[json.loads(e[0]) for e in events], review=json.loads(review[0]) if review else None)

    def list_executions(self, user: Principal, limit=50, offset=0):
        where, params = ("", []) if user.role in {"developer", "reviewer"} else ("WHERE tester_id=?", [user.tester_id])
        with self.lock:
            rows = self.db.execute(f"SELECT execution_id,case_id,case_version,tester_id,created_at,status FROM eval_executions {where} ORDER BY created_at DESC LIMIT ? OFFSET ?", [*params, limit, offset]).fetchall()
        return [dict(zip(("execution_id", "case_id", "case_version", "tester_id", "created_at", "status"), r)) for r in rows]

    def event(self, eid, data, run_id=None):
        with self.lock, self.db:
            state = self.db.execute("SELECT status FROM eval_executions WHERE execution_id=?", (eid,)).fetchone()
            if not state or state[0] != "open":
                raise fail("execution_closed", "评分已提交，当前执行不可继续修改。")
            if run_id and not self.db.execute("SELECT 1 FROM agent_runs WHERE run_id=?", (run_id,)).fetchone():
                raise fail("evaluation_trace_missing", "运行记录未保存，不能绑定本轮评分。")
            seq = self.db.execute("SELECT COUNT(*) FROM eval_events WHERE execution_id=?", (eid,)).fetchone()[0] + 1
            event = {**data, "sequence": seq, "created_at": now(), "run_id": run_id}
            self.db.execute("INSERT INTO eval_events VALUES (?,?,?,?)", (eid, seq, json.dumps(event, ensure_ascii=False), run_id))
        return event

    def review(self, eid, user: Principal, body: ReviewInput):
        execution = self.execution(eid, user)
        if execution["tester_id"] != user.tester_id:
            raise fail("evaluation_forbidden", "只能为自己执行的用例提交评分。", 403)
        run_ids = [e["run_id"] for e in execution["events"] if e["run_id"]]
        if body.overall != "blocked" and not any(e["action"] in {"query", "upload"} for e in execution["events"]):
            raise fail("evaluation_no_runs", "请先执行提问或上传附件；无法执行时请选择受阻并说明原因。")
        if body.overall != "blocked" and any(e.get("trace_missing") for e in execution["events"]):
            raise fail("evaluation_trace_missing", "本次执行有未保存的运行记录，请标为受阻或新建执行。")
        run_versions, missing_runs = self.run_versions(run_ids)
        if body.overall != "blocked" and missing_runs:
            raise fail("evaluation_trace_missing", "本次执行缺少运行记录，请标为受阻或新建执行。")
        if execution["task_id"] and body.overall != "blocked":
            with self.lock:
                task = json.loads(self.db.execute("SELECT payload FROM eval_tasks WHERE task_id=?",
                                                 (execution["task_id"],)).fetchone()[0])
            if any(version != task["runtime_config_version"] for version in run_versions):
                raise fail("task_run_config_mismatch", "已有 Run 与任务冻结配置不一致，请标为受阻并在对应版本的新执行中复测。")
        item = self.case(execution["case_id"], execution["case_version"])
        review = {**body.model_dump(), "review_id": str(uuid4()), "execution_id": eid,
                  "tester_id": user.tester_id, "case_id": execution["case_id"], "case_version": execution["case_version"],
                  "run_ids": run_ids, "created_at": now(), "case_snapshot": item,
                  "runtime_config_versions": run_versions,
                  "event_sequences": [e["sequence"] for e in execution["events"]],
                  "review_kind": "development_trial", "professional_review": "pending"}
        with self.lock, self.db:
            state = self.db.execute("SELECT status FROM eval_executions WHERE execution_id=?", (eid,)).fetchone()[0]
            if state != "open":
                raise fail("review_already_submitted", "评分已保存；历史评分不覆盖，复测请新建执行。")
            self.db.execute("INSERT INTO eval_reviews VALUES (?,?,?)", (review["review_id"], eid, json.dumps(review, ensure_ascii=False)))
            self.db.execute("UPDATE eval_executions SET status='reviewed' WHERE execution_id=?", (eid,))
        return review

    def run_versions(self, run_ids: list[str]) -> tuple[list[str], bool]:
        traces = [self.runs.get(run_id) for run_id in run_ids]
        return sorted({trace.config_version for trace in traces if trace}), any(trace is None for trace in traces)

    def statistics(self):
        with self.lock:
            total = self.db.execute("SELECT COUNT(*) FROM eval_executions").fetchone()[0]
            reviews = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM eval_reviews").fetchall()]
            assessments = [json.loads(r[0]) for r in self.db.execute("SELECT payload FROM eval_assessments").fetchall()]
        def summarize(items):
            return {"reviewed": len(items), "overall": {key: sum(r["overall"] == key for r in items) for key in ("pass", "partial", "fail", "blocked")},
                    "layers": {key: {"denominator": sum(r["overall"] != "blocked" and r[key] != "n.a." for r in items),
                                     **{value: sum(r["overall"] != "blocked" and r[key] == value for r in items) for value in ("yes", "partial", "no")}}
                               for key in ("route_correct", "tool_correct", "evidence_correct", "answer_correct")}}
        groups = sorted({(r["case_id"], r["case_version"]) for r in reviews})
        return {"executions": total, "pending": total - len(reviews), **summarize(reviews),
                "assessment_counts": {kind: sum(a["kind"] == kind for a in assessments)
                                      for kind in ("ai_assisted", "domain_expert")},
                "by_case_version": [
                    {"case_id": cid, "case_version": version, **summarize([r for r in reviews if (r["case_id"], r["case_version"]) == (cid, version)])}
                    for cid, version in groups]}

    def list_runs(self, limit=50, offset=0):
        with self.lock:
            rows = self.db.execute("SELECT payload FROM agent_runs ORDER BY started_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        return [{k: v for k, v in json.loads(row[0]).items() if k in {
            "run_id", "started_at", "input", "status", "outcome", "latency_ms", "config_version", "decision", "error_code"}} for row in rows]
