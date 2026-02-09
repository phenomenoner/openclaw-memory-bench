from openclaw_memory_bench.adapters.memory_core import MemoryCoreAdapter


def test_select_messages_head_tail() -> None:
    msgs = list(range(10))
    out = MemoryCoreAdapter._select_messages(msgs, 4)
    assert out == [0, 1, 8, 9]


def test_truncate_text() -> None:
    text = "abcdefghij"
    out = MemoryCoreAdapter._truncate_text(text, 5)
    assert out.startswith("abcde")
    assert out.endswith(" …")


def test_safe_container_tag() -> None:
    assert MemoryCoreAdapter._safe_container_tag("run:1/q?x") == "run-1-q-x"
