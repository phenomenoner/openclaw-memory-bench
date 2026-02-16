from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_runner_module():
    repo_root = Path(__file__).resolve().parents[1]
    script_path = repo_root / "scripts" / "run_lancedb_vs_openclaw_mem_assisted.py"
    spec = importlib.util.spec_from_file_location("phase_ab_compare_runner", script_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_resolve_run_group_slug() -> None:
    runner = _load_runner_module()

    assert runner._resolve_run_group(explicit_run_group="Deterministic Run 01", run_label="ignored") == "deterministic-run-01"


def test_main_writes_stable_latest_pointer(monkeypatch, tmp_path, capsys) -> None:
    runner = _load_runner_module()

    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "name": "mini",
                "questions": [
                    {
                        "question_id": "q1",
                        "question": "What should we remember?",
                        "question_type": "profile",
                        "sessions": [
                            {
                                "session_id": "s1",
                                "messages": [
                                    {"role": "user", "content": "must remember this preference"},
                                ],
                            }
                        ],
                        "relevant_session_ids": ["s1"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    out_root = tmp_path / "out"

    def _fake_run_lancedb(**kwargs):
        run_suffix = kwargs["run_suffix"]
        p95 = 120.0 if run_suffix == "baseline" else 90.0
        recall = 1.0 if run_suffix == "baseline" else 0.98

        report_path = Path(kwargs["out_dir"]) / run_suffix / "retrieval-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("{}\n", encoding="utf-8")

        return {
            "label": run_suffix,
            "report_path": str(report_path),
            "summary": {
                "hit_at_k": 1.0,
                "precision_at_k": 1.0,
                "recall_at_k": recall,
                "mrr": 1.0,
                "ndcg_at_k": 1.0,
            },
            "latency": {
                "search_ms_p50": 60.0,
                "search_ms_p95": p95,
            },
            "top_k": kwargs["top_k"],
            "manifest": {"stub": True},
        }

    monkeypatch.setattr(runner, "_run_lancedb", _fake_run_lancedb)

    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--dataset",
            str(dataset_path),
            "--output-root",
            str(out_root),
            "--run-group",
            "Deterministic Run 01",
            "--latest-pointer-name",
            "LATEST.md",
            "--policies",
            "must",
        ],
    )

    assert runner.main() == 0

    run_group = "deterministic-run-01"
    compare_md = out_root / run_group / f"compare-{run_group}.md"
    latest_md = out_root / "LATEST.md"

    assert compare_md.exists()
    assert latest_md.exists()

    latest_text = latest_md.read_text(encoding="utf-8")
    assert "run_group: `deterministic-run-01`" in latest_text
    assert f"compare-{run_group}.md" in latest_text

    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["run_group"] == run_group
    assert payload["latest_pointer"].endswith("/LATEST.md")


def test_main_can_build_hybrid_arm(monkeypatch, tmp_path, capsys) -> None:
    runner = _load_runner_module()

    dataset_path = tmp_path / "dataset.json"
    dataset_path.write_text(
        json.dumps(
            {
                "name": "mini-hybrid",
                "questions": [
                    {
                        "question_id": "q1",
                        "question": "What should we remember?",
                        "question_type": "profile",
                        "ground_truth": "s1+s2",
                        "sessions": [
                            {
                                "session_id": "s1",
                                "messages": [{"role": "user", "content": "must remember this."}],
                                "metadata": {"importance": "must"},
                            },
                            {
                                "session_id": "s2",
                                "messages": [{"role": "user", "content": "preference note."}],
                                "metadata": {"importance": "nice"},
                            },
                        ],
                        "relevant_session_ids": ["s1", "s2"],
                    }
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    out_root = tmp_path / "out"

    def _stub_report(*, run_id: str, top_k: int, retrieved: list[str], scores: list[float], latency_ms: float):
        hit = 1.0 if any(x in {"s1", "s2"} for x in retrieved[:top_k]) else 0.0
        recall = sum(1 for x in retrieved[:top_k] if x in {"s1", "s2"}) / 2.0
        return {
            "schema": "openclaw-memory-bench/retrieval-report/v0.2",
            "run_id": run_id,
            "provider": "memory-lancedb",
            "dataset": "mini-hybrid",
            "top_k": top_k,
            "created_at_utc": "2026-02-17T00:00:00Z",
            "summary": {
                "questions_total": 1,
                "questions_succeeded": 1,
                "questions_failed": 0,
                "hit_at_k": hit,
                "precision_at_k": min(1.0, len(retrieved[:top_k]) / float(top_k)),
                "recall_at_k": recall,
                "mrr": 1.0 if retrieved and retrieved[0] in {"s1", "s2"} else 0.0,
                "ndcg_at_k": recall,
                "failure_breakdown": {"by_code": {}, "by_category": {}, "by_phase": {}},
            },
            "latency": {
                "search_ms_p50": latency_ms,
                "search_ms_p95": latency_ms,
                "search_ms_mean": latency_ms,
            },
            "results": [
                {
                    "question_id": "q1",
                    "question": "What should we remember?",
                    "question_type": "profile",
                    "ground_truth": "s1+s2",
                    "relevant_session_ids": ["s1", "s2"],
                    "retrieved_session_ids": retrieved,
                    "retrieved_scores": scores,
                    "retrieved_observation_ids": [],
                    "retrieved_sources": [],
                    "latency_ms": latency_ms,
                    "metrics": {
                        "hit_at_k": hit,
                        "precision_at_k": min(1.0, len(retrieved[:top_k]) / float(top_k)),
                        "recall_at_k": recall,
                        "mrr": 1.0 if retrieved and retrieved[0] in {"s1", "s2"} else 0.0,
                        "ndcg_at_k": recall,
                    },
                }
            ],
            "failures": [],
        }

    def _fake_run_lancedb(**kwargs):
        run_suffix = kwargs["run_suffix"]
        report_path = Path(kwargs["out_dir"]) / run_suffix / "retrieval-report.json"
        report_path.parent.mkdir(parents=True, exist_ok=True)

        if run_suffix == "baseline":
            retrieved, scores, latency_ms = ["s1", "s2"], [1.0, 0.8], 100.0
        elif run_suffix == "experimental-must":
            retrieved, scores, latency_ms = ["s1"], [1.0], 50.0
        else:
            retrieved, scores, latency_ms = ["s1", "s2"], [1.0, 0.6], 60.0

        payload = _stub_report(
            run_id=f"deterministic-{run_suffix}",
            top_k=int(kwargs["top_k"]),
            retrieved=retrieved,
            scores=scores,
            latency_ms=latency_ms,
        )
        report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

        return {
            "label": run_suffix,
            "report_path": str(report_path),
            "summary": payload["summary"],
            "latency": {
                "search_ms_p50": payload["latency"]["search_ms_p50"],
                "search_ms_p95": payload["latency"]["search_ms_p95"],
            },
            "top_k": kwargs["top_k"],
            "manifest": {"stub": True},
        }

    monkeypatch.setattr(runner, "_run_lancedb", _fake_run_lancedb)

    monkeypatch.setattr(
        "sys.argv",
        [
            "runner",
            "--dataset",
            str(dataset_path),
            "--output-root",
            str(out_root),
            "--run-group",
            "Deterministic Hybrid",
            "--policies",
            "must",
            "must+nice",
            "--include-hybrid",
            "--hybrid-min-must-count",
            "2",
        ],
    )

    assert runner.main() == 0

    run_group = "deterministic-hybrid"
    compare_json = out_root / run_group / f"compare-{run_group}.json"
    assert compare_json.exists()

    compare = json.loads(compare_json.read_text(encoding="utf-8"))
    assert compare["schema"].endswith("v0.3")
    assert compare["arms"]["hybrid"]["stage_counts"]["stage2_used"] == 1

    stdout = capsys.readouterr().out
    payload = json.loads(stdout)
    assert payload["hybrid_report"] is not None
