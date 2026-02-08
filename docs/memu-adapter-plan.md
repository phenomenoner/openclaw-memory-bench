# memu-engine adapter plan

Target plugin:
- https://github.com/duxiaoxiong/memu-engine-for-OpenClaw

## Observed integration model

`memu-engine` runs as an OpenClaw plugin and exposes `memory_search` / `memory_get` tool slot behavior,
with SQLite backend managed by MemU internals.

## Adapter options

### Option A (preferred): Gateway tool invocation

Use OpenClaw Gateway `/tools/invoke` with memory slot assigned to `memu-engine`:
- ingest via plugin watcher (session files / markdown paths)
- search via `memory_search`
- get full text via `memory_get`

Pros:
- Closer to real OpenClaw runtime behavior
- Validates plugin integration, not only raw DB state

Cons:
- Requires gateway running and configured plugin slot

### Option B: direct DB/API probing

Read plugin-managed SQLite directly for retrieval checks.

Pros:
- deterministic and fast

Cons:
- may diverge from actual memory tool behavior used by agents

## Status update (2026-02-08)

Option A baseline has been implemented:
- Adapter path: `src/openclaw_memory_bench/adapters/memu_engine.py`
- Search: `memory_search` via Gateway `/tools/invoke`
- Ingest modes:
  - `noop` (default; pre-ingested search)
  - `memory_store` (optional; requires memory slot to expose `memory_store`)

## Proposed v0 order

1. Keep Option A as default for ecosystem realism.
2. Add Option B only as optional diagnostic mode.
