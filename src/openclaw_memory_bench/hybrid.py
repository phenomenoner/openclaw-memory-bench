from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_memory_bench.metrics import RetrievalMetrics, percentile_ms, score_retrieval
from openclaw_memory_bench.validation import validate_retrieval_report_payload

_ALLOWED_FUSION_MODES = {"append_fill", "rrf_fusion"}


def now_utc_iso() -> str:
    return datetime.now(UTC).isoformat()


def safe_mean(values: list[float]) -> float:
    return float(sum(values) / len(values)) if values else 0.0


def load_report(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"report must be object: {path}")
    return raw


def failure_breakdown(failures: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    by_code: dict[str, int] = {}
    by_category: dict[str, int] = {}
    by_phase: dict[str, int] = {}

    for row in failures:
        code = str(row.get("error_code") or "UNKNOWN")
        category = str(row.get("error_category") or "unknown")
        phase = str(row.get("phase") or "unknown")
        by_code[code] = by_code.get(code, 0) + 1
        by_category[category] = by_category.get(category, 0) + 1
        by_phase[phase] = by_phase.get(phase, 0) + 1

    return {"by_code": by_code, "by_category": by_category, "by_phase": by_phase}


def _coerce_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for x in value:
        s = str(x)
        if s:
            out.append(s)
    return out


def _coerce_float_list(value: Any) -> list[float]:
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for x in value:
        if isinstance(x, (int, float)) and not isinstance(x, bool):
            out.append(float(x))
    return out


def _rrf_merge(
    *,
    must_ids: list[str],
    stage2_pairs: list[tuple[str, float]],
    top_k: int,
    k_rrf: float,
) -> tuple[list[str], list[float], int]:
    fused_scores: dict[str, float] = {}
    stage_priority: dict[str, int] = {}
    source_rank: dict[str, int] = {}

    for rank, sid in enumerate(must_ids, start=1):
        fused_scores[sid] = fused_scores.get(sid, 0.0) + (1.0 / (k_rrf + rank))
        stage_priority[sid] = min(stage_priority.get(sid, 99), 0)
        source_rank[sid] = min(source_rank.get(sid, 10**9), rank)

    for rank, (sid, _) in enumerate(stage2_pairs, start=1):
        fused_scores[sid] = fused_scores.get(sid, 0.0) + (1.0 / (k_rrf + rank))
        stage_priority[sid] = min(stage_priority.get(sid, 99), 1)
        source_rank[sid] = min(source_rank.get(sid, 10**9), rank)

    ranked = sorted(
        fused_scores.keys(),
        key=lambda sid: (
            -fused_scores[sid],
            stage_priority.get(sid, 99),
            source_rank.get(sid, 10**9),
            sid,
        ),
    )[:top_k]

    merged_scores = [float(fused_scores[sid]) for sid in ranked]
    added = sum(1 for sid in ranked if sid not in set(must_ids))
    return ranked, merged_scores, added


def _append_fill_merge(
    *,
    must_ids: list[str],
    must_scores: list[float],
    stage2_pairs: list[tuple[str, float]],
    top_k: int,
) -> tuple[list[str], list[float], int]:
    merged_ids = must_ids[:top_k]
    merged_scores = must_scores[: len(merged_ids)]
    added = 0

    for sid, score in stage2_pairs:
        if len(merged_ids) >= top_k:
            break
        if sid in merged_ids:
            continue
        merged_ids.append(sid)
        merged_scores.append(float(score))
        added += 1

    return merged_ids, merged_scores, added


def build_two_stage_hybrid_report(
    *,
    must_report: dict[str, Any],
    fallback_report: dict[str, Any],
    run_id: str,
    manifest: dict[str, Any] | None = None,
    min_must_count: int = 3,
    stage2_max_additional: int = 20,
    stage2_max_ms: float | None = None,
    fusion_mode: str = "append_fill",
    k_rrf: float = 60.0,
) -> tuple[dict[str, Any], dict[str, Any]]:
    if fusion_mode not in _ALLOWED_FUSION_MODES:
        raise ValueError(f"unsupported fusion_mode: {fusion_mode}")
    if min_must_count < 0:
        raise ValueError("min_must_count must be >= 0")
    if stage2_max_additional < 0:
        raise ValueError("stage2_max_additional must be >= 0")
    if k_rrf <= 0:
        raise ValueError("k_rrf must be > 0")

    must_rows = must_report.get("results")
    fallback_rows = fallback_report.get("results")
    if not isinstance(must_rows, list) or not isinstance(fallback_rows, list):
        raise ValueError("input reports must have .results arrays")

    must_by_qid = {str(r.get("question_id")): r for r in must_rows if isinstance(r, dict)}
    fallback_by_qid = {str(r.get("question_id")): r for r in fallback_rows if isinstance(r, dict)}

    qids: set[str] = set(must_by_qid)
    qids.update(fallback_by_qid)

    selected_rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    latencies_ms: list[float] = []
    metrics_list: list[RetrievalMetrics] = []

    stage_counts = {
        "stage2_used": 0,
        "stage2_skipped_budget": 0,
        "stage2_not_triggered": 0,
    }

    top_k = int(must_report.get("top_k") or fallback_report.get("top_k") or 10)
    stage2_budget = int(max(0, stage2_max_additional))

    for qid in sorted(qids):
        must_row = must_by_qid.get(qid)
        fallback_row = fallback_by_qid.get(qid)

        if not must_row and not fallback_row:
            failures.append(
                {
                    "question_id": qid,
                    "phase": "select",
                    "error_code": "MISSING_RESULT",
                    "error_category": "postprocess",
                    "retryable": False,
                    "exception_type": "KeyError",
                    "error": "question_id missing from both input reports",
                }
            )
            continue

        rel_ids: list[str] = []
        rel_src = fallback_row if isinstance(fallback_row, dict) else must_row
        if isinstance(rel_src, dict) and isinstance(rel_src.get("relevant_session_ids"), list):
            rel_ids = [str(x) for x in rel_src.get("relevant_session_ids") if str(x)]

        must_ids = _coerce_str_list(must_row.get("retrieved_session_ids") if isinstance(must_row, dict) else None)
        must_scores = _coerce_float_list(must_row.get("retrieved_scores") if isinstance(must_row, dict) else None)
        must_latency = float(must_row.get("latency_ms") or 0.0) if isinstance(must_row, dict) else 0.0

        fallback_ids = _coerce_str_list(
            fallback_row.get("retrieved_session_ids") if isinstance(fallback_row, dict) else None
        )
        fallback_scores = _coerce_float_list(
            fallback_row.get("retrieved_scores") if isinstance(fallback_row, dict) else None
        )
        fallback_latency = float(fallback_row.get("latency_ms") or 0.0) if isinstance(fallback_row, dict) else 0.0

        if len(must_scores) < len(must_ids):
            must_scores = must_scores + [0.0] * (len(must_ids) - len(must_scores))
        if len(fallback_scores) < len(fallback_ids):
            fallback_scores = fallback_scores + [0.0] * (len(fallback_ids) - len(fallback_scores))

        must_count = len(must_ids)
        stage2_should_trigger = bool(fallback_row is not None and must_count < int(min_must_count))
        stage2_allowed = True
        if stage2_max_ms is not None and stage2_max_ms > 0:
            stage2_allowed = fallback_latency <= float(stage2_max_ms)
        stage2_used = bool(stage2_should_trigger and stage2_allowed)

        stage2_pairs: list[tuple[str, float]] = []
        if stage2_used:
            stage2_pairs = list(zip(fallback_ids, fallback_scores, strict=False))[:stage2_budget]

        if fusion_mode == "append_fill":
            retrieved_ids, retrieved_scores, stage2_added = _append_fill_merge(
                must_ids=must_ids,
                must_scores=must_scores,
                stage2_pairs=stage2_pairs,
                top_k=top_k,
            )
        else:
            retrieved_ids, retrieved_scores, stage2_added = _rrf_merge(
                must_ids=must_ids,
                stage2_pairs=stage2_pairs,
                top_k=top_k,
                k_rrf=float(k_rrf),
            )

        if stage2_used:
            stage_counts["stage2_used"] += 1
        elif stage2_should_trigger and not stage2_allowed:
            stage_counts["stage2_skipped_budget"] += 1
        else:
            stage_counts["stage2_not_triggered"] += 1

        latency_ms = must_latency + (fallback_latency if stage2_used else 0.0)
        latencies_ms.append(float(latency_ms))

        metrics = score_retrieval(retrieved_ids=retrieved_ids, relevant_ids=rel_ids, k=top_k)
        metrics_list.append(metrics)

        base = must_row if isinstance(must_row, dict) else fallback_row
        row = {
            "question_id": str((base or {}).get("question_id") or qid),
            "question": str((base or {}).get("question") or ""),
            "question_type": str((base or {}).get("question_type") or ""),
            "ground_truth": str((base or {}).get("ground_truth") or ""),
            "relevant_session_ids": rel_ids,
            "retrieved_session_ids": retrieved_ids,
            "retrieved_scores": retrieved_scores,
            "retrieved_observation_ids": (base or {}).get("retrieved_observation_ids")
            if isinstance((base or {}).get("retrieved_observation_ids"), list)
            else [],
            "retrieved_sources": (base or {}).get("retrieved_sources")
            if isinstance((base or {}).get("retrieved_sources"), list)
            else [],
            "latency_ms": float(latency_ms),
            "metrics": asdict(metrics),
            "two_stage": {
                "mode": "must_count_gate",
                "fusion_mode": fusion_mode,
                "must_retrieved_count": must_count,
                "min_must_count": int(min_must_count),
                "stage2_should_trigger": stage2_should_trigger,
                "stage2_used": stage2_used,
                "stage2_skipped_budget": bool(stage2_should_trigger and not stage2_allowed),
                "stage2_max_additional": stage2_budget,
                "stage2_candidates_considered": (len(stage2_pairs) if stage2_used else 0),
                "stage2_added_count": (stage2_added if stage2_used else 0),
                "stage1_latency_ms": must_latency,
                "stage2_latency_ms": (fallback_latency if stage2_used else 0.0),
                "stage2_max_ms": (float(stage2_max_ms) if stage2_max_ms is not None else None),
                "tie_break_order": [
                    "fused_score_desc",
                    "stage_priority_asc",
                    "source_rank_asc",
                    "session_id_asc",
                ],
                "stage_priority": {"stage1": 0, "stage2": 1},
            },
        }

        if fusion_mode == "rrf_fusion":
            row["two_stage"]["k_rrf"] = float(k_rrf)

        selected_rows.append(row)

    hit_scores = [m.hit_at_k for m in metrics_list]
    precision_scores = [m.precision_at_k for m in metrics_list]
    recall_scores = [m.recall_at_k for m in metrics_list]
    mrr_scores = [m.mrr for m in metrics_list]
    ndcg_scores = [m.ndcg_at_k for m in metrics_list]

    config: dict[str, Any] = {
        "must_run_id": str(must_report.get("run_id") or ""),
        "fallback_run_id": str(fallback_report.get("run_id") or ""),
        "mode": "must_count_gate",
        "fusion_mode": fusion_mode,
        "min_must_count": int(min_must_count),
        "stage2_max_additional": stage2_budget,
        "stage2_max_ms": (float(stage2_max_ms) if stage2_max_ms is not None else None),
    }
    if fusion_mode == "rrf_fusion":
        config["k_rrf"] = float(k_rrf)

    report = {
        "schema": "openclaw-memory-bench/retrieval-report/v0.2",
        "run_id": run_id,
        "provider": "two-stage-hybrid",
        "dataset": str(must_report.get("dataset") or fallback_report.get("dataset") or "unknown"),
        "top_k": top_k,
        "created_at_utc": now_utc_iso(),
        "config": config,
        "manifest": manifest,
        "summary": {
            "questions_total": int(len(qids)),
            "questions_succeeded": int(len(selected_rows)),
            "questions_failed": int(len(failures)),
            "hit_at_k": safe_mean(hit_scores),
            "precision_at_k": safe_mean(precision_scores),
            "recall_at_k": safe_mean(recall_scores),
            "mrr": safe_mean(mrr_scores),
            "ndcg_at_k": safe_mean(ndcg_scores),
            "failure_breakdown": failure_breakdown(failures),
        },
        "latency": {
            "search_ms_p50": percentile_ms(latencies_ms, 50),
            "search_ms_p95": percentile_ms(latencies_ms, 95),
            "search_ms_mean": safe_mean(latencies_ms),
        },
        "results": selected_rows,
        "failures": failures,
    }

    extra = {
        "stage_counts": stage_counts,
        "hybrid_config": config,
    }

    validate_retrieval_report_payload(report)
    return report, extra
