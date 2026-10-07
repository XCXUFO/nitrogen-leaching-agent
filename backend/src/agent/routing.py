"""Conservative intent rules, separate from attachment availability and calculation.

Unrecognized knowledge questions retain the existing RAG path. Composition has
a constrained grammar; this is not a general semantic classifier.
"""
from __future__ import annotations

import re

from src.agent.contracts import Route, RouteDecision
from src.agent.file_chat import needs_file
from src.agent.composition import MECHANISM_INTENT
from src.model_tools.whcns_results import SCHEMAS

STATISTIC = re.compile(r"最大|最小|最高|最低|峰值|(?<![a-z-])(?:min|max|minimum|maximum)(?![a-z])", re.I)
CALCULATION = re.compile(r"(?:总量|平均值|均值|总和|浓度)(?:是多少|多少|呢)?[?？。]*$")
FILE_REFERENCE = re.compile(r"[\w-]+\.xlsx?\b|nbal_out|wtabal_out|waterbal_out|这[份个张].{0,6}(文件|表|输出)|(?:文件|表格|表)中|(?:上述|上传的|当前)(?:文件|表格|表)|根据.{0,8}文件", re.I)
LITERATURE = re.compile(r"文献|论文|研究中|研究表明|手册", re.I)
DEFINITION = re.compile(r"含义|意义|定义|是什么")
AMBIGUOUS = re.compile(r"(?:帮我)?(?:看看|分析一下|分析下|看一下|看下)[?？。]*")
BARE_FIELDS = {field.lower() for schema in SCHEMAS.values() for field in schema["fields"]}
GUIDANCE = re.compile(r"(?:\d+|你好[!！。]?|您好[!！。]?|hi|hello|你是谁[?？]?|(?:你能|可以)做什么[?？]?|(?:介绍|说明)(?:一下)?(?:你的)?(?:功能|能力)[?？]?)", re.I)
OUT_OF_SCOPE = re.compile(r"(?:今天天气(?:怎么样)?|写(?:一首)?(?:诗|情诗)|讲(?:个|一个)?笑话|推荐电影)[?？。！!]*")
FOLLOWUP = re.compile(r"(?:那|那么|再看|再查|它的|这个指标的|该指标的)?\s*(?:最大值?|最小值?|最高值?|最低值?)(?:呢|是多少|及对应日序|对应日序)?[?？。\s]*")
CROP_UPDATE = re.compile(r"(?:只讨论|只考虑|仅讨论|改为|改成|换成|接下来讨论)\s*(玉米|水稻|小麦|番茄)")
CROP_MENTION = re.compile(r"玉米|水稻|小麦|番茄")


def crop_scope(query: str) -> tuple[bool, str | None]:
    """Recognize ordinary crop questions as well as explicit scope changes.

    Multiple crops clear the single-crop constraint so a comparison/rotation
    question cannot silently reuse evidence for only the previous crop.
    """
    explicit = CROP_UPDATE.search(query)
    if explicit:
        return True, explicit.group(1)
    crops = set(CROP_MENTION.findall(query))
    if not crops:
        return False, None
    if len(crops) != 1 or re.search(r"(?:不讨论|不考虑|不是|排除|除外)", query):
        return True, None
    return True, crops.pop()


def decide(query: str, *, has_file: bool) -> RouteDecision:
    if GUIDANCE.fullmatch(query):
        return RouteDecision(route=Route.DIRECT, reason_code="capability_request", skills=["capability_guidance"])
    if OUT_OF_SCOPE.fullmatch(query):
        return RouteDecision(route=Route.OUT_OF_SCOPE, reason_code="outside_supported_domain", skills=["capability_guidance"])
    explicit_file = bool(FILE_REFERENCE.search(query))
    statistic = bool(STATISTIC.search(query))
    composed = statistic and bool(MECHANISM_INTENT.search(query))
    # Explicitly asking about a paper's result remains a literature request.
    paper_result = bool(re.search(r"(?:论文|文献|研究)中", query)) and not explicit_file
    if composed and not paper_result:
        if not has_file:
            return RouteDecision(route=Route.CLARIFY, reason_code="missing_attachment", skills=["clarification"])
        return RouteDecision(route=Route.COMPOSED, reason_code="file_and_mechanism_intent",
                             skills=["file_inspector", "whcns_analyzer", "knowledge_search"])
    # A paper's extrema belong to RAG. An attached table does not override this.
    if LITERATURE.search(query) and not explicit_file:
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="literature_intent", skills=["knowledge_search"])
    if DEFINITION.search(query) and not explicit_file and not re.search(r"最大值是什么|最小值是什么", query):
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="definition_intent", skills=["knowledge_search"])
    file_intent = (explicit_file or needs_file(query) or bool(FOLLOWUP.fullmatch(query))
                   or (has_file and (statistic or CALCULATION.search(query) or query.lower() in BARE_FIELDS)))
    if file_intent:
        if not has_file:
            return RouteDecision(route=Route.CLARIFY, reason_code="missing_attachment", skills=["clarification"])
        return RouteDecision(route=Route.FILE_ANALYSIS, reason_code="file_intent", skills=["file_inspector", "whcns_analyzer"])
    if AMBIGUOUS.fullmatch(query):
        return RouteDecision(route=Route.CLARIFY, reason_code="unclear_intent", skills=["clarification"])
    return RouteDecision(route=Route.KNOWLEDGE, reason_code="knowledge_intent", skills=["knowledge_search"])
