"""``blending_data`` for the overworld chunks of a Java 1.18+ world that another generator (or another seed, or
another place) made, so the game blends its own terrain into them instead of meeting them with a wall.

The chunks are finished (status ``full``); a chunk with ``blending_data`` counts as an old chunk for the game's
Blender, which smooths the terrain it generates around it (heights computed by the game from the chunk's
WORLD_SURFACE_WG heightmap when the tag has none).  Layout per DataVersion (the game's own fixers):

* 2825 (1.18) to 3440: ``{old_noise: 1b}`` (ChunkHeightAndBiomeFix);
* 3441 (1.20) and later: ``{min_section, max_section}`` (BlendingDataFix v3441: the overworld's sections
  from y -64 and 384 high: -4 and 20).
"""

from __future__ import annotations

import os
import zlib
from typing import Optional

from .. import nbt as wnbt

FLAT_CHUNKS = 2825            # chunk NBT without "Level", with 24 sections (1.18)
MIN_MAX_SECTION = 3441        # BlendingDataFix: blending_data {min_section, max_section}
MIN_SECTION, MAX_SECTION = -4, 20


def layout(data_version: int) -> Optional[wnbt.CompoundTag]:
    """The ``blending_data`` compound of the overworld in a chunk of ``data_version`` (None: no such chunk)."""
    if data_version < FLAT_CHUNKS:
        return None
    if data_version < MIN_MAX_SECTION:
        return wnbt.CompoundTag({"old_noise": wnbt.ByteTag(1)})
    return wnbt.CompoundTag({"min_section": wnbt.IntTag(MIN_SECTION), "max_section": wnbt.IntTag(MAX_SECTION)})


OVERWORLD_REGIONS = ("region", os.path.join("dimensions", "minecraft", "overworld", "region"))   # before / from 26.1


def supported(target) -> bool:
    """The target game blends by itself (Java 1.18+) and the blending is not turned off (``--no-blend``):
    its converted overworld chunks get ``blending_data``, always, whatever the seed or the source."""
    from ..convert import CAVES_CLIFFS
    from .. import amulet_bridge as ab

    return (target.family == "java" and target.blend
            and tuple(target.version or ab.latest("java")) >= CAVES_CLIFFS)


def mark_world(world_dir: str) -> int:
    """Add ``blending_data`` to every finished chunk of the overworld (``region/`` and, in 26.1+ worlds,
    ``dimensions/minecraft/overworld/region/``), each with the layout of its own DataVersion; chunks in the
    pre-1.18 format and chunks that already have it are left as they are.  Every chunk is decompressed once;
    a region file is rewritten only when it changed, and the chunks of it that did not are copied as stored.
    Returns the chunks changed."""
    from .region import JavaRegion, RegionWriter

    done = 0
    for sub in OVERWORLD_REGIONS:
        folder = os.path.join(world_dir, sub)
        if not os.path.isdir(folder):
            continue
        for name in sorted(os.listdir(folder)):
            if not (name.startswith("r.") and name.endswith(".mca")):
                continue
            path = os.path.join(folder, name)
            reg = JavaRegion(path)
            out = RegionWriter(external=True)
            changed = 0
            for lx, lz in reg.chunks():
                comp = reg.zlib_body(lx, lz)
                try:
                    raw = zlib.decompress(comp) if comp is not None else None
                except zlib.error:
                    raw = None
                if raw is None or raw[:2] == b"\x1f\x8b":
                    comp, raw = None, reg.read(lx, lz)
                if raw is None:
                    continue
                root = wnbt.load(raw, compressed=False).tag
                dv = wnbt.get(root, "DataVersion")
                bd = layout(int(dv)) if dv is not None else None
                status = str(wnbt.get(root, "Status") or "").replace("minecraft:", "")
                if bd is not None and "Level" not in root and "blending_data" not in root and status not in ("", "empty"):
                    root["blending_data"] = bd
                    out.put(lx, lz, wnbt.dump(root, ""))
                    changed += 1
                elif comp is not None:
                    out.put_compressed(lx, lz, comp)
                else:
                    out.put(lx, lz, raw)
            if changed:
                out.write(path)
                done += changed
    return done
