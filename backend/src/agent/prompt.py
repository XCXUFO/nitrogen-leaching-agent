from __future__ import annotations

from src.llm.base import ChatMessage
from src.rag.retriever import RetrievalResult

SYSTEM_PROMPT_WITH_CONTEXT = """\
你是面向中国农业研究者的氮素淋失风险问答助手。
回答必须基于下面给出的参考资料。如果资料不足以回答，请明确说明"资料中未涉及"。
回答时请用 [1][2] 形式标注你引用的资料编号，与下方资料编号对应。

【参考资料】
{context}
"""

SYSTEM_PROMPT_NO_CONTEXT = """\
你是面向中国农业研究者的氮素淋失风险问答助手。
当前未检索到相关参考资料。请基于通用知识谨慎回答，
并在回答开头明确告知用户"以下回答未引用本知识库资料"。
"""


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


def build_messages(
    query: str,
    retrieved: list[RetrievalResult],
    *,
    max_context_chars: int,
) -> list[ChatMessage]:
    if retrieved:
        context = format_context(retrieved, max_context_chars)
        system = SYSTEM_PROMPT_WITH_CONTEXT.format(context=context)
    else:
        system = SYSTEM_PROMPT_NO_CONTEXT

    return [
        ChatMessage(role="system", content=system),
        ChatMessage(role="user", content=query),
    ]
