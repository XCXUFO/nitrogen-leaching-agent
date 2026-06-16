#!/usr/bin/env bash
# One-shot eval group runner: start server -> wait health -> run mini eval -> stop server.
# Binds server + eval into a single process lifetime so neither depends on
# surviving across harness turns. Proxy env is stripped because a newline in
# HTTPS_PROXY crashes both the DeepSeek client (server) and httpx (eval).
#
# Usage: run_eval_group.sh <OUT_SUBDIR> <RECALL> <TOP_N> <REFFILTER true|false> <OVERFETCH>
set -uo pipefail

OUT_SUBDIR="$1"; RECALL="$2"; TOP_N="$3"; REFFILTER="$4"; OVERFETCH="${5:-2}"

cd "$(dirname "$0")/.."   # backend/

# Strip the broken proxy vars for every child in this script.
unset HTTPS_PROXY HTTP_PROXY https_proxy http_proxy ALL_PROXY all_proxy
export NO_PROXY='127.0.0.1,localhost' no_proxy='127.0.0.1,localhost'

LOG="/tmp/eval-group-${OUT_SUBDIR}.uvicorn.log"
: > "$LOG"

echo "[group] out=$OUT_SUBDIR recall=$RECALL top_n=$TOP_N reffilter=$REFFILTER overfetch=$OVERFETCH"

RAG_ENABLED=true \
RAG_CHROMA_DIR=var/chroma \
RAG_COLLECTION=papers \
RAG_RERANKER_ENABLED=true \
RAG_RERANKER_TOP_K_RECALL="$RECALL" \
RAG_RERANKER_TOP_N="$TOP_N" \
RAG_REFERENCE_FILTER_ENABLED="$REFFILTER" \
RAG_REFERENCE_FILTER_MIN_KEEP=1 \
RAG_REFERENCE_FILTER_OVERFETCH="$OVERFETCH" \
uv run uvicorn src.main:app --host 127.0.0.1 --port 8000 > "$LOG" 2>&1 &
SERVER_PID=$!

cleanup() { kill "$SERVER_PID" 2>/dev/null; wait "$SERVER_PID" 2>/dev/null; }
trap cleanup EXIT

# Wait for health (model load can take ~30s).
ready=0
for _ in $(seq 1 90); do
  if grep -q "Application startup failed" "$LOG"; then
    echo "[group] FATAL: server startup failed"; sed -n '1,60p' "$LOG"; exit 3
  fi
  code=$(curl -s --noproxy '*' -o /dev/null -w '%{http_code}' --max-time 3 http://127.0.0.1:8000/api/health || true)
  if [ "$code" = "200" ]; then ready=1; break; fi
  sleep 1
done
if [ "$ready" != "1" ]; then echo "[group] FATAL: health never 200"; tail -30 "$LOG"; exit 4; fi

echo "[group] server lifespan line:"
grep "RAG enabled" "$LOG" | tail -1

echo "[group] starting eval ..."
uv run python scripts/run_mini_eval.py \
  --questions ../data/eval/mini_questions.yaml \
  --api http://127.0.0.1:8000 \
  --timeout 180 \
  --out "var/eval/$OUT_SUBDIR"
rc=$?

echo "[group] eval exit rc=$rc"
exit "$rc"
