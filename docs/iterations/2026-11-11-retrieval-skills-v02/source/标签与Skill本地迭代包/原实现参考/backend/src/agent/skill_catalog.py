"""Read-only descriptions of the real registry; probes never invoke an LLM."""
from __future__ import annotations

from datetime import datetime, timezone
from importlib.util import find_spec
from typing import Literal

from fastapi import HTTPException
from pydantic import Field

from src.agent.contracts import Contract, HARNESS_VERSION
from src.agent.skills import build_registry

Availability = Literal["available", "unavailable", "unknown"]


class Dependency(Contract):
    name: str
    status: Availability
    message: str
    required: bool = True


class SkillSummary(Contract):
    name: str
    title: str
    description: str
    registered: bool = True
    generation: Literal["llm", "local", "program", "unknown"]
    availability: Availability
    availability_note: str
    configuration: Literal["read_only", "limited"] = "read_only"


class SkillDetail(SkillSummary):
    registry_description: str
    scenarios: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    dependencies: list[Dependency] = Field(default_factory=list)
    input_schema: dict
    output_schema: dict
    harness_version: str = HARNESS_VERSION
    runtime_config_version: str | None = None
    code_sha256: str | None = None
    skill_version: str | None = None
    checked_at: str


DESCRIPTIONS = {
    "knowledge_search": {
        "title": "文献检索问答", "generation": "llm",
        "description": "从本地文献和当前会话材料中查找依据，回答专业问题或解释可能机理。",
        "scenarios": ["查阅农田氮淋失知识", "结合当前会话文档回答", "计算后补充有文献依据的可能机理"],
        "examples": ["玉米农田氮淋失主要受哪些因素影响？"],
        "inputs": ["问题、可用的对话历史和会话材料", "可选检索数量与机理解释模式"],
        "outputs": ["带引用的回答、实际检索片段和用量记录"],
        "limitations": ["检索本地资料，不提供联网搜索。", "当前入口须已初始化文献服务；仅有附件不代表该入口可用。", "引用校验不等于专业因果判断已经审核。"],
    },
    "case_reference": {
        "title": "案例与措施参考", "generation": "llm",
        "description": "从已开放案例中选择相关做法，说明场景差异并提供来源。",
        "scenarios": ["寻找相似场景的案例", "为后续解释提供已匹配案例"],
        "examples": ["有没有玉米水肥一体化的案例可以参考？"],
        "inputs": ["问题和相关背景", "可选的指定案例范围"],
        "outputs": ["参考回答、实际采用案例及来源", "无匹配时说明资料缺口"],
        "limitations": ["只读取已开放且未删除的案例，候选及回答前均复核可用性。", "候选搜索覆盖全部开放记录；单次调用仅采用预算内的完整材料（最多 30 条／24000 字符）。关键材料无法完整采用时说明预算不足。", "材料缺失不推定措施效果，也不自动给出田块施肥方案。"],
    },
    "case_explanation": {
        "title": "案例与措施解释", "generation": "llm",
        "description": "解释指定案例、表格或粘贴文本，也可对指定对象作比较。",
        "scenarios": ["读懂专业表格和术语", "比较指定案例", "解释用户粘贴的材料并继续追问"],
        "examples": ["请通俗解释这段材料：追肥分三次施用，表中数值为三次合计。"],
        "inputs": ["用户问题和粘贴文本，或指定案例", "必要的比较对象与上下文"],
        "outputs": ["保留原文条件的解释与比较", "采用案例时返回可追溯来源"],
        "limitations": ["粘贴文本无需先保存到案例库；使用库内案例时仍需检查开放状态。", "不补造空缺数据，不混淆数字、单位和单次／合计口径。", "表达改善不等于农业专业认证；不保证材料足以形成完整执行方案。"],
    },
    "file_inspector": {
        "title": "附件检查", "generation": "local",
        "description": "检查附件是否仍有效，并在分析阶段校验 WHCNS 结果表。",
        "scenarios": ["文件计算前检查附件", "确认结果表结构和业务校验信息"],
        "examples": ["上传 Nbal_out.xls 后，查询硝态氮淋失最大值。"],
        "inputs": ["当前用户及会话可访问的有效附件标识"],
        "outputs": ["已解析并通过业务校验的摘要，或明确的附件错误"],
        "limitations": ["检查实际附件时仍会核对有效期、权限与内容格式。", "上传成功不等于已经通过业务校验；扫描件不提供 OCR。", "XLS 和 XLSX 的首次解析分别需要对应本地依赖。"],
    },
    "whcns_analyzer": {
        "title": "WHCNS 结果分析", "generation": "local",
        "description": "对受支持的 WHCNS 输出表计算单字段整表极值，并保留原件证据。",
        "scenarios": ["查询整表最大值或最小值", "查看对应模型日序与单元格位置"],
        "examples": ["硝态氮淋失最大值及对应日序。", "排水量最小值及对应日序。"],
        "inputs": ["已校验的结果表摘要", "一个明确字段和整表最大值／最小值要求"],
        "outputs": ["数值、单位、模型日序、值及日序单元格", "数据范围、文件指纹和工具版本"],
        "limitations": ["支持既定 Nbal_out 氮平衡和 WtaBal_out 水平衡结构，不是通用 Excel 分析器。", "不执行 WHCNS 仿真，不自动校准或制定施肥方案。", "不将逐列算术和解释为季节总量，不自动把模型日序映射为日期。", "新的附件须先通过附件检查；本项的就绪状态只表示已校验摘要的本地计算入口。"],
    },
    "clarification": {
        "title": "澄清追问", "generation": "program",
        "description": "用程序文案请求补充影响执行的必要信息。",
        "scenarios": ["缺少附件或明确字段", "对象或支持范围需要说明"],
        "examples": ["上传结果表后只问“最大值”，系统会要求明确指标。"],
        "inputs": ["运行时确定的缺失信息或需要澄清的内容"],
        "outputs": ["必要追问和待补充状态"],
        "limitations": ["程序生成，不依赖 LLM，也不代表业务任务已经完成。", "不能通过此入口扩张计算或资料访问范围。"],
    },
    "capability_guidance": {
        "title": "能力引导", "generation": "program",
        "description": "介绍支持的任务、提问示例和当前能力边界。",
        "scenarios": ["了解助手可以做什么", "范围外请求的支持说明"],
        "examples": ["你能做什么？"],
        "inputs": ["能力咨询或范围外请求标记"],
        "outputs": ["支持范围、限制与提问示例"],
        "limitations": ["程序生成，不调用 LLM。", "说明支持范围不代表该环境的所有外部依赖都已可用。"],
    },
}


def _llm_dependency(llm) -> Dependency:
    return Dependency(name="语言模型服务", status="unknown" if llm is not None else "unavailable",
                      message="客户端已初始化，未执行在线连通性检查。" if llm is not None else "模型客户端未初始化。")


def _case_dependency(store) -> Dependency:
    if store is None:
        return Dependency(name="开放案例材料", status="unavailable", message="案例库未初始化。")
    try:
        cases = store.candidates()
    except HTTPException as exc:
        if isinstance(exc.detail, dict) and exc.detail.get("code") == "case_capacity":
            return Dependency(name="开放案例材料", status="unknown",
                              message="自动范围超过 30 条或 24000 字符容量；指定较小案例范围仍需单独校验。")
    except Exception:
        pass
    else:
        return Dependency(name="开放案例材料", status="available" if cases else "unavailable",
                          message="当前存在开放候选，实际搜索后按材料预算选取，使用前仍会复核。" if cases else "当前没有可用的开放案例。")
    return Dependency(name="开放案例材料", status="unknown", message="本次无法确认案例材料状态，请稍后刷新。")


def _workbook_dependency(module: str, format_name: str) -> Dependency:
    try:
        installed = find_spec(module) is not None
    except (ImportError, ValueError):
        return Dependency(name=f"{format_name} 解析", status="unknown", required=False, message="本次未能确认解析依赖。")
    return Dependency(name=f"{format_name} 解析", status="available" if installed else "unavailable", required=False,
                      message="已安装本地解析依赖，实际附件仍需校验。" if installed else "对应解析依赖未安装，首次解析此格式不可用。")


async def _unused_report(file_id: str) -> dict:
    raise RuntimeError("Catalog inspection never executes attachment processing")


def describe_skills(*, service=None, llm=None, case_store=None, runtime=None) -> list[SkillDetail]:
    registry = build_registry(service, _unused_report, llm=llm, case_store=case_store)
    checked_at = datetime.now(timezone.utc).isoformat()
    manifest = getattr(runtime, "config_manifest", {}) or {}
    version = getattr(runtime, "config_version", None)
    version = version if version and version != "unconfigured" else None
    case_dependency = _case_dependency(case_store)
    parser_dependencies = [_workbook_dependency("xlrd", "XLS"), _workbook_dependency("openpyxl", "XLSX")]
    result = []
    for registered in registry.describe():
        name = registered["name"]
        metadata = DESCRIPTIONS.get(name, {"title": registered["description"], "description": "能力说明待补充。", "generation": "unknown"})
        if name == "knowledge_search":
            dependencies = [Dependency(name="本地文献服务", status="available" if service is not None else "unavailable",
                                       message="已初始化；本次未重新执行索引检索。" if service is not None else "文献服务未启用或初始化失败。"),
                            _llm_dependency(getattr(service, "_llm", None))]
        elif name == "case_reference":
            dependencies = [_llm_dependency(llm), case_dependency]
        elif name == "case_explanation":
            dependencies = [_llm_dependency(llm), case_dependency.model_copy(update={"required": False})]
        elif name == "file_inspector":
            dependencies = [Dependency(name="附件检查入口", status="available", message="本地检查入口已加载；附件有效性在实际请求时判断。"), *parser_dependencies]
        elif name in {"whcns_analyzer", "clarification", "capability_guidance"}:
            dependencies = [Dependency(name="本地执行入口", status="available", message="程序入口已加载，不需要远程模型服务。")]
        else:
            dependencies = [Dependency(name="依赖检查", status="unknown", message="此能力的依赖状态尚未采集。")]
        required = [dependency.status for dependency in dependencies if dependency.required]
        availability = "unavailable" if "unavailable" in required else "unknown" if "unknown" in required else "available"
        note = {"available": "本地执行所需依赖可用，具体输入仍需校验。", "unavailable": "存在尚不可用的必要依赖，详见下方说明。", "unknown": "必要依赖尚未全部验证，不保证本次任务可执行。"}[availability]
        if name == "file_inspector":
            formats = [item.name.removesuffix(" 解析") for item in parser_dependencies if item.status == "available"]
            availability = "available" if formats else "unknown"
            note = (f"检查入口可用；新表格首次解析可用格式：{'、'.join(formats)}，实际内容仍需校验。" if formats else
                    "检查入口已加载，但未确认可用的表格解析依赖；已缓存摘要须按实际附件判断。")
        result.append(SkillDetail(**metadata, name=name, registry_description=registered["description"], dependencies=dependencies, availability=availability,
                                  configuration="limited" if name == "case_explanation" else "read_only",
                                  availability_note=note, input_schema=registered["input_schema"], output_schema=registered["output_schema"],
                                  runtime_config_version=version, code_sha256=manifest.get("agent_code_sha256"), checked_at=checked_at))
    return result
