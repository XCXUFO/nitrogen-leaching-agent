from __future__ import annotations

import time
import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import uuid4

from src.evaluation.contracts import Principal
from src.evaluation.store import EvaluationStore, fail
from src.evaluation.workflow import WorkflowStore
from src.evaluation.catalog import CaseCatalog


@dataclass
class ExecutionContext:
    session_id: str = field(default_factory=lambda: str(uuid4()))
    file_id: str | None = None
    attachment: dict | None = None
    history: list = field(default_factory=list)
    expires_at: float = field(default_factory=lambda: time.monotonic() + 1800)


class EvaluationService:
    def __init__(self, store: EvaluationStore):
        self.store = store
        self.workflow = WorkflowStore(store)
        self.catalog = CaseCatalog(store)
        self.contexts: dict[str, ExecutionContext] = {}
        self.busy: set[str] = set()
        self.replay_owners: dict[str, asyncio.Task] = {}

    def prune(self):
        self.contexts = {key: value for key, value in self.contexts.items()
                         if value.expires_at > time.monotonic() or key in self.busy}

    def reset(self, eid):
        self.prune()
        if eid not in self.contexts and len(self.contexts) >= 256:
            raise fail("evaluation_capacity", "活动测试过多，请稍后再试。", 503)
        self.contexts[eid] = ExecutionContext()
        return self.contexts[eid]

    def context(self, eid, execution=None):
        ctx = self.contexts.get(eid)
        if ctx is None or ctx.expires_at <= time.monotonic():
            self.contexts.pop(eid, None)
            # A never-started execution has no context to recover. Callers pass
            # the authorized execution; existing events must never be erased.
            if execution is not None and execution["status"] == "open" and not execution["events"]:
                return self.reset(eid)
            raise fail("evaluation_context_lost", "临时会话已过期或服务已重启。请点击重置上下文并重新上传附件，历史记录仍保留。")
        return ctx

    def view(self, eid, user):
        self.prune()
        result = self.store.execution(eid, user)
        ctx = self.contexts.get(eid)
        if (ctx is None and result["status"] == "open" and not result["events"]
                and result["tester_id"] == user.tester_id
                and eid not in self.busy and eid not in self.replay_owners):
            ctx = self.reset(eid)
        return {**result, "automation_running": eid in self.replay_owners, "needs_reset": ctx is None and result["status"] == "open",
                "attachment": ctx.attachment if ctx else None}

    @contextmanager
    def guard(self, eid, user: Principal):
        execution = self.store.execution(eid, user)
        if execution["tester_id"] != user.tester_id:
            raise fail("evaluation_forbidden", "只能操作自己创建的测试执行。", 403)
        if execution["status"] != "open":
            raise fail("execution_closed", "评分已提交；复测请新建执行。")
        if eid in self.replay_owners and self.replay_owners[eid] is not asyncio.current_task():
            raise fail("execution_busy", "自动重跑进行中，不能手动修改或提交评分。")
        if eid in self.busy:
            raise fail("execution_busy", "本次执行还有操作未完成，请稍后重试。")
        self.busy.add(eid)
        try:
            yield execution
        finally:
            self.busy.discard(eid)
            if eid in self.contexts:
                self.contexts[eid].expires_at = time.monotonic() + 1800

    def check_capacity(self, execution):
        if len(execution["events"]) >= 80:
            raise fail("execution_event_limit", "本次执行已达 80 步，请提交记录后新建执行。")

    def check_task_config(self, execution, runtime_config_version: str):
        if execution["task_id"]:
            task = self.workflow.task(execution["task_id"])
            if task["runtime_config_version"] != runtime_config_version:
                raise fail("task_config_mismatch", "服务配置已改变，不能继续此任务的旧执行。可查看或评分已有记录；新版本请新建任务与执行。")
