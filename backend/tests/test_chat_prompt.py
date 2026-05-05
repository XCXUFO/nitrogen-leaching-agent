from src.agent.prompt import build_messages, format_context
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
    assert messages[1].content == "氮素淋失受什么影响？"


def test_build_messages_no_retrieved_uses_no_context_prompt() -> None:
    messages = build_messages("氮素淋失受什么影响？", [], max_context_chars=500)

    assert "未检索到相关参考资料" in messages[0].content
    assert messages[1].content == "氮素淋失受什么影响？"


def test_build_messages_returns_two_messages() -> None:
    assert len(build_messages("q", [_result(1)], max_context_chars=500)) == 2
