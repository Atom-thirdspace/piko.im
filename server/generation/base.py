from dataclasses import dataclass
from typing import Tuple

REGISTRY = {}

@dataclass(frozen=True)
class Draft:
    slug: str
    title: str
    topic: str
    difficulty: str
    xp: int
    statement: str
    inputs: Tuple[str, ...]
    reference_source: str
    reference_language: str = "python"
    hints: Tuple[Tuple[str, int], ...] = ()      # (body, cost_xp)
    sample_count: int = 2
    time_limit_sec: float = 2.0
    memory_mb: int = 256

def generator(name):
    def wrap(fn):
        REGISTRY[name] = fn
        return fn
    return wrap