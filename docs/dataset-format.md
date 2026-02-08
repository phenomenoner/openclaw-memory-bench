# Retrieval dataset format (v0.1)

`run-retrieval` consumes a JSON dataset with this schema:

```json
{
  "name": "mini-smoke",
  "questions": [
    {
      "question_id": "q1",
      "question": "What is Alice's favorite color?",
      "ground_truth": "Blue",
      "question_type": "fact-recall",
      "relevant_session_ids": ["s1"],
      "sessions": [
        {
          "session_id": "s1",
          "messages": [
            { "role": "user", "content": "My favorite color is blue." },
            { "role": "assistant", "content": "Noted." }
          ],
          "metadata": {}
        }
      ]
    }
  ]
}
```

## Notes

- `relevant_session_ids` is required for robust retrieval scoring.
- Roles accepted: `user`, `assistant`, `system`, `tool`.
- If `relevant_session_ids` is omitted, the first session in `sessions` is assumed relevant.
