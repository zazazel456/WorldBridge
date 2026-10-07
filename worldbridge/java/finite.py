"""Finite-map Java worlds (Classic, Indev) exposed as chunked hub worlds."""

from __future__ import annotations

from typing import List, Optional, Tuple

import numpy as np

from .. import nbt
from ..model import OVERWORLD, NumericChunk, WorldInfo, WorldSource


class FiniteWorld(WorldSource):
    """A finite block volume ``blocks[y, z, x]`` split into 16x16 chunks."""

    def __init__(self, blocks: np.ndarray, data: Optional[np.ndarray], info: WorldInfo,
                 tile_entities=None, entities=None):
        h, length, width = blocks.shape
        self.height = 256 if h > 128 else 128
        self.max_height = self.height
        self.blocks = blocks[: self.height]
        self.data = data[: self.height] if data is not None else None
        self.length, self.width = length, width
        self.info = info
        self.tiles = tile_entities or []
        self.ents = entities or []

    def dimensions(self) -> List[int]:
        return [OVERWORLD]

    def chunk_coords(self, dim: int) -> List[Tuple[int, int]]:
        return [(cx, cz) for cx in range((self.width + 15) // 16) for cz in range((self.length + 15) // 16)]

    def read_chunk(self, dim: int, cx: int, cz: int) -> Optional[NumericChunk]:
        c = NumericChunk(cx, cz, self.height)
        x0, z0 = cx * 16, cz * 16
        sub = self.blocks[:, z0 : z0 + 16, x0 : x0 + 16]
        h, sz, sx = sub.shape
        c.blocks[:h, :sz, :sx] = sub
        if self.data is not None:
            c.data[:h, :sz, :sx] = self.data[:, z0 : z0 + 16, x0 : x0 + 16]
        c.biomes = np.ones((16, 16), np.uint8)
        c.sky_light = c.compute_sky_light()
        c.block_light = np.zeros_like(c.sky_light)
        for t in self.tiles:
            x, z = int(nbt.get(t, "x", -1)), int(nbt.get(t, "z", -1))
            if x0 <= x < x0 + 16 and z0 <= z < z0 + 16:
                c.tile_entities.append(t)
        for e in self.ents:
            pos = nbt.get_tag(e, "Pos")
            if pos is not None and len(pos) == 3:
                x, z = float(pos[0].py_data), float(pos[2].py_data)
                if x0 <= x < x0 + 16 and z0 <= z < z0 + 16:
                    c.entities.append(e)
        return c


# ------------------------------------------------------------------ Indev


def _doubles(e) -> None:
    """Indev stores Pos / Motion as floats; later formats (and our rebuilt positions) use doubles."""
    for k in ("Pos", "Motion"):
        v = nbt.get_tag(e, k)
        if isinstance(v, nbt.ListTag) and len(v) == 3 and not isinstance(v[0], nbt.DoubleTag):
            e[k] = nbt.pos_list(*v)


def load_indev(path: str) -> FiniteWorld:
    root = nbt.load(open(path, "rb").read()).tag
    m = root["Map"]
    w, l, h = int(nbt.get(m, "Width")), int(nbt.get(m, "Length")), int(nbt.get(m, "Height"))
    blocks = np.asarray(m["Blocks"].np_array).astype(np.uint8).reshape(h, l, w).astype(np.uint16)
    data = None
    if "Data" in m:
        data = (np.asarray(m["Data"].np_array).astype(np.uint8).reshape(h, l, w) & 0x0F).astype(np.uint8)
    info = WorldInfo()
    about = nbt.get_tag(root, "About") or nbt.CompoundTag()
    info.level = nbt.CompoundTag({"LevelName": nbt.StringTag(str(nbt.get(about, "Name", "Indev World")))})
    spawn = nbt.get_tag(m, "Spawn")
    if spawn is not None and len(spawn) == 3:
        sx, sy, sz = (int(v.py_data) for v in spawn)
        info.level["SpawnX"], info.level["SpawnY"], info.level["SpawnZ"] = nbt.IntTag(sx), nbt.IntTag(sy), nbt.IntTag(sz)
    env = nbt.get_tag(root, "Environment")
    if env is not None:
        info.level["Time"] = nbt.LongTag(int(nbt.get(env, "TimeOfDay", 0) or 0))
    tiles = []
    for t in nbt.get_tag(root, "TileEntities") or []:
        p = int(nbt.get(t, "Pos", 0))
        t = nbt.copy(t)
        t["x"], t["y"], t["z"] = nbt.IntTag(p % 1024), nbt.IntTag((p >> 10) % 1024), nbt.IntTag((p >> 20) % 1024)
        tiles.append(t)
    ents = [e for e in (nbt.get_tag(root, "Entities") or []) if nbt.get(e, "id") != "LocalPlayer"]
    for e in nbt.get_tag(root, "Entities") or []:
        if nbt.get(e, "id") == "LocalPlayer":
            info.players["host"] = e
    for e in ents + list(info.players.values()):
        _doubles(e)
    info.source_description = "Java Edition Indev"
    return FiniteWorld(blocks, data, info, tiles, ents)


class IndevWorld(FiniteWorld):
    def __init__(self, path: str):
        w = load_indev(path)
        self.__dict__.update(w.__dict__)


# ------------------------------------------------------------------ Classic
# Classic cloth colours -> Java wool data
CLASSIC_CLOTH = {21: 14, 22: 1, 23: 4, 24: 5, 25: 13, 26: 5, 27: 9, 28: 3, 29: 11, 30: 10, 31: 10, 32: 2, 33: 6,
                 34: 7, 35: 8, 36: 0}
