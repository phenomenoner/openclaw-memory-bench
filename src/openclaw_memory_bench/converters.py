from __future__ import annotations

import json
import re
import urllib.request
from pathlib import Path
from typing import Any


LOCOMO_URL = "https://raw.githubusercontent.com/snap-research/locomo/main/data/locomo10.json"
LONGMEMEVAL_URL = "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned/resolve/main/longmemeval_s_cleaned.json"
CONVOMEM_BASE = "https://huggingface.co/datasets/Salesforce/ConvoMem/resolve/main/core_benchmark/pre_mixed_testcases"

CONVOMEM_CATEGORIES: dict[str, list[str]] = {
    "user_evidence": ["1_evidence"],
    "assistant_facts_evidence": ["1_evidence"],
    "changing_evidence": ["2_evidence"],
    "abstention_evidence": ["1_evidence"],
    "preference_evidence": ["1_evidence"],
    "implicit_connection_evidence": ["1_evidence"],
}

_LOC_EVID_RE = re.compile(r"D(\d+):\d+")


def _download_json(url: str) -> Any:
    with urllib.request.urlopen(url, timeout=180) as r:
        return json.loads(r.read().decode("utf-8"))


def _message(role: str, content: str) -> dict:
    return {"role": role, "content": content}


def convert_locomo(*, limit: int | None = None) -> dict:
    data = _download_json(LOCOMO_URL)
    questions: list[dict] = []

    for item in data:
        sample_id = str(item.get("sample_id"))
        conv = item.get("conversation", {})
        speaker_a = conv.get("speaker_a")

        sessions: list[dict] = []
        session_map: dict[int, str] = {}
        i = 1
        while True:
            skey = f"session_{i}"
            if skey not in conv:
                break
            sid = f"{sample_id}-{skey}"
            session_map[i] = sid
            msgs = conv[skey]
            parsed_msgs = []
            for m in msgs:
                role = "user" if m.get("speaker") == speaker_a else "assistant"
                parsed_msgs.append(_message(role, str(m.get("text") or "")))
            sessions.append({"session_id": sid, "messages": parsed_msgs, "metadata": {}})
            i += 1

        for qi, qa in enumerate(item.get("qa", [])):
            qid = f"{sample_id}-q{qi}"
            evidences = qa.get("evidence") or []
            relevant = []
            for ev in evidences:
                m = _LOC_EVID_RE.search(str(ev))
                if m:
                    idx = int(m.group(1))
                    sid = session_map.get(idx)
                    if sid and sid not in relevant:
                        relevant.append(sid)
            if not relevant and sessions:
                relevant = [sessions[0]["session_id"]]

            questions.append(
                {
                    "question_id": qid,
                    "question": str(qa.get("question") or ""),
                    "ground_truth": str(qa.get("answer") or ""),
                    "question_type": f"category-{qa.get('category')}",
                    "relevant_session_ids": relevant,
                    "sessions": sessions,
                }
            )

            if limit and len(questions) >= limit:
                return {"name": "locomo", "questions": questions}

    return {"name": "locomo", "questions": questions}


def convert_longmemeval(*, limit: int | None = None) -> dict:
    data = _download_json(LONGMEMEVAL_URL)
    questions: list[dict] = []

    for item in data:
        qid = str(item.get("question_id") or "")
        if not qid:
            continue

        question = str(item.get("question") or "").strip()
        answer = str(item.get("answer") or "").strip()
        if not question or not answer:
            continue

        sessions = []
        relevant: list[str] = []

        haystack_sessions = item.get("haystack_sessions") or []
        for raw_session in haystack_sessions:
            parsed_msgs = []
            has_answer = False
            for msg in raw_session:
                role = str(msg.get("role") or "user")
                content = str(msg.get("content") or "").strip()
                if bool(msg.get("has_answer")):
                    has_answer = True
                if not content:
                    continue
                parsed_msgs.append(_message(role, content))

            if not parsed_msgs:
                continue

            sid = f"{qid}-session-{len(sessions)}"
            sessions.append({"session_id": sid, "messages": parsed_msgs, "metadata": {}})
            if has_answer:
                relevant.append(sid)

        if not sessions:
            continue

        if not relevant:
            relevant = [sessions[0]["session_id"]]

        questions.append(
            {
                "question_id": qid,
                "question": question,
                "ground_truth": answer,
                "question_type": str(item.get("question_type") or "generic"),
                "relevant_session_ids": relevant,
                "sessions": sessions,
            }
        )

        if limit and len(questions) >= limit:
            break

    return {"name": "longmemeval", "questions": questions}


def _session_has_evidence_messages(session: dict, evidence_texts: set[str]) -> bool:
    for m in session.get("messages", []):
        if str(m.get("content") or "") in evidence_texts:
            return True
    return False


def convert_convomem(*, limit: int | None = None) -> dict:
    questions: list[dict] = []

    for category, folders in CONVOMEM_CATEGORIES.items():
        for folder in folders:
            url = f"{CONVOMEM_BASE}/{category}/{folder}/batched_000.json"
            batched = _download_json(url)

            for bidx, batch in enumerate(batched):
                evidence_items = batch.get("evidenceItems") or []
                for eidx, ev in enumerate(evidence_items):
                    qid = f"convomem-{category}-{bidx}-{eidx}"

                    sessions = []
                    convs = ev.get("conversations") or []
                    for ci, conv in enumerate(convs):
                        sid = f"{qid}-session-{ci}"
                        msgs = [
                            _message(
                                "user" if str(m.get("speaker", "")).lower() == "user" else "assistant",
                                str(m.get("text") or ""),
                            )
                            for m in (conv.get("messages") or [])
                        ]
                        sessions.append({"session_id": sid, "messages": msgs, "metadata": {}})

                    evidence_texts = {
                        str(x.get("text") or "") for x in (ev.get("message_evidences") or []) if x.get("text")
                    }
                    relevant = [
                        s["session_id"] for s in sessions if _session_has_evidence_messages(s, evidence_texts)
                    ]
                    if not relevant and sessions:
                        relevant = [sessions[0]["session_id"]]

                    questions.append(
                        {
                            "question_id": qid,
                            "question": str(ev.get("question") or ""),
                            "ground_truth": str(ev.get("answer") or ""),
                            "question_type": category,
                            "relevant_session_ids": relevant,
                            "sessions": sessions,
                        }
                    )

                    if limit and len(questions) >= limit:
                        return {"name": "convomem", "questions": questions}

    return {"name": "convomem", "questions": questions}


def benchmark_sources(benchmark: str) -> list[str]:
    b = benchmark.lower()
    if b == "locomo":
        return [LOCOMO_URL]
    if b == "longmemeval":
        return [LONGMEMEVAL_URL]
    if b == "convomem":
        urls: list[str] = []
        for category, folders in CONVOMEM_CATEGORIES.items():
            for folder in folders:
                urls.append(f"{CONVOMEM_BASE}/{category}/{folder}/batched_000.json")
        return urls
    raise ValueError(f"Unsupported benchmark: {benchmark}")


def convert_benchmark(benchmark: str, *, limit: int | None = None) -> dict:
    b = benchmark.lower()
    if b == "locomo":
        return convert_locomo(limit=limit)
    if b == "longmemeval":
        return convert_longmemeval(limit=limit)
    if b == "convomem":
        return convert_convomem(limit=limit)
    raise ValueError(f"Unsupported benchmark: {benchmark}")


def write_dataset(data: dict, out_path: str | Path) -> Path:
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return p
