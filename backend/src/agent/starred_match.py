"""Auditable reuse of maintained Q&A; no answer means no coverage."""
import hashlib
import re

from src.agent.understanding import canonical, CROPS, terms


def question_key(text):
    value = canonical(text)
    for pattern, replacement in (
        (r"主要受哪些因素影响|受什么影响|影响因素有哪些|有哪些影响因素|为什么会发生|原因是什么|有哪些原因", "原因"),
        (r"是什么意思|什么意思|是什么|的含义|的定义|含义是什么", "含义"),
        (r"氮素淋洗|氮素淋失|氮淋洗", "氮淋失"),
        (r"请问|请解释|解释一下|能不能|可以|帮我|一下|什么是|[\s，,。？?！!:：；;]", ""),
    ):
        value = re.sub(pattern, replacement, value)
    return value


def match_starred(understanding, questions):
    results, covered = [], []
    for task in understanding["subtasks"]:
        if task["intent"] not in {"knowledge", "explanation", "case_search", "comparison"}: continue
        query = task["query"]
        key = question_key(query)
        candidates = []
        for item in questions:
            question = item["question"]
            candidate_key = question_key(question)
            overlap = len(terms(query) & terms(question))
            if not overlap and key != candidate_key: continue
            current_crops = {crop for crop in CROPS if crop in canonical(query)}
            candidate_crops = {crop for crop in CROPS if crop in canonical(question)}
            compatible = current_crops == candidate_crops or not candidate_crops
            # Numeric conditions and negations must survive canonicalization.
            numbers_equal = re.findall(r"\d+(?:\.\d+)?", query) == re.findall(r"\d+(?:\.\d+)?", question)
            negation_equal = bool(re.search(r"没有|不要|排除|不适用", query)) == bool(re.search(r"没有|不要|排除|不适用", question))
            exact_meaning = key == candidate_key
            if not exact_meaning and (key.endswith("含义") or candidate_key.endswith("含义")):
                subject = key.removesuffix("含义")
                exact_meaning = subject == candidate_key.removeprefix("什么是").removesuffix("含义")
            compatible = compatible and numbers_equal and negation_equal
            answer = item.get("answer", "").strip()
            adopted = compatible and exact_meaning and bool(answer)
            status = "adopted" if adopted else "empty_answer" if compatible and exact_meaning else "not_applicable" if not compatible else "candidate_only"
            snapshot = {"question_id": item["question_id"], "revision": item.get("revision"), "question": question,
                        "answer": item.get("answer", ""), "updated_at": item.get("updated_at")}
            fingerprint = hashlib.sha256(str(sorted(snapshot.items())).encode()).hexdigest()
            candidates.append({"question_id": item["question_id"], "status": status, "overlap": overlap,
                               "reason": {"adopted": "规范问题一致且条件无冲突，有可用人工答案", "empty_answer": "问题相符但答案为空，继续后续能力", "not_applicable": "作物、数值或否定条件冲突", "candidate_only": "仅相关候选，尚不能确认完整覆盖"}[status],
                               "fingerprint": fingerprint, "snapshot": snapshot})
        candidates.sort(key=lambda item: (item["status"] == "adopted", item["overlap"]), reverse=True)
        selected = next((item for item in candidates if item["status"] == "adopted"), None)
        if selected:
            covered.append({"subtask_id": task["subtask_id"], "query": query, "question_id": selected["question_id"],
                            "answer": selected["snapshot"]["answer"], "fingerprint": selected["fingerprint"]})
        results.append({"subtask_id": task["subtask_id"], "candidates": candidates, "coverage": "complete" if selected else "none"})
    remaining = [task["subtask_id"] for task in understanding["subtasks"] if task["subtask_id"] not in {item["subtask_id"] for item in covered}]
    return {"version": "starred-matching-v1", "run_id": understanding["run_id"], "turn_id": understanding["turn_id"],
            "status": "full" if covered and not remaining else "partial" if covered else "empty_answer" if any(candidate["status"] == "empty_answer" for item in results for candidate in item["candidates"]) else "no_match",
            "tasks": results, "adopted": covered, "remaining_subtask_ids": remaining}
