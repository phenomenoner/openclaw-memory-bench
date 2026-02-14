# openclaw-memory-bench

CLI-first benchmark toolkit for **OpenClaw memory-layer plugins**.

This project is designed to provide a reproducible, non-interactive evaluation workflow for memory plugins such as:
- `openclaw-mem`
- `memory-core` (OpenClaw built-in memory)
- `memory-lancedb`
- `memu-engine-for-OpenClaw`
- future OpenClaw memory-layer plugins

## Why this exists

Public SaaS memory providers already have benchmark visibility. The OpenClaw community needs a neutral, plugin-focused benchmark harness with:
- deterministic retrieval metrics
- optional end-to-end answer/judge metrics
- reproducible run manifests
- machine-readable outputs for CI and community comparison

## Scope (v0.1)

- **Track A: Retrieval benchmark (deterministic)**
  - Hit@K, Recall@K, Precision@K, MRR, nDCG
  - latency (p50/p95)
- **Track B: End-to-end benchmark (optional)**
  - retrieval → answer model → judge model
  - accuracy + cost/latency metadata

## Principles

1. **CLI and non-interactive by default**
2. **Reproducibility first** (versioned manifests, pinned config)
3. **Plugin neutrality** (same protocol for all adapters)
4. **Transparent reporting** (JSON outputs + docs)

## Quickstart (retrieval track MVP)

```bash
uv sync
uv run openclaw-memory-bench doctor

# Generate manifest
uv run openclaw-memory-bench plan --provider openclaw-mem --benchmark locomo

# Run deterministic retrieval benchmark using example dataset
uv run openclaw-memory-bench run-retrieval \
  --provider openclaw-mem \
  --dataset examples/mini_retrieval.json \
  --top-k 5

# Run against isolated memory-core profile (no main-system pollution)
uv run openclaw-memory-bench run-retrieval \
  --provider memory-core \
  --dataset examples/mini_retrieval.json \
  --top-k 5 \
  --memory-core-profile membench-memory-core

# Prepare canonical dataset (download + convert)
uv run openclaw-memory-bench prepare-dataset \
  --benchmark longmemeval \
  --limit 50 \
  --out data/datasets/longmemeval-50.json
# Writes dataset + sidecar metadata:
# - data/datasets/longmemeval-50.json
# - data/datasets/longmemeval-50.json.meta.json
```

The run command writes a JSON report under `artifacts/<run-id>/retrieval-report.json` by default.
Reports now embed a reproducibility manifest (`report.manifest`) containing toolkit version, git commit, dataset hash/meta, provider config (sanitized), and runtime metadata.

For dataset schema, see `docs/dataset-format.md`.

## Preliminary results snapshot

See `PRELIMINARY_RESULTS.md` for currently available early comparison artifacts and caveats.

## Provider roles and interpretation guardrails (important)

To avoid misleading comparisons, benchmark providers should be read as follows:

- `openclaw-mem` provider in this repo = **standalone sidecar engine run** (`openclaw-mem` CLI ingest/search on benchmark-managed sqlite files).
  - It is **not automatically combined** with `memory-core` or `memory-lancedb` in current leaderboard numbers.
- `memory-core` provider = OpenClaw built-in backend (`openclaw memory index/search`) under an isolated profile.
- `memory-lancedb` provider = canonical memory tool path (`memory_store` / `memory_recall` / `memory_forget`) via Gateway invoke.

Current reports are primarily **independent-provider comparisons**. A full **combination matrix** (e.g., sidecar + backend pairings) is tracked as follow-up work.

### memory-lancedb (canonical memory tools)

```bash
uv run openclaw-memory-bench run-retrieval \
  --provider memory-lancedb \
  --dataset data/datasets/longmemeval-50.json \
  --top-k 10 \
  --session-key main
```

> This adapter uses `memory_store` + `memory_recall` + `memory_forget` via Gateway invoke.

### memu-engine (gateway mode)

```bash
uv run openclaw-memory-bench run-retrieval \
  --provider memu-engine \
  --dataset data/datasets/longmemeval-50.json \
  --top-k 10 \
  --skip-ingest \
  --gateway-url http://127.0.0.1:18789
```

> For `memu-engine`, default ingest mode is `noop` (pre-ingested search). Use `--memu-ingest-mode memory_store` only if your memory slot exposes `memory_store`.

### Useful flags for `run-retrieval`

- `--limit N` run first N questions
- `--sample-size N --sample-seed S` deterministic seeded subset sampling
- `--fail-fast` stop on first question failure
- `--db-root <dir>` per-container sqlite storage root for `openclaw-mem`
- `--openclaw-mem-cmd ...` override adapter command base when needed
- `--memory-core-profile <name>` isolated OpenClaw profile for `memory-core`
- `--skip-ingest` run search-only against existing memory state
- `--preindex-once` ingest/index selected dataset once, then run per-question search
- `--gateway-url/--gateway-token` for gateway-backed providers (`memu-engine`, `memory-lancedb`)
- `--memu-ingest-mode noop|memory_store` for memu ingestion strategy
- `--lancedb-recall-limit-factor N` candidate pool multiplier before container filtering
- `--memory-core-index-retries N` + `--memory-core-timeout-sec N` for timeout resilience
- `--memory-core-max-messages-per-session`, `--memory-core-max-message-chars`, `--memory-core-max-chars-per-session` for long-session ingest stabilization

## One-shot two-plugin baseline runner (Phase A)

```bash
scripts/run_two_plugin_baseline.sh \
  --profile configs/run-profiles/two-plugin-baseline.json
```

This orchestrator emits both provider reports and merged compare artifacts under `artifacts/full-benchmark/<run-group>/`.
See `docs/PHASE_A_EXECUTION.md` for fallback behavior and fast pilot mode.

## Phase A: QA correctness (LongMemEval-50, repo-local)

We also keep a small **QA correctness** harness for our repo-local `longmemeval-50.json` format.
This is a Phase-A calibration tool (not the official LongMemEval runner).

```bash
# Requires OPENAI_API_KEY in env
scripts/run_longmemeval50_qa_compare.sh --limit 20 --arms oracle observational
# writes to artifacts/qa-compare/<run-group>/summary.md
```

## One-shot Phase A/B compare (memory-lancedb baseline vs openclaw-mem-assisted ingest proxy)

```bash
scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --dataset data/datasets/longmemeval-50.json \
  --top-k 10 \
  --policies must must+nice
```

Deterministic long-run profile (stable run-group path for reproducible reruns):

```bash
scripts/run_phase_ab_longmemeval50.sh
# writes to artifacts/phase-ab-compare/phase-ab-longmemeval50-seed7-topk10/
```

If you need a separate receipt while preserving deterministic naming convention:

```bash
scripts/run_phase_ab_longmemeval50.sh --run-group phase-ab-longmemeval50-rerun-a
```

Multiseed (quality confidence):

```bash
scripts/run_phase_ab_longmemeval50_multiseed.sh
# writes per-seed runs under artifacts/phase-ab-compare/<prefix>-seedN/
# and an aggregate summary under artifacts/phase-ab-compare/<out-group>/multiseed-summary.{json,md}
```

Artifacts are written under `artifacts/phase-ab-compare/<run-group>/`:
- per-arm retrieval reports
- merged compare JSON (`compare-*.json`)
- short summary markdown (`compare-*.md`)
- derived experimental datasets (`derived-dataset-*.json`)

Optional:
- add `--include-observational` to run a third arm where each session is compressed into a compact log-like “observation” message (text-shape proxy; deterministic, no LLM).
- add `--smoke` for a cheap sanity run (small dataset + low limits). Or run:

```bash
scripts/smoke_phase_ab_compare.sh
```

Note:
- retrieval reports include `summary.by_question_type` so LongMemEval category deltas are inspectable (not just overall means).

> Current experimental arm is a documented **proxy mode**: openclaw-mem-style importance gating is applied at ingest-time by dataset filtering before `memory-lancedb` ingest. This isolates the ingestion-compression tradeoff without requiring a new live adapter-composition layer.

## One-shot sidecar pilot (memory-core vs openclaw-mem)

```bash
scripts/run_memory_core_vs_openclaw_mem.sh \
  --dataset examples/dual_language_mini.json \
  --top-k 5
```

Artifacts are written under `artifacts/sidecar-compare/<run-group>/`.
This path is isolated from the main OpenClaw system via an independent memory-core profile (`membench-memory-core`) and per-run openclaw-mem sqlite roots.

## One-shot comprehensive triplet (memory-core, memory-lancedb, openclaw-mem)

```bash
scripts/run_memory_triplet_comprehensive.sh \
  --benchmark longmemeval \
  --dataset-limit 100 \
  --question-limit 100 \
  --top-k 10
```

Artifacts are written under `artifacts/comprehensive-triplet/<run-group>/`.

### Reliability / debug controls (new)

The triplet orchestrator now supports provider-level watchdogs, progress logs, and fail-fast behavior so one stuck provider does not silently block the whole run:

```bash
scripts/run_memory_triplet_comprehensive.sh \
  --benchmark longmemeval \
  --dataset-limit 30 \
  --question-limit 10 \
  --top-k 5 \
  --provider-timeout-sec 900 \
  --progress-log artifacts/comprehensive-triplet/debug-progress.log
```

Useful flags:
- `--provider-timeout-sec <sec>`: hard wall-time timeout per provider run (default `1500`)
- `--fail-fast-provider`: stop remaining providers after first provider failure
- `--progress-log <path>`: timestamped progress log (default `<run-group>/progress.log`)

When a provider fails or times out, the run still emits `compare-*.json` / `compare-*.md` with structured failure status under `provider_status`, instead of aborting with only partial artifacts.

## Current implementation status

- `openclaw-mem`: retrieval-track adapter implemented (MVP, CLI-driven)
- `memory-core`: retrieval-track adapter implemented (isolated `--profile` mode)
- `memory-lancedb`: gateway-backed adapter implemented for canonical memory tools (`memory_store`/`memory_recall`/`memory_forget`)
- `memu-engine`: gateway-backed adapter implemented for `memory_search` (ingest modes: `noop` / `memory_store`)
- Canonical dataset conversion command available (`prepare-dataset`)

## Project plan and TODOs

- `docs/PROJECT_PLAN_AND_TODOS.md`
- `docs/FULL_BENCHMARK_PLAN.md` (two-plugin full report execution plan)
- `docs/PHASE_A_EXECUTION.md` (locked profile + one-shot baseline runner)

## Project layout

- `src/openclaw_memory_bench/cli.py` — main CLI
- `src/openclaw_memory_bench/protocol.py` — provider adapter protocol
- `src/openclaw_memory_bench/adapters/` — plugin adapters
- `docs/decisions/` — architecture decisions
- `docs/devlog/` — implementation progress logs

## License

MIT License. See `LICENSE`.

## Acknowledgements

This toolkit is inspired by the benchmark design ideas from:
- <https://github.com/supermemoryai/memorybench> (MIT)

When specific code-level adaptations are introduced, they will be explicitly documented in `ACKNOWLEDGEMENTS.md` with file-level references.
