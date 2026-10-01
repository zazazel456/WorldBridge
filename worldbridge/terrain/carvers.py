"""Caves and ravines of Minecraft Beta 1.8 - 1.1 (MapGenCaves, MapGenRavine), for releasegen.

The caves are Beta 1.7.3's (betagen) with the changes of Beta 1.8, read from the 1.0 / 1.1 code:
* the seed of each source chunk is ``x * a ^ z * b ^ worldSeed`` (a, b: two plain nextLong());
* the angles use (float) Math.PI (Beta: 3.141593F) and the sine table 10430.378F (Beta: 10430.38F);
* grass over a carved hole comes back as the biome's top block;
* ravines: 1 source chunk in 50, a tall narrow cut with ragged walls.
"""

from __future__ import annotations

import math
from collections import OrderedDict

import numpy as np

from .betagen import DIRT, GRASS, LAVA_FLOWING, STONE, WATER, WATER_FLOWING, JavaRandom, _s64, _SIN, water_in_box

_F = np.float32
PI = _F(math.pi)                 # (float) Math.PI
HALF_PI = _F(math.pi / 2)        # (float) (Math.PI / 2)
_K = _F(10430.378)
RANGE = 8
HEIGHT = 128


def _sin(f) -> np.float32:
    return _SIN[int(_F(f) * _K) & 0xFFFF]


def _cos(f) -> np.float32:
    return _SIN[int(_F(_F(f) * _K) + _F(16384.0)) & 0xFFFF]


def _floor(d: float) -> int:
    i = int(d)
    return i - 1 if d < i else i


def _water_nearby(blocks, x0, x1, y0, y1, z0, z1, height=HEIGHT) -> bool:
    return water_in_box(blocks, x0, x1, y0, y1, z0, z1)


def _water_nearby_scan(blocks, x0, x1, y0, y1, z0, z1, height=HEIGHT) -> bool:
    """The game's own loop (reference for the tests)."""
    for xx in range(x0, x1):
        for zz in range(z0, z1):
            yy = y1 + 1
            while yy >= y0 - 1:
                if 0 <= yy < height:
                    b = blocks[xx, zz, yy]
                    if b == WATER_FLOWING or b == WATER:
                        return True
                    if yy != y0 - 1 and xx != x0 and xx != x1 - 1 and zz != z0 and zz != z1 - 1:
                        yy = y0
                yy -= 1
    return False


def chunk_top_of(b1: np.ndarray, cx: int, cz: int, top_block, fallback):
    """The biome's top block at a world column, from the biomes ``b1`` [z, x] of chunk (cx, cz) (the
    ones the layer stack gives there), ``fallback`` elsewhere."""
    x0, z0 = cx * 16, cz * 16
    tops = {}

    def top_of(x: int, z: int) -> int:
        lx, lz = x - x0, z - z0
        if 0 <= lx < 16 and 0 <= lz < 16:
            b = int(b1[lz, lx])
            t = tops.get(b)
            if t is None:
                t = tops[b] = top_block(b)
            return t
        return fallback(x, z)
    return top_of


def lce_sin_table() -> np.ndarray:
    """Mth::init of the 4J code: the angle is computed in float (Java: in double)."""
    i = np.arange(65536, dtype=np.float32)
    a = i * np.float32(math.pi) * np.float32(2.0) / np.float32(65536.0)
    return np.sin(a.astype(np.float64)).astype(np.float32)


# blocks the caves of 1.8+ also cut through (MapGenCaves.canReplaceBlock): hardened and stained clay,
# sandstone, red sandstone, mycelium, snow; sand and gravel unless water is right above
_WIDE = np.zeros(256, bool)
_WIDE[[1, 2, 3, 172, 159, 24, 179, 110, 78]] = True


def _in_tunnel(x, z, dy, y) -> bool:
    return dy > -0.7 and x * x + dy * dy + z * z < 1.0


class ReleaseCarvers:
    """``height``: blocks of the world (128; 256 from 1.7, whose caves reach y 248 and are rarer:
    ``modern``); ``wide``: the caves of 1.8+ cut through more blocks."""

    def __init__(self, seed: int, sin_table: np.ndarray = None, msvc: bool = False, modern: bool = False,
                 wide: bool = False):
        self.seed = _s64(seed)
        self.height = 256 if modern else HEIGHT
        self.rarity = (15, 7) if modern else (40, 15)
        self.wide = wide
        self.lava = 11 if modern else LAVA_FLOWING         # 1.7+: still lava
        self.table = _SIN if sin_table is None else sin_table
        # the 4J code is C++ built with MSVC, which makes the calls of a function's arguments from
        # right to left: a branch's width is drawn before its seed (Java: seed first)
        self.msvc = msvc

    def _branch(self, random):
        """seed and width of a branch: addTunnel(nextLong(), ..., nextFloat() * 0.5 + 0.5, ...)."""
        if self.msvc:
            w = random.next_float()
            return random.next_long(), _F(_F(w * _F(0.5)) + _F(0.5))
        s = random.next_long()
        return s, _F(_F(random.next_float() * _F(0.5)) + _F(0.5))

    def _sin(self, f) -> np.float32:
        return self.table[int(_F(f) * _K) & 0xFFFF]

    def _cos(self, f) -> np.float32:
        return self.table[int(_F(_F(f) * _K) + _F(16384.0)) & 0xFFFF]

    def carve(self, cx: int, cz: int, blocks: np.ndarray, top_of) -> None:
        """blocks [x, z, y]; top_of(x, z) = the biome's top block at the world column.

        A cave or ravine is drawn from its source chunk's seed alone and carved into every chunk
        within 8 of it: the tunnels of each source chunk (``_sources``) and the course of each tunnel
        (``_tunnel_path``) are worked out once and kept; for every chunk only what depends on it
        runs again (how far the tunnel goes before it is out of reach, the blocks it carves)."""
        self.top_of = top_of
        for kind in (0, 1):                                 # caves, then ravines (MapGenCaves, MapGenRavine)
            for i in range(cx - RANGE, cx + RANGE + 1):
                for j in range(cz - RANGE, cz + RANGE + 1):
                    for spec in self._sources(kind, i, j):
                        if kind == 0:
                            self._tunnel(spec[0], cx, cz, blocks, *spec[1:])
                        else:
                            self._ravine(spec[0], cx, cz, blocks, *spec[1:])

    def _sources(self, kind: int, i: int, j: int) -> list:
        """The tunnels (kind 0) or ravines (kind 1) that start in source chunk (i, j): their
        arguments, drawn as the game draws them."""
        cache = self.__dict__.setdefault("_source_cache", OrderedDict())
        key = (kind, i, j)
        got = cache.get(key)
        if got is not None:
            cache.move_to_end(key)
            return got
        ab = self.__dict__.get("_ab")
        if ab is None:
            r = JavaRandom(self.seed)
            ab = self._ab = (r.next_long(), r.next_long())
        rnd = JavaRandom(0)
        rnd.set_seed(_s64(i * ab[0]) ^ _s64(j * ab[1]) ^ self.seed)
        got = cache[key] = (self._cave_specs if kind == 0 else self._ravine_specs)(rnd, i, j)
        if len(cache) > 20000:
            cache.popitem(last=False)
        return got

    # ------------------------------------------------------------------ caves
    def _cave_source(self, rnd: JavaRandom, i: int, j: int, cx: int, cz: int, blocks):
        for spec in self._cave_specs(rnd, i, j):
            self._tunnel(spec[0], cx, cz, blocks, *spec[1:])

    def _cave_specs(self, rnd: JavaRandom, i: int, j: int) -> list:
        """(seed, d, d1, d2, f, f1, f2, k, l, d3) of every tunnel of source chunk (i, j).  The tunnels
        draw from their own random: calling them after all the source's draws changes nothing."""
        out = []
        n = rnd.next_int(rnd.next_int(rnd.next_int(self.rarity[0]) + 1) + 1)
        if rnd.next_int(self.rarity[1]) != 0:
            n = 0
        for _ in range(n):
            d = float(i * 16 + rnd.next_int(16))
            d1 = float(rnd.next_int(rnd.next_int(HEIGHT - 8) + 8))
            d2 = float(j * 16 + rnd.next_int(16))
            k1 = 1
            if rnd.next_int(4) == 0:
                seed = rnd.next_long()
                out.append((seed, d, d1, d2, _F(_F(1.0) + _F(rnd.next_float() * _F(6.0))), _F(0.0), _F(0.0), -1, -1, 0.5))
                k1 += rnd.next_int(4)
            for _ in range(k1):
                f = _F(_F(rnd.next_float() * PI) * _F(2.0))
                f1 = _F(_F(_F(rnd.next_float() - _F(0.5)) * _F(2.0)) / _F(8.0))
                f2 = _F(_F(rnd.next_float() * _F(2.0)) + rnd.next_float())
                if rnd.next_int(10) == 0:
                    f2 = _F(f2 * _F(_F(_F(rnd.next_float() * rnd.next_float()) * _F(3.0)) + _F(1.0)))
                out.append((rnd.next_long(), d, d1, d2, f2, f, f1, 0, 0, 1.0))
        return out

    def _tunnel_path(self, seed: int, d: float, d1: float, d2: float, f, f1, f2, k: int, l: int, d3: float):
        """The course of a tunnel, whatever chunk it is carved in: (room, l, width, the steps that may
        carve [(k, d, d1, d2, d6, d7)], the two branches it splits into)."""
        cache = self.__dict__.setdefault("_path_cache", OrderedDict())
        key = (seed, d, d1, d2, f, f1, f2, k, l, d3)
        got = cache.get(key)
        if got is not None:
            cache.move_to_end(key)
            return got
        f3 = _F(0.0)
        f4 = _F(0.0)
        random = JavaRandom(seed)
        if l <= 0:
            i1 = RANGE * 16 - 16
            l = i1 - random.next_int(i1 // 4)
        room = False
        if k == -1:
            k = l // 2
            room = True
        j1 = random.next_int(l // 2) + l // 4
        steep = random.next_int(6) == 0
        steps = []
        branches = ()
        while k < l:
            d6 = 1.5 + float(_F(_F(self._sin(_F(_F(k) * PI) / _F(l))) * f) * _F(1.0))
            d7 = d6 * d3
            f5 = self._cos(f2)
            f6 = self._sin(f2)
            d += float(_F(self._cos(f1) * f5))
            d1 += float(f6)
            d2 += float(_F(self._sin(f1) * f5))
            f2 = _F(f2 * (_F(0.92) if steep else _F(0.7)))
            f2 = _F(f2 + _F(f4 * _F(0.1)))
            f1 = _F(f1 + _F(f3 * _F(0.1)))
            f4 = _F(f4 * _F(0.9))
            f3 = _F(f3 * _F(0.75))
            a, b, c = random.next_float(), random.next_float(), random.next_float()
            f4 = _F(f4 + _F(_F(_F(a - b) * c) * _F(2.0)))
            a, b, c = random.next_float(), random.next_float(), random.next_float()
            f3 = _F(f3 + _F(_F(_F(a - b) * c) * _F(4.0)))
            if not room and k == j1 and f > _F(1.0) and l > 0:
                s1, w1 = self._branch(random)
                s2, w2 = self._branch(random)
                branches = ((s1, d, d1, d2, w1, _F(f1 - HALF_PI), _F(f2 / _F(3.0)), k, l, 1.0),
                            (s2, d, d1, d2, w2, _F(f1 + HALF_PI), _F(f2 / _F(3.0)), k, l, 1.0))
                break
            if room or random.next_int(4) != 0:
                steps.append((k, d, d1, d2, d6, d7))
            k += 1
        got = cache[key] = (room, l, f, steps, branches)
        if len(cache) > 20000:
            cache.popitem(last=False)
        return got

    def _tunnel(self, seed: int, i: int, j: int, blocks, d: float, d1: float, d2: float,
                f, f1, f2, k: int, l: int, d3: float):
        """MapGenCaves.addTunnel into chunk (i, j), along the tunnel's course (``_tunnel_path``)."""
        room, l, f, steps, branches = self._tunnel_path(seed, d, d1, d2, f, f1, f2, k, l, d3)
        d4 = float(i * 16 + 8)
        d5 = float(j * 16 + 8)
        d11 = float(_F(_F(f + _F(2.0)) + _F(16.0)))
        for k, d, d1, d2, d6, d7 in steps:
            d8, d9 = d - d4, d2 - d5
            d10 = float(l - k)
            if d8 * d8 + d9 * d9 - d10 * d10 > d11 * d11:
                return                                   # out of this chunk's reach from here on
            if not (d < d4 - 16.0 - d6 * 2.0 or d2 < d5 - 16.0 - d6 * 2.0
                    or d > d4 + 16.0 + d6 * 2.0 or d2 > d5 + 16.0 + d6 * 2.0):
                carved = self._carve(blocks, i, j, d, d1, d2, d6, d7, _in_tunnel, self.wide)
                if room and carved:
                    return
        for b in branches:
            self._tunnel(b[0], i, j, blocks, *b[1:])

    def _carve(self, blocks, i, j, d, d1, d2, d6, d7, inside, wide=False) -> bool:
        """Carve one step of a tunnel; False when water is nearby (nothing carved)."""
        H = self.height
        x0 = max(_floor(d - d6) - i * 16 - 1, 0)
        x1 = min(_floor(d + d6) - i * 16 + 1, 16)
        y0 = max(_floor(d1 - d7) - 1, 1)
        y1 = min(_floor(d1 + d7) + 1, H - 8)
        z0 = max(_floor(d2 - d6) - j * 16 - 1, 0)
        z1 = min(_floor(d2 + d6) - j * 16 + 1, 16)
        if _water_nearby(blocks, x0, x1, y0, y1, z0, z1, H):
            return False
        for xx in range(x0, x1):
            d12 = ((xx + i * 16) + 0.5 - d) / d6
            for zz in range(z0, z1):
                d13 = ((zz + j * 16) + 0.5 - d2) / d6
                if d12 * d12 + d13 * d13 >= 1.0:
                    continue
                col = blocks[xx, zz]
                grass = False
                yw = y1                          # the block written is one above the one tested (as in the game)
                for yt in range(y1 - 1, y0 - 1, -1):
                    d14 = (yt + 0.5 - d1) / d7
                    if inside(d12, d13, d14, yt):
                        b = col[yw]
                        if b == GRASS or (wide and b == 110):
                            grass = True
                        if (_WIDE[b] or (b in (12, 13) and col[yw + 1] not in (8, 9))) if wide else \
                                (b == STONE or b == DIRT or b == GRASS):
                            if yt < 10:
                                col[yw] = self.lava
                            else:
                                col[yw] = 0
                                if grass and col[yw - 1] == DIRT:
                                    col[yw - 1] = self.top_of(xx + i * 16, zz + j * 16)
                    yw -= 1
        return True

    # ------------------------------------------------------------------ ravines
    def _ravine_source(self, rnd: JavaRandom, i: int, j: int, cx: int, cz: int, blocks):
        for spec in self._ravine_specs(rnd, i, j):
            self._ravine(spec[0], cx, cz, blocks, *spec[1:])

    def _ravine_specs(self, rnd: JavaRandom, i: int, j: int) -> list:
        if rnd.next_int(50) != 0:
            return []
        d = float(i * 16 + rnd.next_int(16))
        d1 = float(rnd.next_int(rnd.next_int(40) + 8) + 20)
        d2 = float(j * 16 + rnd.next_int(16))
        f = _F(_F(rnd.next_float() * PI) * _F(2.0))
        f1 = _F(_F(_F(rnd.next_float() - _F(0.5)) * _F(2.0)) / _F(8.0))
        f2 = _F(_F(_F(rnd.next_float() * _F(2.0)) + rnd.next_float()) * _F(2.0))
        return [(rnd.next_long(), d, d1, d2, f2, f, f1, 0, 0, 3.0)]

    def _ravine_path(self, seed: int, d: float, d1: float, d2: float, f, f1, f2, k: int, l: int, d3: float):
        """The course of a ravine, whatever chunk it is carved in (see ``_tunnel_path``)."""
        cache = self.__dict__.setdefault("_path_cache", OrderedDict())
        key = ("ravine", seed, d, d1, d2, f, f1, f2, k, l, d3)
        got = cache.get(key)
        if got is not None:
            cache.move_to_end(key)
            return got
        random = JavaRandom(seed)
        f3 = _F(0.0)
        f4 = _F(0.0)
        if l <= 0:
            i1 = RANGE * 16 - 16
            l = i1 - random.next_int(i1 // 4)
        room = False
        if k == -1:
            k = l // 2
            room = True
        widths = np.empty(self.height, np.float64)
        w = _F(1.0)
        for y in range(self.height):
            if y == 0 or random.next_int(3) == 0:
                w = _F(_F(1.0) + _F(_F(random.next_float() * random.next_float()) * _F(1.0)))
            widths[y] = float(_F(w * w))
        steps = []
        while k < l:
            d6 = 1.5 + float(_F(_F(self._sin(_F(_F(k) * PI) / _F(l))) * f) * _F(1.0))
            d7 = d6 * d3
            d6 *= float(random.next_float()) * 0.25 + 0.75
            d7 *= float(random.next_float()) * 0.25 + 0.75
            f5 = self._cos(f2)
            f6 = self._sin(f2)
            d += float(_F(self._cos(f1) * f5))
            d1 += float(f6)
            d2 += float(_F(self._sin(f1) * f5))
            f2 = _F(f2 * _F(0.7))
            f2 = _F(f2 + _F(f4 * _F(0.05)))
            f1 = _F(f1 + _F(f3 * _F(0.05)))
            f4 = _F(f4 * _F(0.8))
            f3 = _F(f3 * _F(0.5))
            a, b, c = random.next_float(), random.next_float(), random.next_float()
            f4 = _F(f4 + _F(_F(_F(a - b) * c) * _F(2.0)))
            a, b, c = random.next_float(), random.next_float(), random.next_float()
            f3 = _F(f3 + _F(_F(_F(a - b) * c) * _F(4.0)))
            if room or random.next_int(4) != 0:
                steps.append((k, d, d1, d2, d6, d7))
            k += 1
        widths = widths.tolist()

        def inside(x, z, dy, y):
            return (x * x + z * z) * widths[y] + dy * dy / 6.0 < 1.0
        got = cache[key] = (room, l, f, steps, inside)
        if len(cache) > 20000:
            cache.popitem(last=False)
        return got

    def _ravine(self, seed: int, i: int, j: int, blocks, d: float, d1: float, d2: float,
                f, f1, f2, k: int, l: int, d3: float):
        """MapGenRavine.addTunnel into chunk (i, j), along the ravine's course (``_ravine_path``)."""
        room, l, f, steps, inside = self._ravine_path(seed, d, d1, d2, f, f1, f2, k, l, d3)
        d4 = float(i * 16 + 8)
        d5 = float(j * 16 + 8)
        d11 = float(_F(_F(f + _F(2.0)) + _F(16.0)))
        for k, d, d1, d2, d6, d7 in steps:
            d8, d9 = d - d4, d2 - d5
            d10 = float(l - k)
            if d8 * d8 + d9 * d9 - d10 * d10 > d11 * d11:
                return
            if not (d < d4 - 16.0 - d6 * 2.0 or d2 < d5 - 16.0 - d6 * 2.0
                    or d > d4 + 16.0 + d6 * 2.0 or d2 > d5 + 16.0 + d6 * 2.0):
                carved = self._carve(blocks, i, j, d, d1, d2, d6, d7, inside)
                if room and carved:
                    return
