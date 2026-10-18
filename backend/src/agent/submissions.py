"""Single-worker, detached executions with durable admission and safe recovery."""
from __future__ import annotations

import asyncio
from collections import OrderedDict

from fastapi import HTTPException
from loguru import logger


class ChatRunManager:
    def __init__(self, store, *, retention_seconds=86400, max_active=32):
        self.store = store
        self.retention_seconds, self.max_active = retention_seconds, max_active
        self.tasks: dict[str, asyncio.Task] = {}
        self.volatile = OrderedDict()
        # Current deployment uses one worker. Never replay an unconfirmed action
        # from a previous process, even when the request fingerprint is known.
        store.recover_interrupted()

    def submit(self, *, execute, on_created=None, on_finished=None, **identity):
        try:
            record, created = self.store.admit(**identity, retention_seconds=self.retention_seconds, max_active=self.max_active)
        except HTTPException:
            raise
        except Exception as exc:
            logger.exception("Chat admission failed before execution")
            raise HTTPException(503, detail={"code": "run_admission_unavailable", "message": "本次提交暂未能确认受理，请稍后用原提交标识重试。"}) from exc
        if created:
            run_id = record["run_id"]
            task = asyncio.create_task(self._execute(record, execute), name="chat-run-" + run_id)
            self.tasks[run_id] = task
            if on_created:
                on_created()
            task.add_done_callback(lambda completed: self._done(run_id, completed, on_finished))
        return self.get(identity["owner"], record["run_id"])

    def _done(self, run_id, task, on_finished):
        try:
            # Cancellation can happen before the coroutine's first instruction,
            # in which case its finally block never runs.
            if run_id in self.tasks:
                try:
                    self.store.finish(run_id, status="cancelled" if task.cancelled() else "unknown", outcome="unfulfilled")
                except Exception:
                    logger.exception("Unable to record stopped chat | run_id={}", run_id)
                    self.store.mark_unknown(run_id)
                finally:
                    self.tasks.pop(run_id, None)
        finally:
            if on_finished:
                on_finished()

    async def _execute(self, record, execute):
        run_id = record["run_id"]
        pending = []
        lagged = False

        def observe(event):
            nonlocal lagged
            pending.append(event)
            if lagged:
                if event["type"] in {"step_started", "plan_created"}:
                    raise RuntimeError("Progress persistence unavailable before execution")
                return
            try:
                self.store.event(run_id, event)
                pending.pop()
            except Exception:
                lagged = True
                # Do not invoke a new tool whose start cannot be recorded.
                if event["type"] in {"step_started", "plan_created"}:
                    raise
                logger.exception("Progress persistence delayed | run_id={}", run_id)

        result, error, status, outcome = None, None, "failed", "unfulfilled"
        try:
            response = await execute(record, observe)
            result = response.model_dump(mode="json")
            status, outcome = "succeeded", response.outcome
        except asyncio.CancelledError:
            status, outcome = "cancelled", "unfulfilled"
        except HTTPException as exc:
            detail = exc.detail if isinstance(exc.detail, dict) else {}
            code = detail.get("code", "run_failed")
            safe_messages = {
                "rag_not_configured": "文献服务暂不可用，文件分析仍可使用。",
                "rag_query_failed": "文献检索暂时失败，请稍后重新回答。",
                "llm_unreachable": "暂时无法连接大模型服务，请稍后重新回答。",
                "llm_timeout": "大模型响应超时，请稍后重新回答。",
                "llm_rate_limited": "大模型服务请求较多，请稍后重新回答。",
                "llm_auth_failed": "大模型服务配置异常，请联系管理员。",
                "llm_upstream_error": "大模型服务暂时不可用，请稍后重新回答。",
                "internal_error": "服务内部异常，请稍后重新回答。",
                "file_not_found": "文件已过期或不可用，请重新上传。",
                "conversation_busy": "当前对话仍有问题在处理，请等待完成。",
                "request_timeout": "本次处理超时，请稍后重新执行。",
            }
            error = {"code": code, "message": safe_messages.get(code, "本次处理未完成，请稍后重新执行。"), "http_status": exc.status_code}
        except Exception:
            logger.exception("Detached chat failed | run_id={}", run_id)
            error = {"code": "run_failed", "message": "本次处理未完成，请稍后重新执行。", "http_status": 500}
        finally:
            try:
                self.store.finish(run_id, status=status, outcome=outcome, result=result, error=error, pending_events=pending)
            except Exception:
                logger.exception("Chat result persistence failed; execution will not repeat | run_id={}", run_id)
                # A useful computed answer can still be returned while this
                # process lives, but must never be advertised as durable.
                self.volatile[run_id] = {"result": result, "error": error, "result_saved": False, "status": "unknown", "outcome": "unknown"}
                while len(self.volatile) > self.max_active:
                    self.volatile.popitem(last=False)
                try:
                    self.store.mark_unknown(run_id)
                except Exception:
                    logger.exception("Unable to persist unknown status | run_id={}", run_id)
            self.tasks.pop(run_id, None)

    def get(self, owner, run_id, after=0):
        value = self.store.get(owner, run_id, after)
        if not value:
            raise HTTPException(404, detail={"code": "run_not_found", "message": "未找到此运行。"})
        if value["status"] == "expired":
            self.volatile.pop(run_id, None)
            raise HTTPException(410, detail={"code": "recovery_expired", "message": "恢复窗口已过期，请新建对话。"})
        if run_id in self.volatile:
            value.update(self.volatile[run_id])
        return {"protocol": "chat-runs-v1", **value}

    def lookup(self, owner, session_id, request_id):
        value = self.store.lookup(owner, session_id, request_id)
        if not value:
            raise HTTPException(404, detail={"code": "request_not_found", "message": "此提交尚未受理。"})
        if value["status"] == "expired":
            raise HTTPException(410, detail={"code": "recovery_expired", "message": "恢复窗口已过期，请新建对话。"})
        return self.get(owner, value["run_id"])

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
