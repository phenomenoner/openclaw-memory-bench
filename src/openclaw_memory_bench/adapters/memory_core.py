from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from openclaw_memory_bench.protocol import SearchHit, Session

_SAFE_TAG_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_SESSION_ID_RE = re.compile(r"session_id\s*:\s*([a-zA-Z0-9_.-]+)", re.IGNORECASE)


class MemoryCoreAdapter:
    """Adapter for OpenClaw built-in memory-core CLI.

    Isolation strategy:
    - each benchmark run uses a dedicated OpenClaw profile (default: membench-memory-core)
    - profile memory state is hard-reset once at initialize (fast repeatability)
    - each benchmark question ingests files tagged by unique container_tag
    - search is post-filtered to current container files/snippets

    Performance strategy:
    - avoid per-question `memory index --force` (incremental index by default)
    - retry indexing with adaptive timeout on transient slow paths
    - optional ingest truncation to stabilize very long sessions
    """

    name = "memory-core"

    def __init__(self) -> None:
        self.openclaw_bin = "openclaw"
        self.profile = "membench-memory-core"
        self.agent_id = "main"
        self.workspace_dir: Path | None = None
        self.state_dir: Path | None = None

        self.timeout_sec = 120
        self.force_reindex = False
        self.index_retries = 1
        self.index_retry_backoff_sec = 2.0
        self.search_limit_factor = 8

        # ingest shaping (set <=0 to disable a limit)
        self.max_messages_per_session = 80
        self.max_message_chars = 800
        self.max_chars_per_session = 12000

        self._container_files: dict[str, list[str]] = {}
        self._path_to_session_id: dict[str, str] = {}

    def initialize(self, config: dict) -> None:
        self.openclaw_bin = str(config.get("openclaw_bin") or "openclaw")
        self.profile = str(config.get("profile") or "membench-memory-core")
        self.agent_id = str(config.get("agent_id") or "main")

        self.timeout_sec = int(config.get("timeout_sec") or 120)
        self.force_reindex = bool(config.get("force_reindex", False))
        self.index_retries = int(config.get("index_retries") or 1)
        self.index_retry_backoff_sec = float(config.get("index_retry_backoff_sec") or 2.0)
        self.search_limit_factor = int(config.get("search_limit_factor") or 8)

        self.max_messages_per_session = int(config.get("max_messages_per_session") or 80)
        self.max_message_chars = int(config.get("max_message_chars") or 800)
        self.max_chars_per_session = int(config.get("max_chars_per_session") or 12000)

        default_workspace = Path.home() / ".openclaw" / f"workspace-{self.profile}"
        default_state = Path.home() / f".openclaw-{self.profile}"

        self.workspace_dir = Path(str(config.get("workspace_dir") or default_workspace))
        self.state_dir = Path(str(config.get("state_dir") or default_state))

        (self.workspace_dir / "memory").mkdir(parents=True, exist_ok=True)

        # Start each run clean once; avoid per-question hard reset.
        self._hard_reset_state()

    @staticmethod
    def _safe_session_id(session_id: str) -> str:
        safe = _SAFE_TAG_RE.sub("-", session_id).strip("-")
        return safe or "unknown"

    @staticmethod
    def _safe_container_tag(container_tag: str) -> str:
        safe = _SAFE_TAG_RE.sub("-", container_tag).strip("-")
        return safe or "container"

    @staticmethod
    def _extract_json(stdout: str) -> Any:
        payload = stdout.strip()
        if not payload:
            raise RuntimeError("empty output while expecting json")

        try:
            return json.loads(payload)
        except json.JSONDecodeError:
            pass

        # OpenClaw may prepend plugin logs before JSON; parse from the last JSON-like start.
        starts = [i for i, ch in enumerate(payload) if ch in "[{"]
        for i in reversed(starts):
            candidate = payload[i:].strip()
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

        raise RuntimeError(f"failed to parse json from output:\n{stdout}")

    def _cmd(self, *args: str) -> list[str]:
        return [self.openclaw_bin, "--profile", self.profile, *args]

    def _run(self, cmd: list[str], *, timeout_sec: int | None = None) -> str:
        env = os.environ.copy()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_sec or self.timeout_sec,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "command failed: "
                + " ".join(cmd)
                + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc.stdout

    def _hard_reset_state(self) -> None:
        if self.workspace_dir is None or self.state_dir is None:
            raise RuntimeError("adapter not initialized")

        mem_dir = self.workspace_dir / "memory"
        if mem_dir.exists():
            for item in mem_dir.iterdir():
                if item.is_file() or item.is_symlink():
                    item.unlink(missing_ok=True)
                else:
                    shutil.rmtree(item, ignore_errors=True)
        else:
            mem_dir.mkdir(parents=True, exist_ok=True)

        state_mem = self.state_dir / "memory"
        if state_mem.exists():
            for p in state_mem.glob("main.sqlite*"):
                p.unlink(missing_ok=True)

        self._container_files.clear()
        self._path_to_session_id.clear()

    @staticmethod
    def _select_messages(messages: list, max_messages: int) -> list:
        if max_messages <= 0 or len(messages) <= max_messages:
            return messages
        head = max_messages // 2
        tail = max_messages - head
        if tail <= 0:
            return messages[:max_messages]
        return [*messages[:head], *messages[-tail:]]

    @staticmethod
    def _truncate_text(text: str, max_chars: int) -> str:
        if max_chars <= 0 or len(text) <= max_chars:
            return text
        return text[:max_chars] + " …"

    def clear(self, container_tag: str) -> None:
        if self.workspace_dir is None:
            raise RuntimeError("adapter not initialized")

        paths = self._container_files.pop(container_tag, [])
        for path in paths:
            try:
                Path(path).unlink(missing_ok=True)
            except Exception:
                pass
            self._path_to_session_id.pop(path, None)

    def _index(self, *, force: bool, timeout_sec: int) -> None:
        cmd = self._cmd(
            "memory",
            "index",
            "--agent",
            self.agent_id,
        )
        if force:
            cmd.append("--force")
        self._run(cmd, timeout_sec=timeout_sec)

    def _index_with_retry(self, sessions_count: int) -> None:
        attempts = max(1, self.index_retries + 1)
        force = self.force_reindex
        last_error: Exception | None = None

        # Scale timeout mildly with ingest size.
        base_timeout = self.timeout_sec
        ingest_bonus = max(0, sessions_count - 1) * 2

        for attempt in range(attempts):
            timeout = base_timeout + ingest_bonus + (attempt * 30)
            try:
                self._index(force=force, timeout_sec=timeout)
                return
            except Exception as e:
                last_error = e
                msg = str(e).lower()
                # First timeout on force mode: fall back to non-force incremental mode.
                if "timed out" in msg and force:
                    force = False
                if attempt + 1 >= attempts:
                    break
                sleep_s = self.index_retry_backoff_sec * (attempt + 1)
                time.sleep(sleep_s)

        assert last_error is not None
        raise last_error

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        if self.workspace_dir is None:
            raise RuntimeError("adapter not initialized")

        mem_dir = self.workspace_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)

        files: list[str] = []
        safe_ct = self._safe_container_tag(container_tag)

        for session in sessions:
            safe_sid = self._safe_session_id(session.session_id)
            path = mem_dir / f"session-{safe_ct}-{safe_sid}.md"

            lines = [
                f"# Session {session.session_id}",
                f"session_id: {session.session_id}",
                f"container_tag: {container_tag}",
                "",
            ]

            selected = self._select_messages(session.messages, self.max_messages_per_session)
            chars_budget = self.max_chars_per_session
            dropped = False

            for msg in selected:
                body = self._truncate_text(str(msg.content), self.max_message_chars)
                line = f"- {msg.role}: {body}"
                if chars_budget > 0 and len(line) > chars_budget:
                    dropped = True
                    break
                lines.append(line)
                if chars_budget > 0:
                    chars_budget -= len(line)

            if dropped:
                lines.append("- ... (truncated for benchmark stability)")

            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            path_str = str(path)
            files.append(path_str)
            self._path_to_session_id[path_str] = session.session_id

        self._container_files[container_tag] = files
        self._index_with_retry(len(sessions))

        return {
            "container_tag": container_tag,
            "files": files,
            "sessions_ingested": len(sessions),
            "force_reindex": self.force_reindex,
        }

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        del ingest_result, container_tag
        return None

    @staticmethod
    def _session_id_from_row(path: str | None, snippet: str | None) -> str | None:
        if path:
            name = Path(path).name
            if name.startswith("session-") and name.endswith(".md") and "container_tag:" not in (snippet or ""):
                # Legacy filename format: session-<session_id>.md
                return name[len("session-") : -len(".md")]

        if snippet:
            m = _SESSION_ID_RE.search(snippet)
            if m:
                return m.group(1)

        return None

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        scoped_query = f"{query}\ncontainer_tag: {container_tag}"
        max_results = max(limit * max(self.search_limit_factor, 1), limit)

        out = self._run(
            self._cmd(
                "memory",
                "search",
                scoped_query,
                "--json",
                "--max-results",
                str(max_results),
                "--min-score",
                "0",
                "--agent",
                self.agent_id,
            )
        )
        payload = self._extract_json(out)
        rows = payload.get("results", []) if isinstance(payload, dict) else []

        allowed_paths = set(self._container_files.get(container_tag, []))

        hits: list[SearchHit] = []
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            path_str = str(path) if isinstance(path, str) else None
            snippet = str(row.get("snippet") or "")

            in_scope = False
            if path_str and path_str in allowed_paths:
                in_scope = True
            elif f"container_tag: {container_tag}" in snippet:
                in_scope = True

            if not in_scope:
                continue

            session_id = self._path_to_session_id.get(path_str or "")
            if not session_id:
                session_id = self._session_id_from_row(path_str, snippet)

            obs_id = f"{path or 'memory-core'}:{idx}:{row.get('startLine', 0)}"

            hits.append(
                SearchHit(
                    id=obs_id,
                    content=snippet,
                    score=float(row.get("score", 0.0) or 0.0),
                    metadata={
                        "path": path,
                        "source": row.get("source"),
                        "start_line": row.get("startLine"),
                        "end_line": row.get("endLine"),
                        "session_id": session_id,
                    },
                )
            )

            if len(hits) >= limit:
                break

        return hits
