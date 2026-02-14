#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

usage() {
  cat <<'EOF'
Run Phase A/B (LongMemEval-50) across multiple seeds and emit an aggregate summary.

Default profile:
  dataset:   data/datasets/longmemeval-50.json
  top_k:     10
  policies:  must must+nice
  seeds:     0..9
  prefix:    phase-ab-longmemeval50-topk10
  out group: phase-ab-longmemeval50-topk10-multiseed10

Usage:
  scripts/run_phase_ab_longmemeval50_multiseed.sh [--seeds "0,1,2"] [--prefix <name>] [--out-group <name>] [extra-args...]

Notes:
- This wrapper calls `scripts/run_phase_ab_longmemeval50.sh` once per seed.
- Any extra args are forwarded to each run (e.g., --include-observational).
- After all runs, it writes:
    artifacts/phase-ab-compare/<out-group>/multiseed-summary.{json,md}
EOF
}

seeds_csv="0,1,2,3,4,5,6,7,8,9"
prefix="phase-ab-longmemeval50-topk10"
out_group="phase-ab-longmemeval50-topk10-multiseed10"

extra_args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    --seeds)
      [[ $# -ge 2 ]] || { echo "--seeds requires a csv value" >&2; exit 2; }
      seeds_csv="$2"
      shift 2
      ;;
    --prefix)
      [[ $# -ge 2 ]] || { echo "--prefix requires a value" >&2; exit 2; }
      prefix="$2"
      shift 2
      ;;
    --out-group)
      [[ $# -ge 2 ]] || { echo "--out-group requires a value" >&2; exit 2; }
      out_group="$2"
      shift 2
      ;;
    *)
      extra_args+=("$1")
      shift
      ;;
  esac
done

IFS=',' read -r -a seeds <<< "$seeds_csv"

cd "$REPO_ROOT"

run_groups=()
for seed in "${seeds[@]}"; do
  rg="${prefix}-seed${seed}"
  run_groups+=("$rg")
  echo "[multiseed] running seed=${seed} run_group=${rg}" >&2
  scripts/run_phase_ab_longmemeval50.sh \
    --sample-seed "$seed" \
    --run-group "$rg" \
    "${extra_args[@]}"
done

# Emit aggregate summary under a dedicated out_group.
uv run --python 3.13 -- python scripts/summarize_phase_ab_multiseed.py \
  --run-groups "${run_groups[@]}" \
  --out-group "$out_group"
