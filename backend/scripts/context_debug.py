"""Context debug — dump three-stage retrieval + final prompt context per question.

Used for M1.4-c context-packing diagnostics. Given a questions YAML, run each
query through Embedder + Reranker + format_context — the same pipeline that
``/api/chat`` uses — and write one JSON per question to
``backend/var/context_debug/<runid>/<qid>.json``.

Unlike ``retrieval_debug.py`` (single stage per run), this dumps three stages
in one file so we can split failures into three diagnostic classes:

- ``embedding_recall``: snippet only, used to decide retrieval-stage miss vs
  reranker-stage miss. Depth is the ``--top-k-recall`` argument.
- ``reranked_top_n``: full document text, the audit primary surface. Depth
  is the ``--top-n`` argument.
- ``final_context``: the exact string that ``build_messages`` would assemble
  for the LLM, plus per-chunk metadata about what survived
  ``max_context_chars``.

The script does **not** call the LLM and does **not** modify the production
``/api/chat`` path. The only auto-extraction is ``source_reference_hints`` —
bracket references mentioned in the question's ``notes`` and
``expected_points``. These are comparison hints for the human, not a
verified expected-source claim. ``expected_points`` matching is left to the
human filling ``evidence_audit.md``.

Usage:
    cd backend
    uv run python scripts/context_debug.py \\
        --questions ../data/eval/mini_questions.yaml \\
        --persist-dir var/chroma \\
        --collection papers \\
        --out var/context_debug \\
        --top-k-recall 20 --top-n 5

Optional:
    --qids q02,q05,q06,q08
    --max-context-chars 4000        (default: settings.chat_max_context_chars)
    --reranker-model BAAI/...
"""
from __future__ import annotations

import argparse
import gc
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from src.agent.prompt import format_context  # noqa: E402
from src.config import settings  # noqa: E402
from src.rag import BGEEmbedder, Reranker, Retriever  # noqa: E402
from src.rag.retriever import RetrievalResult  # noqa: E402
from src.storage import ChromaStore  # noqa: E402

EMBEDDING_SNIPPET_CHARS = 200

# Notes such as "预期命中 [43] Liang 2020。证据：..." — narrow to the Author Year
# form so refuse-note bracket references (which mention papers to *avoid*
# hallucinating from) don't get pulled in.
_NOTES_HINT_PATTERN = re.compile(r"\[(\d+)\]\s*([A-Za-z]+\s*\d{4})?")

# expected_points items mention [N] inline like "[41] 长江中游稻田 SNR ..." —
# capture the bracket plus up to a short label, stopping at punctuation.
_POINT_HINT_PATTERN = re.compile(r"\[(\d+)\]\s*([^\[\]，。、\n]{0,30})")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M1.4-c context debug dumper")
    p.add_argument(
        "--questions",
        required=True,
        type=Path,
        help="path to questions YAML (e.g. data/eval/mini_questions.yaml)",
    )
    p.add_argument(
        "--persist-dir",
        required=True,
        type=Path,
        help="chroma persist dir (e.g. var/chroma)",
    )
    p.add_argument("--collection", default="papers")
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="parent dir for runid/<qid>.json output (e.g. var/context_debug)",
    )
    p.add_argument(
        "--top-k-recall",
        type=int,
        default=20,
        help="embedding recall depth (default 20)",
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=5,
        help="reranked output depth (default 5)",
    )
    p.add_argument(
        "--max-context-chars",
        type=int,
        default=settings.chat_max_context_chars,
        help=(
            "format_context character budget "
            f"(default settings.chat_max_context_chars={settings.chat_max_context_chars})"
        ),
    )
    p.add_argument(
        "--qids",
        default=None,
        help="optional comma-separated question ids to include (e.g. q02,q05)",
    )
    p.add_argument(
        "--reranker-model",
        default=None,
        help="reranker model id/path; defaults to settings.rag_reranker_model",
    )
    p.add_argument(
        "--reference-filter",
        action="store_true",
        help="drop likely bibliography/reference-list chunks before reranking",
    )
    p.add_argument(
        "--reference-filter-min-keep",
        type=int,
        default=settings.rag_reference_filter_min_keep,
        help="minimum candidates preserved after reference filtering",
    )
    p.add_argument(
        "--reference-filter-overfetch",
        type=int,
        default=settings.rag_reference_filter_overfetch,
        help="embedding recall multiplier used before reference filtering",
    )
    return p.parse_args()


def extract_source_hints(question: dict[str, Any]) -> list[str]:
    """Return all bracket-style ``[N] ...`` references mentioned in the
    question's ``notes`` and ``expected_points``.

    These are **comparison hints** for the human filling the audit, not a
    verified expected-source list:

    - For factual / concept / citation_check questions, ``notes`` usually
      names one paper after ``预期命中`` (e.g. ``[43] Liang 2020``).
    - For synthesis questions (e.g. q07), ``notes`` is narrative and the
      bracket refs live inside ``expected_points`` — typically multiple
      sources, since the answer must synthesise across papers.
    - For refuse questions, returns ``[]`` even if ``notes`` mentions
      bracket refs (those are examples of what the model must *not*
      hallucinate from, not expected hits).

    No automatic hit judgment — the user compares these strings against the
    actual sources in ``embedding_recall`` / ``reranked_top_n`` /
    ``final_context_chunks`` themselves.
    """
    if question.get("should_refuse"):
        return []

    hints: list[str] = []
    seen: set[str] = set()

    notes = question.get("notes") or ""
    if "预期命中" in notes:
        for m in _NOTES_HINT_PATTERN.finditer(notes):
            ref = m.group(1)
            label = (m.group(2) or "").strip()
            key = f"[{ref}]"
            if key in seen:
                continue
            seen.add(key)
            hints.append(f"[{ref}] {label}".strip() if label else f"[{ref}]")

    for ep in question.get("expected_points") or []:
        for m in _POINT_HINT_PATTERN.finditer(ep):
            ref = m.group(1)
            label = (m.group(2) or "").strip()
            key = f"[{ref}]"
            if key in seen:
                continue
            seen.add(key)
            hints.append(f"[{ref}] {label}".strip() if label else f"[{ref}]")

    return hints


# v1: duplicate prompt.format_context's truncation loop so we can report
# which chunks survived without parsing the formatted string back. Keep in
# sync; extract a shared helper once both surfaces stabilise. `verify_mirror`
# below guards against drift.
def compute_final_context_chunks(
    retrieved: list[RetrievalResult],
    max_chars: int,
) -> list[dict[str, Any]]:
    surviving: list[dict[str, Any]] = []
    used = 0
    for index, result in enumerate(retrieved, start=1):
        source = result.metadata.get("source", "unknown")
        block = f"[{index}] (来源: {source})\n{result.document}\n"
        if surviving and used + len(block) > max_chars:
            break
        surviving.append(
            {
                "context_index": index,
                "chunk_id": result.chunk_id,
                "source": str(source),
                "chars": len(block),
            }
        )
        used += len(block)
    return surviving


def verify_mirror(
    retrieved: list[RetrievalResult],
    surviving: list[dict[str, Any]],
    final_context: str,
) -> None:
    """Rebuild the prompt blocks from the surviving chunk list and ensure the
    join is byte-equal to format_context's actual output. Catches drift if the
    upstream format ever changes without us updating compute_final_context_chunks.
    """
    surviving_ids = {c["chunk_id"] for c in surviving}
    blocks: list[str] = []
    for index, result in enumerate(retrieved, start=1):
        if result.chunk_id not in surviving_ids:
            continue
        source = result.metadata.get("source", "unknown")
        blocks.append(f"[{index}] (来源: {source})\n{result.document}\n")
    rebuilt = "\n".join(blocks)
    if rebuilt != final_context:
        raise RuntimeError(
            "context_debug: compute_final_context_chunks drifted from "
            "prompt.format_context — update both to stay in sync."
        )


def _count_by_source(items: list[Any], get_source) -> dict[str, int]:
    counts: dict[str, int] = {}
    for it in items:
        src = get_source(it)
        key = str(src) if src is not None else "unknown"
        counts[key] = counts.get(key, 0) + 1
    return counts


def main() -> int:
    args = parse_args()

    raw = yaml.safe_load(args.questions.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "questions" not in raw:
        print(f"[fatal] {args.questions} missing 'questions' key", file=sys.stderr)
        return 2
    questions: list[dict[str, Any]] = raw["questions"]

    if args.qids:
        wanted = {q.strip() for q in args.qids.split(",") if q.strip()}
        questions = [q for q in questions if q.get("id") in wanted]
        if not questions:
            print(f"[fatal] no questions matched --qids {args.qids}", file=sys.stderr)
            return 2

    timestamp = datetime.now().strftime("%Y%m%dT%H%M%S")
    runid = f"{timestamp}-recall{args.top_k_recall}-top{args.top_n}"
    out_dir = args.out / runid
    out_dir.mkdir(parents=True, exist_ok=True)

    reranker_model = args.reranker_model or settings.rag_reranker_model

    print(f"[runid]              {runid}")
    print(f"[out]                {out_dir}")
    print(f"[top-k-recall]       {args.top_k_recall}")
    print(f"[top-n]              {args.top_n}")
    print(f"[max-context-chars]  {args.max_context_chars}")
    print(f"[chroma]             {args.persist_dir} :: {args.collection}")
    print(f"[embedding]          {settings.embedding_model}")
    print(f"[reranker]           {reranker_model}")
    print(
        "[ref-filter]         "
        f"{'on' if args.reference_filter else 'off'} "
        f"(min_keep={args.reference_filter_min_keep}, "
        f"overfetch={args.reference_filter_overfetch})"
    )
    print(f"[count]              {len(questions)} questions\n")

    embedder = BGEEmbedder(model_id=settings.embedding_model)
    store = ChromaStore(args.persist_dir, args.collection)
    retriever = Retriever(
        embedder,
        store,
        reranker=None,
        top_k_recall=args.top_k_recall,
        reference_filter_enabled=args.reference_filter,
        reference_filter_min_keep=args.reference_filter_min_keep,
        reference_filter_overfetch=args.reference_filter_overfetch,
    )

    recalled: list[tuple[dict[str, Any], list[RetrievalResult]]] = []
    for q in questions:
        qid = q.get("id", "?")
        query = q.get("query", "")
        if not query or query == "TODO":
            print(f"[skip] {qid} (empty/TODO query)")
            continue
        hits = retriever.retrieve(query, k=args.top_k_recall)
        recalled.append((q, hits))

    # Release embedding-stage models before loading the 2.2 GB reranker —
    # same memory pattern as retrieval_debug.py for CPU-only machines.
    del retriever, embedder, store
    gc.collect()

    reranker = Reranker(model_id=reranker_model)

    for q, embedding_hits in recalled:
        qid = q.get("id", "?")
        query = q.get("query", "")

        reranked = reranker.rerank(query, list(embedding_hits))[: args.top_n]

        final_context = format_context(reranked, max_chars=args.max_context_chars)
        final_chunks = compute_final_context_chunks(reranked, args.max_context_chars)
        verify_mirror(reranked, final_chunks, final_context)

        record: dict[str, Any] = {
            "runid": runid,
            "qid": qid,
            "category": q.get("category"),
            "should_refuse": q.get("should_refuse", False),
            "query": query,
            "source_reference_hints": extract_source_hints(q),
            "settings": {
                "top_k_recall": args.top_k_recall,
                "top_n": args.top_n,
                "max_context_chars": args.max_context_chars,
                "embedding_model": settings.embedding_model,
                "reranker_model": reranker_model,
                "reference_filter": {
                    "enabled": args.reference_filter,
                    "min_keep": args.reference_filter_min_keep,
                    "overfetch": args.reference_filter_overfetch,
                },
                "collection": args.collection,
            },
            "embedding_recall": [
                {
                    "rank": i + 1,
                    "chunk_id": h.chunk_id,
                    "source": h.metadata.get("source"),
                    "score": round(h.score, 6),
                    "snippet": h.document[:EMBEDDING_SNIPPET_CHARS],
                }
                for i, h in enumerate(embedding_hits)
            ],
            "reranked_top_n": [
                {
                    "rank": i + 1,
                    "chunk_id": h.chunk_id,
                    "source": h.metadata.get("source"),
                    "score": round(h.score, 6),
                    "document": h.document,
                }
                for i, h in enumerate(reranked)
            ],
            "final_context": final_context,
            "final_context_chunks": final_chunks,
            "source_summary": {
                "embedding_recall": _count_by_source(
                    embedding_hits, lambda h: h.metadata.get("source")
                ),
                "reranked_top_n": _count_by_source(
                    reranked, lambda h: h.metadata.get("source")
                ),
                "final_context": _count_by_source(
                    final_chunks, lambda c: c["source"]
                ),
            },
        }

        out_path = out_dir / f"{qid}.json"
        out_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        rerank_unique_sources = len(
            {Path(str(h.metadata.get("source") or "")).name for h in reranked}
        )
        print(
            f"[ok] {qid} embed={len(embedding_hits)} "
            f"rerank={len(reranked)} rerank_unique_sources={rerank_unique_sources} "
            f"final_chunks={len(final_chunks)}"
        )

    print(f"\noutput dir: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
