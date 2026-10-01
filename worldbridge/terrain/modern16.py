"""Terrain generator of Minecraft Java 1.16 (NoiseBasedChunkGenerator with the overworld settings),
for the ring of terrain WorldBridge writes around a world converted to 1.14 - 1.17.

1.14.4 and 1.15.2 (read from their jars) compute the same density with other formulas (constants
684.412F, depth (d * 4 - 1) / 8, an unnormalised random density offset divided by 8000) and the
same surface builders; 1.14 zooms the biomes in 2D.  1.17.1 adds a bottom slide (15, 3, 0); its
aquifers, noise caves and deepslate are off in the overworld.

Code read from the 1.16.5 jar:

* the density: 5 x 33 x 5 noise columns per chunk (a column every 4 blocks, a sample every 8),
  each the blend of the "lower" and "upper" 16-octave noises by the 8-octave main noise, plus the
  biomes' depth and scale weighted over 5 x 5 columns, a random density offset and the slides at
  the top and bottom; interpolated block by block, then d / 2 - d^3 / 24 (the game's "beard"
  around villages and other structures is left out);
* the surface: every biome's configured surface builder (default with its top / under / underwater
  blocks, mountain, gravelly mountain, shattered savanna, giant tree taiga, swamp puddles, the three
  badlands with their terracotta bands and pillars, frozen ocean icebergs), then the bedrock floor;
* caves, ravines, lakes, ores and trees are the game's own: the ring's chunks are written with the
  "surface" status, the game carves and decorates them itself.

Biomes: layers17 (the 1.16 stack, the 3D fuzzy zoom of 1.15+).
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from .betagen import JavaRandom, Perlin, Simplex, _GRAD2, _F2, _G2, _s64
from .layers17 import Stack17, fuzzy_zoom, voronoi_sha
from .lift import lifted_rock

_F = np.float32
SEA_LEVEL = 63
HEIGHT = 256
STONE, GRASS, DIRT, BEDROCK, WATER, SAND, GRAVEL, ICE, SNOW_BLOCK, MYCELIUM = 1, 2, 3, 7, 9, 12, 13, 79, 80, 110
SANDSTONE, RED_SANDSTONE, PACKED_ICE, TERRACOTTA, STAINED = 24, 179, 174, 172, 159
WHITE, ORANGE, YELLOW, LIGHT_GRAY, BROWN, RED = 0, 1, 4, 8, 12, 14

# surface configs: (top, under, underwater) as (id, data)
_GRASS = ((GRASS, 0), (DIRT, 0), (GRAVEL, 0))
_DESERT = ((SAND, 0), (SAND, 0), (GRAVEL, 0))
_STONE = ((STONE, 0), (STONE, 0), (GRAVEL, 0))
_OCEAN_SAND = ((GRASS, 0), (DIRT, 0), (SAND, 0))
_FULL_SAND = ((SAND, 0), (SAND, 0), (SAND, 0))
_MYCELIUM = ((MYCELIUM, 0), (DIRT, 0), (GRAVEL, 0))
_ICE_SPIKES = ((SNOW_BLOCK, 0), (DIRT, 0), (GRAVEL, 0))
_BADLANDS = ((SAND, 1), (STAINED, WHITE), (GRAVEL, 0))
_GRAVEL = ((GRAVEL, 0), (GRAVEL, 0), (GRAVEL, 0))
_COARSE = ((DIRT, 1), (DIRT, 0), (GRAVEL, 0))
_PODZOL = ((DIRT, 2), (DIRT, 0), (GRAVEL, 0))

# biome id -> (depth, scale, temperature, frozen temperature modifier, surface builder, config)
_B = {}
for _ids, _v in (
        ((0,), (-1.0, 0.1, 0.5, False, "default", _GRASS)),
        ((1, 129), (0.125, 0.05, 0.8, False, "default", _GRASS)),
        ((2,), (0.125, 0.05, 2.0, False, "default", _DESERT)),
        ((3,), (1.0, 0.5, 0.2, False, "mountain", _GRASS)),
        ((4,), (0.1, 0.2, 0.7, False, "default", _GRASS)),
        ((5,), (0.2, 0.2, 0.25, False, "default", _GRASS)),
        ((6,), (-0.2, 0.1, 0.8, False, "swamp", _GRASS)),
        ((7,), (-0.5, 0.0, 0.5, False, "default", _GRASS)),
        ((10,), (-1.0, 0.1, 0.0, True, "frozen_ocean", _GRASS)),
        ((11,), (-0.5, 0.0, 0.0, False, "default", _GRASS)),
        ((12,), (0.125, 0.05, 0.0, False, "default", _GRASS)),
        ((13,), (0.45, 0.3, 0.0, False, "default", _GRASS)),
        ((14,), (0.2, 0.3, 0.9, False, "default", _MYCELIUM)),
        ((15,), (0.0, 0.025, 0.9, False, "default", _MYCELIUM)),
        ((16,), (0.0, 0.025, 0.8, False, "default", _DESERT)),
        ((17,), (0.45, 0.3, 2.0, False, "default", _DESERT)),
        ((18,), (0.45, 0.3, 0.7, False, "default", _GRASS)),
        ((19,), (0.45, 0.3, 0.25, False, "default", _GRASS)),
        ((20,), (0.8, 0.3, 0.2, False, "default", _GRASS)),
        ((21, 23, 168), (0.1, 0.2, 0.95, False, "default", _GRASS)),
        ((22, 169), (0.45, 0.3, 0.95, False, "default", _GRASS)),
        ((24,), (-1.8, 0.1, 0.5, False, "default", _GRASS)),
        ((25,), (0.1, 0.8, 0.2, False, "default", _STONE)),
        ((26,), (0.0, 0.025, 0.05, False, "default", _DESERT)),
        ((27,), (0.1, 0.2, 0.6, False, "default", _GRASS)),
        ((28,), (0.45, 0.3, 0.6, False, "default", _GRASS)),
        ((29,), (0.1, 0.2, 0.7, False, "default", _GRASS)),
        ((30,), (0.2, 0.2, -0.5, False, "default", _GRASS)),
        ((31,), (0.45, 0.3, -0.5, False, "default", _GRASS)),
        ((32,), (0.2, 0.2, 0.3, False, "giant_tree_taiga", _GRASS)),
        ((33,), (0.45, 0.3, 0.3, False, "giant_tree_taiga", _GRASS)),
        ((34,), (1.0, 0.5, 0.2, False, "default", _GRASS)),
        ((35,), (0.125, 0.05, 1.2, False, "default", _GRASS)),
        ((36,), (1.5, 0.025, 1.0, False, "default", _GRASS)),
        ((37,), (0.1, 0.2, 2.0, False, "badlands", _BADLANDS)),
        ((38,), (1.5, 0.025, 2.0, False, "wooded_badlands", _BADLANDS)),
        ((39,), (1.5, 0.025, 2.0, False, "badlands", _BADLANDS)),
        ((44,), (-1.0, 0.1, 0.5, False, "default", _FULL_SAND)),
        ((45,), (-1.0, 0.1, 0.5, False, "default", _OCEAN_SAND)),
        ((46,), (-1.0, 0.1, 0.5, False, "default", _GRASS)),
        ((47,), (-1.8, 0.1, 0.5, False, "default", _FULL_SAND)),
        ((48,), (-1.8, 0.1, 0.5, False, "default", _OCEAN_SAND)),
        ((49,), (-1.8, 0.1, 0.5, False, "default", _GRASS)),
        ((50,), (-1.8, 0.1, 0.5, True, "frozen_ocean", _GRASS)),
        ((130,), (0.225, 0.25, 2.0, False, "default", _DESERT)),
        ((131, 162), (1.0, 0.5, 0.2, False, "gravelly_mountain", _GRASS)),
        ((132,), (0.1, 0.4, 0.7, False, "default", _GRASS)),
        ((133,), (0.3, 0.4, 0.25, False, "default", _GRASS)),
        ((134,), (-0.1, 0.3, 0.8, False, "swamp", _GRASS)),
        ((140,), (0.425, 0.45000002, 0.0, False, "default", _ICE_SPIKES)),
        ((149, 151), (0.2, 0.4, 0.95, False, "default", _GRASS)),
        ((155,), (0.2, 0.4, 0.6, False, "default", _GRASS)),
        ((156,), (0.55, 0.5, 0.6, False, "default", _GRASS)),
        ((157,), (0.2, 0.4, 0.7, False, "default", _GRASS)),
        ((158,), (0.3, 0.4, -0.5, False, "default", _GRASS)),
        ((160, 161), (0.2, 0.2, 0.25, False, "giant_tree_taiga", _GRASS)),
        ((163,), (0.3625, 1.225, 1.1, False, "shattered_savanna", _GRASS)),
        ((164,), (1.05, 1.2125001, 1.0, False, "shattered_savanna", _GRASS)),
        ((165,), (0.1, 0.2, 2.0, False, "eroded_badlands", _BADLANDS)),
        ((166,), (0.45, 0.3, 2.0, False, "wooded_badlands", _BADLANDS)),
        ((167,), (0.45, 0.3, 2.0, False, "badlands", _BADLANDS))):
    for _i in _ids:
        _B[_i] = _v
_DEFAULT_B = _B[1]

_DEPTH = np.zeros(256, np.float32)
_SCALE = np.zeros(256, np.float32)
for _i, _v in _B.items():
    _DEPTH[_i], _SCALE[_i] = _F(_v[0]), _F(_v[1])
for _i in range(256):
    if _i not in _B:
        _DEPTH[_i], _SCALE[_i] = _F(_DEFAULT_B[0]), _F(_DEFAULT_B[1])

_GRAD3 = np.array([[1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0], [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
                   [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1], [1, 1, 0], [0, -1, 1], [-1, 1, 0], [0, -1, -1]],
                  np.float64)


def _lfloor(v):
    return np.floor(v)


def _wrap(v):
    """PerlinNoise.wrap: keeps the coordinates within 2^25 of zero."""
    return v - np.floor(v / 33554432.0 + 0.5) * 33554432.0


def _improved(n: Perlin, x, y, z, y_scale=0.0, y_max=0.0):
    """ImprovedNoise.noise(x, y, z, yScale, yMax) of 1.14+ (vectorised): the gradients at the corners
    of the unit cube, faded; ``y_scale`` / ``y_max`` snap the y of the gradients (not of the fade)."""
    p = n.p
    x = np.asarray(x, np.float64) + n.xo
    y = np.asarray(y, np.float64) + n.yo
    z = np.asarray(z, np.float64) + n.zo
    xi, yi, zi = np.floor(x), np.floor(y), np.floor(z)
    dx, dy, dz = x - xi, y - yi, z - zi
    if y_scale != 0.0:
        fudge = np.floor(np.minimum(y_max, dy) / y_scale) * y_scale
    else:
        fudge = 0.0
    X, Y, Z = xi.astype(np.int64) & 255, yi.astype(np.int64) & 255, zi.astype(np.int64) & 255

    def h(i):
        return p[i & 255]

    i = h(X) + Y
    j = h(i) + Z
    k = h(i + 1) + Z
    l = h(X + 1) + Y
    m = h(l) + Z
    nn = h(l + 1) + Z
    gy = dy - fudge

    def g(hash_, a, b, c):
        v = _GRAD3[hash_ & 15]
        return v[..., 0] * a + v[..., 1] * b + v[..., 2] * c

    d1 = g(h(j), dx, gy, dz)
    d2 = g(h(m), dx - 1, gy, dz)
    d3 = g(h(k), dx, gy - 1, dz)
    d4 = g(h(nn), dx - 1, gy - 1, dz)
    d5 = g(h(j + 1), dx, gy, dz - 1)
    d6 = g(h(m + 1), dx - 1, gy, dz - 1)
    d7 = g(h(k + 1), dx, gy - 1, dz - 1)
    d8 = g(h(nn + 1), dx - 1, gy - 1, dz - 1)
    fx = dx * dx * dx * (dx * (dx * 6.0 - 15.0) + 10.0)
    fy = dy * dy * dy * (dy * (dy * 6.0 - 15.0) + 10.0)
    fz = dz * dz * dz * (dz * (dz * 6.0 - 15.0) + 10.0)

    def lerp(t, a, b):
        return a + t * (b - a)

    return lerp(fz, lerp(fy, lerp(fx, d1, d2), lerp(fx, d3, d4)), lerp(fy, lerp(fx, d5, d6), lerp(fx, d7, d8)))


def _octaves(rnd: JavaRandom, n: int):
    """PerlinNoise of octaves -(n-1) .. 0: the ImprovedNoises in the order they are created (the
    finest first)."""
    return [Perlin(rnd) for _ in range(n)]


def _simplex2(s: Simplex, x, y):
    """SimplexNoise.getValue(x, y) (vectorised, without the noise's offsets)."""
    x = np.asarray(x, np.float64)
    y = np.asarray(y, np.float64)
    t = (x + y) * _F2
    i = np.floor(x + t).astype(np.int64)
    j = np.floor(y + t).astype(np.int64)
    t2 = (i + j) * _G2
    x0 = x - (i - t2)
    y0 = y - (j - t2)
    first = x0 > y0
    i1 = np.where(first, 1, 0)
    j1 = np.where(first, 0, 1)
    x1 = x0 - i1 + _G2
    y1 = y0 - j1 + _G2
    x2 = x0 - 1.0 + 2.0 * _G2
    y2 = y0 - 1.0 + 2.0 * _G2
    p = s.p
    ii, jj = i & 255, j & 255
    total = 0.0
    for g, a, b in ((p[ii + p[jj]] % 12, x0, y0), (p[ii + i1 + p[jj + j1]] % 12, x1, y1),
                    (p[ii + 1 + p[jj + 1]] % 12, x2, y2)):
        c = 0.5 - a * a - b * b
        total = total + np.where(c < 0.0, 0.0, c * c * c * c * (_GRAD2[g, 0] * a + _GRAD2[g, 1] * b))
    return 70.0 * total


class _SimplexOctaves:
    """PerlinSimplexNoise with the octaves ``octaves`` (a list of values <= 0)."""

    def __init__(self, rnd: JavaRandom, octaves):
        lo = -min(octaves)
        n = lo + 1
        self.levels = [None] * n
        first = Simplex(rnd)
        if 0 in octaves:
            self.levels[0] = first
        for i in range(1, n):
            if -i in octaves:
                self.levels[i] = Simplex(rnd)
            else:
                for _ in range(262):
                    rnd.next(32)
        self.amp0 = 1.0 / (2.0 ** n - 1.0)

    def value(self, x, y, offsets: bool):
        total = 0.0
        f, a = 1.0, self.amp0
        for s in self.levels:
            if s is not None:
                total = total + _simplex2(s, np.asarray(x) * f + (s.xo if offsets else 0.0),
                                          np.asarray(y) * f + (s.yo if offsets else 0.0)) * a
            f /= 2.0
            a *= 2.0
        return total


_TEMPERATURE = _FROZEN = _INFO = None


def _biome_noises():
    global _TEMPERATURE, _FROZEN, _INFO
    if _INFO is None:
        _TEMPERATURE = _SimplexOctaves(JavaRandom(1234), [0])
        _FROZEN = _SimplexOctaves(JavaRandom(3456), [-2, -1, 0])
        _INFO = _SimplexOctaves(JavaRandom(2345), [0])
    return _TEMPERATURE, _FROZEN, _INFO


def temperature(bid: int, x: int, y: int, z: int) -> float:
    """Biome.getTemperature(pos) (the frozen oceans' patches of warmer water included)."""
    t, frozen = _B.get(bid, _DEFAULT_B)[2], _B.get(bid, _DEFAULT_B)[3]
    tn, fz, info = _biome_noises()
    t = _F(t)
    if frozen:
        d = float(fz.value(x * 0.05, z * 0.05, False)) * 7.0 + float(info.value(x * 0.2, z * 0.2, False))
        if d < 0.3 and float(info.value(x * 0.09, z * 0.09, False)) < 0.8:
            t = _F(0.2)
    if y > 64:
        v = _F(float(tn.value(float(_F(x) / _F(8.0)), float(_F(z) / _F(8.0)), False)) * 4.0)
        t = _F(t - _F(_F(v + _F(y) - _F(64.0)) * _F(0.05) / _F(30.0)))
    return float(t)


class _Badlands:
    """BadlandsSurfaceBuilder's clay bands and the eroded badlands' pillars (seeded by the world)."""

    def __init__(self, seed: int):
        r = JavaRandom(seed)
        self.offset = _SimplexOctaves(r, [0])
        bands = [(TERRACOTTA, 0)] * 64
        i = 0
        while i < 64:                                  # for (i = 0; i < 64; i++) { i += nextInt(5) + 1; ...
            i += r.next_int(5) + 1
            if i < 64:
                bands[i] = (STAINED, ORANGE)
            i += 1
        for colour, extra in ((YELLOW, 1), (BROWN, 2), (RED, 1)):
            for _ in range(r.next_int(4) + 2):
                n = r.next_int(3) + extra
                start = r.next_int(64)
                for k in range(n):
                    if start + k >= 64:
                        break
                    bands[start + k] = (STAINED, colour)
        cursor = 0
        for _ in range(r.next_int(3) + 3):
            cursor += r.next_int(16) + 4
            if cursor >= 64:
                break
            bands[cursor] = (STAINED, WHITE)
            if cursor > 1 and r.next(1):
                bands[cursor - 1] = (STAINED, LIGHT_GRAY)
            if cursor < 63 and r.next(1):
                bands[cursor + 1] = (STAINED, LIGHT_GRAY)
        self.bands = bands
        r = JavaRandom(seed)
        self.pillar = _SimplexOctaves(r, [-3, -2, -1, 0])
        self.pillar_roof = _SimplexOctaves(r, [0])

    def band(self, x: int, y: int, z: int):
        v = float(self.offset.value(x / 512.0, z / 512.0, False)) * 2.0
        return self.bands[(y + int(math.floor(v + 0.5)) + 64) % 64]


class _FrozenOcean:
    def __init__(self, seed: int):
        r = JavaRandom(seed)
        self.berg = _SimplexOctaves(r, [-3, -2, -1, 0])
        self.roof = _SimplexOctaves(r, [0])


class Modern16Generator:
    """``chunk(cx, cz, lift=None)`` -> (blocks [x, z, y], biomes [x, z], data [x, z, y])."""

    def __init__(self, seed: int, version: str = "1.16", large_biomes: bool = False, amplified: bool = False):
        self.seed = _s64(seed)
        self.version = version
        self.minor = int(version.split(".")[1])
        self.amplified = amplified
        self.stack = Stack17(version, self.seed, large_biomes)
        self.sha = voronoi_sha(self.seed)
        r = JavaRandom(self.seed)
        self.n_min = _octaves(r, 16)
        self.n_max = _octaves(r, 16)
        self.n_main = _octaves(r, 8)
        self.n_surface = _SimplexOctaves(r, [-3, -2, -1, 0])
        for _ in range(2620):
            r.next(32)
        self.n_depth = _octaves(r, 16)              # the random density offset (coarsest last)
        pf = np.zeros(25, np.float32)
        for i in range(-2, 3):
            for j in range(-2, 3):
                pf[i + 2 + (j + 2) * 5] = _F(10.0) / np.sqrt(_F(i * i + j * j) + _F(0.2), dtype=np.float32)
        self.pf = pf
        s = 0.9999999814507745
        self.xz_scale = 684.412 * s
        self.y_scale = 684.412 * s
        self.xz_main = self.xz_scale / 80.0
        self.y_main = self.y_scale / 160.0
        self._badlands = None
        self._frozen = None

    # ---------------------------------------------------------- density
    def _noise(self, X, Y, Z):
        """The blended noise at noise coordinates (columns x, z; samples y)."""
        lo = hi = main = 0.0
        o = 1.0
        for i in range(16):
            fx = _wrap(X * self.xz_scale * o)
            fy = _wrap(Y * self.y_scale * o)
            fz = _wrap(Z * self.xz_scale * o)
            ys = self.y_scale * o
            lo = lo + _improved(self.n_min[i], fx, fy, fz, ys, Y * ys) / o
            hi = hi + _improved(self.n_max[i], fx, fy, fz, ys, Y * ys) / o
            if i < 8:
                ym = self.y_main * o
                main = main + _improved(self.n_main[i], _wrap(X * self.xz_main * o), _wrap(Y * self.y_main * o),
                                        _wrap(Z * self.xz_main * o), ym, Y * ym) / o
            o /= 2.0
        t = (main / 10.0 + 1.0) / 2.0
        a, b = lo / 512.0, hi / 512.0
        return np.where(t < 0.0, a, np.where(t > 1.0, b, a + t * (b - a)))

    def _density_offset(self, X, Z):
        """The random density offset of every column."""
        n = len(self.n_depth)
        total = 0.0
        f = 2.0 ** (-(n - 1))
        amp = 2.0 ** (n - 1) / (2.0 ** n - 1.0)
        for p in reversed(self.n_depth):                 # the coarsest first
            total = total + _improved(p, _wrap(X * 200.0 * f), -p.yo, _wrap(Z * 200.0 * f), 1.0 * f, 0.0) * amp
            f *= 2.0
            amp /= 2.0
        d = np.where(total < 0.0, -total * 0.3, total)
        d = d * 24.575625 - 2.0
        return np.where(d < 0.0, d * 0.009486607142857142, np.minimum(d, 1.0) * 0.006640625)

    def _columns(self, cx: int, cz: int) -> np.ndarray:
        """[5, 5, 33] density samples of the chunk's noise columns."""
        X0, Z0 = cx * 4, cz * 4
        b4 = self.stack.biomes4(X0 - 2, Z0 - 2, 9, 9)            # [z, x]
        depth = np.empty((5, 5), np.float64)
        factor = np.empty((5, 5), np.float64)
        for i in range(5):
            for j in range(5):
                center = _DEPTH[int(b4[j + 2, i + 2])]
                sd = ss = sw = _F(0)
                for di in range(-2, 3):
                    for dj in range(-2, 3):
                        bid = int(b4[j + 2 + dj, i + 2 + di])
                        d, s = _DEPTH[bid], _SCALE[bid]
                        if self.amplified and d > 0:
                            ad, as_ = _F(_F(1.0) + _F(d * _F(2.0))), _F(_F(1.0) + _F(s * _F(4.0)))
                        else:
                            ad, as_ = d, s
                        w = _F(_F(_F(0.5) if d > center else _F(1.0)) * self.pf[di + 2 + (dj + 2) * 5])
                        w = _F(w / _F(ad + _F(2.0)))
                        ss = _F(ss + _F(as_ * w))
                        sd = _F(sd + _F(ad * w))
                        sw = _F(sw + w)
                dd = _F(sd / sw)
                sc = _F(ss / sw)
                depth[i, j] = float(_F(_F(dd * _F(0.5)) - _F(0.125))) * 0.265625
                factor[i, j] = 96.0 / float(_F(_F(sc * _F(0.9)) + _F(0.1)))
        X = (X0 + np.arange(5))[:, None, None].astype(np.float64)
        Z = (Z0 + np.arange(5))[None, :, None].astype(np.float64)
        Y = np.arange(33)[None, None, :].astype(np.float64)
        X, Z, Y = np.broadcast_arrays(X, Z, Y)
        noise = self._noise(X, Y, Z)
        rdo = self._density_offset(X[:, :, 0], Z[:, :, 0])[:, :, None]
        yf = 1.0 - Y * 2.0 / 32.0 + rdo
        dens = yf * 1.0 + -0.46875
        v = (dens + depth[:, :, None]) * factor[:, :, None]
        noise = noise + np.where(v > 0.0, v * 4.0, v)
        t = ((32.0 - Y) - 0.0) / 3.0                          # top slide: -10 over 3 samples
        noise = np.where(t < 0.0, -10.0, np.where(t > 1.0, noise, -10.0 + t * (noise + 10.0)))
        if self.minor >= 17:                                  # 1.17: bottom slide, 15 over 3 samples
            t = (Y - 0.0) / 3.0
            noise = np.where(t < 0.0, 15.0, np.where(t > 1.0, noise, 15.0 + t * (noise - 15.0)))
        return noise

    @staticmethod
    def _density_blocks(q: np.ndarray) -> np.ndarray:
        """[16, 16, 256] density: interpolated along y, then x, then z (as the game), then shaped."""
        yf = (np.arange(8) / 8.0)[None, None, None, :]
        lo, hi = q[:, :, :32, None], q[:, :, 1:, None]
        qy = (lo + yf * (hi - lo)).reshape(5, 5, 256)             # [xcol, zcol, y]
        xf = (np.arange(4) / 4.0)[None, :, None, None]
        qx = qy[:4, None] + xf * (qy[1:, None] - qy[:4, None])     # [4, 4(xo), 5, 256]
        qx = qx.reshape(16, 5, 256)
        zf = (np.arange(4) / 4.0)[None, None, :, None]
        qz = qx[:, :4, None] + zf * (qx[:, 1:, None] - qx[:, :4, None])
        d = qz.reshape(16, 16, 256)
        d = np.clip(d / 200.0, -1.0, 1.0)
        return d / 2.0 - d * d * d / 24.0

    @staticmethod
    def _rock(d: np.ndarray) -> np.ndarray:
        y = np.arange(HEIGHT)[None, None, :]
        return np.where(d > 0.0, STONE, np.where(y < SEA_LEVEL, WATER, 0)).astype(np.uint8)

    # ---------------------------------------------------------- surface
    def _column_biomes(self, cx: int, cz: int, blocks: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """The biome of every column at its surface (the 3D zoom), and that height [x, z]."""
        solid = blocks != 0
        top = np.where(solid.any(2), HEIGHT - 1 - np.argmax(solid[:, :, ::-1], axis=2), -1) + 1
        if self.minor <= 14:                                   # 1.14: the 2D zoom
            return self.stack.biomes(cx * 16, cz * 16, 16, 16).T, top
        px, pz = (cx * 16 - 2) >> 2, (cz * 16 - 2) >> 2
        p4 = self.stack.biomes4(px, pz, 6, 6)
        b = fuzzy_zoom(self.sha, p4, px, pz, cx * 16, cz * 16, 16, 16, top.T)   # [z, x]
        return b.T, top

    def _surface(self, cx: int, cz: int, blocks: np.ndarray, data: np.ndarray):
        biomes, start = self._column_biomes(cx, cz, blocks)
        noise = self.n_surface.value((cx * 16 + np.arange(16))[:, None] * 0.0625,
                                     (cz * 16 + np.arange(16))[None, :] * 0.0625, True) * 0.55 * 15.0
        rnd = JavaRandom(_s64(cx * 341873128712 + cz * 132897987541))
        for lx in range(16):
            for lz in range(16):
                bid = int(biomes[lx, lz])
                x, z = cx * 16 + lx, cz * 16 + lz
                col = blocks[lx, lz].tolist()
                dcol = [0] * HEIGHT
                self._apply(bid, col, dcol, x, z, int(start[lx, lz]), float(noise[lx, lz]), rnd)
                blocks[lx, lz] = col
                data[lx, lz] = dcol
        for lz in range(16):                                   # the bedrock floor (x fastest)
            for lx in range(16):
                for y in range(4, -1, -1):
                    if y <= rnd.next_int(5):
                        blocks[lx, lz, y] = BEDROCK
                        data[lx, lz, y] = 0
        return biomes

    def _apply(self, bid, col, dcol, x, z, start, noise, rnd):
        kind, cfg = _B.get(bid, _DEFAULT_B)[4], _B.get(bid, _DEFAULT_B)[5]
        if kind == "mountain":
            cfg = _STONE if noise > 1.0 else _GRASS
        elif kind == "shattered_savanna":
            cfg = _STONE if noise > 1.75 else _COARSE if noise > -0.5 else _GRASS
        elif kind == "gravelly_mountain":
            cfg = _GRAVEL if (noise < -1.0 or noise > 2.0) else _STONE if noise > 1.0 else _GRASS
        elif kind == "giant_tree_taiga":
            cfg = _COARSE if noise > 1.75 else _PODZOL if noise > -0.95 else _GRASS
        elif kind == "swamp":
            _t, _f, info = _biome_noises()
            if float(info.value(x * 0.25, z * 0.25, False)) > 0.0:
                for y in range(start, -1, -1):
                    if col[y] != 0:
                        if y == 62 and col[y] != WATER:
                            col[y] = WATER
                        break
        elif kind in ("badlands", "wooded_badlands", "eroded_badlands"):
            return self._badlands_column(kind, bid, col, dcol, x, z, start, noise, rnd)
        elif kind == "frozen_ocean":
            return self._frozen_column(bid, col, dcol, x, z, start, noise, rnd)
        self._default(bid, col, dcol, x, z, start, noise, rnd, cfg)

    def _default(self, bid, col, dcol, x, z, start, noise, rnd, cfg):
        top_c, under_c, water_c = cfg
        top, under = top_c, under_c
        run = -1
        k = int(noise / 3.0 + 3.0 + rnd.next_double() * 0.25)
        for y in range(start, -1, -1):
            cur = col[y]
            if cur == 0:
                run = -1
            elif cur == STONE:
                if run == -1:
                    if k <= 0:
                        top, under = (0, 0), (STONE, 0)
                    elif SEA_LEVEL - 4 <= y <= SEA_LEVEL + 1:
                        top, under = top_c, under_c
                    if y < SEA_LEVEL and top[0] == 0:
                        top = (ICE, 0) if temperature(bid, x, y, z) < 0.15 else (WATER, 0)
                    run = k
                    if y >= SEA_LEVEL - 1:
                        col[y], dcol[y] = top
                    elif y < SEA_LEVEL - 7 - k:
                        top, under = (0, 0), (STONE, 0)
                        col[y], dcol[y] = water_c
                    else:
                        col[y], dcol[y] = under
                elif run > 0:
                    run -= 1
                    col[y], dcol[y] = under
                    if run == 0 and under == (SAND, 0) and k > 1:
                        run = rnd.next_int(4) + max(0, y - 63)
                        under = (SANDSTONE, 0)

    def _badlands_column(self, kind, bid, col, dcol, x, z, start, noise, rnd):
        """BadlandsSurfaceBuilder and its wooded / eroded variants (as in the 1.16.5 code)."""
        if self._badlands is None:
            self._badlands = _Badlands(self.seed)
        bl = self._badlands
        pillar = 0.0
        eroded = kind == "eroded_badlands"
        if eroded:
            d0 = min(abs(noise), float(bl.pillar.value(x * 0.25, z * 0.25, False)) * 15.0)
            if d0 > 0.0:
                d1 = abs(float(bl.pillar_roof.value(x * 0.001953125, z * 0.001953125, False)))
                pillar = min(d0 * d0 * 2.5, math.ceil(d1 * 50.0) + 14.0) + 64.0
        red_sand, white = (SAND, 1), (STAINED, WHITE)
        under = white
        k = int(noise / 3.0 + 3.0 + rnd.next_double() * 0.25)
        cos_flag = math.cos(noise / 3.0 * math.pi) > 0.0
        run = -1
        sand = False
        count = 0
        for y in range(max(start, int(pillar) + 1) if eroded else start, -1, -1):
            if not eroded and count >= 15:
                break
            if eroded and col[y] == 0 and y < int(pillar):
                col[y] = STONE
            cur = col[y]
            if cur == 0:
                run = -1
                continue
            if cur != STONE:
                continue
            if run == -1:
                sand = False
                if k <= 0:
                    under = (STONE, 0)
                elif SEA_LEVEL - 4 <= y <= SEA_LEVEL + 1:
                    under = white
                run = k + max(0, y - SEA_LEVEL)
                if kind == "wooded_badlands":
                    if y < SEA_LEVEL - 1:
                        col[y], dcol[y] = (STAINED, ORANGE) if under == white else under
                    elif y > 86 + k * 2:
                        col[y], dcol[y] = (DIRT, 1) if cos_flag else (GRASS, 0)
                    elif y <= SEA_LEVEL + 3 + k:
                        col[y], dcol[y] = red_sand
                        sand = True
                    else:
                        col[y], dcol[y] = self._band_block(y, cos_flag, x, z)
                elif y >= SEA_LEVEL - 1:
                    if y <= SEA_LEVEL + 3 + k:
                        col[y], dcol[y] = red_sand
                        sand = True
                    else:
                        col[y], dcol[y] = self._band_block(y, cos_flag, x, z)
                else:
                    col[y], dcol[y] = (STAINED, ORANGE) if under[0] == STAINED else under
            elif run > 0:
                run -= 1
                col[y], dcol[y] = (STAINED, ORANGE) if sand else bl.band(x, y, z)
            count += 1

    def _band_block(self, y, cos_flag, x, z):
        if y < 64 or y > 127:
            return STAINED, ORANGE
        if cos_flag:
            return TERRACOTTA, 0
        return self._badlands.band(x, y, z)

    def _frozen_column(self, bid, col, dcol, x, z, start, noise, rnd):
        if self._frozen is None:
            self._frozen = _FrozenOcean(self.seed)
        fo = self._frozen
        berg = 0.0
        bottom = 0.0
        t63 = temperature(bid, x, 63, z)
        d2 = min(abs(noise), float(fo.berg.value(x * 0.1, z * 0.1, False)) * 15.0)
        if d2 > 1.8:
            d4 = abs(float(fo.roof.value(x * 0.09765625, z * 0.09765625, False)))
            berg = min(d2 * d2 * 1.2, math.ceil(d4 * 40.0) + 14.0)
            if t63 > 0.1:
                berg -= 2.0
            if berg > 2.0:
                bottom = SEA_LEVEL - berg - 7.0
                berg += SEA_LEVEL
            else:
                berg = 0.0
        top_c, under_c, _w = _GRASS
        top, under = top_c, under_c
        k = int(noise / 3.0 + 3.0 + rnd.next_double() * 0.25)
        run = -1
        snow = 0
        max_snow = 2 + rnd.next_int(4)
        snow_min = SEA_LEVEL + 18 + rnd.next_int(10)
        for y in range(max(start, int(berg) + 1), -1, -1):
            if col[y] == 0 and y < int(berg) and rnd.next_double() > 0.01:
                col[y], dcol[y] = PACKED_ICE, 0
            elif col[y] == WATER and y > int(bottom) and y < SEA_LEVEL and bottom != 0.0 and rnd.next_double() > 0.15:
                col[y], dcol[y] = PACKED_ICE, 0
            cur = col[y]
            if cur == 0:
                run = -1
            elif cur == STONE:
                if run == -1:
                    if k <= 0:
                        top, under = (0, 0), (STONE, 0)
                    elif SEA_LEVEL - 4 <= y <= SEA_LEVEL + 1:
                        top, under = top_c, under_c
                    if y < SEA_LEVEL and top[0] == 0:
                        top = (ICE, 0) if temperature(bid, x, y, z) < 0.15 else (WATER, 0)
                    run = k
                    if y >= SEA_LEVEL - 1:
                        col[y], dcol[y] = top
                    elif y < SEA_LEVEL - 7 - k:
                        top, under = (0, 0), (STONE, 0)
                        col[y], dcol[y] = GRAVEL, 0
                    else:
                        col[y], dcol[y] = under
                elif run > 0:
                    run -= 1
                    col[y], dcol[y] = under
            elif cur == PACKED_ICE and snow <= max_snow and y > snow_min:
                col[y], dcol[y] = SNOW_BLOCK, 0
                snow += 1

    # ---------------------------------------------------------- public
    def chunk(self, cx: int, cz: int, lift=None):
        """Blocks (x, z, y) uint8, biome ids (x, z) and block data (x, z, y) of the chunk after the
        game's noise and surface steps; ``lift`` [x, z]: blocks to move the terrain up or down."""
        q = self._columns(cx, cz)
        d = self._density_blocks(q)
        lifted = lift is not None and bool(np.any(lift))
        blocks = lifted_rock(d, lift, SEA_LEVEL - 1) if lifted else self._rock(d)
        if lifted:
            keep = np.asarray(lift) == 0
            blocks[keep] = self._rock(d)[keep]
        data = np.zeros_like(blocks)
        biomes = self._surface(cx, cz, blocks, data)
        return blocks, biomes, data


class Modern13Generator(Modern16Generator):
    """Minecraft Java 1.13 (ChunkGeneratorOverworld, read from the 1.13.2 jar): the density of 1.12
    (modern.py, with the float settings), the biomes of 1.13 (oceans), the surface builders of 1.13
    (the same as 1.16's, on the 2D biomes and the 1.12 surface noise) and a bedrock pass over 17 x 17
    columns (the last row and column wrap onto the first, as in the game)."""

    def __init__(self, seed: int, large_biomes: bool = False, amplified: bool = False):
        from .modern import ModernGenerator

        self.seed = _s64(seed)
        self.version = "1.13"
        self.minor = 13
        self.amplified = amplified
        self.old = ModernGenerator(self.seed, "1.12", caves=False, large_biomes=large_biomes, amplified=amplified)
        self.old.stack = self.stack = Stack17("1.13", self.seed, large_biomes)
        self._badlands = None
        self._frozen = None

    def chunk(self, cx: int, cz: int, lift=None):
        from .lift import density_field
        from .modern import ModernGenerator

        b4 = self.stack.biomes4(cx * 4 - 2, cz * 4 - 2, 10, 10)
        q = self.old._density(cx, cz, b4)
        blocks = ModernGenerator._terrain(q)
        if lift is not None and bool(np.any(lift)):
            moved = lifted_rock(density_field(q), lift, SEA_LEVEL - 1)
            keep = np.asarray(lift) == 0
            moved[keep] = blocks[keep]
            blocks = moved
        data = np.zeros_like(blocks)
        biomes = self.stack.biomes(cx * 16, cz * 16, 16, 16).T.copy()            # [x, z]
        solid = blocks != 0
        start = np.where(solid.any(2), HEIGHT - 1 - np.argmax(solid[:, :, ::-1], axis=2), -1) + 1
        noise = self.old.n_surface.noise(cx * 16, cz * 16, 16, 16, 0.0625 * 1.5, 0.0625 * 1.5, 0.5, 0.5)
        rnd = JavaRandom(_s64(cx * 341873128712 + cz * 132897987541))
        for lx in range(16):
            for lz in range(16):
                col = blocks[lx, lz].tolist()
                dcol = [0] * HEIGHT
                self._apply(int(biomes[lx, lz]), col, dcol, cx * 16 + lx, cz * 16 + lz, int(start[lx, lz]),
                            float(noise[lx, lz]), rnd)
                blocks[lx, lz] = col
                data[lx, lz] = dcol
        for lz in range(17):                                   # BlockPos.getAllInBox(x0, 0, z0, x0 + 16, 0, z0 + 16)
            for lx in range(17):
                for y in range(4, -1, -1):
                    if y <= rnd.next_int(5):
                        blocks[lx & 15, lz & 15, y] = BEDROCK
                        data[lx & 15, lz & 15, y] = 0
        return blocks, biomes, data
