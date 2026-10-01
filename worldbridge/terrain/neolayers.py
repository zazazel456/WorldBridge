"""Biomes of neoLegacy (the PC port of Legacy Console Edition, TU31 content), for the terrain
generator of LCE targets (neogen).

A numpy port of Layer::getDefaultLayers and of every layer class of the neoLegacy source
(Minecraft.World/*Layer.cpp, VoronoiZoom.cpp).  The stack looks like Java 1.7 - 1.8 but 4J changed it
enough that no Java version gives the same biomes:

* the "warm" climate draws from the 1.1 list (desert, forest, extreme hills, swamp, plains, taiga);
* the biomes are not zoomed before BiomeEdge / RegionHills (Java: two zooms), so they come out
  four times larger than in Java, while the rivers keep their size;
* the hills noise is 2 or 3 (Java 1.8: 2 - 300001): every hills spot is a hills or an "M" biome;
* the layers of the hills noise are seeded (Java leaves them at zero);
* mushroom islands are added inside the zoom loop and grown, shores and river mixing follow 4J.

Primitives (per-position random, zoom, smooth, river, voronoi) come from genlayers, whose semantics
are the same in the 4J code.  ``NeoStack(seed).biomes4`` is the 1:4 grid of the terrain,
``biomes`` the 1:1 grid stored in the chunks.
"""

from __future__ import annotations

import numpy as np

from .genlayers import AreaCache, Layer, _grid, _neigh, _river, _smooth, _u, _voronoi, _zoom, _zoom_fuzzy, chunk_seed, first_int, step

OCEAN, PLAINS, DESERT, EXTREME_HILLS, FOREST, TAIGA, SWAMP, RIVER = 0, 1, 2, 3, 4, 5, 6, 7
FROZEN_OCEAN, FROZEN_RIVER, ICE_FLATS, ICE_MOUNTAINS, MUSHROOM, MUSHROOM_SHORE, BEACH = 10, 11, 12, 13, 14, 15, 16
DESERT_HILLS, FOREST_HILLS, TAIGA_HILLS, SMALLER_EXTREME_HILLS, JUNGLE, JUNGLE_HILLS, JUNGLE_EDGE = 17, 18, 19, 20, 21, 22, 23
DEEP_OCEAN, STONE_BEACH, COLD_BEACH, BIRCH_FOREST, BIRCH_FOREST_HILLS, ROOFED_FOREST = 24, 25, 26, 27, 28, 29
COLD_TAIGA, COLD_TAIGA_HILLS, MEGA_TAIGA, MEGA_TAIGA_HILLS, EXTREME_HILLS_PLUS = 30, 31, 32, 33, 34
SAVANNA, SAVANNA_PLATEAU, MESA, MESA_PLATEAU_F, MESA_PLATEAU = 35, 36, 37, 38, 39
ICE_SPIKES, JUNGLE_M, JUNGLE_EDGE_M = 140, 149, 151
MESA_BRYCE, MESA_PLATEAU_F_M, MESA_PLATEAU_M = 165, 166, 167

# Biome.cpp: the registered biomes, their temperature and rain
_REGISTERED = list(range(40)) + [129, 130, 131, 132, 133, 134, 140, 149, 151, 155, 156, 157, 158] + list(range(160, 168))
_TEMP = {0: 0.5, 1: 0.8, 2: 2.0, 3: 0.2, 4: 0.7, 5: 0.25, 6: 0.8, 7: 0.5, 8: 2.0, 9: 0.5, 10: 0.0, 11: 0.0, 12: 0.0,
         13: 0.0, 14: 0.9, 15: 0.9, 16: 0.8, 17: 2.0, 18: 0.7, 19: 0.25, 20: 0.2, 21: 1.2, 22: 1.2, 23: 0.95, 24: 0.5,
         25: 0.2, 26: 0.05, 27: 0.6, 28: 0.6, 29: 0.7, 30: -0.5, 31: -0.5, 32: 0.3, 33: 0.3, 34: 0.2, 35: 1.2, 36: 1.0,
         37: 2.0, 38: 2.0, 39: 2.0, 129: 0.8, 130: 2.0, 131: 0.2, 132: 0.7, 133: 0.25, 134: 0.8, 140: 0.0, 149: 1.2,
         151: 0.95, 155: 0.6, 156: 0.6, 157: 0.7, 158: -0.5, 160: 0.3, 161: 0.3, 162: 0.2, 163: 1.1, 164: 1.0,
         165: 2.0, 166: 2.0, 167: 2.0}
_NO_RAIN = {2, 8, 9, 17, 35, 36, 37, 38, 39, 130, 163, 164, 165, 166, 167}
_OCEAN_CLASS = {0, 10, 24}
_MUTATED_OF = {131: 3, 155: 27, 156: 28, 157: 29, 162: 34, 163: 35, 164: 36}

_N = 4096                       # ids never exceed 0xFFF (BiomeInit's special bits included)
_RESOLVED = np.zeros(_N, np.int64)                  # Biome::getBiome: unknown ids are the ocean
_RESOLVED[_REGISTERED] = _REGISTERED
_KNOWN = np.zeros(_N, bool)
_KNOWN[_REGISTERED] = True
_SNOW = np.zeros(_N, bool)                          # Biome::hasSnow
_CAT = np.full(_N, 2, np.int64)                     # Biome::getTemperatureCategory (unknown -> ocean's)
for _b in _REGISTERED:
    _SNOW[_b] = _b not in _NO_RAIN and _TEMP[_b] < 0.15
    _t = _TEMP[_MUTATED_OF.get(_b, _b)]
    _CAT[_b] = 0 if _MUTATED_OF.get(_b, _b) in _OCEAN_CLASS else 1 if _t < 0.2 else 3 if _t > 1.0 else 2
_CAT[~_KNOWN] = 0
_MESA_PLATEAUS = np.zeros(_N, bool)
_MESA_PLATEAUS[[MESA_PLATEAU_F, MESA_PLATEAU]] = True


def _ids(a):
    return np.clip(a, 0, _N - 1)


def is_ocean(a):
    return (a == OCEAN) | (a == DEEP_OCEAN) | (a == FROZEN_OCEAN)


def is_same(a, b):
    """Layer::isSame: the same biome, or two mesa plateaus (unknown ids count as the ocean)."""
    ra, rb = _RESOLVED[_ids(a)], _RESOLVED[_ids(b)]
    return (a == b) | np.where(_MESA_PLATEAUS[ra], _MESA_PLATEAUS[rb], ra == rb)


def _cross(p):
    """North, east, west, south neighbours of the centre of a padded area."""
    return p[:-2, 1:-1], p[1:-1, 2:], p[1:-1, :-2], p[2:, 1:-1]


def _diag(p):
    return p[:-2, :-2], p[:-2, 2:], p[2:, :-2], p[2:, 2:]


def _cs(l, x, z, w, h):
    xx, zz = _grid(x, z, w, h)
    return chunk_seed(l.ss, xx, zz)


def _next(l, cs):
    return step(cs, _u(l.st))


# ------------------------------------------------------------------ continents

def _island(l, x, z, w, h):
    out = (first_int(_cs(l, x, z, w, h), 10) == 0).astype(np.int64)
    if -w < x <= 0 and -h < z <= 0:
        out[-z, -x] = 1
    return out


def _add_island(l, x, z, w, h):
    """AddIslandLayer: coasts grow or sink; a sinking cool (4) square stays 4."""
    p, c = _neigh(l, x, z, w, h)
    n1, n2, n3, n4 = _diag(p)
    cs = _cs(l, x, z, w, h)
    out = c.copy()
    sink = (c > 0) & ((n1 == 0) | (n2 == 0) | (n3 == 0) | (n4 == 0))
    hit = sink & (first_int(cs, 5) == 0)
    out[hit] = np.where(c[hit] == 4, 4, 0)
    grow = (c == 0) & ((n1 != 0) | (n2 != 0) | (n3 != 0) | (n4 != 0))
    if grow.any():
        idx = np.nonzero(grow)
        r = cs[idx]
        odds = np.ones(len(r), np.int64)
        swap = np.ones(len(r), np.int64)
        for nb in (n1, n2, n3, n4):
            n = nb[idx]
            has = n != 0
            take = np.zeros(len(r), bool)
            for m in np.unique(odds[has]):
                sel = has & (odds == m)
                take[sel] = first_int(r[sel], int(m)) == 0
            swap = np.where(take, n, swap)
            r = np.where(has, _next(l, r), r)
            odds = odds + has
        keep = first_int(r, 3) == 0
        out[idx] = np.where(keep, swap, np.where(swap == 4, 4, 0))
    return out


def _remove_too_much_ocean(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    n, e, ww, s = _cross(p)
    alone = (c == 0) & (n == 0) & (e == 0) & (ww == 0) & (s == 0)
    return np.where(alone & (first_int(_cs(l, x, z, w, h), 2) == 0), 1, c)


def _add_snow(l, x, z, w, h):
    c = l.p.area(x, z, w, h)
    r = first_int(_cs(l, x, z, w, h), 6)
    return np.where(c == 0, 0, np.where(r == 0, 4, np.where(r <= 1, 3, 1)))


def _cool_warm(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    ns = _cross(p)
    near = np.zeros_like(c, bool)
    for n in ns:
        near |= (n == 3) | (n == 4)
    return np.where((c == 1) & near, 2, c)


def _heat_ice(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    ns = _cross(p)
    near = np.zeros_like(c, bool)
    for n in ns:
        near |= (n == 1) | (n == 2)
    return np.where((c == 4) & near, 3, c)


def _special(l, x, z, w, h):
    c = l.p.area(x, z, w, h)
    cs = _cs(l, x, z, w, h)
    hit = (c != 0) & (first_int(cs, 13) == 0)
    extra = ((first_int(_next(l, cs), 15) + 1) << 8) & 0xF00
    return np.where(hit, c | extra, c)


def _deep_ocean(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    zeros = sum((n == 0).astype(np.int64) for n in _cross(p))
    return np.where((c == 0) & (zeros > 3), DEEP_OCEAN, c)


# ------------------------------------------------------------------ biomes

_DESERT_LIST = np.array([DESERT, FOREST, EXTREME_HILLS, SWAMP, PLAINS, TAIGA])
_WARM_LIST = np.array([FOREST, ROOFED_FOREST, EXTREME_HILLS, PLAINS, BIRCH_FOREST, SWAMP])
_COOL_LIST = np.array([FOREST, EXTREME_HILLS, TAIGA, PLAINS])
_ICY_LIST = np.array([ICE_FLATS, ICE_FLATS, ICE_FLATS, COLD_TAIGA])


def _biome_init(l, x, z, w, h):
    val = l.p.area(x, z, w, h)
    cs = _cs(l, x, z, w, h)
    special = (val >> 8) & 0xF
    v = val & ~0xF00
    out = v.copy()
    sp = special > 0
    out = np.where((v == 1) & ~sp, _DESERT_LIST[first_int(cs, 6)], out)
    out = np.where((v == 1) & sp, np.where(first_int(cs, 3) != 0, MESA_PLATEAU_F, MESA_PLATEAU), out)
    out = np.where((v == 2) & ~sp, _WARM_LIST[first_int(cs, 6)], out)
    out = np.where((v == 2) & sp, JUNGLE, out)
    out = np.where((v == 3) & ~sp, _COOL_LIST[first_int(cs, 4)], out)
    out = np.where((v == 3) & sp, MEGA_TAIGA, out)
    out = np.where(v == 4, _ICY_LIST[first_int(cs, 4)], out)
    return np.where(is_ocean(v) | (v == MUSHROOM), v, out)


def _valid_temperature_edge(n, target):
    cn, ct = _CAT[_ids(n)], _CAT[_ids(target)]
    return is_same(n, target) | (cn == ct) | (cn == 2) | (ct == 2)


def _biome_edge(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    ns = _cross(p)
    out = c.copy()
    done = np.zeros_like(c, bool)
    hills = is_same(c, EXTREME_HILLS)
    interior = np.ones_like(c, bool)
    for n in ns:
        interior &= _valid_temperature_edge(n, EXTREME_HILLS)
    out = np.where(hills & ~interior, SMALLER_EXTREME_HILLS, out)
    done |= hills
    for biome, target in ((MESA_PLATEAU_F, MESA), (MESA_PLATEAU, MESA), (MEGA_TAIGA, TAIGA)):
        this = ~done & (c == biome)
        inside = np.ones_like(c, bool)
        for n in ns:
            inside &= is_same(n, biome)
        out = np.where(this & ~inside, target, out)
        done |= this

    def near(ids):
        r = np.zeros_like(c, bool)
        for n in ns:
            r |= np.isin(n, ids)
        return r

    desert = ~done & (c == DESERT)
    out = np.where(desert & near([ICE_FLATS]), EXTREME_HILLS_PLUS, out)
    swamp = ~done & (c == SWAMP)
    out = np.where(swamp & near([DESERT, COLD_TAIGA, ICE_FLATS]), PLAINS,
                   np.where(swamp & near([JUNGLE]), JUNGLE_EDGE, out))
    return out


_HILL_OF = np.arange(_N)
for _a, _b in ((DESERT, DESERT_HILLS), (FOREST, FOREST_HILLS), (BIRCH_FOREST, BIRCH_FOREST_HILLS),
               (ROOFED_FOREST, PLAINS), (TAIGA, TAIGA_HILLS), (MEGA_TAIGA, MEGA_TAIGA_HILLS),
               (COLD_TAIGA, COLD_TAIGA_HILLS), (ICE_FLATS, ICE_MOUNTAINS), (JUNGLE, JUNGLE_HILLS),
               (OCEAN, DEEP_OCEAN), (EXTREME_HILLS, EXTREME_HILLS_PLUS), (SAVANNA, SAVANNA_PLATEAU),
               (MESA_PLATEAU_F, MESA), (MESA_PLATEAU, MESA)):
    _HILL_OF[_a] = _b


def _mutated(i):
    """i + 128 where that biome exists, else None (-1)."""
    j = _ids(i + 128)
    return np.where((i + 128 < _N) & _KNOWN[j], i + 128, -1)


def _region_hills(l, x, z, w, h):
    p, k = _neigh(l, x, z, w, h)
    noise = l.p2.area(x - 1, z - 1, w + 2, h + 2)[1:-1, 1:-1]
    cs = _cs(l, x, z, w, h)
    flag = (noise - 2) % 29 == 0                   # C++ %: noise is never negative here
    first = (k != 0) & (noise >= 2) & ((noise - 2) % 29 == 1) & (k < 128)
    m = _mutated(k)
    out_first = np.where(m >= 0, m, k)
    r1 = first_int(cs, 3)
    keep = (r1 != 0) & ~flag
    cs2 = _next(l, cs)
    i1 = _HILL_OF[_ids(k)].copy()
    plains = k == PLAINS
    i1 = np.where(plains, np.where(first_int(cs2, 3) == 0, FOREST_HILLS, FOREST), i1)
    deep = (k == DEEP_OCEAN) & (first_int(cs2, 3) == 0)
    i1 = np.where(deep, np.where(first_int(_next(l, cs2), 2) == 0, PLAINS, FOREST), i1)
    mi = _mutated(i1)
    i1 = np.where(flag & (i1 != k), np.where(mi >= 0, mi, k), i1)
    ns = _cross(p)
    count = sum(is_same(n, k).astype(np.int64) for n in ns)
    hilled = np.where(i1 == k, k, np.where(count >= 3, i1, k))
    return np.where(first, out_first, np.where(keep, k, hilled))


def _rare_biome(l, x, z, w, h):
    k = l.p.area(x, z, w, h)
    hit = (first_int(_cs(l, x, z, w, h), 57) == 0) & (k == PLAINS)
    return np.where(hit, k + 128, k)


def _add_mushroom(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    n1, n2, n3, n4 = _diag(p)
    alone = (c == 0) & (n1 == 0) & (n2 == 0) & (n3 == 0) & (n4 == 0)
    return np.where(alone & (first_int(_cs(l, x, z, w, h), 100) == 0), MUSHROOM, c)


def _grow_mushroom(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    near = np.zeros_like(c, bool)
    for n in _diag(p):
        near |= n == MUSHROOM
    return np.where(near, MUSHROOM, c)


_JUNGLE_OK = np.zeros(_N, bool)
_JUNGLE_OK[[JUNGLE, JUNGLE_HILLS, JUNGLE_EDGE, JUNGLE_M, JUNGLE_EDGE_M, FOREST, TAIGA, OCEAN, DEEP_OCEAN, FROZEN_OCEAN]] = True
_MESA_ANY = np.zeros(_N, bool)
_MESA_ANY[[MESA, MESA_PLATEAU_F, MESA_PLATEAU, MESA_BRYCE, MESA_PLATEAU_F_M, MESA_PLATEAU_M]] = True


def _shore(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    ns = _cross(p)
    near_ocean = np.zeros_like(c, bool)
    near_plain_ocean = np.zeros_like(c, bool)
    jungle_ok = np.ones_like(c, bool)
    all_mesa = np.ones_like(c, bool)
    for n in ns:
        near_ocean |= is_ocean(n)
        near_plain_ocean |= n == OCEAN
        jungle_ok &= _JUNGLE_OK[_ids(n)]
        all_mesa &= _MESA_ANY[_ids(n)]
    beach_if_near = np.where(near_ocean, BEACH, c)
    out = np.where(np.isin(c, [OCEAN, DEEP_OCEAN, RIVER, SWAMP]), c, beach_if_near)
    out = np.where(np.isin(c, [MESA, MESA_PLATEAU_F]), np.where(near_ocean, BEACH, np.where(all_mesa, c, DESERT)), out)
    snowy = _SNOW[_RESOLVED[_ids(c)]]
    out = np.where(snowy, np.where(~is_ocean(c) & near_ocean, COLD_BEACH, c), out)
    hills = np.isin(c, [EXTREME_HILLS, EXTREME_HILLS_PLUS, SMALLER_EXTREME_HILLS])
    out = np.where(hills, np.where(near_ocean, STONE_BEACH, c), out)
    jungle = np.isin(c, [JUNGLE, JUNGLE_HILLS, JUNGLE_M])
    out = np.where(jungle, np.where(~jungle_ok, JUNGLE_EDGE, np.where(near_ocean, BEACH, c)), out)
    return np.where(c == MUSHROOM, np.where(near_plain_ocean, MUSHROOM_SHORE, c), out)


def _river_init(l, x, z, w, h):
    b = l.p.area(x, z, w, h)
    return np.where(b > 0, first_int(_cs(l, x, z, w, h), 2) + 2, 0)


def _river_mix(l, x, z, w, h):
    b = l.p.area(x, z, w, h)
    r = l.p2.area(x, z, w, h)
    river = np.where(np.isin(b, [ICE_FLATS, ICE_SPIKES, COLD_TAIGA, COLD_TAIGA_HILLS]), FROZEN_RIVER,
                     np.where((b == MUSHROOM) | (b == MUSHROOM_SHORE), MUSHROOM, r))
    return np.where(is_ocean(b), b, np.where(r >= 0, river, b))


# ------------------------------------------------------------------ stack

class NeoStack:
    """Layer::getDefaultLayers of neoLegacy (normal or large biomes)."""

    def __init__(self, seed: int, large_biomes: bool = False):
        L = Layer
        p = L(_island, 1)
        p = L(_zoom_fuzzy, 2000, p)
        p = L(_add_island, 1, p)
        p = L(_zoom, 2001, p)
        p = L(_add_island, 2, p)
        p = L(_add_island, 50, p)
        p = L(_add_island, 70, p)
        p = L(_remove_too_much_ocean, 2, p)
        p = L(_add_snow, 2, p)
        p = L(_add_island, 3, p)
        p = L(_cool_warm, 2, p)
        p = L(_heat_ice, 2, p)
        p = L(_special, 3, p)
        p = L(_zoom, 2002, p)
        p = L(_zoom, 2003, p)
        p = L(_add_island, 4, p)
        base = L(_deep_ocean, 4, p)
        river_init = L(_river_init, 100, base)
        hills_noise = L(_zoom, 1001, L(_zoom, 1000, river_init))
        r = L(_zoom, 1001, L(_zoom, 1000, river_init))
        for i in range(4):
            r = L(_zoom, 1000 + i, r)
        r = L(_smooth, 1000, L(_river, 1, r))
        b = L(_biome_init, 200, base)
        b = L(_biome_edge, 1000, b)
        b = L(_region_hills, 1000, b, hills_noise)
        b = L(_rare_biome, 1001, b)
        zoom_level = 6 if large_biomes else 4
        for i in range(zoom_level):
            b = L(_zoom, 1000 + i, b)
            if i == 0:
                b = L(_add_island, 3, b)
                b = L(_add_mushroom, 5, b)
            if i == 1:
                b = L(_grow_mushroom, 5, b)
                b = L(_shore, 1000, b)
        b = L(_smooth, 1000, b)
        self.mix = L(_river_mix, 100, b, r)
        self.voronoi = L(_voronoi, 10, self.mix)
        self.voronoi.seed(seed)
        self._c4, self._c1 = AreaCache(16), AreaCache(64)

    def biomes4(self, x: int, z: int, w: int, h: int) -> np.ndarray:
        """[h, w] biome ids of the 1:4 grid (getRawBiomeBlock)."""
        return self._c4.area(self.mix, x, z, w, h)

    def biomes(self, x: int, z: int, w: int, h: int) -> np.ndarray:
        """[h, w] biome ids of the blocks (getBiomeBlock)."""
        return self._c1.area(self.voronoi, x, z, w, h)
