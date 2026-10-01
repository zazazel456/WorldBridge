"""Caves & Cliffs worlds (y -64 .. 319) into games whose world starts at y 0 (Java 1.2 - 1.17, LCE,
Bedrock up to 1.17, and through them the 128 high ones).

The user chooses how much of the underground to keep:

* ``cut`` (the default): what lies under y 0 is dropped, as before;
* ``keep``: everything is kept, the world moves up by 64 blocks;
* a negative y: what lies under it is dropped, the rest moves up so that it lands on y 0.

Whatever does not fit at the top afterwards (the target's world ends at y 255) is compressed like
the 128 high targets (heightfit.py: the mountains come down whole, their surface intact) or cut,
as the user chose (``TargetSpec.tall_terrain``).  The work is done on Amulet's universal chunks while
they are read, so every path through Amulet gets it; the chunks never reach the 0 - 255 limit with
their tops or their bottoms still out of it.
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from . import nbt
from .heightfit import HeightFit
from .model import NumericChunk

DEEP_BOTTOM = -64
TOP = 320                     # first y a Caves & Cliffs world cannot use
CEILING = 256                 # first y the targets cannot store

# categories of universal blocks, as Java 1.12 ids understood by heightfit (ground, logs, leaves...)
_GROUND = {"stone", "granite", "diorite", "andesite", "deepslate", "tuff", "calcite", "dirt", "coarse_dirt",
           "grass_block", "podzol", "mycelium", "rooted_dirt", "mud", "sand", "red_sand", "gravel", "clay",
           "sandstone", "red_sandstone", "terracotta", "stained_terracotta", "bedrock", "ice", "packed_ice",
           "blue_ice", "snow_block", "powder_snow", "netherrack", "magma_block", "dripstone_block", "moss_block",
           "amethyst_block", "budding_amethyst", "smooth_basalt", "end_stone", "obsidian", "infested_block",
           "coal_block", "suspicious_sand", "suspicious_gravel"}
_FLUID = {"water", "lava", "bubble_column"}
_AIR = {"air", "cave_air", "void_air"}
_PLANTS = {"grass", "tall_grass", "short_grass", "fern", "large_fern", "dead_bush", "snow", "sugar_cane", "cactus",
           "kelp", "kelp_plant", "seagrass", "tall_seagrass", "sweet_berry_bush", "flower", "double_plant",
           "dandelion", "poppy", "sunflower", "lilac", "rose_bush", "peony", "lily_pad", "glow_lichen",
           "hanging_roots", "moss_carpet", "spore_blossom", "big_dripleaf", "small_dripleaf", "pointed_dripstone",
           "cave_vines", "cave_vines_plant", "azalea", "flowering_azalea", "sea_pickle", "coral", "coral_fan",
           "bamboo", "pitcher_plant", "torchflower", "pink_petals", "brown_mushroom", "red_mushroom"}


def _category(block) -> int:
    n = getattr(block, "base_name", "")
    if n in _AIR:
        return 0
    if n in _FLUID:
        return 9
    if n in _GROUND or n.endswith("_ore"):
        return 1
    if n.endswith(("_log", "_wood", "_stem", "_hyphae")) or n in ("log", "wood", "mushroom_stem",
                                                                   "brown_mushroom_block", "red_mushroom_block"):
        return 17
    if n.endswith("leaves") or n == "leaves":
        return 18
    if n in ("vine", "vines", "weeping_vines", "twisting_vines"):
        return 106
    if n in _PLANTS or n.endswith(("_flower", "_tulip", "_sapling", "_coral", "_coral_fan")):
        return 31
    return 4                                                  # built by players or structures


class DepthFit:
    """``bottom``: the lowest y kept (0: the underground is cut, -64: everything); ``compress``:
    the part over the target's ceiling comes down (False: it is cut)."""

    def __init__(self, bottom: int = 0, compress: bool = True, low: int = DEEP_BOTTOM, high: int = TOP):
        self.bottom = max(low, min(0, int(bottom)))
        self.dy = -self.bottom
        self.low, self.high = low, high
        self.height = high + self.dy                        # height of the moved column
        self.compress = compress and self.height > CEILING
        self.fit: Optional[HeightFit] = HeightFit(CEILING) if self.compress else None
        self.observed = 0
        self.used = False                                   # set when the blocks were moved (amulet_convert)

    @property
    def active(self) -> bool:
        return self.dy > 0 or self.compress

    # ------------------------------------------------------------------ proxy
    def _column(self, chunk) -> Tuple[np.ndarray, int]:
        """The chunk's blocks [x, y, z] from ``bottom`` to the top, and the y of index 0."""
        y0 = self.bottom
        n = self.high - y0
        arr = np.zeros((16, n, 16), np.uint32)
        for cy in chunk.blocks.sub_chunks:
            lo = cy * 16
            if lo + 16 <= y0 or lo >= self.high:
                continue
            sub = chunk.blocks.get_sub_chunk(cy)
            a, b = max(lo, y0), min(lo + 16, self.high)
            arr[:, a - y0:b - y0, :] = sub[:, a - lo:b - lo, :]
        return arr, y0

    def _proxy(self, chunk, arr: np.ndarray) -> NumericChunk:
        pal = chunk.block_palette
        lut = np.array([_category(pal[i]) for i in range(len(pal))] or [0], np.uint16)
        c = NumericChunk(chunk.cx, chunk.cz, arr.shape[1])
        c.blocks = np.transpose(lut[np.minimum(arr, len(lut) - 1)], (1, 2, 0))       # y, z, x
        c.data = np.zeros_like(c.blocks, dtype=np.uint8)
        return c

    # ------------------------------------------------------------------ passes
    def observe(self, chunk) -> None:
        """Pass 1 (only when compressing): the ground height of every column."""
        if self.fit is None:
            return
        arr, _ = self._column(chunk)
        self.fit.observe(self._proxy(chunk, arr))
        self.observed += 1

    def apply(self, chunk) -> None:
        """Pass 2: move the chunk (blocks, block entities, entities) into 0 .. 255."""
        arr, y0 = self._column(chunk)                       # index i = y - bottom = new y before fitting
        n = arr.shape[1]
        new_y = np.arange(n)
        src = None
        if self.fit is not None and self.fit.needed:
            proxy = self._proxy(chunk, arr)
            s = self.fit.shifts(chunk.cx, chunk.cz)            # [z, x]
            if s.any():
                start = self.fit._band_starts(proxy, s)        # [z, x]
                self.fit._starts[(chunk.cx, chunk.cz)] = start
                self.fit.moved_columns += int((s > 0).sum())
                y = np.arange(n)[None, :, None]
                src = np.where(y >= start.T[:, None, :], y + s.T[:, None, :], y)      # [x, y, z]
        if src is not None:
            inside = src < n
            out = np.take_along_axis(arr, np.minimum(src, n - 1), axis=1)
            arr = np.where(inside, out, 0).astype(np.uint32)
        top = min(n, CEILING)
        sections = {cy: np.ascontiguousarray(arr[:, cy * 16:cy * 16 + 16, :]) for cy in range(top // 16)
                    if arr[:, cy * 16:cy * 16 + 16, :].any()}
        chunk.blocks = sections
        self._move_objects(chunk, y0)
        self._move_biomes(chunk)
        chunk.changed = True

    def _new_y(self, cx: int, cz: int, x: float, y: float, z: float) -> Optional[float]:
        """New y of a point of the source world (None: it is dropped)."""
        if y < self.bottom:
            return None
        ny = y + self.dy
        if self.fit is not None and self.fit.needed:
            ny = self.fit.shift_at(x, ny, z)
        return ny if ny < CEILING else None

    def move_numeric(self, c) -> None:
        """A hub chunk whose block entities, ticks and entities were read again from the original
        world (worldbridge.extra): they follow the blocks, which this DepthFit already moved."""
        if not self.used:
            return                                          # Amulet's pass did not move the blocks
        cx, cz = c.cx, c.cz
        tiles = []
        for t in c.tile_entities:
            try:
                x, y, z = (int(nbt.get(t, k)) for k in ("x", "y", "z"))
            except (TypeError, ValueError):
                continue
            ny = self._new_y(cx, cz, x + 0.5, y, z + 0.5)
            if ny is not None:
                t["y"] = nbt.IntTag(int(ny))
                tiles.append(t)
        c.tile_entities = tiles
        ticks = []
        for t in getattr(c, "tile_ticks", None) or []:
            try:
                x, y, z = (int(nbt.get(t, k)) for k in ("x", "y", "z"))
            except (TypeError, ValueError):
                continue
            ny = self._new_y(cx, cz, x + 0.5, y, z + 0.5)
            if ny is not None:
                t["y"] = nbt.IntTag(int(ny))
                ticks.append(t)
        c.tile_ticks = ticks
        ents = []
        for e in c.entities:
            pos = nbt.get_tag(e, "Pos")
            if pos is None or len(pos) != 3:
                ents.append(e)
                continue
            x, y, z = (float(v.py_data) for v in pos)
            ny = self._new_y(cx, cz, x, y, z)
            if ny is None:
                continue
            e["Pos"] = nbt.ListTag([pos[0], nbt.DoubleTag(float(ny)), pos[2]], 6)
            ents.append(e)
        c.entities = ents

    def point(self, x: float, y: float, z: float) -> float:
        """Where a player or the spawn point lands (never dropped: clamped into the world)."""
        ny = y + self.dy
        if self.fit is not None and self.fit.needed:
            try:
                ny = self.fit.shift_at(x, ny, z)
            except KeyError:
                pass
        return float(min(max(ny, 1.0), CEILING - 2))

    def _move_objects(self, chunk, y0: int) -> None:
        cx, cz = chunk.cx, chunk.cz
        kept = []
        for be in list(chunk.block_entities.values()):
            ny = self._new_y(cx, cz, be.x + 0.5, be.y, be.z + 0.5)
            if ny is not None:
                kept.append(be.new_at_location(be.x, int(ny), be.z))
        chunk.block_entities = kept
        ents = []
        for e in list(chunk.entities):
            ny = self._new_y(cx, cz, e.x, e.y, e.z)
            if ny is not None:
                e.y = ny
                ents.append(e)
        chunk.entities = ents

    def _move_biomes(self, chunk) -> None:
        from amulet.api.chunk.biomes import BiomesShape

        b = chunk.biomes
        if b.dimension != BiomesShape.Shape3D:
            return
        raw = b.to_raw()[2] or {}
        shift = self.dy // 16
        moved: Dict[int, np.ndarray] = {}
        for cy, sec in raw.items():
            ny = cy + shift
            if 0 <= ny < CEILING // 16:
                moved[ny] = sec
        if moved:
            chunk.biomes = moved


def plan(target, deep_source: bool) -> Optional[DepthFit]:
    """The DepthFit of a conversion (None: nothing to do): a Caves & Cliffs source into a game whose
    world starts at y 0."""
    from .convert import CAVES_CLIFFS

    if not deep_source:
        return None
    if target.family in ("java", "bedrock"):
        if target.family == "java" and target.java_mode in ("auto", "dfu"):
            return None
        if target.family == "java" and target.java_mode == "amulet" and tuple(target.version or (99,)) >= CAVES_CLIFFS:
            return None
        if target.family == "bedrock" and tuple(target.version or (99,)) >= CAVES_CLIFFS:
            return None
    depth = getattr(target, "depth", "cut")
    bottom = DEEP_BOTTOM if depth == "keep" else 0 if depth in ("cut", None, "") else int(depth)
    fit = DepthFit(bottom, compress=getattr(target, "tall_terrain", "compress") == "compress")
    return fit if fit.active else None
