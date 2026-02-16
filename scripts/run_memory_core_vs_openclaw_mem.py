from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_memory_bench.dataset import load_retrieval_dataset
from openclaw_memory_bench.manifest import build_retrieval_manifest, file_sha256
from openclaw_memory_bench.runner import run_retrieval_benchmark, save_report


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(txt: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", txt).strip("-").lower()


def _run_provider(
    *,
    provider: str,
    provider_config: dict[str, Any],
    dataset_path: Path,
    top_k: int,
    question_limit: int | None,
    out_dir: Path,
    run_group: str,
) -> dict[str, Any]:
    dataset = load_retrieval_dataset(dataset_path)
    run_id = f"{run_group}-{provider}"

    manifest = build_retrieval_manifest(
        run_id=run_id,
        provider=provider,
        provider_config=provider_config,
        dataset_path=dataset_path,
        dataset_name=dataset.name,
        top_k=top_k,
        limit=question_limit,
        skip_ingest=False,
        fail_fast=False,
        repo_dir=Path(__file__).resolve().parents[1],
    )

    report = run_retrieval_benchmark(
        provider=provider,
        dataset=dataset,
        top_k=top_k,
        run_id=run_id,
        provider_config=provider_config,
        fail_fast=False,
        limit=question_limit,
        skip_ingest=False,
        manifest=manifest,
    )

    report_path = save_report(report, out_dir / provider / "retrieval-report.json")
    return {
        "provider": provider,
        "report_path": str(report_path),
        "summary": report["summary"],
        "latency": report["latency"],
        "top_k": report["top_k"],
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
        "search_ms_p50": float(latency["search_ms_p50"]),
        "search_ms_p95": float(latency["search_ms_p95"]),
        "search_ms_mean": float(latency["search_ms_mean"]),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Pilot compare: memory-core vs openclaw-mem")
    ap.add_argument("--dataset", default="examples/dual_language_mini.json")
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--question-limit", type=int, default=None)
    ap.add_argument("--run-label", default="pilot-memory-core-sidecar")
    ap.add_argument("--output-root", default="artifacts/sidecar-compare")
    ap.add_argument("--memory-core-profile", default="membench-memory-core")
    ap.add_argument(
        "--openclaw-mem-db-root",
        default="artifacts/provider-state/openclaw-mem",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dataset_path = repo_root / args.dataset if not Path(args.dataset).is_absolute() else Path(args.dataset)
    out_root = repo_root / args.output_root

    run_group = f"{_now_tag()}-{_slug(args.run_label)}"
    run_dir = out_root / run_group
    run_dir.mkdir(parents=True, exist_ok=True)

    memory_core_report = _run_provider(
        provider="memory-core",
        provider_config={
            "profile": args.memory_core_profile,
            "agent_id": "main",
            "timeout_sec": 120,
        },
        dataset_path=dataset_path,
        top_k=args.top_k,
        question_limit=args.question_limit,
        out_dir=run_dir,
        run_group=run_group,
    )

    openclaw_mem_cfg = {
        "db_root": args.openclaw_mem_db_root,
    }
    # Optional: only needed when `openclaw-mem` is not on PATH.
    openclaw_mem_project = os.environ.get("OPENCLAW_MEM_PROJECT") or os.environ.get(
        "OPENCLAW_MEM_PROJECT_DIR"
    )
    if openclaw_mem_project:
        openclaw_mem_cfg["openclaw_mem_project"] = openclaw_mem_project

    openclaw_mem_report = _run_provider(
        provider="openclaw-mem",
        provider_config=openclaw_mem_cfg,
        dataset_path=dataset_path,
        top_k=args.top_k,
        question_limit=args.question_limit,
        out_dir=run_dir,
        run_group=run_group,
    )

    m_core = _metric_pack(memory_core_report)
    m_sidecar = _metric_pack(openclaw_mem_report)
    delta = {k: (m_sidecar[k] - m_core[k]) for k in m_core.keys()}

    compare = {
        "schema": "openclaw-memory-bench/sidecar-compare-report/v0.1",
        "run_group": run_group,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": file_sha256(dataset_path),
        "providers": {
            "memory-core": memory_core_report,
            "openclaw-mem": openclaw_mem_report,
        },
        "delta_openclaw_mem_minus_memory_core": delta,
        "isolation": {
            "memory_core_profile": args.memory_core_profile,
            "openclaw_mem_db_root": args.openclaw_mem_db_root,
        },
    }

    compare_json = run_dir / f"compare-{run_group}.json"
    compare_json.write_text(json.dumps(compare, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Sidecar compare ({run_group})",
        "",
        f"- Dataset: `{dataset_path}`",
        f"- top_k: {args.top_k}",
        "",
        "## memory-core",
        f"- hit@k: {m_core['hit_at_k']:.4f}",
        f"- recall@k: {m_core['recall_at_k']:.4f}",
        f"- mrr: {m_core['mrr']:.4f}",
        f"- ndcg@k: {m_core['ndcg_at_k']:.4f}",
        f"- p50/p95(ms): {m_core['search_ms_p50']:.2f}/{m_core['search_ms_p95']:.2f}",
        "",
        "## openclaw-mem (sidecar path)",
        f"- hit@k: {m_sidecar['hit_at_k']:.4f}",
        f"- recall@k: {m_sidecar['recall_at_k']:.4f}",
        f"- mrr: {m_sidecar['mrr']:.4f}",
        f"- ndcg@k: {m_sidecar['ndcg_at_k']:.4f}",
        f"- p50/p95(ms): {m_sidecar['search_ms_p50']:.2f}/{m_sidecar['search_ms_p95']:.2f}",
        "",
        "## Delta (openclaw-mem - memory-core)",
        f"- hit@k: {delta['hit_at_k']:+.4f}",
        f"- recall@k: {delta['recall_at_k']:+.4f}",
        f"- mrr: {delta['mrr']:+.4f}",
        f"- ndcg@k: {delta['ndcg_at_k']:+.4f}",
        f"- p50(ms): {delta['search_ms_p50']:+.2f}",
        f"- p95(ms): {delta['search_ms_p95']:+.2f}",
    ]

    compare_md = run_dir / f"compare-{run_group}.md"
    compare_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "run_group": run_group,
                "compare_json": str(compare_json),
                "compare_md": str(compare_md),
                "memory_core_report": memory_core_report["report_path"],
                "openclaw_mem_report": openclaw_mem_report["report_path"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
