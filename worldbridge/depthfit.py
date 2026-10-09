"""Caves & Cliffs worlds (y -64 .. 319) into games whose world starts at y 0 (Java 1.2 - 1.17, LCE,
Bedrock up to 1.17, and through them the 128 high ones).

The user chooses how much of the underground to keep:

* ``auto`` (the default): flat or low worlds (superflat 1.18+ has its surface at y -61) are kept whole,
  the others are cut, see ``choose``;
* ``cut``: what lies under y 0 is dropped;
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
from .heightfit import KEEP, HeightFit
from .i18n import tr
from .model import NumericChunk

DEEP_BOTTOM = -64
TOP = 320                     # first y a Caves & Cliffs world cannot use
CEILING = 256                 # first y the targets cannot store
SAMPLE = 64                   # chunks of the Overworld whose surface ``auto`` looks at

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
        # block entities / entities of the source cut with their blocks: chunk -> (tiles, entities)
        self.lost: Dict[Tuple[int, int], Tuple[int, int]] = {}
        # chunks left without a single block: (cx, cz) -> True when the source had blocks, which the cut removed
        self.emptied: Dict[Tuple[int, int], bool] = {}

    @property
    def active(self) -> bool:
        return self.dy > 0 or self.compress

    # ------------------------------------------------------------------ proxy
    @staticmethod
    def _air(chunk) -> int:
        """The palette index of air in a chunk: its palette is built in whatever order its blocks come
        (a set, in Amulet's readers), so air is not always 0."""
        from amulet.api.block import Block

        return int(chunk.block_palette.get_add_block(Block("universal_minecraft", "air")))

    def _column(self, chunk) -> Tuple[np.ndarray, int]:
        """The chunk's blocks [x, y, z] from ``bottom`` to the top, and the y of index 0."""
        y0 = self.bottom
        n = self.high - y0
        arr = np.full((16, n, 16), self._air(chunk), np.uint32)
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
        air = self._air(chunk)
        if src is not None:
            inside = src < n
            out = np.take_along_axis(arr, np.minimum(src, n - 1), axis=1)
            arr = np.where(inside, out, air).astype(np.uint32)
        top = min(n, CEILING)
        sections = {cy: np.ascontiguousarray(arr[:, cy * 16:cy * 16 + 16, :]) for cy in range(top // 16)
                    if (arr[:, cy * 16:cy * 16 + 16, :] != air).any()}
        if not sections:
            # nothing left: told apart from a chunk that had no blocks at all
            self.emptied[(chunk.cx, chunk.cz)] = any(
                (chunk.blocks.get_sub_chunk(cy) != air).any() for cy in chunk.blocks.sub_chunks)
        chunk.blocks = sections
        self._move_objects(chunk, y0)
        self._move_biomes(chunk)
        chunk.changed = True

    def entity_y(self, x: float, y: float, z: float) -> Optional[float]:
        """New y of a point of the source world, an entity (inside the rock removed from a mountain it
        lands on the rock under it; None: it is dropped)."""
        if y < self.bottom:
            return None
        ny = y + self.dy
        if self.fit is not None and self.fit.needed:
            ny = self.fit.shift_at(x, ny, z)
        return ny if ny < CEILING else None

    def block_y(self, x: int, y: int, z: int) -> Optional[int]:
        """New y of the block at x, y, z of the source world, exactly where ``apply`` moves it (None:
        the block was cut: under ``bottom``, inside the band removed from a mountain, or over y 255)."""
        if y < self.bottom:
            return None
        ny = int(y) + self.dy
        if self.fit is not None and self.fit.needed:
            key = (int(x) >> 4, int(z) >> 4)
            lx, lz = int(x) & 15, int(z) & 15
            sh = int(self.fit.shifts(*key)[lz, lx])
            if sh:
                starts = self.fit._starts.get(key)
                a = int(starts[lz, lx]) if starts is not None else int(self.fit.heights[key][lz, lx]) - KEEP + 1 - sh
                if ny >= a + sh:
                    ny -= sh
                elif ny >= a:
                    return None                             # inside the removed band
        return ny if ny < CEILING else None

    def count_lost(self, cx: int, cz: int, lost_t: int, lost_e: int) -> None:
        # a chunk can be read more than once (heights, chest rows, writing): it counts once
        if lost_t or lost_e:
            self.lost[(cx, cz)] = (lost_t, lost_e)
        else:
            self.lost.pop((cx, cz), None)

    @property
    def lost_tiles(self) -> int:
        return sum(t for t, _e in self.lost.values())

    @property
    def lost_entities(self) -> int:
        return sum(e for _t, e in self.lost.values())

    def move_numeric(self, c) -> Tuple[int, int]:
        """A hub chunk whose block entities, ticks and entities were read again from the original
        world (worldbridge.extra), at their height there: they follow the blocks, which this DepthFit
        already moved, and those whose blocks were cut are dropped.  Returns how many block entities
        and entities were dropped."""
        if not self.used:
            return 0, 0                                     # Amulet's pass did not move the blocks
        lost_t = lost_e = 0
        tiles = []
        for t in c.tile_entities:
            try:
                x, y, z = (int(nbt.get(t, k)) for k in ("x", "y", "z"))
            except (TypeError, ValueError):
                continue
            ny = self.block_y(x, y, z)
            if ny is None:
                lost_t += 1
                continue
            t["y"] = nbt.IntTag(ny)
            tiles.append(t)
        c.tile_entities = tiles
        ticks = []
        for t in getattr(c, "tile_ticks", None) or []:
            try:
                x, y, z = (int(nbt.get(t, k)) for k in ("x", "y", "z"))
            except (TypeError, ValueError):
                continue
            ny = self.block_y(x, y, z)
            if ny is not None:
                t["y"] = nbt.IntTag(ny)
                ticks.append(t)
        c.tile_ticks = ticks
        ents = []
        for e in c.entities:
            if self._move_legacy_entity(e):
                ents.append(e)
            else:
                lost_e += 1
        c.entities = ents
        return lost_t, lost_e

    def _move_legacy_entity(self, e) -> bool:
        """Move a hub (Java 1.12) entity and its passengers; False: it is dropped.  Paintings and item
        frames follow the block they hang on (TileY), the others the ground under them."""
        pos = nbt.get_tag(e, "Pos")
        if pos is None or len(pos) != 3:
            return True
        x, y, z = (float(v.py_data) for v in pos)
        if "TileY" in e:
            try:
                tx, ty, tz = (int(nbt.get(e, k)) for k in ("TileX", "TileY", "TileZ"))
            except (TypeError, ValueError):
                return False
            nty = self.block_y(tx, ty, tz)
            if nty is None:
                return False
            e["TileY"] = nbt.IntTag(nty)
            ny = y + (nty - ty)
        else:
            ny = self.entity_y(x, y, z)
            if ny is None:
                return False
        e["Pos"] = nbt.pos_list(x, ny, z)
        for p in nbt.get_tag(e, "Passengers") or []:
            self._move_legacy_entity(p)
        return True

    def move_canon(self, cx: int, cz: int, tl: list, el: list) -> Tuple[list, list]:
        """The same for the canonical block entities / entities (worldbridge.tiles / entities) of an
        overworld chunk of the source, which go straight into the target (Amulet to Amulet)."""
        if not self.used:
            return tl, el                                   # Amulet's pass did not move the blocks
        tiles, ents = [], []
        lost_t = lost_e = 0
        for t in tl:
            x, y, z = t["pos"]
            ny = self.block_y(int(x), int(y), int(z))
            if ny is None:
                lost_t += 1
                continue
            tiles.append(dict(t, pos=(x, ny, z)))
        for e in el:
            x, y, z = e["pos"]
            tile = e.get("tile")
            if tile is not None and e.get("name") in ("painting", "item_frame", "glow_item_frame"):
                tx, ty, tz = tile
                nty = self.block_y(int(tx), int(ty), int(tz))
                if nty is None:
                    lost_e += 1
                    continue
                ents.append(dict(e, pos=(x, y + (nty - ty), z), tile=(tx, nty, tz)))
                continue
            ny = self.entity_y(x, y, z)
            if ny is None:
                lost_e += 1
                continue
            moved = dict(e, pos=(x, float(ny), z))
            if isinstance(e.get("poi"), dict):                   # a villager's bed / bell / job site go with their blocks
                poi = {}
                for k, (px, py, pz) in e["poi"].items():
                    npy = self.block_y(int(px), int(py), int(pz))
                    if npy is not None:
                        poi[k] = (px, npy, pz)
                moved["poi"] = poi
            ents.append(moved)
        self.count_lost(cx, cz, lost_t, lost_e)
        return tiles, ents

    def surface(self, chunk) -> np.ndarray:
        """y of the top block (plants, trees, buildings and water count) of every column of a source
        chunk that has any block."""
        arr, y0 = self._column(chunk)
        solid = self._proxy(chunk, arr).blocks != 0                      # y, z, x
        top = solid.shape[0] - 1 - np.argmax(solid[::-1], axis=0)
        return top[solid.any(axis=0)].astype(np.int32) + y0

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
        kept = []
        for be in list(chunk.block_entities.values()):
            ny = self.block_y(be.x, be.y, be.z)
            if ny is not None:
                kept.append(be.new_at_location(be.x, int(ny), be.z))
        chunk.block_entities = kept
        ents = []
        for e in list(chunk.entities):
            ny = self.entity_y(e.x, e.y, e.z)
            if ny is not None:
                e.y = ny
                ents.append(e)
        chunk.entities = ents
        self._move_native(chunk)

    def _move_native(self, chunk) -> None:
        """The entities the source's reader left in their own format (Amulet translates them when it
        writes the target): their NBT holds the position."""
        from amulet.api.chunk.entity_list import EntityList

        native = getattr(chunk, "_native_entities", None)
        if not native:
            return
        kept = []
        for e in list(native):
            tag = getattr(e.nbt, "compound", None) or e.nbt.tag
            pos = tag.get("Pos") if hasattr(tag, "get") else None
            ny = self.entity_y(e.x, e.y, e.z)
            if ny is None:
                continue
            e.y = ny
            if pos is not None and len(pos) == 3:
                pos[1] = type(pos[1])(ny)
            kept.append(e)
        chunk._native_entities = EntityList(kept)

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


def sample_surface(level) -> np.ndarray:
    """y of the top block of the columns of a sample of the Overworld's chunks (a loaded Amulet level):
    ``SAMPLE`` chunks spread over the world; when they hold little (a void world with a few builds),
    others are added, up to ``8 * SAMPLE`` chunks."""
    probe = DepthFit(DEEP_BOTTOM, compress=False)
    coords = sorted(level.level_wrapper.all_chunk_coords("minecraft:overworld"))
    step = max(1, -(-len(coords) // SAMPLE))
    got, columns, loaded = [], 0, 0
    for phase in range(step):
        for cx, cz in coords[phase::step]:
            try:
                top = probe.surface(level.level_wrapper.load_chunk(cx, cz, "minecraft:overworld"))
            except Exception:  # noqa: BLE001
                continue
            loaded += 1
            columns += len(top)
            got.append(top)
        if columns >= 16 * 256 or loaded >= 8 * SAMPLE:
            break
    return np.concatenate(got) if got else np.zeros(0, np.int32)


def decide(tops: np.ndarray) -> Tuple[int, str]:
    """The ``auto`` depth for a world whose sampled columns have their top block at ``tops``: (bottom, why).
    A flat or low world (the median top under y 0: superflat 1.18+ has its surface at y -61) is kept
    whole, the others are cut.  ``why`` is the line for the log."""
    if not len(tops):
        return 0, tr("Underground (automatic): no blocks found in the sampled chunks, what lies below y 0 is cut "
                     "(--depth keep keeps it).")
    median = int(np.median(tops))
    if median < 0:
        return DEEP_BOTTOM, tr("Underground (automatic): the surface of this world is mostly below y 0 (median y {y}): "
                               "the whole underground is kept and the world rises by 64 blocks.", y=median)
    return 0, tr("Underground (automatic): the surface of this world is above y 0 (median y {y}): what lies below y 0 "
                 "is cut (--depth keep keeps it).", y=median)


def choose(path: str) -> Tuple[int, str]:
    """The ``auto`` depth of the Caves & Cliffs world at ``path``, from a sample of its chunks."""
    from . import amulet_bridge as ab

    level = ab.load_level(path)
    try:
        tops = sample_surface(level)
    except Exception:  # noqa: BLE001
        tops = np.zeros(0, np.int32)
    finally:
        level.close()
    return decide(tops)


def plan(target, deep_source: bool, path: Optional[str] = None, progress=None) -> Optional[DepthFit]:
    """The DepthFit of a conversion (None: nothing to do): a Caves & Cliffs source into a game whose
    world starts at y 0.  ``path``: the source world, which ``auto`` looks at."""
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
    depth = getattr(target, "depth", "auto")
    if depth in ("auto", None, "") and path is not None:
        bottom, why = choose(path)
        if progress is not None:
            progress.log(why)
    elif depth == "keep":
        bottom = DEEP_BOTTOM
    elif depth in ("auto", "cut", None, ""):
        bottom = 0
    else:
        bottom = int(depth)
    fit = DepthFit(bottom, compress=getattr(target, "tall_terrain", "compress") == "compress")
    return fit if fit.active else None
