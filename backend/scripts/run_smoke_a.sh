#!/usr/bin/env bash
# Smoke A (M1.5-a, DoD #3): start server with the A2 demo defaults -> wait
# health -> ask q04 once -> assert the answer is NOT a refusal (i.e. the A2
# default path actually surfaces the [79] evidence numbers, not "资料中未涉及").
#
# Local/manual gate only — NOT in CI. Requires a real DEEPSEEK_API_KEY, the
# local chroma index (var/chroma) and the reranker model. Proxy env is stripped
# because a newline in HTTPS_PROXY crashes both the DeepSeek client and httpx.
#
# Usage: backend/scripts/run_smoke_a.sh
set -uo pipefail

cd "$(dirname "$0")/.."   # backend/

unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy ALL_PROXY all_proxy
export NO_PROXY='127.0.0.1,localhost' no_proxy='127.0.0.1,localhost'

OUT_SUBDIR="smoke"
LOG="/tmp/smoke-a.uvicorn.log"
: > "$LOG"

echo "[smoke-a] A2 defaults: recall=20 top_n=5 ref-filter=on overfetch=10 reranker=on"

# Port preflight: refuse to run if 8000 already serves a healthy backend —
# otherwise this script's own uvicorn would fail to bind, the health probe
# and eval would silently hit the *pre-existing* process, and the gate would
# test the wrong server (false positive). Make the operator stop it first.
pre=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/api/health || true)
if [ "$pre" = "200" ]; then
  echo "[smoke-a] FATAL: 127.0.0.1:8000 already serves a healthy backend."
  echo "[smoke-a] stop it first — this gate must run against its own server."
  exit 2
fi

# Fixed A2 demo profile. reranker on is required (q04 flip depends on it);
# ref-filter/overfetch already default to A2 in config.py but pinned here
# so the smoke is self-describing regardless of .env.
RAG_ENABLED=true \
RAG_CHROMA_DIR=var/chroma \
RAG_COLLECTION=papers \
RAG_RERANKER_ENABLED=true \
RAG_RERANKER_TOP_K_RECALL=20 \
RAG_RERANKER_TOP_N=5 \
RAG_REFERENCE_FILTER_ENABLED=true \
RAG_REFERENCE_FILTER_MIN_KEEP=1 \
RAG_REFERENCE_FILTER_OVERFETCH=10 \
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000 > "$LOG" 2>&1 &
SERVER_PID=$!

cleanup() { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }
trap cleanup EXIT

# Wait for health (embedder + 2.2GB reranker load can take ~60s on CPU).
ready=0
for _ in $(seq 1 120); do
  if grep -q "Application startup failed" "$LOG"; then
    echo "[smoke-a] FATAL: server startup failed"; sed -n '1,60p' "$LOG"; exit 3
  fi
  code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/api/health || true)
  if [ "$code" = "200" ]; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != "1" ]; then echo "[smoke-a] FATAL: health never 200"; tail -30 "$LOG"; exit 4; fi

echo "[smoke-a] server lifespan line:"
grep "RAG enabled" "$LOG" | tail -1

echo "[smoke-a] asking q04 ..."
# runner timeout must exceed the backend worst case (DEEPSEEK_TIMEOUT_S 60s x
# (1+2 retries) = 180s LLM, plus CPU rerank) so a real backend 504 surfaces
# instead of a client-side ReadTimeout race.
uv run python scripts/run_mini_eval.py \
  --questions ../data/eval/smoke_questions.yaml \
  --api http://127.0.0.1:8000 \
  --timeout 300 \
  --out "var/eval/$OUT_SUBDIR"
eval_rc=$?
if [ "$eval_rc" != "0" ]; then
  echo "[smoke-a] FAIL: eval runner reported HTTP error (env/API issue, not a refusal)"; exit 5
fi

# Assert: q04 answer is non-refusal and grounded in the [79] numbers.
LATEST=$(ls -t "var/eval/$OUT_SUBDIR"/mini_eval_*.jsonl 2>/dev/null | head -1)
echo "[smoke-a] asserting on $LATEST"
uv run python - "$LATEST" <<'PY'
import json, sys

path = sys.argv[1]
with open(path, encoding="utf-8") as fh:
    rec = json.loads(fh.readline())

answer = (rec.get("answer") or "").strip()
if rec.get("error") or not answer:
    print(f"[smoke-a] FAIL: q04 has no usable answer (error={rec.get('error')})")
    sys.exit(6)

# Grounded numbers from 079::0004/0005 (the A2 flip evidence).
numbers = [n for n in ("6.2", "33", "4%") if n in answer]
refusal_markers = ("未涉及", "无法回答", "没有相关", "未提供", "资料中未", "无法找到")
refused = any(m in answer for m in refusal_markers)

print(f"[smoke-a] q04 answer ({len(answer)} chars): {answer[:160]}...")
print(f"[smoke-a] grounded numbers present: {numbers or 'NONE'}; refusal markers: {refused}")

if numbers and not refused:
    print("[smoke-a] PASS: q04 default path surfaces [79] evidence (non-refusal)")
    sys.exit(0)
print("[smoke-a] FAIL: q04 looks like a refusal / missing evidence numbers")
sys.exit(7)
PY
exit $?
