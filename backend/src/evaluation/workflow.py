"""Frozen task scope, issue evidence, retests and separate review identities."""
from __future__ import annotations

import hashlib
import json
from uuid import uuid4

from src.evaluation.contracts import AssessmentInput, IssueInput, IssueUpdateInput, Principal, RetestInput, ReviewAssignmentInput, ReviewResolutionInput, TaskInput
from src.evaluation.store import EvaluationStore, fail, now


class WorkflowStore:
    def __init__(self, evaluations: EvaluationStore):
        self.evaluations = evaluations
        self.db, self.lock = evaluations.db, evaluations.lock
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS eval_review_assignments (
                  execution_id TEXT NOT NULL, reviewer_id TEXT NOT NULL, payload TEXT NOT NULL,
                  PRIMARY KEY(execution_id, reviewer_id));
                CREATE TABLE IF NOT EXISTS eval_review_resolutions (
                  resolution_id TEXT PRIMARY KEY, execution_id TEXT NOT NULL, payload TEXT NOT NULL);
            """)

    def create_task(self, body: TaskInput, user: Principal, runtime_config_version: str,
                    knowledge_config: dict, version_manifest: dict | None = None) -> dict:
        if body.build_version != runtime_config_version.split(":", 1)[0]:
            raise fail("task_build_mismatch", "填写的构建版本与当前服务不同。", 422)
        for item in body.case_versions:
            self.evaluations.case(item.case_id, item.case_version)
        record = {**body.model_dump(), "task_id": str(uuid4()), "created_by": user.tester_id,
                  "created_at": now(), "status": "open",
                  "runtime_config_version": runtime_config_version,
                  "knowledge_config": knowledge_config,
                  "version_manifest": version_manifest or {}}
        with self.lock, self.db:
            self.db.execute("INSERT INTO eval_tasks VALUES (?,?)", (record["task_id"], json.dumps(record, ensure_ascii=False)))
        return record

    def tasks(self) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_tasks ORDER BY rowid DESC").fetchall()
        return [json.loads(row[0]) for row in rows]

    def task(self, task_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT payload FROM eval_tasks WHERE task_id=?", (task_id,)).fetchone()
            executions = self.db.execute("SELECT execution_id FROM eval_task_executions WHERE task_id=? ORDER BY rowid", (task_id,)).fetchall()
        if not row:
            raise fail("task_not_found", "未找到该测评任务。", 404)
        return {**json.loads(row[0]), "execution_ids": [item[0] for item in executions]}

    def task_progress(self, task_id: str, user: Principal) -> dict:
        task = self.task(task_id)
        with self.lock:
            rows = self.db.execute("""SELECT e.execution_id,e.case_id,e.case_version,e.tester_id,
                e.created_at,e.status,r.payload,COUNT(v.sequence)
                FROM eval_task_executions t JOIN eval_executions e ON e.execution_id=t.execution_id
                LEFT JOIN eval_reviews r ON r.execution_id=e.execution_id
                LEFT JOIN eval_events v ON v.execution_id=e.execution_id
                WHERE t.task_id=? GROUP BY e.execution_id ORDER BY e.created_at,e.execution_id""", (task_id,)).fetchall()
        executions = [{"execution_id": row[0], "case_id": row[1], "case_version": row[2],
                       "tester_id": row[3], "created_at": row[4], "status": row[5],
                       "overall": json.loads(row[6])["overall"] if row[6] else None,
                       "event_count": row[7]} for row in rows
                      if user.role in {"developer", "reviewer"} or row[3] == user.tester_id]
        cases = []
        for item in task["case_versions"]:
            records = [record for record in executions if
                       (record["case_id"], record["case_version"]) == (item["case_id"], item["case_version"])]
            cases.append({**item, "executions": records,
                          "started": any(record["event_count"] for record in records),
                          "reviewed": any(record["status"] == "reviewed" for record in records)})
        return {"task": {**task, "execution_ids": [item["execution_id"] for item in executions]},
                "cases": cases, "summary": {"total_cases": len(cases),
                    "prepared_cases": sum(bool(item["executions"]) for item in cases),
                    "started_cases": sum(item["started"] for item in cases),
                    "reviewed_cases": sum(item["reviewed"] for item in cases),
                    "executions": len(executions)},
                "scope": "all" if user.role in {"developer", "reviewer"} else "own"}

    def task_evidence(self, task_id: str, user: Principal) -> dict:
        """Export a reviewable task snapshot without access keys or ephemeral file tokens."""
        task = self.task(task_id)
        if len(task["execution_ids"]) > 200:
            raise fail("task_export_limit", "此任务执行超过 200 次，请使用管理员离线导出。", 422)
        executions = [self.evaluations.execution(eid, user) for eid in task["execution_ids"]]
        issues = self.issues(task_id=task_id)
        for issue in issues:
            for retest in issue["retests"]:
                eid = retest["execution_id"]
                if all(item["execution_id"] != eid for item in executions):
                    executions.append(self.evaluations.execution(eid, user))
                    if len(executions) > 200:
                        raise fail("task_export_limit", "含复测的执行超过 200 次，请使用管理员离线导出。", 422)
        run_ids = sorted({event["run_id"] for execution in executions for event in execution["events"]
                          if event.get("run_id")})
        traces = {}
        for rid in run_ids:
            trace = self.evaluations.runs.get(rid)
            traces[rid] = trace.model_dump(mode="json") if trace else None
        case_keys = {(item["case_id"], item["case_version"]) for item in task["case_versions"]}
        with self.lock:
            assessment_rows = self.db.execute("SELECT payload FROM eval_assessments ORDER BY rowid").fetchall()
        assessments = [item for row in assessment_rows if
                       (item := json.loads(row[0])) and (item["case_id"], item["case_version"]) in case_keys]
        payload = {"task": task, "cases": [self.evaluations.case(item["case_id"], item["case_version"])
                                              for item in task["case_versions"]],
                   "executions": executions, "issues": issues, "assessments": assessments,
                   "traces": traces, "missing_run_ids": [rid for rid, trace in traces.items() if trace is None],
                   "note": "Historical development reviews, AI-assisted assessments and domain-expert assessments retain separate identities; no export verdict is inferred"}
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        return {"format_version": 1, "exported_at": now(), "payload_sha256": hashlib.sha256(canonical).hexdigest(),
                "payload": payload}

    def prepare_task(self, task_id: str, user: Principal, runtime_config_version: str) -> dict:
        """Atomically prepare missing cases for this identity; retries do not create duplicates.

        No LLM calls, scoring or ephemeral context allocation. A never-started
        execution receives an empty context when its owner opens or operates it.
        """
        with self.lock, self.db:
            row = self.db.execute("SELECT payload FROM eval_tasks WHERE task_id=?", (task_id,)).fetchone()
            if not row:
                raise fail("task_not_found", "未找到该测评任务。", 404)
            task = json.loads(row[0])
            if task["runtime_config_version"] != runtime_config_version:
                raise fail("task_config_mismatch", "当前运行配置与任务冻结版本不同，请新建对应任务。", 422)
            existing = set(self.db.execute("""SELECT e.case_id,e.case_version FROM eval_executions e
                JOIN eval_task_executions t ON t.execution_id=e.execution_id
                WHERE t.task_id=? AND e.tester_id=?""", (task_id, user.tester_id)).fetchall())
            for item in task["case_versions"]:
                if (item["case_id"], item["case_version"]) in existing:
                    continue
                eid = str(uuid4())
                self.db.execute("INSERT INTO eval_executions VALUES (?,?,?,?,?,?)",
                                (eid, item["case_id"], item["case_version"], user.tester_id, now(), "open"))
                self.db.execute("INSERT INTO eval_task_executions VALUES (?,?)", (eid, task_id))
        return self.task_progress(task_id, user)

    def create_issue(self, body: IssueInput, user: Principal) -> dict:
        execution = self.evaluations.execution(body.execution_id, user)
        review = execution["review"]
        if not review or review["overall"] not in {"partial", "fail"}:
            raise fail("issue_review_required", "问题须关联已提交的部分通过或不通过评分。", 422)
        event = next((e for e in execution["events"] if e["sequence"] == body.event_sequence), None)
        if not event or event.get("action") != "query" or not event.get("run_id"):
            raise fail("issue_run_required", "请选有运行记录的提问轮次。", 422)
        if event["run_id"] not in review["run_ids"]:
            raise fail("issue_run_mismatch", "运行记录不属于该评分。", 422)
        record = {"issue_id": str(uuid4()), "created_at": now(), "created_by": user.tester_id,
                  "execution_id": body.execution_id, "review_id": review["review_id"],
                  "task_id": execution["task_id"], "case_id": execution["case_id"],
                  "case_version": execution["case_version"], "event_sequence": body.event_sequence,
                  "run_id": event["run_id"], "original_question": event["input"],
                  "answer_snapshot": event.get("response", {}).get("answer"),
                  "error_snapshot": event.get("error"), "title": body.title,
                  "assignee": body.assignee, "evidence_note": body.evidence_note,
                  "review_snapshot": review, "status": "open", "revision": 1,
                  "history": [{"at": now(), "by": user.tester_id, "action": "created",
                               "from_status": None, "to_status": "open", "assignee": body.assignee,
                               "note": body.evidence_note}]}
        with self.lock, self.db:
            self.db.execute("INSERT INTO eval_issues VALUES (?,?)", (record["issue_id"], json.dumps(record, ensure_ascii=False)))
        return record

    @staticmethod
    def issue_state(record: dict, retests: list[dict]) -> dict:
        # Older records predate explicit state; project them without mutating history.
        latest = retests[-1] if retests else None
        inferred = "closed" if latest and latest["overall"] == "pass" and latest.get("version_verified") else "open"
        return {**record, "status": record.get("status", inferred),
                "revision": record.get("revision", 1), "history": record.get("history", []),
                "retests": retests}

    def issues(self, status: str | None = None, assignee: str | None = None,
               task_id: str | None = None) -> list[dict]:
        if status and status not in {"open", "in_progress", "ready_for_retest", "closed"}:
            raise fail("issue_status_invalid", "未知的问题状态。", 422)
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_issues ORDER BY rowid DESC").fetchall()
            retest_rows = self.db.execute("SELECT issue_id,payload FROM eval_issue_retests ORDER BY rowid").fetchall()
        retests: dict[str, list[dict]] = {}
        for issue_id, raw in retest_rows:
            retests.setdefault(issue_id, []).append(json.loads(raw))
        items = [json.loads(row[0]) for row in rows]
        result = [self.issue_state(item, retests.get(item["issue_id"], [])) for item in items]
        return [item for item in result if (not status or item["status"] == status)
                and (not assignee or item["assignee"] == assignee)
                and (not task_id or item.get("task_id") == task_id)]

    def issue(self, issue_id: str) -> dict:
        with self.lock:
            row = self.db.execute("SELECT payload FROM eval_issues WHERE issue_id=?", (issue_id,)).fetchone()
            retests = self.db.execute("SELECT payload FROM eval_issue_retests WHERE issue_id=? ORDER BY rowid", (issue_id,)).fetchall()
        if not row:
            raise fail("issue_not_found", "未找到该问题。", 404)
        return self.issue_state(json.loads(row[0]), [json.loads(item[0]) for item in retests])

    def update_issue(self, issue_id: str, body: IssueUpdateInput, user: Principal) -> dict:
        allowed = {"open": {"open", "in_progress"},
                   "in_progress": {"open", "in_progress", "ready_for_retest"},
                   "ready_for_retest": {"in_progress", "ready_for_retest", "closed"},
                   "closed": {"closed", "in_progress"}}
        with self.lock, self.db:
            row = self.db.execute("SELECT payload FROM eval_issues WHERE issue_id=?", (issue_id,)).fetchone()
            if not row:
                raise fail("issue_not_found", "未找到该问题。", 404)
            retests = [json.loads(item[0]) for item in self.db.execute(
                "SELECT payload FROM eval_issue_retests WHERE issue_id=? ORDER BY rowid", (issue_id,))]
            record = self.issue_state(json.loads(row[0]), retests)
            if record["revision"] != body.expected_revision:
                raise fail("issue_revision_conflict", "问题已有新处理记录，请刷新后重试。")
            if body.status not in allowed[record["status"]]:
                raise fail("issue_transition_invalid", "请按待处理、处理中、待复测、关闭的顺序流转。", 422)
            latest = retests[-1] if retests else None
            if body.status == "closed" and not (latest and latest["overall"] == "pass" and latest.get("version_verified")):
                raise fail("issue_pass_retest_required", "关闭问题需要最近一次独立复测通过且 Run 版本已核验。", 422)
            record["history"].append({"at": now(), "by": user.tester_id, "action": "updated",
                                      "from_status": record["status"], "to_status": body.status,
                                      "from_assignee": record["assignee"], "assignee": body.assignee,
                                      "note": body.note})
            record.update(status=body.status, assignee=body.assignee, revision=record["revision"] + 1)
            record.pop("retests", None)
            self.db.execute("UPDATE eval_issues SET payload=? WHERE issue_id=?",
                            (json.dumps(record, ensure_ascii=False), issue_id))
        return self.issue(issue_id)

    def record_retest(self, issue_id: str, body: RetestInput, user: Principal) -> dict:
        issue = self.issue(issue_id)
        execution = self.evaluations.execution(body.execution_id, user)
        if execution["execution_id"] == issue["execution_id"] or (execution["case_id"], execution["case_version"]) != (issue["case_id"], issue["case_version"]):
            raise fail("retest_case_mismatch", "复测必须使用同一用例版本的新执行。", 422)
        review = execution["review"]
        if not review:
            raise fail("retest_review_required", "复测需先提交独立评分。", 422)
        with self.lock:
            if self.db.execute("SELECT 1 FROM eval_issue_retests WHERE execution_id=?", (body.execution_id,)).fetchone():
                raise fail("retest_already_linked", "该执行已关联问题复测。")
        versions, missing_runs = self.evaluations.run_versions(review["run_ids"])
        verified = (not missing_runs and len(versions) == 1 and
                    body.fix_version in {versions[0], versions[0].split(":", 1)[0]})
        if review["overall"] != "blocked" and not verified:
            raise fail("retest_version_mismatch", "修复版本须与复测 Run 的实际构建或完整配置标识一致；缺少 Run 或混用版本时不能关联有效复测。", 422)
        record = {"retest_id": str(uuid4()), "issue_id": issue_id, "execution_id": body.execution_id,
                  "review_id": review["review_id"], "run_ids": review["run_ids"],
                  "overall": review["overall"], "fix_version": body.fix_version,
                  "runtime_config_versions": versions, "version_verified": verified,
                  "notes": body.notes, "created_at": now(), "recorded_by": user.tester_id}
        with self.lock, self.db:
            prior = self.db.execute("SELECT 1 FROM eval_issue_retests WHERE execution_id=?", (body.execution_id,)).fetchone()
            if prior:
                raise fail("retest_already_linked", "该执行已关联问题复测。")
            self.db.execute("INSERT INTO eval_issue_retests VALUES (?,?,?,?)",
                            (record["retest_id"], issue_id, body.execution_id, json.dumps(record, ensure_ascii=False)))
            row = self.db.execute("SELECT payload FROM eval_issues WHERE issue_id=?", (issue_id,)).fetchone()
            issue_record = json.loads(row[0])
            previous = issue_record.get("status", issue["status"])
            next_status = "closed" if record["overall"] == "pass" and verified else (
                "ready_for_retest" if record["overall"] == "blocked" else "in_progress")
            history = issue_record.get("history", [])
            history.append({"at": now(), "by": user.tester_id, "action": "retest_linked",
                            "from_status": previous, "to_status": next_status,
                            "retest_id": record["retest_id"], "overall": record["overall"],
                            "version_verified": verified, "note": body.notes})
            issue_record.update(status=next_status, revision=issue_record.get("revision", 1) + 1,
                                history=history)
            self.db.execute("UPDATE eval_issues SET payload=? WHERE issue_id=?",
                            (json.dumps(issue_record, ensure_ascii=False), issue_id))
        return record

    def record_assessment(self, body: AssessmentInput, user: Principal) -> dict:
        if body.kind == "domain_expert" and user.role != "reviewer":
            raise fail("expert_reviewer_required", "领域专家签核需专家审核身份。", 403)
        if body.kind == "ai_assisted" and user.role != "developer":
            raise fail("developer_required", "AI 辅助复核归档需开发者身份。", 403)
        self.evaluations.case(body.case_id, body.case_version)
        review_id = None
        if body.execution_id:
            execution = self.evaluations.execution(body.execution_id, user)
            if (execution["case_id"], execution["case_version"]) != (body.case_id, body.case_version):
                raise fail("assessment_case_mismatch", "来源审核与用例版本不一致。", 422)
            review_id = execution["review"]["review_id"] if execution["review"] else None
        record = {**body.model_dump(), "assessment_id": str(uuid4()), "recorded_at": now(),
                  "recorded_by": user.tester_id, "reviewer_role": user.role,
                  "review_id": review_id}
        with self.lock, self.db:
            self.db.execute("INSERT INTO eval_assessments VALUES (?,?)",
                            (record["assessment_id"], json.dumps(record, ensure_ascii=False)))
        return record

    def assessments(self, case_id: str | None = None) -> list[dict]:
        with self.lock:
            rows = self.db.execute("SELECT payload FROM eval_assessments ORDER BY rowid DESC").fetchall()
        items = [json.loads(row[0]) for row in rows]
        return [item for item in items if case_id is None or item["case_id"] == case_id]

    def review_queue(self, status: str | None = None) -> list[dict]:
        allowed = {"pending_development", "unassigned", "pending_expert", "expert_consensus",
                   "expert_disagreement", "resolved_disagreement"}
        if status and status not in allowed:
            raise fail("review_queue_status_invalid", "未知的审核队列状态。", 422)
        with self.lock:
            executions = self.db.execute("""SELECT e.execution_id,e.case_id,e.case_version,e.tester_id,
                e.created_at,e.status,r.payload FROM eval_executions e
                LEFT JOIN eval_reviews r ON r.execution_id=e.execution_id
                ORDER BY e.created_at DESC,e.execution_id DESC""").fetchall()
            assignments = [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM eval_review_assignments").fetchall()]
            assessments = [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM eval_assessments").fetchall()]
            resolutions = [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM eval_review_resolutions ORDER BY rowid").fetchall()]
        result = []
        for eid, cid, version, tester, created, execution_status, raw_review in executions:
            review = json.loads(raw_review) if raw_review else None
            assigned = [item for item in assignments if item["execution_id"] == eid]
            experts = [item for item in assessments if item.get("execution_id") == eid
                       and item["kind"] == "domain_expert"]
            ids = sorted(item["assessment_id"] for item in experts)
            current_resolution = next((item for item in reversed(resolutions)
                                       if item["execution_id"] == eid and sorted(item["assessment_ids"]) == ids), None)
            pending = [item["reviewer_id"] for item in assigned if
                       item["reviewer_id"] not in {assessment["recorded_by"] for assessment in experts}]
            if not review:
                stage = "pending_development"
            elif not assigned and not experts:
                stage = "unassigned"
            elif pending or not experts:
                stage = "pending_expert"
            elif len({item["overall"] for item in experts}) > 1:
                stage = "resolved_disagreement" if current_resolution else "expert_disagreement"
            else:
                stage = "expert_consensus"
            item = {"execution_id": eid, "case_id": cid, "case_version": version,
                    "tester_id": tester, "created_at": created, "execution_status": execution_status,
                    "development_review": review, "assignments": assigned,
                    "expert_assessments": experts, "pending_reviewers": pending,
                    "resolution": current_resolution, "status": stage}
            if not status or stage == status:
                result.append(item)
        return result

    def assign_review(self, eid: str, body: ReviewAssignmentInput, user: Principal) -> dict:
        with self.lock, self.db:
            row = self.db.execute("SELECT status FROM eval_executions WHERE execution_id=?", (eid,)).fetchone()
            if not row:
                raise fail("execution_not_found", "未找到该执行。", 404)
            if row[0] != "reviewed":
                raise fail("development_review_required", "须先提交执行评分，再分派专家审核。", 422)
            if self.db.execute("SELECT 1 FROM eval_review_assignments WHERE execution_id=? AND reviewer_id=?",
                               (eid, body.reviewer_id)).fetchone():
                raise fail("review_already_assigned", "该审核人已被分派。")
            record = {"assignment_id": str(uuid4()), "execution_id": eid,
                      "reviewer_id": body.reviewer_id, "assigned_by": user.tester_id,
                      "assigned_at": now(), "note": body.note}
            self.db.execute("INSERT INTO eval_review_assignments VALUES (?,?,?)",
                            (eid, body.reviewer_id, json.dumps(record, ensure_ascii=False)))
        return record

    def resolve_review(self, eid: str, body: ReviewResolutionInput, user: Principal) -> dict:
        with self.lock, self.db:
            if not self.db.execute("SELECT 1 FROM eval_executions WHERE execution_id=?", (eid,)).fetchone():
                raise fail("execution_not_found", "未找到该执行。", 404)
            assessments = [json.loads(row[0]) for row in self.db.execute(
                "SELECT payload FROM eval_assessments").fetchall()]
            experts = [item for item in assessments if item.get("execution_id") == eid
                       and item["kind"] == "domain_expert"]
            ids = [item["assessment_id"] for item in experts]
            if len(ids) < 2 or len({item["recorded_by"] for item in experts}) < 2 or len({item["overall"] for item in experts}) < 2:
                raise fail("review_disagreement_required", "至少两位专家对同一执行提交不同结论后才能记录分歧处理。", 422)
            if sorted(body.assessment_ids) != sorted(ids):
                raise fail("review_resolution_stale", "审核记录已变化；请纳入当前全部专家结论后再处理分歧。", 409)
            record = {"resolution_id": str(uuid4()), "execution_id": eid,
                      "assessment_ids": sorted(ids), "conclusion": body.conclusion,
                      "rationale": body.rationale, "resolved_by": user.tester_id,
                      "resolved_at": now(), "kind": "expert_disagreement_resolution"}
            self.db.execute("INSERT INTO eval_review_resolutions VALUES (?,?,?)",
                            (record["resolution_id"], eid, json.dumps(record, ensure_ascii=False)))
        return record

    def dashboard(self, task_id: str) -> dict:
        """Execution counts within one frozen task; never a professional accuracy rate."""
        task = self.task(task_id)
        with self.lock:
            rows = self.db.execute("""SELECT e.execution_id,e.case_id,e.case_version,e.status,r.payload
                FROM eval_task_executions t JOIN eval_executions e ON e.execution_id=t.execution_id
                LEFT JOIN eval_reviews r ON r.execution_id=e.execution_id WHERE t.task_id=?""", (task_id,)).fetchall()
            assessment_rows = self.db.execute("SELECT payload FROM eval_assessments").fetchall()
            issue_rows = self.db.execute("SELECT payload FROM eval_issues").fetchall()
            retest_rows = self.db.execute("SELECT issue_id,payload FROM eval_issue_retests ORDER BY rowid").fetchall()
            has_regressions = bool(self.db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='eval_regressions'").fetchone())
            regressions = [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM eval_regressions").fetchall()] if has_regressions else []
            replays = [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM eval_replays").fetchall()] if has_regressions else []
            reviews_by_execution = {row[0]: json.loads(row[1]) for row in self.db.execute("SELECT execution_id,payload FROM eval_reviews").fetchall()}
        executions = [{"execution_id": row[0], "case_id": row[1], "case_version": row[2],
                       "status": row[3], "review": json.loads(row[4]) if row[4] else None} for row in rows]
        ids = {item["execution_id"] for item in executions}
        def counts(items: list[dict]) -> dict:
            reviews = [item["review"] for item in items if item["review"]]
            outcomes = {name: sum(review["overall"] == name for review in reviews)
                        for name in ("pass", "partial", "fail", "blocked")}
            return {"executions": len(items), "pending": len(items) - len(reviews),
                    "scored_denominator": outcomes["pass"] + outcomes["partial"] + outcomes["fail"],
                    **outcomes}
        by_case = [{"case_id": case["case_id"], "case_version": case["case_version"],
                    **counts([item for item in executions if (item["case_id"], item["case_version"]) ==
                              (case["case_id"], case["case_version"])])}
                   for case in task["case_versions"]]
        linked_assessments = [json.loads(row[0]) for row in assessment_rows
                              if (item := json.loads(row[0])).get("execution_id") in ids]
        assessment_counts = {name: sum(item["kind"] == name for item in linked_assessments)
                             for name in ("ai_assisted", "domain_expert")}
        issues = [json.loads(row[0]) for row in issue_rows if json.loads(row[0]).get("task_id") == task_id]
        retests_by_issue: dict[str, list[dict]] = {}
        for issue_id, payload in retest_rows:
            retests_by_issue.setdefault(issue_id, []).append(json.loads(payload))
        unresolved = 0
        for issue in issues:
            retests = retests_by_issue.get(issue["issue_id"], [])
            unresolved += self.issue_state(issue, retests)["status"] != "closed"
        baseline_by_regression = {item["regression_id"]: item["baseline"]["execution_id"] for item in regressions}
        severe = []
        for replay in replays:
            baseline_id = baseline_by_regression.get(replay["regression_id"])
            candidate_id = replay.get("execution_id")
            if baseline_id not in ids or not candidate_id:
                continue
            baseline_review = reviews_by_execution.get(baseline_id)
            candidate_review = reviews_by_execution.get(candidate_id)
            if not baseline_review or not candidate_review:
                continue
            reasons = []
            if baseline_review["overall"] == "pass" and candidate_review["overall"] == "fail":
                reasons.append("overall_pass_to_fail")
            for field in ("evidence_correct", "answer_correct"):
                if baseline_review[field] == "yes" and candidate_review[field] == "no":
                    reasons.append(f"{field}_yes_to_no")
            if reasons:
                severe.append({"regression_id": replay["regression_id"], "replay_id": replay["replay_id"],
                               "baseline_execution_id": baseline_id, "candidate_execution_id": candidate_id,
                               "reasons": reasons})
        return {"task": task, "summary": counts(executions), "by_case_version": by_case,
                "assessment_counts": assessment_counts,
                "issues": {"total": len(issues), "unresolved": unresolved},
                "severe_regressions": severe,
                "metric_policy": "one frozen task; execution counts, not case success rate; blocked/pending excluded from scored denominator; linked AI/expert assessments separate; severe regression requires two submitted development reviews"}
