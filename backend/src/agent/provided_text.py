"""Recognize explicitly pasted source text without interpreting its subject."""
from __future__ import annotations

import re

SOURCE = re.compile(r"(?:资料|材料|原文|正文|段落|文本|表格|内容|观测记录(?:回答)?|试验条件|试验方案记录|passage|context)\s*[:：]", re.I)
QUESTION = re.compile(r"(?:^|\n)\s*(?:问题|提问|question)\s*[:：]", re.I)


def has_provided_text(query: str) -> bool:
    source = SOURCE.search(query)
    if source is None:
        # An explicit request to restate an actual agricultural record also
        # supplies source material when it has no colon or question label.
        return bool(re.search(r"(?:农田|水氮|作物).{0,12}(?:试验|记录)", query)
                    and re.search(r"(?:仅|只)复述(?:这些|本轮|两个地块)?(?:测试条件|条件|记录)", query)
                    and re.search(r"\d", query))
    question = QUESTION.search(query, source.end())
    body = query[source.end():question.start() if question else len(query)].strip()
    return bool(body) and not re.fullmatch(r"https?://\S+", body, re.I)


def requested_question(query: str) -> str:
    """Quoted source content must not trigger topic rules for another question."""
    if has_provided_text(query):
        questions = list(QUESTION.finditer(query))
        if questions:
            return query[questions[-1].end():].strip() or query
    return query
