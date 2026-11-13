"""Conservative intent rules, separate from attachment availability and calculation.

Unrecognized knowledge questions retain the existing RAG path. Composition has
a constrained grammar; this is not a general semantic classifier.
"""
from __future__ import annotations

import re

from src.agent.case_ids import case_ids_in
from src.agent.concept_intent import concept_intent
from src.agent.contracts import Route, RouteDecision
from src.agent.file_chat import needs_file
from src.agent.domain_scope import outside_domain
from src.agent.provided_text import has_provided_text, requested_question
from src.agent.query_intent import general_leaching_extrema, has_statistic_request
from src.agent.composition import MECHANISM_INTENT
from src.model_tools.whcns_results import SCHEMAS

CALCULATION = re.compile(r"(?:总量|平均值|均值|总和|浓度)(?:是多少|多少|呢)?[?？。]*$")
FILE_REFERENCE = re.compile(r"[\w-]+\.xlsx?\b|nbal_out|wtabal_out|waterbal_out|这[份个张].{0,6}(文件|表|输出)|(?:文件|表格|表)中|(?:上述|上传的|当前)(?:文件|表格|表)|根据.{0,8}文件|\b(?:this|uploaded)\s+(?:file|table|document)\b", re.I)
LITERATURE = re.compile(r"文献|论文|研究中|研究表明|手册|\b(?:papers?|literature|research|manuals?)\b", re.I)
DEFINITION = re.compile(r"含义|意义|定义|是什么")
AMBIGUOUS = re.compile(r"(?:帮我)?(?:看看|分析一下|分析下|看一下|看下)[?？。]*")
BARE_FIELDS = {field.lower() for schema in SCHEMAS.values() for field in schema["fields"]}
GREETING = re.compile(r"(?:你好|您好|早上好|早安|上午好|中午好|下午好|晚上好|晚安|嗨|哈喽|hi|hello|good\s+(?:morning|afternoon|evening))[!！。?？]*", re.I)
INTRODUCTION = re.compile(rf"(?:\d+|{GREETING.pattern})", re.I)
GUIDANCE = re.compile(rf"(?:{INTRODUCTION.pattern}|你是谁[?？]?|(?:你能|可以)做什么[?？]?|(?:当前|现在)(?:的)?(?:农业)?(?:模型)?助手(?:有(?:哪些|什么)功能|能做什么|具备哪些能力)[?？]?|(?:介绍|说明)(?:一下)?(?:你的)?(?:功能|能力)[?？]?)", re.I)
OUT_OF_SCOPE = re.compile(r"(?:今天天气(?:怎么样)?|写(?:一首)?(?:诗|情诗)|讲(?:个|一个)?笑话|推荐电影)[?？。！!]*")
FOLLOWUP = re.compile(r"(?:(?:那|那么|再看|再查|它的|这个指标的|该指标的)?\s*(?:最大值?|最小值?|最高值?|最低值?)(?:呢|是多少|及对应日序|对应日序)?|(?:(?:and|then|what about)\s+)?(?:the\s+)?(?:maximum|minimum|max|min)(?:\s+value)?)[?？。\s]*", re.I)
CROP_UPDATE = re.compile(r"(?:只讨论|只考虑|仅讨论|改为|改成|换成|接下来讨论)\s*(玉米|水稻|小麦|番茄)")
CROP_MENTION = re.compile(r"玉米|水稻|小麦|番茄")


def introductory_query(query: str) -> bool:
    """Greetings, bare numbers and symbol-only input need concrete guidance."""
    query = query.strip()
    return bool(INTRODUCTION.fullmatch(query)) or not any(char.isalnum() for char in query)


def guidance_query(query: str) -> bool:
    return (introductory_query(query) or bool(GUIDANCE.fullmatch(query.strip()))
            or bool(re.fullmatch(r"(?:what can you do|who are you|how can you help(?: me)?)[?!.\s]*", query, re.I)))


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


def decide(query: str, *, has_file: bool, understanding=None) -> RouteDecision:
    if understanding and understanding.get('status') == 'collected':
        query = understanding.get('resolved_query') or query
    if guidance_query(query):
        return RouteDecision(route=Route.DIRECT, reason_code="capability_request", skills=["capability_guidance"])
    if OUT_OF_SCOPE.fullmatch(query) or outside_domain(query, understanding):
        return RouteDecision(route=Route.OUT_OF_SCOPE, reason_code="outside_supported_domain", skills=["capability_guidance"])
    provided_text = has_provided_text(query)
    if provided_text:
        query = requested_question(query)
    if not provided_text and general_leaching_extrema(query, has_file=has_file):
        return RouteDecision(route=Route.KNOWLEDGE, reason_code='general_leaching_extrema', skills=['concept_explanation'])
    if understanding and re.search('比较|对比|区别', query) and re.search('文献|论文', query) and not re.search('案例', query):
        return RouteDecision(route=Route.KNOWLEDGE, reason_code='literature_comparison', skills=['knowledge_search'])
    explanation = bool(re.search(r"解释|通俗|看不懂|什么意思|含义|对比|比较|区别|为什么", query))
    case_id = bool(case_ids_in(query))
    reference = bool(re.search(r"类似案例|参考.{0,6}(?:案例|措施)|(?:案例|措施).{0,6}参考|有没有.{0,8}(?:案例|措施)|别人.{0,15}怎么做|找.{0,6}案例", query))
    case_referent = bool(re.search(r"(?:这个|那个|该|上述|上面|上文|刚才|这些|这两|第[一二三四五]个).{0,3}案例", query))
    reference = reference or (not case_referent and "案例" in query and not case_id and (not explanation or bool(re.search(r"介绍|推荐|列举|找|有哪些", query))))
    # Source restrictions such as "只用本地材料" do not turn a concept into pasted-case work.
    if (not reference and not case_id and not case_referent and not FILE_REFERENCE.search(query)
            and not re.search(r"案例|措施|报告|这段|以下|如下|文字|文本|[:：\n]", query) and concept_intent(query)):
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="introductory_concept", skills=["concept_explanation"])
    if reference and explanation:
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="case_reference_and_explanation", skills=["case_assistant"])
    if reference:
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="case_reference_intent", skills=["case_assistant"])
    if provided_text:
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="provided_text_question", skills=["case_assistant"])
    if case_id or case_referent or (explanation and re.search(r"案例|措施|报告|材料|表格|这段|以下|如下|文字|文本|[:：\n]", query)):
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="case_explanation_intent", skills=["case_assistant"])
    explicit_file = bool(FILE_REFERENCE.search(query))
    statistic = has_statistic_request(query)
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
    if not explicit_file and not statistic and concept_intent(query):
        return RouteDecision(route=Route.KNOWLEDGE, reason_code="introductory_concept", skills=["concept_explanation"])
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
