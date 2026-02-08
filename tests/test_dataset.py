from pathlib import Path

from openclaw_memory_bench.dataset import load_retrieval_dataset


def test_load_example_dataset() -> None:
    p = Path("examples/mini_retrieval.json")
    ds = load_retrieval_dataset(p)
    assert ds.name == "mini-retrieval-smoke"
    assert len(ds.questions) == 2
    assert ds.questions[0].question_id == "q1"
    assert ds.questions[0].relevant_session_ids == ["s1"]
