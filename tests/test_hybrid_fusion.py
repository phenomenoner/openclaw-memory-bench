from __future__ import annotations

import json
from pathlib import Path

from openclaw_memory_bench.hybrid import _rrf_merge, build_two_stage_hybrid_report

_RRF_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hybrid" / "rrf_tie_break_case.json"
_GATE_FIXTURE_PATH = (
    Path(__file__).parent / "fixtures" / "hybrid" / "stage2_budget_latency_case.json"
)


def _load_fixture(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rrf_fixture() -> dict:
    return _load_fixture(_RRF_FIXTURE_PATH)


def _gate_fixture() -> dict:
    return _load_fixture(_GATE_FIXTURE_PATH)


def test_rrf_merge_tie_break_is_deterministic_from_fixture() -> None:
    fixture = _rrf_fixture()
    must_row = fixture["must_report"]["results"][0]
    fallback_row = fixture["fallback_report"]["results"][0]

    ranked, scores, added = _rrf_merge(
        must_ids=must_row["retrieved_session_ids"],
        stage2_pairs=list(
            zip(
                fallback_row["retrieved_session_ids"],
                fallback_row["retrieved_scores"],
                strict=False,
            )
        ),
        top_k=4,
        k_rrf=60.0,
    )

    expected = fixture["expected"]
    assert ranked == expected["rrf_ranked_top4"]
    assert added == expected["stage2_added_count"]
    assert abs(scores[0] - scores[1]) < 1e-12
    assert abs(scores[2] - scores[3]) < 1e-12


def test_build_two_stage_hybrid_report_records_rrf_tie_break_contract() -> None:
    fixture = _rrf_fixture()
    report, extra = build_two_stage_hybrid_report(
        must_report=fixture["must_report"],
        fallback_report=fixture["fallback_report"],
        run_id="fixture-rrf-report",
        min_must_count=4,
        stage2_max_additional=3,
        fusion_mode="rrf_fusion",
        k_rrf=60.0,
    )

    expected = fixture["expected"]
    row = report["results"][0]

    assert row["retrieved_session_ids"] == expected["rrf_ranked_top4"]
    assert row["two_stage"]["tie_break_order"] == [
        "fused_score_desc",
        "stage_priority_asc",
        "source_rank_asc",
        "session_id_asc",
    ]
    assert row["two_stage"]["stage_priority"] == {"stage1": 0, "stage2": 1}
    assert row["two_stage"]["stage2_added_count"] == expected["stage2_added_count"]
    assert extra["stage_counts"]["stage2_used"] == 1


def test_append_fill_respects_stage1_order_before_stage2_fill() -> None:
    fixture = _rrf_fixture()
    report, _ = build_two_stage_hybrid_report(
        must_report=fixture["must_report"],
        fallback_report=fixture["fallback_report"],
        run_id="fixture-append-fill-report",
        min_must_count=4,
        stage2_max_additional=3,
        fusion_mode="append_fill",
    )

    assert (
        report["results"][0]["retrieved_session_ids"]
        == fixture["expected"]["append_fill_ranked_top4"]
    )


def test_stage2_budget_and_latency_gate_receipts_from_fixture() -> None:
    fixture = _gate_fixture()

    report, extra = build_two_stage_hybrid_report(
        must_report=fixture["must_report"],
        fallback_report=fixture["fallback_report"],
        run_id="fixture-stage2-gate-report",
        min_must_count=2,
        stage2_max_additional=1,
        stage2_max_ms=20.0,
        fusion_mode="append_fill",
    )

    expected = fixture["expected"]
    assert extra["stage_counts"] == expected["stage_counts"]

    rows_by_qid = {row["question_id"]: row for row in report["results"]}
    for qid, row_expected in expected["rows"].items():
        row = rows_by_qid[qid]
        two_stage = row["two_stage"]
        assert row["retrieved_session_ids"] == row_expected["retrieved_session_ids"]
        assert two_stage["stage2_used"] is row_expected["stage2_used"]
        assert two_stage["stage2_skipped_budget"] is row_expected["stage2_skipped_budget"]
        assert (
            two_stage["stage2_candidates_considered"]
            == row_expected["stage2_candidates_considered"]
        )
        assert two_stage["stage2_added_count"] == row_expected["stage2_added_count"]
        assert row["latency_ms"] == row_expected["latency_ms"]
