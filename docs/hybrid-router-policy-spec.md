# Hybrid Router Policy Spec (QMD → LanceDB → Optional Rerank)

Status: draft for Phase A/B+ benchmark arm wiring  
Owner: openclaw-memory-bench slow-cook thread  
Updated: 2026-02-16 (Asia/Taipei)

## 1) Goal
Define a deterministic, replayable hybrid retrieval policy that improves must-coverage while keeping latency bounded.

This spec is benchmark-facing only (aggregate metrics, no raw memory export).

## 2) Two-stage policy (default)

### Stage 1 — QMD candidate generation
- Run QMD-style lexical + semantic retrieval.
- Return ranked candidates with stable IDs and scores.
- Stage 1 is treated as the **must-first** source.

### Stage 2 — LanceDB fill (conditional)
- Trigger only when Stage 1 coverage is insufficient (gate below).
- Pull additional candidates from LanceDB-only report.
- Fill remaining top-k slots with deduplication and deterministic ordering.

### Optional Stage 3 — Rerank (future toggle)
- Disabled by default for current benchmark milestone.
- If enabled later, rerank only the merged candidate set (no new retrieval).

## 3) Candidate budgets (top-N)
For LongMemEval-50 Phase A/B+ evaluation:

- Global final `top_k`: **10**
- Stage 1 QMD candidate budget: **N1 = 20**
- Stage 2 LanceDB additional candidate budget: **N2 = 20**
- Max Stage 2 appended count into final top-k: **10** (practically fill-to-k)

Determinism constraints:
- Deduplicate by `session_id` (first kept occurrence wins by stage priority).
- Stable tie-break order: `(fused_score desc, stage_priority asc, source_rank asc, session_id asc)`.
- stage_priority: Stage1/QMD = 0, Stage2/LanceDB = 1.

## 4) Must-coverage gate (stage2 trigger)
Use must-first gate with explicit threshold:

- `min_must_count = 3` for `top_k=10`.
- Trigger Stage 2 when `len(stage1_ids) < min_must_count`.
- If Stage 2 is skipped due to latency budget violation, keep Stage 1 only and record skip reason.

Rationale:
- `3/10` is a quality-first floor that avoids excessive stage2 calls while reducing obvious under-retrieval cases.

## 5) Fusion policy (deterministic)
Two supported deterministic fusion modes for implementation/testing:

1. **append_fill (Phase A/B+ default)**
   - Keep Stage 1 ranking as-is.
   - Append non-duplicate Stage 2 IDs until top-k reached.

2. **rrf_fusion (experimental arm)**
   - Reciprocal Rank Fusion with fixed constant `k_rrf = 60`.
   - `rrf_score(id) = Σ 1/(k_rrf + rank_source(id))` across Stage 1 + Stage 2.
   - Apply deterministic tie-break order above.

(Weighted-score merge can be added as a third mode after baseline receipts.)

## 6) Latency budget (quality-first but bounded)
Per-question budget guardrails:

- Target p95 total retrieval latency: **≤ 1500 ms**
- Stage 2 soft budget cap: **≤ 600 ms**
- Policy:
  - If Stage 2 estimated/observed latency exceeds cap, skip Stage 2 for that question.
  - Always emit per-question metadata: `stage2_should_trigger`, `stage2_used`, `stage2_skipped_budget`, latency split.

Report-level acceptance for this arm:
- p95 ≤ 1500 ms, and
- recall@k is non-degrading vs LanceDB-only baseline (or degradation is explicitly quantified in report).

## 7) Receipt contract for benchmark arm wiring
Implementation should produce:
- retrieval report JSON with `config.mode`, gate values, and stage usage counters.
- markdown summary including:
  - stage2_used / skipped / not_triggered counts
  - summary metrics (hit/precision/recall/mrr/ndcg)
  - latency p50/p95
- fixture-backed tests for:
  - append_fill determinism
  - rrf score calculation determinism
  - tie-break rule determinism

## 8) Non-goals (this cycle)
- No model-side reranker integration yet.
- No raw-memory payload exports.
- No policy auto-tuning; thresholds remain explicit constants for reproducibility.
