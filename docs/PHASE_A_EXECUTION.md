# Phase A Execution Guide (two-plugin baseline)

Last updated: 2026-02-08

## What Phase A delivers

- Locked baseline profile for fair-ish two-plugin runs.
- One-shot orchestration script that:
  1) prepares canonical dataset,
  2) runs retrieval benchmark for `openclaw-mem`,
  3) runs retrieval benchmark for `memu-engine` (try `memory_store`, fallback to `noop + --skip-ingest`),
  4) emits merged compare artifacts (`.json` + `.md`).

## Profile file

- `configs/run-profiles/two-plugin-baseline.json`

Default baseline:
- benchmark: `longmemeval`
- dataset limit: `100`
- top_k: `10`

## Run command

```bash
# Run from your local checkout of the repo.
# Example (OpenClaw host default workspace):
#   cd /root/.openclaw/workspace/openclaw-memory-bench
cd /path/to/openclaw-memory-bench

scripts/run_two_plugin_baseline.sh \
  --profile configs/run-profiles/two-plugin-baseline.json
```

Optional fast validation run:

```bash
scripts/run_two_plugin_baseline.sh \
  --profile configs/run-profiles/two-plugin-baseline.json \
  --dataset-limit 20 \
  --question-limit 5 \
  --run-label pilot
```

## Output layout

Under `artifacts/full-benchmark/<run-group>/`:

- `openclaw-mem/retrieval-report.json`
- `memu-engine/retrieval-report.json`
- `compare-<run-group>.json`
- `compare-<run-group>.md`
- `profile.lock.json`
- `dataset.meta.json`

## Notes on comparability

- `memu-engine` ingest via `memory_store` can be expensive/slow depending on slot implementation.
- If ingest fails, Phase A falls back to `noop + --skip-ingest` and records fallback reason.
- This fallback keeps pipeline progress but may reduce strict comparability. Phase B will harden this.
