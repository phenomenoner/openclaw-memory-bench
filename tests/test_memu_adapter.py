from openclaw_memory_bench.adapters.memu_engine import MemuEngineAdapter


def test_extract_results_from_content_text_json() -> None:
    payload = {
        "content": [
            {
                "type": "text",
                "text": '{"results":[{"path":"/tmp/sessions/abc123.jsonl","snippet":"hello","score":0.9}]}'
            }
        ]
    }
    rows = MemuEngineAdapter._extract_results(payload)
    assert len(rows) == 1
    assert rows[0]["score"] == 0.9


def test_extract_session_id() -> None:
    sid = MemuEngineAdapter._extract_session_id(
        "/tmp/sessions/06b45be9-2b5f-48a4-87b2-83dc481f211a.jsonl",
        None,
    )
    assert sid is not None
