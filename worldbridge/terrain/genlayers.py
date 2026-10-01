"""Biomes of Minecraft Beta 1.8 - 1.6.4 (the GenLayer stack), for the terrain generator of
those versions (releasegen).

A numpy port of the layers of cubiomes (https://github.com/Cubitect/cubiomes, MIT License,
Copyright (c) 2020 Cubitect), which reproduces the game's GenLayer classes exactly.  Every layer
works on a whole area at once: ``Stack(version, seed).area(layer, x, z, w, h)`` returns [h, w]
biome ids (rows = z).
"""

from __future__ import annotations

from collections import OrderedDict
from typing import Callable, Dict, Tuple

import numpy as np

U64 = np.uint64
_A = U64(6364136223846793005)
_B = U64(1442695040888963407)
_M32A = np.uint32(1284865837)
_M32B = np.uint32(4150755663)

# biome ids (the game's numeric ids)
OCEAN, PLAINS, DESERT, MOUNTAINS, FOREST, TAIGA, SWAMP, RIVER = 0, 1, 2, 3, 4, 5, 6, 7
FROZEN_OCEAN, FROZEN_RIVER, SNOWY_TUNDRA, SNOWY_MOUNTAINS, MUSHROOM, MUSHROOM_SHORE = 10, 11, 12, 13, 14, 15
BEACH, DESERT_HILLS, WOODED_HILLS, TAIGA_HILLS, MOUNTAIN_EDGE = 16, 17, 18, 19, 20
JUNGLE, JUNGLE_HILLS = 21, 22
OLD_BIOMES_11 = np.array([DESERT, FOREST, MOUNTAINS, SWAMP, PLAINS, TAIGA], np.int64)
OLD_BIOMES = np.array([DESERT, FOREST, MOUNTAINS, SWAMP, PLAINS, TAIGA, JUNGLE], np.int64)    # 1.2 - 1.6

_CATEGORY = np.arange(64)
for _ids, _cat in (((BEACH,), BEACH), ((DESERT, DESERT_HILLS), DESERT), ((MOUNTAINS, MOUNTAIN_EDGE), MOUNTAINS),
                   ((FOREST, WOODED_HILLS), FOREST), ((SNOWY_TUNDRA, SNOWY_MOUNTAINS), SNOWY_TUNDRA),
                   ((MUSHROOM, MUSHROOM_SHORE), MUSHROOM), ((OCEAN, FROZEN_OCEAN), OCEAN), ((PLAINS,), PLAINS),
                   ((RIVER, FROZEN_RIVER), RIVER), ((SWAMP,), SWAMP), ((TAIGA, TAIGA_HILLS), TAIGA),
                   ((JUNGLE, JUNGLE_HILLS), JUNGLE)):
    _CATEGORY[list(_ids)] = _cat


def _u(v) -> np.uint64:
    return U64(int(v) & 0xFFFFFFFFFFFFFFFF)


def step(s, salt):
    if type(s) is np.ndarray:            # integer arrays wrap silently: no error state to switch
        return s * (s * _A + _B) + salt
    with np.errstate(over="ignore"):
        return s * (s * _A + _B) + salt


def _step_int(s: int, salt: int) -> int:
    return (s * ((s * 6364136223846793005 + 1442695040888963407) & 0xFFFFFFFFFFFFFFFF) + salt) & 0xFFFFFFFFFFFFFFFF


def layer_salt(salt: int) -> int:
    ls = _step_int(salt, salt)
    ls = _step_int(ls, salt)
    return _step_int(ls, salt)


def start_salt_seed(world_seed: int, salt: int) -> Tuple[int, int]:
    if salt == 0:
        return 0, 0  # before 1.13 the hills branch stays zero-initialised
    ls = layer_salt(salt)
    st = world_seed & 0xFFFFFFFFFFFFFFFF
    for _ in range(3):
        st = _step_int(st, ls)
    return st, _step_int(st, 0)


def chunk_seed(ss: int, x: np.ndarray, z: np.ndarray) -> np.ndarray:
    xs = x.astype(np.int64).view(U64)
    zs = z.astype(np.int64).view(U64)
    cs = _u(ss) + xs
    if type(cs) is not np.ndarray:
        cs = np.asarray(cs)
    cs = step(cs, zs)
    cs = step(cs, xs)
    return step(cs, zs)


def first_int(cs: np.ndarray, mod: int) -> np.ndarray:
    return (cs.view(np.int64) >> 24) % mod


def _grid(x: int, z: int, w: int, h: int):
    """(x, z) of every cell of an area, [h, w] int64 (np.mgrid, without its overhead)."""
    xx = np.empty((h, w), np.int64)
    zz = np.empty((h, w), np.int64)
    xx[:] = np.arange(x, x + w, dtype=np.int64)
    zz[:] = np.arange(z, z + h, dtype=np.int64)[:, None]
    return xx, zz


class Layer:
    def __init__(self, fn: Callable, salt: int, parent=None, parent2=None):
        self.fn, self.salt, self.p, self.p2 = fn, salt, parent, parent2
        self.st = self.ss = 0

    def seed(self, world_seed: int):
        for q in (self.p2, self.p):
            if q is not None:
                q.seed(world_seed)
        self.st, self.ss = start_salt_seed(world_seed, self.salt)

    def area(self, x: int, z: int, w: int, h: int) -> np.ndarray:
        return self.fn(self, x, z, w, h)


class AreaCache:
    """Areas of a layer computed in aligned square blocks, the last ``keep`` blocks kept.  Neighbouring
    chunks (a ring, a filled map, the columns a cave passes) ask for overlapping pieces of the same
    areas: each block is computed once.  Every cell of a layer depends on its own position only (as
    in the game's GenLayer), so a piece cut out of a block is exactly the area asked for."""

    def __init__(self, size: int, keep: int = 256):
        self.size, self.keep = size, keep
        self._blocks: "OrderedDict[tuple, np.ndarray]" = OrderedDict()

    def _block(self, layer: "Layer", bx: int, bz: int, key: tuple) -> np.ndarray:
        k = (bx, bz) + key
        blk = self._blocks.get(k)
        if blk is None:
            blk = self._blocks[k] = layer.area(bx * self.size, bz * self.size, self.size, self.size)
            if len(self._blocks) > self.keep:
                self._blocks.popitem(last=False)
        else:
            self._blocks.move_to_end(k)
        return blk

    def area(self, layer: "Layer", x: int, z: int, w: int, h: int, key: tuple = ()) -> np.ndarray:
        B = self.size
        if w * h > B * B:                     # a big area (the filler's regions): at once
            return layer.area(x, z, w, h)
        out = None
        for bz in range(z // B, (z + h - 1) // B + 1):
            for bx in range(x // B, (x + w - 1) // B + 1):
                blk = self._block(layer, bx, bz, key)
                if out is None:
                    out = np.empty((h, w), blk.dtype)
                x0, x1 = max(x, bx * B), min(x + w, bx * B + B)
                z0, z1 = max(z, bz * B), min(z + h, bz * B + B)
                out[z0 - z:z1 - z, x0 - x:x1 - x] = blk[z0 - bz * B:z1 - bz * B, x0 - bx * B:x1 - bx * B]
        return out


# ------------------------------------------------------------------ layers


def _continent(l: Layer, x, z, w, h):
    xx, zz = _grid(x, z, w, h)
    out = (first_int(chunk_seed(l.ss, xx, zz), 10) == 0).astype(np.int64)
    out[(xx == 0) & (zz == 0)] = 1
    return out


def _zoom_common(l: Layer, x, z, w, h, fuzzy: bool):
    px, pz = x >> 1, z >> 1
    pw, ph = ((x + w) >> 1) - px + 1, ((z + h) >> 1) - pz + 1
    p = l.p.area(px, pz, pw + 1, ph + 1)       # one more row / column: the right and lower neighbours
    a, b, c, d = p[:-1, :-1], p[:-1, 1:], p[1:, :-1], p[1:, 1:]   # v00, v10 (x + 1), v01 (z + 1), v11
    ii, jj = _grid(0, 0, pw, ph)
    cx = ((ii + px) * 2).astype(np.int64).view(U64).astype(np.uint32)
    cz = ((jj + pz) * 2).astype(np.int64).view(U64).astype(np.uint32)
    st, ss = np.uint32(l.st & 0xFFFFFFFF), np.uint32(l.ss & 0xFFFFFFFF)
    with np.errstate(over="ignore"):
        cs = ss + cx
        cs = cs * (cs * _M32A + _M32B) + cz
        cs = cs * (cs * _M32A + _M32B) + cx
        cs = cs * (cs * _M32A + _M32B) + cz
        o01 = np.where((cs >> 24) & 1, c, a)
        cs = cs * (cs * _M32A + _M32B) + st
        o10 = np.where((cs >> 24) & 1, b, a)
        cs = cs * (cs * _M32A + _M32B) + st
        r = (cs >> 24) & 3
        rnd = np.where(r == 0, a, np.where(r == 1, b, np.where(r == 2, c, d)))
    if fuzzy:
        o11 = rnd
    else:
        cv00 = (a == b).astype(int) + (a == c) + (a == d)
        cv10 = (b == c).astype(int) + (b == d)
        cv01 = (c == d).astype(int)
        o11 = np.where((cv00 > cv10) & (cv00 > cv01), a, np.where(cv10 > cv00, b, np.where(cv01 > cv00, c, rnd)))
    same = (a == b) & (a == c) & (a == d)
    o01, o10, o11 = (np.where(same, a, o) for o in (o01, o10, o11))
    buf = np.empty((ph * 2, pw * 2), np.int64)
    buf[0::2, 0::2] = a
    buf[1::2, 0::2] = o01
    buf[0::2, 1::2] = o10
    buf[1::2, 1::2] = o11
    return buf[(z & 1):(z & 1) + h, (x & 1):(x & 1) + w]


def _zoom(l, x, z, w, h):
    return _zoom_common(l, x, z, w, h, False)


def _zoom_fuzzy(l, x, z, w, h):
    return _zoom_common(l, x, z, w, h, True)


def _neigh(l: Layer, x, z, w, h):
    p = l.p.area(x - 1, z - 1, w + 2, h + 2)
    return p, p[1:-1, 1:-1]


def _land16(l: Layer, x, z, w, h):
    p, v11 = _neigh(l, x, z, w, h)
    v00, v20, v02, v22 = p[:-2, :-2], p[:-2, 2:], p[2:, :-2], p[2:, 2:]
    xx, zz = _grid(x, z, w, h)
    cs = chunk_seed(l.ss, xx, zz)
    st = _u(l.st)
    out = v11.copy()
    # land next to ocean may sink
    shore = (v11 != 0) & ((v00 == 0) | (v20 == 0) | (v02 == 0) | (v22 == 0))
    sink = shore & (first_int(cs, 5) == 0)
    out[sink] = np.where(v11[sink] == SNOWY_TUNDRA, FROZEN_OCEAN, OCEAN)
    # ocean next to land may rise, taking the biome of a neighbour
    grow = (v11 == 0) & ~((v00 == 0) & (v20 == 0) & (v02 == 0) & (v22 == 0))
    if grow.any():
        idx = np.nonzero(grow)
        c = cs[idx]
        inc = np.zeros(len(c), np.int64)
        v = np.ones(len(c), np.int64)
        for nb, mods in ((v00, None), (v20, (2,)), (v02, (2, 3)), (v22, (2, 3, 4))):
            n = nb[idx]
            has = n != OCEAN
            inc = inc + has
            if mods is None:
                take = has
            else:
                take = has & (inc == 1)
                for k, m in enumerate(mods):
                    cond = inc == k + 2 if k + 1 < len(mods) else inc >= k + 2
                    take |= has & cond & (first_int(c, m) == 0)
            v = np.where(take, n, v)
            with np.errstate(over="ignore"):
                c = np.where(has, step(c, st), c)
        keep = first_int(c, 3) == 0
        out[idx] = np.where(keep, v, np.where(v == SNOWY_TUNDRA, FROZEN_OCEAN, OCEAN))
    return out


def _land_b18(l: Layer, x, z, w, h):
    p, v11 = _neigh(l, x, z, w, h)
    v00, v20, v02, v22 = p[:-2, :-2], p[:-2, 2:], p[2:, :-2], p[2:, 2:]
    xx, zz = _grid(x, z, w, h)
    cs = chunk_seed(l.ss, xx, zz)
    out = v11.copy()
    a = (v11 == 0) & ((v00 != 0) | (v02 != 0) | (v20 != 0) | (v22 != 0))
    b = (v11 == 1) & ((v00 != 1) | (v02 != 1) | (v20 != 1) | (v22 != 1))
    out[a] = first_int(cs, 3)[a] // 2
    out[b] = 1 - first_int(cs, 5)[b] // 4
    return out


def _snow16(l: Layer, x, z, w, h):
    v = l.p.area(x, z, w, h)
    xx, zz = _grid(x, z, w, h)
    snow = first_int(chunk_seed(l.ss, xx, zz), 5) == 0
    return np.where(v != OCEAN, np.where(snow, SNOWY_TUNDRA, PLAINS), v)


def _mushroom(l: Layer, x, z, w, h):
    p, v11 = _neigh(l, x, z, w, h)
    xx, zz = _grid(x, z, w, h)
    alone = (v11 == 0) & (p[:-2, :-2] == 0) & (p[:-2, 2:] == 0) & (p[2:, :-2] == 0) & (p[2:, 2:] == 0)
    hit = alone & (first_int(chunk_seed(l.ss, xx, zz), 100) == 0)
    return np.where(hit, MUSHROOM, v11)


def _biome(l: Layer, x, z, w, h):
    v = l.p.area(x, z, w, h)
    xx, zz = _grid(x, z, w, h)
    cs = chunk_seed(l.ss, xx, zz)
    new = OLD_BIOMES_11[first_int(cs, 6)] if l.version <= 11 else OLD_BIOMES[first_int(cs, 7)]
    # the cold land becomes snowy tundra; from 1.3 its taiga stays taiga
    new = np.where((v != PLAINS) & ((new != TAIGA) | (l.version <= 12)), SNOWY_TUNDRA, new)
    return np.where((v == OCEAN) | (v == MUSHROOM), v, new)


def _noise(l: Layer, x, z, w, h):
    v = l.p.area(x, z, w, h)
    xx, zz = _grid(x, z, w, h)
    return np.where(v > 0, first_int(chunk_seed(l.ss, xx, zz), 2) + 2, 0)


def _hills(l: Layer, x, z, w, h):
    p = l.p.area(x - 1, z - 1, w + 2, h + 2)
    a11 = p[1:-1, 1:-1]
    xx, zz = _grid(x, z, w, h)
    try_ = first_int(chunk_seed(l.ss, xx, zz), 3) == 0
    hill = a11.copy()
    for src, dst in ((DESERT, DESERT_HILLS), (FOREST, WOODED_HILLS), (TAIGA, TAIGA_HILLS), (PLAINS, FOREST),
                     (SNOWY_TUNDRA, SNOWY_MOUNTAINS), (JUNGLE, JUNGLE_HILLS)):
        hill[a11 == src] = dst
    cat = _CATEGORY[a11]
    equals = sum((_CATEGORY[n] == cat).astype(int) for n in (p[:-2, 1:-1], p[1:-1, 2:], p[1:-1, :-2], p[2:, 1:-1]))
    return np.where(try_ & (hill != a11) & (equals >= 4), hill, a11)


def _shore(l: Layer, x, z, w, h):
    p, v11 = _neigh(l, x, z, w, h)
    ns = (p[:-2, 1:-1], p[1:-1, 2:], p[1:-1, :-2], p[2:, 1:-1])
    any_ocean = (ns[0] == OCEAN) | (ns[1] == OCEAN) | (ns[2] == OCEAN) | (ns[3] == OCEAN)
    out = np.where((v11 == MUSHROOM) & any_ocean, MUSHROOM_SHORE, v11)
    if l.version <= 10:
        return out
    all_mtn = (ns[0] == MOUNTAINS) & (ns[1] == MOUNTAINS) & (ns[2] == MOUNTAINS) & (ns[3] == MOUNTAINS)
    out = np.where((v11 == MOUNTAINS) & ~all_mtn, MOUNTAIN_EDGE, out)
    beach = (v11 != MUSHROOM) & (v11 != MOUNTAINS) & (v11 != OCEAN) & (v11 != RIVER) & (v11 != SWAMP) & any_ocean
    return np.where(beach, BEACH, out)


def _swamp_river(l: Layer, x, z, w, h):
    v = l.p.area(x, z, w, h)
    xx, zz = _grid(x, z, w, h)
    fi = chunk_seed(l.ss, xx, zz)
    # a swamp, and from 1.2 a jungle, may become river
    hit = ((v == SWAMP) & (first_int(fi, 6) == 0)) | (np.isin(v, (JUNGLE, JUNGLE_HILLS)) & (first_int(fi, 8) == 0))
    return np.where(hit, RIVER, v)


def _river(l: Layer, x, z, w, h):
    p, v11 = _neigh(l, x, z, w, h)
    same = (v11 == p[1:-1, :-2]) & (v11 == p[:-2, 1:-1]) & (v11 == p[2:, 1:-1]) & (v11 == p[1:-1, 2:])
    return np.where(v11 == 0, RIVER, np.where(same, -1, RIVER))


def _smooth(l: Layer, x, z, w, h):
    p, v11 = _neigh(l, x, z, w, h)
    v01, v10, v21, v12 = p[1:-1, :-2], p[:-2, 1:-1], p[1:-1, 2:], p[2:, 1:-1]
    xx, zz = _grid(x, z, w, h)
    bit = (chunk_seed(l.ss, xx, zz) >> U64(24)) & U64(1)
    both = (v01 == v21) & (v10 == v12)
    out = np.where(both, np.where(bit == 1, v10, v01), np.where(v10 == v12, v10, np.where(v01 == v21, v01, v11)))
    return np.where((v11 != v01) | (v11 != v10), out, v11)


def _river_mix(l: Layer, x, z, w, h):
    v = l.p.area(x, z, w, h)
    r = l.p2.area(x, z, w, h)
    riv = (r == RIVER) & (v != OCEAN)
    new = np.where(v == SNOWY_TUNDRA, FROZEN_RIVER,
                   np.where((v == MUSHROOM) | (v == MUSHROOM_SHORE), MUSHROOM_SHORE, RIVER))
    return np.where(riv, new, v)


def _voronoi(l: Layer, x, z, w, h):
    x -= 2
    z -= 2
    px, pz = x >> 2, z >> 2
    pw, ph = ((x + w) >> 2) - px + 2, ((z + h) >> 2) - pz + 2
    p = l.p.area(px, pz, pw, ph)
    ii, jj = _grid(0, 0, pw - 1, ph - 1)
    gx, gz = (ii + px).astype(np.int64), (jj + pz).astype(np.int64)

    def jitter(cx, cz, ox, oz):
        cs = chunk_seed(l.ss, cx * 4, cz * 4)
        d1 = (first_int(cs, 1024) - 512) * 36 + ox
        d2 = (first_int(step(cs, _u(l.st)), 1024) - 512) * 36 + oz
        return d1, d2

    da = jitter(gx, gz, 0, 0)
    db = jitter(gx + 1, gz, 40 * 1024, 0)
    dc = jitter(gx, gz + 1, 0, 40 * 1024)
    dd = jitter(gx + 1, gz + 1, 40 * 1024, 40 * 1024)
    v00, v10, v01, v11 = p[:-1, :-1], p[:-1, 1:], p[1:, :-1], p[1:, 1:]
    out = np.empty((4 * (ph - 1), 4 * (pw - 1)), np.int64)
    for jjj in range(4):
        mj = 10240 * jjj
        for iii in range(4):
            mi = 10240 * iii
            dist = [(mi - d1) ** 2 + (mj - d2) ** 2 for d1, d2 in (da, db, dc, dd)]
            a, b, c, d = dist
            v = np.where((a < b) & (a < c) & (a < d), v00,
                         np.where((b < a) & (b < c) & (b < d), v10,
                                  np.where((c < a) & (c < b) & (c < d), v01, v11)))
            out[jjj::4, iii::4] = v
    ox, oz = x - px * 4, z - pz * 4
    return out[oz:oz + h, ox:ox + w]


# ------------------------------------------------------------------ stacks

VERSIONS = {"b1.8": 8, "1.0": 10, "1.1": 11, "1.2": 12, "1.3": 13, "1.4": 14, "1.5": 15, "1.6": 16}


class Stack:
    """The GenLayer stack of one version; ``biomes4`` (1:4, used by the terrain) and ``biomes``
    (1:1, used by the surface).  ``large_biomes``: the "Large Biomes" world type (1.3+)."""

    def __init__(self, version: str, seed: int, large_biomes: bool = False):
        v = VERSIONS[version]
        large = large_biomes and v >= 13
        L = Layer
        if v == 8:
            p = L(_continent, 1)
            p = L(_zoom_fuzzy, 2000, p)
            p = L(_land_b18, 1, p)
            p = L(_zoom, 2001, p)
            p = L(_land_b18, 2, p)
            p = L(_zoom, 2002, p)
            p = L(_land_b18, 3, p)
            p = L(_zoom, 2003, p)
            p = L(_land_b18, 3, p)
            p = L(_zoom, 2004, p)
            land = L(_land_b18, 3, p)
        else:
            p = L(_continent, 1)
            p = L(_zoom_fuzzy, 2000, p)
            p = L(_land16, 1, p)
            p = L(_zoom, 2001, p)
            p = L(_land16, 2, p)
            p = L(_snow16, 2, p)
            p = L(_zoom, 2002, p)
            p = L(_land16, 3, p)
            p = L(_zoom, 2003, p)
            p = L(_land16, 4, p)
            land = L(_mushroom, 5, p)
        p = L(_biome, 200, land)
        p = L(_zoom, 1000, p)
        z64 = L(_zoom, 1001, p)
        noise = L(_noise, 100, land)
        if v <= 10:
            p = L(_zoom, 1000, z64)
            p = L(_land_b18 if v == 8 else _land16, 3, p)
            p = L(_shore, 1000, p)
            p = L(_zoom, 1001, p)
            p = L(_zoom, 1002, p)
            p = L(_zoom, 1003, p)
        else:
            hz = L(_zoom, 0, noise)
            hz = L(_zoom, 0, hz)
            p = L(_hills, 1000, z64, hz)
            p = L(_zoom, 1000, p)
            p = L(_land16, 3, p)
            p = L(_zoom, 1001, p)
            p = L(_shore, 1000, p)
            p = L(_swamp_river, 1000, p)
            p = L(_zoom, 1002, p)
            p = L(_zoom, 1003, p)
            if large:
                p = L(_zoom, 1004, p)
                p = L(_zoom, 1005, p)
        biome = L(_smooth, 1000, p)
        r = noise
        for salt in (1000, 1001, 1002, 1003, 1004, 1005) + ((1006, 1007) if large else ()):
            r = L(_zoom, salt, r)
        r = L(_river, 1, r)
        r = L(_smooth, 1000, r)
        self.mix = L(_river_mix, 100, biome, r)
        self.voronoi = L(_voronoi, 10, self.mix)
        self.voronoi.seed(seed)
        for layer in self._all(self.voronoi):
            layer.version = v
        self._c4, self._c1 = AreaCache(16), AreaCache(64)

    @staticmethod
    def _all(layer):
        out, todo = [], [layer]
        while todo:
            q = todo.pop()
            if q is None or q in out:
                continue
            out.append(q)
            todo += [q.p, q.p2]
        return out

    def biomes4(self, x: int, z: int, w: int, h: int) -> np.ndarray:
        return self._c4.area(self.mix, x, z, w, h)

    def biomes(self, x: int, z: int, w: int, h: int) -> np.ndarray:
        return self._c1.area(self.voronoi, x, z, w, h)
