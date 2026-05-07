"""Retrieval debug — dump top-N hits per question, no LLM, no scoring.

Used for M1.4-b retrieval-level diagnostics. Given a questions YAML, run each
query through the same Embedder + ChromaStore that ``/api/chat`` uses and
write one JSON per question to ``backend/var/retrieval/<runid>/<qid>.json``.

The script does **not** call the chat API — it bypasses prompt assembly and
the LLM, which lets us isolate retrieval quality from synthesis quality
(M1.4-a finding: target paper often missed top-5, not LLM hallucinating).

Usage:
    cd backend
    uv run python scripts/retrieval_debug.py \\
        --questions ../data/eval/mini_questions.yaml \\
        --persist-dir var/chroma \\
        --collection papers \\
        --out var/retrieval \\
        --top-n 20

Optional: ``--qids q01,q02`` to limit to specific question ids.

Stage label is ``embedding_only`` for now. M1.4-b §5 step 2 will extend this
to also dump ``reranked`` top-N once the reranker lands; that diff is what
proves rerank actually moves target papers up.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from src.config import settings  # noqa: E402
from src.rag import BGEEmbedder, Reranker, Retriever  # noqa: E402
from src.storage import ChromaStore  # noqa: E402

SNIPPET_CHARS = 120


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M1.4-b retrieval debug dumper")
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
        help="parent dir for runid/<qid>.json output (e.g. var/retrieval)",
    )
    p.add_argument(
        "--top-n",
        type=int,
        default=20,
        help="how many hits to dump per question (default 20)",
    )
    p.add_argument(
        "--qids",
        default=None,
        help="optional comma-separated question ids to include (e.g. q01,q07)",
    )
    p.add_argument(
        "--rerank",
        action="store_true",
        help="run reranker on the recalled top-N and output reranked order "
             "(stage label flips to 'reranked' automatically)",
    )
    p.add_argument(
        "--reranker-model",
        default=None,
        help="reranker model id/path; defaults to settings.rag_reranker_model",
    )
    p.add_argument(
        "--stage",
        default=None,
        help="override stage label written to each output file "
             "(default: 'reranked' when --rerank, else 'embedding_only')",
    )
    return p.parse_args()


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

    stage = args.stage or ("reranked" if args.rerank else "embedding_only")
    runid = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = args.out / runid
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[runid]      {runid}")
    print(f"[out]        {out_dir}")
    print(f"[stage]      {stage}")
    print(f"[top-n]      {args.top_n}")
    print(f"[chroma]     {args.persist_dir} :: {args.collection}")
    print(f"[embedding]  {settings.embedding_model}")
    if args.rerank:
        print(f"[reranker]   {args.reranker_model or settings.rag_reranker_model}")
    print(f"[count]      {len(questions)} questions\n")

    embedder = BGEEmbedder(model_id=settings.embedding_model)
    store = ChromaStore(args.persist_dir, args.collection)
    reranker: Reranker | None = None
    if args.rerank:
        reranker = Reranker(
            model_id=args.reranker_model or settings.rag_reranker_model,
        )
    # Embedder recalls top_n; if reranker provided, recall is identical (no
    # extra recall depth) so the dump exposes EXACTLY the rerank of the same
    # candidates the embedding-only run saw — clean A/B comparison.
    retriever = Retriever(embedder, store, reranker=reranker, top_k_recall=args.top_n)

    for q in questions:
        qid = q.get("id", "?")
        query = q.get("query", "")
        if not query or query == "TODO":
            print(f"[skip] {qid} (empty/TODO query)")
            continue

        hits = retriever.retrieve(query, k=args.top_n)

        record = {
            "runid": runid,
            "question_id": qid,
            "category": q.get("category"),
            "query": query,
            "should_refuse": q.get("should_refuse", False),
            "stage": stage,
            "top_n": args.top_n,
            "embedding_model": settings.embedding_model,
            "reranker_model": (
                args.reranker_model or settings.rag_reranker_model
                if args.rerank else None
            ),
            "collection": args.collection,
            "results": [
                {
                    "rank": i + 1,
                    "chunk_id": h.chunk_id,
                    "source": h.metadata.get("source"),
                    "score": round(h.score, 6),
                    "snippet": h.document[:SNIPPET_CHARS],
                }
                for i, h in enumerate(hits)
            ],
        }

        out_path = out_dir / f"{qid}.json"
        out_path.write_text(
            json.dumps(record, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        if hits:
            top5_sources = [h.metadata.get("source", "?") for h in hits[:5]]
            unique_top5 = len({Path(s).name for s in top5_sources if s})
            print(
                f"[ok] {qid} hits={len(hits)} "
                f"top5_unique_sources={unique_top5} "
                f"top1_score={hits[0].score:.3f}"
            )
        else:
            print(f"[ok] {qid} hits=0")

    print(f"\noutput dir: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
