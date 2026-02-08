# ADR 0001 — Separate benchmark repo + MIT license

- Status: Accepted
- Date: 2026-02-08

## Context

We need a community-trustworthy benchmark toolkit for OpenClaw memory-layer plugins.
`openclaw-mem` is one implementation, but the benchmark framework should remain neutral and extensible (e.g., memu-engine).

## Decision

1. Create a standalone repository: `openclaw-memory-bench`.
2. Use MIT license.
3. Add explicit acknowledgements to `supermemoryai/memorybench` (MIT), with attribution policy for any future adapted code.
4. Keep CLI-first, non-interactive architecture for CI and automation.

## Consequences

- Better trust and neutrality vs bundling benchmark code inside `openclaw-mem`.
- Independent release cycle and easier community contributions.
- Slightly higher coordination cost across repos.
