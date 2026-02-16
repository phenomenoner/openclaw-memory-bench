from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import re
import signal
import subprocess
import time
import traceback
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


def _ts() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(txt: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", txt).strip("-").lower()


def _log(msg: str, progress_log: Path | None) -> None:
    line = f"[{_ts()}] {msg}"
    print(line, flush=True)
    if progress_log is not None:
        progress_log.parent.mkdir(parents=True, exist_ok=True)
        with progress_log.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")


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
        "status": "ok",
        "report_path": str(report_path),
        "top_k": report["top_k"],
        "summary": report["summary"],
        "latency": report["latency"],
    }


def _provider_worker(queue: mp.Queue, kwargs: dict[str, Any]) -> None:
    try:
        result = _run_provider(**kwargs)
        queue.put({"ok": True, "result": result})
    except Exception as exc:  # pragma: no cover - defensive guard path
        queue.put(
            {
                "ok": False,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            }
        )


def _descendant_pids(root_pid: int) -> list[int]:
    try:
        out = subprocess.check_output(["ps", "-eo", "pid=,ppid="], text=True)
    except Exception:
        return []

    children: dict[int, list[int]] = {}
    for line in out.splitlines():
        parts = line.strip().split()
        if len(parts) != 2:
            continue
        try:
            pid = int(parts[0])
            ppid = int(parts[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)

    stack = [root_pid]
    found: list[int] = []
    while stack:
        cur = stack.pop()
        for ch in children.get(cur, []):
            found.append(ch)
            stack.append(ch)
    return found


def _kill_pid_tree(root_pid: int) -> None:
    pids = [root_pid, *_descendant_pids(root_pid)]

    for sig in (signal.SIGTERM, signal.SIGKILL):
        for pid in pids:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                continue
            except PermissionError:
                continue
        time.sleep(0.4)


def _run_provider_with_timeout(*, kwargs: dict[str, Any], timeout_sec: int) -> dict[str, Any]:
    ctx = mp.get_context("spawn")
    queue: mp.Queue = ctx.Queue()
    proc = ctx.Process(target=_provider_worker, args=(queue, kwargs))
    proc.start()
    proc.join(timeout=timeout_sec)

    if proc.is_alive():
        _kill_pid_tree(proc.pid)
        proc.join(2)
        return {
            "ok": False,
            "error": f"PROVIDER_TIMEOUT: exceeded {timeout_sec}s wall time",
            "traceback": None,
        }

    if not queue.empty():
        return queue.get()

    return {
        "ok": False,
        "error": f"PROVIDER_CRASHED: process exitcode={proc.exitcode}",
        "traceback": None,
    }


def _failed_provider_result(
    *,
    provider: str,
    question_total: int,
    top_k: int,
    reason: str,
    code: str,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "status": "failed",
        "report_path": None,
        "top_k": top_k,
        "summary": {
            "questions_total": question_total,
            "questions_succeeded": 0,
            "questions_failed": question_total,
            "hit_at_k": 0.0,
            "precision_at_k": 0.0,
            "recall_at_k": 0.0,
            "mrr": 0.0,
            "ndcg_at_k": 0.0,
            "failure_breakdown": {
                "by_code": {code: question_total},
                "by_category": {"provider_error": question_total},
                "by_phase": {"provider": question_total},
            },
        },
        "latency": {
            "search_ms_p50": 0.0,
            "search_ms_p95": 0.0,
            "search_ms_mean": 0.0,
        },
        "error": reason,
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
    ap.add_argument("--provider-timeout-sec", type=int, default=1500)
    ap.add_argument("--fail-fast-provider", action="store_true")
    ap.add_argument("--progress-log", default=None)

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
    run_dir = repo_root / args.output_root / run_group
    run_dir.mkdir(parents=True, exist_ok=True)

    progress_log = Path(args.progress_log) if args.progress_log else run_dir / "progress.log"

    _log(f"run_group={run_group} benchmark={args.benchmark}", progress_log)

    dataset_out = repo_root / "data" / "datasets" / f"{args.benchmark}-{args.dataset_limit}.json"
    dataset_path, dataset_meta = _prepare_dataset(
        benchmark=args.benchmark,
        limit=args.dataset_limit,
        out=dataset_out,
    )

    dataset = load_retrieval_dataset(dataset_path)
    effective_questions = min(args.question_limit, len(dataset.questions)) if args.question_limit is not None else len(dataset.questions)

    (run_dir / "dataset.meta.json").write_text(
        json.dumps(dataset_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    openclaw_mem_cfg: dict[str, Any] = {
        "db_root": args.openclaw_mem_db_root,
    }
    openclaw_mem_project = os.environ.get("OPENCLAW_MEM_PROJECT") or os.environ.get(
        "OPENCLAW_MEM_PROJECT_DIR"
    )
    if openclaw_mem_project:
        openclaw_mem_cfg["openclaw_mem_project"] = openclaw_mem_project

    provider_specs: list[tuple[str, dict[str, Any], bool]] = [
        (
            "memory-core",
            {
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
            args.memory_core_preindex_once,
        ),
        (
            "memory-lancedb",
            {
                "session_key": args.lancedb_session_key,
                "recall_limit_factor": args.lancedb_recall_limit_factor,
            },
            False,
        ),
        (
            "openclaw-mem",
            openclaw_mem_cfg,
            False,
        ),
    ]

    providers: dict[str, dict[str, Any]] = {}
    provider_status: dict[str, dict[str, Any]] = {}

    for provider_name, provider_config, preindex_once in provider_specs:
        _log(f"provider={provider_name} status=starting", progress_log)

        payload = _run_provider_with_timeout(
            kwargs={
                "provider": provider_name,
                "provider_config": provider_config,
                "dataset_path": dataset_path,
                "dataset_name": dataset.name,
                "top_k": args.top_k,
                "question_limit": args.question_limit,
                "run_group": run_group,
                "out_dir": run_dir,
                "preindex_once": preindex_once,
            },
            timeout_sec=args.provider_timeout_sec,
        )

        if payload.get("ok"):
            provider_result = payload["result"]
            providers[provider_name] = provider_result
            provider_status[provider_name] = {"status": "ok", "error": None}
            _log(
                f"provider={provider_name} status=ok failed={provider_result['summary']['questions_failed']} "
                f"hit@k={provider_result['summary']['hit_at_k']:.4f}",
                progress_log,
            )
            continue

        err = str(payload.get("error") or "UNKNOWN_PROVIDER_ERROR")
        traceback_text = payload.get("traceback")
        if traceback_text:
            (run_dir / f"{provider_name}-error.log").write_text(traceback_text, encoding="utf-8")

        providers[provider_name] = _failed_provider_result(
            provider=provider_name,
            question_total=effective_questions,
            top_k=args.top_k,
            reason=err,
            code="PROVIDER_TIMEOUT" if "TIMEOUT" in err else "PROVIDER_ERROR",
        )
        provider_status[provider_name] = {"status": "failed", "error": err}
        _log(f"provider={provider_name} status=failed reason={err}", progress_log)

        if args.fail_fast_provider:
            _log("fail_fast_provider=true; aborting remaining providers", progress_log)
            break

    for provider_name, _, _ in provider_specs:
        if provider_name in providers:
            continue
        providers[provider_name] = _failed_provider_result(
            provider=provider_name,
            question_total=effective_questions,
            top_k=args.top_k,
            reason="SKIPPED_AFTER_FAIL_FAST",
            code="PROVIDER_SKIPPED",
        )
        provider_status[provider_name] = {"status": "skipped", "error": "SKIPPED_AFTER_FAIL_FAST"}

    metrics = {name: _metric_pack(rep) for name, rep in providers.items()}

    compare = {
        "schema": "openclaw-memory-bench/comprehensive-triplet-report/v0.2",
        "run_group": run_group,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "benchmark": args.benchmark,
        "question_limit": args.question_limit,
        "top_k": args.top_k,
        "provider_timeout_sec": args.provider_timeout_sec,
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": file_sha256(dataset_path),
        "providers": providers,
        "provider_status": provider_status,
        "progress_log": str(progress_log),
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
        f"- provider_timeout_sec: {args.provider_timeout_sec}",
        f"- progress_log: `{progress_log}`",
        "",
    ]

    for name in ["memory-core", "memory-lancedb", "openclaw-mem"]:
        m = metrics[name]
        st = provider_status.get(name, {"status": "unknown", "error": None})
        lines.extend(
            [
                f"## {name}",
                f"- status: {st['status']}",
                f"- error: {st.get('error') or 'none'}",
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

    _log(f"status=done compare_json={compare_json}", progress_log)

    print(
        json.dumps(
            {
                "ok": True,
                "run_group": run_group,
                "dataset": str(dataset_path),
                "progress_log": str(progress_log),
                "compare_json": str(compare_json),
                "compare_md": str(compare_md),
                "provider_status": provider_status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
