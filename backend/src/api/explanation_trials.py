"""Authenticated explanation method comparison endpoints."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi import Request
from pydantic import Field

from src.agent.explanation_method import METHOD_VERSION, METHOD_SOURCE
from src.api.chat import run_manager
from src.evaluation.auth import current_user
from src.evaluation.contracts import Principal
from src.agent.contracts import Contract
from src.evaluation.explanation_trials import ExplanationTrials, TrialInput, TrialJudgment, TrialPrompt, prompt_templates

router = APIRouter(prefix="/eval")


def trials(request):
    if not hasattr(request.app.state, "explanation_trials"):
        request.app.state.explanation_trials = ExplanationTrials(request.app.state.agent_runtime, manager=run_manager(request))
    return request.app.state.explanation_trials


@router.get("/explanation-method")
def explanation_method(request: Request, user: Principal = Depends(current_user)):
    return {"version": METHOD_VERSION, **METHOD_SOURCE, "prompts": prompt_templates(),
            "scope": "文献问答、机制分析、案例与措施参考及解释的模型生成环节统一使用全局生效版本。"}


@router.get("/prompt-versions")
def prompt_versions(request: Request, user: Principal = Depends(current_user)):
    return trials(request).list_prompts(user)


@router.post("/prompt-versions", status_code=201)
def save_prompt_version(request: Request, body: TrialPrompt, user: Principal = Depends(current_user)):
    return trials(request).save_prompt(body, user)


class ActivePromptInput(Contract):
    prompt_id: str = Field(min_length=1, max_length=100)


@router.get("/active-prompt")
def active_prompt(request: Request, user: Principal = Depends(current_user)):
    return request.app.state.agent_runtime.runs.prompts.active()


@router.put("/active-prompt")
def activate_prompt(request: Request, body: ActivePromptInput, user: Principal = Depends(current_user)):
    return request.app.state.agent_runtime.runs.prompts.activate(body.prompt_id, user.tester_id)


@router.get("/explanation-trials")
def explanation_trials(request: Request, user: Principal = Depends(current_user)):
    return trials(request).list(user)


@router.post("/explanation-trials", status_code=202)
async def start_explanation_trial(request: Request, body: TrialInput, user: Principal = Depends(current_user)):
    if not getattr(request.app.state, "llm", None):
        raise HTTPException(503, detail={"code": "trial_model_unavailable", "message": "模型服务暂不可用，未创建试验。"})
    return trials(request).submit(body, user, llm=request.app.state.llm)


@router.get("/explanation-trials/{trial_id}")
def explanation_trial(request: Request, trial_id: str, user: Principal = Depends(current_user)):
    return trials(request).get(trial_id, user)


@router.post("/explanation-trials/{trial_id}/judgments")
def judge_explanation_trial(request: Request, trial_id: str, body: TrialJudgment, user: Principal = Depends(current_user)):
    return trials(request).judge(trial_id, body, user)
