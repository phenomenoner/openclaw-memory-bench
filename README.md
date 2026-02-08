# openclaw-memory-bench

CLI-first benchmark toolkit for **OpenClaw memory-layer plugins**.

This project is designed to provide a reproducible, non-interactive evaluation workflow for memory plugins such as:
- `openclaw-mem`
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
- `--fail-fast` stop on first question failure
- `--db-root <dir>` per-container sqlite storage root for `openclaw-mem`
- `--openclaw-mem-cmd ...` override adapter command base when needed
- `--skip-ingest` run search-only against existing memory state
- `--gateway-url/--gateway-token` for gateway-backed providers (`memu-engine`)
- `--memu-ingest-mode noop|memory_store` for memu ingestion strategy

## One-shot two-plugin baseline runner (Phase A)

```bash
scripts/run_two_plugin_baseline.sh \
  --profile configs/run-profiles/two-plugin-baseline.json
```

This orchestrator emits both provider reports and merged compare artifacts under `artifacts/full-benchmark/<run-group>/`.
See `docs/PHASE_A_EXECUTION.md` for fallback behavior and fast pilot mode.

## Current implementation status

- `openclaw-mem`: retrieval-track adapter implemented (MVP, CLI-driven)
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
