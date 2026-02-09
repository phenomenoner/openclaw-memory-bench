from __future__ import annotations

import json
from pathlib import Path

from openclaw_memory_bench.manifest import build_retrieval_manifest, sanitize_config


def test_sanitize_config_redacts_tokens() -> None:
    cfg = {
        "gateway_token": "abc",
        "api_key": "xyz",
        "db_root": "artifacts/db",
    }
    out = sanitize_config(cfg)
    assert out["gateway_token"] == "***REDACTED***"
    assert out["api_key"] == "***REDACTED***"
    assert out["db_root"] == "artifacts/db"


def test_build_retrieval_manifest_includes_dataset_meta(tmp_path: Path) -> None:
    ds = tmp_path / "mini.json"
    ds.write_text('{"name":"mini","questions":[]}', encoding="utf-8")

    meta = {
        "schema": "openclaw-memory-bench/dataset-meta/v0.1",
        "benchmark": "longmemeval",
        "sources": ["https://example.test/longmemeval.json"],
    }
    meta_path = ds.with_name(f"{ds.name}.meta.json")
    meta_path.write_text(json.dumps(meta), encoding="utf-8")

    manifest = build_retrieval_manifest(
        run_id="run-1",
        provider="memu-engine",
        provider_config={"gateway_token": "secret", "session_key": "main"},
        dataset_path=ds,
        dataset_name="mini",
        top_k=5,
        limit=10,
        sample_size=7,
        sample_seed=99,
        skip_ingest=True,
        fail_fast=False,
        repo_dir=tmp_path,
    )

    assert manifest["dataset"]["meta"]["benchmark"] == "longmemeval"
    assert manifest["provider"]["config"]["gateway_token"] == "***REDACTED***"
    assert manifest["dataset"]["sha256"]
    assert manifest["parameters"]["sample_size"] == 7
    assert manifest["parameters"]["sample_seed"] == 99
