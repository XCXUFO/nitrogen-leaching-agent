"""Read a bounded amount of a paper PDF and suggest registration fields."""
from __future__ import annotations

import json
import re
import unicodedata
from difflib import SequenceMatcher
from pathlib import Path
from typing import Literal

import fitz
from pydantic import BaseModel, Field

from src.llm.base import ChatMessage, LLMClient

MAX_PAGES = 3
MAX_TEXT_CHARS = 12000


class SuggestedAuthor(BaseModel):
    name: str = Field(max_length=200)
    kind: Literal["person", "institution"] = "person"


class SuggestedFields(BaseModel):
    title: str = Field(default="", max_length=500)
    authors: list[SuggestedAuthor] = Field(default_factory=list, max_length=100)
    publication_type: Literal["期刊论文", "会议论文", "预印本", "其他学术论文"] | None = None
    venue: str = Field(default="", max_length=500)
    year: int | None = Field(default=None, ge=1000, le=3000)
    language: Literal["中文", "英文", "其他"] | None = None
    language_note: str = Field(default="", max_length=100)
    doi: str = Field(default="", max_length=300)
    source_url: str = Field(default="", max_length=2000)
    source_note: str = Field(default="", max_length=2000)
    abstract: str = Field(default="", max_length=20000)


def read_pdf_for_extraction(path: Path) -> tuple[str, int]:
    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("PDF 已加密，无法解析。")
        pages = min(pdf.page_count, MAX_PAGES)
        chunks = []
        pages_read = 0
        for number in range(pages):
            pages_read += 1
            text = pdf.load_page(number).get_text("text", sort=True).strip()
            if text:
                chunks.append(f"[第 {number + 1} 页]\n{text}")
            if sum(map(len, chunks)) >= MAX_TEXT_CHARS:
                break
    result = "\n\n".join(chunks)[:MAX_TEXT_CHARS]
    if len(result.strip()) < 40:
        raise ValueError("PDF 未提取到足够的可选中文字；请手动填写扫描版文献。")
    return result, pages_read


DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s<>\"']+", re.I)
YEAR_PATTERN = re.compile(r"(?<![A-Za-z0-9])(?:19|20)\d{2}(?![A-Za-z0-9])")


def _clean(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).split()).strip(" -·•\t")


def _valid_title(value: str) -> bool:
    return len(value) >= 12 and len(value) <= 500 and not re.search(
        r"^(?:untitled|microsoft word|article|pdf|document|research article|contents lists|※农业科学)", value, re.I
    ) and "网络首发论文" not in value


def _layout_title(page: fitz.Page) -> str:
    """Find the prominent multi-line article title, ignoring short journal mastheads."""
    lines: list[tuple[float, float, str]] = []
    candidates: list[tuple[float, str]] = []
    for block in page.get_text("dict")["blocks"]:
        block_lines = []
        block_sizes = []
        for line in block.get("lines", []):
            value = _clean("".join(span["text"] for span in line["spans"]))
            if value and line["bbox"][1] < page.rect.height * 0.65:
                size = max(span["size"] for span in line["spans"])
                lines.append((line["bbox"][1], size, value))
                block_lines.append(value)
                block_sizes.append(size)
        if block_lines:
            combined = " ".join(block_lines)
            size = max(block_sizes)
            if size >= 11 and _valid_title(combined):
                candidates.append((size ** 4 * min(len(combined), 110) ** 0.5, combined))
    lines.sort(key=lambda item: item[0])
    for index, (y, size, value) in enumerate(lines):
        if size < 11 or len(value) < 8:
            continue
        combined = value
        previous_y = y
        for next_y, next_size, next_value in lines[index + 1:index + 5]:
            if next_y - previous_y > size * 1.8 or abs(next_size - size) > 1.1:
                break
            combined += " " + next_value
            previous_y = next_y
        if _valid_title(combined):
            candidates.append((size ** 4 * min(len(combined), 110) ** 0.5, combined))
    return max(candidates, default=(0, ""))[1]


def _layout_authors(page: fitz.Page, title: str, metadata_author: str) -> list[SuggestedAuthor]:
    if not title:
        return []
    blocks = page.get_text("blocks")
    normalize = lambda value: re.sub(r"\W", "", _clean(value)).casefold()
    title_key = normalize(title)
    matches = [(SequenceMatcher(None, title_key, normalize(block[4])).ratio(), block)
               for block in blocks if block[1] < page.rect.height * 0.65 and block[6] == 0]
    score, title_block = max(matches, default=(0.0, None), key=lambda item: item[0])
    if score < 0.68 or title_block is None:
        return []
    nearby = sorted((block for block in blocks
                     if title_block[3] - 1 <= block[1] <= title_block[3] + 85
                     and block[6] == 0), key=lambda block: block[1])
    detailed_blocks = page.get_text("dict")["blocks"]
    for block in nearby:
        detailed = next((item for item in detailed_blocks
                         if abs(item["bbox"][0] - block[0]) < 2 and abs(item["bbox"][1] - block[1]) < 2
                         and item.get("lines")), None)
        raw = block[4]
        if detailed:
            spans = [span for line in detailed["lines"][:3] for span in line["spans"]]
            main_size = max((span["size"] for span in spans), default=0)
            raw = "\n".join("".join(span["text"] for span in line["spans"]
                                     if span["size"] >= main_size * 0.78)
                            for line in detailed["lines"][:3])
        lines = []
        for line in raw.splitlines():
            if re.search(r"\b(?:university|college|school|department|institute|abstract|keywords|doi|cite this article)\b|大学|学院|研究所|摘要|关键词|引用格式", line, re.I):
                break
            lines.append(line)
            if len(lines) >= 3:
                break
        value = _clean(" ".join(lines))
        if not value or len(value) > 320 or re.search(r"https?://|@|\b(?:vol|issn|journal)\b", value, re.I):
            continue
        if not re.search(r"[,，、;&；]|\band\b", value, re.I):
            continue
        parts = re.split(r"[,，、;&；]|\band\b", value, flags=re.I)
        authors: list[SuggestedAuthor] = []
        for part in parts:
            name = _clean(re.sub(r"[\d*#⁎†‡§]+", "", part))
            name = re.sub(r"(?<=[\u4e00-\u9fff])\s+(?=[\u4e00-\u9fff])", "", name)
            if metadata_author and name.casefold() == _clean(metadata_author).casefold() + "a":
                name = _clean(metadata_author)
            if re.fullmatch(r"[\u4e00-\u9fff·]{2,8}", name) or re.fullmatch(r"(?:[A-Z][A-Za-z'-]*\.?\s+){1,3}[A-Z][A-Za-z'-]*", name):
                authors.append(SuggestedAuthor(name=name))
        if 2 <= len(authors) <= 40:
            return authors
    return []


def local_suggestions(path: Path) -> SuggestedFields:
    """Extract conservative bibliographic fields when the online model is unavailable."""
    with fitz.open(path) as pdf:
        page = pdf[0]
        metadata = pdf.metadata or {}
        first_page = page.get_text("text", sort=True)
        title = _clean(metadata.get("title") or "")
        if not _valid_title(title):
            title = _layout_title(page)
        subject = _clean(metadata.get("subject") or "")
        doi_text = re.sub(r"\s*([/.])\s*", r"\1", unicodedata.normalize("NFKC", first_page[:7000]))
        doi_match = DOI_PATTERN.search(subject) or DOI_PATTERN.search(doi_text)
        doi = doi_match.group(0).rstrip(".,;:)）]") if doi_match else ""
        normalized_first = unicodedata.normalize("NFKC", first_page)
        year_match = YEAR_PATTERN.search(normalized_first[:1200])
        if not year_match:
            published = re.search(r"\bPublished\s*:\s*[^\n]{0,60}?((?:19|20)\d{2})", normalized_first[:6000], re.I)
            year_match = published.group(1) if published else None
        year = int(year_match if isinstance(year_match, str) else year_match.group(0)) if year_match else None
        labeled_title = re.search(r"(?:^|\n)\s*题目\s*[:：]\s*(.{12,300})", first_page)
        if labeled_title:
            title = _clean(labeled_title.group(1))
        venue = ""
        if subject:
            candidate = subject.split(",", 1)[0].strip()
            if 5 <= len(candidate) <= 150 and not candidate.lower().startswith("doi:"):
                venue = candidate
        if not venue:
            for line in first_page[:900].splitlines():
                candidate = _clean(line)
                if re.match(r"^(?:Journal of|[\w ]+ Journal )", candidate, re.I) and len(candidate) < 110:
                    venue = candidate
                    break
        language = "中文" if len(re.findall(r"[\u4e00-\u9fff]", first_page[:2500])) > 30 else "英文"
        abstract = ""
        blocks = page.get_text("blocks")
        heading = re.compile(r"^\s*(?:A\s*B\s*S\s*T\s*R\s*A\s*C\s*T\b|摘\s*要)\s*[:：.\-—]?\s*", re.I)
        next_section = re.compile(r"(?:^|\n)\s*(?:Keywords?\b|关键词|(?:\d+[.)]?\s*)?(?:Introduction\b|引言|绪论))", re.I)
        marker = next((block for block in blocks if block[6] == 0 and heading.match(block[4])), None)
        if marker:
            # Some PDFs put the heading and paragraph in the same text block.
            # Only look below a standalone heading, never skip the inline abstract.
            content = heading.sub("", marker[4], count=1).strip()
            if not content:
                candidates = [block for block in blocks if block[6] == 0 and block[1] >= marker[3] - 2
                              and block[1] < page.rect.height * 0.82
                              and abs(block[0] - marker[0]) < 25
                              and block[4].strip()]
                if candidates:
                    content = min(candidates, key=lambda block: block[1])[4]
            content = next_section.split(content, maxsplit=1)[0]
            if len(content.strip()) >= 40:
                abstract = _clean(content)[:5000]
        labeled_authors = re.search(r"(?:^|\n)\s*作者\s*[:：]\s*(.{4,300})", first_page)
        authors = []
        if labeled_authors:
            names = re.split(r"[，,、；;]", labeled_authors.group(1))
            authors = [SuggestedAuthor(name=_clean(name)) for name in names if 2 <= len(_clean(name)) <= 30]
        if not authors:
            authors = _layout_authors(page, title, metadata.get("author") or "")
        metadata_names = re.split(r"[,，、；;]|\band\b", metadata.get("author") or "", flags=re.I)
        if len(metadata_names) > 1:
            metadata_authors = [SuggestedAuthor(name=_clean(name)) for name in metadata_names
                                if re.fullmatch(r"[\u4e00-\u9fff·]{2,8}|(?:[A-Z][A-Za-z'-]*\.?\s+){1,3}[A-Z][A-Za-z'-]*", _clean(name))]
            if len(metadata_authors) == len(metadata_names) and len(metadata_authors) > len(authors):
                authors = metadata_authors
        return SuggestedFields(
            title=title, publication_type="期刊论文" if venue else None,
            authors=authors, venue=venue, year=year, language=language, doi=doi, abstract=abstract,
        )


async def suggest_fields(text: str, llm: LLMClient) -> SuggestedFields:
    chat = getattr(llm, "chat_json", llm.chat)
    result = await chat([
        ChatMessage(role="system", content=(
            "你是学术文献编目助手。仅根据提供的 PDF 文字提取字段，返回一个 JSON 对象，不要 Markdown。"
            "字段：title、authors（按署名顺序，元素含 name 和 kind=person/institution）、"
            "publication_type（期刊论文/会议论文/预印本/其他学术论文之一或 null）、venue、"
            "year（四位数字或 null）、language（中文/英文/其他或 null）、language_note、"
            "doi（规范 DOI，不含链接前缀）、source_url、source_note、abstract。"
            "不确定时用空字符串、空数组或 null；绝不从文件名猜测，也不要编造作者、年份或来源。"
            "摘要若无法确认原文完整段落则留空。只返回 PDF 明确支持的信息。"
        )),
        ChatMessage(role="user", content=text),
    ], temperature=0, max_tokens=1800)
    content = result.content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", content, re.S | re.I)
    if fenced:
        content = fenced.group(1)
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        first, last = content.find("{"), content.rfind("}")
        if first < 0 or last <= first:
            raise
        data = json.loads(content[first:last + 1])
    if not isinstance(data, dict):
        raise ValueError("AI response is not a field object")
    for key in ("title", "venue", "language_note", "doi", "source_url", "source_note", "abstract"):
        if data.get(key) is None:
            data[key] = ""
    if data.get("authors") is None:
        data["authors"] = []
    if isinstance(data.get("authors"), list):
        data["authors"] = [{"name": author, "kind": "person"} if isinstance(author, str) else author
                           for author in data["authors"]]
    if isinstance(data.get("doi"), str):
        data["doi"] = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", data["doi"].strip(), flags=re.I)
    data["language"] = {"Chinese": "中文", "English": "英文", "Other": "其他"}.get(data.get("language"), data.get("language"))
    return SuggestedFields.model_validate(data)
