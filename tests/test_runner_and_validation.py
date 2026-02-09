from __future__ import annotations

import re
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


class _EchoSessionAdapter(_SuccessAdapter):
    def search(self, query: str, container_tag: str, limit: int = 10):
        del query, limit
        # container_tag format: <run_id>:<question_id>
        qid = container_tag.split(":", 1)[1]
        return [
            SearchHit(
                id=qid,
                content=f"answer for {qid}",
                score=1.0,
                metadata={"session_id": qid, "path": f"memory/session-{qid}.md"},
            )
        ]


class _PreindexAdapter(_SuccessAdapter):
    ingest_calls = 0

    def ingest(self, sessions, container_tag: str) -> dict:
        type(self).ingest_calls += 1
        self.sessions = list(sessions)
        self.container_tag = container_tag
        return {"container_tag": container_tag, "sessions": len(sessions)}

    def search(self, query: str, container_tag: str, limit: int = 10):
        del limit, container_tag
        m = re.search(r"(\d+)", query)
        sid = f"s{m.group(1)}" if m else "s0"
        return [
            SearchHit(
                id=sid,
                content=f"answer for {sid}",
                score=1.0,
                metadata={"session_id": sid, "path": f"memory/session-{sid}.md"},
            )
        ]


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


def _multi_dataset(n: int = 6) -> RetrievalDataset:
    questions: list[RetrievalQuestion] = []
    for i in range(n):
        qid = f"s{i}"
        questions.append(
            RetrievalQuestion(
                question_id=qid,
                question=f"where {i}?",
                ground_truth=qid,
                question_type="fact",
                sessions=[
                    Session(
                        session_id=qid,
                        messages=[SessionMessage(role="user", content=f"message {i}")],
                        metadata={},
                    )
                ],
                relevant_session_ids=[qid],
            )
        )
    return RetrievalDataset(name="multi", questions=questions)


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


def test_run_retrieval_sample_subset_is_seeded_and_deterministic(monkeypatch) -> None:
    import openclaw_memory_bench.runner as runner

    monkeypatch.setattr(runner, "available_adapters", lambda: {"fake": _EchoSessionAdapter})

    kwargs = dict(
        provider="fake",
        dataset=_multi_dataset(8),
        top_k=5,
        provider_config={},
        skip_ingest=False,
        fail_fast=False,
        limit=None,
        sample_size=3,
        sample_seed=7,
        manifest={"schema": "test"},
    )

    r1 = run_retrieval_benchmark(run_id="run-a", **kwargs)
    r2 = run_retrieval_benchmark(run_id="run-b", **kwargs)

    qids1 = [x["question_id"] for x in r1["results"]]
    qids2 = [x["question_id"] for x in r2["results"]]
    assert qids1 == qids2
    assert len(qids1) == 3
    assert r1["summary"]["questions_total"] == 3


def test_run_retrieval_sample_size_too_large_raises(monkeypatch) -> None:
    import openclaw_memory_bench.runner as runner

    monkeypatch.setattr(runner, "available_adapters", lambda: {"fake": _EchoSessionAdapter})

    with pytest.raises(ValueError):
        run_retrieval_benchmark(
            provider="fake",
            dataset=_multi_dataset(2),
            top_k=5,
            run_id="run-bad-sample",
            provider_config={},
            skip_ingest=False,
            fail_fast=False,
            limit=None,
            sample_size=3,
            sample_seed=1,
            manifest={"schema": "test"},
        )


def test_preindex_once_ingests_once(monkeypatch) -> None:
    import openclaw_memory_bench.runner as runner

    _PreindexAdapter.ingest_calls = 0
    monkeypatch.setattr(runner, "available_adapters", lambda: {"fake": _PreindexAdapter})

    report = run_retrieval_benchmark(
        provider="fake",
        dataset=_multi_dataset(5),
        top_k=5,
        run_id="run-preindex",
        provider_config={},
        skip_ingest=False,
        preindex_once=True,
        fail_fast=False,
        limit=3,
        sample_size=None,
        sample_seed=None,
        manifest={"schema": "test"},
    )

    assert report["summary"]["questions_failed"] == 0
    assert report["summary"]["questions_total"] == 3
    assert _PreindexAdapter.ingest_calls == 1
    assert report["config"]["preindex_once"] is True
