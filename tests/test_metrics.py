from openclaw_memory_bench.metrics import percentile_ms, score_retrieval


def test_score_retrieval_basic() -> None:
    m = score_retrieval(
        retrieved_ids=["s2", "s1", "s1", "s3"],
        relevant_ids=["s1"],
        k=3,
    )
    assert m.hit_at_k == 1.0
    assert abs(m.precision_at_k - (1 / 3)) < 1e-9
    assert m.recall_at_k == 1.0
    assert m.mrr == 0.5
    assert m.ndcg_at_k > 0.0


def test_percentile() -> None:
    values = [10.0, 20.0, 30.0, 40.0]
    assert percentile_ms(values, 50) == 25.0
    assert percentile_ms(values, 95) > 30.0
