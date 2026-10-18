"""Durable paired trials; interruption never causes automatic model replay."""
from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timezone
from uuid import uuid4

from fastapi import HTTPException
from loguru import logger
from pydantic import Field, field_validator
from typing import Literal

from src.agent.contracts import Contract
from src.agent.case_skills import trial_system_prompt
from src.agent.explanation_method import METHOD_SOURCE, inspect_explanation
from src.agent.skill_config import ExpressionPreferences
from src.agent.submissions import ChatRunManager
from src.api.chat_schema import ChatRequest
from src.storage.prompt_versions import LEGACY_PROMPT, ENHANCED_PROMPT


class TrialPrompt(Contract):
    label: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=24000)

    @field_validator("label", "text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Prompt 名称和正文不能为空。")
        return value

    def snapshot(self):
        digest = hashlib.sha256(self.text.encode()).hexdigest()
        return {**self.model_dump(), "sha256": digest, "version": "prompt-" + digest[:12]}


class TrialPrompts(Contract):
    baseline: TrialPrompt
    candidate: TrialPrompt


def default_prompts():
    return TrialPrompts(
        baseline=TrialPrompt(label="原版解释 v1", text=LEGACY_PROMPT),
        candidate=TrialPrompt(label="增强解释 v2", text=ENHANCED_PROMPT),
    )


def prompt_templates():
    return {variant: prompt.snapshot() for variant, prompt in default_prompts()}


class TrialInput(Contract):
    submission_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    query: str = Field(min_length=1, max_length=3000)
    material: str = Field(default="", max_length=18000)
    prompts: TrialPrompts = Field(default_factory=default_prompts)

    @field_validator("query")
    @classmethod
    def nonblank_query(cls, value):
        if not value.strip():
            raise ValueError("用户问题不能为空。")
        return value


class TrialJudgment(Contract):
    submission_id: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_-]+$")
    variant: Literal["baseline", "candidate"]
    dimension: Literal["fidelity", "comprehension"]
    conclusion: Literal["pass", "partial", "fail", "unjudgeable"]
    basis: str = Field(min_length=1, max_length=5000)


class ExplanationTrials:
    def __init__(self, runtime, manager=None):
        self.runtime = runtime
        self.db, self.lock = runtime.runs._connection, runtime.runs._lock
        self.tasks = {}
        self.manager = manager or ChatRunManager(runtime.runs.live)
        with self.lock, self.db:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS explanation_trials (
                    trial_id TEXT PRIMARY KEY, actor TEXT NOT NULL, submission_id TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, payload TEXT NOT NULL,
                    UNIQUE(actor,submission_id));
                CREATE TABLE IF NOT EXISTS explanation_trial_judgments (
                    trial_id TEXT NOT NULL, submission_id TEXT NOT NULL, actor TEXT NOT NULL,
                    fingerprint TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(trial_id,submission_id));
            """)
            self.db.execute("UPDATE explanation_trials SET status='interrupted' WHERE status IN ('accepted','running')")

    def list_prompts(self, user):
        return self.runtime.runs.prompts.list()

    def save_prompt(self, body, user):
        return self.runtime.runs.prompts.save(body.label, body.text, user.tester_id)

    def _row(self, trial_id):
        row = self.db.execute("SELECT actor,status,payload FROM explanation_trials WHERE trial_id=?", (trial_id,)).fetchone()
        if not row: raise HTTPException(404, detail={"code": "trial_not_found", "message": "未找到此对照试验。"})
        return row

    def get(self, trial_id, user):
        with self.lock:
            actor, status, raw = self._row(trial_id)
            if actor != user.tester_id and user.role not in {"developer", "reviewer"}: raise HTTPException(404, detail={"code": "trial_not_found", "message": "未找到此对照试验。"})
            judgments = [json.loads(row[0]) for row in self.db.execute("SELECT payload FROM explanation_trial_judgments WHERE trial_id=? ORDER BY rowid", (trial_id,))]
        return {**json.loads(raw), "status": status, "judgments": judgments}

    def list(self, user):
        with self.lock:
            rows = self.db.execute("SELECT trial_id FROM explanation_trials" + ("" if user.role in {"developer", "reviewer"} else " WHERE actor=?") + " ORDER BY created_at DESC LIMIT 50", () if user.role in {"developer", "reviewer"} else (user.tester_id,)).fetchall()
        return [self.get(row[0], user) for row in rows]

    def submit(self, body, user, *, llm):
        fingerprint = hashlib.sha256(json.dumps(body.model_dump(exclude={"submission_id"}), sort_keys=True).encode()).hexdigest()
        saved = self.runtime.runs.prompts.list()
        left = next((item for item in saved if item["label"] == body.prompts.baseline.label and item["text"] == body.prompts.baseline.text), None)
        if left is None:
            raise HTTPException(422, detail={"code": "historical_prompt_required", "message": "左侧请选择一个已保存的 Prompt 版本。"})
        right = next((item for item in saved if item["label"] == body.prompts.candidate.label and item["text"] == body.prompts.candidate.text), None)
        right = right or self.save_prompt(body.prompts.candidate, user)
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            prior = self.db.execute("SELECT trial_id,fingerprint FROM explanation_trials WHERE actor=? AND submission_id=?", (user.tester_id, body.submission_id)).fetchone()
            if prior:
                if prior[1] != fingerprint: raise HTTPException(409, detail={"code": "trial_submission_conflict", "message": "相同提交标识不能对应不同问题、材料或 Prompt。"})
                trial_id = prior[0]
                created = False
            else:
                if len(self.tasks) >= 2: raise HTTPException(429, detail={"code": "trial_capacity", "message": "已有对照试验正在运行，请稍后重试。"})
                trial_id = str(uuid4())
                value = {"trial_id": trial_id, "query": body.query, "material": body.material, "material_fingerprint": hashlib.sha256(body.material.encode()).hexdigest(),
                         "method_version": "prompt-comparison-v1", "source": METHOD_SOURCE, "actor": user.tester_id, "variants": {},
                         "prompts": {"baseline": left, "candidate": right},
                         "created_at": datetime.now(timezone.utc).isoformat(), "config_version": self.runtime.config_version}
                self.db.execute("INSERT INTO explanation_trials VALUES (?,?,?,?,?,?,?)", (trial_id, user.tester_id, body.submission_id, fingerprint, "accepted", value["created_at"], json.dumps(value, ensure_ascii=False)))
                created = True
        if created:
            task = asyncio.create_task(self._execute(trial_id, user, llm))
            self.tasks[trial_id] = task
            task.add_done_callback(lambda completed: self._done(trial_id, completed))
        return self.get(trial_id, user)

    def _done(self, trial_id, task):
        self.tasks.pop(trial_id, None)
        try:
            with self.lock, self.db:
                self.db.execute("UPDATE explanation_trials SET status=? WHERE trial_id=? AND status IN ('accepted','running')",
                                ("interrupted" if task.cancelled() else "unknown", trial_id))
            if not task.cancelled(): task.exception()
        except Exception:
            logger.exception("Trial terminal state unavailable; no execution will repeat | trial_id={}", trial_id)

    def _save(self, trial_id, value, status):
        with self.lock, self.db:
            self.db.execute("UPDATE explanation_trials SET status=?,payload=? WHERE trial_id=?", (status, json.dumps(value, ensure_ascii=False), trial_id))

    async def _execute(self, trial_id, user, llm):
        value = self.get(trial_id, user)
        value.pop("judgments", None); value.pop("status", None)
        try:
            for variant in ("baseline", "candidate"):
                prompt = value["prompts"][variant]
                config = {"version": prompt["version"], "values": ExpressionPreferences().model_dump(),
                          "trial_prompt": trial_system_prompt(prompt["text"]), "communication": prompt,
                          "prompt_label": prompt["label"], "prompt_sha256": prompt["sha256"]}
                owner = "internal_" + user.tester_id
                session_id = "trial_" + trial_id.replace("-", "")
                request_id = trial_id + "-" + variant
                body = ChatRequest(query=value["query"] + ("\n待解释材料：\n" + value["material"] if value["material"] else ""), session_id=session_id,
                                   case_skill="explain", operator_id=user.tester_id, turn_id=trial_id, request_id=request_id)
                async def execute(record, observer):
                    return await asyncio.wait_for(self.runtime.execute(body, service=None, get_report=None, llm=llm,
                        run_id=record["run_id"], observer=observer, expression_config=config,
                        run_context={key: record[key] for key in ("source", "mode", "turn_id", "request_id", "primary_run_id", "rerun_of_run_id")}), timeout=240)
                fingerprint = hashlib.sha256(body.query.encode()).hexdigest()
                accepted = self.manager.submit(execute=execute, owner=owner, session_id=session_id, turn_id=trial_id,
                    request_id=request_id, fingerprint=fingerprint, rerun_of_run_id=value["variants"].get("baseline", {}).get("run_id") if variant == "candidate" else None,
                    config_version=self.runtime.config_version + ":" + config["version"], source="test", mode="specified")
                run_id = accepted["run_id"]
                value["variants"][variant] = {"run_id": run_id, "status": "running"}
                self._save(trial_id, value, "running")
                task = self.manager.tasks.get(run_id)
                if task: await task
                finished = self.manager.get(owner, run_id)
                if finished["status"] == "cancelled": raise asyncio.CancelledError()
                if finished["status"] != "succeeded" or not finished["result_saved"]:
                    raise RuntimeError("trial_variant_not_saved")
                response = finished["result"]
                value["variants"][variant] = {"run_id": run_id, "status": "succeeded", "answer": response["answer"],
                    "checks": inspect_explanation(value["query"] + "\n" + value["material"], response["answer"]),
                    "prompt": prompt, "actual_config": config, "model": response["model"]}
                self._save(trial_id, value, "running")
            self._save(trial_id, value, "completed")
        except asyncio.CancelledError:
            self._save(trial_id, value, "interrupted")
        except Exception:
            logger.exception("Explanation trial stopped without replay | trial_id={}", trial_id)
            self._save(trial_id, value, "failed")

    def judge(self, trial_id, body, user):
        trial = self.get(trial_id, user)
        if body.dimension == "fidelity" and user.role != "reviewer": raise HTTPException(403, detail={"code": "expert_judgment_required", "message": "专业忠实性结论由领域审核者填写。"})
        if trial["variants"].get(body.variant, {}).get("status") != "succeeded": raise HTTPException(409, detail={"code": "trial_not_ready", "message": "请等待该方案完成后再评价。"})
        fingerprint = hashlib.sha256(json.dumps({**body.model_dump(), "actor": user.tester_id}, sort_keys=True).encode()).hexdigest()
        with self.lock, self.db:
            prior = self.db.execute("SELECT fingerprint,payload FROM explanation_trial_judgments WHERE trial_id=? AND submission_id=?", (trial_id, body.submission_id)).fetchone()
            if prior:
                if prior[0] != fingerprint: raise HTTPException(409, detail={"code": "trial_judgment_conflict", "message": "相同评价提交标识对应不同内容。"})
                return json.loads(prior[1])
            value = {**body.model_dump(), "actor": user.tester_id, "role": user.role, "method": "human", "created_at": datetime.now(timezone.utc).isoformat()}
            self.db.execute("INSERT INTO explanation_trial_judgments VALUES (?,?,?,?,?)", (trial_id, body.submission_id, user.tester_id, fingerprint, json.dumps(value, ensure_ascii=False)))
        return value

    async def shutdown(self):
        tasks = list(self.tasks.values())
        for task in tasks: task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
