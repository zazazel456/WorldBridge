"""Biomes of Minecraft Java 1.7 - 1.17 (the GenLayer stack of the "layered" biome source), for the
terrain generators of those versions.

A numpy port of cubiomes (https://github.com/Cubitect/cubiomes, MIT License, Copyright (c) 2020
Cubitect), which reproduces the game's GenLayer classes exactly.  The stack of 1.7 replaced the
one of 1.1 - 1.6: climates (warm, lush, cold, freezing), rare "special" variants (mesa plateaus,
jungle, mega taiga), hills and "M" biomes from the river noise, jungle edges and stone shores.
Later changes, all following the game:

* 1.9 - 1.10: the birch forest's mutation is the tall birch hills (MC-98995);
* 1.13: the hills noise is seeded; warm, lukewarm, cold and frozen oceans are mixed in last;
* 1.14: bamboo jungles;
* 1.15: the last (voronoi) zoom is seeded by a SHA-256 of the world seed and is 3D;
* 1.16: the badlands plateaus are no longer "similar" to each other.

Layers whose semantics are the same as neoLegacy's (neolayers) or older Java's (genlayers) are
reused.  ``Stack17(version, seed).biomes4`` is the 1:4 grid of the terrain, ``biomes`` the 1:1 grid
stored in the chunks.
"""

from __future__ import annotations

import hashlib
import math
import struct

import numpy as np

from .genlayers import AreaCache, Layer, _grid, _neigh, _smooth, _u, _voronoi, _zoom, _zoom_fuzzy, chunk_seed, first_int, step
from .neolayers import (_add_island, _add_mushroom, _add_snow, _cool_warm, _cross, _deep_ocean, _heat_ice, _island,
                        _remove_too_much_ocean, _special)

# biome ids of Java 1.7 - 1.17
(OCEAN, PLAINS, DESERT, MOUNTAINS, FOREST, TAIGA, SWAMP, RIVER, NETHER, THE_END, FROZEN_OCEAN, FROZEN_RIVER,
 SNOWY_TUNDRA, SNOWY_MOUNTAINS, MUSHROOM, MUSHROOM_SHORE, BEACH, DESERT_HILLS, WOODED_HILLS, TAIGA_HILLS,
 MOUNTAIN_EDGE, JUNGLE, JUNGLE_HILLS, JUNGLE_EDGE, DEEP_OCEAN, STONE_SHORE, SNOWY_BEACH, BIRCH_FOREST,
 BIRCH_FOREST_HILLS, DARK_FOREST, SNOWY_TAIGA, SNOWY_TAIGA_HILLS, GIANT_TREE_TAIGA, GIANT_TREE_TAIGA_HILLS,
 WOODED_MOUNTAINS, SAVANNA, SAVANNA_PLATEAU, BADLANDS, WOODED_BADLANDS_PLATEAU, BADLANDS_PLATEAU) = range(40)
WARM_OCEAN, LUKEWARM_OCEAN, COLD_OCEAN, DEEP_WARM_OCEAN, DEEP_LUKEWARM_OCEAN, DEEP_COLD_OCEAN, DEEP_FROZEN_OCEAN = range(44, 51)
SUNFLOWER_PLAINS, BAMBOO_JUNGLE, BAMBOO_JUNGLE_HILLS = 129, 168, 169
TALL_BIRCH_FOREST, TALL_BIRCH_HILLS = 155, 156
NONE = -1

_N = 4096
_SHALLOW = np.zeros(_N, bool)
_SHALLOW[[OCEAN, FROZEN_OCEAN, WARM_OCEAN, LUKEWARM_OCEAN, COLD_OCEAN]] = True
_OCEANIC = _SHALLOW.copy()
_OCEANIC[[DEEP_OCEAN, DEEP_WARM_OCEAN, DEEP_LUKEWARM_OCEAN, DEEP_COLD_OCEAN, DEEP_FROZEN_OCEAN]] = True
_DEEP = _OCEANIC & ~_SHALLOW
_SNOWY = np.zeros(_N, bool)
_SNOWY[[FROZEN_OCEAN, FROZEN_RIVER, SNOWY_TUNDRA, SNOWY_MOUNTAINS, SNOWY_BEACH, SNOWY_TAIGA, SNOWY_TAIGA_HILLS,
        140, 158]] = True
_MESA = np.zeros(_N, bool)
_MESA[[BADLANDS, 165, 166, 167, WOODED_BADLANDS_PLATEAU, BADLANDS_PLATEAU]] = True

_MUTATION = {PLAINS: 129, DESERT: 130, MOUNTAINS: 131, FOREST: 132, TAIGA: 133, SWAMP: 134, SNOWY_TUNDRA: 140,
             JUNGLE: 149, JUNGLE_EDGE: 151, BIRCH_FOREST: 155, BIRCH_FOREST_HILLS: 156, DARK_FOREST: 157,
             SNOWY_TAIGA: 158, GIANT_TREE_TAIGA: 160, GIANT_TREE_TAIGA_HILLS: 161, WOODED_MOUNTAINS: 162,
             SAVANNA: 163, SAVANNA_PLATEAU: 164, BADLANDS: 165, WOODED_BADLANDS_PLATEAU: 166, BADLANDS_PLATEAU: 167}

_CATEGORY_OF = {}
for _cat, _ids in ((BEACH, (BEACH, SNOWY_BEACH)), (DESERT, (DESERT, DESERT_HILLS, 130)),
                   (MOUNTAINS, (MOUNTAINS, MOUNTAIN_EDGE, WOODED_MOUNTAINS, 131, 162)),
                   (FOREST, (FOREST, WOODED_HILLS, BIRCH_FOREST, BIRCH_FOREST_HILLS, DARK_FOREST, 132, 155, 156, 157)),
                   (SNOWY_TUNDRA, (SNOWY_TUNDRA, SNOWY_MOUNTAINS, 140)),
                   (JUNGLE, (JUNGLE, JUNGLE_HILLS, JUNGLE_EDGE, 149, 151, BAMBOO_JUNGLE, BAMBOO_JUNGLE_HILLS)),
                   (BADLANDS, (BADLANDS, 165, 166, 167)), (MUSHROOM, (MUSHROOM, MUSHROOM_SHORE)),
                   (STONE_SHORE, (STONE_SHORE,)), (OCEAN, tuple(np.nonzero(_OCEANIC)[0])),
                   (PLAINS, (PLAINS, 129)), (RIVER, (RIVER, FROZEN_RIVER)),
                   (SAVANNA, (SAVANNA, SAVANNA_PLATEAU, 163, 164)), (SWAMP, (SWAMP, 134)),
                   (TAIGA, (TAIGA, TAIGA_HILLS, SNOWY_TAIGA, SNOWY_TAIGA_HILLS, GIANT_TREE_TAIGA,
                            GIANT_TREE_TAIGA_HILLS, 133, 158, 160, 161))):
    for _i in _ids:
        _CATEGORY_OF[int(_i)] = _cat


def _tables(mc: int):
    cat = np.full(_N, NONE, np.int64)
    for i, c in _CATEGORY_OF.items():
        cat[i] = c
    # the badlands plateaus: a mesa before 1.16, their own category after
    cat[[WOODED_BADLANDS_PLATEAU, BADLANDS_PLATEAU]] = BADLANDS if mc <= 15 else BADLANDS_PLATEAU
    mut = np.full(_N, NONE, np.int64)
    for a, b in _MUTATION.items():
        mut[a] = b
    if 9 <= mc <= 10:                               # MC-98995
        mut[BIRCH_FOREST], mut[BIRCH_FOREST_HILLS] = TALL_BIRCH_HILLS, NONE
    return cat, mut


def _ids(a):
    return np.clip(a, 0, _N - 1)


def _similar(l, a, b):
    """areSimilar: the same biome or category (the two badlands plateaus before 1.16)."""
    cat = l.cat
    out = (a == b) | ((cat[_ids(a)] == cat[_ids(b)]) & (a >= 0) & (b >= 0))
    if l.mc <= 15:
        pa = (a == WOODED_BADLANDS_PLATEAU) | (a == BADLANDS_PLATEAU)
        pb = (b == WOODED_BADLANDS_PLATEAU) | (b == BADLANDS_PLATEAU)
        out = np.where(pa, pb | (a == b), out)
    return out


def _cs(l, x, z, w, h):
    xx, zz = _grid(x, z, w, h)
    return chunk_seed(l.ss, xx, zz)


def _next(l, cs):
    return step(cs, _u(l.st))


def _any4(ns, ids):
    r = np.zeros_like(ns[0], bool)
    for n in ns:
        r |= np.isin(n, ids)
    return r


# ------------------------------------------------------------------ biomes

_WARM = np.array([DESERT, DESERT, DESERT, SAVANNA, SAVANNA, PLAINS])
_LUSH = np.array([FOREST, DARK_FOREST, MOUNTAINS, PLAINS, BIRCH_FOREST, SWAMP])
_COLD = np.array([FOREST, MOUNTAINS, TAIGA, PLAINS])
_SNOW = np.array([SNOWY_TUNDRA, SNOWY_TUNDRA, SNOWY_TUNDRA, SNOWY_TAIGA])


def _biome(l, x, z, w, h):
    val = l.p.area(x, z, w, h)
    cs = _cs(l, x, z, w, h)
    high = (val & 0xF00) != 0
    v = val & ~0xF00
    out = np.full_like(v, MUSHROOM)
    out = np.where(v == 1, np.where(high, np.where(first_int(cs, 3) == 0, BADLANDS_PLATEAU, WOODED_BADLANDS_PLATEAU),
                                    _WARM[first_int(cs, 6)]), out)
    out = np.where(v == 2, np.where(high, JUNGLE, _LUSH[first_int(cs, 6)]), out)
    out = np.where(v == 3, np.where(high, GIANT_TREE_TAIGA, _COLD[first_int(cs, 4)]), out)
    out = np.where(v == 4, _SNOW[first_int(cs, 4)], out)
    return np.where(_OCEANIC[_ids(v)] | (v == MUSHROOM), v, out)


def _bamboo(l, x, z, w, h):
    v = l.p.area(x, z, w, h)
    return np.where((v == JUNGLE) & (first_int(_cs(l, x, z, w, h), 10) == 0), BAMBOO_JUNGLE, v)


def _biome_edge(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    ns = _cross(p)
    out = c.copy()
    done = np.zeros_like(c, bool)
    for base, edge in ((WOODED_BADLANDS_PLATEAU, BADLANDS), (BADLANDS_PLATEAU, BADLANDS), (GIANT_TREE_TAIGA, TAIGA)):
        this = ~done & (c == base)
        inside = np.ones_like(c, bool)
        for n in ns:
            inside &= _similar(l, n, np.full_like(n, base))
        out = np.where(this & ~inside, edge, out)
        done |= this
    out = np.where(~done & (c == DESERT) & _any4(ns, [SNOWY_TUNDRA]), WOODED_MOUNTAINS, out)
    swamp = ~done & (c == SWAMP)
    out = np.where(swamp & _any4(ns, [DESERT, SNOWY_TAIGA, SNOWY_TUNDRA]), PLAINS,
                   np.where(swamp & _any4(ns, [JUNGLE, BAMBOO_JUNGLE]), JUNGLE_EDGE, out))
    return out


def _noise(l, x, z, w, h):
    v = l.p.area(x, z, w, h)
    return np.where(v > 0, first_int(_cs(l, x, z, w, h), 299999) + 2, 0)


_HILL = {DESERT: DESERT_HILLS, FOREST: WOODED_HILLS, BIRCH_FOREST: BIRCH_FOREST_HILLS, DARK_FOREST: PLAINS,
         TAIGA: TAIGA_HILLS, GIANT_TREE_TAIGA: GIANT_TREE_TAIGA_HILLS, SNOWY_TAIGA: SNOWY_TAIGA_HILLS,
         SNOWY_TUNDRA: SNOWY_MOUNTAINS, JUNGLE: JUNGLE_HILLS, BAMBOO_JUNGLE: BAMBOO_JUNGLE_HILLS, OCEAN: DEEP_OCEAN,
         MOUNTAINS: WOODED_MOUNTAINS, SAVANNA: SAVANNA_PLATEAU}
_HILL_OF = np.arange(_N)
for _a, _b in _HILL.items():
    _HILL_OF[_a] = _b


def _hills(l, x, z, w, h):
    p, a11 = _neigh(l, x, z, w, h)
    b11 = l.p2.area(x - 1, z - 1, w + 2, h + 2)[1:-1, 1:-1]
    bn = np.fmod(b11 - 2, 29)                       # C's % (negative for the ocean's 0)
    mutated = (bn == 1) & (b11 >= 2) & ~_SHALLOW[_ids(a11)]
    m = l.mut[_ids(a11)]
    out_mut = np.where(m > 0, m, a11)
    cs = _cs(l, x, z, w, h)
    try_ = (bn == 0) | (first_int(cs, 3) == 0)
    hill = _HILL_OF[_ids(a11)].copy()
    cs2 = _next(l, cs)
    hill = np.where(a11 == PLAINS, np.where(first_int(cs2, 3) == 0, WOODED_HILLS, FOREST), hill)
    badl = _similar(l, a11, np.full_like(a11, WOODED_BADLANDS_PLATEAU))
    specials = np.isin(a11, list(_HILL)) | (a11 == PLAINS)
    hill = np.where(~specials & badl, BADLANDS, hill)
    deep = ~specials & ~badl & _DEEP[_ids(a11)]
    cs3 = _next(l, cs2)
    hill = np.where(deep & (first_int(cs2, 3) == 0), np.where(first_int(cs3, 2) == 0, PLAINS, FOREST), hill)
    mh = l.mut[_ids(hill)]
    hill = np.where((bn == 0) & (hill != a11), np.where(mh < 0, a11, mh), hill)
    count = sum(_similar(l, n, a11).astype(np.int64) for n in _cross(p))
    out_hill = np.where((hill != a11) & (count >= 3), hill, a11)
    return np.where(mutated, out_mut, np.where(try_, out_hill, a11))


def _sunflower(l, x, z, w, h):
    v = l.p.area(x, z, w, h)
    return np.where((v == PLAINS) & (first_int(_cs(l, x, z, w, h), 57) == 0), SUNFLOWER_PLAINS, v)


def _shore(l, x, z, w, h):
    p, c = _neigh(l, x, z, w, h)
    ns = _cross(p)
    cat = l.cat
    oc = np.zeros_like(c, bool)
    jfto = np.ones_like(c, bool)
    mesa4 = np.ones_like(c, bool)
    plain_ocean = np.zeros_like(c, bool)
    for n in ns:
        o = _OCEANIC[_ids(n)] & (n >= 0)
        oc |= o
        jfto &= (cat[_ids(n)] == JUNGLE) | (n == FOREST) | (n == TAIGA) | o
        mesa4 &= _MESA[_ids(n)]
        plain_ocean |= n == OCEAN
    c_oc = _OCEANIC[_ids(c)]
    out = np.where(~np.isin(c, [OCEAN, DEEP_OCEAN, RIVER, SWAMP]) & oc, BEACH, c)
    out = np.where(np.isin(c, [BADLANDS, WOODED_BADLANDS_PLATEAU]), np.where(~oc & ~mesa4, DESERT, c), out)
    out = np.where(_SNOWY[_ids(c)], np.where(~c_oc & oc, SNOWY_BEACH, c), out)
    out = np.where(np.isin(c, [MOUNTAINS, WOODED_MOUNTAINS]), np.where(oc, STONE_SHORE, c), out)
    jungle = cat[_ids(c)] == JUNGLE
    out = np.where(jungle, np.where(jfto, np.where(oc, BEACH, c), JUNGLE_EDGE), out)
    return np.where(c == MUSHROOM, np.where(plain_ocean, MUSHROOM_SHORE, c), out)


def _river(l, x, z, w, h):
    p, _ = _neigh(l, x, z, w, h)
    r = np.where(p >= 2, 2 + (p & 1), p)            # reduceID
    c = r[1:-1, 1:-1]
    same = (c == r[1:-1, :-2]) & (c == r[:-2, 1:-1]) & (c == r[2:, 1:-1]) & (c == r[1:-1, 2:])
    return np.where(same, -1, RIVER)


def _river_mix(l, x, z, w, h):
    v = l.p.area(x, z, w, h)
    r = l.p2.area(x, z, w, h)
    riv = (r == RIVER) & (v != OCEAN) & ~_OCEANIC[_ids(v)]
    new = np.where(v == SNOWY_TUNDRA, FROZEN_RIVER, np.where((v == MUSHROOM) | (v == MUSHROOM_SHORE), MUSHROOM_SHORE,
                                                             RIVER))
    return np.where(riv, new, v)


# ------------------------------------------------------------------ oceans (1.13+)

class _Perlin:
    """One octave of the game's ImprovedNoise, seeded by the world seed (Java Random)."""

    def __init__(self, seed: int):
        from .betagen import JavaRandom

        r = JavaRandom(seed)
        self.a, self.b, self.c = r.next_double() * 256.0, r.next_double() * 256.0, r.next_double() * 256.0
        d = list(range(256))
        for i in range(256):
            j = r.next_int(256 - i) + i
            d[i], d[j] = d[j], d[i]
        self.d = np.array(d + d, np.int64)

    @staticmethod
    def _grad(h, x, y, z):
        g = np.array([[1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0], [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
                      [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1], [1, 1, 0], [0, -1, 1], [-1, 1, 0], [0, -1, -1]],
                     np.float64)[h & 15]
        return g[..., 0] * x + g[..., 1] * y + g[..., 2] * z

    def sample(self, x, y):
        """noise(x, y, 0): OceanTemperatureLayer passes (x / 8, z / 8, 0), the z coordinate in y's place."""
        d = self.d
        x = x + self.a
        y = y + self.b
        zz = self.c
        i1, i2, i3 = np.floor(x), np.floor(y), math.floor(zz)
        x, y, z = x - i1, y - i2, zz - i3
        h1, h2, h3 = i1.astype(np.int64) & 255, i2.astype(np.int64) & 255, int(i3) & 255
        fade = lambda t: t * t * t * (t * (t * 6.0 - 15.0) + 10.0)  # noqa: E731
        t1, t2, t3 = fade(x), fade(y), fade(z)
        a1 = d[h1] + h2
        a2 = d[a1] + h3
        a3 = d[a1 + 1] + h3
        b1 = d[h1 + 1] + h2
        b2 = d[b1] + h3
        b3 = d[b1 + 1] + h3
        g = self._grad
        l1 = g(d[a2], x, y, z) + t1 * (g(d[b2], x - 1, y, z) - g(d[a2], x, y, z))
        l2 = g(d[a3], x, y - 1, z) + t1 * (g(d[b3], x - 1, y - 1, z) - g(d[a3], x, y - 1, z))
        l3 = g(d[a2 + 1], x, y, z - 1) + t1 * (g(d[b2 + 1], x - 1, y, z - 1) - g(d[a2 + 1], x, y, z - 1))
        l4 = g(d[a3 + 1], x, y - 1, z - 1) + t1 * (g(d[b3 + 1], x - 1, y - 1, z - 1) - g(d[a3 + 1], x, y - 1, z - 1))
        l1 = l1 + t2 * (l2 - l1)
        l3 = l3 + t2 * (l4 - l3)
        return l1 + t3 * (l3 - l1)


def _ocean_temp(l, x, z, w, h):
    xx, zz = _grid(x, z, w, h)
    t = l.noise.sample(xx / 8.0, zz / 8.0)
    return np.where(t > 0.4, WARM_OCEAN, np.where(t > 0.2, LUKEWARM_OCEAN, np.where(
        t < -0.4, FROZEN_OCEAN, np.where(t < -0.2, COLD_OCEAN, OCEAN))))


def _ocean_mix(l, x, z, w, h):
    ocean = l.p2.area(x, z, w, h)
    land = l.p.area(x - 8, z - 8, w + 17, h + 17)
    c = land[8:8 + h, 8:8 + w]
    near_land = np.zeros_like(c, bool)
    for di in range(-8, 9, 4):
        for dj in range(-8, 9, 4):
            near_land |= ~_OCEANIC[_ids(land[8 + dj:8 + dj + h, 8 + di:8 + di + w])]
    rep = np.where(ocean == WARM_OCEAN, LUKEWARM_OCEAN, np.where(ocean == FROZEN_OCEAN, COLD_OCEAN, 0))
    deep = {LUKEWARM_OCEAN: DEEP_LUKEWARM_OCEAN, OCEAN: DEEP_OCEAN, COLD_OCEAN: DEEP_COLD_OCEAN,
            FROZEN_OCEAN: DEEP_FROZEN_OCEAN}
    o = ocean.copy()
    for a, b in deep.items():
        o = np.where((c == DEEP_OCEAN) & (ocean == a), b, o)
    o = np.where((rep != 0) & near_land, rep, o)
    return np.where(_OCEANIC[_ids(c)], o, c)


# ------------------------------------------------------------------ voronoi of 1.15+

def voronoi_sha(seed: int) -> int:
    """The first 8 bytes of SHA-256 of the seed (little endian), as the game's BiomeManager."""
    d = hashlib.sha256(struct.pack("<q", seed if seed < 2 ** 63 else seed - 2 ** 64)).digest()
    return struct.unpack("<Q", d[:8])[0]


def fuzzy_zoom(sha: int, p4: np.ndarray, px: int, pz: int, x: int, z: int, w: int, h: int, y: int = 0) -> np.ndarray:
    """FuzzyOffsetBiomeZoomer of 1.15+: the 1:1 biomes [h, w] from the 1:4 grid ``p4`` (whose [0, 0] is
    the cell (px, pz)), at block height ``y`` (a number or [h, w]; the offsets of its 3D cells are random)."""
    zz, xx = np.mgrid[z - 2:z - 2 + h, x - 2:x - 2 + w]
    j = np.broadcast_to(np.asarray(y, np.int64), xx.shape) - 2           # (a height per column too)
    l, n, m = xx >> 2, zz >> 2, j >> 2
    fx, fz, fy = (xx & 3) / 4.0, (zz & 3) / 4.0, (j & 3) / 4.0
    seed = _u(sha)

    def fiddle(s):
        return ((((s.view(np.int64) >> 24) & 1023).astype(np.float64) / 1024.0) - 0.5) * 0.9

    best = best_o = None
    for o in range(8):
        cx = l + ((o >> 2) & 1)
        cy = m + ((o >> 1) & 1)
        cz = n + (o & 1)
        gx = fx - ((o >> 2) & 1)
        gy = fy - ((o >> 1) & 1)
        gz = fz - (o & 1)
        with np.errstate(over="ignore"):
            s = np.full(xx.shape, seed, np.uint64)
            for v in (cx, cy, cz) * 2:
                s = step(s, v.astype(np.int64).view(np.uint64))
            d = fiddle(s)
            s = step(s, seed)
            e = fiddle(s)
            s = step(s, seed)
            f = fiddle(s)
        dist = (gz + f) ** 2 + (gy + e) ** 2 + (gx + d) ** 2
        if best is None:
            best, best_o = dist, np.zeros(xx.shape, np.int64)
        else:
            take = best > dist
            best = np.where(take, dist, best)
            best_o = np.where(take, o, best_o)
    cx = l + ((best_o >> 2) & 1) - px
    cz = n + (best_o & 1) - pz
    return p4[cz, cx]


def _voronoi_sha(l, x, z, w, h):
    px, pz = (x - 2) >> 2, (z - 2) >> 2
    pw, ph = ((x - 2 + w) >> 2) - px + 2, ((z - 2 + h) >> 2) - pz + 2
    return fuzzy_zoom(l.sha, l.p.area(px, pz, pw, ph), px, pz, x, z, w, h, getattr(l, "y", 0))




# ------------------------------------------------------------------ stack

VERSIONS = {f"1.{i}": i for i in range(7, 18)}


class Stack17:
    """The GenLayer stack of Java 1.7 - 1.17 (normal or "Large Biomes")."""

    def __init__(self, version: str, seed: int, large_biomes: bool = False):
        mc = VERSIONS[version]
        self.mc = mc
        cat, mut = _tables(mc)
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
        p = L(_add_mushroom, 5, p)
        deep = L(_deep_ocean, 4, p)
        b = L(_biome, 200, deep)
        if mc >= 14:
            b = L(_bamboo, 1001, b)
        b = L(_zoom, 1000, b)
        b = L(_zoom, 1001, b)
        b = L(_biome_edge, 1000, b)
        river_init = L(_noise, 100, deep)
        salts = (1000, 1001) if mc >= 13 else (0, 0)       # before 1.13 the hills branch is not seeded
        hz = L(_zoom, salts[1], L(_zoom, salts[0], river_init))
        b = L(_hills, 1000, b, hz)
        b = L(_sunflower, 1001, b)
        b = L(_zoom, 1000, b)
        b = L(_add_island, 3, b)
        b = L(_zoom, 1001, b)
        b = L(_shore, 1000, b)
        b = L(_zoom, 1002, b)
        b = L(_zoom, 1003, b)
        if large_biomes:
            b = L(_zoom, 1005, L(_zoom, 1004, b))
        b = L(_smooth, 1000, b)
        r = river_init
        for salt in (1000, 1001, 1000, 1001, 1002, 1003) + ((1004, 1005) if large_biomes and mc == 7 else ()):
            r = L(_zoom, salt, r)
        r = L(_smooth, 1000, L(_river, 1, r))
        mix = L(_river_mix, 100, b, r)
        if mc >= 13:
            o = L(_ocean_temp, 2)
            for salt in range(2001, 2007):
                o = L(_zoom, salt, o)
            mix = L(_ocean_mix, 100, mix, o)
        self.mix = mix
        self.voronoi = L(_voronoi_sha, 0, mix) if mc >= 15 else L(_voronoi, 10, mix)
        self.voronoi.seed(seed)
        todo = [self.voronoi]
        while todo:
            q = todo.pop()
            if q is None:
                continue
            q.mc, q.cat, q.mut = mc, cat, mut
            if q.fn is _ocean_temp:
                q.noise = _Perlin(seed)
            todo += [q.p, q.p2]
        self.voronoi.sha = voronoi_sha(seed) if mc >= 15 else 0
        self._c4, self._c1 = AreaCache(16), AreaCache(64)

    def biomes4(self, x: int, z: int, w: int, h: int) -> np.ndarray:
        """[h, w] biome ids of the 1:4 grid (the terrain's)."""
        return self._c4.area(self.mix, x, z, w, h)

    def biomes(self, x: int, z: int, w: int, h: int, y: int = 0) -> np.ndarray:
        """[h, w] biome ids of the blocks (1.15+: at block height ``y``, their zoom is 3D)."""
        self.voronoi.y = y
        if not isinstance(y, (int, np.integer)):
            return self.voronoi.area(x, z, w, h)
        return self._c1.area(self.voronoi, x, z, w, h, (int(y),))
