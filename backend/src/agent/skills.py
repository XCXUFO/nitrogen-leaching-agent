"""Small registry of typed adapters around existing, verified capabilities."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field

from src.agent.chat_service import ChatService
from src.agent.contracts import AnswerSection, Contract, SkillName
from src.agent.file_chat import answer_file, reply
from src.agent.composition import MechanismEvidenceError
from src.agent.prompt import DialogueTurn
from src.api.chat_schema import ChatResponse

GUIDANCE = (
    "我可以根据本地文献回答农田氮淋失问题，并给出参考依据；"
    "也可以读取 WHCNS 氮/水平衡输出表，查询一个字段的整表最大值、最小值和对应模型日序。\n\n"
    "你可以问：\n"
    "- 玉米农田氮淋失主要受哪些因素影响？\n"
    "- 上传 Nbal_out.xls 后问：硝态氮淋失最大值及对应日序。\n\n"
    "文件功能分析的是已有输出表，目前不执行 WHCNS 模拟，也不自动制定施肥方案。"
)


class KnowledgeUnavailable(RuntimeError):
    pass


class KnowledgeInput(Contract):
    query: str
    k: int | None = Field(default=None, ge=1, le=20)
    history: list[DialogueTurn] = Field(default_factory=list)
    mode: Literal["answer", "mechanisms"] = "answer"
    crop: str | None = None
    purpose: Literal["general", "peak", "maize_factors"] = "general"


class InspectInput(Contract):
    file_id: str


class InspectOutput(Contract):
    report: dict


class AnalyzeInput(Contract):
    query: str
    report: dict


class ClarificationInput(Contract):
    message: str


class GuidanceInput(Contract):
    outside_domain: bool = False


@dataclass(frozen=True)
class Skill:
    name: SkillName
    description: str
    input_model: type[BaseModel]
    output_model: type[BaseModel]
    handler: Callable[[BaseModel], Awaitable[BaseModel]]


class SkillRegistry:
    def __init__(self):
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        if skill.name in self._skills:
            raise ValueError(f"duplicate skill: {skill.name}")
        self._skills[skill.name] = skill

    async def invoke(self, name: SkillName, payload: dict) -> BaseModel:
        skill = self._skills[name]
        inputs = skill.input_model.model_validate(payload)
        result = await skill.handler(inputs)
        return skill.output_model.model_validate(result)

    def describe(self) -> list[dict]:
        return [{"name": skill.name, "description": skill.description,
                 "input_schema": skill.input_model.model_json_schema(),
                 "output_schema": skill.output_model.model_json_schema()}
                for skill in self._skills.values()]


def build_registry(service: ChatService | None, get_report: Callable[[str], Awaitable[dict]]) -> SkillRegistry:
    async def knowledge(inputs: KnowledgeInput) -> ChatResponse:
        if service is None:
            raise KnowledgeUnavailable("rag_not_configured")
        result = (await service.explain_mechanisms(inputs.query, crop=inputs.crop, k=inputs.k, purpose=inputs.purpose)
                  if inputs.mode == "mechanisms" else
                  await service.answer(inputs.query, k=inputs.k, history=inputs.history))
        if inputs.mode == "mechanisms" and (not result.citations or not result.claims):
            raise MechanismEvidenceError("mechanism_evidence_missing")
        return ChatResponse(answer=result.answer, citations=result.citations, usage=result.usage,
                            retrieved_count=result.retrieved_count, model=result.model,
                            sections=[AnswerSection(kind="literature_inference", content=f"{claim.text} [{claim.citation_index}]",
                                                    citation_indices=[claim.citation_index]) for claim in result.claims])

    async def inspect(inputs: InspectInput) -> InspectOutput:
        return InspectOutput(report=await get_report(inputs.file_id))

    async def analyze(inputs: AnalyzeInput) -> ChatResponse:
        return answer_file(inputs.query, inputs.report)

    async def clarify(inputs: ClarificationInput) -> ChatResponse:
        return reply(inputs.message)

    async def guide(inputs: GuidanceInput) -> ChatResponse:
        result = reply(("这个问题超出了当前助手的能力范围。\n\n" if inputs.outside_domain else "") + GUIDANCE)
        result.route = "out_of_scope" if inputs.outside_domain else "direct"
        result.outcome = "complete"
        result.model = "agent-policy"
        return result

    registry = SkillRegistry()
    for skill in (
        Skill("knowledge_search", "文献检索与有引用的问答", KnowledgeInput, ChatResponse, knowledge),
        Skill("file_inspector", "检查附件是否有效并读取已校验摘要", InspectInput, InspectOutput, inspect),
        Skill("whcns_analyzer", "计算单字段整表极值及模型日序", AnalyzeInput, ChatResponse, analyze),
        Skill("clarification", "请求补充缺少的参数或明确能力边界", ClarificationInput, ChatResponse, clarify),
        Skill("capability_guidance", "能力介绍与提问示例", GuidanceInput, ChatResponse, guide),
    ):
        registry.register(skill)
    return registry
