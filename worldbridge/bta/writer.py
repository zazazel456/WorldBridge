"""A converted chunk in the Minecraft 1.18.2 chunk format (DataVersion 2975).

Items, block entities and entities keep the 1.17 / 1.18 layout, which the vanilla DataFixer then
upgrades to 26.3; for every pre-26.x overworld chunk the 26.3 DataFixer adds ``blending_data``
(BlendingDataFix), so newly generated terrain blends into the converted terrain.

The overworld is moved down by ``shift`` blocks so BTA's sea level matches vanilla's (y 63): the
BTA underground ends up below y 0, which only exists since 1.18 - hence the 1.18.2 format.
Light and heightmaps are not written (isLightOn = 0: the game relights and primes them on load).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict

import numpy as np

from .. import nbt
from . import DATA_VERSION
from .chunks import Stage1
from .entities import output_name
from .states import AIR, BEDROCK, by_id, palette_tag


@dataclass(frozen=True)
class Layout:
    min_section: int
    section_count: int
    shift: int

    @property
    def min_y(self) -> int:
        return self.min_section * 16

    @property
    def max_y(self) -> int:
        return (self.min_section + self.section_count) * 16 - 1


NETHER_END = Layout(0, 16, 0)


def overworld(shift: int) -> Layout:
    return Layout(-4, 24, shift)


def _bits_for(n: int) -> int:
    return (n - 1).bit_length()


def pack(values: np.ndarray, bits: int) -> np.ndarray:
    """1.16+ packing: entries never span two longs."""
    per = 64 // bits
    n = (len(values) + per - 1) // per
    v = np.zeros(n * per, np.uint64)
    v[:len(values)] = values.astype(np.uint64)
    v = v.reshape(n, per) << (np.arange(per, dtype=np.uint64) * np.uint64(bits))
    return np.bitwise_or.reduce(v, axis=1).view(np.int64)


def _first_order(values: np.ndarray):
    """(palette in first-occurrence order, indices into it)."""
    uniq, first, inv = np.unique(values, return_index=True, return_inverse=True)
    order = np.argsort(first, kind="stable")
    rank = np.empty_like(order)
    rank[order] = np.arange(len(order))
    return uniq[order], rank[inv.reshape(-1)]


def shift_entity(e: nbt.CompoundTag, shift: int) -> nbt.CompoundTag:
    if shift == 0:
        return e
    s = nbt.copy(e)
    p = nbt.get_tag(s, "Pos")
    if p is not None and len(p) == 3:
        s["Pos"] = nbt.ListTag([p[0], nbt.DoubleTag(float(p[1].py_data) - shift), p[2]], 6)
    if "TileY" in s:
        s["TileY"] = nbt.IntTag(int(s["TileY"].py_data) - shift)
    return s


_NAME_CACHE: Dict[int, nbt.CompoundTag] = {}


def _palette_entry(sid: int) -> nbt.CompoundTag:
    t = _NAME_CACHE.get(sid)
    if t is None:
        s = by_id(sid)
        t = _NAME_CACHE[sid] = palette_tag(s, output_name(s.name))
    return t


def write_chunk(c: Stage1, last_update: int, layout: Layout) -> nbt.CompoundTag:
    root = nbt.CompoundTag({
        "DataVersion": nbt.IntTag(DATA_VERSION), "xPos": nbt.IntTag(c.cx), "yPos": nbt.IntTag(layout.min_section),
        "zPos": nbt.IntTag(c.cz), "LastUpdate": nbt.LongTag(max(0, last_update)), "InhabitedTime": nbt.LongTag(0),
        "Status": nbt.StringTag("full"), "isLightOn": nbt.ByteTag(0),
    })
    height = layout.section_count * 16
    column = np.full((height, 16, 16), AIR.id, np.uint32)
    lo = max(0, layout.min_y + layout.shift)          # first BTA y that lands inside the output
    hi = min(255, layout.max_y + layout.shift)
    if hi >= lo:
        column[lo - layout.shift - layout.min_y:hi - layout.shift - layout.min_y + 1] = c.states[lo:hi + 1]
    if layout.shift > 0:
        column[0] = BEDROCK.id  # the BTA layer below this one fell out of the world
    biome_cells = np.array([b or "" for b in c.biomes], dtype=object)
    sections = nbt.ListTag([], 10)
    for i in range(layout.section_count):
        sy = layout.min_section + i
        base_y = sy * 16
        pal, idx = _first_order(column[i * 16:(i + 1) * 16].reshape(-1))
        sec = nbt.CompoundTag({"Y": nbt.ByteTag(sy)})
        bs = nbt.CompoundTag({"palette": nbt.ListTag([nbt.copy(_palette_entry(int(s))) for s in pal], 10)})
        if len(pal) > 1:
            bs["data"] = nbt.LongArrayTag(pack(idx, max(4, _bits_for(len(pal)))))
        sec["block_states"] = bs
        # biomes: 4x4x4 cells, index (y << 4) | (z << 2) | x
        cells = []
        for j in range(64):
            vy = base_y + (j >> 4) * 4
            bta_cell = max(0, min(63, (vy + layout.shift) >> 2))
            cells.append(biome_cells[(bta_cell << 4) | (j & 15)])
        bpal: Dict[str, int] = {}
        bidx = np.fromiter((bpal.setdefault(b, len(bpal)) for b in cells), np.int64, 64)
        bio = nbt.CompoundTag({"palette": nbt.ListTag([nbt.StringTag(b) for b in bpal], 8)})
        if len(bpal) > 1:
            bio["data"] = nbt.LongArrayTag(pack(bidx, _bits_for(len(bpal))))
        sec["biomes"] = bio
        sections.append(sec)
    root["sections"] = sections
    ents = nbt.ListTag([], 10)
    for e in c.entities:
        s = shift_entity(e, layout.shift)
        y = float(s["Pos"][1].py_data)
        if y < layout.min_y - 32 or y > layout.max_y + 64:
            continue  # would be deleted by the game anyway
        ents.append(s)
    root["entities"] = ents
    tes = nbt.ListTag([], 10)
    for te in c.block_entities.values():
        y = int(te["y"].py_data) - layout.shift
        if y < layout.min_y or y > layout.max_y:
            continue
        t = nbt.copy(te)
        t["y"] = nbt.IntTag(y)
        tes.append(t)
    root["block_entities"] = tes
    root["block_ticks"] = nbt.ListTag([], 10)
    root["fluid_ticks"] = nbt.ListTag([], 10)
    root["PostProcessing"] = nbt.ListTag([nbt.ListTag([], 2) for _ in range(layout.section_count)], 9)
    root["structures"] = nbt.CompoundTag({"References": nbt.CompoundTag(), "starts": nbt.CompoundTag()})
    return root
