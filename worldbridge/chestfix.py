"""Rows of chests for the games that pair chests by themselves (Legacy Console Edition, Java up to 1.12).

Modern Java stores which chest a chest is paired with (``type`` left / right / single), so its
storage rooms have rows of double chests side by side.  The older games pair a chest with ANY chest
of the same kind next to it, and draw a double chest only from the half with no chest to its west
or north: in a row of two double chests the second pair has a chest to its west and is never drawn
(invisible chests, contents still there).  Such rows cannot be built in those games, so they never
had to deal with them.

Every group of touching chests that the old game would not read as a plain single or double chest
is paired again two by two along the double chest's axis, and the pairs alternate between chest and
trapped chest, which never join each other, like a checkerboard: every pair is drawn, whatever the
shape of the group, and every chest keeps its own contents.  A single chest, and two chests that already make a proper double chest, are left
as they are.
"""

from __future__ import annotations

from collections import OrderedDict, deque
from typing import Callable, Dict, List, Optional, Set, Tuple

import numpy as np

CHEST, TRAPPED = 54, 146
KINDS = (CHEST, TRAPPED)
_NS = (2, 3)                                   # chest data: 2 north, 3 south, 4 west, 5 east
Cell = Tuple[int, int, int]                    # world x, y, z


class _Snapshot:
    """The blocks of a chunk as they were before ``fix`` changed them."""

    __slots__ = ("cx", "cz", "blocks", "data")

    def __init__(self, c):
        self.cx, self.cz = c.cx, c.cz
        self.blocks, self.data = c.blocks.copy(), c.data


class ChestRows:
    def __init__(self, read: Callable[[int, int, int], object], cache: int = 16):
        self.read = read                        # (dim, cx, cz) -> numeric chunk or None
        self._cache: "OrderedDict[Tuple[int, int, int], object]" = OrderedDict()
        self._size = cache
        self.changed = 0

    # ------------------------------------------------------------------ world access
    def _chunk(self, dim: int, cx: int, cz: int):
        key = (dim, cx, cz)
        if key in self._cache:
            self._cache.move_to_end(key)
            return self._cache[key]
        try:
            c = self.read(dim, cx, cz)
        except Exception:  # noqa: BLE001
            c = None
        self._cache[key] = c
        if len(self._cache) > self._size:
            self._cache.popitem(last=False)
        return c

    def _block(self, dim: int, here, x: int, y: int, z: int) -> Tuple[int, int]:
        cx, cz = x >> 4, z >> 4
        c = here if (cx, cz) == (here.cx, here.cz) else self._chunk(dim, cx, cz)
        if c is None or not 0 <= y < c.blocks.shape[0]:
            return 0, 0
        return int(c.blocks[y, z & 15, x & 15]), int(c.data[y, z & 15, x & 15])

    # ------------------------------------------------------------------ fixing a chunk
    def fix(self, dim: int, c) -> int:
        """Changes, in chunk ``c``, the chests of rows the old game would not draw; returns how many.
        The groups are always found in the world as it was read (this chunk before any change, its
        neighbours read again): a group across a chunk border gets the same pairs from both sides,
        whatever the order (or the process) the chunks are fixed in."""
        ys, zs, xs = np.nonzero(np.isin(c.blocks, KINDS))
        if not len(ys):
            return 0
        here = _Snapshot(c)
        done: Set[Cell] = set()
        n = 0
        for y, z, x in zip(ys.tolist(), zs.tolist(), xs.tolist()):
            cell = (c.cx * 16 + x, y, c.cz * 16 + z)
            if cell in done:
                continue
            kind = int(here.blocks[y, z, x])
            group, facing = self._group(dim, here, cell, kind)
            done |= group
            if self._plain(group, facing):
                continue
            for (wx, wy, wz), new in self._plan(group, facing, kind).items():
                if (wx >> 4, wz >> 4) == (c.cx, c.cz) and c.blocks[wy, wz & 15, wx & 15] != new:
                    c.blocks[wy, wz & 15, wx & 15] = new
                    n += 1
        self.changed += n
        return n

    def _group(self, dim, c, start: Cell, kind: int, limit: int = 4096):
        """The chests of ``kind`` touching ``start`` sideways (the whole group, across chunks)."""
        group = {start}
        facing = {}
        todo = deque([start])
        while todo and len(group) < limit:
            x, y, z = todo.popleft()
            facing[(x, y, z)] = self._block(dim, c, x, y, z)[1]
            for nx, nz in ((x - 1, z), (x + 1, z), (x, z - 1), (x, z + 1)):
                if (nx, y, nz) not in group and self._block(dim, c, nx, y, nz)[0] == kind:
                    group.add((nx, y, nz))
                    todo.append((nx, y, nz))
        return group, facing

    @staticmethod
    def _plain(group: Set[Cell], facing: Dict[Cell, int]) -> bool:
        """A single chest, or two chests side by side facing the same way: what the game builds."""
        if len(group) == 1:
            return True
        if len(group) != 2:
            return False
        a, b = sorted(group)
        fa, fb = facing.get(a, 2), facing.get(b, 2)
        if fa != fb:
            return False
        along_x = a[2] == b[2]
        return along_x == (fa in _NS)

    @staticmethod
    def _plan(group: Set[Cell], facing: Dict[Cell, int], kind: int) -> Dict[Cell, int]:
        """Chest / trapped chest on a lattice: pairs two by two along the double chest's axis (from the
        group's first chest, so aligned rows keep their pairs), alternating by pair and by row.  Every
        chest then touches at most one chest of its kind, its partner, beside it: whatever the shape."""
        ns = [c for c in group if facing.get(c, 2) in _NS]
        ew = [c for c in group if facing.get(c, 2) not in _NS]
        ox = min(c[0] for c in ns) & 1 if ns else 0
        oz = min(c[2] for c in ew) & 1 if ew else 0
        other = TRAPPED if kind == CHEST else CHEST
        out: Dict[Cell, int] = {}
        for (x, y, z) in group:
            if facing.get((x, y, z), 2) in _NS:           # facing north / south: pairs along x
                g = ((x - ox) >> 1) + z
            else:                                         # facing west / east: pairs along z
                g = ((z - oz) >> 1) + x
            out[(x, y, z)] = kind if g % 2 == 0 else other
        return out
