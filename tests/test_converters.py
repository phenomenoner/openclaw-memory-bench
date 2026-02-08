from __future__ import annotations

from openclaw_memory_bench import converters


def test_convert_longmemeval_skips_empty_messages(monkeypatch) -> None:
    sample = [
        {
            "question_id": "q1",
            "question": "Who likes sushi?",
            "answer": "Alex",
            "question_type": "fact",
            "haystack_sessions": [
                [
                    {"role": "user", "content": "", "has_answer": False},
                    {"role": "assistant", "content": "Alex likes sushi", "has_answer": True},
                ],
                [
                    {"role": "user", "content": "   ", "has_answer": False},
                ],
            ],
        }
    ]

    monkeypatch.setattr(converters, "_download_json", lambda _url: sample)

    ds = converters.convert_longmemeval(limit=10)
    assert ds["name"] == "longmemeval"
    assert len(ds["questions"]) == 1

    q = ds["questions"][0]
    assert q["question_id"] == "q1"
    assert len(q["sessions"]) == 1
    assert q["sessions"][0]["messages"][0]["content"] == "Alex likes sushi"
    assert q["relevant_session_ids"] == [q["sessions"][0]["session_id"]]
