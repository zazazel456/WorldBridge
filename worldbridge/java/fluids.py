"""Scheduled ticks of the liquids (and of the blocks that tick) of a Java world made from a Bedrock one.

Bedrock saves a liquid mid-flow: the flowing / falling cells (``liquid_depth`` 1-15) are in the chunk together with
the pending ticks that keep them flowing.  A translated chunk has the cells but no tick, so the game never looks at
them again: every flowing cell stays as a static partial block ("pieces of lava that look like terrain") until a
neighbour changes.  This module gives the Java chunks the ticks:

* every flowing / falling liquid cell gets a fluid tick (the game then resolves it: an unsupported cell dries up,
  a supported one keeps flowing), and so does every source cell that has air (or a replaceable plant) next to it or
  below it, since it can still spread (a few per chunk at most);
* the pending ticks Bedrock saved (chunk keys 0x33 PendingTicks and 0x3a RandomTicks, a ``tickList`` of
  ``{blockState, x, y, z, time}``) become block ticks when the block they name is still there (fire, coral, gravel...)
  and liquid ticks for the liquids.

Chunks of 1.18+ (``fluid_ticks`` / ``block_ticks``), 1.13 - 1.17 (``Level.LiquidTicks`` / ``TileTicks``) and 1.12
(``Level.TileTicks`` only, block ids by name) are handled; older formats are left alone.
"""

from __future__ import annotations

import struct
from typing import Dict, List, Optional, Tuple

import numpy as np

from .. import nbt
from ..model import NETHER, OVERWORLD, THE_END, Progress
from ..i18n import tr
from .modern import SPANNING_DV, _decode, _folder, _regions, _sections
from .region import JavaRegion, RegionWriter

# first DataVersion of 1.13 (the flattening) and of 1.12
FLAT_DV = 1519
LEGACY_MIN_DV = 1343          # 1.12: block ticks by name

# game delays (FlowingFluid.getTickDelay): water 5, lava 30 (10 in the Nether)
WATER_DELAY = 5
LAVA_DELAY = {OVERWORLD: 30, NETHER: 10, THE_END: 30}

MAX_FLOWING = 8192            # per chunk
MAX_SOURCES = 1024
MAX_BEDROCK = 4096
MAX_DELAY = 1200

AIR = 1
WATER = 2
LAVA = 3

_OPEN = frozenset({"air", "cave_air", "void_air", "short_grass", "grass", "tall_grass", "fern", "large_fern",
                   "dead_bush", "fire", "soul_fire", "vine", "snow", "light"})
_ALIAS = {"magma": "magma_block", "flowing_water": "water", "flowing_lava": "lava", "stationary_water": "water",
          "stationary_lava": "lava", "grass": "short_grass"}
# 1.12 block ids by name for the pending ticks of Bedrock that are not liquids
_LEGACY_IDS = {"fire": 51, "sand": 12, "gravel": 13, "rail": 66, "vine": 106, "dispenser": 23, "dropper": 158}
_BEDROCK_TICK_TAGS = (0x33, 0x3A)


def _entry_class(name: str, props) -> Tuple[int, int]:
    n = name.split(":", 1)[-1]
    if n == "water" or n == "lava":
        lev = 0
        if props is not None:
            try:
                lev = int(str(nbt.get(props, "level", 0)))
            except ValueError:
                lev = 0
        return (WATER if n == "water" else LAVA), lev
    return (AIR if n in _OPEN else 0), 0


def _nibbles(arr: np.ndarray) -> np.ndarray:
    out = np.empty(arr.size * 2, np.uint8)
    out[0::2] = arr & 15
    out[1::2] = arr >> 4
    return out


def _bytes(tag, key) -> Optional[np.ndarray]:
    t = nbt.get_tag(tag, key)
    if t is None:
        return None
    return np.asarray(t.np_array if hasattr(t, "np_array") else t.py_data).astype(np.uint8)


class _Grid:
    """cls / level / forced of every cell of a chunk, [y, z, x] from the lowest section up."""

    def __init__(self, ys: int, y0: int):
        self.y0 = y0                                    # y of the first row
        self.cls = np.full((ys * 16, 16, 16), AIR, np.uint8)
        self.lev = np.zeros((ys * 16, 16, 16), np.uint8)
        self.forced = np.zeros((ys * 16, 16, 16), bool)  # 1.12 flowing blocks (a level 0 one is a source in motion)
        self.src_ok = True                              # may a source cell be ticked (not in 1.12: static liquid)


def _build_grid(root: nbt.CompoundTag, dv: int) -> Optional[Tuple[_Grid, dict]]:
    """(grid, {section Y: (idx, [names])}) of the chunk, or None when it holds no liquid / is not understood."""
    lvl = nbt.get_tag(root, "Level")
    secs: Dict[int, tuple] = {}
    spanning = bool(dv) and dv < SPANNING_DV
    any_liquid = False
    if dv >= FLAT_DV or (lvl is None):
        for sec, holder, pkey, dkey in _sections(root):
            palette = nbt.get_tag(holder, pkey) or []
            if not len(palette):
                continue
            names = [nbt.state_name(st, "minecraft:air") for st in palette]
            cl = [_entry_class(n, nbt.state_props(st)) for n, st in zip(names, palette)]
            idx = _decode(nbt.get_tag(holder, dkey), len(palette), spanning)
            if idx is None:
                continue
            sy = int(nbt.get(sec, "Y", 0))
            ca = np.array([c for c, _ in cl], np.uint8)
            la = np.array([lv for _, lv in cl], np.uint8)
            any_liquid = any_liquid or bool((ca >= WATER).any())
            secs[sy] = (idx, names, ca, la, None)
    elif lvl is not None and dv >= LEGACY_MIN_DV and "Sections" in lvl:
        for sec in nbt.get_tag(lvl, "Sections") or []:
            b = _bytes(sec, "Blocks")
            if b is None or b.size < 4096:
                continue
            ids = b[:4096].astype(np.uint16)
            add = _bytes(sec, "Add")
            if add is not None and add.size >= 2048:
                ids |= _nibbles(add[:2048]).astype(np.uint16) << 8
            d = _bytes(sec, "Data")
            data = _nibbles(d[:2048]) if d is not None and d.size >= 2048 else np.zeros(4096, np.uint8)
            sy = int(nbt.get(sec, "Y", 0))
            still = np.isin(ids, (9, 11)) & (data != 0)
            if still.any():           # a static block (9, 11) with a level is a flowing one the game never updates:
                ids[still] -= 1       # it is stored as the flowing block (8, 10) it is, and ticked below
                sec["Blocks"] = nbt.ByteArrayTag((ids & 255).astype(np.uint8).view(np.int8))
            any_liquid = any_liquid or bool(np.isin(ids, (8, 9, 10, 11)).any())
            secs[sy] = (ids, None, None, None, data)
    else:
        return None
    if not secs or not any_liquid:
        return None
    lo, hi = min(secs), max(secs)
    g = _Grid(hi - lo + 1, lo * 16)
    legacy = dv < FLAT_DV and lvl is not None
    g.src_ok = not legacy
    for sy, (idx, names, ca, la, data) in secs.items():
        sl = slice((sy - lo) * 16, (sy - lo) * 16 + 16)
        if data is None:
            g.cls[sl] = ca[idx].reshape(16, 16, 16)
            g.lev[sl] = la[idx].reshape(16, 16, 16)
        else:
            ids = idx
            cls = np.zeros(4096, np.uint8)
            cls[ids == 0] = AIR
            cls[np.isin(ids, (31, 32, 51, 106, 78, 175))] = AIR      # tall grass, dead bush, fire, vine, snow layer, plants
            cls[np.isin(ids, (8, 9))] = WATER
            cls[np.isin(ids, (10, 11))] = LAVA
            g.cls[sl] = cls.reshape(16, 16, 16)
            g.lev[sl] = data.reshape(16, 16, 16)
            g.forced[sl] = np.isin(ids, (8, 10)).reshape(16, 16, 16)
    return g, secs


def _cells(g: _Grid):
    """(flowing mask, source-to-tick mask) of the grid."""
    liq = g.cls >= WATER
    flowing = liq & ((g.lev != 0) | g.forced)
    sources = liq & ~flowing
    if not g.src_ok or not sources.any():
        return flowing, np.zeros_like(flowing)
    op = g.cls == AIR
    near = np.zeros_like(op)
    near[1:] |= op[:-1]                                  # below
    near[:, 1:, :] |= op[:, :-1, :]
    near[:, :-1, :] |= op[:, 1:, :]
    near[:, :, 1:] |= op[:, :, :-1]
    near[:, :, :-1] |= op[:, :, 1:]
    return flowing, sources & near


def _tick(i: str, x: int, y: int, z: int, t: int) -> nbt.CompoundTag:
    return nbt.CompoundTag({"i": nbt.StringTag(i), "p": nbt.IntTag(0), "t": nbt.IntTag(int(t)),
                            "x": nbt.IntTag(int(x)), "y": nbt.IntTag(int(y)), "z": nbt.IntTag(int(z))})


def _ids(g: _Grid, legacy: bool, dim: int, y: int, z: int, x: int) -> Tuple[str, int]:
    """(tick id, default delay) of the liquid cell: the fluid (1.13+) or the block (1.12) that stands there."""
    water = g.cls[y, z, x] == WATER
    moving = bool(g.forced[y, z, x]) if legacy else bool(g.lev[y, z, x])
    base = "water" if water else "lava"
    return "minecraft:" + ("flowing_" + base if moving else base), (WATER_DELAY if water else LAVA_DELAY.get(dim, 30))


def add_ticks(root: nbt.CompoundTag, cx: int, cz: int, dim: int, bedrock: Optional[list] = None,
              assume_dv: int = 0) -> Tuple[int, int]:
    """Add the fluid and block ticks to a chunk (modified in place).  ``bedrock``: the pending ticks of the source
    chunk as ``(name, x, y, z, delay)``.  ``assume_dv``: the data version of a chunk that has none (the numeric Anvil
    writer's 1.8 - 1.12 chunks: pass 1343).  Returns (fluid ticks, block ticks) added."""
    dv = int(nbt.get(root, "DataVersion", 0) or 0)
    lvl = nbt.get_tag(root, "Level")
    if not dv and lvl is not None and assume_dv and "Sections" in lvl:
        dv = assume_dv
    legacy = lvl is not None and dv < FLAT_DV
    if dv < LEGACY_MIN_DV:
        return 0, 0
    built = _build_grid(root, dv)
    if built is None:
        return 0, 0
    g, secs = built
    holder = lvl if lvl is not None else root
    k_block, k_fluid = ("TileTicks", "LiquidTicks") if lvl is not None else ("block_ticks", "fluid_ticks")
    if legacy:
        k_fluid = k_block                                 # 1.12: one list
    have = set()
    for key in {k_block, k_fluid}:
        for t in nbt.get_tag(holder, key) or []:
            have.add((str(nbt.get(t, "i", "")), int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))))
    fluid: List[nbt.CompoundTag] = []
    block: List[nbt.CompoundTag] = []
    wanted: Dict[Tuple[int, int, int], int] = {}          # Bedrock's own delays for the cells
    bblocks = []
    for name, x, y, z, delay in bedrock or []:
        n = _ALIAS.get(name.split(":", 1)[-1], name.split(":", 1)[-1])
        if n in ("water", "lava"):
            wanted[(x, y, z)] = delay
        else:
            bblocks.append((n, x, y, z, delay))
    flowing, sources = _cells(g)
    x0, z0 = cx * 16, cz * 16
    for mask, cap in ((flowing, MAX_FLOWING), (sources, MAX_SOURCES)):
        ys, zs, xs = np.nonzero(mask)
        for j in range(min(len(ys), cap)):
            y, z, x = int(ys[j]), int(zs[j]), int(xs[j])
            tid, delay = _ids(g, legacy, dim, y, z, x)
            wx, wy, wz = x0 + x, g.y0 + y, z0 + z
            if (tid, wx, wy, wz) in have:
                continue
            fluid.append(_tick(tid, wx, wy, wz, wanted.get((wx, wy, wz), delay)))
            have.add((tid, wx, wy, wz))
    # the pending ticks of Bedrock that name another block, when that block is still there
    for n, x, y, z, delay in bblocks[:MAX_BEDROCK]:
        sy = y >> 4
        if sy not in secs:
            continue
        lx, ly, lz = x - x0, y & 15, z - z0
        if not (0 <= lx < 16 and 0 <= lz < 16):
            continue
        i = ly << 8 | lz << 4 | lx
        idx, names, _, _, _ = secs[sy]
        if names is not None:
            here = names[int(idx[i])].split(":", 1)[-1]
            tid = "minecraft:" + here
        else:
            if _LEGACY_IDS.get(n) != int(idx[i]):
                continue
            here, tid = n, "minecraft:" + n
        if here != n or (tid, x, y, z) in have:
            continue
        block.append(_tick(tid, x, y, z, delay))
        have.add((tid, x, y, z))
    n_fluid, n_block = len(fluid), len(block)
    if legacy:                                            # 1.12 has one list for all
        block = fluid + block
    elif fluid:
        _extend(holder, k_fluid, fluid)
    if block:
        _extend(holder, k_block, block)
    return n_fluid, n_block


def _extend(holder: nbt.CompoundTag, key: str, items: list) -> None:
    cur = nbt.get_tag(holder, key)
    if cur is None:
        holder[key] = nbt.compound_list(items)
        return
    for it in items:
        cur.append(it)


# ------------------------------------------------------------------------------ Bedrock source


def read_bedrock_ticks(src: str) -> Dict[Tuple[int, int, int], list]:
    """{(dim, cx, cz): [(block name, x, y, z, delay)]} of the pending ticks saved in a Bedrock world."""
    from ..bedrock.extra import DIM_FROM_BEDROCK, _db

    out: Dict[Tuple[int, int, int], list] = {}
    db = _db(src)
    try:
        for key, value in db.iterate():
            k = bytes(key)
            if len(k) not in (9, 13) or k[-1] not in _BEDROCK_TICK_TAGS:
                continue
            cx, cz = struct.unpack_from("<ii", k, 0)
            dim = OVERWORLD if len(k) == 9 else DIM_FROM_BEDROCK.get(struct.unpack_from("<i", k, 8)[0])
            if dim is None:
                continue
            try:
                root = nbt.load(bytes(value), little_endian=True, compressed=False).tag
            except Exception:  # noqa: BLE001
                continue
            cur = int(nbt.get(root, "currentTick", 0) or 0)
            lst = out.setdefault((dim, cx, cz), [])
            for t in nbt.get_tag(root, "tickList") or []:
                try:
                    bs = nbt.get_tag(t, "blockState")
                    name = str(nbt.get(bs, "name", ""))
                    lst.append((name, int(nbt.get(t, "x")), int(nbt.get(t, "y")), int(nbt.get(t, "z")),
                                min(max(int(nbt.get(t, "time", 0)) - cur, 1), MAX_DELAY)))
                except (TypeError, ValueError):
                    continue
    finally:
        db.close()
    return out


# --------------------------------------------------------------------------------- the world


def schedule_world(out_dir: str, progress: Optional[Progress] = None, bedrock_src: Optional[str] = None,
                   assume_dv: int = 0) -> Dict[str, int]:
    """Give every Anvil chunk of the world the ticks of its liquids (see the module's docstring).  ``bedrock_src``:
    the Bedrock world whose pending ticks are translated as well (pass it only when no block moved).  ``assume_dv``:
    see ``add_ticks``."""
    stats = {"fluid": 0, "block": 0, "chunks": 0}
    pending = {}
    if bedrock_src:
        try:
            pending = read_bedrock_ticks(bedrock_src)
        except Exception as ex:  # noqa: BLE001 - the liquids below do not need them
            if progress is not None:
                progress.log(tr("The pending ticks of the Bedrock world could not be read: {error}", error=ex))
    for dim in (OVERWORLD, NETHER, THE_END):
        for rx, rz, path in _regions(_folder(out_dir, dim, "region")):
            try:
                reg = JavaRegion(path)
                chunks = list(reg.chunks())
            except OSError:
                continue
            rw = RegionWriter(external=True)
            dirty = 0
            for lx, lz in chunks:
                raw = reg.read(lx, lz)
                if raw is None:
                    continue
                cx, cz = rx * 32 + lx, rz * 32 + lz
                try:
                    root = nbt.load(raw, compressed=False).tag
                    nf, nb = add_ticks(root, cx, cz, dim, pending.get((dim, cx, cz)), assume_dv)
                except Exception:  # noqa: BLE001 - a chunk that cannot be read stays as it is
                    rw.put(lx, lz, raw)
                    continue
                if nf or nb:
                    stats["fluid"] += nf
                    stats["block"] += nb
                    stats["chunks"] += 1
                    dirty += 1
                    rw.put(lx, lz, nbt.dump(root, ""))
                else:
                    rw.put(lx, lz, raw)
            if dirty:
                rw.write(path)
    if progress is not None and (stats["fluid"] or stats["block"]):
        progress.log(tr("Liquids: {fluid} fluid ticks and {block} block ticks scheduled in {chunks} chunks, so that the "
                        "game settles the flowing water and lava when it loads them.", **stats))
    return stats
