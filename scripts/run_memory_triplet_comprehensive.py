from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_memory_bench.converters import benchmark_sources, convert_benchmark, write_dataset
from openclaw_memory_bench.dataset import load_retrieval_dataset
from openclaw_memory_bench.manifest import build_retrieval_manifest, file_sha256
from openclaw_memory_bench.runner import run_retrieval_benchmark, save_report
from openclaw_memory_bench.validation import validate_dataset_payload


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(txt: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", txt).strip("-").lower()


def _prepare_dataset(*, benchmark: str, limit: int | None, out: Path) -> tuple[Path, dict[str, Any]]:
    data = convert_benchmark(benchmark, limit=limit)
    validate_dataset_payload(data)

    out.parent.mkdir(parents=True, exist_ok=True)
    dataset_path = write_dataset(data, out)

    meta = {
        "schema": "openclaw-memory-bench/dataset-meta/v0.1",
        "benchmark": benchmark,
        "limit": limit,
        "converted_at_utc": datetime.now(UTC).isoformat(),
        "sources": benchmark_sources(benchmark),
    }
    meta_path = dataset_path.with_name(f"{dataset_path.name}.meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return dataset_path, meta


def _run_provider(
    *,
    provider: str,
    provider_config: dict[str, Any],
    dataset_path: Path,
    dataset_name: str,
    top_k: int,
    question_limit: int | None,
    run_group: str,
    out_dir: Path,
    preindex_once: bool = False,
) -> dict[str, Any]:
    run_id = f"{run_group}-{provider}"

    manifest = build_retrieval_manifest(
        run_id=run_id,
        provider=provider,
        provider_config=provider_config,
        dataset_path=dataset_path,
        dataset_name=dataset_name,
        top_k=top_k,
        limit=question_limit,
        sample_size=None,
        sample_seed=None,
        skip_ingest=False,
        preindex_once=preindex_once,
        fail_fast=False,
        repo_dir=Path(__file__).resolve().parents[1],
    )

    report = run_retrieval_benchmark(
        provider=provider,
        dataset=load_retrieval_dataset(dataset_path),
        top_k=top_k,
        run_id=run_id,
        provider_config=provider_config,
        fail_fast=False,
        limit=question_limit,
        skip_ingest=False,
        preindex_once=preindex_once,
        manifest=manifest,
    )

    report_path = save_report(report, out_dir / provider / "retrieval-report.json")
    return {
        "provider": provider,
        "report_path": str(report_path),
        "top_k": report["top_k"],
        "summary": report["summary"],
        "latency": report["latency"],
    }


def _metric_pack(report: dict[str, Any]) -> dict[str, float]:
    s = report["summary"]
    latency = report["latency"]
    return {
        "hit_at_k": float(s["hit_at_k"]),
        "precision_at_k": float(s["precision_at_k"]),
        "recall_at_k": float(s["recall_at_k"]),
        "mrr": float(s["mrr"]),
        "ndcg_at_k": float(s["ndcg_at_k"]),
        "questions_failed": float(s["questions_failed"]),
        "search_ms_p50": float(latency["search_ms_p50"]),
        "search_ms_p95": float(latency["search_ms_p95"]),
        "search_ms_mean": float(latency["search_ms_mean"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Comprehensive triplet benchmark: memory-core, memory-lancedb, openclaw-mem")
    ap.add_argument("--benchmark", default="longmemeval", choices=["locomo", "longmemeval", "convomem"])
    ap.add_argument("--dataset-limit", type=int, default=100)
    ap.add_argument("--question-limit", type=int, default=100)
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--run-label", default="comprehensive-triplet")
    ap.add_argument("--output-root", default="artifacts/comprehensive-triplet")
    ap.add_argument("--memory-core-profile", default="membench-memory-core")
    ap.add_argument("--memory-core-timeout-sec", type=int, default=180)
    ap.add_argument("--memory-core-force-reindex", action="store_true")
    ap.add_argument("--memory-core-index-retries", type=int, default=1)
    ap.add_argument("--memory-core-max-messages-per-session", type=int, default=80)
    ap.add_argument("--memory-core-max-message-chars", type=int, default=800)
    ap.add_argument("--memory-core-max-chars-per-session", type=int, default=12000)
    ap.add_argument("--memory-core-search-limit-factor", type=int, default=8)
    ap.add_argument("--memory-core-preindex-once", action="store_true")
    ap.add_argument("--openclaw-mem-db-root", default="artifacts/provider-state/openclaw-mem")
    ap.add_argument("--lancedb-session-key", default="main")
    ap.add_argument("--lancedb-recall-limit-factor", type=int, default=12)
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    run_group = f"{_now_tag()}-{_slug(args.run_label)}"
    run_dir = (repo_root / args.output_root / run_group)
    run_dir.mkdir(parents=True, exist_ok=True)

    dataset_out = repo_root / "data" / "datasets" / f"{args.benchmark}-{args.dataset_limit}.json"
    dataset_path, dataset_meta = _prepare_dataset(
        benchmark=args.benchmark,
        limit=args.dataset_limit,
        out=dataset_out,
    )
    dataset = load_retrieval_dataset(dataset_path)

    (run_dir / "dataset.meta.json").write_text(
        json.dumps(dataset_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    providers: dict[str, dict[str, Any]] = {}

    providers["memory-core"] = _run_provider(
        provider="memory-core",
        provider_config={
            "profile": args.memory_core_profile,
            "agent_id": "main",
            "timeout_sec": args.memory_core_timeout_sec,
            "force_reindex": args.memory_core_force_reindex,
            "index_retries": args.memory_core_index_retries,
            "search_limit_factor": args.memory_core_search_limit_factor,
            "max_messages_per_session": args.memory_core_max_messages_per_session,
            "max_message_chars": args.memory_core_max_message_chars,
            "max_chars_per_session": args.memory_core_max_chars_per_session,
        },
        dataset_path=dataset_path,
        dataset_name=dataset.name,
        top_k=args.top_k,
        question_limit=args.question_limit,
        run_group=run_group,
        out_dir=run_dir,
        preindex_once=args.memory_core_preindex_once,
    )

    providers["memory-lancedb"] = _run_provider(
        provider="memory-lancedb",
        provider_config={
            "session_key": args.lancedb_session_key,
            "recall_limit_factor": args.lancedb_recall_limit_factor,
        },
        dataset_path=dataset_path,
        dataset_name=dataset.name,
        top_k=args.top_k,
        question_limit=args.question_limit,
        run_group=run_group,
        out_dir=run_dir,
    )

    providers["openclaw-mem"] = _run_provider(
        provider="openclaw-mem",
        provider_config={
            "db_root": args.openclaw_mem_db_root,
            "openclaw_mem_project": "/home/agent/.openclaw/workspace/openclaw-mem",
        },
        dataset_path=dataset_path,
        dataset_name=dataset.name,
        top_k=args.top_k,
        question_limit=args.question_limit,
        run_group=run_group,
        out_dir=run_dir,
    )

    metrics = {name: _metric_pack(rep) for name, rep in providers.items()}

    compare = {
        "schema": "openclaw-memory-bench/comprehensive-triplet-report/v0.1",
        "run_group": run_group,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "benchmark": args.benchmark,
        "question_limit": args.question_limit,
        "top_k": args.top_k,
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": file_sha256(dataset_path),
        "providers": providers,
        "metrics": metrics,
        "delta_openclaw_mem_minus_memory_core": {
            k: metrics["openclaw-mem"][k] - metrics["memory-core"][k] for k in metrics["memory-core"]
        },
        "delta_lancedb_minus_memory_core": {
            k: metrics["memory-lancedb"][k] - metrics["memory-core"][k] for k in metrics["memory-core"]
        },
        "delta_openclaw_mem_minus_lancedb": {
            k: metrics["openclaw-mem"][k] - metrics["memory-lancedb"][k]
            for k in metrics["memory-lancedb"]
        },
    }

    compare_json = run_dir / f"compare-{run_group}.json"
    compare_json.write_text(json.dumps(compare, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Comprehensive triplet report ({run_group})",
        "",
        f"- Benchmark: `{args.benchmark}`",
        f"- Dataset: `{dataset_path}`",
        f"- question_limit/top_k: {args.question_limit}/{args.top_k}",
        "",
    ]

    for name in ["memory-core", "memory-lancedb", "openclaw-mem"]:
        m = metrics[name]
        lines.extend(
            [
                f"## {name}",
                f"- hit@k: {m['hit_at_k']:.4f}",
                f"- recall@k: {m['recall_at_k']:.4f}",
                f"- mrr: {m['mrr']:.4f}",
                f"- ndcg@k: {m['ndcg_at_k']:.4f}",
                f"- failed: {int(m['questions_failed'])}",
                f"- p50/p95(ms): {m['search_ms_p50']:.2f}/{m['search_ms_p95']:.2f}",
                "",
            ]
        )

    compare_md = run_dir / f"compare-{run_group}.md"
    compare_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "run_group": run_group,
                "dataset": str(dataset_path),
                "compare_json": str(compare_json),
                "compare_md": str(compare_md),
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
