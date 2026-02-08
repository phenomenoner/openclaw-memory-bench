# Full Benchmark Plan — openclaw-mem vs memu-engine

Last updated: 2026-02-08

## Goal

Produce a reproducible, apples-to-apples benchmark report for two OpenClaw memory-layer plugins:

1. `openclaw-mem`
2. `memu-engine`

Outputs should be machine-readable artifacts plus one human summary report.

## Definition of "full report"

A run package that includes:
- Retrieval metrics: Hit@K / Precision@K / Recall@K / MRR / nDCG
- Latency metrics: p50 / p95 / mean
- Failure breakdown (ingest/search/parse)
- Reproducibility manifest (toolkit/git/dataset/provider/runtime)
- Same dataset slice + same `top_k` across providers

## What is already done

- Retrieval benchmark runner + metrics implemented.
- Adapters available for both providers (`openclaw-mem`, `memu-engine`).
- Canonical dataset converters available (`locomo`, `longmemeval`, `convomem`).
- Report manifest embedding implemented (`retrieval-report/v0.2`).
- CI baseline is green.

## Remaining work to unlock the first full two-plugin report

## Phase A — Fairness baseline lock (required)

1. Freeze run recipe
   - select benchmark dataset + fixed subset size (e.g., LongMemEval-100)
   - set shared params (`top_k`, `limit`, `skip_ingest` policy)
2. Create a versioned run profile file in repo (`configs/run-profiles/two-plugin-baseline.json`)
3. Add dataset + report schema validation gate

Deliverable: one approved baseline profile used by both plugins.

## Phase B — Provider capability alignment (required)

1. Confirm `memu-engine` ingest mode for fair comparison:
   - preferred: `memory_store` available and enabled
   - fallback: explicit pre-ingest pipeline + `--skip-ingest` for both providers
2. Document capability matrix (`supports_ingest`, `search_only`, etc.)
3. Add robust error taxonomy in reports

Deliverable: both providers can run under one comparable protocol.

## Phase C — Two-plugin orchestration (required)

1. Add orchestration command or script (`scripts/run_two_plugin_baseline.sh`) that runs:
   - openclaw-mem baseline
   - memu-engine baseline
2. Add merge step to produce consolidated comparison JSON:
   - `artifacts/compare-<run-id>.json`
3. Add human-readable summary markdown:
   - `artifacts/compare-<run-id>.md`

Deliverable: one-shot command to generate full report package.

## Phase D — Quality hardening (high priority)

1. Add converter unit tests for LoCoMo/LongMemEval/ConvoMem edge cases
2. Add failure-injection tests (timeout/tool invoke errors/invalid payload)
3. Add CI smoke for two-plugin compare path (small limit)

Deliverable: stable repeatability for future reruns.

## Suggested execution order

1. Schema validation + error taxonomy
2. Baseline run profile file
3. memu ingest alignment decision
4. Two-plugin orchestrator + compare report
5. Execute first official run and publish artifacts

## Risks / blockers

- `memu-engine` environments without `memory_store` ingest may reduce comparability.
- Canonical dataset evidence mapping may need spot-check adjustments for fairness.
- Tool invoke latency variability can skew p95 if not controlled.

## First official report target (proposed)

- Dataset: LongMemEval
- Size: 100 questions
- Params: `top_k=10`, deterministic retrieval only
- Providers:
  - `openclaw-mem` (per-container DB root)
  - `memu-engine` (`memory_store` ingest if available; otherwise documented pre-ingest mode)
- Outputs:
  - two retrieval reports
  - one merged compare JSON/MD
  - reproducibility manifest bundle
