from .memory_core import MemoryCoreAdapter
from .openclaw_mem import OpenClawMemAdapter
from .memu_engine import MemuEngineAdapter


def available_adapters() -> dict[str, type]:
    return {
        "openclaw-mem": OpenClawMemAdapter,
        "memu-engine": MemuEngineAdapter,
        "memory-core": MemoryCoreAdapter,
    }
