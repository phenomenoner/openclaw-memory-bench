from openclaw_memory_bench.adapters.memory_lancedb import MemoryLanceDBAdapter


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
