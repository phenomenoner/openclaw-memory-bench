#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

uv run --python 3.13 -- python scripts/run_memory_core_vs_openclaw_mem.py "$@"
