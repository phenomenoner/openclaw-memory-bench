# Phase A/B Milestone Report — LongMemEval-50 (Draft)

- Updated: 2026-02-14 05:36 Asia/Taipei
- Status: Draft (artifact-backed narrative + replay contract)

## Goal
Compare:
1) **Baseline**: `memory-lancedb` canonical ingest (all sessions)
2) **Assisted**: `openclaw-mem + memory-lancedb` via importance-gated derived dataset proxy (`must`, `must+nice`)

This report is redaction-safe: aggregate metrics only, no raw private memory payloads.

## Latest reproducible artifact currently available
- Run group: `20260213T172602Z-phase-ab-smoke`
- Compare markdown: `artifacts/phase-ab-compare/20260213T172602Z-phase-ab-smoke/compare-20260213T172602Z-phase-ab-smoke.md`
- Compare JSON: `artifacts/phase-ab-compare/20260213T172602Z-phase-ab-smoke/compare-20260213T172602Z-phase-ab-smoke.json`
- Dataset used in this artifact: `examples/dual_language_mini.json` (smoke profile)

## Tradeoff summary (from latest artifact)
### Baseline metrics
- hit@k: `1.0000`
- precision@k: `0.2000`
- recall@k: `1.0000`
- mrr: `1.0000`
- ndcg@k: `1.0000`
- latency p50/p95: `154.13 / 154.13 ms`

### Experimental (`must`) vs baseline
- Compression (items/chars): `0.125 / 0.155`
- Δ hit@k: `+0.0000`
- Δ precision@k: `+0.0000`
- Δ recall@k: `+0.0000`
- Δ mrr: `+0.0000`
- Δ ndcg@k: `+0.0000`
- Δ p50/p95: `+35.03 / +35.03 ms`
- Win rule pass: `False` (`p95_gain=-0.227`, `recall_drop=0.000`, `ndcg_delta=0.000`)

## by_question_type narrative check
The latest compare JSON includes `summary.by_question_type` for both baseline and experimental arms.

Observed in the latest artifact:
- Only one question type bucket appears: `cross-lingual` (sample size = 1)
- Quality parity holds in this bucket (`hit@k`, `recall@k`, `mrr`, `ndcg@k` unchanged)
- Latency regresses in this bucket for experimental (`+35.03 ms` p95)

Interpretation: the type-level section works and is informative, but the smoke sample is too small for milestone claims.

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

### Deterministic smoke replay (for quick regression check)
```bash
cd /root/.openclaw/workspace/openclaw-memory-bench
scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --smoke \
  --run-group 20260213T172602Z-phase-ab-smoke
```

## Next gate to mark milestone complete
Populate this report with LongMemEval-50 artifact-backed rows (`must`, `must+nice`) and link the final compare JSON/MD produced by the full run.
