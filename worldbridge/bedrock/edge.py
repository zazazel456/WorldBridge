"""Blending the border of a Bedrock 1.18+ world made from a 1.18+ source (docs/SEAMLESS_BORDERS.md).

Bedrock 1.18+ blends only the chunks it takes for pre-1.18 ones, and the only marker it honours is the chunk
version record (key 0x2c) below 39 (measured on a real server: the 0x3d flag or version 39 do not blend).  A
chunk marked that way is upgraded by the game, which regenerates **everything below y 0** in it (measured: 57 % of
the blocks below 0 were lost in 1.18, 40 % in 1.21).  So the option marks only the outer ring of the converted
chunks: the border blends, the interior keeps its underground.
"""

from __future__ import annotations

import os
import struct
from typing import Dict, Iterable, Optional, Set, Tuple

from ..i18n import tr

CAVES_CLIFFS = (1, 18, 0)
OLD_VERSION = 22                    # chunk version of the old worlds (pre-1.18): 0x2c = 22
VERSION_TAG = 0x2C
SUBCHUNK_TAG = 0x2F
# records that tell the game a 1.18+ chunk was already blended / generated: gone from a chunk marked as old
BLEND_TAGS = (0x3D, 0x3F, 0x40, 0x41)
# overworld tags every chunk has (a key is x, z int32 LE + tag; sub chunks add their y; other dimensions add an int32)
_CHUNK_TAGS = (0x2B, 0x2C, 0x2D, 0x36, 0x76)

Chunk = Tuple[int, int]


def applies(target, source_kind: str, source_old: bool, moved: bool) -> bool:
    """The border of the converted world stays cut unless it is blended: the target is Bedrock 1.18+, the source
    has 1.18+ terrain, and it is not a Bedrock world going back into Bedrock where it was (same terrain, same
    seed: the game continues it by itself).  Pre-1.18 sources are already written in the old format."""
    if getattr(target, "family", "") != "bedrock":
        return False
    from .. import amulet_bridge as ab

    if tuple(target.version or ab.latest("bedrock")) < CAVES_CLIFFS:
        return False
    if source_old or source_kind not in ("java_modern", "bedrock"):
        return False
    return not (source_kind == "bedrock" and not moved)


def is_moved(target, sel=None) -> bool:
    """The world is not where it was: --move-to, or --y-offset."""
    sel = sel if sel is not None else getattr(target, "selection", None)
    return bool(getattr(sel, "moves", False)) or bool(getattr(target, "y_offset", 0))


def border_chunks(chunks: Iterable[Chunk], width: int = 1) -> Set[Chunk]:
    """The chunks with an absent chunk within ``width`` chunks of them: the outer ring, ``width`` chunks wide."""
    have = set(chunks)
    w = max(1, int(width))
    span = range(-w, w + 1)
    return {(cx, cz) for cx, cz in have if any((cx + dx, cz + dz) not in have for dx in span for dz in span)}


def overworld_chunks(db) -> Set[Chunk]:
    out = set()
    for k, _v in db.iterate():
        k = bytes(k)
        if len(k) == 9 and k[8] in _CHUNK_TAGS or len(k) == 10 and k[8] == SUBCHUNK_TAG:
            out.add(struct.unpack_from("<ii", k))
    return out


def below_zero_blocks(db, chunks: Iterable[Chunk]) -> int:
    """Non-air blocks in the sub chunks with y < 0 of ``chunks``."""
    import numpy as np

    from ..mapview import bedrock_subchunk

    air = {"air", "cave_air", "void_air"}
    n = 0
    for cx, cz in chunks:
        for sy in range(-4, 0):
            try:
                raw = db.get(struct.pack("<ii", cx, cz) + bytes([SUBCHUNK_TAG, sy & 0xFF]))
            except KeyError:
                continue
            try:
                layers = bedrock_subchunk(bytes(raw))
            except Exception:  # noqa: BLE001
                continue
            if layers:
                idx, names = layers[0]
                free = np.array([nm.split(":", 1)[-1] in air for nm in names], bool)
                n += int((~free[idx]).sum())
    return n


def mark_border(world_dir: str, width: int = 1) -> Dict[str, int]:
    """Mark the outer ring of the overworld chunks of a Bedrock world as pre-1.18 (version 22, no blending
    records).  Returns ``{"chunks": all, "marked": ring chunks, "below0": non-air blocks below y 0 in them}``."""
    from leveldb import LevelDB

    db = LevelDB(os.path.join(world_dir, "db"))
    try:
        everything = overworld_chunks(db)
        ring = border_chunks(everything, width)
        below = below_zero_blocks(db, ring)
        for cx, cz in sorted(ring):
            pre = struct.pack("<ii", cx, cz)
            db.put(pre + bytes([VERSION_TAG]), bytes([OLD_VERSION]))
            for tag in BLEND_TAGS:
                db.delete(pre + bytes([tag]))
    finally:
        db.close()
    return {"chunks": len(everything), "marked": len(ring), "below0": below}


def warning_text() -> str:
    return tr("The border of this world will stay cut: Bedrock blends only the chunks it takes for pre-1.18 ones, and a "
              "world made from a 1.18+ one has none. The option \"Blend the Bedrock border\" (--bedrock-edge-blend) marks "
              "the outer ring of chunks as old so the game blends them, but then it regenerates the layer below y 0 in "
              "those chunks only.")


def done_text(n_marked: int, below0: int, width: int) -> str:
    return tr("Border blending: {n} border chunks ({width} wide) marked as pre-1.18; the {blocks} blocks below y 0 they "
              "hold will be regenerated by the game.", n=n_marked, width=width, blocks=below0)
