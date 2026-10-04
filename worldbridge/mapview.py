"""Top-down map of any supported world (the "Mappa" tab).

For every chunk the visible top block of each column is found and coloured, MCA Selector
style: one pixel per block, shaded by the height difference with the block to the north and
darkened with the water depth.  Every source format is read natively and quickly:

* numeric worlds (LCE, Java 1.2-1.12, Alpha/McRegion, Pocket Edition, Classic/Indev) through
  the hub reader used by the converter;
* Java 1.13+ (also the 26.1+ ``dimensions/`` layout) by parsing the region files directly;
* Bedrock 1.2.13+ by parsing the sub-chunks in LevelDB (older Bedrock falls back to Amulet).
"""

from __future__ import annotations

import functools
import os
import re
import shutil
import struct
import tempfile
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from . import nbt
from .model import NETHER, OVERWORLD, THE_END, Progress
from .i18n import tr

AIR = frozenset({"air", "cave_air", "void_air", "structure_void", "light", "barrier", "moving_piston"})
WATERY = frozenset({"water", "flowing_water", "bubble_column", "kelp", "kelp_plant", "seagrass", "tall_seagrass",
                    "stationary_water"})

# --------------------------------------------------------------------------- colours
# Minecraft map colours (MapColor) for the families of blocks, then exact names.
_DYES = {
    "white": (242, 242, 242), "orange": (216, 127, 51), "magenta": (178, 76, 216), "light_blue": (102, 153, 216),
    "yellow": (229, 229, 51), "lime": (127, 204, 25), "pink": (242, 127, 165), "gray": (76, 76, 76),
    "light_gray": (153, 153, 153), "silver": (153, 153, 153), "cyan": (76, 127, 153), "purple": (127, 63, 178),
    "blue": (51, 76, 178), "brown": (102, 76, 51), "green": (102, 127, 51), "red": (153, 51, 51),
    "black": (25, 25, 25),
}
_EXACT = {
    "grass_block": (127, 178, 56), "grass": (127, 178, 56), "short_grass": (104, 160, 46), "tall_grass": (104, 160, 46),
    "fern": (96, 150, 44), "large_fern": (96, 150, 44), "tallgrass": (104, 160, 46), "double_plant": (110, 165, 50),
    "dirt": (151, 109, 77), "coarse_dirt": (140, 100, 70), "rooted_dirt": (140, 100, 70), "farmland": (120, 84, 55),
    "podzol": (122, 88, 50), "mycelium": (127, 100, 120), "dirt_path": (148, 122, 65), "grass_path": (148, 122, 65),
    "mud": (70, 60, 60), "clay": (164, 168, 184), "gravel": (136, 126, 126),
    "sand": (247, 233, 163), "sandstone": (237, 222, 157), "red_sand": (190, 102, 33), "red_sandstone": (180, 98, 35),
    "snow": (255, 255, 255), "snow_layer": (255, 255, 255), "snow_block": (255, 255, 255), "powder_snow": (250, 250, 255),
    "ice": (160, 160, 255), "packed_ice": (150, 150, 250), "blue_ice": (130, 140, 250), "frosted_ice": (160, 160, 255),
    "water": (64, 64, 255), "flowing_water": (64, 64, 255), "lava": (255, 90, 0), "flowing_lava": (255, 90, 0),
    "stone": (112, 112, 112), "cobblestone": (104, 104, 104), "mossy_cobblestone": (90, 110, 90),
    "andesite": (125, 125, 125), "diorite": (190, 190, 190), "granite": (150, 105, 85), "tuff": (100, 100, 90),
    "deepslate": (70, 70, 75), "calcite": (215, 215, 210), "bedrock": (60, 60, 60), "obsidian": (20, 18, 30),
    "netherrack": (112, 2, 0), "soul_sand": (84, 64, 51), "soul_soil": (76, 58, 46), "glowstone": (248, 212, 120),
    "magma_block": (130, 40, 10), "nether_wart_block": (120, 10, 10), "warped_wart_block": (22, 126, 134),
    "crimson_nylium": (130, 25, 30), "warped_nylium": (40, 110, 100), "basalt": (80, 80, 85), "blackstone": (40, 35, 40),
    "end_stone": (221, 223, 165), "purpur_block": (170, 125, 170), "chorus_plant": (100, 70, 110),
    "oak_leaves": (60, 130, 40), "leaves": (60, 130, 40), "leaves2": (60, 120, 35), "spruce_leaves": (50, 90, 50),
    "birch_leaves": (90, 140, 60), "jungle_leaves": (40, 140, 30), "acacia_leaves": (70, 130, 40),
    "dark_oak_leaves": (40, 100, 30), "mangrove_leaves": (60, 120, 40), "cherry_leaves": (240, 170, 200),
    "azalea_leaves": (90, 130, 50), "flowering_azalea_leaves": (120, 130, 80), "pale_oak_leaves": (140, 150, 140),
    "vine": (60, 120, 30), "vines": (60, 120, 30), "lily_pad": (30, 110, 40), "waterlily": (30, 110, 40),
    "cactus": (30, 110, 30), "sugar_cane": (140, 190, 90), "reeds": (140, 190, 90), "bamboo": (100, 150, 40),
    "pumpkin": (216, 127, 51), "carved_pumpkin": (216, 127, 51), "melon": (120, 160, 40), "hay_block": (200, 170, 50),
    "crafting_table": (140, 105, 60), "furnace": (95, 95, 95), "chest": (160, 115, 50), "trapped_chest": (160, 115, 50),
    "torch": (255, 214, 90), "wall_torch": (255, 214, 90), "glass": (200, 220, 230), "glass_pane": (200, 220, 230),
    "bookshelf": (130, 95, 55), "brick_block": (150, 70, 55), "bricks": (150, 70, 55), "tnt": (220, 50, 30),
    "iron_block": (220, 220, 220), "gold_block": (250, 238, 77), "diamond_block": (92, 219, 213),
    "emerald_block": (0, 217, 58), "lapis_block": (74, 128, 255), "redstone_block": (200, 20, 10),
    "coal_block": (20, 20, 20), "quartz_block": (240, 238, 232), "prismarine": (90, 160, 150), "sea_lantern": (200, 230, 230),
    "rail": (150, 130, 100), "powered_rail": (170, 140, 80), "detector_rail": (150, 120, 110), "activator_rail": (150, 110, 100),
    "spawner": (40, 60, 80), "mob_spawner": (40, 60, 80), "cobweb": (220, 220, 220), "web": (220, 220, 220),
    "mushroom_stem": (200, 190, 170), "red_mushroom_block": (180, 40, 35), "brown_mushroom_block": (150, 110, 80),
    "brown_mushroom_block_legacy": (150, 110, 80), "dead_bush": (140, 110, 60), "deadbush": (140, 110, 60),
    "terracotta": (152, 94, 67), "hardened_clay": (152, 94, 67), "stained_hardened_clay": (160, 100, 80),
    "moss_block": (90, 120, 40), "moss_carpet": (90, 120, 40), "sculk": (15, 40, 45), "dripstone_block": (130, 100, 85),
    "beacon": (120, 220, 220), "enchanting_table": (80, 30, 40), "anvil": (70, 70, 70), "cauldron": (60, 60, 60),
}
_KEYWORDS = [  # (substring, colour) – checked in order after the exact table
    ("water", (64, 64, 255)), ("lava", (255, 90, 0)), ("leaves", (60, 125, 40)), ("sapling", (70, 140, 50)),
    ("coral", (220, 100, 140)), ("kelp", (40, 100, 60)), ("seagrass", (40, 110, 60)), ("glass", (200, 220, 230)),
    ("_log", (110, 85, 50)), ("_wood", (110, 85, 50)), ("stem", (120, 90, 110)), ("hyphae", (120, 90, 110)),
    ("planks", (160, 130, 80)), ("_slab", (150, 135, 110)), ("_stairs", (150, 135, 110)), ("fence", (143, 119, 72)),
    ("door", (143, 119, 72)), ("trapdoor", (143, 119, 72)), ("sign", (143, 119, 72)), ("bed", (170, 40, 40)),
    ("carpet", (200, 200, 200)), ("wool", (230, 230, 230)), ("concrete", (180, 180, 180)), ("terracotta", (152, 94, 67)),
    ("flower", (200, 60, 60)), ("tulip", (220, 90, 60)), ("rose", (200, 30, 30)), ("poppy", (200, 30, 30)),
    ("dandelion", (240, 220, 40)), ("orchid", (60, 160, 220)), ("allium", (180, 110, 220)), ("daisy", (230, 230, 200)),
    ("mushroom", (170, 90, 70)), ("wheat", (200, 180, 70)), ("carrots", (220, 140, 40)), ("potatoes", (200, 170, 70)),
    ("beetroot", (150, 40, 50)), ("crop", (180, 160, 60)), ("ore", (120, 120, 120)), ("deepslate", (70, 70, 75)),
    ("sandstone", (237, 222, 157)), ("sand", (247, 233, 163)), ("nether_brick", (60, 25, 30)), ("quartz", (240, 238, 232)),
    ("brick", (150, 70, 55)), ("stone", (112, 112, 112)), ("cobble", (104, 104, 104)), ("snow", (255, 255, 255)),
    ("ice", (160, 160, 255)), ("prismarine", (90, 160, 150)), ("purpur", (170, 125, 170)), ("copper", (190, 110, 80)),
    ("amethyst", (150, 100, 200)), ("rail", (150, 130, 100)), ("torch", (255, 214, 90)), ("lantern", (230, 180, 90)),
    ("grass", (110, 165, 50)), ("dirt", (151, 109, 77)), ("mud", (70, 60, 60)), ("gold", (250, 238, 77)),
    ("iron", (200, 200, 200)), ("diamond", (92, 219, 213)), ("emerald", (0, 217, 58)), ("redstone", (180, 20, 10)),
    ("button", (140, 140, 140)), ("pressure_plate", (140, 140, 140)), ("wall", (110, 110, 110)), ("pane", (200, 220, 230)),
    ("shulker", (140, 100, 140)), ("candle", (230, 210, 170)), ("banner", (200, 200, 200)), ("head", (120, 120, 120)),
    ("skull", (120, 120, 120)), ("chest", (160, 115, 50)), ("barrel", (140, 100, 55)), ("pot", (130, 70, 50)),
]
_DYE_FAMILIES = ("wool", "carpet", "concrete_powder", "concrete", "terracotta", "stained_glass_pane", "stained_glass",
                 "shulker_box", "bed", "banner", "candle", "glazed_terracotta")


@functools.lru_cache(maxsize=4096)
def block_color(name: str) -> Tuple[int, int, int]:
    """Map colour of a block (any namespace / edition naming)."""
    n = name.split(":", 1)[-1].lower()
    if n in _EXACT:
        return _EXACT[n]
    for dye in sorted(_DYES, key=len, reverse=True):
        if n.startswith(dye + "_") and n[len(dye) + 1:] in _DYE_FAMILIES:
            r, g, b = _DYES[dye]
            if "terracotta" in n and "glazed" not in n:  # terracotta colours are muted
                return (int(r * 0.7 + 40), int(g * 0.6 + 30), int(b * 0.6 + 20))
            return _DYES[dye]
    for key, col in _KEYWORDS:
        if key in n:
            return col
    return (150, 150, 150)


def is_air(name: str) -> bool:
    return name.split(":", 1)[-1] in AIR


def is_watery(name: str) -> bool:
    return name.split(":", 1)[-1] in WATERY


@functools.lru_cache(maxsize=65536)
def numeric_name(bid: int, data: int) -> str:
    """Name for a Java 1.12 numeric block (used for LCE / old Java / Pocket Edition)."""
    if bid == 0:
        return "air"
    if bid in (8, 9):
        return "water"
    if bid in (10, 11):
        return "lava"
    try:
        from .items import legacy_block_item_name

        name = legacy_block_item_name(bid, data)
    except Exception:  # noqa: BLE001
        name = None
    if not name:
        from . import ids

        name = ids.java_block_names().get(bid, f"block_{bid}")
    return name


# --------------------------------------------------------------------------- tiles


@dataclass
class Tile:
    """Top view of one chunk: [z, x] arrays."""

    color: np.ndarray          # uint8 [16,16,3] base colour of the top block
    height: np.ndarray         # int16 [16,16] y of the top block (-32768 = nothing)
    depth: np.ndarray          # int16 [16,16] water depth above the first solid block
    names: List[str]           # palette of the top blocks
    index: np.ndarray          # uint16 [16,16] -> names

    def name_at(self, lx: int, lz: int) -> str:
        return self.names[int(self.index[lz, lx])] if self.names else "?"


EMPTY_HEIGHT = -32768


def _below_roof(mask: np.ndarray, roof: int) -> np.ndarray:
    """Nether: hide the bedrock ceiling - keep only what lies below the first air gap under ``roof``."""
    top = min(roof, mask.shape[0])
    rev = ~mask[:top][::-1]                       # air, scanning down from the roof
    has_gap = rev.any(axis=0)
    gap = top - 1 - np.argmax(rev, axis=0)        # highest air block below the roof
    ys = np.arange(mask.shape[0])[:, None, None]
    return mask & (ys < np.where(has_gap, gap, -1)[None])


def _tile_core(keys: np.ndarray, air: np.ndarray, water: np.ndarray, name_of, ymin: int = 0,
               roof: Optional[int] = None) -> Optional[Tile]:
    """``keys`` [H,16,16] block keys; ``air``/``water`` boolean look-up tables indexed by key."""
    mask = ~air[keys]
    if roof is not None:
        mask = _below_roof(mask, roof - ymin)
    has = mask.any(axis=0)
    if not has.any():
        return None
    h = keys.shape[0]
    top = (h - 1 - np.argmax(mask[::-1], axis=0)).astype(np.int32)
    solid = mask & ~water[keys]
    has_solid = solid.any(axis=0)
    stop = (h - 1 - np.argmax(solid[::-1], axis=0)).astype(np.int32)
    zz, xx = np.indices((16, 16))
    tk = keys[top, zz, xx]
    uniq, inv = np.unique(tk, return_inverse=True)
    names = [name_of(int(k)) for k in uniq]
    index = inv.reshape(16, 16).astype(np.uint16)
    color = np.array([block_color(n) for n in names], np.uint8)[index]
    is_w = water[uniq][index] & has
    depth = np.where(is_w, np.where(has_solid, top - stop, 32), 0)
    height = np.where(has, top + ymin, EMPTY_HEIGHT).astype(np.int16)
    return Tile(color, height, np.clip(depth, 0, 255).astype(np.int16), names, index)


def _section_idx(idx) -> np.ndarray:
    """A section's palette indices, unpacked only now when they are given as a function."""
    return idx() if callable(idx) else idx


def tile_from_sections(sections: Iterable[Tuple[int, np.ndarray, Sequence[str]]], roof: Optional[int] = None) -> Optional[Tile]:
    """``sections`` = (section_y, palette indices [16(y),16(z),16(x)] or a function giving them,
    palette names), any order."""
    sections = [s for s in sections if len(s[2])]
    if not sections:
        return None
    pos: Dict[str, int] = {}
    ymin = min(s[0] for s in sections)
    ymax = max(s[0] for s in sections)
    pos["air"] = 0
    luts = [np.array([pos.setdefault(n, len(pos)) for n in pal], np.int32) for _sy, _idx, pal in sections]
    names = sorted(pos, key=pos.get)
    air = np.array([is_air(n) for n in names], bool)
    water = np.array([is_watery(n) for n in names], bool)
    if roof is None and len({s[0] for s in sections}) == len(sections):
        return _tile_top_down(sections, luts, air, water, names, ymin, ymax)
    keys = np.zeros(((ymax - ymin + 1) * 16, 16, 16), np.int32)
    for (sy, idx, _pal), lut in zip(sections, luts):
        keys[(sy - ymin) * 16:(sy - ymin) * 16 + 16] = lut[np.clip(_section_idx(idx), 0, len(lut) - 1)]
    return _tile_core(keys, air, water, lambda k: names[k], ymin * 16, roof)


def _tile_top_down(sections, luts, air: np.ndarray, water: np.ndarray, names: List[str], ymin: int,
                   ymax: int) -> Optional[Tile]:
    """``_tile_core`` for a column of sections without a roof, looking at the sections from the top
    down and only as far as needed: the top block of every column and the first solid one under it
    are usually in the highest two or three sections, the rest is never unpacked.  Same tile."""
    by_y = {s[0]: (s[1], lut) for s, lut in zip(sections, luts)}
    top = np.full((16, 16), -1, np.int32)          # y (from ymin * 16) of the top block, -1 = none yet
    stop = np.full((16, 16), -1, np.int32)         # y of the highest solid block
    tk = None                                      # key of the top block ([z, x])
    first = True
    for sy in range(ymax, ymin - 1, -1):
        sec = by_y.get(sy)
        if sec is None:
            continue                               # a missing section is air
        idx, lut = sec
        keys = lut[np.clip(_section_idx(idx), 0, len(lut) - 1)]           # [y, z, x]
        if first:
            tk = keys[15].copy()                   # columns without any block: the top layer's key
            first = False
        base = (sy - ymin) * 16
        mask = ~air[keys]
        solid = mask & ~water[keys]
        need_top = top < 0
        if need_top.any():
            has = mask.any(axis=0) & need_top
            if has.any():
                ly = 15 - np.argmax(mask[::-1], axis=0)
                top = np.where(has, base + ly, top)
                zz, xx = np.nonzero(has)
                tk[zz, xx] = keys[ly[zz, xx], zz, xx]
        need_stop = (stop < 0) & (top >= 0)
        if need_stop.any():
            hs = solid.any(axis=0) & (stop < 0)
            stop = np.where(hs, base + 15 - np.argmax(solid[::-1], axis=0), stop)
        if (stop >= 0).all():
            break
    has = top >= 0
    if tk is None or not has.any():
        return None
    has_solid = stop >= 0
    uniq, inv = np.unique(tk, return_inverse=True)
    tnames = [names[int(k)] for k in uniq]
    index = inv.reshape(16, 16).astype(np.uint16)
    color = np.array([block_color(n) for n in tnames], np.uint8)[index]
    is_w = water[uniq][index] & has
    depth = np.where(is_w, np.where(has_solid, top - stop, 32), 0)
    height = np.where(has, top + ymin * 16, EMPTY_HEIGHT).astype(np.int16)
    return Tile(color, height, np.clip(depth, 0, 255).astype(np.int16), tnames, index)


_NUM_AIR = np.zeros(65536, bool)
_NUM_AIR[:16] = True
_NUM_WATER = np.zeros(65536, bool)
_NUM_WATER[8 * 16:10 * 16] = True


def tile_from_numeric(c, roof: Optional[int] = None) -> Optional[Tile]:
    """Tile of a hub :class:`NumericChunk` ([y,z,x] numeric ids)."""
    blocks = np.asarray(c.blocks).astype(np.int32)
    data = np.asarray(c.data).astype(np.int32) if c.data is not None else np.zeros_like(blocks)
    keys = (blocks & 4095) * 16 + (data & 15)
    tile = _tile_core(keys, _NUM_AIR, _NUM_WATER, lambda k: numeric_name(k >> 4, k & 15), 0, roof)
    if tile is None:
        return None
    for (x, y, z), state in (getattr(c, "modern_blocks", None) or {}).items():  # LCE Aquatic blocks
        if 0 <= x < 16 and 0 <= z < 16 and tile.height[z, x] == y:
            nm = state.split("[", 1)[0]
            if nm not in tile.names:
                tile.names.append(nm)
            tile.index[z, x] = tile.names.index(nm)
            tile.color[z, x] = block_color(nm)
    return tile


def _roof(dim: int) -> Optional[int]:
    return 127 if dim == NETHER else None


def shade(tile: Tile, north: Optional[np.ndarray] = None) -> np.ndarray:
    """RGB image [16,16,3] with map-like relief shading and water depth."""
    h = tile.height.astype(np.int32)
    prev = np.empty_like(h)
    prev[1:] = h[:-1]
    prev[0] = north if north is not None else h[0]
    f = np.where(h > prev, 1.0, np.where(h < prev, 0.78, 0.9))
    water = tile.depth > 0
    f = np.where(water, 1.0 - np.clip(tile.depth, 0, 30) / 30.0 * 0.55, f)
    img = np.clip(tile.color.astype(np.float32) * f[..., None], 0, 255).astype(np.uint8)
    img[h == EMPTY_HEIGHT] = 0
    return img


# --------------------------------------------------------------------------- sources


@dataclass
class PlayerEntry:
    key: str                               # id in the source (file name / "host" / Bedrock key)
    label: str                             # human readable description
    pos: Optional[Tuple[float, float, float]] = None
    dim: int = 0
    name: Optional[str] = None             # known nickname, if the world stores it
    items: int = 0                         # inventory size (helps telling anonymous players apart)


@dataclass
class MapSource:
    path: str
    kind: str
    description: str = ""
    spawn: Tuple[int, int, int] = (0, 64, 0)
    players: List[PlayerEntry] = field(default_factory=list)
    tmp: Optional[str] = None

    def dimensions(self) -> List[int]:
        raise NotImplementedError

    def chunk_coords(self, dim: int) -> List[Tuple[int, int]]:
        raise NotImplementedError

    def tile(self, dim: int, cx: int, cz: int) -> Optional[Tile]:
        raise NotImplementedError

    def close(self):
        if self.tmp:
            shutil.rmtree(self.tmp, ignore_errors=True)
            self.tmp = None


_SONY_NAME = re.compile(r"^P_[0-9A-Fa-f]+_[0-9A-Fa-f]+_(.+?)_?$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def known_names(world: str) -> Dict[str, str]:
    """uuid -> name from a server's usercache.json (next to or above the world folder)."""
    import json

    out: Dict[str, str] = {}
    for folder in (world, os.path.dirname(os.path.abspath(world))):
        f = os.path.join(folder, "usercache.json")
        if os.path.isfile(f):
            try:
                for e in json.load(open(f, encoding="utf-8")):
                    out[str(e.get("uuid", "")).lower()] = str(e.get("name", ""))
            except Exception:  # noqa: BLE001
                pass
    return out


def _player_entries(players: Dict[str, nbt.CompoundTag], names: Optional[Dict[str, str]] = None) -> List[PlayerEntry]:
    out = []
    for key, p in players.items():
        pos = None
        pl = nbt.get_tag(p, "Pos")
        if pl is not None and len(pl) == 3:
            pos = tuple(float(v.py_data) for v in pl)
        dim = nbt.get(p, "Dimension", 0)
        if isinstance(dim, str):
            dim = {"minecraft:the_nether": -1, "minecraft:the_end": 1}.get(dim, 0)
        name = None
        for k in ("bukkit", "Paper"):
            b = nbt.get_tag(p, k)
            if isinstance(b, nbt.CompoundTag) and nbt.get(b, "lastKnownName"):
                name = str(nbt.get(b, "lastKnownName"))
        m = _SONY_NAME.match(key)
        if not name and m:  # PlayStation saves: P_<id>_<n>_<PSN name>
            name = m.group(1)
        if not name and names and _UUID_RE.match(key):
            name = names.get(key.lower())
        label = tr("Main player") if key in ("host", "~local_player") else key
        if name:
            label += f" ({name})"
        inv = nbt.get_tag(p, "Inventory")
        out.append(PlayerEntry(key, label, pos, int(dim or 0), name, len(inv) if inv is not None else 0))
    return out


class HubMapSource(MapSource):
    """Numeric worlds, read through the converter's own hub readers."""

    def __init__(self, path: str, kind: str, world, description: str):
        super().__init__(path, kind, description)
        self.world = world
        self.spawn = tuple(world.info.spawn)
        self.players = _player_entries(world.info.players)

    def dimensions(self):
        return list(self.world.dimensions())

    def chunk_coords(self, dim):
        return list(self.world.chunk_coords(dim))

    def tile(self, dim, cx, cz):
        c = self.world.read_chunk(dim, cx, cz)
        return tile_from_numeric(c, _roof(dim)) if c is not None else None

    def close(self):
        try:
            self.world.close()
        finally:
            super().close()


_REGION_RE = re.compile(r"^r\.(-?\d+)\.(-?\d+)\.mca$")


def _unpack(longs: np.ndarray, bits: int, count: int, spanning: bool) -> np.ndarray:
    raw = np.ascontiguousarray(longs.astype("<i8")).view("<u8")
    if spanning:
        bitarr = np.unpackbits(raw.view(np.uint8), bitorder="little")[:count * bits]
        if bitarr.size < count * bits:
            bitarr = np.concatenate([bitarr, np.zeros(count * bits - bitarr.size, np.uint8)])
        weights = (1 << np.arange(bits, dtype=np.uint64))
        return (bitarr.reshape(count, bits).astype(np.uint64) * weights).sum(axis=1).astype(np.int64)
    per = 64 // bits
    shifts = np.arange(per, dtype=np.uint64) * np.uint64(bits)
    vals = (raw[:, None] >> shifts[None, :]) & np.uint64((1 << bits) - 1)
    return vals.reshape(-1)[:count].astype(np.int64)


def _palette_names(pal) -> List[str]:
    return [nbt.state_name(p, "air") for p in pal or []]


def java_chunk_tile(root: nbt.CompoundTag, roof: Optional[int] = None) -> Optional[Tile]:
    """Tile of a Java 1.13+ chunk (1.13-1.17 ``Level.Sections`` or 1.18+ ``sections``)."""
    dv = int(nbt.get(root, "DataVersion", 0) or 0)
    level = nbt.get_tag(root, "Level")
    secs = []
    if level is not None and nbt.get_tag(level, "Sections") is not None:
        spanning = dv < 2527
        for s in nbt.get_tag(level, "Sections"):
            pal = _palette_names(nbt.get_tag(s, "Palette"))
            states = nbt.get_tag(s, "BlockStates")
            if not pal:
                continue
            secs.append((int(nbt.get(s, "Y", 0)), _lazy_indices(states, len(pal), spanning), pal))
    else:
        for s in nbt.get_tag(root, "sections") or []:
            bs = nbt.get_tag(s, "block_states")
            if bs is None:
                continue
            pal = _palette_names(nbt.get_tag(bs, "palette"))
            data = nbt.get_tag(bs, "data")
            if not pal:
                continue
            secs.append((int(nbt.get(s, "Y", 0)), _lazy_indices(data, len(pal), False), pal))
    return tile_from_sections(secs, roof)


_ZERO_IDX = np.zeros((16, 16, 16), np.int64)
_ZERO_IDX.setflags(write=False)


def _lazy_indices(states, n_pal: int, spanning: bool):
    """The palette indices [y, z, x] of a section, unpacked only when the map needs that section."""
    if states is None or n_pal == 1:
        return _ZERO_IDX

    def unpack():
        bits = max(4, int(n_pal - 1).bit_length())
        return _unpack(np.asarray(states.np_array), bits, 4096, spanning).reshape(16, 16, 16)
    return unpack


class JavaModernMapSource(MapSource):
    def __init__(self, path: str, description: str):
        super().__init__(path, "java_modern", description)
        from .extra import read_amulet_info
        from .detect import Detected

        info = read_amulet_info(Detected(kind="java_modern", description=description, path=path))
        self.spawn = tuple(info.spawn)
        self.players = _player_entries(info.players, known_names(path))
        self._index: Dict[int, object] = {}          # dim -> java.region.ChunkIndex
        self._cache: Dict[str, object] = {}

    def _folder(self, dim: int) -> str:
        from .java.modern import _folder

        return _folder(self.path, dim, "region")

    def _scan(self, dim: int):
        if dim in self._index:
            return self._index[dim]
        from .java.region import ChunkIndex

        out = ChunkIndex()
        folder = self._folder(dim)
        if os.path.isdir(folder):
            for fn in os.listdir(folder):
                m = _REGION_RE.match(fn)
                if not m or os.path.getsize(os.path.join(folder, fn)) < 8192:
                    continue
                try:
                    out.add_region(int(m.group(1)), int(m.group(2)), os.path.join(folder, fn))
                except Exception:  # noqa: BLE001
                    continue
        self._index[dim] = out
        return out

    def dimensions(self):
        return [d for d in (OVERWORLD, NETHER, THE_END) if self._scan(d)]

    def chunk_coords(self, dim):
        return sorted(self._scan(dim), key=lambda c: (c[1], c[0]))

    def tile(self, dim, cx, cz):
        from .java.region import JavaRegion

        ent = self._scan(dim).get((cx, cz))
        if ent is None:
            return None
        path, lx, lz = ent
        reg = self._cache.get(path)
        if reg is None:
            if len(self._cache) > 8:
                self._cache.clear()
            reg = self._cache[path] = JavaRegion(path)
        raw = reg.read(lx, lz)
        if raw is None:
            return None
        try:
            return java_chunk_tile(nbt.load(raw, compressed=False).tag, _roof(dim))
        except Exception:  # noqa: BLE001
            return None


class BtaMapSource(MapSource):
    """Better than Adventure saves, drawn with the blocks they become in Java 26.3."""

    def __init__(self, path: str, description: str):
        super().__init__(path, "bta", description)
        from .bta.nbtio import gi, glist, num
        from .bta.world import BtaWorld, to_wb_dim

        self.world = BtaWorld(path)
        lv = self.world.level
        self.spawn = (gi(lv, "SpawnX"), gi(lv, "SpawnY", 64), gi(lv, "SpawnZ"))
        players = self.world.players()
        host = lv.get("Player") if isinstance(lv.get("Player"), dict) else None
        last = str(lv.get("LastPlayerUUID") or "")
        entries = []
        if host is not None and last not in players:
            entries.append(("host", host))
        entries.extend(players.items())
        names = known_names(path)
        for key, p in entries:
            pos = glist(p, "Pos")
            pos = tuple(num(v) for v in pos) if pos is not None and len(pos) == 3 else None
            name = names.get(key.lower()) if _UUID_RE.match(key) else (key if key != "host" else None)
            label = tr("Main player") if key == "host" or key == last else key
            if key == last and key != "host":
                label += f"  ·  {key}"
            if name:
                label += f" ({name})"
            inv = glist(p, "Inventory") or []
            self.players.append(PlayerEntry(key, label, pos, to_wb_dim(gi(p, "Dimension", 0)) if gi(p, "Dimension", 0) in (0, 1, 2) else 0,
                                            name, len(inv)))
        self._coords: Dict[int, List[Tuple[int, int]]] = {}
        self._palette = None
        self._convs: Dict[int, object] = {}

    def _bta_dim(self, dim: int) -> Optional[int]:
        from .bta.world import from_wb_dim

        return from_wb_dim(dim)

    def dimensions(self):
        from .bta.world import to_wb_dim

        return [to_wb_dim(d) for d in self.world.dimensions()]

    def chunk_coords(self, dim):
        bd = self._bta_dim(dim)
        if bd is None:
            return []
        if dim not in self._coords:
            self._coords[dim] = sorted(self.world.chunk_coords(bd), key=lambda c: (c[1], c[0]))
        return self._coords[dim]

    def tile(self, dim, cx, cz):
        from .bta import blockmap
        from .bta.palette import Palette
        from .bta.states import AIR, by_id, count
        from .bta.world import read_chunk

        bd = self._bta_dim(dim)
        if bd is None:
            return None
        try:
            level = self.world.read_level(bd, cx, cz)
            if level is None:
                return None
            c = read_chunk(level)
        except Exception:  # noqa: BLE001
            return None
        if self._palette is None:
            self._palette = Palette()
        cache = self._convs.setdefault(bd, {})
        keys = (c.blocks.astype(np.uint32) << 8) | c.data
        uniq, inv = np.unique(keys, return_inverse=True)
        ctx = blockmap.MapCtx(self._palette)
        ids = []
        for k in uniq.tolist():
            sid = cache.get(k)
            if sid is None:
                try:
                    st = blockmap.map_block(k >> 8, k & 0xFF, ctx)
                except Exception:  # noqa: BLE001
                    st = None
                sid = cache[k] = (st or AIR).id
            ids.append(sid)
        sids = np.array(ids, np.int64)[inv.reshape(-1)].reshape(keys.shape)
        n = count()
        if getattr(self, "_luts", None) is None or len(self._luts[0]) != n:
            names = [by_id(i).name for i in range(n)]
            self._luts = (names, np.array([is_air(nm) for nm in names], bool),
                          np.array([is_watery(nm) for nm in names], bool))
        names, air, water = self._luts
        return _tile_core(sids, air, water, lambda k: names[k], 0, _roof(dim))


_BEDROCK_DIMS = {OVERWORLD: 0, NETHER: 1, THE_END: 2}


def bedrock_subchunk(raw: bytes) -> List[Tuple[np.ndarray, List[str]]]:
    """Decode a Bedrock sub-chunk (versions 1, 8, 9) -> [(indices [y,z,x], palette names)] per layer."""
    ver = raw[0]
    off = 1
    if ver == 1:
        layers = 1
    elif ver in (8, 9):
        layers = raw[off]
        off += 1
        if ver == 9:
            off += 1  # sub-chunk y index
    else:
        raise ValueError(f"sub-chunk v{ver}")
    out = []
    for _ in range(layers):
        head = raw[off]
        off += 1
        bits = head >> 1
        if bits == 0:
            idx = np.zeros(4096, np.int64)
        else:
            per = 32 // bits
            words = (4096 + per - 1) // per
            arr = np.frombuffer(raw, "<u4", words, off).astype(np.uint64)
            off += words * 4
            shifts = np.arange(per, dtype=np.uint64) * np.uint64(bits)
            idx = ((arr[:, None] >> shifts[None, :]) & np.uint64((1 << bits) - 1)).reshape(-1)[:4096].astype(np.int64)
        count = struct.unpack_from("<i", raw, off)[0] if bits else 1
        if bits:
            off += 4
        names = []
        for _i in range(count):
            tag, off = nbt.load_with_offset(raw, off, little_endian=True)
            names.append(str(nbt.get(tag.tag, "name", "minecraft:air")))
        out.append((idx.reshape(16, 16, 16).transpose(2, 1, 0), names))  # stored x,z,y
    return out


class BedrockMapSource(MapSource):
    def __init__(self, path: str, description: str):
        super().__init__(path, "bedrock", description)
        from .extra import read_amulet_info
        from .detect import Detected, snapshot
        from leveldb import LevelDB

        # read from a private copy: LevelDB may rewrite files when opened and is locked while the
        # game (or a conversion) has the world open
        self._snap_root = tempfile.mkdtemp(prefix="worldbridge_bmap_")
        path = snapshot(path, self._snap_root)
        self._read_path = path
        info = read_amulet_info(Detected(kind="bedrock", description=description, path=path))
        self.spawn = tuple(info.spawn)
        self.players = _player_entries(info.players)
        self.db = LevelDB(os.path.join(path, "db"))
        self._chunks: Dict[int, Dict[Tuple[int, int], List[int]]] = {0: {}, 1: {}, 2: {}}
        self._legacy: Dict[int, set] = {0: set(), 1: set(), 2: set()}
        for key, _v in self.db.iterate():
            n = len(key)
            if n in (10, 14) and key[-2] == 0x2F:
                x, z = struct.unpack_from("<ii", key)
                d = struct.unpack_from("<i", key, 8)[0] if n == 14 else 0
                sy = struct.unpack("b", key[-1:])[0]
                self._chunks.setdefault(d, {}).setdefault((x, z), []).append(sy)
            elif n in (9, 13) and key[-1] == 0x30:  # LegacyTerrain (Pocket Edition 0.9 - 1.0)
                x, z = struct.unpack_from("<ii", key)
                d = struct.unpack_from("<i", key, 8)[0] if n == 13 else 0
                self._legacy.setdefault(d, set()).add((x, z))
                self._chunks.setdefault(d, {}).setdefault((x, z), [])
        self._amulet = None

    def dimensions(self):
        rev = {v: k for k, v in _BEDROCK_DIMS.items()}
        return [rev[d] for d in (0, 1, 2) if self._chunks.get(d)]

    def chunk_coords(self, dim):
        return sorted(self._chunks.get(_BEDROCK_DIMS[dim], {}), key=lambda c: (c[1], c[0]))

    def _key(self, d, cx, cz, tag: int, sy: Optional[int] = None) -> bytes:
        k = struct.pack("<ii", cx, cz) + (struct.pack("<i", d) if d else b"") + bytes([tag])
        return k + (struct.pack("b", sy) if sy is not None else b"")

    def tile(self, dim, cx, cz):
        d = _BEDROCK_DIMS[dim]
        if (cx, cz) in self._legacy.get(d, ()):
            return self._legacy_tile(d, cx, cz, _roof(dim))
        secs = []
        for sy in self._chunks.get(d, {}).get((cx, cz), []):
            try:
                raw = self.db.get(self._key(d, cx, cz, 0x2F, sy))
            except KeyError:
                continue
            try:
                layers = bedrock_subchunk(raw)
            except ValueError:
                return self._amulet_tile(dim, cx, cz)
            except Exception:  # noqa: BLE001
                continue
            idx, names = layers[0]
            if len(layers) > 1:  # water layer (waterlogged blocks): show it where layer 0 is air
                widx, wnames = layers[1]
                air0 = np.array([is_air(n) for n in names], bool)[idx]
                if air0.any():
                    merged = list(names) + list(wnames)
                    idx = np.where(air0, widx + len(names), idx)
                    names = merged
            secs.append((sy, idx, names))
        return tile_from_sections(secs, _roof(dim))

    def _legacy_tile(self, d, cx, cz, roof=None):
        try:
            raw = self.db.get(self._key(d, cx, cz, 0x30))
        except KeyError:
            return None
        ids = np.frombuffer(raw, np.uint8, 32768).reshape(16, 16, 128)          # x,z,y
        nib = np.frombuffer(raw, np.uint8, 16384, 32768)
        dv = np.empty(32768, np.uint8)
        dv[0::2] = nib & 15
        dv[1::2] = nib >> 4

        class _C:  # minimal NumericChunk look-alike
            pass

        c = _C()
        c.blocks = ids.transpose(2, 1, 0).astype(np.int32)
        c.data = dv.reshape(16, 16, 128).transpose(2, 1, 0).astype(np.int32)
        return tile_from_numeric(c, roof)

    def _amulet_tile(self, dim, cx, cz):
        """Very old sub-chunk formats (numeric ids): let Amulet decode them."""
        try:
            from . import amulet_bridge as ab

            if self._amulet is None:
                self._amulet = ab.load_level(self._read_path)
            chunk = self._amulet.get_chunk(cx, cz, ab.AMULET_DIMS[dim])
            secs = []
            pal = chunk.block_palette
            names = [b.base_name for b in pal]
            for sy in chunk.blocks.sub_chunks:
                arr = np.asarray(chunk.blocks.get_sub_chunk(sy))  # x,y,z
                secs.append((sy, arr.transpose(1, 2, 0), names))
            return tile_from_sections(secs, _roof(dim))
        except Exception:  # noqa: BLE001
            return None

    def close(self):
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass
        if self._amulet is not None:
            try:
                self._amulet.close()
            except Exception:  # noqa: BLE001
                pass
        shutil.rmtree(getattr(self, "_snap_root", ""), ignore_errors=True)
        super().close()


def parallel_safe(src: MapSource) -> bool:
    """The source can be read by forked worker processes (parallel.py): not Bedrock's LevelDB."""
    return getattr(src, "kind", "") != "bedrock"


def map_tile(state, c: Tuple[int, int]):
    """(cx, cz, tile or None) of chunk ``c`` (worker function, parallel.py): ``state`` = (source, dim)."""
    src, dim = state
    try:
        return c[0], c[1], src.tile(dim, c[0], c[1])
    except Exception:  # noqa: BLE001
        return c[0], c[1], None


def open_map(path: str, progress: Optional[Progress] = None) -> MapSource:
    """Open any supported world for the map view."""
    from . import detect as det
    from .model import ConversionError

    d = det.detect(path)
    if d is None:
        raise ConversionError(tr("World format not recognised."))
    tmp = None
    try:
        if d.kind == "archive":
            tmp = tempfile.mkdtemp(prefix="worldbridge_map_")
            folder = det.extract_archive(d.path, tmp)
            d = det.detect(folder)
            if d is None:
                raise ConversionError(tr("The archive does not contain a recognised world."))
        if d.kind == "java_modern":
            src: MapSource = JavaModernMapSource(d.path, d.description)
        elif d.kind == "bta":
            src = BtaMapSource(d.path, d.description)
        elif d.kind == "bedrock":
            src = BedrockMapSource(d.path, d.description)
        else:
            from .convert import open_source

            world = open_source(d, progress or Progress(), tmp or "")
            src = HubMapSource(d.path, d.kind, world, d.description)
    except BaseException:
        if tmp:
            shutil.rmtree(tmp, ignore_errors=True)
        raise
    src.tmp = tmp
    return src
