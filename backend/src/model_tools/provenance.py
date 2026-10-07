"""Versioned source facts for the received WHCNS sample; no inferred run pairing."""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path


METADATA_PATH = Path(__file__).resolve().parents[3] / "data/metadata/whcns-case-20260926.v1.json"


@lru_cache(maxsize=1)
def received_case_metadata() -> dict:
    return json.loads(METADATA_PATH.read_text(encoding="utf-8"))


def output_source_note(sha256: str) -> str | None:
    meta = received_case_metadata()
    if sha256 != meta["output"]["sha256"]:
        return None
    return ("随包 WHCNS 手册第 26 页将 Leak_NO3 定义为硝态氮淋失量；"
            "第 4、21 页说明模型以天为步长，Day 1 对应 manage_in 首次播种日期。"
            "本表与随包输入文件的实际运行配对、可执行程序版本和输出边界深度尚未独立核实，"
            "因此不换算日历日期或指定边界深度。")
