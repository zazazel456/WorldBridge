"""The Nether's biomes in Minecraft Java 1.18 and later (multi-noise biome source, "nether" preset),
for the ring WorldBridge writes around a converted Nether (ring3d.py).

Found by reading the 26.3 jar and checked cell by cell against the biomes of a 26.3 Nether
(tests/test_netherbiomes.py), in our own words:

* the Nether keeps the random source of Minecraft 1.16 (its noise settings say so), so its two climate
  noises are the 1.16 ones, not the Xoroshiro-seeded noises of the Overworld: the temperature noise is
  seeded with the world seed, the humidity ("vegetation") noise with the world seed + 1, both with
  octaves -7 and -6 of amplitude 1 (the game calls this "createForLegacyNetherBiome");
* the noises are made with the old Perlin initialisation: one improved noise is drawn and, for the
  octave above the first one, set aside; the unused octaves are skipped by consuming 262 random numbers
  each (3 offsets = 6 numbers + 256 for the permutation); then the two used octaves are drawn, the
  higher one first;
* a "normal noise" is two such Perlin noises drawn one after the other from the same generator, the
  second sampled 1.0181268882175227 times farther, summed and scaled by (1/6) / (0.1 (1 + 1/2));
* the climate is the noise read at x / 4 and z / 4 of the block, i.e. at the 4 x 4 x 4 cell's own
  integer coordinates, y = 0; the other climate axes are the same for all five points and do not decide;
* the biome of a cell is the point (temperature, humidity) closest to the cell's climate, the distance
  being the sum of squares of the differences of the values times 10,000 (truncated) plus the point's
  own "offset" cost squared: nether_wastes (0, 0), soul_sand_valley (0, -0.5), crimson_forest (0.4, 0),
  warped_forest (0, 0.5) with offset 0.375, basalt_deltas (-0.5, 0) with offset 0.175.

The biomes do not change with the height.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np

from .betagen import JavaRandom, Perlin
from .modern16 import _improved, _wrap

WASTES, SOUL_SAND_VALLEY, CRIMSON_FOREST, WARPED_FOREST, BASALT_DELTAS = range(5)
NAMES = ("minecraft:nether_wastes", "minecraft:soul_sand_valley", "minecraft:crimson_forest",
         "minecraft:warped_forest", "minecraft:basalt_deltas")
# (temperature, humidity, offset) of the five points
POINTS = ((0.0, 0.0, 0.0), (0.0, -0.5, 0.0), (0.4, 0.0, 0.0), (0.0, 0.5, 0.375), (-0.5, 0.0, 0.175))
FIRST_OCTAVE = -7
AMPLITUDES = (1.0, 1.0)
INPUT_FACTOR = 1.0181268882175227
SKIP = 262              # random numbers one unused octave takes: 3 offsets (6) + the 256 swaps of the permutation


def _legacy_octaves(rnd: JavaRandom, first: int, amps) -> List[Optional[Perlin]]:
    n = len(amps)
    j = -first
    levels: List[Optional[Perlin]] = [None] * n
    zero = Perlin(rnd)
    if 0 <= j < n and amps[j] != 0.0:
        levels[j] = zero
    for k in range(j - 1, -1, -1):
        if k < n and amps[k] != 0.0:
            levels[k] = Perlin(rnd)
        else:
            for _ in range(SKIP):
                rnd.next(32)
    return levels


class _Legacy:
    """The game's NormalNoise.createForLegacyNetherBiome(LegacyRandomSource(seed))."""

    def __init__(self, seed: int):
        rnd = JavaRandom(seed)
        self.a = _legacy_octaves(rnd, FIRST_OCTAVE, AMPLITUDES)
        self.b = _legacy_octaves(rnd, FIRST_OCTAVE, AMPLITUDES)
        self.factor = (1.0 / 6.0) / (0.1 * (1.0 + 1.0 / len(AMPLITUDES)))

    @staticmethod
    def _perlin(levels, x, y, z):
        n = len(AMPLITUDES)
        inp = 2.0 ** FIRST_OCTAVE
        vf = 2.0 ** (n - 1) / (2.0 ** n - 1.0)
        tot = 0.0
        for amp, lv in zip(AMPLITUDES, levels):
            if lv is not None:
                tot = tot + amp * _improved(lv, _wrap(x * inp), _wrap(y * inp), _wrap(z * inp)) * vf
            inp *= 2.0
            vf /= 2.0
        return tot

    def value(self, x, y, z):
        f = INPUT_FACTOR
        return (self._perlin(self.a, x, y, z) + self._perlin(self.b, x * f, y * f, z * f)) * self.factor


class NetherBiomes:
    """``grid(qx, qz)`` -> index (0 nether_wastes ... 4 basalt_deltas) of the 4 x 4 cells' columns."""

    def __init__(self, seed: int):
        self.temperature = _Legacy(seed)
        self.vegetation = _Legacy(seed + 1)

    def climate(self, qx, qz):
        """(temperature, humidity) at the cells' coordinates (arrays broadcast together)."""
        x = np.asarray(qx, np.float64)
        z = np.asarray(qz, np.float64)
        return self.temperature.value(x, 0.0, z), self.vegetation.value(x, 0.0, z)

    def grid(self, qx, qz) -> np.ndarray:
        """[len(qx), len(qz)] biome index of the columns of cells qx x qz (4 blocks each)."""
        t, h = self.climate(np.asarray(qx)[:, None], np.asarray(qz)[None, :])
        tq = np.trunc(t.astype(np.float32) * np.float32(10000.0))
        hq = np.trunc(h.astype(np.float32) * np.float32(10000.0))
        best = None
        out = np.zeros(tq.shape, np.int8)
        for i, (pt, ph, po) in enumerate(POINTS):
            d = (tq - int(pt * 10000)) ** 2 + (hq - int(ph * 10000)) ** 2 + int(po * 10000) ** 2
            if best is None:
                best = d
            else:
                better = d < best
                best = np.where(better, d, best)
                out = np.where(better, i, out).astype(np.int8)
        return out

    def chunk(self, cx: int, cz: int) -> np.ndarray:
        """[4, 4] biomes of the chunk's cells (index [qx, qz])."""
        return self.grid(cx * 4 + np.arange(4), cz * 4 + np.arange(4))
