"""Shared lexical boundaries between qualitative rankings and table statistics."""
from __future__ import annotations

import re


STATISTIC = re.compile(r"最大|最小|最高|最低|峰值|(?<![a-z-])(?:min|max|minimum|maximum)(?![a-z])", re.I)
_QUALITATIVE_EXTREMA = re.compile(
    r"(?:影响|作用|贡献|重要性|敏感性|风险)(?:程度)?\s*(?:是|为|的)?\s*(?:最大|最小|最高|最低)(?!值)"
    r"|(?:最大|最小|最高|最低)(?:的)?(?:影响|作用|贡献|风险)"
)
_LEACHING = re.compile(r'(?:氮素?|硝态氮|硝酸盐氮?|铵态氮)(?:的)?(?:淋失|淋溶|淋洗)|'
                       r'\b(?:nitrate|nitrogen|ammonium)\s+(?:nitrogen\s+)?leaching\b', re.I)
_DATA_SOURCE = re.compile(
    r'文件|附件|上传|表格|表中|结果表|输出表|数据|记录|实测|观测|论文|文献|研究|案例|'
    r'日序|单元格|对应日期|第\s*\d+\s*[天日]|leak_NO3|leak_NH4|[\w-]+\.xlsx?\b|'
    r'\b(?:files?|tables?|outputs?|datasets?|data|records?|uploaded|attachments?|spreadsheets?|workbooks?|measured|observed|papers?|literature|research|stud(?:y|ies)|cases?|model\s+days?|cells?)\b', re.I)
_GENERAL_SCOPE = re.compile(r'一般|通常|普遍|通用|从概念|\b(?:in general|generally|universal|theoretical)\b', re.I)


def general_leaching_extrema(query: str, *, has_file: bool = False) -> bool:
    """An unbound leaching maximum is a knowledge question, not a workbook field."""
    return bool(_LEACHING.search(query) and has_statistic_request(query) and not _DATA_SOURCE.search(query)
                and (not has_file or _GENERAL_SCOPE.search(query)))


def has_statistic_request(query: str) -> bool:
    """Rankings of influence are not requests for a table column's extrema.

    Remove only qualitative phrases, keeping any separate numeric request in a
    mixed question, including explicit 最大值 / 最小值 and model field queries.
    """
    return bool(STATISTIC.search(_QUALITATIVE_EXTREMA.sub("", query)))
