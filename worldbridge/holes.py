"""Chunks a Bedrock world does not save inside the area its player explored.

Bedrock draws far more chunks than it stores: the ones that nothing changed in (or that its own generator can
recompute from the seed) are often missing from the database, so a converted world has holes among the saved chunks.
The target game generates them from the seed when the world is opened; trees and structures that cross a hole's
edge can be cut there.  This only counts them, to say so in the log.
"""

from __future__ import annotations

import struct
from typing import Iterable, Set, Tuple

import numpy as np

from .i18n import tr

Chunk = Tuple[int, int]
REACH = 8          # a missing chunk is a hole when saved chunks lie within this many chunks in all four directions
BLOCK = 64         # the chunks are looked at BLOCK x BLOCK at a time, so a world of far apart villages stays cheap
_VERSION_TAGS = (0x2C, 0x76)       # the chunk version records Bedrock writes for every chunk it saves


def overworld_chunks(path: str) -> Set[Chunk]:
    """The Overworld chunks a Bedrock world has saved."""
    from .bedrock.extra import _db

    db = _db(path)
    out: Set[Chunk] = set()
    try:
        for key, _value in db.iterate():
            k = bytes(key)
            if len(k) == 9 and k[8] in _VERSION_TAGS:
                out.add(struct.unpack_from("<ii", k, 0))
    finally:
        db.close()
    return out


def count_holes(chunks: Iterable[Chunk]) -> int:
    """Missing chunks with saved chunks within ``REACH`` chunks to the west, east, north and south."""
    chunks = set(chunks)
    blocks = {}
    for cx, cz in chunks:
        blocks.setdefault((cx // BLOCK, cz // BLOCK), []).append((cx, cz))
    n = 0
    size = BLOCK + 2 * REACH
    todo = {(bx + dx, bz + dz) for (bx, bz) in blocks for dx in (-1, 0, 1) for dz in (-1, 0, 1)}
    for (bx, bz) in todo:
        x0, z0 = bx * BLOCK - REACH, bz * BLOCK - REACH
        grid = np.zeros((size, size), bool)          # [z, x]
        for dx in range(-1, 2):
            for dz in range(-1, 2):
                for cx, cz in blocks.get((bx + dx, bz + dz), ()):
                    gx, gz = cx - x0, cz - z0
                    if 0 <= gx < size and 0 <= gz < size:
                        grid[gz, gx] = True
        west = np.zeros_like(grid)
        east = np.zeros_like(grid)
        north = np.zeros_like(grid)
        south = np.zeros_like(grid)
        for s in range(1, REACH + 1):
            west[:, s:] |= grid[:, :-s]
            east[:, :-s] |= grid[:, s:]
            north[s:, :] |= grid[:-s, :]
            south[:-s, :] |= grid[s:, :]
        hole = ~grid & west & east & north & south
        core = hole[REACH:REACH + BLOCK, REACH:REACH + BLOCK]
        n += int(core.sum())
    return n


def log_missing_chunks(path: str, progress) -> int:
    """Log how many chunks inside the explored area of a Bedrock world are not saved; returns the number."""
    n = count_holes(overworld_chunks(path))
    if n:
        progress.log(tr("{n} chunks inside the explored area are not saved in the Bedrock world (Bedrock does not "
                        "store every chunk it shows): the target game generates them from the seed when the world is "
                        "opened, so trees and structures can be cut at their edges.", n=n))
    return n
