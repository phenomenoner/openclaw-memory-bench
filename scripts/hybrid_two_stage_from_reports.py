from __future__ import annotations

import argparse
import json
from pathlib import Path

from openclaw_memory_bench.hybrid import build_two_stage_hybrid_report, load_report


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a two-stage hybrid retrieval report from two reports.")
    ap.add_argument("--must-report", required=True)
    ap.add_argument("--fallback-report", required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--min-must-count", type=int, default=3)
    ap.add_argument("--stage2-max-additional", type=int, default=20)
    ap.add_argument("--stage2-max-ms", type=float, default=600.0)
    ap.add_argument(
        "--fusion-mode",
        choices=["append_fill", "rrf_fusion"],
        default="append_fill",
        help="Deterministic merge mode.",
    )
    ap.add_argument("--k-rrf", type=float, default=60.0)
    args = ap.parse_args()

    must_path = Path(args.must_report)
    fallback_path = Path(args.fallback_report)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    must_report = load_report(must_path)
    fallback_report = load_report(fallback_path)

    stage2_max_ms = float(args.stage2_max_ms) if args.stage2_max_ms and args.stage2_max_ms > 0 else None

    manifest = {
        "experiment": {
            "arm": "two_stage_hybrid",
            "must_report_path": str(must_path),
            "fallback_report_path": str(fallback_path),
            "two_stage_mode": "must_count_gate",
            "two_stage_min_must_count": int(args.min_must_count),
            "two_stage_stage2_max_additional": int(args.stage2_max_additional),
            "two_stage_stage2_max_ms": stage2_max_ms,
            "fusion_mode": args.fusion_mode,
            "k_rrf": (float(args.k_rrf) if args.fusion_mode == "rrf_fusion" else None),
        }
    }

    report, extra = build_two_stage_hybrid_report(
        must_report=must_report,
        fallback_report=fallback_report,
        run_id=str(args.run_id),
        manifest=manifest,
        min_must_count=int(args.min_must_count),
        stage2_max_additional=int(args.stage2_max_additional),
        stage2_max_ms=stage2_max_ms,
        fusion_mode=args.fusion_mode,
        k_rrf=float(args.k_rrf),
    )

    report_path = out_dir / "retrieval-report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    md_lines = [
        f"# Two-stage hybrid report ({args.run_id})",
        "",
        f"- must_report: `{must_path}`",
        f"- fallback_report: `{fallback_path}`",
        "- mode: must_count_gate",
        f"- fusion_mode: {args.fusion_mode}",
        f"- min_must_count: {int(args.min_must_count)}",
        f"- stage2_max_additional: {int(args.stage2_max_additional)}",
        f"- stage2_max_ms: {('none' if stage2_max_ms is None else f'{stage2_max_ms:.1f}')}",
        "",
        "## Stage2 outcomes",
        f"- stage2_used: {extra['stage_counts'].get('stage2_used', 0)}",
        f"- stage2_skipped_budget: {extra['stage_counts'].get('stage2_skipped_budget', 0)}",
        f"- stage2_not_triggered: {extra['stage_counts'].get('stage2_not_triggered', 0)}",
        "",
        "## Summary metrics",
        f"- hit@k: {report['summary']['hit_at_k']:.4f}",
        f"- precision@k: {report['summary']['precision_at_k']:.4f}",
        f"- recall@k: {report['summary']['recall_at_k']:.4f}",
        f"- mrr: {report['summary']['mrr']:.4f}",
        f"- ndcg@k: {report['summary']['ndcg_at_k']:.4f}",
        f"- latency p50/p95(ms): {report['latency']['search_ms_p50']:.2f}/{report['latency']['search_ms_p95']:.2f}",
        "",
    ]

    if args.fusion_mode == "rrf_fusion":
        md_lines.extend([f"- k_rrf: {float(args.k_rrf):.1f}", ""])

    md_path = out_dir / "retrieval-report.md"
    md_path.write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "ok": True,
                "run_id": str(args.run_id),
                "report_path": str(report_path),
                "md_path": str(md_path),
                "summary": report["summary"],
                "latency": report["latency"],
                "top_k": report["top_k"],
                "manifest": report.get("manifest"),
                "extra": extra,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
