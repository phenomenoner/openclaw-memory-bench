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
