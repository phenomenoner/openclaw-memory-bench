from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

from openclaw_memory_bench.protocol import SearchHit, Session


class OpenClawMemAdapter:
    name = "openclaw-mem"

    def __init__(self) -> None:
        self.db_path: str | None = None

    def initialize(self, config: dict) -> None:
        self.db_path = config.get("db_path")

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        if not self.db_path:
            raise ValueError("openclaw-mem adapter requires db_path")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fp:
            temp_path = Path(fp.name)
            for session in sessions:
                for msg in session.messages:
                    row = {
                        "kind": "benchmark-ingest",
                        "tool_name": "memorybench",
                        "summary": msg.content,
                        "detail": {
                            "container_tag": container_tag,
                            "session_id": session.session_id,
                            "role": msg.role,
                            "source": "openclaw-memory-bench",
                        },
                    }
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        cmd = [
            "openclaw-mem",
            "--db",
            self.db_path,
            "ingest",
            "--file",
            str(temp_path),
            "--json",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        result = json.loads(proc.stdout)
        return {"document_ids": result.get("ids", []), "container_tag": container_tag}

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        # local SQLite/FTS path is effectively immediate for now
        return None

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        if not self.db_path:
            raise ValueError("openclaw-mem adapter requires db_path")

        cmd = [
            "openclaw-mem",
            "--db",
            self.db_path,
            "search",
            query,
            "--limit",
            str(limit),
            "--json",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=True)
        rows = json.loads(proc.stdout)

        hits: list[SearchHit] = []
        for row in rows:
            detail = {
                "id": row.get("id"),
                "kind": row.get("kind"),
                "tool_name": row.get("tool_name"),
                "container_tag": container_tag,
            }
            hits.append(
                SearchHit(
                    id=str(row.get("id")),
                    content=row.get("summary") or row.get("snippet") or "",
                    score=float(row.get("score", 0.0) or 0.0),
                    metadata=detail,
                )
            )
        return hits

    def clear(self, container_tag: str) -> None:
        # No-op for now. Future: maintain per-container DB for isolation.
        return None
