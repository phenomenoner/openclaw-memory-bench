# Full Benchmark Plan — memory-lancedb baseline vs openclaw-mem-assisted ingest

Last updated: 2026-02-13

## Goal

Produce a reproducible, GTM-ready (or falsification-ready) benchmark package answering:

**Does openclaw-mem first-stable importance-gated ingest improve outcome tradeoffs over native memory-lancedb alone?**

Scope for this phase focuses on a two-arm comparison:

1. **Baseline**: `memory-lancedb` canonical memory tools (`memory_store` / `memory_recall` / `memory_forget`), ingest all sessions.
2. **Experimental (proxy)**: openclaw-mem-style importance-gated ingest, implemented as derived dataset filtering (`must` or `must+nice`) before `memory-lancedb` ingest.

> Limitation: this phase does not yet chain a live openclaw-mem adapter in front of memory-lancedb. It isolates the ingestion gating effect with a reproducible proxy.

## Experiment matrix (Phase A/B)

- Provider runtime: `memory-lancedb` (same adapter + same gateway config for all arms)
- Dataset split policy:
  - `baseline/all`
  - `experimental/must`
  - `experimental/must+nice`
- Shared run knobs:
  - fixed dataset file hash
  - fixed `top_k`
  - deterministic sample seed
  - identical recall limit factor and session key

## Optional extension (Phase C) — observational compression (thought-link)

Inspired by Mastra’s “Observational Memory” pattern, add a third arm that keeps **all sessions** but changes the *text shape*:

- **Observational arm (proxy)**: build a derived dataset where each session is compressed into a compact, log-like “observation” message (deterministic heuristic compressor; no LLM).

Purpose:
- isolate whether stable, compact, log-style text improves retrieval tradeoffs even without importance-gated filtering.

Runner knob:
- add `--include-observational` to the Phase A/B runner.

> Limitation: this is a proxy for the *format* benefits, not the full Mastra-style observer/reflector pipeline.

## Metrics (required)

Required reporting:
- Report all retrieval + latency metrics **overall** and **by `question_type`** (LongMemEval category breakdown).

### Retrieval quality
- Hit@K
- Recall@K
- Precision@K
- MRR
- nDCG

### Latency
- search latency p50
- search latency p95

### Ingest volume / compression
- `#items stored` (session-level ingest count estimate)
- `total chars` ingested estimate
- `vector count` estimate (1 vector per stored session in current adapter behavior)
- compression ratio vs baseline (items + chars)

### Cost metadata
- If available from provider/tool payloads, include in compare artifact.
- Current v0.2 retrieval reports do not provide tokenized cost telemetry; compare artifact records this as unavailable.

## Counterfactual ON/OFF plan for the two pillars

This section adds a falsifiable ON/OFF design while keeping current Phase A/B priorities intact.

### Scope and sequencing
- **Pillar A (execute now):** context pack contract hardening effects.
- **Pillar B (pre-register now, execute later):** learning-record/self-improving loop effects.
- Do not mix A and B rollout in the same implementation window.

### Experimental arms
- `A0/B0`: baseline behavior (current pack contract, no learning block).
- `A1/B0`: Pillar A ON (contract hardening enabled).
- `A0/B1`: Pillar B ON (reserved; spec only until Pillar A gate passes).
- `A1/B1`: both ON (reserved for later confirmation run).

For the current cycle, run only `A0/B0` vs `A1/B0`.

### Metric definitions (anti-gaming, explicit)
- **Recall@K / Precision@K / nDCG@K**:
  - `K` must be fixed per run and written in manifest (`top_k`, default `10`).
  - relevance source must be dataset `relevant_session_ids` (no post-hoc re-labeling).
- **Citation coverage**:
  - `1 - (included_without_citation_count / included_count)`.
  - also report numerator/denominator explicitly.
- **Rationale coverage**:
  - `1 - (included_without_reason_count / included_count)`.
- **Determinism pass rate**:
  - For each fixed DB/query case, run 5 repeats and compare canonicalized JSON (excluding timestamp fields only).
  - pass rate denominator must be number of distinct cases, not total runs.
- **Budget exclusion rate**:
  - `excluded_by_budget / total_candidates`.
- **Latency p50/p95**:
  - measured on the retrieval+pack path under the same runner/hardware profile recorded in manifest.

### Decision posture
- Treat this as a non-regression gate first (quality and determinism).
- Only after Pillar A gate passes should Pillar B execution be scheduled.

## Reproducibility contract

Each run package must include a manifest with:
- toolkit git commit
- source dataset path + sha256
- seed and sampling settings
- `top_k`
- provider config (sanitized, no tokens)
- explicit experimental policy / proxy-mode note

## Interpretation and win criteria

Do not use a single opaque score. Read as a tradeoff curve:

- x-axis: compression ratio (items/chars retained)
- y-axes: Recall@K / Precision@K / nDCG / p95 latency

### Win definition for GTM claim (default)

Experimental policy is a **win** when all are true relative to baseline:
1. p95 latency improves by at least 20%
2. Recall@K drop is no worse than 3 percentage points
3. nDCG is non-negative delta

If no policy satisfies these thresholds, result is treated as **falsification-ready** evidence that current gating does not meet launch claim under tested settings.

## One-shot runner (copy/paste)

```bash
uv sync

scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --dataset data/datasets/longmemeval-50.json \
  --top-k 10 \
  --sample-seed 7 \
  --policies must must+nice
```

Outputs:
- `artifacts/phase-ab-compare/<run-group>/baseline/retrieval-report.json`
- `artifacts/phase-ab-compare/<run-group>/experimental-*/retrieval-report.json`
- `artifacts/phase-ab-compare/<run-group>/compare-<run-group>.json`
- `artifacts/phase-ab-compare/<run-group>/compare-<run-group>.md`

## Suggested dataset choices

Primary:
- LongMemEval converted slices (e.g., 50 / 100 questions)

Secondary sensitivity checks:
- LoCoMo slice
- ConvoMem slice

Run same matrix on at least one secondary dataset before public positioning claims.
