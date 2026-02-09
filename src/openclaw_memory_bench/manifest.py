from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__

_SECRET_HINTS = ("token", "secret", "password", "apikey", "api_key")


def _now_utc() -> str:
    return datetime.now(UTC).isoformat()


def _looks_secret(key: str) -> bool:
    k = key.lower()
    return any(h in k for h in _SECRET_HINTS)


def sanitize_config(config: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in config.items():
        if _looks_secret(key):
            out[key] = "***REDACTED***"
            continue
        out[key] = value
    return out


def file_sha256(path: str | Path) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def read_dataset_meta(dataset_path: str | Path) -> dict[str, Any] | None:
    p = Path(dataset_path)
    sidecar = p.with_name(f"{p.name}.meta.json")
    if not sidecar.exists():
        return None

    raw = json.loads(sidecar.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return None
    return raw


def resolve_git_commit(repo_dir: str | Path) -> str | None:
    try:
        cp = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(repo_dir),
            capture_output=True,
            text=True,
            check=True,
        )
        commit = cp.stdout.strip()
        return commit or None
    except Exception:
        return None


def build_retrieval_manifest(
    *,
    run_id: str,
    provider: str,
    provider_config: dict[str, Any],
    dataset_path: str | Path,
    dataset_name: str,
    top_k: int,
    limit: int | None,
    skip_ingest: bool,
    fail_fast: bool,
    preindex_once: bool = False,
    repo_dir: str | Path,
    sample_size: int | None = None,
    sample_seed: int | None = None,
) -> dict[str, Any]:
    p = Path(dataset_path)
    dataset_meta = read_dataset_meta(p)

    return {
        "schema": "openclaw-memory-bench/run-manifest/v0.2",
        "track": "retrieval",
        "run_id": run_id,
        "created_at_utc": _now_utc(),
        "toolkit": {
            "name": "openclaw-memory-bench",
            "version": __version__,
            "git_commit": resolve_git_commit(repo_dir),
        },
        "provider": {
            "name": provider,
            "config": sanitize_config(provider_config),
        },
        "dataset": {
            "name": dataset_name,
            "path": str(p.resolve()),
            "sha256": file_sha256(p),
            "meta": dataset_meta,
        },
        "parameters": {
            "top_k": top_k,
            "limit": limit,
            "sample_size": sample_size,
            "sample_seed": sample_seed,
            "skip_ingest": skip_ingest,
            "preindex_once": preindex_once,
            "fail_fast": fail_fast,
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "executable": sys.executable,
        },
    }
