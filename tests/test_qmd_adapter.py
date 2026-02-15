import json
import subprocess
from pathlib import Path

from openclaw_memory_bench.adapters.qmd import QmdAdapter


def test_extract_rows_supports_dict_results_shape() -> None:
    out = json.dumps({"results": [{"id": "x1"}, {"id": "x2"}]})
    rows = QmdAdapter._extract_rows(out)
    assert [r["id"] for r in rows] == ["x1", "x2"]


def test_search_degrades_gracefully_when_qmd_missing(monkeypatch) -> None:
    adapter = QmdAdapter()
    adapter.initialize({"qmd_cmd": ["/usr/local/bin/qmd"]})

    def _missing(*args, **kwargs):
        raise FileNotFoundError("qmd not found")

    monkeypatch.setattr(subprocess, "run", _missing)

    hits = adapter.search("hello", container_tag="t1", limit=5)
    assert hits == []


def test_search_maps_session_id_from_path(monkeypatch) -> None:
    adapter = QmdAdapter()
    adapter.initialize({"qmd_cmd": ["/usr/local/bin/qmd"]})

    payload = {
        "results": [
            {
                "id": "doc-1",
                "path": "/tmp/memory/sessions/s-mix-3.md:1:1",
                "snippet": "remembered text",
                "score": 0.88,
            }
        ]
    }

    def _ok(*args, **kwargs):
        return subprocess.CompletedProcess(args=["qmd"], returncode=0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(subprocess, "run", _ok)

    hits = adapter.search("hello", container_tag="t1", limit=5)
    assert len(hits) == 1
    assert hits[0].id == "doc-1"
    assert hits[0].metadata["session_id"] == "s-mix-3"
    assert hits[0].score == 0.88


def test_search_maps_non_empty_fixture_payload(monkeypatch) -> None:
    adapter = QmdAdapter()
    adapter.initialize({"qmd_cmd": ["/usr/local/bin/qmd"]})

    fixture_path = Path(__file__).parent / "fixtures" / "qmd" / "non_empty_results.json"
    fixture_stdout = fixture_path.read_text(encoding="utf-8")

    def _ok(*args, **kwargs):
        return subprocess.CompletedProcess(args=["qmd"], returncode=0, stdout=fixture_stdout, stderr="")

    monkeypatch.setattr(subprocess, "run", _ok)

    hits = adapter.search("hello", container_tag="t1", limit=3)
    assert [h.id for h in hits] == ["doc-1", "doc-2", "doc-3"]
    assert [h.metadata["session_id"] for h in hits] == ["s-alpha-1", "s-beta-9", "s-gamma-2"]
    assert [h.content for h in hits] == ["alpha snippet", "beta summary", "gamma content"]
    assert [h.score for h in hits] == [0.91, 0.47, 0.0]
