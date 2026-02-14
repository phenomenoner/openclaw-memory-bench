from __future__ import annotations

import argparse
import json
import math
import random
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "phase-ab-compare"


def _pct(xs: list[float], p: float) -> float:
    if not xs:
        return float("nan")
    xs2 = sorted(xs)
    if p <= 0:
        return xs2[0]
    if p >= 100:
        return xs2[-1]
    rank = (len(xs2) - 1) * (p / 100.0)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return xs2[lo]
    frac = rank - lo
    return xs2[lo] + frac * (xs2[hi] - xs2[lo])


def bootstrap_mean_ci(
    values: list[float], *, n: int = 20000, alpha: float = 0.05, seed: int = 0
) -> dict[str, float]:
    """Bootstrap CI over *seeds* (values list)."""
    if not values:
        return {"mean": float("nan"), "ci_lo": float("nan"), "ci_hi": float("nan"), "n": 0}

    rng = random.Random(seed)
    k = len(values)
    samples: list[float] = []
    for _ in range(n):
        s = [values[rng.randrange(k)] for _ in range(k)]
        samples.append(mean(s))

    return {
        "mean": mean(values),
        "ci_lo": _pct(samples, 100.0 * (alpha / 2.0)),
        "ci_hi": _pct(samples, 100.0 * (1.0 - alpha / 2.0)),
        "n": float(k),
    }


@dataclass
class SeedRow:
    run_group: str
    dataset_path: str
    dataset_sha256: str
    top_k: int
    baseline: dict[str, float]
    baseline_latency: dict[str, float]
    policies: dict[str, dict[str, Any]]


def load_compare(run_group: str) -> tuple[dict[str, Any], Path]:
    folder = ARTIFACTS_ROOT / run_group
    path = folder / f"compare-{run_group}.json"
    if not path.exists():
        raise FileNotFoundError(str(path))
    return json.loads(path.read_text(encoding="utf-8")), path


def _get_tradeoff_row(compare: dict[str, Any], policy: str) -> dict[str, Any]:
    for row in compare.get("tradeoff_curve", []):
        if row.get("policy") == policy:
            return row
    raise KeyError(f"tradeoff_curve policy not found: {policy}")


def _extract_baseline(compare: dict[str, Any]) -> tuple[dict[str, float], dict[str, float]]:
    arms = compare["arms"]
    b = arms["baseline"]
    s = b["summary"]
    lat = b["latency"]

    metrics = {
        "hit_at_k": float(s["hit_at_k"]),
        "precision_at_k": float(s["precision_at_k"]),
        "recall_at_k": float(s["recall_at_k"]),
        "mrr": float(s["mrr"]),
        "ndcg_at_k": float(s["ndcg_at_k"]),
    }
    latency = {
        "search_ms_p50": float(lat["search_ms_p50"]),
        "search_ms_p95": float(lat["search_ms_p95"]),
    }
    return metrics, latency


def _extract_policy_block(compare: dict[str, Any], policy: str) -> dict[str, Any]:
    row = _get_tradeoff_row(compare, policy)

    delta = row["delta_experimental_minus_baseline"]
    baseline = row["baseline"]
    experimental = row["experimental"]

    out: dict[str, Any] = {
        "compression_ratio_items": float(row["compression_ratio_items"]),
        "compression_ratio_chars": float(row["compression_ratio_chars"]),
        "baseline": {
            "hit_at_k": float(baseline["hit_at_k"]),
            "precision_at_k": float(baseline["precision_at_k"]),
            "recall_at_k": float(baseline["recall_at_k"]),
            "mrr": float(baseline["mrr"]),
            "ndcg_at_k": float(baseline["ndcg_at_k"]),
            "search_ms_p50": float(baseline["search_ms_p50"]),
            "search_ms_p95": float(baseline["search_ms_p95"]),
        },
        "experimental": {
            "hit_at_k": float(experimental["hit_at_k"]),
            "precision_at_k": float(experimental["precision_at_k"]),
            "recall_at_k": float(experimental["recall_at_k"]),
            "mrr": float(experimental["mrr"]),
            "ndcg_at_k": float(experimental["ndcg_at_k"]),
            "search_ms_p50": float(experimental["search_ms_p50"]),
            "search_ms_p95": float(experimental["search_ms_p95"]),
        },
        "delta": {
            "hit_at_k": float(delta["hit_at_k"]),
            "precision_at_k": float(delta["precision_at_k"]),
            "recall_at_k": float(delta["recall_at_k"]),
            "mrr": float(delta["mrr"]),
            "ndcg_at_k": float(delta["ndcg_at_k"]),
            "search_ms_p50": float(delta["search_ms_p50"]),
            "search_ms_p95": float(delta["search_ms_p95"]),
        },
    }

    # Optional by_question_type breakdown (if present in the per-arm reports).
    by_qt: dict[str, Any] = {}
    base_qt = compare["arms"]["baseline"]["summary"].get("by_question_type") or {}

    # Find policy arm in arms.experimental list
    exp_list = compare["arms"].get("experimental") or []
    exp_arm = None
    for arm in exp_list:
        if arm.get("policy") == policy:
            exp_arm = arm
            break
    if exp_arm is not None:
        exp_qt = (exp_arm.get("report") or {}).get("summary", {}).get("by_question_type") or {}
    else:
        exp_qt = {}

    for qt, bsum in base_qt.items():
        esum = exp_qt.get(qt)
        if not esum:
            continue
        by_qt[qt] = {
            "baseline": {
                "hit_at_k": float(bsum["hit_at_k"]),
                "mrr": float(bsum["mrr"]),
                "ndcg_at_k": float(bsum["ndcg_at_k"]),
                "search_ms_p50": float(bsum.get("search_ms_p50", 0.0)),
                "search_ms_p95": float(bsum.get("search_ms_p95", 0.0)),
            },
            "experimental": {
                "hit_at_k": float(esum["hit_at_k"]),
                "mrr": float(esum["mrr"]),
                "ndcg_at_k": float(esum["ndcg_at_k"]),
                "search_ms_p50": float(esum.get("search_ms_p50", 0.0)),
                "search_ms_p95": float(esum.get("search_ms_p95", 0.0)),
            },
            "delta": {
                "hit_at_k": float(esum["hit_at_k"]) - float(bsum["hit_at_k"]),
                "mrr": float(esum["mrr"]) - float(bsum["mrr"]),
                "ndcg_at_k": float(esum["ndcg_at_k"]) - float(bsum["ndcg_at_k"]),
                "search_ms_p50": float(esum.get("search_ms_p50", 0.0)) - float(bsum.get("search_ms_p50", 0.0)),
                "search_ms_p95": float(esum.get("search_ms_p95", 0.0)) - float(bsum.get("search_ms_p95", 0.0)),
            },
        }

    if by_qt:
        out["by_question_type"] = by_qt

    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-groups", nargs="+", required=True)
    ap.add_argument("--out-group", required=True)
    ap.add_argument("--bootstrap-n", type=int, default=20000)
    ap.add_argument("--bootstrap-seed", type=int, default=0)
    args = ap.parse_args()

    rows: list[SeedRow] = []

    for rg in args.run_groups:
        compare, _path = load_compare(rg)
        manifest = compare["manifest"]

        baseline_metrics, baseline_latency = _extract_baseline(compare)

        policies: dict[str, dict[str, Any]] = {}
        for policy in ("must", "must+nice"):
            policies[policy] = _extract_policy_block(compare, policy)

        rows.append(
            SeedRow(
                run_group=rg,
                dataset_path=str(manifest["dataset_path"]),
                dataset_sha256=str(manifest["dataset_sha256"]),
                top_k=int(manifest["top_k"]),
                baseline=baseline_metrics,
                baseline_latency=baseline_latency,
                policies=policies,
            )
        )

    # Consistency checks
    ds_sha = {r.dataset_sha256 for r in rows}
    topk = {r.top_k for r in rows}
    if len(ds_sha) != 1:
        raise SystemExit(f"dataset sha mismatch across runs: {sorted(ds_sha)}")
    if len(topk) != 1:
        raise SystemExit(f"top_k mismatch across runs: {sorted(topk)}")

    # Aggregate
    out: dict[str, Any] = {
        "schema": "openclaw-memory-bench/phase-ab-multiseed-summary/v0.1",
        "out_group": args.out_group,
        "run_groups": [r.run_group for r in rows],
        "dataset_sha256": next(iter(ds_sha)),
        "dataset_path": rows[0].dataset_path,
        "top_k": rows[0].top_k,
        "n_seeds": len(rows),
        "baseline": {},
        "policies": {},
        "notes": [
            "CI is bootstrapped over seeds (run groups), not over individual questions.",
            "Experimental arm remains proxy-mode derived-dataset filtering (not live adapter chaining).",
        ],
    }

    # Baseline mean/CI (over seeds)
    for key in ("hit_at_k", "precision_at_k", "recall_at_k", "mrr", "ndcg_at_k"):
        vals = [r.baseline[key] for r in rows]
        out["baseline"][key] = bootstrap_mean_ci(vals, n=args.bootstrap_n, seed=args.bootstrap_seed)
    for key in ("search_ms_p50", "search_ms_p95"):
        vals = [r.baseline_latency[key] for r in rows]
        out["baseline"][key] = bootstrap_mean_ci(vals, n=args.bootstrap_n, seed=args.bootstrap_seed)

    # Policy delta mean/CI (over seeds)
    for policy in ("must", "must+nice"):
        block: dict[str, Any] = {
            "compression_ratio_items": bootstrap_mean_ci(
                [r.policies[policy]["compression_ratio_items"] for r in rows],
                n=args.bootstrap_n,
                seed=args.bootstrap_seed,
            ),
            "compression_ratio_chars": bootstrap_mean_ci(
                [r.policies[policy]["compression_ratio_chars"] for r in rows],
                n=args.bootstrap_n,
                seed=args.bootstrap_seed,
            ),
            "delta": {},
        }
        for key in (
            "hit_at_k",
            "precision_at_k",
            "recall_at_k",
            "mrr",
            "ndcg_at_k",
            "search_ms_p50",
            "search_ms_p95",
        ):
            vals = [r.policies[policy]["delta"][key] for r in rows]
            block["delta"][key] = bootstrap_mean_ci(vals, n=args.bootstrap_n, seed=args.bootstrap_seed)

        out["policies"][policy] = block

    # Write
    out_dir = ARTIFACTS_ROOT / args.out_group
    out_dir.mkdir(parents=True, exist_ok=True)

    out_json = out_dir / "multiseed-summary.json"
    out_md = out_dir / "multiseed-summary.md"

    out_json.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def fmt_ci(d: dict[str, float]) -> str:
        return f"{d['mean']:.4f} [{d['ci_lo']:.4f}, {d['ci_hi']:.4f}] (n={int(d['n'])})"

    lines: list[str] = []
    lines.append(f"# Phase A/B multiseed summary ({args.out_group})\n")
    lines.append(f"- Dataset: `{rows[0].dataset_path}`")
    lines.append(f"- Dataset sha256: `{rows[0].dataset_sha256}`")
    lines.append(f"- top_k: {rows[0].top_k}")
    lines.append(f"- Seeds (run groups): {len(rows)}")
    for rg in out["run_groups"]:
        lines.append(f"  - `{rg}`")

    lines.append("\n## Baseline (mean [95% CI] over seeds)")
    for key in ("hit_at_k", "precision_at_k", "recall_at_k", "mrr", "ndcg_at_k"):
        lines.append(f"- {key}: {fmt_ci(out['baseline'][key])}")
    lines.append(f"- latency p50(ms): {fmt_ci(out['baseline']['search_ms_p50'])}")
    lines.append(f"- latency p95(ms): {fmt_ci(out['baseline']['search_ms_p95'])}")

    for policy in ("must", "must+nice"):
        lines.append(f"\n## Experimental policy = {policy} (Δ experimental - baseline; mean [95% CI] over seeds)")
        lines.append(f"- compression items: {fmt_ci(out['policies'][policy]['compression_ratio_items'])}")
        lines.append(f"- compression chars: {fmt_ci(out['policies'][policy]['compression_ratio_chars'])}")
        for key in ("hit_at_k", "precision_at_k", "recall_at_k", "mrr", "ndcg_at_k"):
            lines.append(f"- Δ {key}: {fmt_ci(out['policies'][policy]['delta'][key])}")
        lines.append(f"- Δ latency p50(ms): {fmt_ci(out['policies'][policy]['delta']['search_ms_p50'])}")
        lines.append(f"- Δ latency p95(ms): {fmt_ci(out['policies'][policy]['delta']['search_ms_p95'])}")

    lines.append("\n## Notes")
    for n in out["notes"]:
        lines.append(f"- {n}")

    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(str(out_json))
    print(str(out_md))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
