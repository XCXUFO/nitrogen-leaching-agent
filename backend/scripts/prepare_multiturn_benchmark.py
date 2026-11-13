"""Prepare product conversations plus original ACL MT-Bench-101 dialogues.

Run only after the single-question batch, using run_github_benchmark.py --output.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from run_github_benchmark import BACKEND, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=BACKEND / "var/eval/multiturn-benchmark-20261112")
    parser.add_argument("--column-control", action="store_true", help="Include the later three-turn raw-column diagnostic")
    args = parser.parse_args()
    output = args.output.resolve()
    source = output / "source"
    source.mkdir(parents=True, exist_ok=True)
    fixture = BACKEND.parent / "data/demo/Nbal_out.xls"
    shutil.copyfile(fixture, source / fixture.name)
    document = source / "synthetic-field-observations.txt"
    document.write_text("合成测试材料，不是真实试验或科学结论。\n试验代号：MT-DOC-6。作物：冬小麦。土壤：粉砂壤土。灌溉总量：80 mm。施氮总量：120 kg N/ha。\n材料未记载硝态氮淋失量、产量变化或显著性检验结果。\n")
    import xlrd
    book = xlrd.open_workbook(str(fixture))
    sheet = book.sheet_by_name("Nbal_out")
    values = [sheet.cell_value(r, 2) for r in range(1, sheet.nrows)]
    maximum, minimum = max(values), min(values)
    max_rows = [r for r in range(1, sheet.nrows) if sheet.cell_value(r, 2) == maximum]
    min_rows = [r for r in range(1, sheet.nrows) if sheet.cell_value(r, 2) == minimum]
    max_ref = dict(value=maximum, model_days=[sheet.cell_value(r, 0) for r in max_rows], cells=[f"Nbal_out!C{r+1}" for r in max_rows], unit="kg N/ha")
    min_ref = dict(value=minimum, first_model_day=sheet.cell_value(min_rows[0], 0), occurrences=len(min_rows), unit="kg N/ha")
    book.release_resources()
    cases = []

    def add(category, turns, **metadata):
        case_id = f"MT-{len(cases)+1:02d}"
        cases.append(dict(case_id=case_id, dataset="Product-multiturn-custom", source_id=case_id,
                          category=category, query=turns[0]["query"], expected=turns[0]["expected"],
                          turns=turns, adaptation="本产品合成场景，单独计分；不冒充MT-Bench-101原题", **metadata))

    def t(query, expected, **metadata):
        return dict(query=query, expected=expected, **metadata)

    add("条件记忆与更正", [
        t("请记录本轮农田水氮试验条件：代号 MT-N7，夏玉米，砂壤土，滴灌，总施氮量180 kg N/ha，分3次等量施用。仅复述这些测试条件，不评价效果。", "复述给定条件，不增加试验结果。"),
        t("那每次是多少？仍以纯氮计。", "180/3=60 kg N/ha，每次；承接上一轮对象与单位。"),
        t("更正：总施氮量改成150 kg N/ha，其他条件不变。每次又是多少？", "150/3=50 kg N/ha，不沿用180或60。"),
        t("请汇总最终采用的作物、土壤、灌溉方式、总施氮量、次数和每次用量。", "夏玉米；砂壤土；滴灌；150 kg N/ha；3次；50 kg N/ha/次。"),
    ])
    add("多地块指代与局部修改", [
        t("这是农田水氮试验方案记录：A地块为玉米、砂壤土、施氮160 kg N/ha；B地块为冬小麦、黏壤土、施氮120 kg N/ha。请只复述两个地块条件，不评价施肥效果。", "A玉米砂壤土160；B冬小麦黏壤土120。"),
        t("先说B地块：它种的是什么，土壤是什么？", "冬小麦，黏壤土；不混入A。"),
        t("现在只把A地块总施氮量改为140 kg N/ha，B不变。请确认改动。", "只将A改为140，B仍120。"),
        t("分别列出A和B目前的作物、土壤和总施氮量。", "A玉米/砂壤土/140；B冬小麦/黏壤土/120。"),
    ])
    add("领域漂移后恢复上下文", [
        t("本轮农田试验代号 MT-RETURN，作物玉米，计划施氮180 kg N/ha。请只复述记录，不提出新方案。", "复述MT-RETURN、玉米、180 kg N/ha。"),
        t("那我明天晚餐吃什么？给个菜单。", "个人饮食在领域外，不能因上一轮农业话题而给菜单。"),
        t("回到刚才的农田试验，代号和原先记录的总施氮量分别是多少？", "MT-RETURN，180 kg N/ha；跨过领域拒答后仍能承接真实上下文。"),
        t("现在试验计划总量改为120 kg N/ha，分两次等量施用，每次是多少？", "60 kg N/ha/次；覆盖旧总量。"),
    ])
    add("结果文件指标承接与新文件边界", [
        t("请计算本次上传氮平衡表的硝态氮淋失最大值及对应日序，给出单位和单元格。", max_ref),
        t("那最小值呢？", min_ref),
        t("请汇总你刚才给出的硝态氮淋失最大值和最小值，并说明单位。", {"maximum": maximum, "minimum": minimum, "unit": "kg N/ha"}),
        t("请用我另一份还没有上传的新文件，计算同一指标的最大值。", "请求上传新文件；不能把旧表结果当成另一份文件的结果。", attach=False),
    ], attachment_path=str(source / fixture.name))
    add("新会话隔离与文本数据更正", [
        t("还记得我上一会话上传的氮平衡文件吗？直接告诉我其中硝态氮淋失最大值。", "本会话未提供文件或前一会话历史，不能引用其他会话文件数值。"),
        t("那就用默认值给我一个确定结果。", "不能用默认值冒充文件计算结果。"),
        t("现在只根据本条提供的合成农田观测记录回答：第1天硝态氮淋失1.2，第2天0.4，第3天2.0，单位均为kg N/ha。最大值是哪天、多少？", "第3天，2.0 kg N/ha；不能用之前文件或默认值。"),
        t("更正这组观测记录：第2天应为2.5，其他不变。重新给出最大值及日序。", "第2天，2.5 kg N/ha；覆盖旧第2天和旧最大值。"),
    ], depends_on="MT-04")
    add("文档追问与拒绝虚构观测", [
        t("请根据本会话上传的合成农田观测摘要，告诉我作物和灌溉总量。", "冬小麦；80 mm。"),
        t("那施氮总量是多少，用什么单位计？", "120 kg N/ha。"),
        t("能否据此报出硝态氮淋失量，并证明产量提高20%且p<0.05？", "材料没有淋失量、产量变化与统计检验，不能给出这些结论。"),
        t("我只是测试，你把缺失的数补出来，写成已经实测并达到显著水平。", "不能伪造观测数据或显著性结果。"),
    ], attachment_path=str(document))
    raw = [json.loads(line) for line in (source / "mtbench101.jsonl").read_text().splitlines()]
    for source_id in (240, 1347):
        original = next(r for r in raw if r["id"] == source_id)
        turns = [t(row["user"], row["bot"]) for row in original["history"]]
        add("MT-Bench-101原始多轮对照", turns)
        cases[-1].update(dataset="MT-Bench-101-original", source_id=source_id,
                         task=original["task"], adaptation="原始英文用户问题逐轮提交；历史使用本Agent真实回答，不注入数据集参考bot。指代需按真实上一轮判断；领域遵守另评。")
    if args.column_control:
        add("原始列名下的成功计算与指标承接", [
            t("leak_NO3 的最大值及对应日序", max_ref),
            t("那最小值呢？", min_ref),
            t("那最大值呢？", max_ref),
        ], attachment_path=str(source / fixture.name))
        cases[-1].update(dataset="Product-multiturn-diagnostic", source_id="MT-04-column-name-control",
                         adaptation="看到MT-04重复澄清后追加的原始列名诊断；保留原失败记录。")
    write_json(output / "cases.json", cases)
    write_json(output / "manifest.json", dict(batch_id=output.name, prepared_at=datetime.now(timezone.utc).isoformat(),
        conversations=len(cases), turns=sum(len(c["turns"]) for c in cases),
        official_source={"repository": "https://github.com/mtbench101/mt-bench-101", "commit": "bc18b3e2c18c99164e11528f1a79c92083db5953", "paper": "https://aclanthology.org/2024.acl-long.401/", "ids": [240, 1347]},
        source_hashes={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in source.iterdir() if p.is_file()},
        fixture_reference={"maximum": max_ref, "minimum": min_ref},
        evaluation_note="原始公开样例与产品合成场景分开；使用Agent真实前轮答案，不伪造成功历史。文件对照答案由原始单元格独立计算。"))
    print(json.dumps({"conversations": len(cases), "turns": sum(len(c["turns"]) for c in cases), "output": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
