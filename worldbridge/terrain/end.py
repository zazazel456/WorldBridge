"""The End of Minecraft 1.0 - 1.12 (ChunkProviderEnd / ChunkGeneratorEnd), for the ring WorldBridge
writes around a converted End (ring3d.py).

Read from the 1.0, 1.6.4, 1.7.10 and 1.12.2 jars:

* a 3 x 33 x 3 density field (cells of 8 x 4 x 8 blocks) from the same three noises as the
  Nether's, plus an island shape: 100 - 8 x the distance from 0, 0 in cells (80 at most, -100 at
  least), closed at the top and at the bottom; end stone where it is positive, air elsewhere;
* 1.9 - 1.12: the outer islands, more than 1,024 blocks from the centre: wherever a 2D simplex noise
  at a chunk is below -0.9, an island 9 - 21 cells wide (the widest of those within 12 chunks);
* no surface and no caves.  The obsidian pillars, the portal, chorus plants and end cities come with
  the game's decoration.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Tuple

import numpy as np

from .betagen import JavaRandom, PerlinOctaves, Simplex, _s64
from .nether import interpolate

HEIGHT = 128
END_STONE = 121
SKY = 9
_F = np.float32
_SQ3 = math.sqrt(3.0)
_F2 = 0.5 * (_SQ3 - 1.0)
_G2 = (3.0 - _SQ3) / 6.0
_GRAD = ((1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (-1, 0), (1, 0), (-1, 0), (0, 1), (0, -1), (0, 1), (0, -1))


def _fl(v: float) -> int:
    return int(v) if v > 0.0 else int(v) - 1


def _fsqrt(v) -> np.float32:
    return _F(math.sqrt(float(v)))


class _IslandNoise:
    """SimplexNoise.getValue(x, y) of 1.9+ (no offsets)."""

    def __init__(self, simplex: Simplex):
        self.p = [int(v) for v in simplex.p]

    def value(self, x: float, y: float) -> float:
        p = self.p
        s = (x + y) * _F2
        i, j = _fl(x + s), _fl(y + s)
        t = (i + j) * _G2
        x0, y0 = x - (i - t), y - (j - t)
        i1, j1 = (1, 0) if x0 > y0 else (0, 1)
        x1, y1 = x0 - i1 + _G2, y0 - j1 + _G2
        x2, y2 = x0 - 1.0 + 2.0 * _G2, y0 - 1.0 + 2.0 * _G2
        ii, jj = i & 255, j & 255
        n = 0.0
        for g, a, b in ((p[ii + p[jj]] % 12, x0, y0), (p[ii + i1 + p[jj + j1]] % 12, x1, y1),
                        (p[ii + 1 + p[jj + 1]] % 12, x2, y2)):
            t0 = 0.5 - a * a - b * b
            if t0 >= 0.0:
                t0 *= t0
                n += t0 * t0 * (_GRAD[g][0] * a + _GRAD[g][1] * b)
        return 70.0 * n


class EndGenerator:
    """``islands``: the outer islands of 1.9+ (1.0 - 1.8: the main island only).  ``version``
    "1.13": the same terrain, the island noise drawn from a random of its own (TheEndBiomeProvider),
    and the End's biomes (``biome``)."""

    height = HEIGHT

    def __init__(self, seed: int, islands: bool = True, version: str = ""):
        self.seed = _s64(seed)
        r = JavaRandom(self.seed)
        self.lo = PerlinOctaves(r, 16)
        self.hi = PerlinOctaves(r, 16)
        self.main = PerlinOctaves(r, 8)
        PerlinOctaves(r, 10)
        PerlinOctaves(r, 16)
        self.islands = islands or version == "1.13"
        if version == "1.13":
            r = JavaRandom(self.seed)
            for _ in range(17292):
                r.next(1)
        self.noise = _IslandNoise(Simplex(r)) if self.islands else None
        self._near = lru_cache(maxsize=4096)(self._near_islands)
        self.version = version
        if version == "1.13":
            r = JavaRandom(self.seed)
            self.surface_noise = [Simplex(r) for _ in range(4)]

    def _near_islands(self, cx: int, cz: int):
        """The outer islands within 12 chunks: (dx, dz, width factor)."""
        out = []
        for i in range(-12, 13):
            for j in range(-12, 13):
                k, l = cx + i, cz + j
                if k * k + l * l > 4096 and self.noise.value(float(k), float(l)) < float(_F(-0.9)):
                    f3 = _F(_F(_F(_F(abs(_F(k))) * _F(3439.0)) + _F(_F(abs(_F(l))) * _F(147.0))) % _F(13.0)) + _F(9.0)
                    out.append((i, j, f3))
        return out

    def island(self, cx: int, cz: int, a: int, b: int) -> np.float32:
        f = _F(cx * 2 + a)
        f1 = _F(cz * 2 + b)
        h = _F(_F(100.0) - _F(_fsqrt(_F(_F(f * f) + _F(f1 * f1))) * _F(8.0)))
        h = min(max(h, _F(-100.0)), _F(80.0))
        if self.islands:
            for i, j, f3 in self._near(cx, cz):
                f = _F(a - i * 2)
                f1 = _F(b - j * 2)
                v = _F(_F(100.0) - _F(_fsqrt(_F(_F(f * f) + _F(f1 * f1))) * f3))
                v = min(max(v, _F(-100.0)), _F(80.0))
                if v > h:
                    h = v
        return h

    def density(self, cx: int, cz: int) -> np.ndarray:
        """The density grid [3, 3, 33] of a chunk (end stone where > 0 once interpolated)."""
        x, z = cx * 2, cz * 2
        d = 684.412 * 2.0
        main = self.main.noise(x, 0, z, 3, 33, 3, d / 80.0, 684.412 / 160.0, d / 80.0)
        lo = self.lo.noise(x, 0, z, 3, 33, 3, d, 684.412, d)
        hi = self.hi.noise(x, 0, z, 3, 33, 3, d, 684.412, d)
        t = (main / 10.0 + 1.0) / 2.0
        a, b = lo / 512.0, hi / 512.0
        v = np.where(t < 0.0, a, np.where(t > 1.0, b, a + (b - a) * t)) - 8.0
        isl = np.array([[float(self.island(cx, cz, i, j)) for j in range(3)] for i in range(3)])
        v = v + isl[:, :, None]
        for y in range(33):
            if y > 14:
                w = min(max(float(_F(y - 14) / _F(64.0)), 0.0), 1.0)
                v[:, :, y] = v[:, :, y] * (1.0 - w) + -3000.0 * w
            if y < 8:
                w = float(_F(8 - y) / _F(7.0))
                v[:, :, y] = v[:, :, y] * (1.0 - w) + -30.0 * w
        return v

    def biome(self, cx: int, cz: int) -> int:
        """The biome of a chunk in 1.13+ (TheEndBiomeProvider): the_end near the centre, then
        end_highlands, end_midlands, end_barrens and small_end_islands by the island's height."""
        if cx * cx + cz * cz <= 4096:
            return SKY
        h = self.island(cx, cz, 1, 1)
        return 42 if h > 40.0 else 41 if h >= 0.0 else 40 if h < -20.0 else 43

    def chunk(self, cx: int, cz: int, lift=None) -> Tuple[np.ndarray, np.ndarray]:
        """Blocks [x, z, y] of the unpopulated chunk (128 high) and its biomes (The End)."""
        d = interpolate(self.density(cx, cz), 32, 4, n=2, s=8)
        blocks = np.where(d > 0.0, END_STONE, 0).astype(np.uint8)
        if self.version == "1.13":
            self._surface13(cx, cz, blocks)
            return blocks, np.full((16, 16), self.biome(cx, cz), np.uint8)
        return blocks, np.full((16, 16), SKY, np.uint8)

    def _surface13(self, cx: int, cz: int, blocks: np.ndarray) -> None:
        """1.13's default surface builder with the End's sea at y 0: where the builder's noise is
        low the top block of every layer of end stone becomes air (the rest is end stone again)."""
        noise = np.zeros((16, 16))
        f = 1.0
        for o in self.surface_noise:
            o.add(noise, float(cx * 16), float(cz * 16), 16, 16, 0.0625 * f, 0.0625 * f, 0.55 / f)
            f *= 0.5
        rnd = JavaRandom(_s64(cx * 341873128712 + cz * 132897987541))
        bare = np.zeros((16, 16), bool)
        for x in range(16):
            for z in range(16):
                bare[x, z] = int(noise[x, z] / 3.0 + 3.0 + rnd.next_double() * 0.25) <= 0
        if bare.any():
            solid = blocks != 0
            top = solid.copy()
            top[:, :, :-1] &= ~solid[:, :, 1:]
            blocks[top & bare[:, :, None]] = 0
