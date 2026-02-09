# Upstream Insights (OpenClaw #12633 / #12660) — 2026-02-09

## Scope
This note distills benchmark-relevant insights from two upstream threads and records what we contributed publicly.

- #12633: <https://github.com/openclaw/openclaw/issues/12633>
- #12660: <https://github.com/openclaw/openclaw/issues/12660>

Our public comments:
- #12633 comment: <https://github.com/openclaw/openclaw/issues/12633#issuecomment-3872028757>
- #12660 comment: <https://github.com/openclaw/openclaw/issues/12660#issuecomment-3872029522>

---

## 1) #12633 Session indexing skip: what matters for benchmarking

### Observed upstream finding
- A cold-start gating path can permanently skip sessions indexing (`shouldSyncSessions()` dead loop pattern).

### Additional field finding from this repo
- A second failure class exists: session-heavy indexing can stall/timeout.
- Repeated signatures in benchmark artifacts include index timeouts around 120s, 240s, 298s, and 314s.

### Why this matters
If upstream only fixes skip logic but not bootstrap run-shape, large/session-heavy environments may still produce unstable indexing latency and inconsistent benchmark behavior.

### Suggested fix envelope (v1-safe)
1. Cold-start bootstrap rule when session source is enabled and DB has no indexed session rows.
2. Verbose skip diagnostics (`reason`, `needsFullReindex`, `sessionsDirty`, `dirtyFiles.size`).
3. Regression test for pre-existing DB + non-empty sessions directory.
4. Optional bounded/checkpointed first-sync (file/chunk budget per run).

---

## 2) #12660 Context provider slot: why it is strategically important

### Core insight
Routing models reduces $/token, but long-run cost/speed pain is often token volume from unbounded context assembly. A context-provider slot is the structural control point.

### Practical rollout guidance
1. Fail-open fallback to default transcript assembly on provider error/timeout.
2. Provider runtime budget/timeout guardrails.
3. Clear compaction semantics when provider owns context.
4. Keep full transcript for audit/replay while decoupling model prompt payload.
5. Expose provider stats and fallback counters.
6. Prefer shadow mode before production cutover.

### Why this is benchmark-relevant
This repository can evaluate context-provider changes with replayable, deterministic slices (seeded sampling + manifest reproducibility), reducing rollout risk.

---

## Follow-up work tracked for this repo
- Add benchmark scenario tags that explicitly separate:
  - cold-start indexing correctness,
  - sustained indexing stability,
  - replay-based context-provider A/B readiness.
- Extend report commentary templates with "correctness vs stability" split to avoid one-dimensional conclusions.
