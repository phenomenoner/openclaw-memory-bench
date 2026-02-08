from __future__ import annotations

from openclaw_memory_bench.protocol import SearchHit, Session


class MemuEngineAdapter:
    """Scaffold adapter for https://github.com/duxiaoxiong/memu-engine-for-OpenClaw.

    TODO:
    - Confirm CLI/API contract.
    - Implement ingest/search lifecycle.
    """

    name = "memu-engine"

    def initialize(self, config: dict) -> None:
        self.config = config

    def ingest(self, sessions: list[Session], container_tag: str) -> dict:
        raise NotImplementedError("memu-engine adapter not implemented yet")

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None:
        return None

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]:
        raise NotImplementedError("memu-engine adapter not implemented yet")

    def clear(self, container_tag: str) -> None:
        return None
