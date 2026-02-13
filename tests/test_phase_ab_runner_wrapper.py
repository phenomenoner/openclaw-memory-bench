from __future__ import annotations

import subprocess
from pathlib import Path


def test_phase_ab_wrapper_errors_on_missing_dataset() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "run_lancedb_vs_openclaw_mem_assisted.sh"

    proc = subprocess.run(
        [str(script), "--dataset", "does/not/exist.json"],
        cwd=repo_root,
        check=False,
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 2
    assert "dataset not found" in proc.stderr.lower()
