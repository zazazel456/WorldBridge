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


def needed(source_kind: str, old_source: bool, unmoved: bool, upgrade_only: bool) -> bool:
    """True when the terrain of a Java 1.18+ target was not made by its own generator at this place: anything
    but a Java 1.18+ world that stays where it is and goes to the same or a newer version (and keeps its seed).
    A pre-1.18 source is written in the pre-1.18 format instead, which the game's upgrade blends."""
    if old_source:
        return False
    return not (source_kind == "java_modern" and unmoved and upgrade_only)


def mark_world(world_dir: str, sub: str = "region") -> int:
    """Add ``blending_data`` to every finished chunk of the overworld region folder ``sub`` of ``world_dir``;
    returns the chunks changed."""
    from .region import JavaRegion, RegionWriter

    folder = os.path.join(world_dir, sub)
    if not os.path.isdir(folder):
        return 0
    done = 0
    for name in sorted(os.listdir(folder)):
        if not (name.startswith("r.") and name.endswith(".mca")):
            continue
        path = os.path.join(folder, name)
        reg = JavaRegion(path)
        out = RegionWriter(external=True)
        changed = 0
        for lx, lz in reg.chunks():
            raw = reg.read(lx, lz)
            if raw is None:
                continue
            root = wnbt.load(raw, compressed=False).tag
            dv = wnbt.get(root, "DataVersion")
            bd = layout(int(dv)) if dv is not None else None
            status = str(wnbt.get(root, "Status") or "").replace("minecraft:", "")
            if bd is not None and "Level" not in root and "blending_data" not in root and status not in ("", "empty"):
                root["blending_data"] = bd
                raw = wnbt.dump(root, "")
                changed += 1
            out.put(lx, lz, raw)
        if changed:
            out.write(path)
            done += changed
    return done
