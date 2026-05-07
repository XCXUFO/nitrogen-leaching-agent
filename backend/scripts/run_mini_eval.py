"""Mini eval runner — read questions YAML, call POST /api/chat, write JSONL.

Usage:
    cd backend
    uv run python scripts/run_mini_eval.py \
        --questions ../data/eval/mini_questions.yaml \
        --api http://localhost:8000 \
        --out var/eval

Behavior (intentionally minimal — see M1.4-a spec §3.4):
    - Sequential, no concurrency (avoid DeepSeek rate limit).
    - No retry; failures are written verbatim for human inspection.
    - No scoring; this script only collects raw responses.

Backend must be running with RAG_ENABLED=true and a populated chroma index.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx
import yaml


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M1.4-a mini eval runner")
    p.add_argument(
        "--questions",
        required=True,
        type=Path,
        help="path to questions YAML (e.g. data/eval/mini_questions.yaml)",
    )
    p.add_argument(
        "--api",
        default="http://localhost:8000",
        help="backend base URL (no trailing slash)",
    )
    p.add_argument(
        "--out",
        required=True,
        type=Path,
        help="output directory for the JSONL file",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="per-request timeout in seconds (default 60)",
    )
    p.add_argument(
        "--k",
        type=int,
        default=None,
        help="optional per-request retrieval k override (API allows 1..20)",
    )
    return p.parse_args()


def main() -> int:
    args = parse_args()

    raw = yaml.safe_load(args.questions.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "questions" not in raw:
        print(f"[fatal] {args.questions} missing 'questions' key", file=sys.stderr)
        return 2
    questions: list[dict[str, Any]] = raw["questions"]

    todo_count = sum(1 for q in questions if q.get("query") == "TODO")
    if todo_count:
        print(
            f"[warn] {todo_count}/{len(questions)} questions still have query=TODO; "
            "fill them before running a real evaluation.",
            file=sys.stderr,
        )

    runid = datetime.now().strftime("%Y%m%d-%H%M%S")
    args.out.mkdir(parents=True, exist_ok=True)
    out_path = args.out / f"mini_eval_{runid}.jsonl"

    print(f"[runid] {runid}")
    print(f"[out]   {out_path}")
    print(f"[api]   {args.api}")
    print(f"[k]     {args.k if args.k is not None else 'backend default'}")
    print(f"[count] {len(questions)} questions\n")

    ok = 0
    err = 0
    with httpx.Client(timeout=args.timeout) as client, out_path.open(
        "w", encoding="utf-8"
    ) as fh:
        for q in questions:
            qid = q.get("id", "?")
            t0 = time.perf_counter()
            record: dict[str, Any] = {
                "runid": runid,
                "question_id": qid,
                "category": q.get("category"),
                "query": q.get("query"),
                "should_refuse": q.get("should_refuse", False),
                "request_k": args.k,
            }

            try:
                payload: dict[str, Any] = {"query": q["query"]}
                if args.k is not None:
                    payload["k"] = args.k
                resp = client.post(
                    f"{args.api}/api/chat",
                    json=payload,
                )
                latency_ms = int((time.perf_counter() - t0) * 1000)
                record["latency_ms"] = latency_ms

                if resp.status_code == 200:
                    body = resp.json()
                    record.update(
                        answer=body.get("answer"),
                        citations=body.get("citations", []),
                        retrieved_count=body.get("retrieved_count"),
                        usage=body.get("usage"),
                        model=body.get("model"),
                        error=None,
                    )
                    ok += 1
                    n_cites = len(body.get("citations") or [])
                    print(f"[ok]  {qid} {latency_ms}ms cites={n_cites}")
                else:
                    record["error"] = {
                        "http_status": resp.status_code,
                        "body": _safe_json(resp),
                    }
                    err += 1
                    print(f"[err] {qid} HTTP {resp.status_code}")
            except Exception as exc:
                record["latency_ms"] = int((time.perf_counter() - t0) * 1000)
                record["error"] = {"http_status": None, "body": repr(exc)}
                err += 1
                print(f"[err] {qid} {exc!r}")

            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            fh.flush()

    print(f"\nsummary: {ok} ok, {err} err, total {len(questions)}")
    print(f"output: {out_path}")
    return 0 if err == 0 else 1


def _safe_json(resp: httpx.Response) -> Any:
    try:
        return resp.json()
    except Exception:
        return resp.text[:500]


if __name__ == "__main__":
    sys.exit(main())
