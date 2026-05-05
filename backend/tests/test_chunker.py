import pytest

from src.rag import Chunk, chunk_text


def test_empty_text_returns_empty_list() -> None:
    assert chunk_text("", "doc-1", "/tmp/doc.txt") == []
    assert chunk_text("   \n\n  \t", "doc-1", "/tmp/doc.txt") == []


def test_short_text_returns_single_chunk() -> None:
    text = "  氮素淋失风险分析。  "

    chunks = chunk_text(text, "paper-001", "/tmp/paper.txt")

    assert len(chunks) == 1
    chunk = chunks[0]
    assert isinstance(chunk, Chunk)
    assert chunk.chunk_id == "paper-001::0000"
    assert chunk.text == "氮素淋失风险分析。"
    assert chunk.metadata["char_start"] == 2
    assert chunk.metadata["char_end"] == len(text) - 2


def test_paragraphs_merged_until_target_size() -> None:
    text = "甲甲甲\n\n乙乙乙\n\n丙丙丙"

    chunks = chunk_text(
        text,
        "paper-001",
        "/tmp/paper.txt",
        target_size=7,
        max_size=10,
        overlap=2,
    )

    assert len(chunks) == 2
    assert chunks[0].text == "甲甲甲\n\n乙乙乙\n\n"
    assert chunks[1].text == "丙丙丙"
    assert len(chunks[0].text) >= 7
    assert len(chunks[0].text) <= 10
    assert chunks[0].metadata["char_end"] == chunks[1].metadata["char_start"]


def test_long_paragraph_hard_split_with_overlap() -> None:
    text = "甲" * 25

    chunks = chunk_text(
        text,
        "paper-001",
        "/tmp/paper.txt",
        target_size=8,
        max_size=10,
        overlap=3,
    )

    assert len(chunks) == 4
    for previous, current in zip(chunks, chunks[1:]):
        assert (
            current.metadata["char_start"]
            == previous.metadata["char_end"] - 3
        )
        overlap = previous.text[-3:]
        assert overlap == current.text[:3]


def test_chunk_index_is_monotonic_and_dense() -> None:
    text = "甲甲甲\n\n乙乙乙\n\n" + ("长" * 25)

    chunks = chunk_text(
        text,
        "paper-001",
        "/tmp/paper.txt",
        target_size=7,
        max_size=10,
        overlap=3,
    )

    assert [chunk.metadata["chunk_index"] for chunk in chunks] == list(range(len(chunks)))


def test_char_offsets_form_valid_intervals() -> None:
    text = " \n甲甲甲\n\n乙乙乙\n\n" + ("长" * 12) + "。" + ("长" * 12) + "  "

    chunks = chunk_text(
        text,
        "paper-001",
        "/tmp/paper.txt",
        target_size=7,
        max_size=10,
        overlap=3,
    )

    first_non_whitespace = next(index for index, char in enumerate(text) if not char.isspace())
    last_non_whitespace = max(
        index for index, char in enumerate(text) if not char.isspace()
    ) + 1

    assert chunks[0].metadata["char_start"] == first_non_whitespace
    assert chunks[-1].metadata["char_end"] == last_non_whitespace

    starts = [chunk.metadata["char_start"] for chunk in chunks]
    ends = [chunk.metadata["char_end"] for chunk in chunks]
    for chunk in chunks:
        start = chunk.metadata["char_start"]
        end = chunk.metadata["char_end"]
        assert chunk.text == text[start:end]

    assert starts == sorted(starts)
    assert ends == sorted(ends)
    assert all(left < right for left, right in zip(starts, starts[1:]))
    assert all(left <= right for left, right in zip(ends, ends[1:]))
    assert chunks[0].metadata["char_end"] == chunks[1].metadata["char_start"]
    assert (
        chunks[2].metadata["char_start"]
        == chunks[1].metadata["char_end"] - 3
    )


def test_chunk_id_format() -> None:
    text = "甲甲甲\n\n乙乙乙\n\n丙丙丙"

    chunks = chunk_text(
        text,
        "paper-001",
        "/tmp/paper.txt",
        target_size=7,
        max_size=10,
        overlap=2,
    )

    assert [chunk.chunk_id for chunk in chunks] == [
        "paper-001::0000",
        "paper-001::0001",
    ]


def test_base_metadata_passes_through() -> None:
    chunks = chunk_text(
        "甲甲甲\n\n乙乙乙",
        "paper-001",
        "/tmp/paper.txt",
        base_metadata={"title": "X", "year": 2024, "is_peer_reviewed": True},
    )

    assert len(chunks) == 1
    assert chunks[0].metadata["title"] == "X"
    assert chunks[0].metadata["year"] == 2024
    assert chunks[0].metadata["is_peer_reviewed"] is True


def test_base_metadata_with_reserved_key_raises() -> None:
    with pytest.raises(ValueError, match="chunk_index"):
        chunk_text(
            "甲甲甲",
            "paper-001",
            "/tmp/paper.txt",
            base_metadata={"chunk_index": 99},
        )


@pytest.mark.parametrize(
    ("value", "expected_type"),
    [
        (["a", "b"], "list"),
        ({"nested": 1}, "dict"),
    ],
)
def test_base_metadata_with_non_scalar_value_raises(
    value: object,
    expected_type: str,
) -> None:
    with pytest.raises(TypeError, match=expected_type):
        chunk_text(
            "甲甲甲",
            "paper-001",
            "/tmp/paper.txt",
            base_metadata={"bad": value},  # type: ignore[arg-type]
        )


def test_chinese_punctuation_boundary_backtrack() -> None:
    text = ("甲" * 18) + "。" + ("乙" * 20)

    chunks = chunk_text(
        text,
        "paper-001",
        "/tmp/paper.txt",
        target_size=8,
        max_size=20,
        overlap=2,
    )

    assert chunks[0].text.endswith("。")
    assert len(chunks[0].text) == 19
    assert chunks[1].metadata["char_start"] == chunks[0].metadata["char_end"] - 2


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"target_size": 0}, "target_size must be > 0"),
        ({"target_size": 11, "max_size": 10}, "target_size must be <= max_size"),
        ({"target_size": 10, "overlap": 10, "max_size": 10}, "overlap must be < max_size"),
        ({"overlap": -1}, "overlap must be >= 0"),
    ],
)
def test_invalid_params_raise(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        chunk_text("甲甲甲", "paper-001", "/tmp/paper.txt", **kwargs)
