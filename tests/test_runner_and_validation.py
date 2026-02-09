from __future__ import annotations

import subprocess

import pytest

from openclaw_memory_bench.dataset import RetrievalDataset, RetrievalQuestion
from openclaw_memory_bench.protocol import SearchHit, Session, SessionMessage
from openclaw_memory_bench.runner import run_retrieval_benchmark
from openclaw_memory_bench.validation import SchemaValidationError, validate_dataset_payload


class _SuccessAdapter:
    def initialize(self, config: dict) -> None:
        self.config = config

    def clear(self, container_tag: str) -> None:
        return None

    def ingest(self, sessions, container_tag: str) -> dict:
        return {"container_tag": container_tag, "sessions": len(sessions)}

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        return None

    def search(self, query: str, container_tag: str, limit: int = 10):
        del query, container_tag, limit
        return [
            SearchHit(
                id="1",
                content="answer",
                score=1.0,
                metadata={"session_id": "s1", "path": "memory/session-s1.md"},
            )
        ]


class _TimeoutAdapter(_SuccessAdapter):
    def search(self, query: str, container_tag: str, limit: int = 10):
        del query, container_tag, limit
        raise subprocess.TimeoutExpired(cmd=["fake-cmd"], timeout=5)


def _mini_dataset() -> RetrievalDataset:
    q = RetrievalQuestion(
        question_id="q1",
        question="where?",
        ground_truth="taipei",
        question_type="fact",
        sessions=[
            Session(
                session_id="s1",
                messages=[SessionMessage(role="user", content="meeting in Taipei")],
                metadata={},
            )
        ],
        relevant_session_ids=["s1"],
    )
    return RetrievalDataset(name="mini", questions=[q])


def test_run_retrieval_success_includes_failure_breakdown(monkeypatch) -> None:
    import openclaw_memory_bench.runner as runner

    monkeypatch.setattr(runner, "available_adapters", lambda: {"fake": _SuccessAdapter})

    report = run_retrieval_benchmark(
        provider="fake",
        dataset=_mini_dataset(),
        top_k=5,
        run_id="run-ok",
        provider_config={},
        skip_ingest=False,
        fail_fast=False,
        limit=None,
        manifest={"schema": "test"},
    )

    assert report["summary"]["questions_failed"] == 0
    assert report["summary"]["failure_breakdown"] == {
        "by_code": {},
        "by_category": {},
        "by_phase": {},
    }


def test_run_retrieval_timeout_has_standardized_failure_fields(monkeypatch) -> None:
    import openclaw_memory_bench.runner as runner

    monkeypatch.setattr(runner, "available_adapters", lambda: {"fake": _TimeoutAdapter})

    report = run_retrieval_benchmark(
        provider="fake",
        dataset=_mini_dataset(),
        top_k=5,
        run_id="run-timeout",
        provider_config={},
        skip_ingest=False,
        fail_fast=False,
        limit=None,
        manifest={"schema": "test"},
    )

    assert report["summary"]["questions_failed"] == 1
    f = report["failures"][0]
    assert f["question_id"] == "q1"
    assert f["phase"] == "search"
    assert f["error_code"] == "TIMEOUT"
    assert f["error_category"] == "timeout"
    assert f["retryable"] is True
    assert f["exception_type"] == "TimeoutExpired"

    assert report["summary"]["failure_breakdown"]["by_code"] == {"TIMEOUT": 1}
    assert report["summary"]["failure_breakdown"]["by_phase"] == {"search": 1}


def test_validate_dataset_payload_rejects_unknown_relevant_session_id() -> None:
    bad = {
        "name": "mini",
        "questions": [
            {
                "question_id": "q1",
                "question": "where",
                "ground_truth": "taipei",
                "question_type": "fact",
                "relevant_session_ids": ["missing"],
                "sessions": [
                    {
                        "session_id": "s1",
                        "messages": [{"role": "user", "content": "meeting in Taipei"}],
                        "metadata": {},
                    }
                ],
            }
        ],
    }

    with pytest.raises(SchemaValidationError):
        validate_dataset_payload(bad)
