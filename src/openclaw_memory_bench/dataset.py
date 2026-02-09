from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .protocol import Session, SessionMessage
from .validation import validate_dataset_payload


@dataclass
class RetrievalQuestion:
    question_id: str
    question: str
    ground_truth: str
    question_type: str
    sessions: list[Session]
    relevant_session_ids: list[str]


@dataclass
class RetrievalDataset:
    name: str
    questions: list[RetrievalQuestion]


def _build_session(raw: dict) -> Session:
    sid = str(raw.get("session_id") or "")
    if not sid:
        raise ValueError("session_id is required")

    messages_raw = raw.get("messages")
    if not isinstance(messages_raw, list) or not messages_raw:
        raise ValueError(f"session {sid}: messages must be a non-empty list")

    messages: list[SessionMessage] = []
    for m in messages_raw:
        role = str(m.get("role") or "")
        content = str(m.get("content") or "")
        ts = m.get("ts")
        if role not in {"user", "assistant", "system", "tool"}:
            raise ValueError(f"session {sid}: unsupported role {role!r}")
        if not content.strip():
            raise ValueError(f"session {sid}: message content cannot be empty")
        messages.append(SessionMessage(role=role, content=content, ts=ts))

    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    return Session(session_id=sid, messages=messages, metadata=metadata)


def load_retrieval_dataset(path: str | Path) -> RetrievalDataset:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Dataset file not found: {p}")

    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError("dataset root must be an object")

    validate_dataset_payload(raw)

    name = str(raw.get("name") or p.stem)

    raw_questions = raw.get("questions")
    if not isinstance(raw_questions, list) or not raw_questions:
        raise ValueError("dataset.questions must be a non-empty list")

    questions: list[RetrievalQuestion] = []
    for q in raw_questions:
        qid = str(q.get("question_id") or "")
        question = str(q.get("question") or "")
        ground_truth = str(q.get("ground_truth") or "")
        question_type = str(q.get("question_type") or "generic")

        if not qid or not question or not ground_truth:
            raise ValueError("question requires question_id, question, ground_truth")

        sessions_raw = q.get("sessions")
        if not isinstance(sessions_raw, list) or not sessions_raw:
            raise ValueError(f"question {qid}: sessions must be a non-empty list")

        sessions = [_build_session(s) for s in sessions_raw]
        known_session_ids = {s.session_id for s in sessions}

        rel = q.get("relevant_session_ids")
        if rel is None:
            relevant_session_ids = [sessions[0].session_id]
        else:
            if not isinstance(rel, list) or not rel:
                raise ValueError(f"question {qid}: relevant_session_ids must be a non-empty list")
            relevant_session_ids = [str(x) for x in rel]

        unknown = [sid for sid in relevant_session_ids if sid not in known_session_ids]
        if unknown:
            raise ValueError(f"question {qid}: unknown relevant_session_ids: {unknown}")

        questions.append(
            RetrievalQuestion(
                question_id=qid,
                question=question,
                ground_truth=ground_truth,
                question_type=question_type,
                sessions=sessions,
                relevant_session_ids=relevant_session_ids,
            )
        )

    return RetrievalDataset(name=name, questions=questions)
