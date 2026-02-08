from __future__ import annotations

import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

from .adapters import available_adapters


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
        "notes": "Scaffold manifest generated. Executor pipeline WIP.",
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({"ok": True, "manifest": str(out), "run_id": run_id}, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="openclaw-memory-bench")
    sub = p.add_subparsers(dest="cmd", required=True)

    doctor = sub.add_parser("doctor", help="Show environment and adapter availability")
    doctor.set_defaults(func=cmd_doctor)

    plan = sub.add_parser("plan", help="Generate reproducible run manifest (scaffold)")
    plan.add_argument("--provider", required=True, help="openclaw-mem | memu-engine")
    plan.add_argument("--benchmark", required=True, help="locomo | longmemeval | convomem")
    plan.add_argument("--track", default="retrieval", choices=["retrieval", "e2e"])
    plan.add_argument("--limit", type=int, default=50)
    plan.add_argument("--run-id", default=None)
    plan.add_argument("--out", default="artifacts/run-manifest.json")
    plan.set_defaults(func=cmd_plan)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
