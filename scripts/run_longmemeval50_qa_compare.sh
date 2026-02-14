#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "${SCRIPT_DIR}/.." && pwd)"

cd "$REPO_ROOT"

# Requires OPENAI_API_KEY in env.
# Example:
#   export OPENAI_API_KEY=...
#   scripts/run_longmemeval50_qa_compare.sh --limit 20 --arms oracle observational

uv run --python 3.13 -- python scripts/run_longmemeval50_qa_compare.py "$@"
