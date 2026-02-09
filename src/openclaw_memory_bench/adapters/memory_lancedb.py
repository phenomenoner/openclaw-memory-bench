from __future__ import annotations

import re
from typing import Any

from openclaw_memory_bench.gateway_client import invoke_tool
from openclaw_memory_bench.protocol import SearchHit, Session

_SESSION_MARKER_RE = re.compile(r"\[session:([A-Za-z0-9_.:-]+)\]", re.IGNORECASE)


class MemoryLanceDBAdapter:
    """Adapter for OpenClaw memory-lancedb tools via Gateway invoke.

    Uses canonical memory tools:
    - memory_store
    - memory_recall
    - memory_forget

    Isolation strategy:
    - every ingested row is prefixed with a deterministic [container:<tag>] marker
    - search filters by this marker
    - clear removes tracked memory ids and best-effort marker matches
    """

    name = "memory-lancedb"

    def __init__(self) -> None:
        self.config: dict[str, Any] = {}
        self.session_key = "main"
        self.recall_limit_factor = 10
        self._container_ids: dict[str, list[str]] = {}

    def initialize(self, config: dict) -> None:
        self.config = dict(config)
        self.session_key = str(config.get("session_key") or "main")
        self.recall_limit_factor = int(config.get("recall_limit_factor") or 10)

    @staticmethod
    def _container_marker(container_tag: str) -> str:
        return f"[container:{container_tag}]"

    @staticmethod
    def _session_id_from_text(text: str) -> str | None:
        m = _SESSION_MARKER_RE.search(text)
        if not m:
            return None
        sid = m.group(1).strip()
        return sid or None

    @staticmethod
    def _extract_memories(result: Any) -> list[dict]:
        if not isinstance(result, dict):
            return []
        details = result.get("details")
        if isinstance(details, dict) and isinstance(details.get("memories"), list):
            return [x for x in details["memories"] if isinstance(x, dict)]
        return []

    def _invoke(self, tool: str, args: dict) -> Any:
        return invoke_tool(tool=tool, tool_args=args, session_key=self.session_key, config=self.config)

    def clear(self, container_tag: str) -> None:
        ids = list(self._container_ids.get(container_tag, []))

        # Best-effort fallback in case state was partially lost.
        if not ids:
            marker = self._container_marker(container_tag)
            res = self._invoke("memory_recall", {"query": marker, "limit": 200})
            for mem in self._extract_memories(res):
                txt = str(mem.get("text") or "")
                if marker in txt:
                    mid = str(mem.get("id") or "")
                    if mid:
                        ids.append(mid)

        for mid in ids:
            try:
                self._invoke("memory_forget", {"memoryId": mid})
            except Exception:
                # best-effort cleanup only
                pass

        self._container_ids.pop(container_tag, None)

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        marker = self._container_marker(container_tag)
        stored_ids: list[str] = []

        # Store one memory per session for cost/perf stability.
        for session in sessions:
            turns = "\n".join(f"{m.role}: {m.content}" for m in session.messages)
            text = f"{marker} [session:{session.session_id}]\n{turns}"

            res = self._invoke(
                "memory_store",
                {
                    "text": text,
                    "category": "benchmark-ingest",
                    "importance": 0.1,
                },
            )

            details = res.get("details") if isinstance(res, dict) else None
            mid = str(details.get("id") or "") if isinstance(details, dict) else ""
            if mid:
                stored_ids.append(mid)

        self._container_ids[container_tag] = stored_ids
        return {
            "container_tag": container_tag,
            "stored": len(stored_ids),
            "memory_ids": stored_ids,
        }

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        del ingest_result, container_tag
        return None

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        marker = self._container_marker(container_tag)
        recall_limit = max(limit * max(self.recall_limit_factor, 1), limit)

        res = self._invoke(
            "memory_recall",
            {
                "query": f"{query}\n{marker}",
                "limit": recall_limit,
            },
        )

        memories = self._extract_memories(res)
        scoped = [m for m in memories if marker in str(m.get("text") or "")]

        hits: list[SearchHit] = []
        for idx, mem in enumerate(scoped[:limit]):
            text = str(mem.get("text") or "")
            sid = self._session_id_from_text(text)
            mid = str(mem.get("id") or f"memory-{idx}")
            score = float(mem.get("score", 0.0) or 0.0)

            hits.append(
                SearchHit(
                    id=mid,
                    content=text,
                    score=score,
                    metadata={
                        "session_id": sid,
                        "container_tag": container_tag,
                        "memory_id": mid,
                        "category": mem.get("category"),
                    },
                )
            )

        return hits
