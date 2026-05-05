from __future__ import annotations

import re
from dataclasses import dataclass

ChunkMetaValue = str | int | float | bool

_BOUNDARY_CHARS = "。！？；.!?;\n\r\t "
_PARAGRAPH_BREAK_RE = re.compile(r"\n{2,}")
_RESERVED_METADATA_KEYS = {
    "source",
    "document_id",
    "chunk_index",
    "char_start",
    "char_end",
}


@dataclass(frozen=True, slots=True)
class Chunk:
    """RAG pipeline internal chunk."""

    chunk_id: str
    document_id: str
    text: str
    metadata: dict[str, ChunkMetaValue]


@dataclass(frozen=True, slots=True)
class _Paragraph:
    start: int
    end: int


def chunk_text(
    text: str,
    document_id: str,
    source: str,
    *,
    target_size: int = 300,
    max_size: int = 450,
    overlap: int = 60,
    base_metadata: dict[str, ChunkMetaValue] | None = None,
) -> list[Chunk]:
    """Split plain text into chunks with original-text offsets."""

    _validate_params(target_size=target_size, max_size=max_size, overlap=overlap)
    metadata_seed = _validate_base_metadata(base_metadata)

    paragraphs = _find_paragraphs(text)
    if not paragraphs:
        return []

    spans: list[tuple[int, int]] = []
    buffer: list[int] = []
    buffer_len = 0

    for index, paragraph in enumerate(paragraphs):
        next_start = paragraphs[index + 1].start if index + 1 < len(paragraphs) else None
        paragraph_len = paragraph.end - paragraph.start

        if paragraph_len > max_size:
            _flush_buffer(buffer, paragraphs, spans)
            buffer = []
            buffer_len = 0
            spans.extend(
                _hard_split_paragraph(
                    text=text,
                    paragraph=paragraph,
                    next_start=next_start,
                    max_size=max_size,
                    overlap=overlap,
                )
            )
            continue

        projected_start = paragraphs[buffer[0]].start if buffer else paragraph.start
        projected_end = next_start if next_start is not None else paragraph.end
        if buffer and projected_end - projected_start > max_size:
            _flush_buffer(buffer, paragraphs, spans)
            buffer = []
            buffer_len = 0

        buffer.append(index)
        current_end = next_start if next_start is not None else paragraph.end
        buffer_len = current_end - paragraphs[buffer[0]].start
        if buffer_len >= target_size:
            _flush_buffer(buffer, paragraphs, spans)
            buffer = []
            buffer_len = 0

    _flush_buffer(buffer, paragraphs, spans)

    chunks: list[Chunk] = []
    for chunk_index, (start, end) in enumerate(spans):
        metadata = {
            **metadata_seed,
            "source": source,
            "document_id": document_id,
            "chunk_index": chunk_index,
            "char_start": start,
            "char_end": end,
        }
        chunks.append(
            Chunk(
                chunk_id=f"{document_id}::{chunk_index:04d}",
                document_id=document_id,
                text=text[start:end],
                metadata=metadata,
            )
        )
    return chunks


def _validate_params(*, target_size: int, max_size: int, overlap: int) -> None:
    if target_size <= 0:
        raise ValueError("target_size must be > 0")
    if target_size > max_size:
        raise ValueError("target_size must be <= max_size")
    if overlap < 0:
        raise ValueError("overlap must be >= 0")
    if overlap >= max_size:
        raise ValueError("overlap must be < max_size")


def _validate_base_metadata(
    base_metadata: dict[str, ChunkMetaValue] | None,
) -> dict[str, ChunkMetaValue]:
    if base_metadata is None:
        return {}

    conflicts = sorted(_RESERVED_METADATA_KEYS & base_metadata.keys())
    if conflicts:
        raise ValueError(
            "base_metadata cannot contain reserved keys: "
            + ", ".join(conflicts)
        )

    validated: dict[str, ChunkMetaValue] = {}
    for key, value in base_metadata.items():
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError(
                "base_metadata values must be scalar "
                f"(str | int | float | bool); got {type(value).__name__} for {key!r}"
            )
        validated[key] = value
    return validated


def _find_paragraphs(text: str) -> list[_Paragraph]:
    doc_start = _first_non_whitespace_index(text)
    if doc_start is None:
        return []

    doc_end = _last_non_whitespace_index(text) + 1
    paragraphs: list[_Paragraph] = []
    cursor = doc_start

    for match in _PARAGRAPH_BREAK_RE.finditer(text, doc_start, doc_end):
        _append_paragraph(text, cursor, match.start(), paragraphs)
        cursor = match.end()

    _append_paragraph(text, cursor, doc_end, paragraphs)
    return paragraphs


def _append_paragraph(
    text: str,
    segment_start: int,
    segment_end: int,
    paragraphs: list[_Paragraph],
) -> None:
    segment = text[segment_start:segment_end]
    if not segment.strip():
        return

    leading = len(segment) - len(segment.lstrip())
    trailing = len(segment) - len(segment.rstrip())
    start = segment_start + leading
    end = segment_end - trailing
    if start < end:
        paragraphs.append(_Paragraph(start=start, end=end))


def _flush_buffer(
    buffer: list[int],
    paragraphs: list[_Paragraph],
    spans: list[tuple[int, int]],
) -> None:
    if not buffer:
        return

    first = paragraphs[buffer[0]]
    last_index = buffer[-1]
    last = paragraphs[last_index]
    next_start = paragraphs[last_index + 1].start if last_index + 1 < len(paragraphs) else None
    end = next_start if next_start is not None else last.end
    spans.append((first.start, end))


def _hard_split_paragraph(
    *,
    text: str,
    paragraph: _Paragraph,
    next_start: int | None,
    max_size: int,
    overlap: int,
) -> list[tuple[int, int]]:
    paragraph_text = text[paragraph.start:paragraph.end]
    spans: list[tuple[int, int]] = []
    pos = 0
    lookback = int(max_size * 0.1)

    while pos < len(paragraph_text):
        raw_end = min(pos + max_size, len(paragraph_text))
        end = raw_end
        if raw_end < len(paragraph_text):
            end = _backtrack_to_boundary(
                paragraph_text=paragraph_text,
                start=pos,
                end=raw_end,
                lookback=lookback,
            )
        if end <= pos:
            end = raw_end

        start_offset = paragraph.start + pos
        end_offset = paragraph.start + end
        spans.append((start_offset, end_offset))
        if end >= len(paragraph_text):
            break
        pos = end - overlap

    if next_start is not None and spans:
        last_start, _ = spans[-1]
        spans[-1] = (last_start, next_start)

    return spans


def _backtrack_to_boundary(
    *,
    paragraph_text: str,
    start: int,
    end: int,
    lookback: int,
) -> int:
    lower_bound = max(start + 1, end - lookback)
    for boundary_index in range(end - 1, lower_bound - 1, -1):
        if paragraph_text[boundary_index] in _BOUNDARY_CHARS:
            return boundary_index + 1
    return end


def _first_non_whitespace_index(text: str) -> int | None:
    for index, char in enumerate(text):
        if not char.isspace():
            return index
    return None


def _last_non_whitespace_index(text: str) -> int:
    for index in range(len(text) - 1, -1, -1):
        if not text[index].isspace():
            return index
    raise ValueError("text does not contain non-whitespace characters")
