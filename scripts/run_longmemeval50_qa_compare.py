#!/usr/bin/env python3
"""Phase A QA compare on longmemeval-50 (repo-local dataset).

This is *not* the official LongMemEval runner.
Goal: provide an apples-to-apples QA correctness harness for our existing
LongMemEval-50-derived dataset so we can compare representation strategies:
- oracle (relevant sessions only)
- full (all sessions)
- observational (deterministic compression)

We use an LLM-as-judge yes/no rubric adapted from LongMemEval's evaluate_qa.py,
but default the judge model to the same model as the actor.

Requires:
  OPENAI_API_KEY in env

Writes artifacts under:
  artifacts/qa-compare/<run_group>/
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS_ROOT = REPO_ROOT / "artifacts" / "qa-compare"
DEFAULT_DATASET = REPO_ROOT / "data" / "datasets" / "longmemeval-50.json"


def _now_tag() -> str:
    return datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")


def _slug(s: str) -> str:
    out = []
    for ch in s.strip().lower():
        out.append(ch if ch.isalnum() or ch in {"-", "_", "."} else "-")
    txt = "".join(out).strip("-")
    while "--" in txt:
        txt = txt.replace("--", "-")
    return txt or "run"


def _jitter_sleep(min_s: float = 2.0, max_s: float = 6.0) -> None:
    # Human-like jitter between LLM requests (per pacing guardrails)
    time.sleep(random.uniform(min_s, max_s))


def openai_chat_completions(
    *,
    api_key: str,
    model: str,
    messages: list[dict[str, str]],
    temperature: float = 0.0,
    max_tokens: int = 256,
    timeout_s: int = 120,
    base_url: str = "https://api.openai.com/v1/chat/completions",
    max_retries: int = 8,
) -> str:
    """Minimal ChatCompletions client (stdlib only).

    Uses exponential backoff on 429/5xx.
    """

    body = json.dumps(
        {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
    ).encode("utf-8")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    delay = 1.5
    last_err: Exception | None = None

    for attempt in range(max_retries):
        req = urllib.request.Request(base_url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                raw = resp.read().decode("utf-8")
            data = json.loads(raw)
            return (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )
        except urllib.error.HTTPError as e:
            # Read body for debugging (keep local)
            try:
                err_body = e.read().decode("utf-8", errors="replace")
            except Exception:
                err_body = ""

            retryable = e.code in {429, 500, 502, 503, 504}
            last_err = RuntimeError(f"HTTP {e.code}: {err_body[:500]}")
            if not retryable or attempt == max_retries - 1:
                raise last_err
            time.sleep(delay)
            delay = min(delay * 1.8, 30.0)
        except Exception as e:
            last_err = e
            if attempt == max_retries - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 1.8, 30.0)

    if last_err:
        raise last_err
    raise RuntimeError("openai_chat_completions failed")


def get_anscheck_prompt(
    task: str,
    question: str,
    answer: str,
    response: str,
    *,
    abstention: bool = False,
) -> str:
    # Adapted from LongMemEval src/evaluation/evaluate_qa.py
    if not abstention:
        if task in {"single-session-user", "single-session-assistant", "multi-session"}:
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                "If the response is equivalent to the correct answer or contains all the intermediate steps "
                "to get the correct answer, you should also answer yes. If the response only contains a subset "
                "of the information required by the answer, answer no.\n\n"
                "Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)

        if task == "temporal-reasoning":
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                "If the response is equivalent to the correct answer or contains all the intermediate steps "
                "to get the correct answer, you should also answer yes. If the response only contains a subset "
                "of the information required by the answer, answer no. In addition, do not penalize off-by-one "
                "errors for the number of days.\n\n"
                "Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)

        if task == "knowledge-update":
            template = (
                "I will give you a question, a correct answer, and a response from a model. "
                "Please answer yes if the response contains the correct answer. Otherwise, answer no. "
                "If the response contains some previous information along with an updated answer, the response "
                "should be considered as correct as long as the updated answer is the required answer.\n\n"
                "Question: {}\n\nCorrect Answer: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)

        if task == "single-session-preference":
            template = (
                "I will give you a question, a rubric for desired personalized response, and a response from a model. "
                "Please answer yes if the response satisfies the desired response. Otherwise, answer no. "
                "The model does not need to reflect all the points in the rubric. The response is correct as long "
                "as it recalls and utilizes the user's personal information correctly.\n\n"
                "Question: {}\n\nRubric: {}\n\nModel Response: {}\n\n"
                "Is the model response correct? Answer yes or no only."
            )
            return template.format(question, answer, response)

        raise ValueError(f"unknown task: {task}")

    template = (
        "I will give you an unanswerable question, an explanation, and a response from a model. "
        "Please answer yes if the model correctly identifies the question as unanswerable. The model could say "
        "that the information is incomplete, or some other information is given but the asked information is not.\n\n"
        "Question: {}\n\nExplanation: {}\n\nModel Response: {}\n\n"
        "Does the model correctly identify the question as unanswerable? Answer yes or no only."
    )
    return template.format(question, answer, response)


def _clip(txt: str, max_chars: int) -> str:
    t = " ".join((txt or "").split())
    return t if len(t) <= max_chars else (t[: max_chars - 1] + "…")


def render_sessions_full(sessions: list[dict[str, Any]], *, max_msg_chars: int = 600) -> str:
    blocks: list[str] = []
    for s in sessions:
        sid = str(s.get("session_id") or "")
        blocks.append(f"[SESSION {sid}]")
        for m in s.get("messages", []):
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            content = _clip(str(m.get("content") or ""), max_msg_chars)
            if content:
                blocks.append(f"{role}: {content}")
        blocks.append("")
    return "\n".join(blocks).strip() + "\n"


def render_sessions_observational(
    sessions: list[dict[str, Any]],
    *,
    max_lines_per_session: int = 10,
    max_chars_per_line: int = 220,
) -> str:
    # Deterministic log-like compression (no LLM).
    lines: list[str] = []
    for s in sessions:
        sid = str(s.get("session_id") or "")
        lines.append(f"OBSERVATION [session:{sid}]")
        count = 0
        for m in s.get("messages", []):
            if not isinstance(m, dict):
                continue
            role = str(m.get("role") or "")
            content = _clip(str(m.get("content") or ""), max_chars_per_line)
            if not content:
                continue
            lines.append(f"- {role}: {content}")
            count += 1
            if count >= max_lines_per_session:
                break
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def actor_prompt(*, history: str, question: str) -> list[dict[str, str]]:
    return [
        {
            "role": "system",
            "content": (
                "You are a careful assistant. Answer the question using ONLY the provided history. "
                "If the history does not contain the answer, say you don't know. Be concise."
            ),
        },
        {"role": "user", "content": f"HISTORY:\n{history}\n\nQUESTION: {question}\nANSWER:"},
    ]


@dataclass
class Row:
    question_id: str
    question_type: str
    question: str
    answer: str
    hypothesis: str
    label: bool


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--run-group", default=f"{_now_tag()}-longmemeval50-qa")
    ap.add_argument("--model", default="gpt-5-mini")
    ap.add_argument("--judge-model", default="")
    ap.add_argument("--limit", type=int, default=20, help="question limit (default 20 for Phase A)")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--arms", nargs="+", default=["oracle", "observational"], choices=["oracle", "full", "observational"])
    ap.add_argument("--max-msg-chars", type=int, default=600)
    args = ap.parse_args()

    api_key = os.getenv("OPENAI_API_KEY") or ""
    if not api_key.strip():
        raise SystemExit("OPENAI_API_KEY is missing/empty. Set it in the environment before running.")

    judge_model = args.judge_model.strip() or args.model

    raw = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    questions = raw.get("questions")
    if not isinstance(questions, list) or not questions:
        raise SystemExit("dataset.questions must be a non-empty list")

    rng = random.Random(args.seed)
    qs = list(questions)
    rng.shuffle(qs)
    qs = qs[: max(0, min(args.limit, len(qs)))]

    run_group = _slug(args.run_group)
    out_dir = ARTIFACTS_ROOT / run_group
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "schema": "openclaw-memory-bench/qa-compare/v0.1",
        "dataset": str(Path(args.dataset).as_posix()),
        "run_group": run_group,
        "model": args.model,
        "judge_model": judge_model,
        "seed": args.seed,
        "limit": len(qs),
        "arms": args.arms,
        "created_at": datetime.now(UTC).isoformat(),
        "note": "Phase A QA compare on repo-local longmemeval-50 format (not official LongMemEval runner).",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    summary: dict[str, Any] = {"manifest": manifest, "arms": {}}

    for arm in args.arms:
        arm_dir = out_dir / arm
        arm_dir.mkdir(parents=True, exist_ok=True)
        hyp_path = arm_dir / "hypotheses.jsonl"
        eval_path = arm_dir / "eval.jsonl"

        rows: list[Row] = []

        with hyp_path.open("w", encoding="utf-8") as hyp_f, eval_path.open("w", encoding="utf-8") as eval_f:
            for i, q in enumerate(qs):
                qid = str(q.get("question_id") or "")
                qtype = str(q.get("question_type") or "")
                question = str(q.get("question") or "")
                answer = str(q.get("ground_truth") or q.get("answer") or "")
                sessions = q.get("sessions") if isinstance(q.get("sessions"), list) else []

                rel_ids = set(str(x) for x in (q.get("relevant_session_ids") or []) if str(x))
                if arm == "oracle":
                    arm_sessions = [s for s in sessions if str(s.get("session_id") or "") in rel_ids]
                else:
                    arm_sessions = sessions

                if arm == "observational":
                    history = render_sessions_observational(arm_sessions)
                else:
                    history = render_sessions_full(arm_sessions, max_msg_chars=args.max_msg_chars)

                # Actor
                _jitter_sleep()
                hyp = openai_chat_completions(
                    api_key=api_key,
                    model=args.model,
                    messages=actor_prompt(history=history, question=question),
                    temperature=0.0,
                    max_tokens=256,
                )

                print(json.dumps({"question_id": qid, "hypothesis": hyp}, ensure_ascii=False), file=hyp_f)

                # Judge
                abstention = "_abs" in qid
                judge_prompt = get_anscheck_prompt(qtype, question, answer, hyp, abstention=abstention)

                _jitter_sleep()
                judge_resp = openai_chat_completions(
                    api_key=api_key,
                    model=judge_model,
                    messages=[{"role": "user", "content": judge_prompt}],
                    temperature=0.0,
                    max_tokens=10,
                )

                label = "yes" in judge_resp.lower()

                entry = {
                    "question_id": qid,
                    "question_type": qtype,
                    "hypothesis": hyp,
                    "autoeval": {
                        "judge_model": judge_model,
                        "label": bool(label),
                        "raw": judge_resp,
                    },
                }
                print(json.dumps(entry, ensure_ascii=False), file=eval_f)

                rows.append(Row(qid, qtype, question, answer, hyp, bool(label)))

                # Progress line
                print(f"[{arm}] {i+1}/{len(qs)} qid={qid} label={label}")

        # Summarize
        by_type: dict[str, list[bool]] = {}
        for r in rows:
            by_type.setdefault(r.question_type, []).append(r.label)

        def acc(xs: Iterable[bool]) -> float:
            xs2 = list(xs)
            return (sum(1 for x in xs2 if x) / len(xs2)) if xs2 else 0.0

        arm_summary = {
            "n": len(rows),
            "accuracy": acc([r.label for r in rows]),
            "by_question_type": {k: {"accuracy": acc(v), "n": len(v)} for k, v in sorted(by_type.items())},
            "paths": {"hypotheses": str(hyp_path.relative_to(REPO_ROOT)), "eval": str(eval_path.relative_to(REPO_ROOT))},
        }
        summary["arms"][arm] = arm_summary

    # Write summary
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Markdown
    md_lines: list[str] = []
    md_lines.append(f"# LongMemEval-50 QA compare (Phase A) — {run_group}\n")
    md_lines.append(f"- Model (actor): `{args.model}`")
    md_lines.append(f"- Judge model: `{judge_model}`")
    md_lines.append(f"- Limit: {manifest['limit']} (seed={args.seed})")
    md_lines.append(f"- Dataset: `{manifest['dataset']}`\n")

    for arm in args.arms:
        a = summary["arms"][arm]
        md_lines.append(f"## Arm: {arm}\n")
        md_lines.append(f"- Accuracy: {a['accuracy']:.4f} (n={a['n']})")
        md_lines.append("- By question type:")
        for k, v in a["by_question_type"].items():
            md_lines.append(f"  - {k}: {v['accuracy']:.4f} (n={v['n']})")
        md_lines.append(f"- Artifacts: `{a['paths']['eval']}`")
        md_lines.append("")

    (out_dir / "summary.md").write_text("\n".join(md_lines).strip() + "\n", encoding="utf-8")

    print(str(out_dir / "summary.md"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
