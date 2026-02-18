# Hybrid stage2 latency-cap sensitivity (smoke q2/s8)

- Updated: 2026-02-19 02:08 Asia/Taipei
- Scope: focused hybrid sensitivity slice on `artifacts/smoke-input/longmemeval-50-smoke-q2-s8.json`
- Contract: `openclaw-memory-bench/phase-ab-compare-report/v0.3`

## Runs
- Tight cap (`--hybrid-stage2-max-ms 20`): `phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap20`
- Default cap (`--hybrid-stage2-max-ms 600`): `phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap600`
- Cap off (`--hybrid-stage2-max-ms 0`): `phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap0`

## Stage-count + latency receipts
- Tight cap (20ms): stage2 used/skipped/not-triggered = `0/2/0`, hybrid p95 = `303.28 ms` (Δ p95 vs baseline `+1.53 ms`)
- Default cap (600ms): stage2 used/skipped/not-triggered = `2/0/0`, hybrid p95 = `524.15 ms` (Δ p95 vs baseline `+239.73 ms`)
- Cap off (0ms=>disabled): stage2 used/skipped/not-triggered = `2/0/0`, hybrid p95 = `561.50 ms` (Δ p95 vs baseline `+287.51 ms`)

## Interpretation (for recommendation text)
- Tight cap forces `stage2_skipped_budget` and materially bounds latency inflation on this smoke slice.
- Default/off caps both allow full stage2 usage on all questions in this slice; latency overhead remains large while recall delta stays neutral here.
- Recommendation text should treat stage2 latency cap as a first-class safety knob until full LongMemEval-50 hybrid run is stable.

## Replay commands
```bash
cd /root/.openclaw/workspace/openclaw-memory-bench
scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --dataset artifacts/smoke-input/longmemeval-50-smoke-q2-s8.json \
  --top-k 10 \
  --sample-seed 7 \
  --policies must must+nice \
  --include-hybrid \
  --hybrid-stage2-max-ms 20 \
  --run-group phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap20

scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --dataset artifacts/smoke-input/longmemeval-50-smoke-q2-s8.json \
  --top-k 10 \
  --sample-seed 7 \
  --policies must must+nice \
  --include-hybrid \
  --hybrid-stage2-max-ms 600 \
  --run-group phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap600

scripts/run_lancedb_vs_openclaw_mem_assisted.sh \
  --dataset artifacts/smoke-input/longmemeval-50-smoke-q2-s8.json \
  --top-k 10 \
  --sample-seed 7 \
  --policies must must+nice \
  --include-hybrid \
  --hybrid-stage2-max-ms 0 \
  --run-group phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap0
```

## Artifact pointers
- `artifacts/phase-ab-compare/phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap20/compare-phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap20.json`
- `artifacts/phase-ab-compare/phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap600/compare-phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap600.json`
- `artifacts/phase-ab-compare/phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap0/compare-phase-ab-hybrid-smoke-q2-s8-seed7-topk10-cap0.json`
