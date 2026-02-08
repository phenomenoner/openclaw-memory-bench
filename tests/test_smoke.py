from openclaw_memory_bench.adapters import available_adapters


def test_adapters_registered() -> None:
    names = available_adapters().keys()
    assert "openclaw-mem" in names
    assert "memu-engine" in names
