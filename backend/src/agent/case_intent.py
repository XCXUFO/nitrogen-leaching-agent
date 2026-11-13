"""Canonical case task modes and historical entry-point adapters."""
import re
from typing import Literal

CaseMode = Literal['search', 'explain', 'compare', 'evidence']
CASE_ALIASES = {'case_reference': 'search', 'case_explanation': 'explain'}
CASE_SKILLS = {'case_assistant', *CASE_ALIASES}


def case_mode(query: str, default: CaseMode = 'search') -> CaseMode:
    # A request to omit evaluation must not activate the evidence workflow.
    query = re.sub(r'(?:不要|无需|不)(?:再|进行)?(?:评价|评估|讨论)(?:施肥|方案|试验)?效果', '', query)
    if re.search(r'效果.{0,12}证据|效果(?:怎么样|如何|呢|是什么|有哪些)?[？?。]*$|证据|不能得出|不能判断|证明.{0,8}(?:有效|效果)|是否有效', query):
        return 'evidence'
    if re.search(r'比较|对比|比对|区别|差异|两者', query):
        return 'compare'
    if re.search(r'解释|为什么|为何|关键措施|含义|什么意思|措施是什么|如何理解', query):
        return 'explain'
    return default


def normalize_case_call(name, payload):
    if name in CASE_ALIASES:
        payload = {**payload, 'mode': case_mode(payload.get('query', ''), CASE_ALIASES[name])}
        if name == 'case_reference':
            payload['lookup_cases'] = True
        return 'case_assistant', payload
    return name, payload
