from __future__ import annotations

import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

from .adapters import available_adapters
from .dataset import load_retrieval_dataset
from .runner import run_retrieval_benchmark, save_report


def cmd_doctor(args: argparse.Namespace) -> int:
    payload = {
        "ok": True,
        "python": platform.python_version(),
        "platform": platform.platform(),
        "adapters": sorted(list(available_adapters().keys())),
        "timestamp_utc": datetime.now(UTC).isoformat(),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    benchmark = args.benchmark
    provider = args.provider
    if provider not in available_adapters():
        raise SystemExit(f"Unknown provider: {provider}")

    run_id = args.run_id or datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")
    manifest = {
        "schema": "openclaw-memory-bench/run-manifest/v0.1",
        "run_id": run_id,
        "provider": provider,
        "benchmark": benchmark,
        "track": args.track,
        "limit": args.limit,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "notes": "Scaffold manifest generated. Use run-retrieval for executable retrieval runs.",
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"ok": True, "manifest": str(out), "run_id": run_id}, ensure_ascii=False, indent=2))
    return 0


def cmd_run_retrieval(args: argparse.Namespace) -> int:
    provider = args.provider
    if provider not in available_adapters():
        raise SystemExit(f"Unknown provider: {provider}")

    dataset = load_retrieval_dataset(args.dataset)
    run_id = args.run_id or datetime.now(UTC).strftime("run-%Y%m%d-%H%M%S")

    provider_config: dict = {}
    if provider == "openclaw-mem":
        if args.db_path:
            provider_config["db_path"] = args.db_path
        provider_config["db_root"] = args.db_root
        provider_config["openclaw_mem_project"] = args.openclaw_mem_project
        if args.openclaw_mem_cmd:
            provider_config["command_base"] = args.openclaw_mem_cmd

    report = run_retrieval_benchmark(
        provider=provider,
        dataset=dataset,
        top_k=args.top_k,
        run_id=run_id,
        provider_config=provider_config,
        fail_fast=args.fail_fast,
        limit=args.limit,
    )

    out = args.out or f"artifacts/{run_id}/retrieval-report.json"
    report_path = save_report(report, out)

    summary = {
        "ok": report["summary"]["questions_failed"] == 0,
        "run_id": run_id,
        "provider": provider,
        "dataset": dataset.name,
        "top_k": args.top_k,
        "report": str(report_path),
        "summary": report["summary"],
        "latency": report["latency"],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    return 0 if report["summary"]["questions_failed"] == 0 else 3


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openclaw-memory-bench")
    sub = p.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="Show environment and adapter availability")
    doctor.set_defaults(func=cmd_doctor)

    plan = sub.add_parser("plan", help="Generate reproducible run manifest")
    plan.add_argument("--provider", required=True, help="openclaw-mem | memu-engine")
    plan.add_argument("--benchmark", required=True, help="locomo | longmemeval | convomem")
    plan.add_argument("--track", default="retrieval", choices=["retrieval", "e2e"])
    plan.add_argument("--limit", type=int, default=50)
    plan.add_argument("--run-id", default=None)
    plan.add_argument("--out", default="artifacts/run-manifest.json")
    plan.set_defaults(func=cmd_plan)

    run = sub.add_parser("run-retrieval", help="Execute deterministic retrieval benchmark")
    run.add_argument("--provider", required=True, help="openclaw-mem | memu-engine")
    run.add_argument("--dataset", required=True, help="Path to retrieval dataset JSON")
    run.add_argument("--top-k", type=int, default=10)
    run.add_argument("--run-id", default=None)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument("--db-path", default=None, help="(openclaw-mem) fixed DB path")
    run.add_argument(
        "--db-root",
        default="artifacts/provider-state/openclaw-mem",
        help="(openclaw-mem) per-container DB root",
    )
    run.add_argument(
        "--openclaw-mem-project",
        default="/home/agent/.openclaw/workspace/openclaw-mem",
        help="(openclaw-mem) project path for uv fallback",
    )
    run.add_argument(
        "--openclaw-mem-cmd",
        nargs="+",
        default=None,
        help="(openclaw-mem) explicit command base override, e.g. openclaw-mem",
    )
    run.add_argument("--out", default=None, help="Output report path")
    run.add_argument("--fail-fast", action="store_true")
    run.set_defaults(func=cmd_run_retrieval)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
