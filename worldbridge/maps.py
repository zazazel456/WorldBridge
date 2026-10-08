"""Filled maps: Java / LCE ``data/map_<n>.dat`` (palette indices) <-> Bedrock ``map_<uuid>`` records (RGBA)."""

from __future__ import annotations

import logging
import os
import re
from typing import Dict, Iterator, Optional, Tuple

import numpy as np

from . import items, nbt

log = logging.getLogger(__name__)

# Java map base colours (index = colour id; 0 = transparent), in registration order
BASE_COLORS = [
    (0, 0, 0), (127, 178, 56), (247, 233, 163), (199, 199, 199), (255, 0, 0), (160, 160, 255), (167, 167, 167),
    (0, 124, 0), (255, 255, 255), (164, 168, 184), (151, 109, 77), (112, 112, 112), (64, 64, 255), (143, 119, 72),
    (255, 252, 245), (216, 127, 51), (178, 76, 216), (102, 153, 216), (229, 229, 51), (127, 204, 25), (242, 127, 165),
    (76, 76, 76), (153, 153, 153), (76, 127, 153), (127, 63, 178), (51, 76, 178), (102, 76, 51), (102, 127, 51),
    (153, 51, 51), (25, 25, 25), (250, 238, 77), (92, 219, 213), (74, 128, 255), (0, 217, 58), (129, 86, 49),
    (112, 2, 0), (209, 177, 161), (159, 82, 36), (149, 87, 108), (112, 108, 138), (186, 133, 36), (103, 117, 53),
    (160, 77, 78), (57, 41, 35), (135, 107, 98), (87, 92, 92), (122, 73, 88), (76, 62, 92), (76, 50, 35),
    (76, 82, 42), (142, 60, 46), (37, 22, 16), (189, 48, 49), (148, 63, 97), (92, 25, 29), (22, 126, 134),
    (58, 142, 140), (86, 44, 62), (20, 180, 133), (100, 100, 100), (216, 175, 147), (127, 167, 150),
]
SHADES = (180, 220, 255, 135)


def _palette() -> np.ndarray:
    pal = np.zeros((256, 4), np.uint8)
    for i, (r, g, b) in enumerate(BASE_COLORS):
        if i == 0:
            continue
        for s, m in enumerate(SHADES):
            pal[i * 4 + s] = (r * m // 255, g * m // 255, b * m // 255, 255)
    return pal


PALETTE = _palette()
_MAP_FILE = re.compile(r"^map_(\d+)\.dat$")


def java_to_rgba(colors: bytes) -> bytes:
    idx = np.frombuffer(bytes(colors), np.uint8)[: 128 * 128]
    return PALETTE[idx].tobytes()


def rgba_to_java(rgba: bytes, max_base: int = 52) -> bytes:
    """Nearest map colour; max_base 52 = the colours Java 1.12 (the hub) knows."""
    px = np.frombuffer(bytes(rgba), np.uint8)[: 128 * 128 * 4].reshape(-1, 4).astype(np.int32)
    solid = PALETTE[4: max_base * 4].astype(np.int32)  # skip the transparent colour
    best = np.empty(len(px), np.uint8)
    for i in range(0, len(px), 2048):  # nearest colour, in blocks to bound memory
        d = ((px[i:i + 2048, None, :3] - solid[None, :, :3]) ** 2).sum(axis=2)
        best[i:i + 2048] = d.argmin(axis=1) + 4
    best[px[:, 3] < 128] = 0
    return best.tobytes()


# ------------------------------------------------------------------ Java / LCE files


def iter_java_maps(world: str) -> Iterator[Tuple[int, nbt.CompoundTag]]:
    """(map number, ``data`` compound) of every map file of a Java / hub world."""
    for base in (os.path.join(world, "data"), os.path.join(world, "data", "minecraft", "maps")):
        if not os.path.isdir(base):
            continue
        for fn in os.listdir(base):
            m = _MAP_FILE.match(fn)
            if not m:
                continue
            try:
                root = nbt.load(open(os.path.join(base, fn), "rb").read(), compressed=None).tag
            except Exception:  # noqa: BLE001
                continue
            data = nbt.get_tag(root, "data")
            if data is not None and "colors" in data:
                yield int(m.group(1)), data


def java_map_file(data: nbt.CompoundTag) -> bytes:
    return nbt.dump(nbt.CompoundTag({"data": data}), "", compressed=True)


# ------------------------------------------------------------------ Bedrock records


def bedrock_record(n: int, data: nbt.CompoundTag) -> Tuple[bytes, nbt.CompoundTag]:
    uuid = items.bedrock_map_uuid(n)
    dim = nbt.get(data, "dimension", 0)
    if isinstance(dim, str):
        dim = {"minecraft:the_nether": -1, "minecraft:the_end": 1}.get(dim, 0)
    dim = {-1: 1, 1: 2}.get(int(dim or 0), 0)
    # no "parentMapId": a map without a parent has none; Bedrock 1.17 - 26 logs "Map item N has invalid
    # parentMapId" at every load of a chunk holding the map when it is -1
    rec = nbt.CompoundTag({
        "mapId": nbt.LongTag(uuid), "dimension": nbt.ByteTag(dim),
        "fullyExplored": nbt.ByteTag(0), "mapLocked": nbt.ByteTag(1 if nbt.get(data, "locked", 0) else 0),
        "scale": nbt.ByteTag(int(nbt.get(data, "scale", 0) or 0)), "unlimitedTracking": nbt.ByteTag(0),
        "height": nbt.ShortTag(128), "width": nbt.ShortTag(128),
        "xCenter": nbt.IntTag(int(nbt.get(data, "xCenter", 0) or 0)),
        "zCenter": nbt.IntTag(int(nbt.get(data, "zCenter", 0) or 0)),
        "colors": nbt.ByteArrayTag(np.frombuffer(java_to_rgba(bytes(np.asarray(data["colors"], np.uint8))), np.int8)),
        "decorations": nbt.ListTag([], 10),
    })
    return b"map_" + str(uuid).encode(), rec


def java_from_bedrock(rec: nbt.CompoundTag) -> Optional[Tuple[int, nbt.CompoundTag]]:
    uuid = nbt.get(rec, "mapId")
    colors = nbt.get_tag(rec, "colors")
    if uuid is None or colors is None or len(colors) < 128 * 128 * 4:
        return None
    n = items.java_map_id(int(uuid))
    dim = {1: -1, 2: 1}.get(int(nbt.get(rec, "dimension", 0) or 0), 0)
    data = nbt.CompoundTag({
        "scale": nbt.ByteTag(int(nbt.get(rec, "scale", 0) or 0)), "dimension": nbt.ByteTag(dim),
        "width": nbt.ShortTag(128), "height": nbt.ShortTag(128), "trackingPosition": nbt.ByteTag(1),
        "unlimitedTracking": nbt.ByteTag(0), "locked": nbt.ByteTag(1 if nbt.get(rec, "mapLocked", 0) else 0),
        "xCenter": nbt.IntTag(int(nbt.get(rec, "xCenter", 0) or 0)),
        "zCenter": nbt.IntTag(int(nbt.get(rec, "zCenter", 0) or 0)),
        "colors": nbt.ByteArrayTag(np.frombuffer(rgba_to_java(bytes(np.asarray(colors, np.uint8))), np.int8)),
    })
    return n, data


def bedrock_maps_as_java(db) -> Dict[str, bytes]:
    """``data/map_<n>.dat`` files for the maps of a Bedrock world (see items.java_map_id)."""
    out = {}
    for k, v in db.iterate(b"map_", b"map_\xff"):
        k = bytes(k)
        if not k.startswith(b"map_"):
            continue
        try:
            rec = nbt.load(bytes(v), little_endian=True, compressed=False).tag
            got = java_from_bedrock(rec)
        except Exception:  # noqa: BLE001
            got = None
        if got is not None:
            out[f"data/map_{got[0]}.dat"] = java_map_file(got[1])
    return out



def java_map_colors(version) -> int:
    """How many base map colours (MapColor / MaterialColor) a Java version registers: a colour id past
    them is a null slot and crashes the game when the map is drawn.  ``version`` is a numeric-era
    label ("b1.6", "1.8"; None = the 1.12 hub) or a version tuple."""
    if version is None:
        return 52
    if isinstance(version, str):
        from . import blocks as blk

        r = blk.version_rank(version)
        return 14 if r < blk.version_rank("1.7") else 36 if r < blk.version_rank("1.12") else 52
    v = tuple(version)
    if v < (1, 7):
        return 14                              # Beta 1.6 - 1.6.4
    if v < (1, 12):
        return 36
    if v < (1, 16):
        return 52                              # terracotta colours (1.12)
    if v < (1, 17):
        return 59                              # crimson / warped (1.16)
    return len(BASE_COLORS)                    # deepslate, raw iron, glow lichen (1.17)


def cap_colors(colors, max_base: int) -> np.ndarray:
    """Map colour bytes with every colour id from ``max_base`` on replaced by the nearest older one."""
    cols = np.asarray(colors).astype(np.uint8)
    bad = (cols >> 2) >= max_base
    if bad.any():
        cols = cols.copy()
        pal = PALETTE[4: max_base * 4].astype(np.int32)
        px = PALETTE[cols[bad]].astype(np.int32)
        d = ((px[:, None, :3] - pal[None, :, :3]) ** 2).sum(axis=2)
        cols[bad] = d.argmin(axis=1).astype(np.uint8) + 4
    return cols


def legacy_map_data(data: nbt.CompoundTag, max_base: int = 52) -> nbt.CompoundTag:
    """A map ``data`` compound readable by old games: numeric dimension, only the first ``max_base``
    base colours (Java 1.12 has 52, Java 1.7 - 1.11 and LCE 36; a newer colour id crashes them)."""
    out = nbt.CompoundTag()
    for k in ("scale", "width", "height", "xCenter", "zCenter", "trackingPosition", "unlimitedTracking", "locked"):
        if k in data:
            out[k] = data[k]
    dim = nbt.get(data, "dimension", 0)
    if isinstance(dim, str):
        dim = {"minecraft:the_nether": -1, "minecraft:the_end": 1}.get(dim, 0)
    out["dimension"] = nbt.ByteTag(int(dim or 0))
    out.setdefault("scale", nbt.ByteTag(0))
    out.setdefault("width", nbt.ShortTag(128))
    out.setdefault("height", nbt.ShortTag(128))
    out["colors"] = nbt.ByteArrayTag(cap_colors(data["colors"], max_base).view(np.int8))
    return out


def capped_map_file(blob: bytes, max_base: int, legacy: bool = False) -> bytes:
    """A ``data/map_<n>.dat`` file whose colours the target game knows (``max_base`` base colours).
    ``legacy``: also rebuilt for a numeric-era game (see legacy_map_data).  The file is returned as
    it is when nothing needs to change or it cannot be read."""
    try:
        named = nbt.load(blob, compressed=None)
        root = named.tag
        data = nbt.get_tag(root, "data")
        if not isinstance(data, nbt.CompoundTag) or "colors" not in data:
            return blob
        if legacy:
            return java_map_file(legacy_map_data(data, max_base))
        cols = np.asarray(data["colors"]).astype(np.uint8)
        if not ((cols >> 2) >= max_base).any():
            return blob
        data["colors"] = nbt.ByteArrayTag(cap_colors(cols, max_base).view(np.int8))
        return nbt.dump(root, named.name or "", compressed=True)
    except Exception:  # noqa: BLE001
        log.debug("map file not capped", exc_info=True)
        return blob


def legacy_map_files(world: str, max_base: int = 52) -> Dict[str, bytes]:
    """``data/map_<n>.dat`` of a Java 1.13+ world, rewritten for the Java 1.12 hub."""
    return {f"data/map_{n}.dat": java_map_file(legacy_map_data(data, max_base)) for n, data in iter_java_maps(world)}
