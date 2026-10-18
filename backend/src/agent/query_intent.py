"""Shared lexical boundaries between qualitative rankings and table statistics."""
from __future__ import annotations

import re


STATISTIC = re.compile(r"最大|最小|最高|最低|峰值|(?<![a-z-])(?:min|max|minimum|maximum)(?![a-z])", re.I)
_QUALITATIVE_EXTREMA = re.compile(
    r"(?:影响|作用|贡献|重要性|敏感性|风险)(?:程度)?\s*(?:是|为|的)?\s*(?:最大|最小|最高|最低)(?!值)"
    r"|(?:最大|最小|最高|最低)(?:的)?(?:影响|作用|贡献|风险)"
)


def has_statistic_request(query: str) -> bool:
    """Rankings of influence are not requests for a table column's extrema.

    Remove only qualitative phrases, keeping any separate numeric request in a
    mixed question, including explicit 最大值 / 最小值 and model field queries.
    """
    return bool(STATISTIC.search(_QUALITATIVE_EXTREMA.sub("", query)))
