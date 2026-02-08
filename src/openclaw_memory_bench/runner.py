from __future__ import annotations

import json
import statistics
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from .adapters import available_adapters
from .dataset import RetrievalDataset
from .metrics import percentile_ms, score_retrieval


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _safe_mean(values: list[float]) -> float:
    return float(statistics.mean(values)) if values else 0.0


def run_retrieval_benchmark(
    *,
    provider: str,
    dataset: RetrievalDataset,
    top_k: int,
    run_id: str,
    provider_config: dict,
    fail_fast: bool = False,
    limit: int | None = None,
    skip_ingest: bool = False,
    manifest: dict | None = None,
) -> dict:
    adapters = available_adapters()
    if provider not in adapters:
        raise ValueError(f"Unknown provider: {provider}")

    adapter = adapters[provider]()
    adapter.initialize(provider_config)

    questions = dataset.questions[:limit] if limit else dataset.questions

    latencies_ms: list[float] = []
    hit_scores: list[float] = []
    precision_scores: list[float] = []
    recall_scores: list[float] = []
    mrr_scores: list[float] = []
    ndcg_scores: list[float] = []

    results: list[dict] = []
    failures: list[dict] = []

    for idx, q in enumerate(questions, start=1):
        container_tag = f"{run_id}:{q.question_id}"
        print(f"[{idx}/{len(questions)}] {q.question_id} :: ingest/search")

        try:
            adapter.clear(container_tag)
            ingest_result = {"ingest": "skipped"}
            if not skip_ingest:
                ingest_result = adapter.ingest(q.sessions, container_tag)
                adapter.await_indexing(ingest_result, container_tag)

            t0 = time.perf_counter()
            hits = adapter.search(q.question, container_tag=container_tag, limit=top_k)
            dt_ms = (time.perf_counter() - t0) * 1000.0

            retrieved_session_ids = [str(h.metadata.get("session_id", "")) for h in hits]
            retrieved_session_ids = [x for x in retrieved_session_ids if x]

            metrics = score_retrieval(
                retrieved_ids=retrieved_session_ids,
                relevant_ids=q.relevant_session_ids,
                k=top_k,
            )

            latencies_ms.append(dt_ms)
            hit_scores.append(metrics.hit_at_k)
            precision_scores.append(metrics.precision_at_k)
            recall_scores.append(metrics.recall_at_k)
            mrr_scores.append(metrics.mrr)
            ndcg_scores.append(metrics.ndcg_at_k)

            results.append(
                {
                    "question_id": q.question_id,
                    "question": q.question,
                    "question_type": q.question_type,
                    "ground_truth": q.ground_truth,
                    "relevant_session_ids": q.relevant_session_ids,
                    "retrieved_session_ids": retrieved_session_ids,
                    "retrieved_observation_ids": [h.id for h in hits],
                    "retrieved_sources": [h.metadata.get("path") for h in hits if h.metadata.get("path")],
                    "ingest_result": ingest_result,
                    "latency_ms": dt_ms,
                    "metrics": asdict(metrics),
                }
            )
        except Exception as e:
            err = {
                "question_id": q.question_id,
                "error": str(e),
            }
            failures.append(err)
            print(f"  ! failed: {e}")
            if fail_fast:
                break

    report = {
        "schema": "openclaw-memory-bench/retrieval-report/v0.2",
        "run_id": run_id,
        "provider": provider,
        "dataset": dataset.name,
        "top_k": top_k,
        "created_at_utc": _now_utc(),
        "config": {
            "skip_ingest": skip_ingest,
        },
        "manifest": manifest,
        "summary": {
            "questions_total": len(questions),
            "questions_succeeded": len(results),
            "questions_failed": len(failures),
            "hit_at_k": _safe_mean(hit_scores),
            "precision_at_k": _safe_mean(precision_scores),
            "recall_at_k": _safe_mean(recall_scores),
            "mrr": _safe_mean(mrr_scores),
            "ndcg_at_k": _safe_mean(ndcg_scores),
        },
        "latency": {
            "search_ms_p50": percentile_ms(latencies_ms, 50),
            "search_ms_p95": percentile_ms(latencies_ms, 95),
            "search_ms_mean": _safe_mean(latencies_ms),
        },
        "results": results,
        "failures": failures,
    }
    return report


def save_report(report: dict, out_path: str | Path) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
