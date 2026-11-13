"""Small registry of typed adapters around existing, verified capabilities."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field
from fastapi import HTTPException

from src.agent.web_evidence import supplement, WEB_REQUEST, observe
from src.agent.answer_language import answer_language
from src.agent.domain_scope import DOMAIN_GUIDANCE_ANSWER_EN, OUTSIDE_DOMAIN_ANSWER_EN, ASSISTANT_IDENTITY_EN
from src.agent.case_intent import CASE_ALIASES, normalize_case_call
from src.agent.case_skills import CaseSkillInput, answer_cases
from src.agent.chat_service import ChatService, RAGQueryError
from src.agent.contracts import AnswerSection, Contract, SkillName
from src.agent.file_chat import answer_file, reply
from src.agent.composition import MechanismEvidenceError
from src.agent.prompt import DialogueTurn, format_history
from src.agent.task_prompts import task_instructions
from src.agent.concept_intent import CONCEPT_SYSTEM, local_only
from src.agent.domain_scope import ASSISTANT_IDENTITY, DOMAIN_GUIDANCE_ANSWER, DOMAIN_INSTRUCTIONS, OUTSIDE_DOMAIN_ANSWER
from src.agent.explanation_method import communication_instructions
from src.llm.base import ChatMessage
from src.api.chat_schema import ChatResponse

GUIDANCE = (
    "我可以根据本地文献回答农田氮淋失问题，并给出参考依据；"
    "也可以参考已开放的案例与措施，或通俗解释你粘贴的专业文字。"
    "还可以读取 WHCNS 氮/水平衡输出表，查询一个字段的整表最大值、最小值和对应模型日序。\n\n"
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
    allow_general_knowledge: bool = False
    crop: str | None = None
    purpose: Literal["general", "peak", "maize_factors"] = "general"
    session_documents: list[dict] = Field(default_factory=list)
    session_document_only: bool = False


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
    introductory: bool = False
    greeting: str = ""


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
        name, payload = normalize_case_call(name, payload)
        skill = self._skills[name]
        inputs = skill.input_model.model_validate(payload)
        result = await skill.handler(inputs)
        return skill.output_model.model_validate(result)

    def describe(self, *, include_aliases=False) -> list[dict]:
        return [{"name": skill.name, "description": skill.description,
                 "input_schema": skill.input_model.model_json_schema(),
                 "output_schema": skill.output_model.model_json_schema()}
                for skill in self._skills.values() if include_aliases or skill.name not in CASE_ALIASES]

    def label(self, name: SkillName) -> str:
        return self._skills[name].description


def build_registry(service: ChatService | None, get_report: Callable[[str], Awaitable[dict]], *, case_store=None, llm=None, expression_config=None, web=None,
                   understanding=None, tag_mapping=None, retrieval_observer=None, tool_runner=None) -> SkillRegistry:
    def source_unavailable(inputs):
        return reply("The local material service is unavailable, so I cannot answer using only the specified materials. Please provide the relevant text to continue."
                     if answer_language(inputs.query) == "en" else
                     "本地资料服务当前不可用，无法仅依据指定材料解释该问题。可提供相关正文后继续。")

    def local_fallback(inputs, response, task_scope):
        from src.retrieval.tag_scope import may_expand_scope
        scope=response.literature_scope or {}
        if not isinstance(service,ChatService) or not (understanding or {}).get('allow_local_scope_expansion') or not may_expand_scope(scope):
            return None
        async def expand():
            result=await service.answer(inputs.query,k=inputs.k,history=inputs.history,
                session_documents=inputs.session_documents,task_scope=task_scope,understanding=understanding,
                tag_mapping=tag_mapping,retrieval_observer=retrieval_observer,tool_runner=tool_runner,
                allow_general_knowledge=inputs.allow_general_knowledge,
                _expanded_scope={**scope,'expanded':True,'expansion_reason':'necessary_explanation_gap',
                    'initial_retrieval_ms':scope.get('retrieval_ms'),'initial_eligible_chunks':scope.get('eligible_chunks')})
            return ChatResponse(answer=result.answer,citations=result.citations,usage=result.usage,
                outcome=result.outcome,retrieved_count=result.retrieved_count,model=result.model,literature_scope=result.literature_scope)
        return expand
    async def knowledge(inputs: KnowledgeInput) -> ChatResponse:
        if service is None:
            if local_only(inputs.query, inputs.history):
                return source_unavailable(inputs)
            if WEB_REQUEST.search(inputs.query) or (web is not None and web.ready):
                response = await supplement(inputs.query, inputs.history, local=None, web=web, llm=llm,
                    scope="knowledge_search", tool_runner=tool_runner, mechanism_contract=inputs.mode == "mechanisms", understanding=understanding)
                if response is not None:
                    return response
            raise KnowledgeUnavailable("rag_not_configured")
        try:
            if inputs.mode == "mechanisms":
                result = await service.explain_mechanisms(inputs.query, crop=inputs.crop, k=inputs.k, purpose=inputs.purpose,
                    **({"tool_runner": tool_runner, "understanding": understanding, "tag_mapping": tag_mapping, "retrieval_observer": retrieval_observer} if isinstance(service, ChatService) else {}))
            else:
                result = await service.answer(inputs.query, k=inputs.k, history=inputs.history,
                    **({"understanding": understanding, "tag_mapping": tag_mapping, "retrieval_observer": retrieval_observer, "tool_runner": tool_runner,
                        "session_document_only": inputs.session_document_only,
                        "allow_general_knowledge": inputs.allow_general_knowledge} if isinstance(service, ChatService) else {}),
                    **({'allow_scope_expansion':bool((understanding or {}).get('allow_local_scope_expansion'))} if isinstance(service, ChatService) else {}),
                    **({"session_documents": inputs.session_documents} if inputs.session_documents else {}))
        except RAGQueryError:
            if local_only(inputs.query, inputs.history):
                return source_unavailable(inputs)
            if inputs.mode == "answer" and (WEB_REQUEST.search(inputs.query) or (web is not None and web.ready)):
                observe({"status": "local_retrieval_failed", "queries": []})
                recovered = await supplement(inputs.query, inputs.history, local=None, web=web, llm=llm or getattr(service, "_llm", None),
                    scope="knowledge_search", tool_runner=tool_runner, understanding=understanding)
                if recovered is not None:
                    return recovered
            raise
        if inputs.mode == "mechanisms" and (not result.citations or not result.claims):
            raise MechanismEvidenceError("mechanism_evidence_missing")
        response = ChatResponse(answer=result.answer, citations=result.citations, usage=result.usage,
                            literature_scope=getattr(result,'literature_scope',None),
                            outcome=getattr(result,'outcome','complete'),
                            retrieved_count=result.retrieved_count, model=result.model,
                            sections=[AnswerSection(kind="literature_inference", content=f"{claim.text} [{claim.citation_index}]",
                                                    citation_indices=[claim.citation_index]) for claim in result.claims])
        return await supplement(inputs.query, inputs.history, local=response, web=web, llm=llm or getattr(service, "_llm", None),
            scope="knowledge_search", tool_runner=tool_runner, mechanism_contract=inputs.mode == "mechanisms", understanding=understanding,
            general_knowledge=inputs.allow_general_knowledge,
            local_fallback=local_fallback(inputs,response,'knowledge_search') if inputs.mode=='answer' else None)

    async def concept(inputs: KnowledgeInput) -> ChatResponse:
        local = None
        generator = llm or getattr(service, "_llm", None)
        if service is not None:
            try:
                result = await service.answer(inputs.query, k=inputs.k, history=inputs.history,
                    **({"task_scope": "concept_explanation", "understanding": understanding, "tag_mapping": tag_mapping,
                        "tool_runner": tool_runner, "retrieval_observer": retrieval_observer,
                        'allow_scope_expansion':bool((understanding or {}).get('allow_local_scope_expansion'))} if isinstance(service, ChatService) else {}),
                    **({"session_documents": inputs.session_documents} if inputs.session_documents else {}))
                local = ChatResponse(answer=result.answer, citations=result.citations, usage=result.usage,
                                     literature_scope=getattr(result,'literature_scope',None),
                                     retrieved_count=result.retrieved_count, model=result.model,outcome=getattr(result,'outcome','complete'))
            except RAGQueryError:
                observe({"status": "local_retrieval_failed", "queries": []})
        if local is None and local_only(inputs.query, inputs.history):
            return source_unavailable(inputs)
        if local is not None:
            result = await supplement(inputs.query, inputs.history, local=local, web=web, llm=generator,
                scope="concept_explanation", tool_runner=tool_runner, understanding=understanding,
                local_fallback=local_fallback(inputs,local,'concept_explanation'))
            if result is not None:
                return result
        if generator is None:
            raise HTTPException(503, detail={"code": "concept_model_unavailable", "message": "概念解释模型服务当前不可用，请稍后重试。"})
        messages = [ChatMessage(role="system", content=DOMAIN_INSTRUCTIONS + CONCEPT_SYSTEM + task_instructions("concept_explanation") + "\n" + communication_instructions()
            + "\n直接解释可靠的通用原理，不编造研究结论、数值或引用，不添加来源状态声明。"),
            ChatMessage(role="user", content="【最近对话，仅用于理解】\n" + format_history(inputs.history) + "\n【当前问题】\n" + inputs.query)]
        generated = await generator.chat(messages, temperature=0.3)
        if not generated.content.strip():
            raise HTTPException(502, detail={"code": "concept_answer_empty", "message": "模型未返回概念解释，请重试。"})
        local = ChatResponse(answer=generated.content.strip(),
                            citations=[], usage=generated.usage, retrieved_count=0, model=generated.model)
        return await supplement(inputs.query, inputs.history, local=local, web=web, llm=generator,
            scope="concept_explanation", tool_runner=tool_runner, understanding=understanding)

    async def inspect(inputs: InspectInput) -> InspectOutput:
        report = await tool_runner("读取并校验附件", lambda: get_report(inputs.file_id)) if tool_runner else await get_report(inputs.file_id)
        return InspectOutput(report=report)

    async def analyze(inputs: AnalyzeInput) -> ChatResponse:
        return await tool_runner("计算已校验字段的整表极值", lambda: answer_file(inputs.query, inputs.report)) if tool_runner else answer_file(inputs.query, inputs.report)

    async def clarify(inputs: ClarificationInput) -> ChatResponse:
        return reply(inputs.message)

    async def guide(inputs: GuidanceInput) -> ChatResponse:
        english = answer_language() == "en"
        if inputs.outside_domain:
            result = reply(OUTSIDE_DOMAIN_ANSWER_EN if english else OUTSIDE_DOMAIN_ANSWER)
            result.route, result.outcome, result.model = "out_of_scope", "complete", "agent-policy"
            return result
        if inputs.introductory:
            opening = (f"{inputs.greeting}! " if english else f"{inputs.greeting}！") if inputs.greeting else ""
            result = reply(opening + (DOMAIN_GUIDANCE_ANSWER_EN if english else DOMAIN_GUIDANCE_ANSWER))
            result.route, result.outcome, result.model = "direct", "complete", "agent-policy"
            return result
        from importlib.util import find_spec
        if english:
            features = []
            if service is not None or llm is not None:
                features.append("Explain agricultural concepts, water and nitrogen management, and related models.")
            if service is not None:
                features.append("Answer research questions using available literature and uploaded materials.")
            if llm is not None:
                features.append("Explain agricultural text and tables you provide.")
                if case_store is not None:
                    features.append("Find and interpret relevant management cases and check their reported effects.")
            if find_spec("xlrd") or find_spec("openpyxl"):
                features.append("Read existing WHCNS balance tables and calculate whole-table extrema and corresponding model days.")
            result = reply(ASSISTANT_IDENTITY_EN + ".\n\n" + "\n".join("- " + item for item in features)
                + "\n\nI do not run WHCNS simulations or automatically prescribe fertilizer rates."
                + (" Web evidence search is available when needed." if web is not None and web.ready else " Web evidence search is not configured."))
            result.route, result.outcome, result.model = "direct", "complete", "agent-policy"
            return result
        features, examples = [], []
        if service is not None or llm is not None:
            features.append("解释农业、水氮及相关基础概念，介绍农业模型与本助手的用途")
            examples.append("WHCNS 模型是什么，有什么用途？")
        if service is not None:
            features.append("查询本地文献与会话材料，回答专业问题并列出依据")
            examples.append("农田氮素淋失主要受哪些因素影响？")
        if llm is not None:
            features.append("解释你粘贴的专业文字或表格")
            if case_store is not None:
                features.append("检索已开放案例，解释措施并核对已有的效果证据")
        if find_spec("xlrd") or find_spec("openpyxl"):
            features.append("读取已有 WHCNS 氮/水平衡输出表，查询一个字段的整表最大值、最小值和对应模型日序")
            examples.append("上传受支持的输出表后问：硝态氮淋失最大值及对应日序。")
        content = ASSISTANT_IDENTITY + "。\n\n当前可以帮助你：\n" + "\n".join("- " + f for f in features)
        if examples:
            content += "\n\n提问示例：\n" + "\n".join("- " + x for x in examples[:3])
        content += "\n\n当前不执行 WHCNS 模拟、不自动制定施肥处方，也不预测个人考试或就业结果。"
        content += "相关领域联网取证已配置，按需检索并核对正文。" if web is not None and web.ready else "联网取证尚未配置。"
        result = reply(content)
        result.route = "direct"
        result.outcome = "complete"
        result.model = "agent-policy"
        return result

    async def cases(inputs: CaseSkillInput) -> ChatResponse:
        result = await answer_cases(inputs, mode=inputs.mode, store=case_store, llm=llm, expression_config=expression_config,
                                  understanding=understanding, tag_mapping=tag_mapping, retrieval_observer=retrieval_observer, tool_runner=tool_runner)
        result.case_mode = inputs.mode
        result.case_route = ["case_assistant"]
        return result

    registry = SkillRegistry()
    for skill in (
        Skill("case_assistant", "案例与措施助手", CaseSkillInput, ChatResponse, cases),
        Skill("case_reference", "案例参考（兼容入口）", CaseSkillInput, ChatResponse, cases),
        Skill("case_explanation", "案例解释（兼容入口）", CaseSkillInput, ChatResponse, cases),
        Skill("concept_explanation", "概念解释与入门用途说明", KnowledgeInput, ChatResponse, concept),
        Skill("knowledge_search", "文献检索与有引用的问答", KnowledgeInput, ChatResponse, knowledge),
        Skill("file_inspector", "检查附件是否有效并读取已校验摘要", InspectInput, InspectOutput, inspect),
        Skill("whcns_analyzer", "计算单字段整表极值及模型日序", AnalyzeInput, ChatResponse, analyze),
        Skill("clarification", "请求补充缺少的参数或明确能力边界", ClarificationInput, ChatResponse, clarify),
        Skill("capability_guidance", "能力介绍与提问示例", GuidanceInput, ChatResponse, guide),
    ):
        registry.register(skill)
    return registry
