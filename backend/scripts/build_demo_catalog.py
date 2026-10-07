"""Rebuild the explicitly selected public archive; never read live databases."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / "docs/iterations/2026-09-29-agent-harness"
OUTPUT = ROOT / "data/demo"


def read(name):
    return json.loads((ARCHIVE / name).read_text(encoding="utf-8"))


def project_run(run):
    evidence = []
    for item in run.get("evidence", []):
        if item.get("source_type") == "file":
            evidence.append({"value": item.get("claim_or_value"), "unit": item.get("unit"),
                "cell": item.get("location", {}).get("cell"),
                "day_cell": item.get("location", {}).get("day_cell"),
                "model_day": item.get("location", {}).get("model_day")})
    return {key: run.get(key) for key in ("run_id", "started_at", "input", "answer", "latency_ms", "outcome")} | {
        "route": run.get("decision", {}).get("route"),
        "tools": [{"skill": t["skill"], "status": t["status"]} for t in run.get("tool_calls", [])],
        "citations": [{"index": e.get("location", {}).get("citation_index"),
                       "title": e.get("provenance", {}).get("title", "文献依据"),
                       "excerpt": e.get("claim_or_value", "")}
                      for e in run.get("evidence", []) if e.get("source_type") == "literature"],
        "evidence": evidence}


def main():
    source = "evidence-2026-10-03/selected-run-traces.json"
    runs = read(source)["runs"]
    specs = [
        ("file-extrema", "一张结果表，得到可核对的最大值", "文件分析", [1],
         "读取已有 WHCNS 输出，使用程序计算，并给出值、单位、模型日序与单元格。",
         ["最大值约 3.6593 kg N ha-1，模型日序 283。", "对应 C284/A284，不擅自换算为日历日期。"]),
        ("follow-up", "连续追问与附件移除", "多轮对话", [1, 2, 3],
         "有效附件下继承指标；附件移除后要求重新上传，避免继续引用旧表。",
         ["追问最小值返回 0，首次模型日序 2，共 191 条并列。", "附件不可用时澄清，不复用旧数值。"]),
        ("literature", "有出处的文献解释", "文献问答", [5],
         "回答区分研究场景与证据尺度，机制解释仍待独立领域审核。",
         ["逐条给出引用，不能将一般机制认定为某一天峰值的实际成因。"]),
        ("composed", "文件事实与可能机制分开表达", "组合回答", [6],
         "先给表中计算结果，再解释有文献支持的可能机制和缺失材料。",
         ["区分表中观察、可能机制和待核查材料。", "缺少运行来源时不宣称已复现仿真。"]),
    ]
    cases = [{"id": identity, "title": title, "category": category, "summary": summary,
              "expected": expected, "status": "专业审核待完成" if identity in {"literature", "composed"} else "历史工程重放",
              "review": "已保存真实运行回答；本展示未新增人工评分或专家签核。",
              "runs": [project_run(runs[i]) for i in indices], "source": source}
             for identity, title, category, indices, summary, expected in specs]
    workflow_source = "evidence-2026-10-04-workflow-integrity.json"
    workflow = read(workflow_source)
    case = workflow["executions"][0]["review"]["case_snapshot"]["case"]
    cases.append({"id": "workflow", "title": "从问题登记到回归复测", "category": "流程演示",
        "summary": "隔离浏览器测试实际走通任务、执行、评分、Issue、重放与复测关联。",
        "status": "合成评分 · 流程验证", "expected": case["expected"],
        "review": "fail/pass 是测试脚本刻意提交的合成评分，仅验证流程，不代表真实缺陷被修复或专业准确率。",
        "runs": [project_run(r) for r in workflow["runs"]], "source": workflow_source,
        "stages": ["任务冻结用例 NEW01@2 与构建", "保存真实问答和合成 fail 评分", "关联原执行登记 Issue",
                   "保存回归基线并重放", "新执行提交合成 pass 评分", "核验运行版本并关联复测，保留原评分"],
        "comparison": [{"label": "原执行", "overall": "fail（合成）", "execution_id": workflow["executions"][0]["execution_id"]},
                       {"label": "重放执行", "overall": "pass（合成）", "execution_id": workflow["executions"][1]["execution_id"]}]})
    fixture = ROOT / "data/demo/Nbal_out.xls"
    OUTPUT.mkdir(exist_ok=True)
    catalog = {"version": "public-demo-v1", "published_on": "2026-10-05",
        "notice": "只读公开快照；不包含实时访客聊天。历史工程运行与合成流程评分分别标注，专业审核尚未完成。",
        "cases": cases, "assets": [{"filename": fixture.name, "sha256": hashlib.sha256(fixture.read_bytes()).hexdigest(),
            "description": "WHCNS 氮平衡输出示例，352 条记录；仅演示结果读取，不证明输入输出运行配对。"}],
        "sources": [{"name": name, "sha256": hashlib.sha256((ARCHIVE / name).read_bytes()).hexdigest()}
                    for name in (source, workflow_source)]}
    (OUTPUT / "catalog.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Published {len(cases)} selected cases; no operational database was read.")


if __name__ == "__main__":
    main()
