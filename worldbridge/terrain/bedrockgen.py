"""Terrain of Bedrock's overworld before 1.18 (Bedrock Dedicated Server 1.6 - 1.17): the generator the ring of a
Bedrock 1.6 - 1.17 target is made with.

    gen = BedrockGenerator(seed, version=(1, 16))
    blocks, biomes, data = gen.chunk(cx, cz, lift=None)      # [x, z, y] Java 1.12 ids, [x, z] biome ids, [x, z, y]

The pieces, each reproducing the game bit for bit in a default (non-experimental) infinite world:

* ``bedrockbiomes``: the biome graph (the same in every version);
* this module: the 5 x 5 x 17 density cells of the chunk (``Terrain.density``: four noises, the biomes' depth and
  scale blended over 3 x 3 lattice points, the ceiling slide) and their trilinear expansion to 16 x 128 x 16 blocks
  of stone, water (below y 63) and air;
* ``bedrocksurface``: the bedrock floor and the biomes' surfaces.

Caves, ravines, ores, lakes, structures and trees are not made here: the game adds them.

Versions.  The terrain and the biomes were measured identical in every version from 1.6 to 1.17 (``VERIFIED``);
only the container changes in 1.17 (a 16 x 320 x 16 volume with air above y 127 and a 5 x 5 x 41 density buffer
whose levels above 16 are -100000), which does not change a block.  To add a version, extend ``VERSION_PARAMS``
if it differs, and widen ``FIRST_VERSION`` / ``END_VERSION``.
"""

from __future__ import annotations

from typing import Optional, Tuple

import numpy as np

from .bedrockbiomes import BedrockBiomes
from .bedrockdata import BIOME_HEIGHT, HEIGHT_PROFILES
from .bedrocknoise import OverworldNoises
from .bedrocksurface import SurfaceBuilder, to_java

F = np.float32
SEA_LEVEL = 63                       # water below this y
VOLUME = 128                         # blocks of the generator's own terrain
AIR, STONE, WATER = 0, 1, 2          # the terrain pass' volume

# Bedrock releases the generator reproduces: FIRST_VERSION <= version < END_VERSION (the generator of 1.18 is another)
FIRST_VERSION = (1, 6, 0)
END_VERSION = (1, 18, 0)
VERIFIED = ((1, 6), (1, 10), (1, 12), (1, 14), (1, 16), (1, 17))     # (major, minor) measured against the game
# what a release changes in how the terrain is stored, by (major, minor); the first entry not above a version counts
VERSION_PARAMS = {
    (1, 6): dict(volume_height=128, levels=17),
    (1, 17): dict(volume_height=320, levels=41),
}


def _key(version) -> Optional[Tuple[int, int, int]]:
    try:
        v = tuple(int(x) for x in version)
    except (TypeError, ValueError):
        return None
    return (v + (0, 0, 0))[:3] if v else None


def supports(version) -> bool:
    """The generator reproduces the overworld of Bedrock ``version`` (a tuple such as (1, 16, 40))."""
    v = _key(version)
    return v is not None and FIRST_VERSION <= v < END_VERSION


def version_params(version) -> dict:
    v = _key(version)
    if not supports(version):
        raise ValueError("Bedrock %s is not supported by the old overworld generator" % (version,))
    best = max(k for k in VERSION_PARAMS if k <= v[:2])
    return VERSION_PARAMS[best]


# ------------------------------------------------------------------------------------------------ biome heights
def _height_tables() -> Tuple[np.ndarray, np.ndarray]:
    depth, scale = np.zeros(256, np.float32), np.zeros(256, np.float32)
    for i, h in BIOME_HEIGHT.items():
        d, s = HEIGHT_PROFILES[h] if isinstance(h, str) else h
        depth[i], scale[i] = d, s
    return depth, scale


DEPTH, SCALE = _height_tables()

# the noise scales (float32 constants of the game)
_MAIN_SCALE = (8.555150032043457, 4.277575016021729, 8.555150032043457)
_MIN_SCALE = (684.4119873046875, 855.5150146484375, 684.4119873046875)
_MAX_SCALE = (684.4119873046875, 684.4119873046875, 684.4119873046875)


def _clamped_lerp(a, b, t):
    """a below t = 0, b above t = 1, else a + (b - a) t."""
    return np.where(t < F(0.0), a, np.where(t > F(1.0), b, (b - a) * t + a))


class Terrain:
    """The density field and the stone / water / air volume of a chunk."""

    def __init__(self, noises: OverworldNoises):
        self.noises = noises
        # blending kernel over the 3 x 3 lattice points: 10 / sqrt(dx^2 + dz^2 + 0.2), index (dz + 1) * 3 + dx + 1
        w = np.zeros(9, np.float32)
        for q in range(9):
            dz, dx = q // 3 - 1, q % 3 - 1
            w[q] = F(10.0) / np.sqrt(F(dx * dx + dz * dz) + F(0.2), dtype=np.float32)
        self.kernel = w

    def _blend(self, depth: np.ndarray, scale: np.ndarray, i: int, k: int):
        """Depth and scale of density column (i, k): the 3 x 3 biome lattice points around it (centred on
        point (i + 1, k + 1)), each weighted by the kernel over (its depth + 2), halved where the centre is deeper
        than the point; the sums add the taps with x outer, z inner."""
        centre = depth[i + 1, k + 1]
        sd = ss = sw = None
        for xo in range(3):
            for zo in range(3):
                nd = depth[i + xo, k + zo]
                w = self.kernel[zo * 3 + xo] / (nd + F(2.0))
                if (xo, zo) != (1, 1) and centre < nd:
                    w = w * F(0.5)
                td, ts = w * nd, w * scale[i + xo, k + zo]
                sd, ss, sw = (td, ts, w) if sd is None else (sd + td, ss + ts, sw + w)
        return sd / sw, ss / sw

    def density(self, cx: int, cz: int, depth: np.ndarray, scale: np.ndarray) -> np.ndarray:
        """The 5 x 5 x 17 density cells [x, z, level] (8 blocks per level).  ``depth`` and ``scale``: the biomes'
        floats on the 7 x 7 lattice of points at blocks (cx * 16 - 2 + 4 i, cz * 16 - 2 + 4 j)."""
        n = self.noises
        X, Z = cx * 4, cz * 4
        depth_n = n.depth.region2(X, Z, 5, 5, 200.0, 200.0)
        main_n = n.main.region3((X, 0, Z), 5, 17, 5, _MAIN_SCALE)
        min_n = n.min_limit.region3((X, 0, Z), 5, 17, 5, _MIN_SCALE)
        max_n = n.max_limit.region3((X, 0, Z), 5, 17, 5, _MAX_SCALE)
        out = np.zeros((5, 5, 17), np.float32)
        level = np.arange(17, dtype=np.float32)
        lv = np.arange(17)
        for i in range(5):
            for k in range(5):
                bd, bs = self._blend(depth, scale, i, k)
                sc = bs * F(0.9) + F(0.1)
                dn = depth_n[i, k] / F(8000.0)
                dn = (dn * F(-0.3) if dn < F(0.0) else dn) * F(3.0) + F(-2.0)
                if dn >= F(0.0):
                    off = min(dn, F(1.0)) * F(0.125)
                else:
                    off = (max(dn * F(0.5), F(-1.0)) / F(1.4)) * F(0.5)
                base = (((bd * F(4.0) + F(-1.0)) * F(0.125) + off * F(0.2)) * F(8.5) * F(0.5)) + F(8.5)
                t = (level - base) * (F(12.0) / sc)
                t = np.where(t < F(0.0), t * F(4.0), t)
                w = (main_n[i, k] / F(10.0) + F(1.0)) * F(0.5)
                d = _clamped_lerp(min_n[i, k] * F(0.00390625), max_n[i, k] * F(0.001953125), w) - t
                top = 13                                           # the ceiling slide starts at level 13
                f = (lv - top).astype(np.float32) / F(3.0)
                d = np.where((lv > top) & (lv < top + 4), d * (F(1.0) - f) + f * F(-10.0), d)
                out[i, k] = np.where(lv >= top + 4, F(-10.0), d).astype(np.float32)
        return out

    @staticmethod
    def expand(cells: np.ndarray) -> np.ndarray:
        """[16, 16, 128] densities from the cells.  The game interpolates by repeated float additions (along y
        8 steps per level, then x and z 4 per cell), not by a formula per block, and so does this."""
        q, h = F(0.25), F(0.125)

        def corner(dx, dz):
            return cells[dx:dx + 4, dz:dz + 4, :16]

        def rise(dx, dz):
            return (cells[dx:dx + 4, dz:dz + 4, 1:] - cells[dx:dx + 4, dz:dz + 4, :16]) * h

        p0, p1, q0, q1 = corner(0, 0).copy(), corner(0, 1).copy(), corner(1, 0).copy(), corner(1, 1).copy()
        r0, r1, s0, s1 = rise(0, 0), rise(0, 1), rise(1, 0), rise(1, 1)
        vals = np.empty((4, 4, 16, 8, 4, 4), np.float32)           # xc, zc, yc, y step, x step, z step
        for m in range(8):
            dx0, dx1 = (q0 - p0) * q, (q1 - p1) * q
            a, b = p0.copy(), p1.copy()
            for xs in range(4):
                s = (b - a) * q
                u = (a - s) + s
                for zs in range(4):
                    vals[:, :, :, m, xs, zs] = u
                    u = u + s
                a = a + dx0
                b = b + dx1
            p0, p1, q0, q1 = p0 + r0, p1 + r1, q0 + s0, q1 + s1
        return vals.transpose(0, 4, 1, 5, 2, 3).reshape(16, 16, 128)

    @staticmethod
    def volume(field: np.ndarray) -> np.ndarray:
        """Stone where the density is positive, water below the sea level, else air (uint8 AIR / STONE / WATER)."""
        y = np.arange(field.shape[2])[None, None, :]
        return np.where(field > 0.0, STONE, np.where(y < SEA_LEVEL, WATER, AIR)).astype(np.uint8)


# The ring travels through the Java 1.12 numeric format (the hub Amulet translates from), which has only the biomes
# 0 - 39: the others come out as plains.  The generator hands the ring the nearest of those, and the ring's chunks
# get their exact Bedrock biomes back after the translation (``restore_biomes``).
_NEAREST = {40: 0, 41: 24, 42: 0, 43: 24, 44: 0, 45: 24, 46: 10, 47: 10, 48: 21, 49: 22, 129: 1, 130: 2, 131: 3,
            132: 4, 133: 5, 134: 6, 140: 12, 149: 21, 151: 23, 155: 27, 156: 28, 157: 29, 158: 30, 160: 32, 161: 33,
            162: 34, 163: 35, 164: 36, 165: 37, 166: 38, 167: 39}
_HUB = np.arange(256, dtype=np.uint8)
for _b, _h in _NEAREST.items():
    _HUB[_b] = _h
# the hub's frozen ocean (10) is Bedrock's frozen_ocean (46) once translated
_TRANSLATED = _HUB.copy()
_TRANSLATED[10] = 46
_TRANSLATED[_HUB == 10] = 46


def restore_biomes(stored: np.ndarray, exact: np.ndarray) -> np.ndarray:
    """The biomes of a ring chunk once Amulet has translated it: ``stored`` (what came out of the hub) where it is
    not the translation of ``exact`` (the ring changed it: land biomes under the sea), else ``exact``."""
    stored = np.asarray(stored)
    return np.where(stored == _TRANSLATED[exact], exact, stored).astype(stored.dtype)


class BedrockGenerator:
    """The overworld generator for the ring: ``chunk(cx, cz, lift=None)`` -> (blocks [x, z, y] uint8 Java 1.12
    ids, biomes [x, z] Java ids, data [x, z, y]), the chunk as the game makes it before its caves, ravines and
    decoration.  ``lift`` [x, z]: blocks to move the terrain up or down (the density field is sampled lower or
    higher, so the ring's ground follows the game's shape)."""

    sea = SEA_LEVEL - 1                    # y of the sea surface (the highest water block)

    def __init__(self, seed: int, version=(1, 16)):
        if not supports(version):
            raise ValueError("Bedrock %s is not supported by the old overworld generator" % (version,))
        self.version = tuple(version)
        self.params = version_params(version)
        self.seed = seed & 0xFFFFFFFF                     # the game takes the level seed as an unsigned 32-bit number
        self.noises = OverworldNoises(self.seed)
        self.biome_source = BedrockBiomes(self.seed)
        self.terrain = Terrain(self.noises)
        self.surface = SurfaceBuilder(self.seed, self.noises)

    # ---------------------------------------------------------- the stages
    def biome_grid(self, cx: int, cz: int) -> np.ndarray:
        """[25, 25] Bedrock biome ids [z, x] of the blocks (cx * 16 - 2 .. cx * 16 + 22, same for z): the 16 x 16
        of the chunk are the middle, the terrain reads every 4th one."""
        return self.biome_source.area(cx * 16 - 2, cz * 16 - 2, 25, 25)

    def field(self, cx: int, cz: int, grid: Optional[np.ndarray] = None) -> np.ndarray:
        """[16, 16, 128] float32 density of the chunk."""
        g = self.biome_grid(cx, cz) if grid is None else grid
        lattice = g[::4, ::4].T                           # [x, z] of the 7 x 7 points
        cells = self.terrain.density(cx, cz, DEPTH[lattice], SCALE[lattice])
        return self.terrain.expand(cells)

    def chunk_bedrock(self, cx: int, cz: int, lift: Optional[np.ndarray] = None):
        """(palette codes [x, z, y], Bedrock biome ids [x, z]) of the chunk; 128 high unless a lift raises the
        ground above that."""
        from .lift import lifted_rock

        grid = self.biome_grid(cx, cz)
        biomes = grid[2:18, 2:18].T.astype(np.int64)
        field = self.field(cx, cz, grid)
        volume = self.terrain.volume(field)
        if lift is not None and bool(np.any(lift)):
            moved = lifted_rock(field, lift, SEA_LEVEL - 1, height=256)      # 1 stone, 9 water in its result
            moved = np.where(moved == 9, WATER, moved).astype(np.uint8)
            keep = np.asarray(lift) == 0
            moved[keep, :VOLUME] = volume[keep]
            moved[keep, VOLUME:] = AIR
            volume = moved if moved[:, :, VOLUME:].any() else moved[:, :, :VOLUME]
        return self.surface.build(volume, biomes, cx, cz), biomes

    def biomes(self, cx: int, cz: int) -> np.ndarray:
        """[x, z] Bedrock biome ids of the chunk."""
        return self.biome_source.area(cx * 16, cz * 16, 16, 16).T.astype(np.uint8)

    def chunk(self, cx: int, cz: int, lift: Optional[np.ndarray] = None):
        codes, biomes = self.chunk_bedrock(cx, cz, lift)
        blocks, data = to_java(codes)
        return blocks, _HUB[biomes], data
