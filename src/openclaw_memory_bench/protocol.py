from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass
class SessionMessage:
    role: str
    content: str
    ts: str | None = None


@dataclass
class Session:
    session_id: str
    messages: list[SessionMessage]
    metadata: dict


@dataclass
class SearchHit:
    id: str
    content: str
    score: float
    metadata: dict


class MemoryAdapter(Protocol):
    """Adapter protocol for OpenClaw memory-layer plugins."""

    name: str

    def initialize(self, config: dict) -> None: ...

    def ingest(self, sessions: Sequence[Session], container_tag: str) -> dict: ...

    def await_indexing(self, ingest_result: dict, container_tag: str) -> None: ...

    def search(self, query: str, container_tag: str, limit: int = 10) -> list[SearchHit]: ...

    def clear(self, container_tag: str) -> None: ...
