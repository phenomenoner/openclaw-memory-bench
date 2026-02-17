from __future__ import annotations

import json
from pathlib import Path

from openclaw_memory_bench.hybrid import _rrf_merge, build_two_stage_hybrid_report

_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "hybrid" / "rrf_tie_break_case.json"


def _fixture() -> dict:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def test_rrf_merge_tie_break_is_deterministic_from_fixture() -> None:
    fixture = _fixture()
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
    fixture = _fixture()
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
    fixture = _fixture()
    report, _ = build_two_stage_hybrid_report(
        must_report=fixture["must_report"],
        fallback_report=fixture["fallback_report"],
        run_id="fixture-append-fill-report",
        min_must_count=4,
        stage2_max_additional=3,
        fusion_mode="append_fill",
    )

    assert report["results"][0]["retrieved_session_ids"] == fixture["expected"]["append_fill_ranked_top4"]
