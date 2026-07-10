from src.agent.prompt import (
    DialogueTurn,
    build_messages,
    build_retrieval_query,
    expand_retrieval_query,
    format_context,
    format_history,
)
from src.rag.retriever import RetrievalResult


def _result(
    index: int,
    *,
    document: str | None = None,
    source: str | None = None,
) -> RetrievalResult:
    return RetrievalResult(
        chunk_id=f"c{index}",
        document=document or f"chunk text {index}",
        score=1.0 - index * 0.1,
        metadata={"source": source or f"paper-{index}.txt"},
    )


def test_format_context_empty_returns_empty_string() -> None:
    assert format_context([], max_chars=100) == ""


def test_format_context_numbers_from_one() -> None:
    context = format_context([_result(1), _result(2), _result(3)], max_chars=500)
    assert "[1]" in context
    assert "[2]" in context
    assert "[3]" in context


def test_format_context_includes_source_metadata() -> None:
    context = format_context([_result(1, source="data/papers/sample.txt")], max_chars=500)
    assert "data/papers/sample.txt" in context


def test_format_context_truncates_by_max_chars_after_first_chunk() -> None:
    results = [
        _result(1, document="a" * 40),
        _result(2, document="b" * 40),
        _result(3, document="c" * 40),
    ]

    context = format_context(results, max_chars=70)

    assert "[1]" in context
    assert "[2]" not in context
    assert "[3]" not in context


def test_format_context_keeps_at_least_one_chunk() -> None:
    context = format_context([_result(1, document="a" * 100)], max_chars=10)

    assert "[1]" in context
    assert "a" * 100 in context


def test_build_messages_with_retrieved_uses_context_prompt() -> None:
    messages = build_messages(
        "氮素淋失受什么影响？",
        [_result(1)],
        max_context_chars=500,
    )

    assert [m.role for m in messages] == ["system", "user"]
    assert "参考资料" in messages[0].content
    assert "[1]" in messages[0].content
    assert "请先逐条检查所有参考资料 chunk" in messages[0].content
    assert "来源文件名中的 079_" in messages[0].content
    assert messages[1].content == "氮素淋失受什么影响？"


def test_build_messages_no_retrieved_uses_no_context_prompt() -> None:
    messages = build_messages("氮素淋失受什么影响？", [], max_context_chars=500)

    assert "未检索到相关参考资料" in messages[0].content
    assert messages[1].content == "氮素淋失受什么影响？"


def test_build_messages_returns_two_messages() -> None:
    assert len(build_messages("q", [_result(1)], max_context_chars=500)) == 2


def test_format_history_includes_recent_turns() -> None:
    history = [
        DialogueTurn(role="user", content="先讲 q04"),
        DialogueTurn(role="assistant", content="地下径流约为地表径流 2 倍"),
    ]

    text = format_history(history, max_chars=500)

    assert "用户: 先讲 q04" in text
    assert "助手: 地下径流约为地表径流 2 倍" in text


def test_build_retrieval_query_adds_history_for_followup() -> None:
    query = build_retrieval_query(
        "那侧向渗漏贡献多少？",
        [DialogueTurn(role="user", content="湖北荆州稻田地下径流")],
    )

    assert "湖北荆州稻田地下径流" in query
    assert "当前问题: lateral seepage" in query
    assert "中文问题: 那侧向渗漏贡献多少？" in query


def test_expand_retrieval_query_adds_domain_english_hints() -> None:
    query = expand_retrieval_query("湖北荆州稻田地下径流氮损失和地表径流相比如何？")

    assert query.startswith("subsurface fluxes dominate")
    assert "central China Huang 2024" in query
    assert "dissolved nitrogen losses" in query
    assert "subsurface" in query
    assert "surface runoff" in query
    assert "中文问题: 湖北荆州稻田地下径流氮损失和地表径流相比如何？" in query


def test_expand_retrieval_query_adds_greenhouse_tomato_hints() -> None:
    query = expand_retrieval_query("温室番茄系统中，滴灌减氮怎样降低氮淋失？")

    assert "Han 2025" in query
    assert "greenhouse tomato systems" in query
    assert "Liang 2020" in query
    assert "vegetable production" in query
    assert "中文问题: 温室番茄系统中，滴灌减氮怎样降低氮淋失？" in query


def test_expand_retrieval_query_uses_han_2025_override() -> None:
    query = expand_retrieval_query("2025 年 Han 等温室番茄研究中，滴灌减氮有什么影响？")

    assert query.startswith("drip irrigation reduced N application")
    assert "average seasonal drainage" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_uses_greenhouse_synthesis_override() -> None:
    query = expand_retrieval_query("温室番茄系统中，2020 年和 2025 年两篇研究结论是否一致？")

    assert query.startswith("Simulating nitrate and DON leaching")
    assert "41 60 68 68 percent" in query
    assert "Han 2025 drip irrigation reduced N application" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_uses_straw_tradeoff_override() -> None:
    query = expand_retrieval_query("在同一篇温室番茄研究中，秸秆还田有什么相反影响？")

    assert query.startswith("CIFS reduced overall average seasonal total N leaching")
    assert "increased average seasonal DON leaching N2O emissions" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_uses_corpus_source_id_override() -> None:
    query = expand_retrieval_query("请比较 [79] 与 [81] 对湖北稻田氮损失的证据。")

    assert query.startswith("079_huang_2024")
    assert "081_li_2025 regional modelling" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_whcns_rice_ci_hints() -> None:
    query = expand_retrieval_query("WHCNS_Rice 节水灌溉研究中，控制灌溉 CI 表现如何？")

    assert query.startswith("ＣＩ模式在保证节水的前提下")
    assert "６４．２７％～７３．６５％" in query
    assert "熵权ＴＯＰＳＩＳ" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_i4_i6_hints() -> None:
    query = expand_retrieval_query("黄淮海冬小麦-夏玉米轮作研究中，I-4 相比雨养和 I-6 如何？")

    assert query.startswith("Compared to R treatment I-4")
    assert "comparable yields to I-6" in query
    assert "90.53 irrigation water productivity" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_shallow_groundwater_maize_hints() -> None:
    query = expand_retrieval_query("浅层地下水绿洲滴灌玉米研究中，高初始土壤矿质氮有什么影响？")

    assert query.startswith("Simulations revealed high NISM levels")
    assert "shallow groundwater drip irrigated maize oasis farmland" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_nansi_f2w2_hints() -> None:
    query = expand_retrieval_query("南四湖流域小麦研究中，F2W2 处理相对 CK 有什么影响？")

    assert query.startswith("Feng 2025 Nansi Lake basin F2W2")
    assert "29.17 27.13" in query
    assert "11.38 17.80" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_nansi_f2w1_f1w2_hints() -> None:
    query = expand_retrieval_query("南四湖流域小麦研究中，F2W1 和 F1W2 相对 CK 怎么样？")

    assert query.startswith("Feng 2025 Nansi Lake basin F2W1 F1W2")
    assert "F2W1 reduced 8.90 41.67" in query
    assert "F1W2 reduced 12.50 15.99" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_hubei_total_n_loss_hints() -> None:
    query = expand_retrieval_query("单季稻、早稻和晚稻的平均总氮损失分别是多少？")

    assert query.startswith("Li 2025 Hubei regional WHCNS rice")
    assert "77.2 65.6 81.5" in query
    assert "33.6 31.5 40.8" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_hubei_spatial_driver_hints() -> None:
    query = expand_retrieval_query("湖北省水稻区域模拟研究中，各类氮损失的空间差异受什么影响？")

    assert query.startswith("Li 2025 Hubei regional WHCNS spatial difference")
    assert "solar radiation temperature soil clay content" in query
    assert "soil total N organic matter poor aeration" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_ws_w4_hints() -> None:
    query = expand_retrieval_query("冬小麦-大豆系统研究中，WS 系统和 W4 对 ETc 有什么影响？")

    assert query.startswith("Wu 2024 W4 treatment saved")
    assert "23.6 29.1" in query
    assert "97.9 98.2" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_rice_nue_hints() -> None:
    query = expand_retrieval_query("1978-2019 年中国单季稻 NUE 趋势和 2050 目标是什么？")

    assert query.startswith("Ju 2025 The national NUE")
    assert "0.048 per 10 years" in query
    assert "target of 0.6 by 2050" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_bo_2025_framework_hints() -> None:
    query = expand_retrieval_query("2025 年区域稻作灌溉优化框架研究解释了多少试验变异？")

    assert query.startswith("Bo 2025 process-based modeling framework")
    assert "52 60 37 94" in query
    assert "35 85 percent" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_late_rice_hints() -> None:
    query = expand_retrieval_query("湖北省晚稻氮损失为什么比单季稻和早稻更严重？")

    assert query.startswith("Li 2025 Hubei regional WHCNS late season rice")
    assert "77.2 65.6 81.5" in query
    assert "33.6 31.5 40.8" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_adds_w4_i4_synthesis_hints() -> None:
    query = expand_retrieval_query("黄淮海平原小麦轮作系统的灌溉优化研究对 W4/I-4 有什么共同结论？")

    assert query.startswith("Wu 2023 I-4 treatment achieved")
    assert "W4 significantly reduced field water losses" in query
    assert "R treatment led to severe yield losses" in query
    assert "中文问题" not in query


def test_expand_retrieval_query_leaves_non_domain_query_unchanged() -> None:
    assert expand_retrieval_query("What is WHCNS?") == "What is WHCNS?"


def test_build_messages_with_history_keeps_current_query_last() -> None:
    messages = build_messages(
        "那侧向渗漏贡献多少？",
        [_result(1)],
        max_context_chars=500,
        history=[DialogueTurn(role="assistant", content="前文回答")],
    )

    assert [m.role for m in messages] == ["system", "user", "user"]
    assert "最近对话" in messages[1].content
    assert messages[-1].content == "那侧向渗漏贡献多少？"
