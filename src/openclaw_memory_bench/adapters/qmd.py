from __future__ import annotations

import json
import re
import shutil
import subprocess
from typing import Any

from openclaw_memory_bench.protocol import SearchHit, Session

_SESSION_FROM_PATH_RE = re.compile(r"/sessions/([^/]+)\.(?:jsonl|md)(?::\d+:\d+)?$", re.IGNORECASE)


class QmdAdapter:
    """Stub adapter for QMD retrieval (`qmd query --json`).

    This adapter intentionally keeps ingest/clear as no-ops because QMD indexing
    is expected to happen outside this benchmark harness for now.

    Degrade-gracefully policy:
    - if `qmd` is unavailable, `search()` returns an empty hit list.
    - command errors can be made strict via `strict=true` in provider config.
    """

    name = "qmd"

    def __init__(self) -> None:
        self.command_base: list[str] = ["qmd"]
        self.query_extra_args: list[str] = []
        self.timeout_sec = 20
        self.strict = False
        self._available = True
        self._warned_unavailable = False

    def initialize(self, config: dict[str, Any]) -> None:
        cmd = config.get("command_base") or config.get("qmd_cmd")
        if isinstance(cmd, list) and cmd:
            self.command_base = [str(x) for x in cmd]
        elif isinstance(cmd, str) and cmd.strip():
            self.command_base = cmd.split()

        extra_args = config.get("query_extra_args") or config.get("qmd_query_extra_args") or []
        if isinstance(extra_args, list):
            self.query_extra_args = [str(x) for x in extra_args]

        timeout_raw = config.get("timeout_sec") or config.get("qmd_timeout_sec")
        if timeout_raw is not None:
            self.timeout_sec = int(timeout_raw)

        self.strict = bool(config.get("strict") or config.get("qmd_strict") or False)

        exe = self.command_base[0]
        self._available = bool(shutil.which(exe)) if "/" not in exe else True

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        return {
            "ingest": "noop",
            "provider": self.name,
            "container_tag": container_tag,
            "sessions_seen": len(sessions),
            "reason": "qmd index is managed externally in this spike",
        }

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        del ingest_result, container_tag
        return None

    def clear(self, container_tag: str) -> None:
        del container_tag
        return None

    @staticmethod
    def _extract_rows(stdout: str) -> list[dict[str, Any]]:
        raw = stdout.strip()
        if not raw:
            return []

        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            parsed = None

        if isinstance(parsed, dict):
            rows = parsed.get("results")
            return [x for x in rows if isinstance(x, dict)] if isinstance(rows, list) else []

        if isinstance(parsed, list):
            return [x for x in parsed if isinstance(x, dict)]

        rows: list[dict[str, Any]] = []
        for line in raw.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue

            if isinstance(item, dict) and isinstance(item.get("results"), list):
                rows.extend([x for x in item["results"] if isinstance(x, dict)])
            elif isinstance(item, dict):
                rows.append(item)

        return rows

    @staticmethod
    def _extract_session_id(row: dict[str, Any]) -> str | None:
        sid = row.get("session_id")
        if isinstance(sid, str) and sid.strip():
            return sid.strip()

        path = row.get("path")
        if not isinstance(path, str):
            return None

        m = _SESSION_FROM_PATH_RE.search(path)
        if not m:
            return None

        sid = m.group(1).strip()
        return sid or None

    def _build_query_cmd(self, query: str, limit: int) -> list[str]:
        return [
            *self.command_base,
            "query",
            "--json",
            query,
            "--limit",
            str(limit),
            *self.query_extra_args,
        ]

    def _warn_once(self, reason: str) -> None:
        if self._warned_unavailable:
            return
        print(f"  ! qmd adapter fallback: {reason}")
        self._warned_unavailable = True

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        del container_tag

        if not self._available:
            self._warn_once("`qmd` command not found; returning empty results")
            return []

        cmd = self._build_query_cmd(query=query, limit=limit)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout_sec,
                check=False,
            )
        except FileNotFoundError:
            self._available = False
            self._warn_once("`qmd` command missing at runtime; returning empty results")
            return []

        if proc.returncode != 0:
            msg = (
                f"qmd query failed (exit={proc.returncode})"
                f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
            if self.strict:
                raise RuntimeError(msg)
            self._warn_once("qmd query failed; returning empty results (strict=false)")
            return []

        rows = self._extract_rows(proc.stdout)
        hits: list[SearchHit] = []
        for idx, row in enumerate(rows[:limit]):
            snippet = row.get("snippet") or row.get("summary") or row.get("content") or ""
            score = float(row.get("score", 0.0) or 0.0)
            obs_id = str(row.get("id") or row.get("doc_id") or f"qmd-{idx}")
            hits.append(
                SearchHit(
                    id=obs_id,
                    content=str(snippet),
                    score=score,
                    metadata={
                        "provider": self.name,
                        "path": row.get("path"),
                        "session_id": self._extract_session_id(row),
                    },
                )
            )

        return hits
