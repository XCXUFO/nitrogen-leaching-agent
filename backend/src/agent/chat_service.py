from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from src.agent.prompt import DialogueTurn, build_messages, build_retrieval_query
from src.agent.curated_evidence import excerpts
from src.agent.composition import MECHANISM_SYSTEM, PEAK_MECHANISM_SYSTEM, MechanismClaim, MechanismEvidenceError, is_event_mechanism_source, is_mechanism_source, supports_crop, validate_claims
from src.rag.reference_filter import is_reference_chunk
from src.rag.source_labels import article_label
from src.llm.base import ChatMessage, ChatUsage, LLMClient
from src.rag.retriever import RetrievalResult, Retriever

_SNIPPET_LEN = 400


class RAGQueryError(RuntimeError):
    """Raised when retrieval fails before prompt construction."""


class Citation(BaseModel):
    index: int = Field(..., ge=1)
    chunk_id: str
    source: str
    score: float
    snippet: str
    title: str | None = None
    author_hint: str | None = None
    year: str | None = None
    document_id: str | None = None
    document_available: bool = False


@dataclass(frozen=True, slots=True)
class ChatServiceResult:
    answer: str
    citations: list[Citation]
    usage: ChatUsage
    retrieved_count: int
    model: str
    claims: list[MechanismClaim] = field(default_factory=list)


class ChatService:
    def __init__(
        self,
        retriever: Retriever,
        llm: LLMClient,
        *,
        top_k: int,
        max_context_chars: int,
        temperature: float,
    ) -> None:
        self._retriever = retriever
        self._llm = llm
        self._top_k = top_k
        self._max_context_chars = max_context_chars
        self._temperature = temperature

    async def answer(
        self,
        query: str,
        k: int | None = None,
        *,
        history: list[DialogueTurn] | None = None,
    ) -> ChatServiceResult:
        effective_k = k if k is not None else self._top_k
        retrieval_query = build_retrieval_query(query, history or [])
        try:
            retrieved = await asyncio.to_thread(
                self._retriever.retrieve,
                retrieval_query,
                effective_k,
            )
        except Exception as exc:
            raise RAGQueryError("retriever query failed") from exc

        usable = [item for item in retrieved if not is_reference_chunk(item.document)]
        messages = build_messages(
            query,
            usable,
            max_context_chars=self._max_context_chars,
            history=history,
        )
        chat = await self._llm.chat(messages, temperature=self._temperature)
        supplied = {int(index) for index in re.findall(r"^\[(\d+)\] \(来源:", messages[0].content, re.M)}
        answer, citations, _ = normalize_citations(chat.content, [item for item in _make_citations(usable) if item.index in supplied])
        return ChatServiceResult(
            answer=answer,
            citations=citations,
            usage=chat.usage,
            retrieved_count=len(retrieved),
            model=chat.model,
        )

    async def explain_mechanisms(self, query: str, *, crop: str | None = None, k: int | None = None,
                                 purpose: str = "general") -> ChatServiceResult:
        """Use bounded source excerpts or grounded generation; file values never go to the LLM."""
        if crop == "玉米" and purpose in {"peak", "maize_factors"}:
            return _curated_maize_evidence(purpose)
        try:
            recalled = await asyncio.to_thread(self._retriever.retrieve,
                                              build_retrieval_query(query, []), max(k or self._top_k, 12) if purpose == "peak" else k or self._top_k)
        except Exception as exc:
            raise RAGQueryError("retriever query failed") from exc
        eligible = [item for item in recalled
                    if (is_event_mechanism_source(item.document) if purpose == "peak" else is_mechanism_source(item.document))
                    and supports_crop(crop, item.document, str(item.metadata.get("source", "")))]
        used, blocks, budget = [], [], self._max_context_chars
        for item in eligible:
            block = f"[{len(used) + 1}]\n{item.document}\n"
            if len(block) > budget:
                continue
            used.append(item)
            blocks.append(block)
            budget -= len(block)
        if not used:
            raise MechanismEvidenceError("mechanism_evidence_missing")
        messages = [
            ChatMessage(role="system", content=PEAK_MECHANISM_SYSTEM if purpose == "peak" else MECHANISM_SYSTEM),
            ChatMessage(role="user", content=f"作物：{crop or '未指定'}\n问题：{query}\n参考片段：\n" + "\n".join(blocks)),
        ]
        chat = await self._llm.chat(messages, temperature=self._temperature)
        usage = chat.usage
        try:
            claims = validate_claims(chat.content, [item.document for item in used], purpose=purpose)
        except MechanismEvidenceError as exc:
            if exc.code != "mechanism_output_invalid":
                raise
            # One bounded retry for malformed structured output. Never relax
            # quote, citation, crop, or scope validation to manufacture evidence.
            chat = await self._llm.chat([*messages, ChatMessage(role="user", content=
                '上次回答未通过 JSON 格式校验。请仅返回 {"claims":[{"text":"中文结论",'
                '"citation_index":1,"supporting_quote":"对应片段的连续原文"}]}，最多4条；'
                '无依据则返回 {"claims":[]}。不要输出解释、思考过程或代码围栏。')], temperature=0)
            usage = ChatUsage(prompt_tokens=usage.prompt_tokens + chat.usage.prompt_tokens,
                              completion_tokens=usage.completion_tokens + chat.usage.completion_tokens,
                              total_tokens=usage.total_tokens + chat.usage.total_tokens)
            claims = validate_claims(chat.content, [item.document for item in used], purpose=purpose)
        by_index: dict[int, list[str]] = {}
        for claim in claims:
            by_index.setdefault(claim.citation_index, []).append(claim.supporting_quote)
        citations = [Citation(index=i, chunk_id=used[i-1].chunk_id, source=str(used[i-1].metadata.get("source", "unknown")),
                              score=used[i-1].score, snippet="\n…\n".join(dict.fromkeys(by_index[i])))
                     for i in sorted(by_index)]
        citations = [citation.model_copy(update=dict(zip(("title", "author_hint"), article_label(citation.source))))
                     for citation in citations]
        return ChatServiceResult(answer="\n".join(f"{claim.text} [{claim.citation_index}]" for claim in claims),
                                 citations=citations, usage=usage, retrieved_count=len(recalled), model=chat.model, claims=claims)


def normalize_citations(answer: str, citations: list[Citation]) -> tuple[str, list[Citation], dict[int, int]]:
    """Keep only referenced evidence, numbered by first appearance in the answer."""
    by_index = {item.index: item for item in citations}
    mapping: dict[int, int] = {}
    sources: dict[str, Citation] = {}
    def replace(match: re.Match) -> str:
        if match.group(1):  # Preserve examples and numeric arrays inside Markdown code.
            return match.group(1)
        old = int(match.group(2))
        if old not in by_index:
            return ""
        item = by_index[old]
        key = item.document_id or item.source.replace("\\", "/") or item.chunk_id
        if key not in sources:
            sources[key] = item.model_copy(update={"index": len(sources) + 1})
        elif old not in mapping and item.snippet not in sources[key].snippet:
            sources[key].snippet += "\n…\n" + item.snippet
        mapping[old] = sources[key].index
        return f"[{mapping[old]}]"
    answer = re.sub(r"(```[\s\S]*?```|`[^`\n]*`)|\[(\d+)\](?!\()", replace, answer)
    return answer, list(sources.values()), mapping


def _make_citations(retrieved: list[RetrievalResult]) -> list[Citation]:
    return [
        Citation(
            index=index,
            chunk_id=result.chunk_id,
            source=str(result.metadata.get("source", "unknown")),
            score=result.score,
            snippet=result.document[:_SNIPPET_LEN],
            title=article_label(str(result.metadata.get("source", "unknown")))[0],
            author_hint=article_label(str(result.metadata.get("source", "unknown")))[1],
        )
        for index, result in enumerate(retrieved, start=1)
    ]


def _curated_maize_evidence(purpose: str) -> ChatServiceResult:
    cards = excerpts()["modes"][purpose]
    indices: dict[str, int] = {}
    sources: dict[str, dict] = {}
    quotes: dict[str, list[str]] = {}
    claims = []
    for card in cards:
        key = card["chunk_id"]
        if key not in indices:
            indices[key] = len(indices) + 1
            sources[key] = card
            quotes[key] = []
        quotes[key].append(card["supporting_quote"])
        claims.append(MechanismClaim(text=card["text"], citation_index=indices[key],
                                     supporting_quote=card["supporting_quote"]))
    citations = [Citation(index=index, chunk_id=key, source=sources[key]["source"], score=0.0,
                          snippet="\n…\n".join(dict.fromkeys(quotes[key])),
                          title=article_label(sources[key]["source"])[0],
                          author_hint=article_label(sources[key]["source"])[1])
                 for key, index in indices.items()]
    answer = "\n".join(f"{claim.text} [{claim.citation_index}]" for claim in claims)
    if purpose == "maize_factors":
        answer += "\n\n以上是所引论文场景内的证据；模型校准或参数误差属于模拟结果局限，不是实际淋失的环境驱动因素。"
    return ChatServiceResult(answer=answer, citations=citations,
                             usage=ChatUsage(prompt_tokens=0, completion_tokens=0, total_tokens=0),
                             retrieved_count=0, model="curated-excerpts-v1", claims=claims)
