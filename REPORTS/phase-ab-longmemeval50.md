# Phase A/B Milestone Report — LongMemEval-50 (Draft)

- Updated: 2026-02-15 03:26 Asia/Taipei
- Status: Draft (LongMemEval-50 artifact-backed narrative + replay contract)

## Goal
Compare:
1) **Baseline**: `memory-lancedb` canonical ingest (all sessions)
2) **Assisted**: `openclaw-mem + memory-lancedb` via importance-gated derived dataset proxy (`must`, `must+nice`)

This report is redaction-safe: aggregate metrics only, no raw private memory payloads.

## Latest reproducible artifact currently available
- Run group: `phase-ab-longmemeval50-seed7-topk10`
- Compare markdown: `artifacts/phase-ab-compare/phase-ab-longmemeval50-seed7-topk10/compare-phase-ab-longmemeval50-seed7-topk10.md`
- Compare JSON: `artifacts/phase-ab-compare/phase-ab-longmemeval50-seed7-topk10/compare-phase-ab-longmemeval50-seed7-topk10.json`
- Dataset: `data/datasets/longmemeval-50.json` (`sha256=ca8e6e63c1224c79fc37c875e7a50e49bbc410e563ffd8926b0ffba3b29e984b`)
- Toolkit commit: `17448d7`

## Tradeoff summary (LongMemEval-50 aggregate)
### Baseline metrics
- hit@k: `0.8980`
- precision@k: `0.0898`
- recall@k: `0.8980`
- mrr: `0.7370`
- ndcg@k: `0.7764`
- latency p50/p95: `194.68 / 225.72 ms`

### Experimental (`must`) vs baseline
- compression (items/chars): `0.540 / 0.582`
- Δ hit@k: `-0.2653`
- Δ precision@k: `-0.0265`
- Δ recall@k: `-0.2653`
- Δ mrr: `-0.2878`
- Δ ndcg@k: `-0.2838`
- Δ p50/p95: `+2.03 / +24.96 ms`
- win rule pass: `False` (`p95_gain=-0.111`, `recall_drop=0.265`, `ndcg_delta=-0.284`)

### Experimental (`must+nice`) vs baseline
- compression (items/chars): `0.928 / 0.976`
- Δ hit@k: `+0.0204`
- Δ precision@k: `+0.0020`
- Δ recall@k: `+0.0204`
- Δ mrr: `+0.0829`
- Δ ndcg@k: `+0.0667`
- Δ p50/p95: `+15.66 / +17.95 ms`
- win rule pass: `False` (`p95_gain=-0.080`, `recall_drop=-0.020`, `ndcg_delta=+0.067`)

## Interpretation (tight)
- `must` compresses aggressively and materially degrades retrieval quality; not viable for this milestone objective.
- `must+nice` mostly preserves corpus size and improves quality metrics, but still increases latency enough to fail the current win rule.
- Net: under current proxy-mode filtering, neither policy is a strict “win” against the baseline rule; `must+nice` is the only quality-positive candidate and should be treated as a quality/latency tradeoff, not a strict upgrade.

## Recommendation memo (decision options)

### Option 1 — quality-first (keep baseline semantics, accept latency-quality tradeoff)
- Select `must+nice` as a candidate only if CK accepts relaxed operational constraints (allowing +17.95 ms p95 and +15.66/17.95 ms latency uplift on LongMemEval-50).
- This arm preserves quality most (`+0.0204` hit / `+0.0667` nDCG / `+0.0829` mRR) but still fails the strict win rule (`p95_gain=-0.080`, `recall_drop=-0.020`).
- Practical action: keep as experimental, no auto-default yet; monitor recall drift on larger slices.

### Option 2 — latency-first (freeze baseline by default)
- Keep baseline as default (`0` compression policy) because both filtered arms violate latency/recall rule under current gate.
- This avoids regression risk for recall and p95 while retaining known behavior.
- Practical action: only revisit after upstream recall/serving optimization or after adding a stronger must+nice selector.

## by_question_type narrative check
The latest compare JSON includes `summary.by_question_type` for all arms.

Observed in the latest artifact:
- One bucket appears: `single-session-user`.
- Baseline and both experimental arms each report `49 succeeded / 1 failed`.
- The single failure class is consistent (`UNEXPECTED_ERROR` at ingest), so by-type quality values mirror aggregate values.

Interpretation: type-level reporting is functioning, but this dataset slice does not test cross-type robustness.

## Replay commands
### Milestone target run (LongMemEval-50)
```bash
cd /root/.openclaw/workspace/openclaw-memory-bench
uv sync
scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --dataset data/datasets/longmemeval-50.json \
  --top-k 10 \
  --sample-seed 7 \
  --policies must must+nice
```

### Deterministic smoke replay (quick regression check)
```bash
cd /root/.openclaw/workspace/openclaw-memory-bench
scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --smoke \
  --run-group 20260213T172602Z-phase-ab-smoke
```

## Milestone publish footer (artifact pointers)
- Command for replay:
  ```bash
  cd /root/.openclaw/workspace/openclaw-memory-bench
  uv sync
  scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
    --dataset data/datasets/longmemeval-50.json \
    --top-k 10 \
    --sample-seed 7 \
    --policies must must+nice
  ```
- Canonical artifacts (LongMemEval-50):
  - [Compare markdown](artifacts/phase-ab-compare/phase-ab-longmemeval50-seed7-topk10/compare-phase-ab-longmemeval50-seed7-topk10.md)
  - [Compare JSON](artifacts/phase-ab-compare/phase-ab-longmemeval50-seed7-topk10/compare-phase-ab-longmemeval50-seed7-topk10.json)
  - [Run-group pointer](artifacts/phase-ab-compare/compare-latest.md)
  - [Benchmark report](REPORTS/phase-ab-longmemeval50.md)

## Next gate to mark milestone complete
Freeze this report as the milestone baseline and run the observational add-on (`--include-observational`) to decide whether latency/quality tradeoffs remain stable with a third arm.
