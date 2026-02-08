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


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(txt: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", txt).strip("-").lower()


def _read_profile(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("profile must be a JSON object")
    if data.get("schema") != "openclaw-memory-bench/run-profile/v0.1":
        raise ValueError("unsupported profile schema")
    return data


def _prepare_dataset(profile: dict[str, Any], dataset_limit_override: int | None) -> tuple[Path, dict[str, Any]]:
    bench = str(profile["benchmark"])
    ds = profile.get("dataset") or {}

    limit = dataset_limit_override if dataset_limit_override is not None else ds.get("limit")
    limit = int(limit) if limit is not None else None

    out = Path(str(ds.get("out") or f"data/datasets/{bench}.json"))
    out.parent.mkdir(parents=True, exist_ok=True)

    data = convert_benchmark(bench, limit=limit)
    out = write_dataset(data, out)

    meta = {
        "schema": "openclaw-memory-bench/dataset-meta/v0.1",
        "benchmark": bench,
        "limit": limit,
        "converted_at_utc": datetime.now(UTC).isoformat(),
        "sources": benchmark_sources(bench),
    }
    meta_path = out.with_name(f"{out.name}.meta.json")
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    return out, meta


def _run_provider(
    *,
    provider: str,
    dataset_path: Path,
    dataset_name: str,
    top_k: int,
    question_limit: int | None,
    run_group: str,
    out_dir: Path,
    provider_config: dict[str, Any],
    skip_ingest: bool,
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
        skip_ingest=skip_ingest,
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
        skip_ingest=skip_ingest,
        manifest=manifest,
    )
    report_path = save_report(report, out_dir / provider / "retrieval-report.json")

    return {
        "provider": provider,
        "report_path": str(report_path),
        "top_k": report["top_k"],
        "summary": report["summary"],
        "latency": report["latency"],
        "failures": report.get("failures", []),
        "config": {
            "skip_ingest": skip_ingest,
            "provider_config": provider_config,
        },
    }


def _build_compare(
    *,
    run_group: str,
    run_dir: Path,
    profile_path: Path,
    dataset_path: Path,
    openclaw_report: dict[str, Any],
    memu_report: dict[str, Any],
    memu_mode: dict[str, Any],
) -> tuple[Path, Path]:
    def _metrics(rep: dict[str, Any]) -> dict[str, float]:
        s = rep["summary"]
        latency = rep["latency"]
        return {
            "hit_at_k": float(s["hit_at_k"]),
            "precision_at_k": float(s["precision_at_k"]),
            "recall_at_k": float(s["recall_at_k"]),
            "mrr": float(s["mrr"]),
            "ndcg_at_k": float(s["ndcg_at_k"]),
            "search_ms_p50": float(latency["search_ms_p50"]),
            "search_ms_p95": float(latency["search_ms_p95"]),
            "search_ms_mean": float(latency["search_ms_mean"]),
            "questions_failed": float(s["questions_failed"]),
        }

    m_open = _metrics(openclaw_report)
    m_memu = _metrics(memu_report)

    delta = {k: (m_open[k] - m_memu[k]) for k in m_open.keys()}

    compare = {
        "schema": "openclaw-memory-bench/compare-report/v0.1",
        "run_group": run_group,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "profile_path": str(profile_path.resolve()),
        "profile_sha256": file_sha256(profile_path),
        "dataset_path": str(dataset_path.resolve()),
        "dataset_sha256": file_sha256(dataset_path),
        "providers": {
            "openclaw-mem": openclaw_report,
            "memu-engine": memu_report,
        },
        "memu_execution": memu_mode,
        "delta_openclaw_minus_memu": delta,
        "comparability": {
            "same_top_k": openclaw_report["top_k"] == memu_report["top_k"],
            "same_question_count": openclaw_report["summary"]["questions_total"] == memu_report["summary"]["questions_total"],
        },
    }

    compare_json = run_dir / f"compare-{run_group}.json"
    compare_json.write_text(json.dumps(compare, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Two-plugin compare report ({run_group})",
        "",
        f"- Profile: `{profile_path}`",
        f"- Dataset: `{dataset_path}`",
        "",
        "## openclaw-mem",
        f"- hit@k: {m_open['hit_at_k']:.4f}",
        f"- recall@k: {m_open['recall_at_k']:.4f}",
        f"- mrr: {m_open['mrr']:.4f}",
        f"- ndcg@k: {m_open['ndcg_at_k']:.4f}",
        f"- p50/p95(ms): {m_open['search_ms_p50']:.2f} / {m_open['search_ms_p95']:.2f}",
        "",
        "## memu-engine",
        f"- mode used: {memu_mode['mode_used']} (skip_ingest={memu_mode['skip_ingest']})",
        f"- hit@k: {m_memu['hit_at_k']:.4f}",
        f"- recall@k: {m_memu['recall_at_k']:.4f}",
        f"- mrr: {m_memu['mrr']:.4f}",
        f"- ndcg@k: {m_memu['ndcg_at_k']:.4f}",
        f"- p50/p95(ms): {m_memu['search_ms_p50']:.2f} / {m_memu['search_ms_p95']:.2f}",
        "",
        "## Delta (openclaw-mem - memu-engine)",
        f"- hit@k: {delta['hit_at_k']:+.4f}",
        f"- recall@k: {delta['recall_at_k']:+.4f}",
        f"- mrr: {delta['mrr']:+.4f}",
        f"- ndcg@k: {delta['ndcg_at_k']:+.4f}",
        f"- p50(ms): {delta['search_ms_p50']:+.2f}",
        f"- p95(ms): {delta['search_ms_p95']:+.2f}",
    ]

    compare_md = run_dir / f"compare-{run_group}.md"
    compare_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return compare_json, compare_md


def main() -> int:
    ap = argparse.ArgumentParser(description="Run two-plugin retrieval baseline and generate compare artifacts")
    ap.add_argument("--profile", default="configs/run-profiles/two-plugin-baseline.json")
    ap.add_argument("--dataset-limit", type=int, default=None, help="override dataset conversion limit")
    ap.add_argument("--question-limit", type=int, default=None, help="override benchmark question count used in run")
    ap.add_argument("--run-label", default=None, help="optional suffix for run group")
    ap.add_argument("--gateway-url", default=None, help="override memu gateway url")
    ap.add_argument("--gateway-token", default=None, help="override memu gateway token")
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    profile_path = (repo_root / args.profile).resolve() if not Path(args.profile).is_absolute() else Path(args.profile)
    profile = _read_profile(profile_path)

    out_root = repo_root / str((profile.get("output") or {}).get("root") or "artifacts/full-benchmark")
    run_group = _now_tag() + ("-" + _slug(args.run_label) if args.run_label else "")
    run_dir = out_root / run_group
    run_dir.mkdir(parents=True, exist_ok=True)

    dataset_path, dataset_meta = _prepare_dataset(profile, args.dataset_limit)
    dataset = load_retrieval_dataset(dataset_path)

    retrieval = profile.get("retrieval") or {}
    top_k = int(retrieval.get("top_k") or 10)
    question_limit = args.question_limit if args.question_limit is not None else retrieval.get("question_limit")
    question_limit = int(question_limit) if question_limit is not None else None

    (run_dir / "profile.lock.json").write_text(
        json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (run_dir / "dataset.meta.json").write_text(
        json.dumps(dataset_meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    providers = profile.get("providers") or {}

    # openclaw-mem
    o_cfg_raw = providers.get("openclaw-mem") or {}
    o_cfg = {
        "db_root": str(o_cfg_raw.get("db_root") or "artifacts/provider-state/openclaw-mem"),
    }
    if o_cfg_raw.get("db_path"):
        o_cfg["db_path"] = str(o_cfg_raw["db_path"])
    if o_cfg_raw.get("openclaw_mem_project"):
        o_cfg["openclaw_mem_project"] = str(o_cfg_raw["openclaw_mem_project"])

    openclaw_report = _run_provider(
        provider="openclaw-mem",
        dataset_path=dataset_path,
        dataset_name=dataset.name,
        top_k=top_k,
        question_limit=question_limit,
        run_group=run_group,
        out_dir=run_dir,
        provider_config=o_cfg,
        skip_ingest=False,
    )

    # memu-engine with fallback policy
    m_cfg_raw = providers.get("memu-engine") or {}
    preferred_mode = str(m_cfg_raw.get("ingest_mode") or "memory_store")
    allow_fallback = bool(m_cfg_raw.get("allow_fallback_skip_ingest", True))

    base_m_cfg = {
        "gateway_url": args.gateway_url or m_cfg_raw.get("gateway_url"),
        "gateway_token": args.gateway_token or m_cfg_raw.get("gateway_token"),
        "agent_id": str(m_cfg_raw.get("agent_id") or "main"),
        "session_key": str(m_cfg_raw.get("session_key") or "main"),
    }

    memu_mode: dict[str, Any] = {
        "preferred_mode": preferred_mode,
        "mode_used": preferred_mode,
        "skip_ingest": False,
        "fallback_triggered": False,
        "fallback_reason": None,
    }

    try:
        m_cfg = dict(base_m_cfg)
        m_cfg["ingest_mode"] = preferred_mode
        memu_report = _run_provider(
            provider="memu-engine",
            dataset_path=dataset_path,
            dataset_name=dataset.name,
            top_k=top_k,
            question_limit=question_limit,
            run_group=run_group,
            out_dir=run_dir,
            provider_config=m_cfg,
            skip_ingest=False,
        )

        # Trigger fallback when preferred mode effectively failed for the full run.
        failed = int(memu_report["summary"]["questions_failed"])
        succeeded = int(memu_report["summary"]["questions_succeeded"])
        if failed > 0 and succeeded == 0 and allow_fallback:
            first_err = None
            if memu_report["failures"]:
                first_err = memu_report["failures"][0].get("error")
            raise RuntimeError(first_err or "memu preferred mode failed without successful questions")
    except Exception as e:  # noqa: BLE001
        if not allow_fallback:
            raise

        memu_mode["fallback_triggered"] = True
        memu_mode["fallback_reason"] = str(e)
        memu_mode["mode_used"] = "noop"
        memu_mode["skip_ingest"] = True

        m_cfg = dict(base_m_cfg)
        m_cfg["ingest_mode"] = "noop"
        memu_report = _run_provider(
            provider="memu-engine",
            dataset_path=dataset_path,
            dataset_name=dataset.name,
            top_k=top_k,
            question_limit=question_limit,
            run_group=run_group,
            out_dir=run_dir,
            provider_config=m_cfg,
            skip_ingest=True,
        )

    compare_json, compare_md = _build_compare(
        run_group=run_group,
        run_dir=run_dir,
        profile_path=profile_path,
        dataset_path=dataset_path,
        openclaw_report=openclaw_report,
        memu_report=memu_report,
        memu_mode=memu_mode,
    )

    payload = {
        "ok": True,
        "run_group": run_group,
        "dataset": str(dataset_path),
        "question_count": len(dataset.questions),
        "question_limit_used": question_limit,
        "openclaw_report": openclaw_report["report_path"],
        "memu_report": memu_report["report_path"],
        "compare_json": str(compare_json),
        "compare_md": str(compare_md),
        "memu_mode": memu_mode,
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
