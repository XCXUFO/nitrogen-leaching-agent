"""Conservative shared interpretation. Uncertain referents remain unresolved."""
from __future__ import annotations

import hashlib
import re

from src.agent.case_ids import case_ids_in
from src.agent.query_intent import has_statistic_request

VERSION = "understanding-rules-v2"
ALIASES = {"玉米": ("玉米", "maize", "corn"), "小麦": ("小麦", "wheat"), "水稻": ("水稻", "rice"),
           "番茄": ("番茄", "西红柿", "tomato"), "硝态氮": ("硝态氮", "硝酸盐氮", "硝酸盐"),
           "水肥一体化": ("水肥一体化", "随水施肥"), "折氮量": ("折氮量", "纯氮量", "折纯氮"),
           "灌溉": ("灌溉", "irrigation"), "滴灌": ("滴灌", "drip irrigation")}
CROPS = {"玉米", "小麦", "水稻", "番茄"}
SWITCH = re.compile(r"换个?话题|另一个问题|另外[，,：:]|不说.{0,6}了")
FOLLOW = re.compile(r"刚才|上述|其中|这些|这两|两者|(?<!其)它|这个|那个|前者|后者|第[一二三四五]|^那|再解释|再详细|说错|改成|改为|不是.+是")
FACTOR_FOLLOWUP = re.compile(r"^(?:哪(?:些|个|种|项|一个))(?:因素|因子)?(?:的)?(?:影响|作用|贡献)?(?:最大|最小|最高|最低|最重要|最关键|更重要|更大|更小)(?!值)")
CASE_PAIR = re.compile(r"[这那]两(?:个|份|项|篇|者)?|两者")
REFERENCE_WORDS = re.compile(r"刚才|上述|其中|展示|列出|提供|提到|介绍|请|帮我|比较|比对|对比|一下|案例|试验|记录|做法")


def is_followup(text):
    elliptical = (re.fullmatch(r"[^，,。；;？?]{1,24}呢[？?。\s]*", text)
                  and not re.search(r"是什么|什么意思|为什么|如何|怎么|哪些|多少", text))
    return not SWITCH.search(text) and bool(FOLLOW.search(text) or FACTOR_FOLLOWUP.search(text) or elliptical
        or re.fullmatch(r"那?(?:最大|最小)值?呢?[？?。\s]*", text))


def canonical(text):
    value = text.lower()
    for name, aliases in ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            value = value.replace(alias, name)
    return value


def terms(text):
    value = canonical(text)
    return set(re.findall(r"[\u4e00-\u9fff]{2}|[a-z_]{2,}|\d+(?:\.\d+)?", value)) | set(
        re.findall(r"(?=([\u4e00-\u9fff]{2}))", value))


def intent(text):
    if re.search(r"你能|你是谁|你的功能", text): return "capability"
    if has_statistic_request(text) or "日序" in text: return "file_calculation"
    if re.search(r"比较|对比|区别", text): return "comparison"
    if re.search(r"案例|别人.+怎么做", text): return "case_search"
    if re.search(r"解释|什么意思|含义|定义|是什么", text): return "explanation"
    return "knowledge"


def resolve_case_pair(raw, state):
    """Resolve qualified pairs only within the previously displayed case scope.

    Titles are referent metadata, not factual evidence. The case skill still
    re-reads the selected IDs and checks their current availability and content.
    """
    pair = CASE_PAIR.search(raw)
    if not pair or not state.current_case_ids:
        return []
    anchors = {item["source_id"]: item for item in state.material_anchors
               if item.get("source_type") == "case" and item.get("source_id") in state.current_case_ids}
    # Read descriptors attached to the referent, not the requested comparison
    # field: "山西的这两个案例的追肥" is scoped by 山西, not 追肥.
    prefix = re.split(r"[，,。；;？?]", raw[:pair.start()])[-1]
    suffix = re.match(r"([^的，,。；;？?]*?)(?:案例|试验|记录|做法)", raw[pair.end():])
    scope = REFERENCE_WORDS.sub(" ", prefix + " 的 " + (suffix.group(1) if suffix else ""))
    groups = [re.findall(r"[\u4e00-\u9fff]{2,}|[a-z][a-z0-9_-]+", part)
              for part in re.split(r"以及|和|与|、", canonical(scope).replace("的", " "))]
    groups = [group for group in groups if group]
    if not groups:
        return list(state.current_case_ids) if len(state.current_case_ids) == 2 else []
    matched = set()
    for group in groups:
        candidates = {case_id for case_id, anchor in anchors.items()
                      if all(value in canonical(anchor.get("title", "")) for value in group)}
        if not candidates:
            return []
        matched.update(candidates)
    return [case_id for case_id in state.current_case_ids if case_id in matched] if len(matched) == 2 else []


def understand(body, state, trace, taxonomy=None):
    raw = body.query
    switched = bool(SWITCH.search(raw))
    followup = is_followup(raw)
    previous = state.understanding_context if followup else {}
    query = canonical(raw)
    conditions = [dict(item, source="historical_user", operation="inherited") for item in previous.get("conditions", [])]
    concepts = []
    names = set(ALIASES) | {tag["name"] for tag in (taxonomy or {}).get("tags", []) if tag.get("enabled")}
    dimension_names = {item["id"]: item.get("name", "") for item in (taxonomy or {}).get("dimensions", [])}
    region_names = {tag["name"] for tag in (taxonomy or {}).get("tags", []) if re.search(r"地区|地域|区域|省市", dimension_names.get(tag.get("dimension_id"), ""))}
    for name in sorted(names):
        normalized = canonical(name)
        if normalized not in query: continue
        original = next((word for word in ALIASES.get(name, (name,)) if word.lower() in raw.lower()), name)
        # A negative constraint is retained as a negative constraint.
        negative = bool(re.search(r"(?:(?<!有)没有|不种|不要|排除|不考虑|不讨论|不是)\s*" + re.escape(normalized), query))
        category = "crop" if normalized in CROPS else "region" if name in region_names else "concept"
        concepts.append({"original": original, "canonical": normalized, "category": category, "source": "current_user"})
        if category in {"crop", "region"} or re.search(r"必须|仅限|只查|只找|只考虑|没有|排除", query):
            # Current crop corrections replace only previous crop conditions.
            if category == "crop": conditions = [item for item in conditions if item.get("category") != "crop" or item.get("source") == "current_user"]
            condition_id = f"{trace.run_id}:condition:{len(conditions)+1}"
            conditions.append({"condition_id": condition_id, "value": normalized, "category": category,
                               "required": True, "negated": negative, "source": "current_user", "operation": "corrected" if followup else "new",
                               "source_turn_id": trace.turn_id, "source_run_id": trace.run_id,
                               "object_group": normalized if category in {"crop", "region"} and re.search(r"比较|对比|区别", query) else "subject"})
    for matched in re.finditer(r"(?<!有)没有[^，,。；;？?]{1,12}条件|\d+(?:\.\d+)?\s*(?:kg/ha|kg·hm-2|千克/亩|公斤/亩|毫米|mm|天)|(?:三|两|二|四|五|\d+)次合计", query, re.I):
        value = matched.group()
        if any(item["value"] == value for item in conditions): continue
        conditions.append({"condition_id": f"{trace.run_id}:condition:{len(conditions)+1}", "value": value,
            "category": "explicit_scope", "required": True, "negated": False, "source": "current_user", "operation": "new",
            "source_turn_id": trace.turn_id, "source_run_id": trace.run_id, "object_group": "subject"})
    # Historical condition IDs are source references; assign distinct current IDs.
    for index, condition in enumerate(conditions):
        if condition["source"] == "historical_user":
            condition["source_condition_id"] = condition["condition_id"]
            condition["condition_id"] = f"{trace.run_id}:condition:{index+1}"
    anchors = [dict(anchor) for anchor in state.material_anchors] if followup else []
    unresolved = []
    explicit_case_ids = body.case_ids or case_ids_in(raw)
    pair_reference = bool(CASE_PAIR.search(raw)) and followup and not explicit_case_ids
    resolved_case_ids = resolve_case_pair(raw, state) if pair_reference else []
    if pair_reference and state.current_case_ids and not resolved_case_ids:
        unresolved.append({"field": "comparison_objects", "requires_clarification": True, "message": "刚才展示了多个案例，请说明要比较哪两个案例（可使用标题）。"})
    if followup and re.search(r"它们|这个案例|那个案例|这两个案例", raw) and not anchors and not state.current_case_ids and not explicit_case_ids:
        unresolved.append({"field": "material_referent", "requires_clarification": True, "message": "请说明指的是哪份材料或案例，当前没有可确认的已展示对象。"})
    resolved = raw
    metric_followup = bool(re.fullmatch(r"那?(?:最大|最小)值?呢?[？?。\s]*", raw))
    if metric_followup and state.current_metric:
        resolved = f"{state.current_metric} {'最小值' if '最小' in raw else '最大值'}及对应日序"
    elif followup and conditions and not any(concept["category"] == "crop" for concept in concepts):
        inherited = [item["value"] for item in conditions if item["category"] == "crop"]
        if inherited: resolved = "、".join(inherited) + "；" + raw
    if resolved_case_ids:
        titles = {item["source_id"]: item["title"] for item in anchors if item.get("source_type") == "case" and item.get("title")}
        if all(case_id in titles for case_id in resolved_case_ids):
            resolved += "\n本轮已确认的对比案例（按此前展示顺序）：" + "、".join(titles[case_id] for case_id in resolved_case_ids)
    clauses = [part.strip(" ，,。；;?") for part in re.split(r"[；;]|[，,]\s*(?:再|然后|并且|同时)|同时|并且", resolved) if part.strip(" ，,。；;?")]
    subtasks = []
    for index, clause in enumerate(clauses or [resolved]):
        task_intent = intent(clause)
        subtasks.append({"subtask_id": f"{trace.run_id}:task:{index+1}", "query": clause, "intent": task_intent,
                         "original_span": raw.find(clause), "depends_on": [subtasks[-1]["subtask_id"]] if task_intent == "comparison" and subtasks else [],
                         "condition_ids": [item["condition_id"] for item in conditions]})
    return {"version": VERSION, "status": "collected", "run_id": trace.run_id, "turn_id": trace.turn_id,
            "raw_query": raw, "resolved_query": resolved, "queries": [task["query"] for task in subtasks],
            "intents": list(dict.fromkeys(task["intent"] for task in subtasks)), "concepts": concepts, "keywords": [item["canonical"] for item in concepts],
            "conditions": conditions, "subtasks": subtasks, "anchors": anchors, "resolved_case_ids": resolved_case_ids, "unresolved": unresolved,
            "context_relation": "topic_switch" if switched else "followup" if followup else "independent",
            "basis": "明确词语、已展示对象及相关会话状态；未确定项不自动补全。"}


def map_tags(understanding, taxonomy=None):
    if taxonomy is None:
        return {"version": "tag-mapping-v1", "status": "unavailable", "mappings": [], "unmatched": understanding["concepts"]}
    dims = {item["id"]: item for item in taxonomy.get("dimensions", [])}
    tags = {tag["id"]: tag for tag in taxonomy.get("tags", [])}
    enabled = []
    for tag in tags.values():
        node, seen, active = tag, set(), True
        while node and node["id"] not in seen:
            seen.add(node["id"])
            active = active and bool(node.get("enabled"))
            node = tags.get(node.get("parent_id"))
        if active and dims.get(tag["dimension_id"], {}).get("enabled"): enabled.append(tag)
    mappings, unmatched = [], []
    for concept in understanding["concepts"]:
        candidates = [tag for tag in enabled if canonical(tag["name"]) == concept["canonical"]]
        if not candidates: unmatched.append(concept); continue
        hard = [item for item in understanding["conditions"] if item["value"] == concept["canonical"]]
        usage = "explicit_tag_filter" if re.search(r"(?:只查|仅查|只找).{0,12}(?:标签|打标)|带.{0,12}标签", understanding["raw_query"]) else "semantic_condition" if hard else "ranking_signal"
        mappings.append({"term": concept["original"], "canonical": concept["canonical"], "source": concept["source"],
                         "status": "matched" if len(candidates) == 1 else "ambiguous", "method": "controlled_alias" if concept["original"] != concept["canonical"] else "exact_name",
                         "candidates": [{"id": tag["id"], "path": tag.get("path", tag["name"]), "dimension_id": tag["dimension_id"]} for tag in candidates],
                         "condition_ids": [item["condition_id"] for item in hard], "usage": usage})
    fingerprint = hashlib.sha256(str(sorted((tag["id"], tag["name"], tag.get("updated_at")) for tag in enabled)).encode()).hexdigest()
    return {"version": "tag-mapping-v1", "taxonomy_fingerprint": fingerprint, "status": "collected", "mappings": mappings, "unmatched": unmatched}


def assess_conditions(text, tag_ids, understanding, mapping):
    """Content is checked after access eligibility; missing tags never prefilter."""
    normalized = canonical(text)
    checks = []
    conditions = understanding.get("conditions", [])
    for condition in conditions:
        term = condition["value"]
        present = term in normalized
        negated = bool(re.search(r"(?:没有|不种|排除|不适用于|不是)\s*" + re.escape(term), normalized))
        state = "satisfied" if present and negated == condition["negated"] else "not_satisfied" if present else "unknown"
        if not present and condition["category"] == "crop" and any(crop in normalized for crop in CROPS - {term}): state = "not_satisfied"
        if not present and condition["category"] == "crop" and condition["negated"] and any(crop in normalized for crop in CROPS - {term}): state = "satisfied"
        offset = normalized.find(term)
        related = [item for item in mapping.get("mappings", []) if condition["condition_id"] in item["condition_ids"]]
        tagged = any(candidate["id"] in tag_ids for item in related for candidate in item["candidates"])
        explicit = [item for item in related if item["usage"] == "explicit_tag_filter" and item["status"] == "matched"]
        if explicit and not tagged: state = "not_satisfied"
        checks.append({"condition_id": condition["condition_id"], "object_group": condition["object_group"], "state": state,
                       "basis": normalized[max(0, offset-60):offset+len(term)+100] if offset >= 0 else "正文未提供可核对的条件依据",
                       "tag_match": tagged, "conflict": tagged and state == "not_satisfied", "conflict_resolution": "正文核对" if tagged and state == "not_satisfied" else None,
                       "source": condition["source"], "filter_stage": "content_verification"})
    groups = {}
    for check in checks: groups.setdefault(check["object_group"], []).append(check)
    common = groups.pop("subject", [])
    eligible = all(item["state"] == "satisfied" for item in common) and (not groups or any(all(item["state"] == "satisfied" for item in group) for group in groups.values()))
    return checks, eligible
