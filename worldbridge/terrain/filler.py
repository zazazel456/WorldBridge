"""Fast natural terrain to fill finite worlds (LCE, PE 0.x) around a converted world.

A finite world whose every chunk is written never generates anything, so its border cannot show
a seam: the terrain around the converted area does not have to match any game, it only has to
look natural and be fast (an LCE map is up to 320 x 320 chunks).  The biomes are those of 1.1
(genlayers, exact), the height follows the biomes as in the game (5x5 weighted minimum / maximum
height at 1:4) plus a 2D noise, the surface the biome's blocks.  No caves; ores, trees and lakes
are added by the game when it decorates the chunks.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from .betagen import BEDROCK, DIRT, GRASS, GRAVEL, ICE, SAND, SANDSTONE, STONE, WATER, JavaRandom, PerlinOctaves, _s64
from .genlayers import Stack
from .releasegen import _TOPS, _heights

SEA = 62                      # sea surface (the highest water block), as every game since Beta 1.8
_FROZEN = (10, 11, 12, 13)


class FillGenerator:
    def __init__(self, seed: int, sea: int = SEA):
        self.seed = _s64(seed)
        self.sea = sea
        self.stack = Stack("1.1", self.seed)
        tab = _heights("1.1")
        self.lo = np.zeros(64, np.float32)
        self.hi = np.full(64, 0.3, np.float32)
        for k, (lo, hi, _t) in tab.items():
            self.lo[k], self.hi[k] = lo, hi
        r = JavaRandom(self.seed ^ 0x5DEECE66D)
        self.detail = PerlinOctaves(r, 6)
        self.depth = PerlinOctaves(r, 4)
        pf = np.zeros((5, 5), np.float32)
        for i in range(-2, 3):
            for j in range(-2, 3):
                pf[j + 2, i + 2] = 10.0 / np.sqrt(i * i + j * j + 0.2)
        self.pf = pf
        self._regions = {}

    # biomes are computed for whole regions (32 x 32 chunks): per chunk the layers cost 20 times more
    def _region(self, rx: int, rz: int):
        got = self._regions.get((rx, rz))
        if got is None:
            b4 = self.stack.biomes4(rx * 128 - 2, rz * 128 - 2, 128 + 7, 128 + 7).astype(np.int16)
            b1 = self.stack.biomes(rx * 512, rz * 512, 512, 512).astype(np.int16)
            got = self._regions[(rx, rz)] = (b4, b1)
        return got

    def _b4(self, cx: int, cz: int) -> np.ndarray:
        b4, _ = self._region(cx >> 5, cz >> 5)
        x, z = (cx & 31) * 4, (cz & 31) * 4
        return b4[z:z + 9, x:x + 9]

    def _b1(self, cx: int, cz: int) -> np.ndarray:
        _, b1 = self._region(cx >> 5, cz >> 5)
        x, z = (cx & 31) * 16, (cz & 31) * 16
        return b1[z:z + 16, x:x + 16]

    def _shape(self, cx: int, cz: int):
        """Weighted minimum / maximum height at the 5 x 5 corners of the chunk's 4-block cells."""
        b4 = self._b4(cx, cz)                                         # [z, x]
        lo, hi = self.lo[b4], self.hi[b4]
        f = np.zeros((5, 5), np.float32)
        f1 = np.zeros((5, 5), np.float32)
        tot = np.zeros((5, 5), np.float32)
        clo = lo[2:7, 2:7]
        for j in range(5):
            for i in range(5):
                l, h = lo[j:j + 5, i:i + 5], hi[j:j + 5, i:i + 5]
                w = self.pf[j, i] / (l + 2.0)
                w = np.where(l > clo, w / 2.0, w)
                f += h * w
                f1 += l * w
                tot += w
        return f1 / tot, f / tot                                      # [z, x] at x = 4k, z = 4k

    @staticmethod
    def _up(a: np.ndarray) -> np.ndarray:
        """5 x 5 corners -> 16 x 16 columns (bilinear)."""
        t = np.arange(16) / 4.0
        i = np.minimum(t.astype(int), 3)
        u = t - i
        rows = a[i] * (1 - u)[:, None] + a[i + 1] * u[:, None]       # z
        return rows[:, i] * (1 - u)[None, :] + rows[:, i + 1] * u[None, :]

    def heights(self, cx: int, cz: int, lift=None) -> np.ndarray:
        lo, hi = self._shape(cx, cz)
        lo, hi = self._up(lo), self._up(hi)                            # [z, x]
        # x and z axes: along y the old games' noise recomputes its gradients per cell (seams)
        n = self.detail.noise(cx * 16, 0.0, cz * 16, 16, 1, 16, 1 / 8.0, 1.0, 1 / 8.0).T / 12.0
        h = self.sea + 2 + 20.0 * lo + (4.0 + 24.0 * hi) * np.clip(n, -1.5, 1.5)
        h = np.maximum(h, 30.0)                                       # ocean floors not deeper than y 30
        if lift is not None:
            return np.clip(np.rint(h + np.asarray(lift).T), 2, 125).astype(np.int32)
        return np.clip(np.rint(h), 30, 120).astype(np.int32)          # [z, x]

    def chunk(self, cx: int, cz: int, lift=None) -> Tuple[np.ndarray, np.ndarray]:
        """Blocks (x, z, y) uint8 and biome ids (x, z), like the game generators; ``lift`` [x, z]
        raises (lowers) the ground."""
        h = self.heights(cx, cz, lift).T                               # [x, z]
        b1 = self._b1(cx, cz).T.astype(np.int64)                      # [x, z]
        depth = 3 + (self.depth.noise(cx * 16, 0.0, cz * 16, 16, 1, 16, 1 / 16.0, 1.0, 1 / 16.0) > 0)
        top = np.full((16, 16), GRASS, np.uint8)
        fill = np.full((16, 16), DIRT, np.uint8)
        for bid, (t, f) in _TOPS.items():
            top[b1 == bid] = t
            fill[b1 == bid] = f
        wet = h < self.sea
        shore = (h >= self.sea - 1) & (h <= self.sea + 1)
        top = np.where(shore, SAND, np.where(wet, np.where(h >= self.sea - 6, SAND, GRAVEL), top)).astype(np.uint8)
        fill = np.where(shore | (wet & (h >= self.sea - 6)), SAND, np.where(wet, GRAVEL, fill)).astype(np.uint8)
        y = np.arange(128)[None, None, :]
        hh = h[:, :, None]
        blocks = np.where(y < hh - depth[:, :, None], STONE, 0).astype(np.uint8)
        blocks = np.where((y >= hh - depth[:, :, None]) & (y < hh), fill[:, :, None], blocks)
        blocks = np.where(y == hh, top[:, :, None], blocks)
        sandstone = (fill == SAND)[:, :, None] & (y < hh - depth[:, :, None]) & (y >= hh - depth[:, :, None] - 2)
        blocks = np.where(sandstone, SANDSTONE, blocks)
        water = (y > hh) & (y <= self.sea)
        frozen = np.isin(b1, _FROZEN)[:, :, None] & (y == self.sea)
        blocks = np.where(water, np.where(frozen, ICE, WATER), blocks)
        # bedrock: the floor and a ragged layer above it
        rng = np.random.default_rng([self.seed & 0xFFFFFFFF, cx & 0xFFFFFFFF, cz & 0xFFFFFFFF])
        rag = rng.integers(0, 5, (16, 16, 5))
        bed = (y[:, :, :5] <= rag) | (y[:, :, :5] == 0)
        blocks[:, :, :5] = np.where(bed, BEDROCK, blocks[:, :, :5])
        return blocks, b1.astype(np.int64)
