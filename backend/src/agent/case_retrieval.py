"""Search the eligible corpus before applying a per-call material budget."""
import hashlib
import json

from src.agent.understanding import assess_conditions, terms, balance_objects, object_coverage
from src.retrieval.local_index import retrieval_requests


def select_materials(store, query, *, ids=None, understanding=None, mapping=None, budget=24000, max_cases=30):
    pipeline = {'version':'legacy-scan','status':'selected'}
    if not ids and getattr(store, 'search_strategy', 'indexed') == 'indexed':
        try:
            rows, pipeline = store.search_index.candidates(query, mapping, understanding=understanding)
            candidate_ids = list(dict.fromkeys(r['material_id'] for r in rows))
            pool = store.candidates(candidate_ids) if candidate_ids else []
            origins = {r['material_id']:r['recall_paths'] for r in rows}
        except Exception as exc:
            pool = store.candidates()
            pipeline = {'version':'legacy-scan','status':'degraded','fallback':'scan','error_type':type(exc).__name__}
            origins = {}
    else:
        pool = store.candidates(ids)
        origins = {}
    if ids and set(ids) != {item["id"] for item in pool}:
        return [], {"status": "unavailable", "pool_size": len(pool), "candidates": []}
    if ids:
        pool.sort(key=lambda item: ids.index(item["id"]))
    else:
        unique = {}
        for item in pool: unique.setdefault(store.content_key(item), item)
        pool = list(unique.values())
    query_terms = terms(retrieval_requests(query, understanding)['full_text'])
    ranked = []
    for item in pool:
        text = item["title"] + "\n" + item["body"]
        checks, eligible = assess_conditions(text, item["tag_ids"], understanding or {}, mapping or {})
        score = len(query_terms & terms(text)) + 3 * len(query_terms & terms(item["title"]))
        ranked.append((item, checks, eligible, score))
    if not ids:
        ranked.sort(key=lambda value: (-value[3], value[0]["id"]))
        ranked=balance_objects(ranked,lambda item:item[1] if item[2] else [])
    selected, records, used = [], [], 2
    for item, checks, eligible, score in ranked:
        material = {key: item[key] for key in ("id", "title", "body", "body_format", "explanation", "supplementary", "source")}
        size = len(json.dumps(material, ensure_ascii=False)) + 2
        within_budget = used + size <= budget and len(selected) < max_cases
        adopted = eligible and within_budget
        reason = "selected" if adopted else "condition_unconfirmed" if not eligible else "material_budget"
        fingerprint = hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        records.append({"id": item["id"], "title": item["title"], "revision": item["revision"], "fingerprint": fingerprint,
                        "score": score, "checks": checks, "selected": adopted, "reason": reason, 'recall_paths':origins.get(item['id'], []),
                        "material_chars": size, "location": "完整正文（含表格、解释和补充）", "snippet": item["body"] if adopted else None})
        if adopted:
            used += size
            selected.append(material)
    # Explicit/anchored comparison is atomic: never silently drop one object.
    if ids and len(selected) != len(pool):
        for record in records:
            if record["selected"]: record["selected"], record["reason"] = False, "comparison_incomplete"
        selected = []
    status = "selected" if selected else "budget_exceeded" if any(record["reason"] == "material_budget" for record in records) else "no_match"
    return selected, {"status": status, "query":query,"pool_size": pipeline.get('material_count', len(pool)), "budget_chars": budget, "used_chars": used, 'pipeline':pipeline,
                      'ranked_candidates':[{key:record[key] for key in ('id','title','score')} | {'rank':rank} for rank,record in enumerate(records,1)],
                      'adopted_case_ids':[item['id'] for item in selected],
                      'object_coverage':object_coverage([r['checks'] for r in records if r['selected']],understanding),
                      "scope": "explicit" if ids else "bounded_candidates" if pipeline.get('coverage')=='bounded' else "all_eligible", "candidates": records}
