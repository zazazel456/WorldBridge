"""Chunks the game has not finished generating.

Around the explored area Java 1.14+ keeps proto chunks (``Status`` structure_starts, biomes, noise,
terrain, light...): planned or bare stone, with no surface or trees yet; Bedrock marks them with
``FinalizedState`` < 2.  Converted as they are they become flat stone blocks and holes in the
new world, so they are left out: the game (1.18+) or WorldBridge's ring generates them again.
"""

from __future__ import annotations

import os
import struct
from typing import Dict, Optional, Set, Tuple

from . import nbt
from .model import NETHER, OVERWORLD, THE_END

Chunk = Tuple[int, int]
COMPLETE = {"full", "minecraft:full", "postprocessed", "minecraft:postprocessed", "fullchunk", "minecraft:fullchunk"}

_JAVA_DIRS = {
    OVERWORLD: ("dimensions/minecraft/overworld/region", "region"),
    NETHER: ("dimensions/minecraft/the_nether/region", "DIM-1/region"),
    THE_END: ("dimensions/minecraft/the_end/region", "DIM1/region"),
}


def _status(root) -> str:
    lvl = nbt.get_tag(root, "Level")
    st = nbt.get(root, "Status") if "Status" in root else (nbt.get(lvl, "Status") if lvl is not None else None)
    return str(st) if st is not None else ""


_STATUS = b"\x08\x00\x06Status"


def _fast_status(raw: bytes) -> str:
    """The chunk's Status without parsing its whole NBT (a big world has hundreds of thousands)."""
    i = raw.find(_STATUS)
    if i < 0:
        return ""
    j = i + len(_STATUS)
    n = struct.unpack_from(">H", raw, j)[0]
    return raw[j + 2:j + 2 + n].decode("utf-8", "replace")


def java_incomplete(path: str, only: Optional[Dict[int, Set[Chunk]]] = None) -> Dict[int, Set[Chunk]]:
    """``only``: the chunks that matter (a selection): the others are not even read."""
    from .java.region import JavaRegion

    jobs = []
    for dim, dirs in _JAVA_DIRS.items():
        d = next((os.path.join(path, x) for x in dirs if os.path.isdir(os.path.join(path, x))), None)
        if d is None:
            continue
        want = None if only is None else only.get(dim, set())
        if want is not None and not want:
            continue
        regions = None if want is None else {(cx >> 5, cz >> 5) for cx, cz in want}
        for fn in os.listdir(d):
            parts = fn.split(".")
            if len(parts) != 4 or parts[3] != "mca":
                continue
            try:
                rx, rz = int(parts[1]), int(parts[2])
            except ValueError:
                continue
            if regions is None or (rx, rz) in regions:
                jobs.append((dim, os.path.join(d, fn), rx, rz, want))

    def scan(job) -> Tuple[int, Set[Chunk]]:
        dim, fpath, rx, rz, want = job
        found: Set[Chunk] = set()
        try:
            reg = JavaRegion(fpath)
            for lx, lz in reg.chunks():
                if want is not None and (rx * 32 + lx, rz * 32 + lz) not in want:
                    continue
                try:
                    st = _fast_status(reg.read(lx, lz) or b"")
                except Exception:  # noqa: BLE001
                    continue
                if st and st not in COMPLETE:
                    found.add((rx * 32 + lx, rz * 32 + lz))
        except Exception:  # noqa: BLE001
            pass
        return dim, found

    # zlib works outside the GIL: the region files are read and inflated by several threads at once
    from concurrent.futures import ThreadPoolExecutor

    from .parallel import workers

    out: Dict[int, Set[Chunk]] = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers(), len(jobs)))) as pool:
        for dim, found in pool.map(scan, jobs):
            if found:
                out.setdefault(dim, set()).update(found)
    return out


def bedrock_incomplete(db) -> Dict[int, Set[Chunk]]:
    out: Dict[int, Set[Chunk]] = {}
    for k, v in db.iterate():
        k = bytes(k)
        if len(k) in (9, 13) and k[-1] == 0x36 and len(v) >= 4:          # FinalizedState
            state = struct.unpack_from("<i", bytes(v), 0)[0]
            if state < 2:
                cx, cz = struct.unpack_from("<ii", k, 0)
                dim = struct.unpack_from("<i", k, 8)[0] if len(k) == 13 else 0
                dim = {1: NETHER, 2: THE_END}.get(dim, OVERWORLD)
                out.setdefault(dim, set()).add((cx, cz))
    return out


def incomplete_chunks(kind: str, path: str, only: Optional[Dict[int, Set[Chunk]]] = None) -> Dict[int, Set[Chunk]]:
    if kind == "java_modern":
        return java_incomplete(path, only)
    if kind == "bedrock":
        from .bedrock.extra import _db

        db = _db(path)
        try:
            return bedrock_incomplete(db)
        finally:
            db.close()
    return {}
