#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_DIR="${MODEL_DIR:-$ROOT_DIR/backend/data/models/bge-large-zh-v1.5}"
HF_ENDPOINT="${HF_ENDPOINT:-https://hf-mirror.com}"
MODEL_REPO="${MODEL_REPO:-BAAI/bge-large-zh-v1.5}"
PROXY_URL="${PROXY_URL:-http://127.0.0.1:7890}"

files=(
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

mkdir -p "$MODEL_DIR"

for file in "${files[@]}"; do
  target="$MODEL_DIR/$file"
  partial="$target.part"
  url="$HF_ENDPOINT/$MODEL_REPO/resolve/main/$file"

  mkdir -p "$(dirname "$target")"
  if [[ -s "$target" ]]; then
    echo "skip $file"
    continue
  fi

  echo "download $file"
  curl "${curl_args[@]}" --continue-at - --output "$partial" "$url"
  mv "$partial" "$target"
done

echo "model ready: $MODEL_DIR"
