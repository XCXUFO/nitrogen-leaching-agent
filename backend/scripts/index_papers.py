"""Offline indexer: ingest -> chunk -> embed -> ChromaStore.add.

Usage:
    cd backend
    uv sync --extra rag                                  # first-time only
    uv run python scripts/index_papers.py \
        --paths ../data/papers/sample.txt \
        --persist-dir var/chroma \
        --collection papers \
        --repo-root ..

The ``document_id`` is derived deterministically from the path's repo-relative
location (suffix stripped, characters normalized) — see M1.2.3 spec §3.6.1.
Re-running on the same files produces identical chunk_ids; the script uses
``ChromaStore.upsert`` so repeated runs are idempotent (existing ids are
replaced, not duplicated).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Ensure ``src`` is importable when invoked as ``python scripts/index_papers.py``
_BACKEND_ROOT = Path(__file__).resolve().parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from src.config import settings  # noqa: E402
from src.rag import BGEEmbedder, chunk_text, load_text  # noqa: E402
from src.storage import ChromaStore  # noqa: E402

_ID_SAFE = re.compile(r"[^A-Za-z0-9一-鿿/_-]")


def derive_document_id(path: Path, repo_root: Path) -> str:
    """Stable id from repo-relative stem path (M1.2.3 spec §3.6.1)."""
    rel = path.resolve().relative_to(repo_root.resolve())
    stem_path = rel.with_suffix("")
    raw = str(stem_path).replace("\\", "/")
    return _ID_SAFE.sub("_", raw)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Offline paper indexer")
    p.add_argument("--paths", nargs="+", required=True, type=Path)
    p.add_argument("--persist-dir", required=True, type=Path)
    p.add_argument("--collection", default="papers")
    p.add_argument(
        "--repo-root",
        type=Path,
        default=Path.cwd(),
        help="root used to compute the relative path that becomes document_id",
    )
    p.add_argument("--target-size", type=int, default=300)
    p.add_argument("--max-size", type=int, default=450)
    p.add_argument("--overlap", type=int, default=60)
    return p.parse_args()


def main() -> int:
    args = parse_args()
    embedder = BGEEmbedder(model_id=settings.embedding_model)
    store = ChromaStore(args.persist_dir, args.collection)

    total_docs = 0
    total_chunks = 0
    total_chars = 0
    truncation_warn = 0

    for path in args.paths:
        try:
            text = load_text(path)
        except Exception as exc:
            print(f"[warn] skip {path}: {exc}", file=sys.stderr)
            continue

        try:
            document_id = derive_document_id(path, args.repo_root)
        except ValueError as exc:
            print(f"[warn] skip {path}: not under repo_root ({exc})", file=sys.stderr)
            continue

        chunks = chunk_text(
            text,
            document_id=document_id,
            source=str(path),
            target_size=args.target_size,
            max_size=args.max_size,
            overlap=args.overlap,
        )
        if not chunks:
            print(f"[warn] empty chunks for {path}, skip", file=sys.stderr)
            continue

        vectors = embedder.embed_documents([c.text for c in chunks])
        store.upsert(
            ids=[c.chunk_id for c in chunks],
            documents=[c.text for c in chunks],
            embeddings=vectors,
            metadatas=[c.metadata for c in chunks],
        )

        total_docs += 1
        total_chunks += len(chunks)
        total_chars += sum(len(c.text) for c in chunks)
        truncation_warn += sum(1 for c in chunks if len(c.text) > 350)

        print(f"[ok] {path}: {len(chunks)} chunks (document_id={document_id})")

    avg_chars = (total_chars / total_chunks) if total_chunks else 0.0
    chunks_per_doc = (total_chunks / total_docs) if total_docs else 0.0
    rate = (truncation_warn / total_chunks) if total_chunks else 0.0
    print(
        f"\nsummary: {total_docs} docs, {total_chunks} chunks, "
        f"{chunks_per_doc:.1f} chunks/doc, "
        f"avg {avg_chars:.1f} chars/chunk, "
        f"~{rate:.1%} chunks > 350 chars (BGE may truncate; rough estimate)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
