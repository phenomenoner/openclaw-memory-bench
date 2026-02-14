#!/usr/bin/env python3
"""Phase A QA compare on longmemeval-50 using OpenClaw Gateway routing (codex).

This runner uses `openclaw agent` (Gateway-backed) for both:
- Actor: answer generation from provided history
- Judge: LongMemEval-style yes/no correctness rubric

Why:
- Avoid direct OpenAI API keys.
- Use the deployment's configured provider auth (openai-codex OAuth).

Outputs under:
  artifacts/qa-compare/<run_group>/

Notes:
- This is a *calibration harness* for our repo-local longmemeval-50 dataset format.
- Pacing: sleeps ~17–21s between LLM calls to respect per-agent rate guardrails.
"""

from __future__ import annotations

import argparse
import json
import random
import subprocess
import time
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


def _sleep_jitter(rng: random.Random) -> None:
    # pacing: 15s + 2-6s jitter
    time.sleep(15.0 + rng.uniform(2.0, 6.0))


def openclaw_agent_once(
    *,
    session_id: str,
    message: str,
    thinking: str = "high",
    timeout_s: int = 600,
) -> str:
    """Call OpenClaw agent (Gateway-backed) and return concatenated text payloads."""
    cmd = [
        "openclaw",
        "agent",
        "--session-id",
        session_id,
        "--message",
        message,
        "--thinking",
        thinking,
        "--timeout",
        str(timeout_s),
        "--json",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or f"openclaw agent failed ({proc.returncode})")

    data = json.loads(proc.stdout)
    payloads = (((data or {}).get("result") or {}).get("payloads")) or []
    texts: list[str] = []
    for p in payloads:
        t = p.get("text")
        if isinstance(t, str) and t.strip():
            texts.append(t.strip())
    return "\n".join(texts).strip()


def get_anscheck_prompt(task: str, question: str, answer: str, response: str, *, abstention: bool = False) -> str:
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


def actor_message(*, history: str, question: str) -> str:
    return (
        "You are a careful assistant. Answer the question using ONLY the provided history. "
        "If the history does not contain the answer, say you don't know. Be concise.\n\n"
        f"HISTORY:\n{history}\n\nQUESTION: {question}\nANSWER:"
    )


@dataclass
class Row:
    question_id: str
    question_type: str
    label: bool


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=str(DEFAULT_DATASET))
    ap.add_argument("--run-group", default=f"{_now_tag()}-longmemeval50-qa-openclaw")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--arms", nargs="+", default=["oracle", "observational"], choices=["oracle", "full", "observational"])
    ap.add_argument("--max-msg-chars", type=int, default=600)
    ap.add_argument("--thinking", default="high")
    args = ap.parse_args()

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
        "schema": "openclaw-memory-bench/qa-compare-openclaw/v0.1",
        "dataset": str(Path(args.dataset).as_posix()),
        "run_group": run_group,
        "seed": args.seed,
        "limit": len(qs),
        "arms": args.arms,
        "thinking": args.thinking,
        "created_at": datetime.now(UTC).isoformat(),
        "note": "Uses openclaw agent (Gateway) for actor+judge; pacing enforced via sleeps.",
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

                actor_sid = f"membench-qa-{run_group}-{arm}-actor-{qid}"
                judge_sid = f"membench-qa-{run_group}-{arm}-judge-{qid}"

                # Actor
                _sleep_jitter(rng)
                hyp = openclaw_agent_once(
                    session_id=actor_sid,
                    message=actor_message(history=history, question=question),
                    thinking=args.thinking,
                )
                print(json.dumps({"question_id": qid, "hypothesis": hyp}, ensure_ascii=False), file=hyp_f, flush=True)
                hyp_f.flush()

                # Judge
                abstention = "_abs" in qid
                judge_prompt = get_anscheck_prompt(qtype, question, answer, hyp, abstention=abstention)

                _sleep_jitter(rng)
                judge_resp = openclaw_agent_once(
                    session_id=judge_sid,
                    message=judge_prompt,
                    thinking=args.thinking,
                )
                label = "yes" in judge_resp.lower()

                entry = {
                    "question_id": qid,
                    "question_type": qtype,
                    "hypothesis": hyp,
                    "autoeval": {
                        "label": bool(label),
                        "raw": judge_resp,
                    },
                }
                print(json.dumps(entry, ensure_ascii=False), file=eval_f, flush=True)
                eval_f.flush()
                rows.append(Row(qid, qtype, bool(label)))

                print(f"[{arm}] {i+1}/{len(qs)} qid={qid} label={label}", flush=True)

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

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    md_lines: list[str] = []
    md_lines.append(f"# LongMemEval-50 QA compare (Phase A, OpenClaw) — {run_group}\n")
    md_lines.append(f"- Thinking: `{args.thinking}`")
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
