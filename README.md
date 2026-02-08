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

## Quickstart (scaffold stage)

```bash
uv sync
uv run openclaw-memory-bench doctor
uv run openclaw-memory-bench plan --provider openclaw-mem --benchmark locomo
```

> Note: Adapter execution is currently scaffolded and under active development.

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
