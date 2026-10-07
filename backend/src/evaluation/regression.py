"""Frozen regression baselines and bounded replay against the current build.

No replay is a human review. Unsupported manual steps or missing original
fixtures stop the replay; they are never skipped or replaced with guessed data.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path
from uuid import uuid4

from starlette.requests import Request

from src.evaluation.contracts import EvaluationQuery, ManualAction, Principal
from src.evaluation.store import fail, now


def query_snapshot(event, traces):
    response = event.get("response") or {}
    trace = traces.get(event.get("run_id")) or {}
    return {
        "input": event.get("input"), "run_id": event.get("run_id"),
        "answer": response.get("answer", trace.get("answer")),
        "route": response.get("agent_route") or (trace.get("decision") or {}).get("route"),
        "outcome": response.get("outcome", trace.get("outcome")), "error": event.get("error"),
        "tools": [{k: tool.get(k) for k in ("skill", "status", "error_code")} for tool in trace.get("tool_calls", [])],
        "file_evidence": response.get("file_evidence", []),
        "citations": [{k: c.get(k) for k in ("index", "chunk_id", "source", "title", "author_hint", "snippet")} for c in response.get("citations", [])],
        "latency_ms": trace.get("latency_ms"), "config_version": trace.get("config_version"),
        "model": response.get("model", trace.get("model")), "trace_saved": bool(trace),
    }


class RegressionService:
    def __init__(self, evaluation):
        self.evaluation = evaluation
        self.store = evaluation.store
        self.jobs: dict[str, asyncio.Task] = {}
        with self.store.lock, self.store.db:
            self.store.db.executescript("""
                CREATE TABLE IF NOT EXISTS eval_regressions (
                  regression_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS eval_replays (
                  replay_id TEXT PRIMARY KEY, regression_id TEXT NOT NULL,
                  created_at TEXT NOT NULL, payload TEXT NOT NULL);
            """)
            # A restart cannot leave an apparently running job forever.
            for rid, raw in self.store.db.execute("SELECT replay_id,payload FROM eval_replays").fetchall():
                value = json.loads(raw)
                if value["state"] in {"queued", "running"}:
                    value.update(state="interrupted", message="服务重启中断了本次重跑，请新建重跑。", finished_at=now())
                    self.store.db.execute("UPDATE eval_replays SET payload=? WHERE replay_id=?", (json.dumps(value, ensure_ascii=False), rid))

    def traces(self, execution):
        result = {}
        for event in execution["events"]:
            if event.get("run_id"):
                trace = self.store.runs.get(event["run_id"])
                if trace:
                    result[trace.run_id] = trace.model_dump(mode="json")
        return result

    def create(self, eid, title, notes, user):
        if eid in self.evaluation.busy or eid in self.evaluation.replay_owners:
            raise fail("execution_busy", "请等待原执行完成后再保存回归基线。")
        execution = self.store.execution(eid, user)
        queries = sum(e["action"] == "query" for e in execution["events"])
        if not 1 <= queries <= 20:
            raise fail("regression_query_limit", "回归基线需要 1–20 轮提问。")
        rid = str(uuid4())
        value = {"regression_id": rid, "created_at": now(), "created_by": user.tester_id,
                 "title": title, "notes": notes, "baseline": execution,
                 "case_snapshot": self.store.case(execution["case_id"], execution["case_version"]),
                 "traces": self.traces(execution), "professional_review": "pending"}
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT INTO eval_regressions VALUES (?,?,?)", (rid, value["created_at"], json.dumps(value, ensure_ascii=False)))
        return value

    def get(self, rid):
        with self.store.lock:
            row = self.store.db.execute("SELECT payload FROM eval_regressions WHERE regression_id=?", (rid,)).fetchone()
        if not row:
            raise fail("regression_not_found", "未找到回归基线。", 404)
        return json.loads(row[0])

    def list(self, limit=50, offset=0):
        with self.store.lock:
            rows = self.store.db.execute("SELECT payload FROM eval_regressions ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)).fetchall()
        values = [json.loads(row[0]) for row in rows]
        return [{"regression_id": v["regression_id"], "title": v["title"], "created_at": v["created_at"],
                 "case_id": v["baseline"]["case_id"], "case_version": v["baseline"]["case_version"],
                 "baseline_execution_id": v["baseline"]["execution_id"],
                 "baseline_versions": sorted({t["config_version"] for t in v["traces"].values()}),
                 "replays": self.list_replays(v["regression_id"])} for v in values]

    def replay(self, rid):
        with self.store.lock:
            row = self.store.db.execute("SELECT payload FROM eval_replays WHERE replay_id=?", (rid,)).fetchone()
        if not row:
            raise fail("replay_not_found", "未找到重跑记录。", 404)
        return json.loads(row[0])

    def list_replays(self, rid):
        with self.store.lock:
            rows = self.store.db.execute("SELECT payload FROM eval_replays WHERE regression_id=? ORDER BY created_at DESC LIMIT 20", (rid,)).fetchall()
        return [json.loads(row[0]) for row in rows]

    def update(self, rid, **changes):
        value = self.replay(rid)
        value.update(changes)
        with self.store.lock, self.store.db:
            self.store.db.execute("UPDATE eval_replays SET payload=? WHERE replay_id=?", (json.dumps(value, ensure_ascii=False), rid))
        return value

    def prepare(self, baseline, case_snapshot=None):
        plan = []
        total_bytes = 0
        root = Path(__file__).resolve().parents[3]
        frozen_fixtures = {fixture["filename"]: fixture for fixture in
                           (case_snapshot or {}).get("fixtures", [])}
        for step, event in enumerate(baseline["events"], 1):
            action = event["action"]
            if action in {"query", "clear", "remove_attachment"}:
                plan.append((event, None))
            elif action == "upload" and event.get("attachment"):
                attachment = event["attachment"]
                fixture = frozen_fixtures.get(attachment["filename"])
                if fixture and "path" not in fixture:
                    # Seeded cases omit local paths in their public snapshot.
                    fixture = self.store.fixtures.get(attachment["filename"])
                if not fixture:
                    return plan, {"step": step, "action": action, "message": "原附件未登记为本地回归材料，需人工准备对应材料。"}
                path = (root / fixture["path"]).resolve()
                if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
                    return plan, {"step": step, "action": action, "message": "原附件缺失或超出本地回归材料范围。"}
                raw = path.read_bytes()
                total_bytes += len(raw)
                if total_bytes > 64 * 1024 * 1024:
                    return plan, {"step": step, "action": action, "message": "本次重跑附件合计超过 64 MiB，需人工处理。"}
                if hashlib.sha256(raw).hexdigest() != attachment["sha256"]:
                    return plan, {"step": step, "action": action, "message": "原附件指纹发生变化，需核对基线文件。"}
                plan.append((event, raw))
            else:
                return plan, {"step": step, "action": action, "message": "基线在此处需要人工操作或含不可复原步骤；已暂停，未跳过。"}
        return plan, None

    def start(self, rid, request, user):
        if len(self.jobs) >= 2:
            raise fail("replay_capacity", "已有两项重跑进行中，请等待或取消后再试。", 429)
        frozen = self.get(rid)
        baseline = frozen["baseline"]
        replay_id = str(uuid4())
        value = {"replay_id": replay_id, "regression_id": rid, "created_at": now(), "created_by": user.tester_id,
                 "execution_id": None, "state": "queued", "completed_steps": 0, "total_steps": len(baseline["events"]),
                 "message": "等待执行", "professional_review": "pending"}
        with self.store.lock, self.store.db:
            self.store.db.execute("INSERT INTO eval_replays VALUES (?,?,?,?)", (replay_id, rid, value["created_at"], json.dumps(value, ensure_ascii=False)))
        try:
            plan, blocker = self.prepare(baseline, frozen.get("case_snapshot"))
        except Exception as exc:
            detail = getattr(exc, "detail", {})
            return self.update(replay_id, state="blocked", message=detail.get("message", "无法准备基线材料。"), finished_at=now())
        if blocker and not plan:
            return self.update(replay_id, state="blocked", blocked_step=blocker,
                               message=f"第 {blocker['step']} 步待人工：{blocker['message']}", finished_at=now())
        self.evaluation.prune()
        if len(self.evaluation.contexts) >= 256:
            return self.update(replay_id, state="blocked", message="活动上下文容量已满。", finished_at=now())
        execution = self.store.create(baseline["case_id"], baseline["case_version"], user)
        eid = execution["execution_id"]
        self.evaluation.reset(eid)
        self.update(replay_id, execution_id=eid)
        task = asyncio.create_task(self._run(replay_id, eid, request, user, plan, blocker))
        self.jobs[replay_id] = task
        self.evaluation.replay_owners[eid] = task
        def finished(done):
            self.jobs.pop(replay_id, None)
            self.evaluation.replay_owners.pop(eid, None)
            value = self.replay(replay_id)
            if value["state"] in {"queued", "running"}:
                self.update(replay_id, state="cancelled" if done.cancelled() else "failed",
                            message="任务在完成前中止，请新建重跑。", finished_at=now())
            if not done.cancelled():
                done.exception()  # Consume unexpected failure without leaking exception details.
        task.add_done_callback(finished)
        return self.replay(replay_id)

    async def _run(self, rid, eid, request, user, plan, blocker):
        from src.api.evaluation import action, query, upload
        self.update(rid, state="running", message="按基线顺序执行")
        try:
            for index, (event, raw) in enumerate(plan, 1):
                if event["action"] == "query":
                    result = await query(request, eid, EvaluationQuery(query=event["input"]), user)
                elif event["action"] == "upload":
                    async def receive():
                        return {"type": "http.request", "body": raw, "more_body": False}
                    synthetic = Request({"type": "http", "method": "POST", "path": "/api/eval/replay-upload", "headers": [], "app": request.app}, receive=receive)
                    result = await upload(synthetic, eid, event["attachment"]["filename"], user)
                else:
                    result = await action(request, eid, ManualAction(action=event["action"], note="按冻结基线重跑"), user)
                self.update(rid, completed_steps=index)
                latest = result["events"][-1]
                if latest.get("trace_missing") or (event["action"] == "upload" and latest.get("error")):
                    raise fail("replay_step_failed", "上传或运行记录保存失败，未继续后续步骤。")
            if blocker:
                self.update(rid, state="blocked", blocked_step=blocker,
                            message=f"第 {blocker['step']} 步待人工：{blocker['message']}", finished_at=now())
            else:
                self.update(rid, state="completed", message="重跑完成；差异待人工判断。", finished_at=now())
        except asyncio.CancelledError:
            self.update(rid, state="cancelled", message="重跑已取消，已完成步骤保留。", finished_at=now())
        except Exception as exc:
            detail = getattr(exc, "detail", {})
            self.update(rid, state="failed", message=detail.get("message", "重跑中断，请查看已保存的执行和 Trace。"), finished_at=now())
        finally:
            self.jobs.pop(rid, None)
            self.evaluation.replay_owners.pop(eid, None)

    async def shutdown(self):
        tasks = list(self.jobs.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def cancel(self, rid):
        task = self.jobs.get(rid)
        if not task:
            raise fail("replay_not_running", "该重跑已结束或不在当前进程中。")
        task.cancel()
        return {"message": "已请求取消，正在保存已完成的步骤。"}

    def compare(self, rid, user):
        replay = self.replay(rid)
        base = self.get(replay["regression_id"])
        candidate = self.store.execution(replay["execution_id"], user) if replay["execution_id"] else None
        before = [query_snapshot(e, base["traces"]) for e in base["baseline"]["events"] if e["action"] == "query"]
        traces = self.traces(candidate) if candidate else {}
        after = [query_snapshot(e, traces) for e in candidate["events"] if e["action"] == "query"] if candidate else []
        pairs = []
        for index in range(max(len(before), len(after))):
            left, right = before[index] if index < len(before) else None, after[index] if index < len(after) else None
            keys = ("input", "route", "outcome", "error", "tools", "file_evidence", "citations", "answer", "model", "config_version")
            changes = [k for k in keys if (left or {}).get(k) != (right or {}).get(k)]
            pairs.append({"turn": index + 1, "baseline": left, "candidate": right, "changes": changes,
                          "latency_delta_ms": right["latency_ms"] - left["latency_ms"] if left and right and left["latency_ms"] is not None and right["latency_ms"] is not None else None})
        return {"replay": replay, "title": base["title"], "case_id": base["baseline"]["case_id"],
                "case_version": base["baseline"]["case_version"], "pairs": pairs,
                "baseline_review": base["baseline"].get("review"), "candidate_review": candidate.get("review") if candidate else None,
                "professional_review": "pending", "changed_turns": sum(bool(p["changes"]) for p in pairs),
                "notes": ["差异不等于变好或变坏；专业正确性由人工审核。", "模型生成具有随机性；相同构建也可能得到不同文字。", "配置标识记录代码与运行参数，不证明语料索引和模型文件完全相同。"]}
