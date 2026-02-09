# Draft: OpenClaw GitHub Discussion (Preliminary Benchmark Results)

Title suggestion:

`Preliminary memory plugin benchmark results (openclaw-memory-bench) + request for replication feedback`

Body draft:

---

Hi OpenClaw community,

We are sharing **preliminary** results from an early, reproducible benchmark harness for OpenClaw memory-layer plugins:

- Repo: `phenomenoner/openclaw-memory-bench`
- Scope: CLI-first, non-interactive retrieval benchmarking
- Current note: `PRELIMINARY_RESULTS.md`

## Why we built this

We wanted a neutral way to compare memory-layer behavior in OpenClaw with:

- deterministic retrieval metrics (hit@k, recall@k, MRR, nDCG)
- latency rollups (p50/p95)
- reproducible artifacts + manifests (dataset hash, runtime metadata, config shape)

## Interpretation guardrail (important)

Current snapshots compare provider adapters in their current benchmark modes:

- `openclaw-mem` here = standalone sidecar-engine run in this harness
- `memory-core` / `memory-lancedb` = backend/canonical-memory paths

So this is **not yet** a complete combined-stack ranking (for example, `openclaw-mem + memory-core` vs `openclaw-mem + memory-lancedb`).

## Preliminary snapshot

From current runs:

- `openclaw-mem` shows strong speed/stability in these workloads
- `memory-core` shows promising quality on small subsets but currently faces ingest/index timeout issues in sustained runs
- `memory-lancedb` is stable in smoke runs in our environment, but slower and lower-scoring than `openclaw-mem` in this early snapshot

Please treat this as directional, not final ranking.

## Repro entry points

```bash
scripts/run_two_plugin_baseline.sh --profile configs/run-profiles/two-plugin-baseline.json
scripts/run_memory_core_vs_openclaw_mem.sh --dataset examples/dual_language_mini.json --top-k 5
scripts/run_memory_triplet_comprehensive.sh --benchmark longmemeval --dataset-limit 2 --question-limit 2 --top-k 5
```

## We’d love feedback on

1. Better run-shape for `memory-core` to avoid index timeout skew
2. Additional datasets or stratified slices you want included
3. Report schema improvements for community submissions
4. Any reproducibility gaps in setup/docs

If you replicate, please share:
- command + commit hash
- environment details
- artifact paths

Thanks — suggestions and critiques are very welcome.

---

Posting recommendation:
- Prefer **GitHub Discussions** in `openclaw/openclaw` under a category like `Show and tell` / `Ideas` / `General` (whichever exists).
- If Discussions are unavailable, open a single issue labeled `benchmark` + `community-feedback`.
