#!/usr/bin/env bash
# Download HuggingFace models needed by the backend.
#
# Targets:
#   embedder  -> BAAI/bge-large-zh-v1.5     (~1.3 GB) — required for RAG
#   reranker  -> BAAI/bge-reranker-v2-m3    (~2.2 GB) — required for M1.4-b reranker
#
# Usage:
#   bash scripts/download_models.sh                   # download both (default)
#   bash scripts/download_models.sh embedder          # only embedder
#   bash scripts/download_models.sh reranker          # only reranker
#   bash scripts/download_models.sh embedder reranker # explicit both
#
# Env overrides:
#   HF_ENDPOINT  (default https://hf-mirror.com)
#   PROXY_URL    (default http://127.0.0.1:7890; set empty to disable)
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
PROXY_URL="${PROXY_URL:-http://127.0.0.1:7890}"

curl_args=(
  --fail
  --location
  --retry 10
  --retry-delay 5
  --retry-all-errors
  --connect-timeout 30
)
if [[ -n "$PROXY_URL" ]]; then
  curl_args+=(--proxy "$PROXY_URL")
fi

download_file() {
  local repo="$1" target_dir="$2" file="$3"
  local target="$target_dir/$file"
  local partial="$target.part"
  local url="$HF_ENDPOINT/$repo/resolve/main/$file"

  mkdir -p "$(dirname "$target")"
  if [[ -s "$target" ]]; then
    echo "  skip $file"
    return
  fi

  echo "  download $file"
  curl "${curl_args[@]}" --continue-at - --output "$partial" "$url"
  mv "$partial" "$target"
}

download_embedder() {
  local dir="$ROOT_DIR/backend/data/models/bge-large-zh-v1.5"
  local repo="BAAI/bge-large-zh-v1.5"
  local files=(
    ".gitattributes"
    "README.md"
    "1_Pooling/config.json"
    "config.json"
    "config_sentence_transformers.json"
    "modules.json"
    "sentence_bert_config.json"
    "special_tokens_map.json"
    "tokenizer.json"
    "tokenizer_config.json"
    "vocab.txt"
    "pytorch_model.bin"
  )
  echo "[embedder] $repo -> $dir"
  mkdir -p "$dir"
  for f in "${files[@]}"; do
    download_file "$repo" "$dir" "$f"
  done
  echo "[embedder] ready: $dir"
}

download_reranker() {
  local dir="$ROOT_DIR/backend/data/models/bge-reranker-v2-m3"
  local repo="BAAI/bge-reranker-v2-m3"
  local files=(
    "config.json"
    "tokenizer.json"
    "tokenizer_config.json"
    "special_tokens_map.json"
    "sentencepiece.bpe.model"
    "model.safetensors"
  )
  echo "[reranker] $repo -> $dir (~2.2 GB)"
  mkdir -p "$dir"
  for f in "${files[@]}"; do
    download_file "$repo" "$dir" "$f"
  done
  echo "[reranker] ready: $dir"
}

targets=("$@")
if [[ ${#targets[@]} -eq 0 ]]; then
  targets=(embedder reranker)
fi

for t in "${targets[@]}"; do
  case "$t" in
    embedder) download_embedder ;;
    reranker) download_reranker ;;
    *)
      echo "[fatal] unknown target: $t (expected: embedder | reranker)" >&2
      exit 2
      ;;
  esac
done
