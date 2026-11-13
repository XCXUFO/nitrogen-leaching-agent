"""Shared communication instructions for every model-generated answer."""
import hashlib
import re
from contextvars import ContextVar
from src.agent.answer_language import language_instructions

active_communication = ContextVar("answer_communication", default=None)

USER_FACING_RULES = (
    '\n\n【面向用户的表达规则】\n'
    '以下规则优先于其他关于来源状态标签的表达要求。直接回答问题，不向用户解释内部资料组织或处理流程。'
    '不提案例库、知识库、开放状态、取材预算、路由或待补充清单；'
    '不添加“以上为一般知识／一般农化知识”“非案例库记录”“不是案例库检索结果”'
    '“本次未提供相关案例”“未引用本地或外部资料”等来源状态声明，也不换个措辞重复这些说明。'
    '通用原理自然解释，用“通常”“可能”“例如”等表达适用范围、推断与示例；'
    '引用仅标在有实际来源支持的陈述旁，不为常识编造来源。'
    '仅在影响当前结论或使用时说明具体缺口，例如缺少产量或对照数据，不能判断措施效果。'
    '需要继续讨论且有助于理解或明确下一步时，可在回答末尾自然问一个贴近当前问题、容易回答的小问题，'
    '例如询问想了解的应用场景或尚未讲清的环节。先把当前问题讲清，再引导；'
    '每轮至多一个引导问题，不机械地每轮反问，不重复已知信息，不泛泛询问“还有什么问题”，'
    '用户只需定义、单一事实、明确要求简答或结束时无需反问；基础解释不以收集田块参数为前提。'
)

METHOD_VERSION = "agri-clear-communication-v2"
METHOD_SOURCE = {
    "title": "CDC Clear Communication Index User Guide", "edition": "August 2019",
    "url": "https://www.cdc.gov/ccindex/pdf/clear-communication-user-guide.pdf",
    "sha256": "d4d92ffe4339e15680d7d0e988580c5aa881b260bce36f11f29476c40ab12b95",
    "license_reference": "https://www.cdc.gov/other/agencymaterials.html",
    "adaptation": "独立编写的中文农业对话模板，仅借鉴主旨优先、术语说明、数字与不确定性表达方法。",
    "notice": "方法参考来源为 CDC，原指南可在来源网站免费取得。本地适配、产品与农业效果未经 CDC 或美国政府认可或背书；不复制官方评分或专业认证。",
    "status": "default_enabled",
}
ANSWER_DEPTH_PROMPT = (
    '\n\n【回答深度与解释质量】\n'
    '默认采用中等偏详细的讲解。概念问题应让初学者读完能理解，而不只是记住一句定义或一组术语。'
    '先直接说明是什么，再根据问题和证据解释关键过程或原因、实际意义，并在有帮助时给一个贴近问题的例子。'
    '面对“是什么啊”等入门提问，优先讲清原料、变化、结果及其联系；生化缩写和细胞结构只在帮助理解时引入。'
    '首次使用专业术语时就用通俗语言解释它在该过程中的作用；不要连续堆叠未解释的缩写。'
    '有足够内容的入门解释通常用4至6个自然段或适量要点展开，约500至800个汉字可作篇幅参考；'
    '复杂机制、比较或综合问题可以更充分。篇幅以讲清问题为准，证据有限时如实收束，不补造内容凑字数。'
    '讲过程时说明各环节如何衔接；讲影响因素时说明怎样影响、为什么影响，不能只列名称。'
    '例子用来解释原理，未提供实测数据时使用定性情景，并说明是一般性示例。'
    '有明显日常或农业联系的概念，尽量用一个具体场景串起过程与实际意义，让例子真正帮助理解。'
    '可以简要澄清一个最容易误解的点，但不强行为每题套固定章节或扩展无关话题。'
    '使用连贯段落，每段围绕一个意思；要点适合并列或步骤，避免整篇挤成一段或碎成短句清单。'
    '通用原理自然融入解释，引用紧邻所支持的陈述，不为常识编造来源。'
    '限制说明只写影响当前理解或使用的具体缺口，不反复打断解释。'
    '本轮用户明确要求简短、一句话或指定字数时优先遵守；确认、寒暄和单一事实查询无需扩写。'
)

METHOD_PROMPT = (
    "本次采用科普表达试验方法：先用一句话回应用户最关心的问题；解释完成该理解所必需的术语，"
    "不要只用另一个术语替换。过程按必要的因果或时间顺序说明，但不能把相关关系说成确定因果。"
    "表格必须按原对象保留表头、单位、分组和单次或合计口径；空白不填零。"
    "只有确有帮助时使用简短例子，明确例子并非材料中的实测值；类比说明不适用之处。"
    "把材料陈述、一般概念补充和待核实推断区分开。材料缺少效果、条件、配比时指出具体缺口，"
    "不将材料推荐量指定为用户田块用量。原文与解释冲突时分别陈述，不替人工决定真值。"
    "用户要求专业深度时保留专业术语和相关细节。根据问题选择必要内容，不强套固定模板。"
) + ANSWER_DEPTH_PROMPT


def communication_snapshot():
    return {"version": METHOD_VERSION, "text": METHOD_PROMPT,
            "sha256": hashlib.sha256(METHOD_PROMPT.encode()).hexdigest()}


def communication_instructions(query: str = ""):
    snapshot = active_communication.get()
    return (snapshot["text"] if snapshot is not None else METHOD_PROMPT) + USER_FACING_RULES + language_instructions(query)


def inspect_explanation(material, answer):
    def numbers(text):
        value = re.sub(r"(?m)^\s*\d+[.、)]\s*|\[\d+\]", "", text)
        return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", value))
    extra = sorted(numbers(answer) - numbers(material))
    return {"version": "numeric-surface-check-v1", "method": "program", "status": "needs_check" if extra else "no_extra_numeric_token_detected",
            "additional_numbers": extra, "limitations": "仅核对表面数值是否出现，无法证明数字对象、单位、口径或专业结论正确；需要人工核对。"}
