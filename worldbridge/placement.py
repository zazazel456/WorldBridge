"""Which chunk an entity is stored in.

The games load an entity with the chunk it is stored in and check that its position is inside that chunk:
Java 1.12 and newer log "Wrong location! (0, -2) should be (-1, -2)" and drop the mob.  Bedrock stores an
actor with the chunk it was loaded with, so a world can hold mobs that walked into the next chunk - and a
conversion that shifts positions (a moved or lowered world, a different sea level) moves others over a
chunk border.  Every writer puts each entity in the chunk of its final position.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Tuple

Chunk = Tuple[int, int]
Key = Tuple[int, int, int]


def chunk_of(pos) -> Optional[Chunk]:
    """The chunk (cx, cz) of a position (x, y, z) - floor, so x = -0.5 is in chunk -1 (None: no usable position)."""
    try:
        x, z = float(pos[0]), float(pos[2])
    except (TypeError, ValueError, IndexError, KeyError):
        return None
    if not (math.isfinite(x) and math.isfinite(z)):
        return None
    return math.floor(x / 16.0), math.floor(z / 16.0)


def clamp_pos(pos, cx: int, cz: int):
    """``pos`` moved to the nearest point inside chunk cx, cz (same type)."""
    x = min(max(float(pos[0]), cx * 16 + 0.05), cx * 16 + 15.95)
    z = min(max(float(pos[2]), cz * 16 + 0.05), cz * 16 + 15.95)
    return type(pos)((x, pos[1], z)) if isinstance(pos, (tuple, list)) else pos


def rehome_canon(canon: Dict[Key, Tuple[list, list]], exists: Callable[[int, int, int], bool],
                 clamp: bool = True) -> Tuple[Dict[Key, Tuple[list, list]], int]:
    """``canon``: (dim, cx, cz) -> (block entities, entities) in the canonical form of worldbridge.tiles /
    entities.  Returns the same with each entity (a dict with a "pos") under the chunk of its position, and
    how many moved.  An entity whose chunk does not exist in the output (``exists(dim, cx, cz)``) goes
    back to the chunk it came from, moved to its edge when ``clamp`` (a game refuses it anywhere else)."""
    out: Dict[Key, Tuple[list, list]] = {}
    moved = 0
    for (dim, cx, cz), (tl, el) in canon.items():
        stay = []
        for c in el:
            home = chunk_of(c.get("pos")) if isinstance(c, dict) else None
            if home is None or home == (cx, cz):
                stay.append(c)
                continue
            if exists(dim, home[0], home[1]):
                out.setdefault((dim,) + home, ([], []))[1].append(c)
                moved += 1
                continue
            if clamp:
                c["pos"] = clamp_pos(c["pos"], cx, cz)
                if c.get("tile") is not None and len(c["tile"]) == 3:     # a painting / item frame: its wall block
                    t = c["tile"]
                    c["tile"] = type(t)((min(max(int(t[0]), cx * 16), cx * 16 + 15), t[1],
                                         min(max(int(t[2]), cz * 16), cz * 16 + 15)))
            stay.append(c)
        slot = out.setdefault((dim, cx, cz), ([], []))
        slot[0].extend(tl)
        slot[1][:0] = stay
    return out, moved
