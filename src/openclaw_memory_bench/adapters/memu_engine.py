from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from openclaw_memory_bench.gateway_client import invoke_tool
from openclaw_memory_bench.protocol import SearchHit, Session

_SESSION_MARKER_PATTERNS = [
    re.compile(r"\[session:([A-Za-z0-9_.:-]+)\]", re.IGNORECASE),
    re.compile(r"session[_\s-]?id\s*[:=]\s*([A-Za-z0-9_.:-]+)", re.IGNORECASE),
]
_FILE_TOKEN_RE = re.compile(r"([A-Za-z0-9_.-]+)\.(jsonl|json|md)", re.IGNORECASE)
_LINE_SUFFIX_RE = re.compile(r":\d+(?::\d+)?$")


class MemuEngineAdapter:
    """OpenClaw memu-engine adapter via Gateway tools/invoke.

    Notes:
    - `memory_search` / `memory_get` are expected to be provided by memory slot.
    - Ingest is optional and defaults to no-op (pre-ingested mode).
    """

    name = "memu-engine"

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.session_key = "main"
        self.ingest_mode = "noop"

    def initialize(self, config: dict) -> None:
        self.config = dict(config)
        self.session_key = str(config.get("session_key") or "main")
        self.ingest_mode = str(config.get("ingest_mode") or "noop")

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        if self.ingest_mode == "noop":
            return {"ingest": "noop", "sessions": len(sessions), "container_tag": container_tag}

        if self.ingest_mode != "memory_store":
            raise ValueError(f"Unsupported memu ingest_mode: {self.ingest_mode}")

        count = 0
        for s in sessions:
            for m in s.messages:
                if m.role not in {"user", "assistant", "system", "tool"}:
                    continue
                text = f"[session:{s.session_id}] {m.content}"
                invoke_tool(
                    tool="memory_store",
                    tool_args={
                        "text": text,
                        "category": "benchmark-ingest",
                        "importance": 0.1,
                    },
                    session_key=self.session_key,
                    config=self.config,
                )
                count += 1

        return {"ingest": "memory_store", "stored": count, "container_tag": container_tag}

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        return None

    @staticmethod
    def _extract_results(result: Any) -> list[dict]:
        # Typical shape: {"content":[{"type":"text","text":"{\"results\":[...]}"]}
        if isinstance(result, dict):
            if isinstance(result.get("results"), list):
                return result["results"]

            details = result.get("details")
            if isinstance(details, dict) and isinstance(details.get("results"), list):
                return details["results"]

            content = result.get("content")
            if isinstance(content, list):
                for c in content:
                    if not isinstance(c, dict):
                        continue
                    text = c.get("text")
                    if not isinstance(text, str):
                        continue
                    text = text.strip()
                    if not text:
                        continue
                    try:
                        parsed = json.loads(text)
                        if isinstance(parsed, dict) and isinstance(parsed.get("results"), list):
                            return parsed["results"]
                    except json.JSONDecodeError:
                        continue

        if isinstance(result, list):
            return [x for x in result if isinstance(x, dict)]

        return []

    @staticmethod
    def _normalize_sid(candidate: str | None) -> str | None:
        if not candidate:
            return None
        sid = candidate.strip().strip("\"'[](){}<>.,;:")
        return sid or None

    @staticmethod
    def _extract_sid_from_path(path: str | None) -> str | None:
        if not path:
            return None

        no_line = _LINE_SUFFIX_RE.sub("", path)
        name = Path(no_line).name
        m = _FILE_TOKEN_RE.search(name)
        if not m:
            return None

        stem = m.group(1)
        if stem.startswith("session-"):
            stem = stem[len("session-") :]

        return MemuEngineAdapter._normalize_sid(stem)

    @staticmethod
    def _extract_sid_from_text(text: str | None) -> str | None:
        if not text:
            return None

        for pat in _SESSION_MARKER_PATTERNS:
            m = pat.search(text)
            if m:
                sid = MemuEngineAdapter._normalize_sid(m.group(1))
                if sid:
                    return sid

        for m in _FILE_TOKEN_RE.finditer(text):
            stem = m.group(1)
            if stem.startswith("session-"):
                stem = stem[len("session-") :]
            sid = MemuEngineAdapter._normalize_sid(stem)
            if sid:
                return sid

        return None

    @staticmethod
    def _extract_session_id(path: str | None, snippet: str | None) -> str | None:
        sid = MemuEngineAdapter._extract_sid_from_path(path)
        if sid:
            return sid

        return MemuEngineAdapter._extract_sid_from_text(snippet)

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        result = invoke_tool(
            tool="memory_search",
            tool_args={"query": query, "maxResults": limit},
            session_key=self.session_key,
            config=self.config,
        )

        rows = self._extract_results(result)
        hits: list[SearchHit] = []
        for idx, row in enumerate(rows):
            snippet = str(row.get("snippet") or row.get("text") or "")
            path = row.get("path") or row.get("citation")
            sid = self._extract_session_id(path, snippet)

            meta = {
                "container_tag": container_tag,
                "path": path,
                "source": row.get("source"),
                "citation": row.get("citation"),
                "session_id": sid,
            }

            hit_id = str(row.get("id") or row.get("citation") or row.get("path") or f"hit-{idx}")
            score = float(row.get("score", 0.0) or 0.0)
            hits.append(SearchHit(id=hit_id, content=snippet, score=score, metadata=meta))

        return hits

    def clear(self, container_tag: str) -> None:
        return None
