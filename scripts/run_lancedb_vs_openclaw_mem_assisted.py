from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from openclaw_memory_bench.dataset import load_retrieval_dataset
from openclaw_memory_bench.hybrid import build_two_stage_hybrid_report
from openclaw_memory_bench.manifest import build_retrieval_manifest, file_sha256, resolve_git_commit
from openclaw_memory_bench.runner import run_retrieval_benchmark, save_report


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(txt: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_.-]+", "-", txt).strip("-").lower()


def _resolve_run_group(*, explicit_run_group: str | None, run_label: str) -> str:
    if explicit_run_group:
        run_group = _slug(explicit_run_group)
        if not run_group:
            raise ValueError("--run-group resolved to empty slug; provide a non-empty value")
        return run_group
    return f"{_now_tag()}-{_slug(run_label)}"


def _load_json(path: Path) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("dataset root must be object")
    return raw


def _session_chars(session: dict[str, Any]) -> int:
    total = 0
    for m in session.get("messages", []):
        if isinstance(m, dict):
            total += len(str(m.get("content") or ""))
    return total


def _session_importance_label(session: dict[str, Any]) -> str:
    metadata = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    for key in ("importance", "importance_label", "priority", "must_remember"):
        if key not in metadata:
            continue
        val = metadata[key]
        if isinstance(val, bool):
            return "must" if val else "ignore"
        sval = str(val).strip().lower()
        if sval in {"must", "must_remember", "critical", "high", "p1"}:
            return "must"
        if sval in {"nice", "nice_to_have", "medium", "p2"}:
            return "nice"
        if sval in {"ignore", "low", "p3"}:
            return "ignore"

    # Fallback lexical proxy when dataset lacks labels.
    merged = "\n".join(str(m.get("content") or "") for m in session.get("messages", []) if isinstance(m, dict)).lower()
    must_kw = (
        "must remember",
        "important",
        "critical",
        "deadline",
        "risk",
        "hard stop",
        "do not forget",
        "no exceptions",
    )
    nice_kw = (
        "preference",
        "like",
        "usually",
        "plan",
        "note",
        "remind",
    )
    if any(k in merged for k in must_kw):
        return "must"
    if any(k in merged for k in nice_kw):
        return "nice"
    return "ignore"


def _filter_dataset(raw: dict[str, Any], *, policy: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if policy not in {"must", "must+nice"}:
        raise ValueError(f"unsupported policy: {policy}")

    q_in = raw.get("questions")
    if not isinstance(q_in, list) or not q_in:
        raise ValueError("dataset.questions must be non-empty list")

    kept_questions: list[dict[str, Any]] = []
    q_dropped = 0
    sessions_total = 0
    sessions_kept = 0
    chars_total = 0
    chars_kept = 0

    for q in q_in:
        if not isinstance(q, dict):
            continue
        sessions = q.get("sessions")
        if not isinstance(sessions, list) or not sessions:
            continue

        keep: list[dict[str, Any]] = []
        for s in sessions:
            if not isinstance(s, dict):
                continue
            sessions_total += 1
            chars = _session_chars(s)
            chars_total += chars
            label = _session_importance_label(s)

            allowed = label == "must" or (policy == "must+nice" and label in {"must", "nice"})
            if allowed:
                keep.append(s)
                sessions_kept += 1
                chars_kept += chars

        if not keep:
            q_dropped += 1
            continue

        rel = [str(x) for x in q.get("relevant_session_ids", []) if str(x)]
        keep_ids = {str(s.get("session_id") or "") for s in keep}
        new_rel = [sid for sid in rel if sid in keep_ids]
        if not new_rel:
            # Keep question evaluable even when filter prunes original evidence.
            new_rel = [str(keep[0].get("session_id"))]

        q2 = dict(q)
        q2["sessions"] = keep
        q2["relevant_session_ids"] = new_rel
        kept_questions.append(q2)

    out = dict(raw)
    out["name"] = f"{raw.get('name', 'dataset')}-ingest-{policy}"
    out["questions"] = kept_questions

    stats = {
        "policy": policy,
        "questions_total": len(q_in),
        "questions_kept": len(kept_questions),
        "questions_dropped": q_dropped,
        "sessions_total": sessions_total,
        "sessions_kept": sessions_kept,
        "items_stored_estimate": sessions_kept,
        "chars_total": chars_total,
        "chars_kept": chars_kept,
        "vector_count_estimate": sessions_kept,
        "compression_ratio_items": (sessions_kept / sessions_total) if sessions_total else 0.0,
        "compression_ratio_chars": (chars_kept / chars_total) if chars_total else 0.0,
        "labeling_mode": "metadata+lexical-proxy",
    }
    return out, stats


def _compress_session_observational(
    session: dict[str, Any],
    *,
    max_lines: int = 12,
    max_chars_per_line: int = 240,
) -> tuple[dict[str, Any], int]:
    sid = str(session.get("session_id") or "")
    label = _session_importance_label(session)

    msgs = session.get("messages")
    msgs = msgs if isinstance(msgs, list) else []

    lines: list[str] = [f"OBSERVATION [{label}] [session:{sid}]".strip()]

    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = str(m.get("role") or "")
        content = str(m.get("content") or "").strip()
        if not content:
            continue

        # Make it log-like and stable.
        content = " ".join(content.split())
        if len(content) > max_chars_per_line:
            content = content[: max_chars_per_line - 1] + "…"

        ts = m.get("ts")
        if ts:
            lines.append(f"- {role}@{ts}: {content}")
        else:
            lines.append(f"- {role}: {content}")

        if len(lines) - 1 >= max_lines:
            break

    obs_text = "\n".join(lines).strip() + "\n"

    meta_in = session.get("metadata") if isinstance(session.get("metadata"), dict) else {}
    meta = dict(meta_in)
    meta.setdefault("compression", "observational-v0")
    meta.setdefault("importance_label", label)

    out = dict(session)
    out["metadata"] = meta
    out["messages"] = [
        {
            "role": "system",
            "content": obs_text,
            "ts": None,
        }
    ]
    return out, len(obs_text)


def _compress_dataset_observational(
    raw: dict[str, Any],
    *,
    max_lines: int = 12,
    max_chars_per_line: int = 240,
) -> tuple[dict[str, Any], dict[str, Any]]:
    q_in = raw.get("questions")
    if not isinstance(q_in, list) or not q_in:
        raise ValueError("dataset.questions must be non-empty list")

    kept_questions: list[dict[str, Any]] = []
    sessions_total = 0
    chars_total = 0
    chars_kept = 0

    for q in q_in:
        if not isinstance(q, dict):
            continue
        sessions = q.get("sessions")
        if not isinstance(sessions, list) or not sessions:
            continue

        new_sessions: list[dict[str, Any]] = []
        for s in sessions:
            if not isinstance(s, dict):
                continue
            sessions_total += 1
            chars_total += _session_chars(s)
            s2, kept_chars = _compress_session_observational(
                s,
                max_lines=max_lines,
                max_chars_per_line=max_chars_per_line,
            )
            chars_kept += kept_chars
            new_sessions.append(s2)

        if not new_sessions:
            continue

        q2 = dict(q)
        q2["sessions"] = new_sessions
        kept_questions.append(q2)

    out = dict(raw)
    out["name"] = f"{raw.get('name', 'dataset')}-observational"
    out["questions"] = kept_questions

    stats = {
        "mode": "observational",
        "questions_total": len(q_in),
        "questions_kept": len(kept_questions),
        "sessions_total": sessions_total,
        "sessions_kept": sessions_total,
        "items_stored_estimate": sessions_total,
        "chars_total": chars_total,
        "chars_kept": chars_kept,
        "vector_count_estimate": sessions_total,
        "compression_ratio_items": 1.0,
        "compression_ratio_chars": (chars_kept / chars_total) if chars_total else 0.0,
        "max_lines": max_lines,
        "max_chars_per_line": max_chars_per_line,
    }
    return out, stats


def _run_lancedb(
    *,
    dataset_path: Path,
    out_dir: Path,
    run_group: str,
    run_suffix: str,
    top_k: int,
    question_limit: int | None,
    sample_size: int | None,
    sample_seed: int | None,
    session_key: str,
    gateway_url: str | None,
    gateway_token: str | None,
    recall_limit_factor: int,
    extra_manifest_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    provider = "memory-lancedb"
    provider_config: dict[str, Any] = {
        "session_key": session_key,
        "recall_limit_factor": recall_limit_factor,
    }
    if gateway_url:
        provider_config["gateway_url"] = gateway_url
    if gateway_token:
        provider_config["gateway_token"] = gateway_token

    dataset = load_retrieval_dataset(dataset_path)
    run_id = f"{run_group}-{run_suffix}"

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
        sample_size=sample_size,
        sample_seed=sample_seed,
        repo_dir=Path(__file__).resolve().parents[1],
    )
    if extra_manifest_fields:
        manifest["experiment"] = extra_manifest_fields

    report = run_retrieval_benchmark(
        provider=provider,
        dataset=dataset,
        top_k=top_k,
        run_id=run_id,
        provider_config=provider_config,
        fail_fast=False,
        limit=question_limit,
        sample_size=sample_size,
        sample_seed=sample_seed,
        skip_ingest=False,
        manifest=manifest,
    )

    report_path = save_report(report, out_dir / run_suffix / "retrieval-report.json")
    return {
        "label": run_suffix,
        "report_path": str(report_path),
        "summary": report["summary"],
        "latency": report["latency"],
        "top_k": report["top_k"],
        "manifest": report.get("manifest"),
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
    }


def _win_eval(*, baseline: dict[str, float], candidate: dict[str, float], policy: str) -> dict[str, Any]:
    p95_gain = (
        (baseline["search_ms_p95"] - candidate["search_ms_p95"]) / baseline["search_ms_p95"]
        if baseline["search_ms_p95"]
        else 0.0
    )
    recall_drop = baseline["recall_at_k"] - candidate["recall_at_k"]
    ndcg_delta = candidate["ndcg_at_k"] - baseline["ndcg_at_k"]
    return {
        "policy": policy,
        "win": bool(p95_gain >= 0.20 and recall_drop <= 0.03 and ndcg_delta >= 0.0),
        "p95_gain_ratio": p95_gain,
        "recall_drop_abs": recall_drop,
        "ndcg_delta": ndcg_delta,
    }


def _write_hybrid_markdown(
    *,
    path: Path,
    run_id: str,
    report: dict[str, Any],
    stage_counts: dict[str, int],
    must_policy: str,
    fallback_policy: str,
) -> None:
    cfg = report.get("config") if isinstance(report.get("config"), dict) else {}
    lines = [
        f"# Two-stage hybrid report ({run_id})",
        "",
        f"- must_policy: `{must_policy}`",
        f"- fallback_policy: `{fallback_policy}`",
        f"- fusion_mode: {cfg.get('fusion_mode', 'append_fill')}",
        f"- min_must_count: {cfg.get('min_must_count', 'n/a')}",
        f"- stage2_max_additional: {cfg.get('stage2_max_additional', 'n/a')}",
        f"- stage2_max_ms: {cfg.get('stage2_max_ms', 'n/a')}",
        "",
        "## Stage2 outcomes",
        f"- stage2_used: {stage_counts.get('stage2_used', 0)}",
        f"- stage2_skipped_budget: {stage_counts.get('stage2_skipped_budget', 0)}",
        f"- stage2_not_triggered: {stage_counts.get('stage2_not_triggered', 0)}",
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
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Compare memory-lancedb baseline vs openclaw-mem-assisted importance-gated ingest (proxy)."
    )
    ap.add_argument("--dataset", default="examples/dual_language_mini.json")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--question-limit", type=int, default=None)
    ap.add_argument("--sample-size", type=int, default=None)
    ap.add_argument("--sample-seed", type=int, default=7)
    ap.add_argument("--session-key", default="main")
    ap.add_argument("--gateway-url", default=None)
    ap.add_argument("--gateway-token", default=None)
    ap.add_argument("--lancedb-recall-limit-factor", type=int, default=10)
    ap.add_argument("--run-label", default="phase-ab-lancedb-vs-openclaw-mem-assist")
    ap.add_argument(
        "--run-group",
        default=None,
        help="Optional explicit run-group directory name for deterministic artifact paths.",
    )
    ap.add_argument("--output-root", default="artifacts/phase-ab-compare")
    ap.add_argument(
        "--latest-pointer-name",
        default="compare-latest.md",
        help="Stable markdown pointer file written under output root.",
    )
    ap.add_argument(
        "--policies",
        nargs="+",
        default=["must", "must+nice"],
        choices=["must", "must+nice"],
        help="Importance-gating policies to evaluate for experimental arm.",
    )
    ap.add_argument(
        "--include-observational",
        action="store_true",
        help="Also run an observational compression arm (derived dataset; text-shape proxy).",
    )
    ap.add_argument(
        "--include-hybrid",
        action="store_true",
        help="Build a third arm by fusing two experimental policy reports (must -> must+nice).",
    )
    ap.add_argument("--hybrid-must-policy", choices=["must", "must+nice"], default="must")
    ap.add_argument("--hybrid-fallback-policy", choices=["must", "must+nice"], default="must+nice")
    ap.add_argument("--hybrid-min-must-count", type=int, default=3)
    ap.add_argument("--hybrid-stage2-max-additional", type=int, default=20)
    ap.add_argument(
        "--hybrid-stage2-max-ms",
        type=float,
        default=600.0,
        help="Set <=0 to disable the stage2 latency cap.",
    )
    ap.add_argument(
        "--hybrid-fusion-mode",
        choices=["append_fill", "rrf_fusion"],
        default="append_fill",
    )
    ap.add_argument("--hybrid-k-rrf", type=float, default=60.0)
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    dataset_path = repo_root / args.dataset if not Path(args.dataset).is_absolute() else Path(args.dataset)
    out_root = repo_root / args.output_root

    run_group = _resolve_run_group(explicit_run_group=args.run_group, run_label=args.run_label)
    run_dir = out_root / run_group
    run_dir.mkdir(parents=True, exist_ok=True)

    baseline = _run_lancedb(
        dataset_path=dataset_path,
        out_dir=run_dir,
        run_group=run_group,
        run_suffix="baseline",
        top_k=args.top_k,
        question_limit=args.question_limit,
        sample_size=args.sample_size,
        sample_seed=args.sample_seed,
        session_key=args.session_key,
        gateway_url=args.gateway_url,
        gateway_token=args.gateway_token,
        recall_limit_factor=args.lancedb_recall_limit_factor,
        extra_manifest_fields={"arm": "baseline", "ingest_policy": "all-sessions"},
    )

    raw = _load_json(dataset_path)
    dataset_sha = file_sha256(dataset_path)

    observational: dict[str, Any] | None = None
    if args.include_observational:
        obs_dataset, obs_stats = _compress_dataset_observational(raw)
        obs_path = run_dir / "derived-dataset-observational.json"
        obs_path.write_text(json.dumps(obs_dataset, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        obs_report = _run_lancedb(
            dataset_path=obs_path,
            out_dir=run_dir,
            run_group=run_group,
            run_suffix="observational",
            top_k=args.top_k,
            question_limit=args.question_limit,
            sample_size=args.sample_size,
            sample_seed=args.sample_seed,
            session_key=args.session_key,
            gateway_url=args.gateway_url,
            gateway_token=args.gateway_token,
            recall_limit_factor=args.lancedb_recall_limit_factor,
            extra_manifest_fields={
                "arm": "observational",
                "proxy_mode": "derived_dataset_observational_compression",
                "source_dataset_sha256": dataset_sha,
                "observational_stats": obs_stats,
            },
        )

        observational = {
            "mode": "observational",
            "dataset_path": str(obs_path),
            "dataset_sha256": file_sha256(obs_path),
            "filter_stats": obs_stats,
            "report": obs_report,
        }

    candidates: list[dict[str, Any]] = []

    for policy in args.policies:
        filtered, filter_stats = _filter_dataset(raw, policy=policy)
        filtered_path = run_dir / f"derived-dataset-{policy}.json"
        filtered_path.write_text(json.dumps(filtered, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        report = _run_lancedb(
            dataset_path=filtered_path,
            out_dir=run_dir,
            run_group=run_group,
            run_suffix=f"experimental-{policy}",
            top_k=args.top_k,
            question_limit=args.question_limit,
            sample_size=args.sample_size,
            sample_seed=args.sample_seed,
            session_key=args.session_key,
            gateway_url=args.gateway_url,
            gateway_token=args.gateway_token,
            recall_limit_factor=args.lancedb_recall_limit_factor,
            extra_manifest_fields={
                "arm": "experimental",
                "ingest_policy": policy,
                "proxy_mode": "derived_dataset_filter",
                "source_dataset_sha256": dataset_sha,
            },
        )

        candidates.append(
            {
                "policy": policy,
                "filter_stats": filter_stats,
                "dataset_path": str(filtered_path),
                "dataset_sha256": file_sha256(filtered_path),
                "report": report,
            }
        )

    hybrid: dict[str, Any] | None = None
    if args.include_hybrid:
        by_policy = {cand["policy"]: cand for cand in candidates}
        must_candidate = by_policy.get(args.hybrid_must_policy)
        fallback_candidate = by_policy.get(args.hybrid_fallback_policy)
        if must_candidate is None or fallback_candidate is None:
            raise ValueError(
                "--include-hybrid requires both policies in --policies; "
                f"missing must={args.hybrid_must_policy!r} or fallback={args.hybrid_fallback_policy!r}."
            )

        must_report_payload = _load_json(Path(must_candidate["report"]["report_path"]))
        fallback_report_payload = _load_json(Path(fallback_candidate["report"]["report_path"]))
        stage2_max_ms = float(args.hybrid_stage2_max_ms) if args.hybrid_stage2_max_ms > 0 else None

        hybrid_run_id = f"{run_group}-hybrid"
        hybrid_report, hybrid_extra = build_two_stage_hybrid_report(
            must_report=must_report_payload,
            fallback_report=fallback_report_payload,
            run_id=hybrid_run_id,
            manifest={
                "experiment": {
                    "arm": "hybrid",
                    "must_policy": args.hybrid_must_policy,
                    "fallback_policy": args.hybrid_fallback_policy,
                    "must_report_path": must_candidate["report"]["report_path"],
                    "fallback_report_path": fallback_candidate["report"]["report_path"],
                    "mode": "must_count_gate",
                    "fusion_mode": args.hybrid_fusion_mode,
                    "k_rrf": (float(args.hybrid_k_rrf) if args.hybrid_fusion_mode == "rrf_fusion" else None),
                    "min_must_count": int(args.hybrid_min_must_count),
                    "stage2_max_additional": int(args.hybrid_stage2_max_additional),
                    "stage2_max_ms": stage2_max_ms,
                }
            },
            min_must_count=int(args.hybrid_min_must_count),
            stage2_max_additional=int(args.hybrid_stage2_max_additional),
            stage2_max_ms=stage2_max_ms,
            fusion_mode=args.hybrid_fusion_mode,
            k_rrf=float(args.hybrid_k_rrf),
        )

        hybrid_dir = run_dir / "hybrid"
        hybrid_dir.mkdir(parents=True, exist_ok=True)
        hybrid_json = hybrid_dir / "retrieval-report.json"
        hybrid_json.write_text(json.dumps(hybrid_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        hybrid_md = hybrid_dir / "retrieval-report.md"
        _write_hybrid_markdown(
            path=hybrid_md,
            run_id=hybrid_run_id,
            report=hybrid_report,
            stage_counts=hybrid_extra.get("stage_counts", {}),
            must_policy=args.hybrid_must_policy,
            fallback_policy=args.hybrid_fallback_policy,
        )

        hybrid = {
            "mode": "must_count_gate",
            "fusion_mode": args.hybrid_fusion_mode,
            "must_policy": args.hybrid_must_policy,
            "fallback_policy": args.hybrid_fallback_policy,
            "report": {
                "label": "hybrid",
                "report_path": str(hybrid_json),
                "summary": hybrid_report["summary"],
                "latency": hybrid_report["latency"],
                "top_k": hybrid_report["top_k"],
                "manifest": hybrid_report.get("manifest"),
            },
            "stage_counts": hybrid_extra.get("stage_counts", {}),
            "md_path": str(hybrid_md),
        }

    baseline_metrics = _metric_pack(baseline)
    curve: list[dict[str, Any]] = []
    for cand in candidates:
        exp_metrics = _metric_pack(cand["report"])
        delta = {k: exp_metrics[k] - baseline_metrics[k] for k in baseline_metrics}
        curve.append(
            {
                "policy": cand["policy"],
                "compression_ratio_items": cand["filter_stats"]["compression_ratio_items"],
                "compression_ratio_chars": cand["filter_stats"]["compression_ratio_chars"],
                "baseline": baseline_metrics,
                "experimental": exp_metrics,
                "delta_experimental_minus_baseline": delta,
            }
        )

    hybrid_tradeoff: dict[str, Any] | None = None
    if hybrid is not None:
        hybrid_metrics = _metric_pack(hybrid["report"])
        delta = {k: hybrid_metrics[k] - baseline_metrics[k] for k in baseline_metrics}
        hybrid_tradeoff = {
            "policy": "hybrid",
            "baseline": baseline_metrics,
            "hybrid": hybrid_metrics,
            "delta_hybrid_minus_baseline": delta,
            "stage_counts": hybrid["stage_counts"],
            "mode": hybrid["mode"],
            "fusion_mode": hybrid["fusion_mode"],
        }

    # Win criteria (GTM/falsification ready):
    # Pass if p95 improves >=20% while recall drop <=3pp and nDCG non-negative.
    wins: list[dict[str, Any]] = []
    for row in curve:
        wins.append(_win_eval(baseline=row["baseline"], candidate=row["experimental"], policy=row["policy"]))

    if hybrid_tradeoff is not None:
        wins.append(_win_eval(baseline=baseline_metrics, candidate=hybrid_tradeoff["hybrid"], policy="hybrid"))

    arms: dict[str, Any] = {
        "baseline": baseline,
        "experimental": candidates,
    }
    if observational is not None:
        arms["observational"] = observational
    if hybrid is not None:
        arms["hybrid"] = hybrid

    compare = {
        "schema": "openclaw-memory-bench/phase-ab-compare-report/v0.3",
        "run_group": run_group,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest": {
            "toolkit_git_commit": resolve_git_commit(repo_root),
            "dataset_path": str(dataset_path.resolve()),
            "dataset_sha256": dataset_sha,
            "seed": args.sample_seed,
            "sample_size": args.sample_size,
            "top_k": args.top_k,
            "provider": "memory-lancedb",
            "provider_config_sanitized": {
                "session_key": args.session_key,
                "gateway_url": args.gateway_url,
                "lancedb_recall_limit_factor": args.lancedb_recall_limit_factor,
            },
            "limitation": "Experimental + hybrid arms are proxy-mode derived dataset fusion (no live openclaw-mem adapter chaining yet).",
        },
        "arms": arms,
        "tradeoff_curve": curve,
        "hybrid_tradeoff": hybrid_tradeoff,
        "win_interpretation": {
            "rule": "win if p95 improves >=20% and recall drop <=0.03 and nDCG delta >=0",
            "results": wins,
        },
        "cost_metadata": {
            "available": False,
            "note": "Gateway tool calls do not currently expose tokenized cost metadata in retrieval report v0.2.",
        },
    }

    compare_json = run_dir / f"compare-{run_group}.json"
    compare_json.write_text(json.dumps(compare, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        f"# Phase A/B compare ({run_group})",
        "",
        "Baseline: memory-lancedb canonical ingest (all sessions).",
        "Experimental: memory-lancedb ingest on openclaw-mem-style importance-gated derived dataset (proxy mode).",
        "",
        f"- Dataset: `{dataset_path}`",
        f"- Dataset sha256: `{dataset_sha}`",
        f"- top_k: {args.top_k}",
        f"- sample_seed: {args.sample_seed}",
        "",
        "## Baseline metrics",
        f"- hit@k: {baseline_metrics['hit_at_k']:.4f}",
        f"- precision@k: {baseline_metrics['precision_at_k']:.4f}",
        f"- recall@k: {baseline_metrics['recall_at_k']:.4f}",
        f"- mrr: {baseline_metrics['mrr']:.4f}",
        f"- ndcg@k: {baseline_metrics['ndcg_at_k']:.4f}",
        f"- latency p50/p95(ms): {baseline_metrics['search_ms_p50']:.2f}/{baseline_metrics['search_ms_p95']:.2f}",
        "",
    ]

    if observational is not None:
        obs_metrics = _metric_pack(observational["report"])
        obs_delta = {k: obs_metrics[k] - baseline_metrics[k] for k in baseline_metrics}
        lines.extend(
            [
                "## Observational compression (proxy) metrics",
                f"- compression chars ratio: {observational['filter_stats']['compression_ratio_chars']:.3f}",
                f"- Δ recall@k: {obs_delta['recall_at_k']:+.4f}",
                f"- Δ ndcg@k: {obs_delta['ndcg_at_k']:+.4f}",
                f"- Δ p95(ms): {obs_delta['search_ms_p95']:+.2f}",
                "",
            ]
        )

    win_by_policy = {str(row.get("policy") or ""): row for row in wins}

    lines.append("## Experimental tradeoff rows")

    for row in curve:
        d = row["delta_experimental_minus_baseline"]
        win = win_by_policy.get(str(row["policy"]), {})
        lines.extend(
            [
                f"### policy={row['policy']}",
                f"- compression items/chars: {row['compression_ratio_items']:.3f}/{row['compression_ratio_chars']:.3f}",
                f"- Δ hit@k: {d['hit_at_k']:+.4f}",
                f"- Δ precision@k: {d['precision_at_k']:+.4f}",
                f"- Δ recall@k: {d['recall_at_k']:+.4f}",
                f"- Δ mrr: {d['mrr']:+.4f}",
                f"- Δ ndcg@k: {d['ndcg_at_k']:+.4f}",
                f"- Δ p50/p95(ms): {d['search_ms_p50']:+.2f}/{d['search_ms_p95']:+.2f}",
                f"- win rule pass: {win.get('win')} (p95_gain={win.get('p95_gain_ratio', 0.0):.3f}, recall_drop={win.get('recall_drop_abs', 0.0):.3f})",
                "",
            ]
        )

    if hybrid_tradeoff is not None:
        d = hybrid_tradeoff["delta_hybrid_minus_baseline"]
        win = win_by_policy.get("hybrid", {})
        lines.extend(
            [
                "## Hybrid arm tradeoff",
                f"- mode/fusion: {hybrid_tradeoff['mode']}/{hybrid_tradeoff['fusion_mode']}",
                f"- stage2 used/skipped/not-triggered: {hybrid_tradeoff['stage_counts'].get('stage2_used', 0)}/{hybrid_tradeoff['stage_counts'].get('stage2_skipped_budget', 0)}/{hybrid_tradeoff['stage_counts'].get('stage2_not_triggered', 0)}",
                f"- Δ recall@k: {d['recall_at_k']:+.4f}",
                f"- Δ ndcg@k: {d['ndcg_at_k']:+.4f}",
                f"- Δ p95(ms): {d['search_ms_p95']:+.2f}",
                f"- win rule pass: {win.get('win')} (p95_gain={win.get('p95_gain_ratio', 0.0):.3f}, recall_drop={win.get('recall_drop_abs', 0.0):.3f})",
                "",
            ]
        )

    compare_md = run_dir / f"compare-{run_group}.md"
    compare_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    latest_pointer = out_root / args.latest_pointer_name
    try:
        compare_md_ptr = compare_md.relative_to(repo_root)
        compare_json_ptr = compare_json.relative_to(repo_root)
    except ValueError:
        compare_md_ptr = compare_md
        compare_json_ptr = compare_json

    latest_pointer.write_text(
        "\n".join(
            [
                "# Latest Phase A/B compare pointer",
                "",
                f"- run_group: `{run_group}`",
                f"- compare_md: `{compare_md_ptr}`",
                f"- compare_json: `{compare_json_ptr}`",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "ok": True,
                "run_group": run_group,
                "compare_json": str(compare_json),
                "compare_md": str(compare_md),
                "latest_pointer": str(latest_pointer),
                "baseline_report": baseline["report_path"],
                "observational_report": (observational["report"]["report_path"] if observational is not None else None),
                "experimental_reports": [x["report"]["report_path"] for x in candidates],
                "hybrid_report": (hybrid["report"]["report_path"] if hybrid is not None else None),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
