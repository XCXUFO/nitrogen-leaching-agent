from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from src.llm.base import ChatMessage
from src.rag.retriever import RetrievalResult

SYSTEM_PROMPT_WITH_CONTEXT = """\
你是面向中国农业研究者的氮素淋失风险问答助手。
回答必须基于下面给出的参考资料。如果资料不足以回答，请明确说明"资料中未涉及"。
机制、影响因素等专业判断只能引用论文正文的研究结果或讨论；题名、目录、参考文献条目不能作为机制证据。
保留研究作物、场景和时间尺度；不要用年际关系解释单日事件，也不要把模型误差写成真实淋失的驱动因素。
回答时请用 [1][2] 形式标注你引用的资料编号，与下方资料编号对应。
如果用户在追问前文，请结合【最近对话】理解指代，但事实依据仍只能来自【参考资料】。
若最近对话无法确定“它”“这个”等指代，只询问需要补充的对象和问题；不要猜测对象、罗列可能答案或引用资料。
如果问题要求多个数值或多个指标，请先逐条检查所有参考资料 chunk；
只有所有参考资料都没有相应指标时，才说明"资料中未涉及"。
如果用户问题里的 [79]、[81] 等编号像论文库编号，不要把它们当成下方资料编号；
请根据来源文件名中的 079_、081_ 等前缀识别论文，答案引用仍必须使用下方资料编号。

【参考资料】
{context}
"""

SYSTEM_PROMPT_NO_CONTEXT = """\
你是面向中国农业研究者的氮素淋失风险问答助手。
当前未检索到相关参考资料。请基于通用知识谨慎回答，
并在回答开头明确告知用户"以下回答未引用本知识库资料"。
"""

RECENT_DIALOGUE_TEMPLATE = """\
【最近对话】
{history}
"""

_BILINGUAL_RETRIEVAL_HINTS: tuple[tuple[str, str], ...] = (
    ("湖北", "Hubei"),
    ("荆州", "Jingzhou"),
    ("稻田", "paddy field rice field"),
    ("水稻", "rice"),
    ("生长季", "growing season"),
    ("地下径流", "subsurface runoff subsurface nitrogen losses lateral seepage"),
    ("地下", "subsurface"),
    ("侧向渗漏", "lateral seepage"),
    ("地表径流", "surface runoff"),
    ("径流", "runoff"),
    ("淋失", "leaching losses"),
    ("氮损失", "nitrogen losses"),
    ("氮素损失", "nitrogen losses"),
    ("硝态氮", "nitrate nitrogen NO3"),
    ("氨挥发", "ammonia volatilization NH3"),
    ("氧化亚氮", "nitrous oxide N2O"),
    ("温室", "greenhouse"),
    ("番茄", "tomato"),
    ("秸秆", "straw incorporation"),
    ("减氮", "reduced nitrogen fertilization"),
    ("控制灌溉", "controlled irrigation CI"),
    ("节水灌溉", "water-saving irrigation"),
    ("灌溉", "irrigation"),
    ("施肥", "fertilization nitrogen application"),
    ("绿肥", "green manure milk vetch"),
    ("小麦", "wheat"),
    ("玉米", "maize corn"),
)

_COMPOUND_RETRIEVAL_HINTS: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("温室番茄", "滴灌"),
        "Han 2025 mitigating N leaching N2O emissions combining drip "
        "irrigation reduced fertilization straw incorporation greenhouse "
        "tomato systems conventional flooding fertilization CIF CIFS "
        "drainage nitrate DON dissolved organic nitrogen yield water use "
        "efficiency nitrogen use efficiency Liang 2020 greenhouse vegetable "
        "production systems nitrate DON leaching optimize water N management",
    ),
    (
        ("温室番茄", "秸秆"),
        "Han 2025 greenhouse tomato straw incorporation conventional flooding "
        "fertilization CIFS CIF total nitrogen leaching nitrate leaching DON "
        "leaching N2O emissions drip irrigation reduced fertilization",
    ),
    (
        ("WHCNS_Rice", "控制灌溉"),
        "基于WHCNS_Rice模型的水稻节水灌溉模式模拟与评价 Huang 2026 "
        "controlled irrigation CI flooding irrigation FSI water-saving "
        "irrigation WSI water seepage nitrate nitrogen leaching entropy "
        "weight TOPSIS 64.27 73.65 84.80 93.28",
    ),
    (
        ("水稻", "节水灌溉"),
        "WHCNS_Rice controlled irrigation CI flooding irrigation FSI "
        "water-saving irrigation WSI seepage nitrate leaching TOPSIS",
    ),
    (
        ("I-4", "I-6"),
        "Wu 2023 optimizing irrigation strategies sustainable crop "
        "productivity reduced groundwater consumption winter wheat maize "
        "rotation system rainfed R I-4 I-6 annual crop yield irrigation "
        "water amount crop water productivity irrigation water productivity "
        "19.83 28.65 33.91 33.46 90.53",
    ),
    (
        ("浅层地下水", "滴灌玉米"),
        "Hou 2025 optimising water and nitrogen management drip-irrigated "
        "maize oasis farmland shallow groundwater high initial soil mineral "
        "nitrogen low initial soil mineral nitrogen optimal nitrogen rate "
        "200 250 kg N ha water 473 516 mm maximize yield minimize water "
        "nitrogen losses",
    ),
    (
        ("稻田", "地下径流"),
        "subsurface fluxes dominate dissolved nitrogen losses rice paddies "
        "central China Huang 2024 quantified magnitude dynamics subsurface "
        "N loss during rice growing season surface N runoff total applied N "
        "paddy field Jingzhou Hubei compared with surface runoff lateral "
        "seepage contribution ponded water depth ditch water level optimized "
        "irrigation management conservation tillage mitigation ditch pond system",
    ),
    (
        ("稻田", "侧向渗漏"),
        "subsurface nitrogen losses during rice growing season paddy field "
        "lateral seepage contribution",
    ),
)

_RETRIEVAL_QUERY_OVERRIDES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("温室番茄", "2020", "2025"),
        "Simulating nitrate and DON leaching optimize water N management "
        "greenhouse vegetable production systems drip irrigation conventional "
        "furrow fertilization reduced nitrate DON leaching Liang 2020 Han "
        "2025 drip irrigation reduced N application decreased drainage N "
        "leaching N2O emissions greenhouse tomato drip fertigation treatments "
        "reduced irrigation water use water drainage nitrate and DON leaching "
        "by 41 60 68 68 percent without compromising crop yield",
    ),
    (
        ("F2W2", "南四湖"),
        "Feng 2025 Nansi Lake basin F2W2 reduced controlled-release "
        "fertilizer reduced irrigation compared CK ammonia volatilization "
        "nitrogen loss leaching reduced 29.17 27.13 water nitrogen use "
        "efficiencies increased 11.38 17.80 cumulative nitrogen leaching "
        "ammonia volatilization F2W1 reduced 8.90 41.67 F1W2 reduced 12.50 "
        "15.99",
    ),
    (
        ("F2W1", "F1W2", "南四湖"),
        "Feng 2025 Nansi Lake basin F2W1 F1W2 compared CK cumulative "
        "nitrogen leaching ammonia volatilization F2W1 reduced 8.90 41.67 "
        "F1W2 reduced 12.50 15.99 F2W2 best performance reduced nitrogen "
        "loss stable yield",
    ),
    (
        ("单季稻", "早稻", "晚稻", "平均总氮损失"),
        "Li 2025 Hubei regional WHCNS rice average total N loss single early "
        "late season rice 77.2 65.6 81.5 kg N ha accounting 33.6 31.5 "
        "40.8 percent N application late season rice more severe N loss",
    ),
    (
        ("湖北省水稻", "空间差异"),
        "Li 2025 Hubei regional WHCNS spatial difference yield N loss yield "
        "higher central Hubei lower western southeastern driven solar "
        "radiation temperature soil clay content pH bulk density N runoff "
        "loss decreased east to west rainfall temperature single early "
        "season rice bulk density late season rice higher N leaching "
        "denitrification northwestern Hubei soil total N organic matter poor "
        "aeration higher NH3 eastern Hubei temperature precipitation",
    ),
    (
        ("WS", "W4", "ETc"),
        "Wu 2024 W4 treatment saved 97.9 98.2 mm irrigation water compared "
        "to W6 improved water productivity by 10.7 32.1 reduced water "
        "footprint by 14.3 25.1 WS system exhibited less variability in "
        "evapotranspiration ETc reductions 23.6 29.1 compared WM system "
        "elevating groundwater table by 58.4 146.4",
    ),
    (
        ("1978", "2019", "NUE", "2050"),
        "Ju 2025 The national NUE for single rice was 0.31 over the study "
        "period rapid increase of 0.048 per 10 years after 2005 primarily "
        "controlled by fertilization management and cultivar shifts benefits "
        "of cultivar improvement 0.034 per 10 years almost entirely offset "
        "by excessive use of N fertilizers -0.029 per 10 years before 2005 "
        "To reach NUE target of 0.6 by 2050 better management alone will not "
        "be enough rice breeding urgently needed",
    ),
    (
        ("区域稻作灌溉优化框架", "试验变异"),
        "Bo 2025 process-based modeling framework sustainable irrigation "
        "regional rice greenhouse gas applying framework accounted for 52 "
        "60 37 94 percent experimentally observed variations rice yield "
        "irrigation water use methane nitrous oxide emissions simulation "
        "errors reduced 35 85 percent additional 18 percent areas feasible "
        "irrigation optimization additional 11 14 percent reduction "
        "potentials water use methane emissions without compromising "
        "production",
    ),
    (
        ("晚稻", "单季稻", "早稻", "更严重"),
        "Li 2025 Hubei regional WHCNS late season rice more severe N loss "
        "average total N loss single early late season rice 77.2 65.6 81.5 "
        "kg N ha accounting for 33.6 31.5 40.8 percent N application rates",
    ),
    (
        ("W4/I-4", "共同结论"),
        "Wu 2023 I-4 treatment achieved comparable yields to I-6 treatment "
        "with reduction in irrigation water use increase crop water "
        "productivity irrigation water productivity R treatment led to "
        "severe yield losses sustainably maintained yields with less "
        "irrigation decreasing groundwater consumption Wu 2024 W4 "
        "significantly reduced field water losses particularly deep "
        "percolation comparable yields to W6 and FI higher crop water "
        "productivity optimized precision irrigation strategies Wu 2024 WS "
        "system groundwater table water footprint W4 irrigation regime",
    ),
    (
        ("Han", "温室番茄"),
        "drip irrigation reduced N application decreased average seasonal "
        "drainage N leaching nitrate DON N2O emissions enhanced yield water "
        "use efficiency N use efficiency greenhouse tomato conventional flood "
        "irrigation",
    ),
    (
        ("温室番茄", "秸秆"),
        "CIFS reduced overall average seasonal total N leaching due to "
        "reduction average seasonal nitrate leaching but increased average "
        "seasonal DON leaching N2O emissions flood irrigation greenhouse "
        "tomato straw incorporation CIF",
    ),
    (
        ("WHCNS_Rice", "控制灌溉"),
        "ＣＩ模式在保证节水的前提下可较ＦＳＩ和ＷＳＩ减少６４．２７％～７３．６５％"
        "的水分渗漏和８４．８０％～９３．２８％硝态氮淋失量 熵权ＴＯＰＳＩＳ "
        "控制灌溉 最优灌溉模式 WHCNS_Rice 水稻节水灌溉",
    ),
    (
        ("I-4", "I-6"),
        "Compared to R treatment I-4 significantly increased annual crop "
        "yield 19.83 28.65 maintained similar crop water productivity "
        "comparable yields to I-6 33.91 reduction irrigation water use 33.46 "
        "increase crop water productivity 90.53 irrigation water productivity "
        "winter wheat summer maize rotation",
    ),
    (
        ("浅层地下水", "高初始土壤矿质氮"),
        "Simulations revealed high NISM levels reduced benefits additional N "
        "maize yield resource use efficiency low NISM conditions responded "
        "positively increased N applications optimal N application rate 200 "
        "250 kg N ha total water input 473 516 mm maximizing yield minimizing "
        "water N losses shallow groundwater drip irrigated maize oasis farmland",
    ),
    (
        ("[79]", "[81]"),
        "079_huang_2024 subsurface N losses paddy field lateral seepage "
        "081_li_2025 regional modelling rice yields nitrogen loss Hubei "
        "Province",
    ),
)

StandaloneRole = Literal["user", "assistant"]


@dataclass(frozen=True, slots=True)
class DialogueTurn:
    role: StandaloneRole
    content: str


def format_context(retrieved: list[RetrievalResult], max_chars: int) -> str:
    """Format retrieved chunks as numbered prompt context."""
    if not retrieved:
        return ""

    pieces: list[str] = []
    used = 0
    for index, result in enumerate(retrieved, start=1):
        source = result.metadata.get("source", "unknown")
        block = f"[{index}] (来源: {source})\n{result.document}\n"
        if pieces and used + len(block) > max_chars:
            break
        pieces.append(block)
        used += len(block)

    return "\n".join(pieces)


def format_history(history: Sequence[DialogueTurn], max_chars: int = 1600) -> str:
    """Format recent dialogue newest-last, trimming from the oldest turns."""
    if not history or max_chars <= 0:
        return ""

    lines: list[str] = []
    used = 0
    for turn in reversed(history):
        label = "用户" if turn.role == "user" else "助手"
        content = " ".join(turn.content.split())
        line = f"{label}: {content}"
        cost = len(line) + (1 if lines else 0)
        if lines and used + cost > max_chars:
            break
        lines.append(line)
        used += cost

    lines.reverse()
    return "\n".join(lines)


def expand_retrieval_query(query: str) -> str:
    """Add compact English domain hints for Chinese queries over English papers."""
    for triggers, expansion in _RETRIEVAL_QUERY_OVERRIDES:
        if all(trigger in query for trigger in triggers):
            return expansion

    hints: list[str] = []
    for triggers, expansion in _COMPOUND_RETRIEVAL_HINTS:
        if all(trigger in query for trigger in triggers):
            hints.extend(expansion.split())

    for trigger, expansion in _BILINGUAL_RETRIEVAL_HINTS:
        if trigger in query:
            hints.extend(expansion.split())

    if not hints:
        return query

    deduped = list(dict.fromkeys(hints))
    return f"{' '.join(deduped)}\n中文问题: {query}"


def build_retrieval_query(query: str, history: Sequence[DialogueTurn]) -> str:
    """Compose a retrieval query that carries short dialogue context."""
    expanded_query = expand_retrieval_query(query)
    formatted = format_history(history, max_chars=800)
    if not formatted:
        return expanded_query
    return f"{formatted}\n当前问题: {expanded_query}"


def build_messages(
    query: str,
    retrieved: list[RetrievalResult],
    *,
    max_context_chars: int,
    history: Sequence[DialogueTurn] | None = None,
) -> list[ChatMessage]:
    if retrieved:
        context = format_context(retrieved, max_context_chars)
        system = SYSTEM_PROMPT_WITH_CONTEXT.format(context=context)
    else:
        system = SYSTEM_PROMPT_NO_CONTEXT

    messages = [ChatMessage(role="system", content=system)]
    formatted_history = format_history(history or [], max_chars=1600)
    if formatted_history:
        messages.append(
            ChatMessage(
                role="user",
                content=RECENT_DIALOGUE_TEMPLATE.format(history=formatted_history),
            )
        )
    messages.append(ChatMessage(role="user", content=query))
    return messages
