"""Conservative shared interpretation. Uncertain referents remain unresolved."""
from __future__ import annotations

import hashlib
import re
import unicodedata
from src.agent.tag_matching import tag_index, normalize, compiled
import json

from src.agent.case_ids import case_ids_in
from src.agent.query_intent import general_leaching_extrema, has_statistic_request
from src.agent.provided_text import has_provided_text

VERSION = "understanding-rules-v3"
ALIASES = {"玉米": ("玉米", "maize", "corn"), "小麦": ("小麦", "wheat"), "水稻": ("水稻", "rice"),
           "番茄": ("番茄", "西红柿", "tomato"), "硝态氮": ("硝态氮", "硝酸盐氮", "硝酸盐"),
           "水肥一体化": ("水肥一体化", "随水施肥"), "折氮量": ("折氮量", "纯氮量", "折纯氮"),
           "灌溉": ("灌溉", "irrigation"), "滴灌": ("滴灌", "drip irrigation"),
           "氧化亚氮": ("氧化亚氮", "n2o", "nitrous oxide"), "whcns": ("whcns",)}
CANONICAL_WORDS = {alias: name for name, aliases in ALIASES.items() for alias in aliases}
CANONICAL_PATTERN = re.compile('|'.join(re.escape(word) for word in sorted(CANONICAL_WORDS,key=lambda word:(-len(word),word))))
CROPS = {"玉米", "小麦", "水稻", "番茄"}
SWITCH = re.compile(r"换个?话题|另一个问题|另外[，,：:]|不说.{0,6}了")
FOLLOW = re.compile(r"刚才|上述|上面|上文|前文|你(?:说|提到|展示)的|前面|案例中|其中|这些|这两|两者|(?<!其)它|这个|那个|前者|后者|第[一二三四五]|^那|再解释|再详细|说错|改成|改为|不是.+是")
FACTOR_FOLLOWUP = re.compile(r"^(?:哪(?:些|个|种|项|一个))(?:因素|因子)?(?:的)?(?:影响|作用|贡献)?(?:最大|最小|最高|最低|最重要|最关键|更重要|更大|更小)(?!值)")
CASE_PAIR = re.compile(r"[这那]两(?:个|份|项|篇|者)?|两者")
REFERENCE_WORDS = re.compile(r"刚才|上述|上面|上文|前文|你(?:说|提到|展示)的|前面|案例中|其中|展示|列出|提供|提到|介绍|请|帮我|比较|比对|对比|一下|案例|试验|记录|做法")


def is_followup(text):
    elliptical = (re.fullmatch(r"[^，,。；;？?]{1,24}呢[？?。\s]*", text)
                  and not re.search(r"是什么|什么意思|为什么|如何|怎么|哪些|多少", text))
    return not SWITCH.search(text) and bool(FOLLOW.search(text) or FACTOR_FOLLOWUP.search(text) or elliptical
        or re.fullmatch(r"那?(?:最大|最小)值?呢?[？?。\s]*", text))


def canonical(text):
    value = unicodedata.normalize('NFKC', text).casefold()
    return CANONICAL_PATTERN.sub(lambda match: CANONICAL_WORDS[match.group()], value)


def terms(text):
    value = canonical(text)
    return set(re.findall(r"[\u4e00-\u9fff]{2}|[a-z_]{2,}|\d+(?:\.\d+)?", value)) | set(
        re.findall(r"(?=([\u4e00-\u9fff]{2}))", value))


def explicit_tag_spans(text):
    return re.findall(r'(?:只查|仅查|只找|带|按)[^，。；;]{0,64}?(?:标签|打标)', normalize(text))


def intent(text, *, has_file=False):
    if re.search(r"你能|你是谁|你的功能", text): return "capability"
    if general_leaching_extrema(text, has_file=has_file): return 'explanation'
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
    matcher, alias_error = tag_index(taxonomy or {}, ALIASES)
    dimension_names = {item["id"]: item.get("name", "") for item in (taxonomy or {}).get("dimensions", [])}
    region_names = {tag["name"] for tag in (taxonomy or {}).get("tags", []) if re.search(r"地区|地域|区域|省市", dimension_names.get(tag.get("dimension_id"), ""))}
    extracted = matcher.extract(raw)
    explicit_spans = explicit_tag_spans(raw)
    comparison = bool(re.search(r'比较|对比|区别|相比', raw))
    category_counts = {}
    classified = []
    for original in extracted:
        candidates = matcher.candidates(original, canonical(original))
        tag = matcher.tags.get(candidates[0]['id'], {}) if candidates else {}
        name = original if candidates and candidates[0]['method'] == 'configured_alias' else tag.get('name', original)
        normalized = canonical(name)
        dimension = dimension_names.get(tag.get('dimension_id'), '')
        category = 'crop' if normalized in CROPS or re.search('作物', dimension) else 'region' if name in region_names else 'concept'
        classified.append((original, normalized, category))
        category_counts[category] = category_counts.get(category, 0) + 1
    compared_category = 'region' if category_counts.get('region', 0) > 1 else 'crop'
    for original, normalized, category in classified:
        # A negative constraint is retained as a negative constraint.
        negative = bool(re.search(r"(?:(?<!有)没有|不种|不要|排除|不考虑|不讨论|不是|不带|不含|不包含)\s*" + re.escape(normalized), query))
        replaced = bool(re.search(r'(?:从|不是)\s*' + re.escape(normalized) + r'.{0,8}(?:更正为|改为|改成|换成|而是|是)', query))
        concepts.append({"original": original, "canonical": normalized, "category": category, "source": "current_user",
                         "polarity": "exclude" if negative or replaced else "include", "replaced": replaced})
        if replaced: continue
        if category in {"crop", "region"} or re.search(r"必须|仅限|只查|只找|只考虑|没有|排除", query) or any(original in span for span in explicit_spans):
            # Current crop corrections replace only previous crop conditions.
            if category in {'crop', 'region'}: conditions = [item for item in conditions if item.get("category") != category or item.get("source") == "current_user"]
            condition_id = f"{trace.run_id}:condition:{len(conditions)+1}"
            conditions.append({"condition_id": condition_id, "value": normalized, "category": category,
                               "required": True, "negated": negative, "source": "current_user", "operation": "corrected" if followup else "new",
                               "source_turn_id": trace.turn_id, "source_run_id": trace.run_id,
                               "object_group": normalized if category == compared_category and not negative and (comparison or category_counts.get(category,0)>1) else "subject"})
    for matched in re.finditer(r"(?<!有)没有[^，,。；;？?]{1,12}条件|\d+(?:\.\d+)?\s*(?:kg/ha|kg·hm-2|千克/亩|公斤/亩|毫米|mm|天)|(?:三|两|二|四|五|\d+)次合计", query, re.I):
        value = matched.group()
        if any(item["value"] == value for item in conditions): continue
        conditions.append({"condition_id": f"{trace.run_id}:condition:{len(conditions)+1}", "value": value,
            "category": "explicit_scope", "required": True, "negated": False, "source": "current_user", "operation": "new",
            "source_turn_id": trace.turn_id, "source_run_id": trace.run_id, "object_group": "subject"})
    if category_counts.get('region',0)>1 and category_counts.get('crop',0)>1:
        parts = re.split(r'与|和|、|[；;]', canonical(raw))
        for condition in conditions:
            if condition['category'] not in {'crop','region'} or condition['negated']: continue
            matches = [i for i,part in enumerate(parts) if condition['value'] in part]
            if len(matches)==1: condition['object_group']=f'object_{matches[0]+1}'
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
    ordinal_words = re.findall(r"第([一二三四五六七八九十]|\d+)个", raw) if followup and not explicit_case_ids else []
    if not ordinal_words and followup and len(state.current_case_ids) == 2:
        ordinal_words = ["一"] if "前者" in raw else ["二"] if "后者" in raw else []
    if ordinal_words:
        numbers = {word: index + 1 for index, word in enumerate("一二三四五六七八九十")}
        positions = [int(word) if word.isdigit() else numbers[word] for word in ordinal_words]
        if all(1 <= pos <= len(state.current_case_ids) for pos in positions):
            resolved_case_ids = list(dict.fromkeys(state.current_case_ids[pos - 1] for pos in positions))
        else:
            unresolved.append({"field": "material_referent", "requires_clarification": True, "message": "指定序号不在当前已展示的案例范围内，请核对对象。"})
    if pair_reference and state.current_case_ids and not resolved_case_ids:
        unresolved.append({"field": "comparison_objects", "requires_clarification": True, "message": "刚才展示了多个案例，请说明要比较哪两个案例（可使用标题）。"})
    if followup and re.search(r"它们|这个案例|那个案例|这两个案例", raw) and not anchors and not state.current_case_ids and not state.user_selected_case_ids and not explicit_case_ids and state.case_material_source != "user_text":
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
            resolved += "\n本轮已确认的案例（按此前展示顺序）：" + "、".join(titles[case_id] for case_id in resolved_case_ids)
    provided_text = has_provided_text(raw)
    # Source instructions, the passage and its questions form one grounded task.
    # Punctuation and conjunctions inside that source are not task boundaries.
    clauses = [resolved] if provided_text else [part.strip(" ，,。；;?") for part in re.split(r"[；;]|[，,]\s*(?:再|然后|并且|同时)|[，,](?=\s*(?:比较|对比))|同时|并且", resolved) if part.strip(" ，,。；;?")]
    subtasks = []
    for index, clause in enumerate(clauses or [resolved]):
        task_intent = intent(clause, has_file=bool(state.session_file_ids if state.session_files_enabled else body.file_id))
        subtasks.append({"subtask_id": f"{trace.run_id}:task:{index+1}", "query": clause, "intent": task_intent,
                         "original_span": raw.find(clause), "depends_on": [subtasks[-1]["subtask_id"]] if task_intent == "comparison" and subtasks else [],
                         "condition_ids": [item["condition_id"] for item in conditions if len(clauses)<=1 or item['value'] in canonical(clause) or item.get('negated') or item.get('source')=='historical_user' or task_intent=='comparison'],
                         "retrieval_query": clause, "input_kind": 'user_text' if provided_text or re.search(r'[:：\n]',raw) and re.search('材料|这段|以下|如下|文本|表格',raw) else 'case' if re.search('案例|措施', clause) or task_intent=='comparison' and subtasks and subtasks[-1].get('input_kind')=='case' or state.current_case_ids and followup else 'literature'})
    return {"version": VERSION, "status": "collected", "run_id": trace.run_id, "turn_id": trace.turn_id,
            "raw_query": raw, "resolved_query": resolved, "queries": [task["query"] for task in subtasks],
            "intents": list(dict.fromkeys(task["intent"] for task in subtasks)), "concepts": concepts, "keywords": [item["canonical"] for item in concepts],
            "conditions": conditions, "subtasks": subtasks, "anchors": anchors, "resolved_case_ids": resolved_case_ids, "unresolved": unresolved,
            "context_relation": "topic_switch" if switched else "followup" if followup else "independent",
            "alias_status": alias_error or 'ready', "alias_version": matcher.alias_version,
            'mapping_configuration': matcher.configuration if taxonomy is not None else None,
            'entity_categories': {'regions':sorted(region_names),'crops':sorted(CROPS)},
            "basis": "明确词语、已展示对象及相关会话状态；未确定项不自动补全。"}


def remaining_context(understanding, tasks):
    """A scoped view of one snapshot; covered conditions cannot leak into other work."""
    condition_ids={identifier for task in tasks for identifier in task.get('condition_ids',[])}
    conditions=[item for item in understanding.get('conditions',[]) if item['condition_id'] in condition_ids]
    query='；'.join(task['query'] for task in tasks)
    concepts=[item for item in understanding.get('concepts',[]) if item['canonical'] in canonical(query) or any(c['value']==item['canonical'] for c in conditions)]
    return {**understanding,'resolved_query':query,'queries':[task['query'] for task in tasks],
            'subtasks':tasks,'intents':list(dict.fromkeys(task['intent'] for task in tasks)),
            'conditions':conditions,'concepts':concepts,'keywords':[item['canonical'] for item in concepts],
            'unresolved':[dict(item) for item in understanding.get('unresolved',[])]}


def map_tags(understanding, taxonomy=None):
    if taxonomy is None:
        return {"version": "tag-mapping-v1", "status": "unavailable", "mappings": [], "unmatched": understanding["concepts"]}
    frozen = understanding.get('mapping_configuration')
    if frozen:
        index = compiled(*(json.dumps(frozen[k],ensure_ascii=False,sort_keys=True) for k in ('taxonomy','aliases','base_aliases')))
        degraded = None if understanding.get('alias_status') == 'ready' else understanding.get('alias_status')
    else:
        index, degraded = tag_index(taxonomy, ALIASES)
    mappings, unmatched = [], []
    explicit_spans = explicit_tag_spans(understanding['raw_query'])
    unresolved_filters = []
    for span in explicit_spans:
        remaining = span
        for word in index.extract(span): remaining = remaining.replace(word, '')
        remaining = re.sub(r'只查|仅查|只找|打了|打上|打标|标签|带有|带|按|或者|以及|并且|包含|不要|排除|不含|不|或|和|与|的|了|有|、|[“”"\s/]', '', remaining)
        if remaining: unresolved_filters.append(remaining)
    for concept in understanding["concepts"]:
        candidates = index.candidates(concept['original'], concept['canonical'])
        if not candidates:
            unmatched.append(concept)
            continue
        hard = [item for item in understanding["conditions"] if item["value"] == concept["canonical"]]
        explicit = any(normalize(concept['original']) in span or normalize(concept['canonical']) in span for span in explicit_spans)
        exact = all(c['method'] in {'exact_name', 'exact_path', 'controlled_alias'} and c['review_status'] == 'approved' for c in candidates)
        usage = 'explicit_tag_filter' if explicit and exact else 'semantic_condition' if hard and not explicit else 'ranking_signal'
        mappings.append({"term": concept["original"], "canonical": concept["canonical"], "source": concept["source"],
                         "status": "matched" if len(candidates) == 1 else "ambiguous", "method": candidates[0]['method'],
                         "candidates": candidates, "requires_resolution": explicit and (len(candidates) != 1 or not exact),
                         "polarity": concept.get('polarity', 'include'), 'object_group': hard[0]['object_group'] if hard else 'subject',
                         "condition_ids": [item["condition_id"] for item in hard], "usage": usage})
    return {"version": "tag-mapping-v2", "taxonomy_fingerprint": index.version, 'alias_version': index.alias_version,
            "status": "degraded" if degraded else "collected", 'fallback_reason': degraded, "mappings": mappings, "unmatched": unmatched,
            'unresolved_filters':unresolved_filters,
            'subtask_ids': [s['subtask_id'] for s in understanding.get('subtasks', [])]}


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
        declared_crops = set(re.findall(r'(?:本试验|本研究|研究对象|作物为|作物是|种植作物)[：:为是采用\s]{0,4}(玉米|小麦|水稻|番茄)', normalized))
        if condition['category'] == 'crop' and declared_crops:
            state = 'satisfied' if ((term in declared_crops) != condition['negated']) else 'not_satisfied'
        regions = understanding.get('entity_categories',{}).get('regions',[])
        declared_regions = [r for r in regions if re.search(r'(?:试验地点|研究地点|地区为|位于)[：:为是在\s]{0,3}'+re.escape(r), normalized)]
        if condition['category']=='region' and declared_regions:
            state = 'satisfied' if ((term in declared_regions) != condition['negated']) else 'not_satisfied'
        if not present and condition["category"] == "crop" and any(crop in normalized for crop in CROPS - {term}): state = "not_satisfied"
        if not present and condition["category"] == "crop" and condition["negated"] and any(crop in normalized for crop in CROPS - {term}): state = "satisfied"
        offset = normalized.find(term)
        related = [item for item in mapping.get("mappings", []) if condition["condition_id"] in item["condition_ids"]]
        tagged = any(set(candidate.get('descendant_ids', [candidate['id']])) & set(tag_ids) for item in related for candidate in item['candidates'])
        explicit = [item for item in related if item["usage"] == "explicit_tag_filter" and item["status"] == "matched"]
        if explicit:
            member = tagged != condition['negated']
            if not member: state = 'not_satisfied'
            elif state == 'unknown': state = 'satisfied'
        checks.append({"condition_id": condition["condition_id"], "object_group": condition["object_group"], "state": state,
                       "basis": normalized[max(0, offset-60):offset+len(term)+100] if offset >= 0 else "正文未提供可核对的条件依据",
                       "tag_match": tagged, "conflict": tagged and state == "not_satisfied", "conflict_resolution": "正文核对" if tagged and state == "not_satisfied" else None,
                       "source": condition["source"], "filter_stage": "content_verification"})
        checks[-1]['membership_dimension'] = explicit[0]['candidates'][0]['dimension_id'] if explicit and not condition['negated'] else None
    groups = {}
    for check in checks: groups.setdefault(check["object_group"], []).append(check)
    common = groups.pop("subject", [])
    def satisfied(items):
        dimensions = {}
        for item in items:
            if item['membership_dimension']:
                dimensions.setdefault(item['membership_dimension'],[]).append(item)
            elif item['state'] != 'satisfied': return False
        return all(any(item['state']=='satisfied' for item in group) for group in dimensions.values())
    unresolved_filter = (mapping.get('unresolved_filters') or any(item.get('requires_resolution') for item in mapping.get('mappings',[])) or
                         explicit_tag_spans(understanding.get('raw_query','')) and not any(item['usage']=='explicit_tag_filter' for item in mapping.get('mappings',[])))
    eligible = not unresolved_filter and satisfied(common) and (not groups or any(satisfied(group) for group in groups.values()))
    return checks, eligible


def verified_object_groups(checks):
    groups = {}
    for check in checks:
        if check['object_group'] != 'subject': groups.setdefault(check['object_group'],[]).append(check)
    return {key for key,items in groups.items() if all(item['state']=='satisfied' for item in items)}


def balance_objects(items, checks_for):
    """Keep one verified source per object ahead of the remaining ranked sources."""
    grouped=[verified_object_groups(checks_for(item)) for item in items]
    selected=[]
    for group in sorted(set().union(*grouped)):
        if any(group in grouped[i] for i in selected): continue
        selected.append(next(i for i,groups in enumerate(grouped) if group in groups))
    return [items[i] for i in selected]+[item for i,item in enumerate(items) if i not in selected]


def object_coverage(check_lists, understanding):
    groups={}
    for item in (understanding or {}).get('conditions',[]):
        if item['object_group']!='subject': groups.setdefault(item['object_group'],[]).append(item['value'])
    covered=set().union(*(verified_object_groups(checks) for checks in check_lists))
    return {'expected':list(groups),'covered':sorted(covered),
            'missing':['、'.join(values) for key,values in groups.items() if key not in covered]}
