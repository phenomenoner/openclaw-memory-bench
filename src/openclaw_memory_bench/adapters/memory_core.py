from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from openclaw_memory_bench.protocol import SearchHit, Session

_SAFE_TAG_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_SESSION_ID_RE = re.compile(r"session_id\s*:\s*([a-zA-Z0-9_.-]+)", re.IGNORECASE)


class MemoryCoreAdapter:
    """Adapter for OpenClaw built-in memory-core CLI.

    Isolation strategy:
    - each benchmark run uses a dedicated OpenClaw profile (default: membench-memory-core)
    - each benchmark question clears profile memory state before ingest
    - generated markdown lives under ~/.openclaw/workspace-<profile>/memory
    """

    name = "memory-core"

    def __init__(self) -> None:
        self.openclaw_bin = "openclaw"
        self.profile = "membench-memory-core"
        self.agent_id = "main"
        self.workspace_dir: Path | None = None
        self.state_dir: Path | None = None
        self.timeout_sec = 120

    def initialize(self, config: dict) -> None:
        self.openclaw_bin = str(config.get("openclaw_bin") or "openclaw")
        self.profile = str(config.get("profile") or "membench-memory-core")
        self.agent_id = str(config.get("agent_id") or "main")
        self.timeout_sec = int(config.get("timeout_sec") or 120)

        default_workspace = Path.home() / ".openclaw" / f"workspace-{self.profile}"
        default_state = Path.home() / f".openclaw-{self.profile}"

        self.workspace_dir = Path(str(config.get("workspace_dir") or default_workspace))
        self.state_dir = Path(str(config.get("state_dir") or default_state))

        (self.workspace_dir / "memory").mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe_session_id(session_id: str) -> str:
        safe = _SAFE_TAG_RE.sub("-", session_id).strip("-")
        return safe or "unknown"

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

    def _run(self, cmd: list[str]) -> str:
        env = os.environ.copy()
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=self.timeout_sec,
            env=env,
        )
        if proc.returncode != 0:
            raise RuntimeError(
                "command failed: "
                + " ".join(cmd)
                + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc.stdout

    def clear(self, container_tag: str) -> None:
        del container_tag
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

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        if self.workspace_dir is None:
            raise RuntimeError("adapter not initialized")

        mem_dir = self.workspace_dir / "memory"
        mem_dir.mkdir(parents=True, exist_ok=True)

        files: list[str] = []
        for session in sessions:
            safe_sid = self._safe_session_id(session.session_id)
            path = mem_dir / f"session-{safe_sid}.md"

            lines = [
                f"# Session {session.session_id}",
                f"session_id: {session.session_id}",
                f"container_tag: {container_tag}",
                "",
            ]
            for msg in session.messages:
                lines.append(f"- {msg.role}: {msg.content}")

            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            files.append(str(path))

        self._run(
            self._cmd(
                "memory",
                "index",
                "--force",
                "--agent",
                self.agent_id,
            )
        )

        return {
            "container_tag": container_tag,
            "files": files,
            "sessions_ingested": len(sessions),
        }

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        del ingest_result, container_tag
        return None

    @staticmethod
    def _session_id_from_row(path: str | None, snippet: str | None) -> str | None:
        if path:
            name = Path(path).name
            if name.startswith("session-") and name.endswith(".md"):
                return name[len("session-") : -len(".md")]

        if snippet:
            m = _SESSION_ID_RE.search(snippet)
            if m:
                return m.group(1)

        return None

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        del container_tag
        out = self._run(
            self._cmd(
                "memory",
                "search",
                query,
                "--json",
                "--max-results",
                str(limit),
                "--min-score",
                "0",
                "--agent",
                self.agent_id,
            )
        )
        payload = self._extract_json(out)
        rows = payload.get("results", []) if isinstance(payload, dict) else []

        hits: list[SearchHit] = []
        for idx, row in enumerate(rows, start=1):
            if not isinstance(row, dict):
                continue
            path = row.get("path")
            snippet = row.get("snippet")
            session_id = self._session_id_from_row(
                str(path) if isinstance(path, str) else None,
                str(snippet) if isinstance(snippet, str) else None,
            )
            obs_id = f"{path or 'memory-core'}:{idx}:{row.get('startLine', 0)}"

            hits.append(
                SearchHit(
                    id=obs_id,
                    content=str(snippet or ""),
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

        return hits
