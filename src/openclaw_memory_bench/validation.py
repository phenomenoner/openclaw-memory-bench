from __future__ import annotations

from collections.abc import Sequence
from typing import Any

_ALLOWED_ROLES = {"user", "assistant", "system", "tool"}


class SchemaValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        msg = "schema validation failed"
        if errors:
            msg += ": " + "; ".join(errors[:5])
            if len(errors) > 5:
                msg += f" ... (+{len(errors) - 5} more)"
        super().__init__(msg)


def _is_number(x: Any) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def _require(condition: bool, path: str, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(f"{path}: {message}")


def _require_non_empty_str(value: Any, path: str, errors: list[str]) -> None:
    _require(isinstance(value, str) and value.strip() != "", path, "must be a non-empty string", errors)


def _require_list(value: Any, path: str, errors: list[str]) -> list[Any]:
    if not isinstance(value, list):
        errors.append(f"{path}: must be a list")
        return []
    return value


def validate_dataset_payload(payload: dict[str, Any]) -> None:
    errors: list[str] = []

    _require(isinstance(payload, dict), "dataset", "must be an object", errors)
    if not isinstance(payload, dict):
        raise SchemaValidationError(errors)

    _require_non_empty_str(payload.get("name"), "dataset.name", errors)

    questions = _require_list(payload.get("questions"), "dataset.questions", errors)
    _require(len(questions) > 0, "dataset.questions", "must be a non-empty list", errors)

    for qi, q in enumerate(questions):
        qpath = f"dataset.questions[{qi}]"
        _require(isinstance(q, dict), qpath, "must be an object", errors)
        if not isinstance(q, dict):
            continue

        _require_non_empty_str(q.get("question_id"), f"{qpath}.question_id", errors)
        _require_non_empty_str(q.get("question"), f"{qpath}.question", errors)
        _require_non_empty_str(q.get("ground_truth"), f"{qpath}.ground_truth", errors)
        _require_non_empty_str(q.get("question_type"), f"{qpath}.question_type", errors)

        sessions = _require_list(q.get("sessions"), f"{qpath}.sessions", errors)
        _require(len(sessions) > 0, f"{qpath}.sessions", "must be a non-empty list", errors)

        session_ids: set[str] = set()
        for si, s in enumerate(sessions):
            spath = f"{qpath}.sessions[{si}]"
            _require(isinstance(s, dict), spath, "must be an object", errors)
            if not isinstance(s, dict):
                continue

            sid = s.get("session_id")
            _require_non_empty_str(sid, f"{spath}.session_id", errors)
            if isinstance(sid, str) and sid.strip():
                session_ids.add(sid)

            messages = _require_list(s.get("messages"), f"{spath}.messages", errors)
            _require(len(messages) > 0, f"{spath}.messages", "must be a non-empty list", errors)

            for mi, m in enumerate(messages):
                mpath = f"{spath}.messages[{mi}]"
                _require(isinstance(m, dict), mpath, "must be an object", errors)
                if not isinstance(m, dict):
                    continue

                role = m.get("role")
                _require(
                    isinstance(role, str) and role in _ALLOWED_ROLES,
                    f"{mpath}.role",
                    f"must be one of {sorted(_ALLOWED_ROLES)}",
                    errors,
                )
                _require_non_empty_str(m.get("content"), f"{mpath}.content", errors)

        rel = _require_list(q.get("relevant_session_ids"), f"{qpath}.relevant_session_ids", errors)
        _require(len(rel) > 0, f"{qpath}.relevant_session_ids", "must be a non-empty list", errors)
        for ri, sid in enumerate(rel):
            rpath = f"{qpath}.relevant_session_ids[{ri}]"
            _require_non_empty_str(sid, rpath, errors)
            if isinstance(sid, str) and sid.strip() and session_ids:
                _require(sid in session_ids, rpath, "must reference an existing session_id", errors)

    if errors:
        raise SchemaValidationError(errors)


def _validate_metrics(obj: dict[str, Any], path: str, errors: list[str]) -> None:
    for key in ("hit_at_k", "precision_at_k", "recall_at_k", "mrr", "ndcg_at_k"):
        _require(_is_number(obj.get(key)), f"{path}.{key}", "must be a number", errors)


def validate_retrieval_report_payload(report: dict[str, Any]) -> None:
    errors: list[str] = []

    _require(isinstance(report, dict), "report", "must be an object", errors)
    if not isinstance(report, dict):
        raise SchemaValidationError(errors)

    _require_non_empty_str(report.get("schema"), "report.schema", errors)
    _require_non_empty_str(report.get("run_id"), "report.run_id", errors)
    _require_non_empty_str(report.get("provider"), "report.provider", errors)
    _require_non_empty_str(report.get("dataset"), "report.dataset", errors)
    _require(_is_number(report.get("top_k")), "report.top_k", "must be a number", errors)
    _require_non_empty_str(report.get("created_at_utc"), "report.created_at_utc", errors)

    summary = report.get("summary")
    _require(isinstance(summary, dict), "report.summary", "must be an object", errors)
    if isinstance(summary, dict):
        for key in ("questions_total", "questions_succeeded", "questions_failed"):
            _require(isinstance(summary.get(key), int), f"report.summary.{key}", "must be an integer", errors)
        _validate_metrics(summary, "report.summary", errors)

        breakdown = summary.get("failure_breakdown")
        _require(isinstance(breakdown, dict), "report.summary.failure_breakdown", "must be an object", errors)
        if isinstance(breakdown, dict):
            for key in ("by_code", "by_category", "by_phase"):
                obj = breakdown.get(key)
                _require(isinstance(obj, dict), f"report.summary.failure_breakdown.{key}", "must be an object", errors)
                if isinstance(obj, dict):
                    for kk, vv in obj.items():
                        _require_non_empty_str(kk, f"report.summary.failure_breakdown.{key} key", errors)
                        _require(isinstance(vv, int), f"report.summary.failure_breakdown.{key}.{kk}", "must be an integer", errors)

    latency = report.get("latency")
    _require(isinstance(latency, dict), "report.latency", "must be an object", errors)
    if isinstance(latency, dict):
        for key in ("search_ms_p50", "search_ms_p95", "search_ms_mean"):
            _require(_is_number(latency.get(key)), f"report.latency.{key}", "must be a number", errors)

    results = _require_list(report.get("results"), "report.results", errors)
    for ri, row in enumerate(results):
        rpath = f"report.results[{ri}]"
        _require(isinstance(row, dict), rpath, "must be an object", errors)
        if not isinstance(row, dict):
            continue
        for key in (
            "question_id",
            "question",
            "question_type",
            "ground_truth",
        ):
            _require_non_empty_str(row.get(key), f"{rpath}.{key}", errors)

        for key in ("relevant_session_ids", "retrieved_session_ids", "retrieved_observation_ids", "retrieved_sources"):
            _require(isinstance(row.get(key), list), f"{rpath}.{key}", "must be a list", errors)

        _require(_is_number(row.get("latency_ms")), f"{rpath}.latency_ms", "must be a number", errors)

        metrics = row.get("metrics")
        _require(isinstance(metrics, dict), f"{rpath}.metrics", "must be an object", errors)
        if isinstance(metrics, dict):
            _validate_metrics(metrics, f"{rpath}.metrics", errors)

    failures = _require_list(report.get("failures"), "report.failures", errors)
    for fi, f in enumerate(failures):
        fpath = f"report.failures[{fi}]"
        _require(isinstance(f, dict), fpath, "must be an object", errors)
        if not isinstance(f, dict):
            continue

        _require_non_empty_str(f.get("question_id"), f"{fpath}.question_id", errors)
        _require_non_empty_str(f.get("phase"), f"{fpath}.phase", errors)
        _require_non_empty_str(f.get("error_code"), f"{fpath}.error_code", errors)
        _require_non_empty_str(f.get("error_category"), f"{fpath}.error_category", errors)
        _require(isinstance(f.get("retryable"), bool), f"{fpath}.retryable", "must be a boolean", errors)
        _require_non_empty_str(f.get("exception_type"), f"{fpath}.exception_type", errors)
        _require_non_empty_str(f.get("error"), f"{fpath}.error", errors)

    if errors:
        raise SchemaValidationError(errors)


def validate_required_keys(payload: dict[str, Any], keys: Sequence[str], *, path: str = "object") -> None:
    errors: list[str] = []
    for key in keys:
        _require(key in payload, f"{path}.{key}", "is required", errors)
    if errors:
        raise SchemaValidationError(errors)
