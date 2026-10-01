"""Counters for the conversion report (unknown ids, dropped entities, spilled items...)."""

from __future__ import annotations

from collections import Counter
from typing import Dict, List, Optional

_COUNTERS: Counter = Counter()
_CAPTURE: List[Counter] = []


def add(key: str, n: int = 1) -> None:
    (_CAPTURE[-1] if _CAPTURE else _COUNTERS)[key] += n


def inc(key: str) -> None:
    add(key, 1)


def begin_capture() -> None:
    """Counters of a chunk that may be converted more than once (as a neighbour) are kept apart
    and merged only when the chunk itself is written."""
    _CAPTURE.append(Counter())


def end_capture() -> Counter:
    return _CAPTURE.pop() if _CAPTURE else Counter()


def merge(c: Optional[Dict[str, int]]) -> None:
    if c:
        _COUNTERS.update(c)


def snapshot() -> Dict[str, int]:
    return dict(sorted(_COUNTERS.items()))


def get(key: str) -> int:
    return _COUNTERS.get(key, 0)


def reset() -> None:
    _COUNTERS.clear()
    _CAPTURE.clear()
