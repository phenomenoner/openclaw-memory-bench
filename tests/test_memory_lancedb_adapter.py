from openclaw_memory_bench.adapters.memory_lancedb import MemoryLanceDBAdapter


class _ProbeSpyAdapter(MemoryLanceDBAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.calls: list[tuple[str, dict]] = []

    def _invoke(self, tool: str, args: dict):  # type: ignore[override]
        self.calls.append((tool, dict(args)))
        if tool == "memory_recall":
            return {"details": {"memories": []}}
        return {"ok": True}


def test_extract_memories_from_result_details() -> None:
    payload = {
        "details": {
            "count": 1,
            "memories": [
                {
                    "id": "m1",
                    "text": "[container:run:q1] [session:s1] hello",
                    "score": 0.9,
                    "category": "benchmark-ingest",
                }
            ],
        }
    }
    rows = MemoryLanceDBAdapter._extract_memories(payload)
    assert len(rows) == 1
    assert rows[0]["id"] == "m1"


def test_session_id_from_text_marker() -> None:
    sid = MemoryLanceDBAdapter._session_id_from_text(
        "[container:abc] [session:s-zh-1] assistant: 在台北開會"
    )
    assert sid == "s-zh-1"


def test_container_marker() -> None:
    assert MemoryLanceDBAdapter._container_marker("run:q1") == "[container:run:q1]"


def test_clear_skips_unknown_probe_when_disabled() -> None:
    adapter = _ProbeSpyAdapter()
    adapter.initialize({"probe_on_unknown_clear": False})

    adapter.clear("run:q1")

    assert adapter.calls == []


def test_clear_probes_unknown_container_when_enabled() -> None:
    adapter = _ProbeSpyAdapter()
    adapter.initialize({"probe_on_unknown_clear": True})

    adapter.clear("run:q1")

    assert adapter.calls == [("memory_recall", {"query": "[container:run:q1]", "limit": 200})]
