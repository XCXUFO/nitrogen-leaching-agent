#!/usr/bin/env bash
# Smoke B (M1.5-b, DoD-3): start server with the A2 + numeric-boost demo
# defaults -> wait health -> ask q08 once -> assert the answer is NOT a refusal
# and carries the grounded model-accuracy statistics (R²/RMSE/IA), with a
# citation that traces back to the boost evidence chunk 026::0172.
#
# Local/manual gate only — NOT in CI. Requires a real DEEPSEEK_API_KEY (read
# from backend/.env), the local chroma index (var/chroma) and the reranker
# model. Proxy env is stripped because a newline in HTTPS_PROXY crashes both
# the DeepSeek client and httpx.
#
# Usage: backend/scripts/run_smoke_b.sh
set -uo pipefail

cd "$(dirname "$0")/.."   # backend/

unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy ALL_PROXY all_proxy
export NO_PROXY='127.0.0.1,localhost' no_proxy='127.0.0.1,localhost'

OUT_SUBDIR="smoke_b"
LOG="/tmp/smoke-b.uvicorn.log"
: > "$LOG"

echo "[smoke-b] A2+boost defaults: recall=20 top_n=5 ref-filter=on overfetch=10 reranker=on numeric_boost=on(w=0.445,b=0.30)"

# Port preflight: refuse to run if 8000 already serves a healthy backend —
# otherwise this script's own uvicorn would fail to bind, the probe and eval
# would silently hit the *pre-existing* process, and the gate would test the
# wrong server (false positive). Make the operator stop it first.
pre=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/api/health || true)
if [ "$pre" = "200" ]; then
  echo "[smoke-b] FATAL: 127.0.0.1:8000 already serves a healthy backend."
  echo "[smoke-b] stop it first — this gate must run against its own server."
  exit 2
fi

# Fixed A2 + boost demo profile. numeric_boost on is required (q08 lift depends
# on it); these already default to this in config.py but are pinned here so the
# smoke is self-describing regardless of .env.
RAG_ENABLED=true \
RAG_CHROMA_DIR=var/chroma \
RAG_COLLECTION=papers \
RAG_RERANKER_ENABLED=true \
RAG_RERANKER_TOP_K_RECALL=20 \
RAG_RERANKER_TOP_N=5 \
RAG_REFERENCE_FILTER_ENABLED=true \
RAG_REFERENCE_FILTER_MIN_KEEP=1 \
RAG_REFERENCE_FILTER_OVERFETCH=10 \
RAG_NUMERIC_BOOST_ENABLED=true \
RAG_NUMERIC_BOOST_WEIGHT=0.445 \
RAG_NUMERIC_BOOST_BAND=0.30 \
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000 > "$LOG" 2>&1 &
SERVER_PID=$!

cleanup() { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }
trap cleanup EXIT

# Wait for health (embedder + 2.2GB reranker load can take ~60s on CPU).
ready=0
for _ in $(seq 1 120); do
  if grep -q "Application startup failed" "$LOG"; then
    echo "[smoke-b] FATAL: server startup failed"; sed -n '1,60p' "$LOG"; exit 3
  fi
  code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/api/health || true)
  if [ "$code" = "200" ]; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != "1" ]; then echo "[smoke-b] FATAL: health never 200"; tail -30 "$LOG"; exit 4; fi

echo "[smoke-b] server lifespan line:"
grep "RAG enabled" "$LOG" | tail -1   # should show numeric_boost=on(...)

echo "[smoke-b] asking q08 ..."
# runner timeout must exceed the backend worst case (DEEPSEEK_TIMEOUT_S 60s x
# (1+2 retries) = 180s LLM, plus CPU rerank) so a real backend 504 surfaces
# instead of a client-side ReadTimeout race.
uv run python scripts/run_mini_eval.py \
  --questions ../data/eval/smoke_b_questions.yaml \
  --api http://127.0.0.1:8000 \
  --timeout 300 \
  --out "var/eval/$OUT_SUBDIR"
eval_rc=$?
if [ "$eval_rc" != "0" ]; then
  echo "[smoke-b] FAIL: eval runner reported HTTP error (env/API issue, e.g. llm_unreachable — not a refusal)"; exit 5
fi

# Assert: q08 answer is non-refusal, carries grounded statistics, and a
# citation traces to 026::0172. Per spec — do NOT gate on a verbatim answer.
LATEST=$(ls -t "var/eval/$OUT_SUBDIR"/mini_eval_*.jsonl 2>/dev/null | head -1)
echo "[smoke-b] asserting on $LATEST"
uv run python - "$LATEST" <<'PY'
import json, sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    rec = json.loads(fh.readline())

answer = (rec.get("answer") or "").strip()
if rec.get("error") or not answer:
    print(f"[smoke-b] FAIL: q08 has no usable answer (error={rec.get('error')})")
    sys.exit(6)

# (1) non-refusal
refusal_markers = ("未涉及", "无法回答", "没有相关", "未提供", "资料中未", "无法找到")
refused = any(m in answer for m in refusal_markers)

# (2) grounded model-accuracy statistics present (any of the metric tokens).
metric_tokens = ["0.84", "0.99", "RMSE", "243", "1097", "IA", "0.70", "决定系数", "一致性"]
present = [t for t in metric_tokens if t in answer]

# (3) a citation traces back to the boost evidence chunk 026::0172.
cites = rec.get("citations") or []
cite_ids = [str(c.get("chunk_id", "")) for c in cites]
traced = any(("0172" in cid and "026" in cid) for cid in cite_ids)

print(f"[smoke-b] q08 answer ({len(answer)} chars): {answer[:200]}...")
print(f"[smoke-b] refusal markers: {refused}")
print(f"[smoke-b] metric tokens present: {present or 'NONE'}")
print(f"[smoke-b] citations: {cite_ids}")
print(f"[smoke-b] 026::0172 traced in citations: {traced}")

if (not refused) and present and traced:
    print("[smoke-b] PASS: q08 default path answers with grounded stats and cites 026::0172")
    sys.exit(0)
print("[smoke-b] FAIL: refusal / missing metric tokens / 026::0172 not cited")
sys.exit(7)
PY
exit $?
