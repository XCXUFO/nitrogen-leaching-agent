import asyncio
import json

import pytest
from fastapi import HTTPException

from src.agent.runtime import AgentRuntime
from src.agent.explanation_method import METHOD_PROMPT, inspect_explanation
from src.evaluation.contracts import Principal
from src.evaluation.explanation_trials import ExplanationTrials, TrialInput, TrialJudgment, TrialPrompt, TrialPrompts
from src.storage.run_store import RunStore
from tests.test_case_library import FakeLLM


@pytest.mark.asyncio
async def test_same_inputs_pinned_method_trusted_test_source_idempotency_and_independent_reviews():
    runtime = AgentRuntime()
    trials = ExplanationTrials(runtime)
    expert = Principal(tester_id="expert", role="reviewer")
    tester = Principal(tester_id="user", role="tester")
    class RecordingLLM(FakeLLM):
        def __init__(self): super().__init__(answer="三次施用的合计为160 kg/ha，不能推出每次用量。"); self.calls = []
        async def chat(self, messages, **kwargs):
            self.calls.append(messages)
            return await super().chat(messages, **kwargs)
    model = RecordingLLM()
    body = TrialInput(submission_id="one", query="三次合计是什么意思？", material="推荐量160 kg/ha，分三次施用，为三次合计；各次分配未知。")
    receipt = trials.submit(body, expert, llm=model)
    duplicate = trials.submit(body, expert, llm=model)
    assert receipt["trial_id"] == duplicate["trial_id"]
    await trials.tasks[receipt["trial_id"]]
    result = trials.get(receipt["trial_id"], expert)
    assert result["status"] == "completed" and len(model.calls) == 2
    assert model.calls[0][1].content == model.calls[1][1].content
    assert METHOD_PROMPT not in model.calls[0][0].content and METHOD_PROMPT in model.calls[1][0].content
    baseline = runtime.runs.get(result["variants"]["baseline"]["run_id"])
    candidate = runtime.runs.get(result["variants"]["candidate"]["run_id"])
    assert baseline.source == candidate.source == "test" and candidate.primary_run_id == baseline.run_id
    assert candidate.rerun_of_run_id == baseline.run_id
    assert candidate.skill_config["communication"]["sha256"] == result["prompts"]["candidate"]["sha256"]
    assert candidate.skill_config["case_explanation"]["trial_prompt"] == model.calls[1][0].content
    assert runtime.runs.online_metrics.summary({"source": "formal"})["questions"] == 0
    assert runtime.runs.online_metrics.summary({"source": "test"})["questions"] == 1
    fidelity = TrialJudgment(submission_id="fidelity", variant="candidate", dimension="fidelity", conclusion="pass", basis="对照完整材料，合计与单位保留。")
    saved = trials.judge(result["trial_id"], fidelity, expert)
    assert trials.judge(result["trial_id"], fidelity, expert) == saved
    with pytest.raises(HTTPException): trials.judge(result["trial_id"], fidelity, tester)
    comprehension = TrialJudgment(submission_id="understanding", variant="candidate", dimension="comprehension", conclusion="partial", basis="能够理解合计，但仍需解释单位。")
    trials.judge(result["trial_id"], comprehension, expert)
    assert {item["dimension"] for item in trials.get(result["trial_id"], expert)["judgments"]} == {"fidelity", "comprehension"}
    await trials.shutdown(); runtime.runs.close()


@pytest.mark.asyncio
async def test_trial_interruption_is_retained_and_duplicate_never_replays(tmp_path):
    path = tmp_path / "runs.sqlite3"
    runs = RunStore(path)
    runtime = AgentRuntime(runs=runs)
    trials = ExplanationTrials(runtime)
    user = Principal(tester_id="dev", role="developer")
    class BlockedModel(FakeLLM):
        def __init__(self): super().__init__(); self.started = asyncio.Event(); self.calls = 0
        async def chat(self, messages, **kwargs):
            self.calls += 1; self.started.set(); await asyncio.Event().wait()
    model = BlockedModel()
    body = TrialInput(submission_id="same", query="解释", material="固定材料")
    accepted = trials.submit(body, user, llm=model)
    await asyncio.wait_for(model.started.wait(), 2)
    await trials.shutdown()
    assert trials.get(accepted["trial_id"], user)["status"] == "interrupted"
    runs.close()
    reopened = RunStore(path)
    manager = ExplanationTrials(AgentRuntime(runs=reopened))
    found = manager.submit(body, user, llm=model)
    assert found["status"] == "interrupted" and model.calls == 1 and not manager.tasks
    reopened.close()


def test_numeric_surface_check_does_not_claim_factual_or_professional_validation():
    result = inspect_explanation("三次合计160 kg/ha；各次未知。", "三次合计160 kg/ha，每次53.3 kg/ha。")
    assert result["status"] == "needs_check" and result["additional_numbers"] == ["53.3"]
    assert "无法证明" in result["limitations"]
