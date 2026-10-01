"""A tiny Better than Adventure save writer for tests (BTA NBT dialect: tag 11 = little-endian
short array), producing the same layout as BTA 8.0.1 (dimensions/<n>/region/r.X.Z.mcr, chunk
format version 3 with 16x16x16 sections)."""

import gzip
import os
import struct
import zlib

import numpy as np


class Short(int):
    pass


class Byte(int):
    pass


class Long(int):
    pass


class Float(float):
    pass


def _name(s: str) -> bytes:
    b = s.encode("utf-8")
    return struct.pack(">H", len(b)) + b


def _tag(v):
    """(type id, payload bytes)"""
    if isinstance(v, Byte) or isinstance(v, bool):
        return 1, struct.pack(">b", int(v))
    if isinstance(v, Short):
        return 2, struct.pack(">h", int(v))
    if isinstance(v, Long):
        return 4, struct.pack(">q", int(v))
    if isinstance(v, int):
        return 3, struct.pack(">i", v)
    if isinstance(v, Float):
        return 5, struct.pack(">f", v)
    if isinstance(v, float):
        return 6, struct.pack(">d", v)
    if isinstance(v, str):
        return 8, _name(v)
    if isinstance(v, np.ndarray):
        if v.dtype == np.int8:
            return 7, struct.pack(">i", v.size) + v.tobytes()
        if v.dtype == np.int16:  # BTA short array, little-endian
            return 11, struct.pack(">i", v.size) + v.astype("<i2").tobytes()
        raise TypeError(v.dtype)
    if isinstance(v, list):
        if not v:
            return 9, struct.pack(">bi", 1, 0)  # BTA writes empty lists as byte lists
        items = [_tag(x) for x in v]
        return 9, struct.pack(">bi", items[0][0], len(items)) + b"".join(p for _t, p in items)
    if isinstance(v, dict):
        out = b""
        for k, x in v.items():
            t, p = _tag(x)
            out += struct.pack(">b", t) + _name(k) + p
        return 10, out + b"\x00"
    raise TypeError(type(v))


def dump(root: dict) -> bytes:
    return b"\x0a" + _name("") + _tag(root)[1]


def write_gzip(path: str, root: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(gzip.compress(dump(root)))


class BtaChunkBuilder:
    def __init__(self, cx: int, cz: int):
        self.cx, self.cz = cx, cz
        self.blocks = np.zeros((256, 16, 16), np.int16)
        self.data = np.zeros((256, 16, 16), np.int8)
        self.biome = np.zeros((32, 16, 16), np.int8)  # index into the registry below
        self.entities = []
        self.tiles = []

    def set(self, x: int, y: int, z: int, bid: int, meta: int = 0):
        self.blocks[y, z & 15, x & 15] = bid
        self.data[y, z & 15, x & 15] = np.int8(meta - 256 if meta > 127 else meta)

    def level(self, biomes=("minecraft:overworld.forest", "minecraft:overworld.desert")) -> dict:
        sections = []
        for sy in range(16):
            b = self.blocks[sy * 16:sy * 16 + 16]
            if not b.any():
                continue
            sections.append({"yPos": sy, "Blocks": b.reshape(-1).copy(), "Data": self.data[sy * 16:sy * 16 + 16].reshape(-1).copy(),
                             "BiomeMap": self.biome[sy * 2:sy * 2 + 2].reshape(-1).copy()})
        return {"xPos": self.cx, "zPos": self.cz, "Version": 3, "TerrainPopulated": Byte(1), "TicksOnUnload": Long(100),
                "Registries": {"Biomes": {name: Short(i) for i, name in enumerate(biomes)}},
                "Sections": sections, "Entities": self.entities, "TileEntities": self.tiles}


def write_region(path: str, chunks) -> None:
    """McRegion file with zlib chunks."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    offsets = [0] * 1024
    body = b""
    sector = 2
    for c in chunks:
        comp = zlib.compress(dump({"Level": c.level()}))
        blob = struct.pack(">IB", len(comp) + 1, 2) + comp
        n = (len(blob) + 4095) // 4096
        blob += b"\x00" * (n * 4096 - len(blob))
        offsets[(c.cx & 31) + (c.cz & 31) * 32] = (sector << 8) | n
        body += blob
        sector += n
    with open(path, "wb") as f:
        f.write(struct.pack(">1024I", *offsets) + struct.pack(">1024I", *([1000] * 1024)) + body)


def item(iid: int, count: int = 1, damage: int = 0, slot=None, **extra) -> dict:
    it = {"id": Short(iid), "Count": Byte(count), "Damage": Short(damage), "Expanded": Byte(1), "Version": 19135}
    if slot is not None:
        it["Slot"] = Byte(slot)
    it.update(extra)
    return it
