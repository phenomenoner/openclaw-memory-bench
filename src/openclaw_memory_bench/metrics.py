from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass
class RetrievalMetrics:
    hit_at_k: float
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg_at_k: float


def _dedupe_keep_order(items: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def score_retrieval(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> RetrievalMetrics:
    if k <= 0:
        raise ValueError("k must be > 0")

    ranked = _dedupe_keep_order(retrieved_ids)[:k]
    relevant = set(relevant_ids)

    if not relevant:
        return RetrievalMetrics(hit_at_k=0.0, precision_at_k=0.0, recall_at_k=0.0, mrr=0.0, ndcg_at_k=0.0)

    binary = [1 if x in relevant else 0 for x in ranked]
    rel_count = sum(binary)

    hit = 1.0 if rel_count > 0 else 0.0
    precision = rel_count / float(k)
    recall = rel_count / float(len(relevant))

    reciprocal_rank = 0.0
    for i, sid in enumerate(ranked):
        if sid in relevant:
            reciprocal_rank = 1.0 / float(i + 1)
            break

    dcg = 0.0
    for i, rel in enumerate(binary):
        if rel:
            dcg += 1.0 / math.log2(i + 2)

    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(ideal_hits))
    ndcg = dcg / idcg if idcg > 0 else 0.0

    return RetrievalMetrics(
        hit_at_k=hit,
        precision_at_k=precision,
        recall_at_k=recall,
        mrr=reciprocal_rank,
        ndcg_at_k=ndcg,
    )


def percentile_ms(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if p <= 0:
        return min(values)
    if p >= 100:
        return max(values)

    arr = sorted(values)
    rank = (len(arr) - 1) * (p / 100.0)
    low = int(math.floor(rank))
    high = int(math.ceil(rank))
    if low == high:
        return float(arr[low])
    frac = rank - low
    return float(arr[low] + frac * (arr[high] - arr[low]))
