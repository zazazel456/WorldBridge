"""Work spread over every core, results in order.

The heavy steps of a conversion (the ring's terrain, reading and writing chunks) are pure Python and
numpy: threads would wait on each other (the GIL), so the work goes to worker processes.  They are
started with ``fork`` and inherit the state the work needs (a generator, the source world, the ring's
field) instead of receiving it: only the items and the results travel between the processes.

``ordered_map(fn, state, items)`` yields ``fn(state, item)`` for every item, in the items' order,
exactly as the plain loop would: the output of a conversion does not depend on the number of cores.
Few items, one core, ``WORLDBRIDGE_WORKERS=1``, or a system where processes cannot be started: the
same loop runs in this process.  At most a few batches per worker are in flight, so the results
waiting to be consumed (and the items not yet sent, when ``items`` is an iterator) stay few, whatever
the number of items.
"""

from __future__ import annotations

import itertools
import os
from collections import deque
from typing import Any, Callable, Iterable, Iterator, List, Optional

# the calls in progress, by token: (function, state).  A worker is forked while the call that
# started it is registered, so it finds its own entry; calls made at the same time by other
# threads (the map's loader and a conversion in the GUI) each have their own, and never see
# each other's function or state.
_CALLS: dict = {}
_TOKENS = itertools.count(1)
_IN_WORKER = False


def workers() -> int:
    """Worker processes to use: ``WORLDBRIDGE_WORKERS`` or the cores of the machine."""
    try:
        n = int(os.environ.get("WORLDBRIDGE_WORKERS", "0") or 0)
    except ValueError:
        n = 0
    if n <= 0:
        try:
            n = len(os.sched_getaffinity(0))
        except (AttributeError, OSError):
            n = os.cpu_count() or 1
    return max(1, n)


def can_fork() -> bool:
    import multiprocessing as mp

    return "fork" in mp.get_all_start_methods()


def process_context(leveldb: bool = False):
    """How worker processes start: forked (they inherit the state the work needs), or, when they open
    a LevelDB (Bedrock), from the fork server, a process that never opened one.  A forked copy of a
    process that did (the map of a Bedrock world, the listing of its chunks) inherits LevelDB's
    background thread as running without the thread itself, and waits for it forever when it closes
    its database; those workers get their state as an argument instead."""
    import multiprocessing as mp

    return mp.get_context("forkserver" if leveldb else "fork")


def in_worker() -> bool:
    """True inside a worker process of ``ordered_map``."""
    return _IN_WORKER


def _mark_worker() -> None:
    global _IN_WORKER
    _IN_WORKER = True


def _run_batch(token: int, batch: List[Any]) -> List[Any]:
    fn, state = _CALLS[token]
    return [fn(state, item) for item in batch]


def ordered_map(fn: Callable[[Any, Any], Any], state: Any, items: Iterable[Any], batch: int = 8,
                min_items: int = 32, n_workers: Optional[int] = None) -> Iterator[Any]:
    """``fn(state, item)`` for every item, in order.  ``fn`` must be a module level function (it is
    looked up by name in the workers) and must not depend on anything the parent changes after this
    call starts: the workers see the state as it was when they were started.  ``items`` may be an
    iterator (read lazily, a few batches ahead of the results); ``min_items`` only counts for lists."""
    n = n_workers or workers()
    small = hasattr(items, "__len__") and len(items) < min_items
    it = iter(items)
    if n < 2 or small or not can_fork():
        for item in it:
            yield fn(state, item)
        return
    import concurrent.futures as cf
    import multiprocessing as mp
    from concurrent.futures.process import BrokenProcessPool

    token = next(_TOKENS)
    _CALLS[token] = (fn, state)            # before the first submit: the workers are forked with it
    try:
        yield from _pooled(fn, state, it, token, n, batch, cf, mp, BrokenProcessPool)
    finally:
        _CALLS.pop(token, None)


def _pooled(fn, state, it, token, n, batch, cf, mp, BrokenProcessPool) -> Iterator[Any]:
    try:
        pool = cf.ProcessPoolExecutor(max_workers=n, mp_context=mp.get_context("fork"), initializer=_mark_worker)
    except (OSError, ValueError):
        for item in it:
            yield fn(state, item)
        return
    pending: deque = deque()                        # (future, its items), in order
    window = n * 3

    def refill():
        while len(pending) < window:
            chunk = list(itertools.islice(it, batch))
            if not chunk:
                return
            pending.append((pool.submit(_run_batch, token, chunk), chunk))

    try:
        refill()                                    # the workers start (fork) here (or as they are needed)
        while pending:
            res = pending[0][0].result()
            pending.popleft()
            yield from res
            refill()
    except BrokenProcessPool:
        pool.shutdown(wait=False, cancel_futures=True)
        # no worker processes (killed, out of memory...): the rest in this process, from the first
        # batch not yet given back
        left = [item for _f, chunk in pending for item in chunk]
        pending.clear()
        for item in itertools.chain(left, it):
            yield fn(state, item)
        return
    except BaseException:
        pool.shutdown(wait=False, cancel_futures=True)
        raise
    pool.shutdown(wait=True)
