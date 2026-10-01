"""The Nether and the End of Minecraft 1.14 - 1.17 (NoiseChunkGenerator), for the ring WorldBridge
writes around a converted Nether or End (ring3d.py).

Read from the 1.16.5 jar (NoiseChunkGenerator, NoiseGeneratorSettings "nether" and "end",
TheEndBiomeSource) and checked against the density the game computes (tools: a harness that calls
the game's own code with the same seed):

* Nether: 128 blocks, noise cells of 4 x 8 x 4 blocks; the Overworld's three noises with a
  y scale 3 times larger (684.412 x 3, factor 60), every Nether biome with depth 0.1 and scale 0.2,
  closed by a slide to 120 at the top (3 cells) and to 320 at the bottom (4 cells); netherrack where
  the density is positive, lava under y 32;
* End: 128 blocks, cells of 8 x 4 x 8; the island shape of TheEndBiomeSource (the main island and,
  more than 1,024 blocks away, the outer islands) instead of the biomes' depth, slides to -3000 at
  the top and -30 at the bottom; end stone where the density is positive.

The ring's chunks are written as the game leaves them after its "noise" step: the game then adds
its biomes, surfaces (soul sand valleys, basalt deltas, nylium), caves and decoration by itself.
"""

from __future__ import annotations

import math
from functools import lru_cache
from typing import Tuple

import numpy as np

from .betagen import JavaRandom, Simplex, _s64
from .end import _IslandNoise
from .modern16 import _improved, _octaves, _wrap

_F = np.float32
NETHERRACK, LAVA, END_STONE = 87, 11, 121
HELL, SKY = 8, 9


def _clamped_lerp(a, b, t):
    return np.where(t < 0.0, a, np.where(t > 1.0, b, a + t * (b - a)))


class _Noise16:
    """The blended noise of NoiseChunkGenerator (min / max limit, main)."""

    def __init__(self, seed: int, xz_scale: float, y_scale: float, xz_factor: float, y_factor: float):
        r = JavaRandom(_s64(seed))
        self.n_min = _octaves(r, 16)
        self.n_max = _octaves(r, 16)
        self.n_main = _octaves(r, 8)
        self.xz = 684.412 * xz_scale
        self.y = 684.412 * y_scale
        self.xz_main = self.xz / xz_factor
        self.y_main = self.y / y_factor

    def sample(self, X, Y, Z):
        lo = hi = main = 0.0
        o = 1.0
        for i in range(16):
            fx = _wrap(X * self.xz * o)
            fy = _wrap(Y * self.y * o)
            fz = _wrap(Z * self.xz * o)
            ys = self.y * o
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


def _biome_shape(depth: float, scale: float) -> Tuple[float, float]:
    """The depth and scale factor of a column whose 5 x 5 biomes all have ``depth`` / ``scale``."""
    d, s = _F(depth), _F(scale)
    sd = ss = sw = _F(0)
    for i in range(-2, 3):
        for j in range(-2, 3):
            w = _F(_F(10.0) / np.sqrt(_F(_F(i * i + j * j) + _F(0.2)), dtype=np.float32))
            w = _F(w / _F(d + _F(2.0)))
            ss = _F(ss + _F(s * w))
            sd = _F(sd + _F(d * w))
            sw = _F(sw + w)
    dd, sc = _F(sd / sw), _F(ss / sw)
    return float(_F(_F(dd * _F(0.5)) - _F(0.125))) * 0.265625, 96.0 / float(_F(_F(sc * _F(0.9)) + _F(0.1)))


def density_blocks(q: np.ndarray, w: int, h: int) -> np.ndarray:
    """[16, 16, H] density from the columns [16 / w + 1, 16 / w + 1, H / h + 1]: interpolated along
    y, then x, then z (as the game), then shaped."""
    nx, ny = q.shape[0] - 1, q.shape[2] - 1
    yf = (np.arange(h) / h)[None, None, None, :]
    lo, hi = q[:, :, :ny, None], q[:, :, 1:, None]
    qy = (lo + yf * (hi - lo)).reshape(nx + 1, nx + 1, ny * h)
    xf = (np.arange(w) / w)[None, :, None, None]
    qx = (qy[:nx, None] + xf * (qy[1:, None] - qy[:nx, None])).reshape(nx * w, nx + 1, ny * h)
    zf = (np.arange(w) / w)[None, None, :, None]
    qz = qx[:, :nx, None] + zf * (qx[:, 1:, None] - qx[:, :nx, None])
    d = np.clip(qz.reshape(nx * w, nx * w, ny * h) / 200.0, -1.0, 1.0)
    return d / 2.0 - d * d * d / 24.0


class Nether16Generator:
    """``version`` "1.14" / "1.15": NetherChunkGenerator, the same noise minus the cosine curve of the
    old Nether over the height (nether.py) and a slide to -10 over its top 3 samples."""

    height = 128

    def __init__(self, seed: int, version: str = "1.16"):
        self.seed = _s64(seed)
        self.legacy = int(version.split(".")[1]) <= 15
        self.noise = _Noise16(self.seed, 1.0, 3.0, 80.0, 60.0)
        self.depth, self.factor = _biome_shape(0.1, 0.2)

    def columns(self, cx: int, cz: int) -> np.ndarray:
        """[5, 5, 17] densities of the chunk's noise columns."""
        return self.grid(cx * 4 + np.arange(5), cz * 4 + np.arange(5))

    def grid(self, xs, zs) -> np.ndarray:
        """[len(xs), len(zs), 17] densities of the noise columns xs x zs."""
        X = np.asarray(xs)[:, None, None].astype(np.float64)
        Z = np.asarray(zs)[None, :, None].astype(np.float64)
        Y = np.arange(17)[None, None, :].astype(np.float64)
        X, Z, Y = np.broadcast_arrays(X, Z, Y)
        n = self.noise.sample(X, Y, Z)
        if self.legacy:
            from .nether import _CURVE

            n = n - _CURVE[None, None, :]
            t = (Y - 13.0) / 3.0
            return np.where(Y > 13.0, np.where(t > 1.0, -10.0, n + t * (-10.0 - n)), n)
        dens = (1.0 - Y * 2.0 / 16.0) * 0.0 + 0.019921875
        v = (dens + self.depth) * self.factor
        n = n + np.where(v > 0.0, v * 4.0, v)
        n = _clamped_lerp(120.0, n, ((16.0 - Y) - 0.0) / 3.0)
        return _clamped_lerp(320.0, n, (Y - -1.0) / 4.0)

    def chunk(self, cx: int, cz: int, lift=None):
        d = density_blocks(self.columns(cx, cz), 4, 8)
        y = np.arange(128)[None, None, :]
        blocks = np.where(d > 0.0, NETHERRACK, np.where(y < 32, LAVA, 0)).astype(np.uint8)
        return blocks, np.full((16, 16), HELL, np.uint8)


class End16Generator:
    """``version`` "1.14" / "1.15": EndChunkGenerator, the same noise and island with the slides of
    NoiseChunkGenerator's older form."""

    height = 128

    def __init__(self, seed: int, version: str = "1.16"):
        self.seed = _s64(seed)
        self.legacy = int(version.split(".")[1]) <= 15
        self.noise = _Noise16(self.seed, 2.0, 1.0, 80.0, 160.0)
        r = JavaRandom(self.seed)
        for _ in range(17292):
            r.next(1)
        self.islands = _IslandNoise(Simplex(r))
        self.height_value = lru_cache(maxsize=65536)(self._height_value)

    def _height_value(self, x: int, z: int) -> float:
        """TheEndBiomeSource.getHeightValue at the noise column x, z (8 blocks each)."""
        i, j = int(x / 2), int(z / 2)                    # Java: towards 0
        k, l = x - 2 * i, z - 2 * j
        h = _F(_F(100.0) - _F(_F(math.sqrt(float(_F(x * x + z * z)))) * _F(8.0)))
        h = min(max(h, _F(-100.0)), _F(80.0))
        for m in range(-12, 13):
            for n in range(-12, 13):
                o, p = i + m, j + n
                if o * o + p * p > 4096 and self.islands.value(float(o), float(p)) < float(_F(-0.9)):
                    q = _F(_F(_F(abs(_F(o)) * _F(3439.0)) + _F(abs(_F(p)) * _F(147.0))) % _F(13.0)) + _F(9.0)
                    g, f = _F(k - m * 2), _F(l - n * 2)
                    v = _F(_F(100.0) - _F(_F(math.sqrt(float(_F(_F(g * g) + _F(f * f))))) * q))
                    v = min(max(v, _F(-100.0)), _F(80.0))
                    h = max(h, v)
        return float(h)

    def columns(self, cx: int, cz: int) -> np.ndarray:
        """[3, 3, 33] densities of the chunk's noise columns."""
        return self.grid(cx * 2 + np.arange(3), cz * 2 + np.arange(3))

    def grid(self, xs, zs) -> np.ndarray:
        """[len(xs), len(zs), 33] densities of the noise columns xs x zs."""
        xs, zs = [int(v) for v in xs], [int(v) for v in zs]
        X = np.asarray(xs)[:, None, None].astype(np.float64)
        Z = np.asarray(zs)[None, :, None].astype(np.float64)
        Y = np.arange(33)[None, None, :].astype(np.float64)
        X, Z, Y = np.broadcast_arrays(X, Z, Y)
        n = self.noise.sample(X, Y, Z)
        if self.legacy:
            isl = np.array([[self.height_value(a, b) for b in zs] for a in xs])
            n = n - (8.0 - isl[:, :, None])
            t = (Y - 14.0) / 64.0
            n = np.where(Y > 14.0, np.where(t > 1.0, -3000.0, n + t * (-3000.0 - n)), n)
            t = (8.0 - Y) / 7.0
            return np.where(Y < 8.0, np.where(t > 1.0, -30.0, n + t * (-30.0 - n)), n)
        depth = np.array([[float(_F(_F(self.height_value(a, b)) - _F(8.0))) for b in zs] for a in xs])[:, :, None]
        factor = np.where(depth > 0.0, 0.25, 1.0)
        v = (0.0 + depth) * factor
        n = n + np.where(v > 0.0, v * 4.0, v)
        n = _clamped_lerp(-3000.0, n, ((32.0 - Y) - -46.0) / 64.0)
        return _clamped_lerp(-30.0, n, (Y - 1.0) / 7.0)

    def chunk(self, cx: int, cz: int, lift=None):
        d = density_blocks(self.columns(cx, cz), 8, 4)
        return np.where(d > 0.0, END_STONE, 0).astype(np.uint8), np.full((16, 16), SKY, np.uint8)
