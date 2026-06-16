#!/usr/bin/env bash
# Idempotent matrix runner for the M1.4-c experiment grid.
#
# For each group it checks whether that group's output dir already holds a
# *complete* run (a jsonl with exactly 10 records). If so it SKIPS; otherwise it
# drops any partial jsonl and runs the group via run_eval_group.sh.
#
# Designed for a flaky WSL session that keeps killing the process tree: re-invoke
# this script after any drop and it resumes from the first incomplete group
# without ever re-running a completed one. Completed jsonls are the durable
# checkpoint.
#
# Usage: run_eval_matrix.sh   (no args; edit GROUPS below to change the grid)
set -uo pipefail
cd "$(dirname "$0")/.."   # backend/

# subdir  recall  top_n  reffilter  overfetch
# NOTE: var is MATRIX, not GROUPS — this shell env pre-pollutes the name GROUPS
# into an integer-valued array, which silently mangles the entries to "0".
MATRIX=(
  "m1-4-c-A4-recall20-top7-reffilter 20 7 true 10"
  "m1-4-c-B1-recall10-baseline 10 5 false 2"
  "m1-4-c-B2-recall10-reffilter 10 5 true 10"
  "m1-4-c-C1-recall8-baseline 8 5 false 2"
  "m1-4-c-C2-recall8-reffilter 8 5 true 10"
)

is_complete() {   # $1 = out subdir -> echoes path of a 10-line jsonl if one exists
  local sub="$1" jf
  for jf in "var/eval/$sub"/*.jsonl; do
    [ -f "$jf" ] || continue
    if [ "$(wc -l < "$jf")" -eq 10 ]; then echo "$jf"; return 0; fi
  done
  return 1
}

DRYRUN="${DRYRUN:-0}"

for g in "${MATRIX[@]}"; do
  read -r sub recall top_n reffilter overfetch <<< "$g"
  if done_file=$(is_complete "$sub"); then
    echo "[matrix] SKIP  $sub (complete: $(basename "$done_file"))"
    continue
  fi
  # any jsonl present here is an incomplete partial -> drop before re-running
  rm -f "var/eval/$sub"/*.jsonl 2>/dev/null
  echo "[matrix] RUN   sub=$sub recall=$recall top_n=$top_n reffilter=$reffilter overfetch=$overfetch"
  if [ "$DRYRUN" = "1" ]; then
    echo "[matrix] (dryrun) would call: run_eval_group.sh $sub $recall $top_n $reffilter $overfetch"
    continue
  fi
  bash scripts/run_eval_group.sh "$sub" "$recall" "$top_n" "$reffilter" "$overfetch"
  echo "[matrix] DONE  $sub rc=$?"
done
echo "[matrix] ALL GROUPS PROCESSED"
