# OpenClaw Memory Bench — Project Plan & TODOs

Last updated: 2026-02-13

## 1) Mission

Build a **neutral, reproducible, CLI-first benchmark toolkit** for OpenClaw memory-layer plugins (not SaaS leaderboard replication), with transparent artifacts the community can trust and reproduce.

Primary targets:
- `openclaw-mem`
- `memu-engine-for-OpenClaw`
- future OpenClaw memory plugins

## 2) Non-goals (for now)

- Not trying to publish universal "best memory system" rankings.
- Not optimizing for one composite score that hides tradeoffs.
- Not requiring interactive/human-in-the-loop operation for benchmark runs.

## 3) Current status snapshot

### Completed

- [x] New standalone private repo created (`openclaw-memory-bench`), MIT licensed.
- [x] Proper upstream acknowledgement policy documented for memorybench inspiration.
- [x] Retrieval-track MVP implemented:
  - [x] Dataset loader
  - [x] Deterministic retrieval metrics (Hit@K / Precision@K / Recall@K / MRR / nDCG)
  - [x] Retrieval runner + JSON report output
  - [x] `run-retrieval` command
- [x] `openclaw-mem` adapter implemented (CLI-driven) with per-container DB isolation.
- [x] `memory-lancedb` adapter implemented via canonical memory tools (`memory_store`/`memory_recall`/`memory_forget`).
- [x] `memu-engine` adapter implemented via Gateway `tools/invoke` baseline (`memory_search`, optional `memory_store`).
- [x] Canonical dataset conversion command implemented (`prepare-dataset`) for:
  - [x] LoCoMo
  - [x] LongMemEval
  - [x] ConvoMem
- [x] CI baseline added (lint + tests + smoke path + artifact upload).
- [x] Retrieval reports now embed run-manifest metadata (toolkit/git/dataset/provider/runtime).
- [x] `prepare-dataset` now writes sidecar metadata (`*.meta.json`) with source URLs.
- [x] Phase A baseline profile + orchestrator script added for two-plugin runs (`configs/run-profiles/two-plugin-baseline.json`, `scripts/run_two_plugin_baseline.sh`).
- [x] Comprehensive triplet orchestrator added (`scripts/run_memory_triplet_comprehensive.sh`).
- [x] Sidecar compare orchestrator added (`scripts/run_memory_core_vs_openclaw_mem.sh`).
- [x] Preindex-once runner mode added (`--preindex-once` / `--memory-core-preindex-once`) for timeout diagnosis.
- [x] Preliminary publication pack drafted (`PRELIMINARY_RESULTS.md`, discussion draft, public-release checklist).
- [x] Phase A/B baseline-vs-assisted compare runner added (`scripts/run_lancedb_vs_openclaw_mem_assisted.sh`).
- [x] Full benchmark plan refocused to memory-lancedb baseline vs openclaw-mem-assisted ingest proxy (GTM/falsification framing).

### Verified locally

- [x] Tests passing (`pytest`)
- [x] Lint passing (`ruff`)
- [x] `openclaw-mem` retrieval smoke run successful
- [x] `memu-engine` search-only smoke path successful

## 4) Architecture plan (v0.1 → v0.3)

## v0.1 (Foundation) — mostly done

- CLI core (`doctor`, `plan`, `prepare-dataset`, `run-retrieval`)
- Provider adapter protocol
- Deterministic retrieval scoring
- JSON artifacts for reproducibility

## v0.2 (Comparability hardening)

- Run-manifest embedding into report outputs (config + runtime + git commit).
- Dataset schema validation and strict error taxonomy.
- Provider capability matrix and run profiles (recommended defaults).
- Better failure diagnostics (ingest/search/parse/citation phases).

## v0.3 (Community-ready baseline)

- E2E optional track (retrieval → answer model → judge model).
- Cost + latency rollups with stable report schema versioning.
- Public docs for reproducible community submissions.
- Optional approval-gated publish flow for official reference reports.

## 5) Priority TODO list

## P0 — Next work block (high priority)

- [x] Embed run manifest in retrieval reports:
  - [x] toolkit version
  - [x] git commit
  - [x] dataset source + conversion config
  - [x] provider adapter config (sanitized)
  - [x] runtime metadata (python/os)
- [x] Add schema validation for converted datasets and final reports.
- [x] Standardize error codes and failure categories in runner output.

## P1 — Important

- [ ] Provider capability matrix doc (`supports_ingest`, `supports_clear`, `search_only`, etc.).
- [ ] Add canonical "recipe" docs:
  - [ ] openclaw-mem baseline run recipe
  - [ ] memu-engine baseline run recipe
- [ ] Add explicit **comparison-mode matrix** docs/runs:
  - [x] standalone backend + assisted-ingest proxy runs (Phase A/B)
  - [ ] standalone sidecar runs
  - [ ] sidecar + backend combined stack runs (to avoid interpretation ambiguity)
- [x] Improve `memu-engine` session-id extraction robustness from citations/snippets.
- [x] Add deterministic sample-splitting controls (seeded subsets).

## P2 — Nice to have

- [ ] E2E track scaffolding (answer/judge).
- [ ] Compare command for multi-provider runs over same manifest.
- [ ] HTML report rendering in addition to JSON.
- [ ] Optional telemetry summary for run-cost estimation.

## 6) Dataset conversion TODOs

- [ ] Validate LoCoMo evidence-to-session mapping with spot checks.
- [ ] Re-check LongMemEval relevant-session extraction (`has_answer`) on edge cases.
- [ ] Expand ConvoMem evidence matching quality checks.
- [ ] Add converter unit tests for all three benchmarks.

## 7) Definition of done (for first public release)

- [ ] Reproducible runs from clean environment with pinned instructions.
- [ ] Two plugin adapters production-ready (`openclaw-mem`, `memu-engine`).
- [ ] Canonical datasets convert + validate + run consistently.
- [ ] CI green on main for lint/tests/basic smoke.
- [ ] Documentation complete enough for third-party reproduction.

## 8) Pause/resume handoff notes

When resuming later, start from this sequence:

1. `uv sync`
2. `uv run pytest -q && uv run ruff check`
3. Re-run smoke:
   - `uv run openclaw-memory-bench run-retrieval --provider openclaw-mem --dataset examples/mini_retrieval.json --top-k 5`
4. Continue P0 tasks in this order:
   - manifest embedding
   - schema validation
   - failure taxonomy

## 9) Tracking conventions

- Keep milestone logs in: `docs/devlog/`
- Keep decision records in: `docs/decisions/`
- Two-plugin execution plan: `docs/FULL_BENCHMARK_PLAN.md`
- Update this file as the single source of truth for plan + TODOs.
