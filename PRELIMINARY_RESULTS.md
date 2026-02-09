# Preliminary Results (2026-02-09)

> Status: **preliminary**. These are early benchmark snapshots intended for replication and feedback, not final rankings.

## Scope of this note

This summary focuses on currently interpretable runs for:
- `openclaw-mem`
- `memory-core`
- `memory-lancedb`

`memu-engine` is intentionally excluded from this preliminary public-facing note until adapter mode/stability is finalized.

## Interpretation guardrail: provider roles are not equivalent architecture classes

- `openclaw-mem` in this benchmark currently means a **standalone sidecar-engine run** (benchmark-managed sqlite + `openclaw-mem` CLI ingest/search).
- `memory-core` and `memory-lancedb` are evaluated as **backend/canonical-memory paths**.
- Therefore, current numbers should be read as **adapter/provider-level snapshots**, not as a complete “best production stack” ranking.

### Not included yet (important)

- We have **not** finished a full matrix comparing combined stacks such as:
  - `openclaw-mem + memory-core`
  - `openclaw-mem + memory-lancedb`
- So current `openclaw-mem` numbers are **not** “best-of-two backend combination” numbers.

## Included artifacts

- Phase A baseline (LongMemEval 100q):
  - `artifacts/full-benchmark/20260208T150451Z-phase-a-official/compare-20260208T150451Z-phase-a-official.{json,md}`
- Comprehensive triplet smoke (2q):
  - `artifacts/comprehensive-triplet/20260209T010809Z-smoke-triplet/compare-20260209T010809Z-smoke-triplet.{json,md}`
  - `artifacts/comprehensive-triplet/20260209T014757Z-smoke-triplet-fix1/compare-20260209T014757Z-smoke-triplet-fix1.{json,md}`
- Sidecar dual-language pilot (4q):
  - `artifacts/sidecar-compare/20260209T002132Z-ck-sidecar-pilot-cjkfix3/compare-20260209T002132Z-ck-sidecar-pilot-cjkfix3.{json,md}`

## Snapshot

### A) LongMemEval Phase A (100q, `openclaw-mem`)

- hit@k: **0.9200**
- recall@k: **0.8605**
- mrr: **0.8695**
- ndcg@k: **0.8352**
- search latency p50/p95: **150.40 / 193.89 ms**
- failures: **0/100**

### B) Comprehensive triplet smoke (2q)

Across both smoke runs:
- `openclaw-mem`: **2/2 succeeded**, hit@k **1.0**, p50 **165.7–222.3 ms**
- `memory-lancedb`: **2/2 succeeded**, hit@k **0.5**, p50 **772.1–1078.4 ms**
- `memory-core`: **0/2 succeeded** (ingest timeout), failure phase concentrated at ingest/index

### C) Sidecar dual-language pilot (4q)

- `openclaw-mem`: **4/4 succeeded**, hit@k **1.0**, mrr **0.875**, ndcg@k **0.9077**, p50 **209.99 ms**
- `memory-core`: **3/4 succeeded**, hit@k **1.0** (on succeeded subset), mrr **1.0**, ndcg@k **1.0**, p50 **21287.68 ms**

## Preliminary interpretation (within currently tested provider modes)

- `openclaw-mem` currently shows the strongest **speed + stability** profile in these runs.
- `memory-core` shows high potential quality on small subsets but is currently blocked by ingest/index timeout behavior for sustained runs.
- `memory-lancedb` is currently stable in smoke runs, with slower latency and lower retrieval quality than `openclaw-mem` in this snapshot.
- These points do **not** yet answer which **combined deployment stack** is best overall.

## Known limitations

- Not all providers have completed equal-scale runs under identical stable conditions.
- `memory-core` timeout behavior can dominate outcomes and requires additional run-shape controls.
- Small-sample results (2q/4q) are directional only.

## Repro commands (examples)

```bash
# Phase A profile run
scripts/run_two_plugin_baseline.sh \
  --profile configs/run-profiles/two-plugin-baseline.json

# Sidecar pilot (memory-core vs openclaw-mem)
scripts/run_memory_core_vs_openclaw_mem.sh \
  --dataset examples/dual_language_mini.json \
  --top-k 5

# Comprehensive triplet smoke
scripts/run_memory_triplet_comprehensive.sh \
  --benchmark longmemeval \
  --dataset-limit 2 \
  --question-limit 2 \
  --top-k 5
```

Feedback and replication reports are welcome.
