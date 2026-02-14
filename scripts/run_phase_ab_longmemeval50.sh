#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Deterministic long-run profile for Phase A/B compare on LongMemEval-50.

Usage:
  scripts/run_phase_ab_longmemeval50.sh [--run-group <name>] [--include-observational] [extra-args...]

Defaults:
  --dataset data/datasets/longmemeval-50.json
  --top-k 10
  --sample-seed 7
  --policies must must+nice
  --run-label phase-ab-longmemeval50
  --run-group phase-ab-longmemeval50-seed7-topk10

Examples:
  scripts/run_phase_ab_longmemeval50.sh
  scripts/run_phase_ab_longmemeval50.sh --run-group phase-ab-longmemeval50-rerun-a
EOF
}

has_flag() {
  local needle="$1"
  shift
  local arg
  for arg in "$@"; do
    if [[ "$arg" == "$needle" ]]; then
      return 0
    fi
  done
  return 1
}

args=("$@")

if has_flag -h "${args[@]}" || has_flag --help "${args[@]}"; then
  usage
  exit 0
fi

if ! has_flag --dataset "${args[@]}"; then
  args+=(--dataset data/datasets/longmemeval-50.json)
fi
if ! has_flag --top-k "${args[@]}"; then
  args+=(--top-k 10)
fi
if ! has_flag --sample-seed "${args[@]}"; then
  args+=(--sample-seed 7)
fi
if ! has_flag --policies "${args[@]}"; then
  args+=(--policies must must+nice)
fi
if ! has_flag --run-label "${args[@]}"; then
  args+=(--run-label phase-ab-longmemeval50)
fi
if ! has_flag --run-group "${args[@]}"; then
  args+=(--run-group phase-ab-longmemeval50-seed7-topk10)
fi

cd "$REPO_ROOT"
scripts/run_lancedb_vs_openclaw_mem_assisted.sh "${args[@]}"
