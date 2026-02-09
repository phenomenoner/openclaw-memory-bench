from __future__ import annotations

import argparse
import json
import platform
from datetime import UTC, datetime
from pathlib import Path

from .adapters import available_adapters
from .converters import benchmark_sources, convert_benchmark, write_dataset
from .dataset import load_retrieval_dataset
from .manifest import build_retrieval_manifest
from .runner import run_retrieval_benchmark, save_report
from .validation import validate_dataset_payload


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


def cmd_prepare_dataset(args: argparse.Namespace) -> int:
    data = convert_benchmark(args.benchmark, limit=args.limit)
    validate_dataset_payload(data)
    out = write_dataset(data, args.out)

    meta = {
        "schema": "openclaw-memory-bench/dataset-meta/v0.1",
        "benchmark": args.benchmark,
        "limit": args.limit,
        "converted_at_utc": datetime.now(UTC).isoformat(),
        "sources": benchmark_sources(args.benchmark),
    }
    meta_path = out.with_name(f"{out.name}.meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    payload = {
        "ok": True,
        "benchmark": args.benchmark,
        "questions": len(data.get("questions", [])),
        "out": str(out),
        "meta": str(meta_path),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
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

    if provider == "memu-engine":
        provider_config["gateway_url"] = args.gateway_url
        provider_config["gateway_token"] = args.gateway_token
        provider_config["agent_id"] = args.agent_id
        provider_config["session_key"] = args.session_key
        provider_config["ingest_mode"] = args.memu_ingest_mode

    if provider == "memory-core":
        provider_config["profile"] = args.memory_core_profile
        provider_config["agent_id"] = args.memory_core_agent
        provider_config["timeout_sec"] = args.memory_core_timeout_sec
        provider_config["force_reindex"] = args.memory_core_force_reindex
        provider_config["index_retries"] = args.memory_core_index_retries
        provider_config["search_limit_factor"] = args.memory_core_search_limit_factor
        provider_config["max_messages_per_session"] = args.memory_core_max_messages_per_session
        provider_config["max_message_chars"] = args.memory_core_max_message_chars
        provider_config["max_chars_per_session"] = args.memory_core_max_chars_per_session

    if provider == "memory-lancedb":
        provider_config["gateway_url"] = args.gateway_url
        provider_config["gateway_token"] = args.gateway_token
        provider_config["agent_id"] = args.agent_id
        provider_config["session_key"] = args.session_key
        provider_config["recall_limit_factor"] = args.lancedb_recall_limit_factor

    manifest = build_retrieval_manifest(
        run_id=run_id,
        provider=provider,
        provider_config=provider_config,
        dataset_path=args.dataset,
        dataset_name=dataset.name,
        top_k=args.top_k,
        limit=args.limit,
        sample_size=args.sample_size,
        sample_seed=args.sample_seed,
        skip_ingest=args.skip_ingest,
        preindex_once=args.preindex_once,
        fail_fast=args.fail_fast,
        repo_dir=Path(__file__).resolve().parents[2],
    )

    report = run_retrieval_benchmark(
        provider=provider,
        dataset=dataset,
        top_k=args.top_k,
        run_id=run_id,
        provider_config=provider_config,
        fail_fast=args.fail_fast,
        limit=args.limit,
        sample_size=args.sample_size,
        sample_seed=args.sample_seed,
        skip_ingest=args.skip_ingest,
        preindex_once=args.preindex_once,
        manifest=manifest,
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
    plan.add_argument(
        "--provider",
        required=True,
        help="openclaw-mem | memu-engine | memory-core | memory-lancedb",
    )
    plan.add_argument("--benchmark", required=True, help="locomo | longmemeval | convomem")
    plan.add_argument("--track", default="retrieval", choices=["retrieval", "e2e"])
    plan.add_argument("--limit", type=int, default=50)
    plan.add_argument("--run-id", default=None)
    plan.add_argument("--out", default="artifacts/run-manifest.json")
    plan.set_defaults(func=cmd_plan)

    prep = sub.add_parser("prepare-dataset", help="Download and convert canonical benchmark dataset")
    prep.add_argument("--benchmark", required=True, choices=["locomo", "longmemeval", "convomem"])
    prep.add_argument("--limit", type=int, default=None, help="Limit number of converted questions")
    prep.add_argument("--out", required=True, help="Output retrieval dataset JSON path")
    prep.set_defaults(func=cmd_prepare_dataset)

    run = sub.add_parser("run-retrieval", help="Execute deterministic retrieval benchmark")
    run.add_argument(
        "--provider",
        required=True,
        help="openclaw-mem | memu-engine | memory-core | memory-lancedb",
    )
    run.add_argument("--dataset", required=True, help="Path to retrieval dataset JSON")
    run.add_argument("--top-k", type=int, default=10)
    run.add_argument("--run-id", default=None)
    run.add_argument("--limit", type=int, default=None)
    run.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Deterministically sample N questions before applying --limit",
    )
    run.add_argument(
        "--sample-seed",
        type=int,
        default=None,
        help="Seed for deterministic question sampling (default 0 when --sample-size is set)",
    )
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
    run.add_argument("--skip-ingest", action="store_true", help="Skip adapter ingest and search existing memory")
    run.add_argument(
        "--preindex-once",
        action="store_true",
        help="Ingest/index selected dataset once for all questions, then run per-question search only",
    )
    run.add_argument("--fail-fast", action="store_true")

    # memory-core options
    run.add_argument(
        "--memory-core-profile",
        default="membench-memory-core",
        help="(memory-core) isolated OpenClaw profile name",
    )
    run.add_argument("--memory-core-agent", default="main", help="(memory-core) agent id")
    run.add_argument(
        "--memory-core-timeout-sec",
        type=int,
        default=120,
        help="(memory-core) base command timeout in seconds",
    )
    run.add_argument(
        "--memory-core-force-reindex",
        action="store_true",
        help="(memory-core) force full reindex each ingest (slower)",
    )
    run.add_argument(
        "--memory-core-index-retries",
        type=int,
        default=1,
        help="(memory-core) reindex retry count on timeout/transient failures",
    )
    run.add_argument(
        "--memory-core-search-limit-factor",
        type=int,
        default=8,
        help="(memory-core) multiply top-k for candidate pool before container filtering",
    )
    run.add_argument(
        "--memory-core-max-messages-per-session",
        type=int,
        default=80,
        help="(memory-core) cap turns ingested per session (head+tail strategy)",
    )
    run.add_argument(
        "--memory-core-max-message-chars",
        type=int,
        default=800,
        help="(memory-core) cap chars per message during ingest",
    )
    run.add_argument(
        "--memory-core-max-chars-per-session",
        type=int,
        default=12000,
        help="(memory-core) total char budget per session markdown",
    )

    # memu-engine / gateway options
    run.add_argument("--gateway-url", default=None, help="Gateway base URL (default from local config)")
    run.add_argument("--gateway-token", default=None, help="Gateway token (default from env/config)")
    run.add_argument("--agent-id", default="main", help="x-openclaw-agent-id header")
    run.add_argument("--session-key", default="main", help="sessionKey for tools/invoke")
    run.add_argument(
        "--memu-ingest-mode",
        default="noop",
        choices=["noop", "memory_store"],
        help="memu-engine ingest strategy",
    )
    run.add_argument(
        "--lancedb-recall-limit-factor",
        type=int,
        default=10,
        help="(memory-lancedb) multiply top-k to set memory_recall candidate pool before container filter",
    )

    run.set_defaults(func=cmd_run_retrieval)

    return p


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
