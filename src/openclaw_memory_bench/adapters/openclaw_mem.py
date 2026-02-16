from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from openclaw_memory_bench.protocol import SearchHit, Session

_SAFE_TAG_RE = re.compile(r"[^a-zA-Z0-9_.-]+")
_FTS_CLEAN_RE = re.compile(r"[^0-9A-Za-z_\u4e00-\u9fff]+")


class OpenClawMemAdapter:
    name = "openclaw-mem"

    def __init__(self) -> None:
        self.db_path: str | None = None
        self.db_root: Path = Path("artifacts/provider-state/openclaw-mem")
        self.command_base: list[str] = ["openclaw-mem"]
        self.extra_env: dict[str, str] = {}

    def initialize(self, config: dict) -> None:
        self.db_path = config.get("db_path")
        db_root = config.get("db_root")
        if db_root:
            self.db_root = Path(db_root)
        self.db_root.mkdir(parents=True, exist_ok=True)

        self.extra_env = {}

        command_base = config.get("command_base")
        if isinstance(command_base, list) and command_base:
            self.command_base = [str(x) for x in command_base]
        elif isinstance(command_base, str) and command_base.strip():
            self.command_base = command_base.split()
        else:
            if shutil.which("openclaw-mem"):
                self.command_base = ["openclaw-mem"]
            else:
                # Portable fallback: require an explicit project path (config or env).
                # This avoids hardcoding host-specific directories.
                project = (
                    config.get("openclaw_mem_project")
                    or os.environ.get("OPENCLAW_MEM_PROJECT")
                    or os.environ.get("OPENCLAW_MEM_PROJECT_DIR")
                )
                if not project:
                    raise RuntimeError(
                        "openclaw-mem adapter requires `openclaw-mem` on PATH, or an explicit project path via "
                        "--openclaw-mem-project / provider_config.openclaw_mem_project / $OPENCLAW_MEM_PROJECT."
                    )

                project = str(project)
                self.command_base = [
                    "uv",
                    "run",
                    "--python",
                    "3.13",
                    "--project",
                    project,
                    "--",
                    "python",
                    "-m",
                    "openclaw_mem",
                ]
                existing = os.environ.get("PYTHONPATH", "")
                self.extra_env["PYTHONPATH"] = f"{project}:{existing}" if existing else project

    def _db_for_container(self, container_tag: str) -> str:
        if self.db_path:
            return self.db_path

        safe = _SAFE_TAG_RE.sub("-", container_tag).strip("-")
        if not safe:
            safe = "default"
        return str(self.db_root / f"{safe}.sqlite")

    @staticmethod
    def _sanitize_fts_query(query: str) -> str:
        cleaned = _FTS_CLEAN_RE.sub(" ", query).strip()
        tokens = [tok for tok in cleaned.split() if tok]
        if not tokens:
            return query.strip()
        if len(tokens) == 1:
            return tokens[0]

        # FTS5 defaults to AND for plain token sequences, which is too strict for
        # natural-language questions. Use OR expression to approximate bag-of-words retrieval.
        return " OR ".join(tokens)

    def _cmd(self, *args: str) -> list[str]:
        return [*self.command_base, *args]

    def _run(self, cmd: list[str]) -> str:
        env = os.environ.copy()
        env.update(self.extra_env)
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
        if proc.returncode != 0:
            raise RuntimeError(
                "command failed: "
                + " ".join(cmd)
                + f"\nstdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc.stdout

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        db_path = self._db_for_container(container_tag)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as fp:
            temp_path = Path(fp.name)
            for session in sessions:
                for msg in session.messages:
                    # Prefix session tag into summary for easier FTS retrieval/debugging.
                    row = {
                        "kind": "benchmark-ingest",
                        "tool_name": "memorybench",
                        "summary": f"[session:{session.session_id}] {msg.content}",
                        "detail": {
                            "container_tag": container_tag,
                            "session_id": session.session_id,
                            "role": msg.role,
                            "source": "openclaw-memory-bench",
                        },
                    }
                    fp.write(json.dumps(row, ensure_ascii=False) + "\n")

        cmd = self._cmd(
            "--db",
            db_path,
            "ingest",
            "--file",
            str(temp_path),
            "--json",
        )
        out = self._run(cmd)
        result = json.loads(out)
        return {"document_ids": result.get("ids", []), "container_tag": container_tag, "db_path": db_path}

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        # local SQLite/FTS path is effectively immediate for now
        return None

    def _get_rows_detail(self, db_path: str, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}

        cmd = self._cmd("--db", db_path, "get", *ids, "--json")
        out = self._run(cmd)
        rows = json.loads(out)
        by_id: dict[str, dict] = {}
        for row in rows:
            by_id[str(row.get("id"))] = row
        return by_id

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        db_path = self._db_for_container(container_tag)

        safe_query = self._sanitize_fts_query(query)

        cmd = self._cmd(
            "--db",
            db_path,
            "search",
            safe_query,
            "--limit",
            str(limit),
            "--json",
        )
        out = self._run(cmd)
        rows = json.loads(out)

        ids = [str(row.get("id")) for row in rows if row.get("id") is not None]
        detail_rows = self._get_rows_detail(db_path, ids)

        hits: list[SearchHit] = []
        for row in rows:
            obs_id = str(row.get("id"))
            full_row = detail_rows.get(obs_id, {})

            detail_raw = full_row.get("detail_json")
            detail = {}
            if isinstance(detail_raw, str) and detail_raw.strip():
                try:
                    detail = json.loads(detail_raw)
                except json.JSONDecodeError:
                    detail = {}

            # Defensive filter by container tag, even though per-container DB is preferred.
            detail_tag = detail.get("container_tag")
            if detail_tag and detail_tag != container_tag:
                continue

            meta = {
                "observation_id": row.get("id"),
                "kind": row.get("kind"),
                "tool_name": row.get("tool_name"),
                "container_tag": detail.get("container_tag", container_tag),
                "session_id": detail.get("session_id"),
                "role": detail.get("role"),
            }
            hits.append(
                SearchHit(
                    id=obs_id,
                    content=row.get("summary") or row.get("snippet") or "",
                    score=float(row.get("score", 0.0) or 0.0),
                    metadata=meta,
                )
            )
        return hits

    def clear(self, container_tag: str) -> None:
        # Isolation strategy: one sqlite file per container tag.
        if self.db_path:
            # explicit DB path mode: keep user-owned DB untouched
            return None

        db = Path(self._db_for_container(container_tag))
        if db.exists():
            db.unlink()
        wal = db.with_name(db.name + "-wal")
        shm = db.with_name(db.name + "-shm")
        if wal.exists():
            wal.unlink()
        if shm.exists():
            shm.unlink()
        return None
