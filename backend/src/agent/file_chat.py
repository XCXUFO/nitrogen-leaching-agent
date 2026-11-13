"""Small deterministic router: file facts never depend on LLM arithmetic."""
from __future__ import annotations

import re

from src.agent.query_intent import general_leaching_extrema, has_statistic_request
from src.agent.answer_language import answer_language
from src.api.chat_schema import ChatResponse, FileEvidence
from src.llm.base import ChatUsage
from src.model_tools.provenance import output_source_note


def reply(answer: str, *, evidence: list[FileEvidence] | None = None) -> ChatResponse:
    if answer_language() == "en":
        answer = STATIC_ENGLISH.get(answer, answer)
    return ChatResponse(answer=answer, citations=[], file_evidence=evidence or [],
                        route="file" if evidence else "clarification",
                        outcome="complete" if evidence else "clarification",
                        usage=ChatUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                        retrieved_count=0, model="whcns_balance_reader")


def needs_file(query: str) -> bool:
    if general_leaching_extrema(query):
        return False
    explicit = re.search(r"上传|这[份个张].{0,6}(文件|表|输出)|[\w-]+\.xlsx?\b|nbal_out|wtabal_out|\b(?:this|uploaded)\s+(?:file|table|document)\b", query, re.I)
    statistic = has_statistic_request(query)
    field = re.search(r"硝态氮|铵态氮|降水|灌溉|排水|leak_NO3|leak_NH4|Draining|\b(?:PREC|IRRI|ET0|ETp|ETa|Ep|Ea|Tp|Ta|runoff)\b", query, re.I)
    field = field or requested_fields(query, list(FIELD_ALIASES))
    literature = re.search(r"文献|论文|研究|手册|含义|是什么|\b(?:papers?|literature|research|manuals?)\b", query, re.I)
    return bool(explicit or (statistic and field and not literature))


STATIC_ENGLISH = {
    "请先上传要查询的结果表（.xls 或 .xlsx），再说明字段及最大值或最小值。":
        "Please upload the result table you want to query (.xls or .xlsx), then specify the field and whether you need its maximum or minimum.",
    "请补充你指的是哪个模型、指标或问题，以及希望了解的内容；如果要分析结果表，可上传文件并说明字段和统计项。":
        "Please specify the model, variable or topic and what you would like to know. To analyze a result table, upload it and specify the field and statistic.",
    "问题中的文件名与当前选中的文件不一致，或提到了多份文件。请先选择一份对应文件，再查询它的字段与极值。":
        "The requested filename does not match the selected file, or more than one file was named. Select the corresponding file before asking for its field extrema.",
    "请指定要核对或比较的案例，或粘贴相关材料；当前没有已确认的对象。":
        "Please specify the cases to check or compare, or paste the relevant material. No subject has been confirmed yet.",
    "当前没有可确认的已展示案例，请指定案例或粘贴要解释的材料。":
        "No previously displayed case can be identified. Please specify a case or paste the material to explain.",
}

FIELD_ALIASES = {"leak_NO3": ["硝态氮", "硝酸盐氮", "nitrate leaching", "nitrate nitrogen", "nitrate"],
                 "leak_NH4": ["铵态氮", "ammonium leaching", "ammonium nitrogen", "ammonium"],
                 "Draining": ["排水", "drainage"], "PREC": ["降水", "precipitation"], "IRRI": ["灌溉", "irrigation"]}


def requested_fields(query: str, fields: list[str]) -> list[str]:
    return [f for f in fields if re.search(r"(?<![a-z0-9_])" + re.escape(f) + r"(?![a-z0-9_])", query, re.I)
            or any(re.search(r"(?<![a-z0-9_])" + re.escape(a) + r"(?![a-z0-9_])", query, re.I)
                   if a.isascii() else a in query for a in FIELD_ALIASES.get(f, []))]


def parse_file_request(query: str, fields: list[str], filename: str = "") -> tuple[str, list[str]] | None:
    selected = requested_fields(query, fields)
    operations = [op for op, pattern in {
        "max": r"最大|最高|峰值|(?<![a-z])(?:maximum|max)(?![a-z])",
        "min": r"最小|最低|(?<![a-z])(?:minimum|min)(?![a-z])",
    }.items() if re.search(pattern, query, re.I)]
    # A deliberately small grammar fails closed on time windows, concentration,
    # extra metrics and interpretation. Keyword matching alone could silently
    # answer only the recognized part of a compound question.
    phrases = [filename, *selected,
               *(a for f in selected for a in FIELD_ALIASES.get(f, [])),
               "最大值", "最小值", "最大", "最小", "最高值", "最低值", "最高", "最低", "峰值",
               "maximum", "minimum", "max", "min", "model day", "day", "and",
               "please", "calculate", "compute", "show", "give", "report", "find", "tell me", "what is", "what are", "what about",
               "the", "for", "of", "in", "from", "its", "value", "values", "model days", "unit", "units", "cell", "cells",
               "corresponding", "uploaded", "nitrogen balance table", "water balance table", "file", "table", "entire", "whole", "with", "and the",
               "请问", "请", "帮我", "查询", "查找", "查看", "请查", "计算", "找出", "给出", "告诉我", "我想知道",
               "是多少", "多少", "是什么", "对应", "模型日序", "日序", "单位", "单元格",
               "本次上传", "本次", "氮平衡表", "水平衡表", "汇总", "你刚才给出的", "并说明", "并",
               "硝态氮淋失", "淋失", "整张表", "整表", "全表", "表中", "文件中",
               "这份", "这个", "这张", "该表", "此表", "结果表", "输出表", "上传的", "文件", "记录",
               "的", "及", "和", "与", "以及", "为", "是", "在", "中", "里", "那", "呢", "？", "?", "，", ",", "。", ".", "、", "：", ":", "“", "”", '"', "'", " ", "\n"]
    remainder = query.lower()
    for phrase in sorted(phrases, key=len, reverse=True):
        if phrase.isascii() and re.search(r"[a-z]", phrase, re.I):
            remainder = re.sub(r"(?<![a-z0-9_])" + re.escape(phrase.lower()) + r"(?![a-z0-9_])", "", remainder)
        else:
            remainder = remainder.replace(phrase.lower(), "")
    if len(selected) != 1 or not operations or remainder.strip():
        return None
    return selected[0], operations


def answer_file(query: str, report: dict) -> ChatResponse:
    english = answer_language(query) == "en"
    if report.get("kind") == "document":
        if english:
            return reply("This attachment is a text document, not a WHCNS result table. Ask about its contents or upload a nitrogen or water balance result table.")
        return reply("当前附件是文本文档，不能作为 WHCNS 结果表计算极值。可以询问文档内容，或上传氮/水平衡结果表。")
    fields = [c["header"].split("(")[0] for c in report["columns"]]
    parsed = parse_file_request(query, fields, report["file"])
    if parsed is None:
        if english:
            return reply(f"Read {report['file']} with {report['rows']} records. Please specify a field and its whole-table maximum or minimum, "
                         f"for example, '{fields[0]} maximum'. Available fields: {', '.join(fields)}. "
                         "Time-window filtering, seasonal totals, concentration conversion and comparisons are not supported by this calculation.")
        return reply(
            f"已读取 {report['file']}，共 {report['rows']} 条记录。"
            "当前可计算整张表中一个字段的最大值、最小值及对应模型日序。"
            f"请明确字段和统计项，例如“{fields[0]} 的最大值及对应日序”。\n"
            f"可用字段：{', '.join(fields)}。也可以直接提问文献知识，无需移除附件。"
            "季节总量、日历日期和专业判断还需要确认时间含义与模型版本。"
        )
    selected, operations = parsed
    column = next(c for c in report["columns"] if c["header"].split("(")[0] == selected)
    evidence = []
    lines = []
    for op in operations:
        result = column[op]
        label = "最大值" if op == "max" else "最小值"
        if english:
            lines.append(f"The {'maximum' if op == 'max' else 'minimum'} of {selected} is {result['value']:.15g} {column['unit']}, "
                         f"at model day {result['model_day']}. Value cell: {result['cell']}; model-day cell: {result['day_cell']}. "
                         + (f"There are {result['occurrences']} tied records; the first occurrence is shown." if result['occurrences'] > 1 else ""))
        else:
            lines.append(f"{selected} 的{label}为 {result['value']:.15g} {column['unit']}，"
                     f"对应模型日序 {result['model_day']}。"
                     f"数值单元格 {result['cell']}，日序单元格 {result['day_cell']}。"
                     + (f"共有 {result['occurrences']} 条记录并列，此处列出首次出现。" if result['occurrences'] > 1 else ""))
        evidence.append(FileEvidence(
            filename=report["file"], sha256=report["sha256"], sheet=report["sheet"],
            field=column["header"], unit=column["unit"], operation=op,
            value=result["value"], model_day=result["model_day"], cell=result["cell"],
            day_cell=result["day_cell"], occurrences=result["occurrences"],
            data_range=column["range"], tool_version=report["tool_version"], schema_id=report["schema_id"],
        ))
    source_note = output_source_note(report["sha256"], language="en" if english else "zh")
    if english:
        lines.append(f"Checked {report['rows']} records using the values stored in the uploaded table; formulas were not recalculated. "
                     + (source_note or "Model days are not calendar dates. The program version, input/output pairing and professional review of the manual have not been confirmed. ")
                     + "This does not establish that the case has been reproduced.")
    else:
        lines.append(f"已核查 {report['rows']} 条记录。按上传表中保存的数值计算，未重算公式。"
                 + (source_note if source_note else "模型日序不等于日历日期；程序版本、输入输出配对及手册专业审核尚未确认。")
                 + "此结果不代表案例已复现。")
    return reply("\n".join(lines), evidence=evidence)
