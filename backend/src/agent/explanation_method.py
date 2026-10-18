"""Shared communication instructions for every model-generated answer."""
import hashlib
import re
from contextvars import ContextVar

active_communication = ContextVar("answer_communication", default=None)

METHOD_VERSION = "agri-clear-communication-v1"
METHOD_SOURCE = {
    "title": "CDC Clear Communication Index User Guide", "edition": "August 2019",
    "url": "https://www.cdc.gov/ccindex/pdf/clear-communication-user-guide.pdf",
    "sha256": "d4d92ffe4339e15680d7d0e988580c5aa881b260bce36f11f29476c40ab12b95",
    "license_reference": "https://www.cdc.gov/other/agencymaterials.html",
    "adaptation": "独立编写的中文农业对话模板，仅借鉴主旨优先、术语说明、数字与不确定性表达方法。",
    "notice": "方法参考来源为 CDC，原指南可在来源网站免费取得。本地适配、产品与农业效果未经 CDC 或美国政府认可或背书；不复制官方评分或专业认证。",
    "status": "default_enabled",
}
METHOD_PROMPT = (
    "本次采用科普表达试验方法：先用一句话回应用户最关心的问题；解释完成该理解所必需的术语，"
    "不要只用另一个术语替换。过程按必要的因果或时间顺序说明，但不能把相关关系说成确定因果。"
    "表格必须按原对象保留表头、单位、分组和单次或合计口径；空白不填零。"
    "只有确有帮助时使用简短例子，明确例子并非材料中的实测值；类比说明不适用之处。"
    "把材料陈述、一般概念补充和待核实推断区分开。材料缺少效果、条件、配比时指出具体缺口，"
    "不将材料推荐量指定为用户田块用量。原文与解释冲突时分别陈述，不替人工决定真值。"
    "用户要求专业深度时保留专业术语和相关细节。简单名词无需生成长模板。"
)


def communication_snapshot():
    return {"version": METHOD_VERSION, "text": METHOD_PROMPT,
            "sha256": hashlib.sha256(METHOD_PROMPT.encode()).hexdigest()}


def communication_instructions():
    snapshot = active_communication.get()
    return snapshot["text"] if snapshot is not None else METHOD_PROMPT


def inspect_explanation(material, answer):
    def numbers(text):
        value = re.sub(r"(?m)^\s*\d+[.、)]\s*|\[\d+\]", "", text)
        return set(re.findall(r"(?<![A-Za-z])\d+(?:\.\d+)?", value))
    extra = sorted(numbers(answer) - numbers(material))
    return {"version": "numeric-surface-check-v1", "method": "program", "status": "needs_check" if extra else "no_extra_numeric_token_detected",
            "additional_numbers": extra, "limitations": "仅核对表面数值是否出现，无法证明数字对象、单位、口径或专业结论正确；需要人工核对。"}
