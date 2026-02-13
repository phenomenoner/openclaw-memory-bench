#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"
PY_RUNNER="scripts/run_lancedb_vs_openclaw_mem_assisted.py"
DEFAULT_DATASET="examples/dual_language_mini.json"

die() {
  echo "[phase-ab-runner] error: $*" >&2
  exit 2
}

has_flag() {
  local needle="$1"
  shift
  for arg in "$@"; do
    if [[ "$arg" == "$needle" || "$arg" == "$needle="* ]]; then
      return 0
    fi
  done
  return 1
}

show_help() {
  cat <<'EOF'
Phase A/B compare wrapper (memory-lancedb baseline vs openclaw-mem-assisted ingest proxy)

Usage:
  scripts/run_lancedb_vs_openclaw_mem_assisted.sh [--smoke] [python-runner-args...]

Wrapper options:
  --smoke        Run a cheap smoke profile unless overridden by explicit args:
                 --dataset examples/dual_language_mini.json
                 --question-limit 2
                 --sample-size 1
                 --top-k 5
                 --policies must
                 --run-label phase-ab-smoke
  -h, --help     Show this wrapper help, then the underlying Python runner help.

All other flags are passed through to scripts/run_lancedb_vs_openclaw_mem_assisted.py.
EOF
}

if ! command -v uv >/dev/null 2>&1; then
  die "uv is required but was not found in PATH. Install uv first: https://docs.astral.sh/uv/"
fi

use_smoke=0
dataset_arg="$DEFAULT_DATASET"
args=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --smoke)
      use_smoke=1
      shift
      ;;
    --dataset)
      [[ $# -ge 2 ]] || die "--dataset requires a path argument"
      dataset_arg="$2"
      args+=("$1" "$2")
      shift 2
      ;;
    --dataset=*)
      dataset_arg="${1#*=}"
      args+=("$1")
      shift
      ;;
    -h|--help)
      show_help
      echo
      echo "Underlying runner options:"
      cd "$REPO_ROOT"
      uv run --python 3.13 -- python "$PY_RUNNER" --help
      exit 0
      ;;
    *)
      args+=("$1")
      shift
      ;;
  esac
done

if [[ "$use_smoke" -eq 1 ]]; then
  has_flag --dataset "${args[@]}" || {
    dataset_arg="$DEFAULT_DATASET"
    args+=(--dataset "$dataset_arg")
  }
  has_flag --question-limit "${args[@]}" || args+=(--question-limit 2)
  has_flag --sample-size "${args[@]}" || args+=(--sample-size 1)
  has_flag --top-k "${args[@]}" || args+=(--top-k 5)
  has_flag --policies "${args[@]}" || args+=(--policies must)
  has_flag --run-label "${args[@]}" || args+=(--run-label phase-ab-smoke)
fi

if [[ "$dataset_arg" = /* ]]; then
  dataset_abs="$dataset_arg"
else
  dataset_abs="$REPO_ROOT/$dataset_arg"
fi

[[ -f "$dataset_abs" ]] || die "dataset not found: $dataset_arg (resolved: $dataset_abs)"

cd "$REPO_ROOT"
if [[ "$use_smoke" -eq 1 ]]; then
  echo "[phase-ab-runner] smoke profile active (override via explicit flags)." >&2
fi

uv run --python 3.13 -- python "$PY_RUNNER" "${args[@]}"
