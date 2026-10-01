"""Terrain generator of Minecraft Java 1.7 - 1.12 (ChunkProviderGenerate / ChunkProviderOverworld),
for the ring of terrain WorldBridge writes around a converted world (see ring.py).

Code read from the 1.7.10 and 1.12.2 jars:

* the density is 5 x 5 x 33 (256 blocks high), from the biomes' depth and scale weighted over 5 x 5
  samples; from 1.8 its settings are floats (ChunkProviderSettings), which shifts the noise a hair;
  the "Amplified" world type raises and stretches every land biome;
* the surface is each biome's genTerrainBlocks: the default one (grass or the biome's top block,
  dirt below, gravel on deep sea floors, sandstone under sand) and the overrides of the extreme
  hills (stone and gravel), mega taiga (podzol, coarse dirt), shattered savanna, swamp (puddles and
  lily pads) and mesa (clay bands, red sand, bryce pillars).  As in the game, the column's x and z
  are passed swapped inside the chunk to the noises of the surface;
* caves and ravines: carvers.py with the 256-high world (caves rarer than in 1.6, from 1.8 cutting
  through sandstone, clay, sand and gravel too).

Biomes: layers17.
"""

from __future__ import annotations

import math
from typing import Tuple

import numpy as np

from .betagen import BEDROCK, DIRT, GRASS, GRAVEL, ICE, SAND, SANDSTONE, STONE, WATER, JavaRandom, PerlinOctaves, \
    Simplex, SimplexOctaves, _s64
from .layers17 import Stack17
from .carvers import chunk_top_of as _chunk_top_of
from .lift import density_field, lifted_rock, move_caves
from .neogen import _Mesa, _octaves

_F = np.float32
SEA_LEVEL = 63
HEIGHT = 256
MYCELIUM, LILY, SNOW_BLOCK, STAINED_CLAY, HARDENED_CLAY, RED_SANDSTONE = 110, 111, 80, 159, 172, 179
VERSIONS = ("1.7", "1.8", "1.9", "1.10", "1.11", "1.12")

# Biome registry of 1.12 (the same values as 1.7): id -> (depth, scale, temperature)
_BIOMES = {
    0: (-1.0, 0.1, 0.5), 1: (0.125, 0.05, 0.8), 2: (0.125, 0.05, 2.0), 3: (1.0, 0.5, 0.2), 4: (0.1, 0.2, 0.7),
    5: (0.2, 0.2, 0.25), 6: (-0.2, 0.1, 0.8), 7: (-0.5, 0.0, 0.5), 10: (-1.0, 0.1, 0.0), 11: (-0.5, 0.0, 0.0),
    12: (0.125, 0.05, 0.0), 13: (0.45, 0.3, 0.0), 14: (0.2, 0.3, 0.9), 15: (0.0, 0.025, 0.9), 16: (0.0, 0.025, 0.8),
    17: (0.45, 0.3, 2.0), 18: (0.45, 0.3, 0.7), 19: (0.45, 0.3, 0.25), 20: (0.8, 0.3, 0.2), 21: (0.1, 0.2, 0.95),
    22: (0.45, 0.3, 0.95), 23: (0.1, 0.2, 0.95), 24: (-1.8, 0.1, 0.5), 25: (0.1, 0.8, 0.2), 26: (0.0, 0.025, 0.05),
    27: (0.1, 0.2, 0.6), 28: (0.45, 0.3, 0.6), 29: (0.1, 0.2, 0.7), 30: (0.2, 0.2, -0.5), 31: (0.45, 0.3, -0.5),
    32: (0.2, 0.2, 0.3), 33: (0.45, 0.3, 0.3), 34: (1.0, 0.5, 0.2), 35: (0.125, 0.05, 1.2), 36: (1.5, 0.025, 1.0),
    37: (0.1, 0.2, 2.0), 38: (1.5, 0.025, 2.0), 39: (1.5, 0.025, 2.0),
    129: (0.125, 0.05, 0.8), 130: (0.225, 0.25, 2.0), 131: (1.0, 0.5, 0.2), 132: (0.1, 0.4, 0.7),
    133: (0.3, 0.4, 0.25), 134: (-0.1, 0.3, 0.8), 140: (0.425, 0.45000002, 0.0), 149: (0.2, 0.4, 0.95),
    151: (0.2, 0.4, 0.95), 155: (0.2, 0.4, 0.6), 156: (0.55, 0.5, 0.6), 157: (0.2, 0.4, 0.7), 158: (0.3, 0.4, -0.5),
    160: (0.2, 0.2, 0.25), 161: (0.2, 0.2, 0.25), 162: (1.0, 0.5, 0.2), 163: (0.3625, 1.225, 1.1),
    164: (1.05, 1.2125001, 1.0), 165: (0.1, 0.2, 2.0), 166: (0.45, 0.3, 2.0), 167: (0.45, 0.3, 2.0)}
# the oceans of 1.13+ (the 1.13 generator uses this density with them)
_BIOMES.update({44: (-1.0, 0.1, 0.5), 45: (-1.0, 0.1, 0.5), 46: (-1.0, 0.1, 0.5), 47: (-1.8, 0.1, 0.5),
                48: (-1.8, 0.1, 0.5), 49: (-1.8, 0.1, 0.5), 50: (-1.8, 0.1, 0.5)})
_DEFAULT = (0.1, 0.2, 0.5)

# top (id, data), filler (id, data) of the biomes that are not grass over dirt
_MATERIALS = {b: ((SAND, 0), (SAND, 0)) for b in (2, 16, 17, 26, 130)}
_MATERIALS.update({25: ((STONE, 0), (STONE, 0)), 14: ((MYCELIUM, 0), (DIRT, 0)), 15: ((MYCELIUM, 0), (DIRT, 0)),
                   140: ((SNOW_BLOCK, 0), (DIRT, 0))})
_GRASS = ((GRASS, 0), (DIRT, 0))
_HILLS = {3: "normal", 20: "trees", 34: "trees", 131: "mutated", 162: "mutated"}
_MEGA_TAIGA = {32, 33, 160, 161}
_SHATTERED = {163, 164}
_SWAMP = {6, 134}
_MESA = {37: (False, False), 38: (False, True), 39: (False, False), 165: (True, False), 166: (False, True),
         167: (False, False)}                     # id: (bryce pillars, trees on top)
_ORANGE = (STAINED_CLAY, 1)
_WHITE = (STAINED_CLAY, 0)


class ModernGenerator:
    """``chunk(cx, cz, lift=None)`` -> (blocks [x, z, y], biomes [x, z], data [x, z, y])."""

    def __init__(self, seed: int, version: str = "1.12", caves: bool = True, large_biomes: bool = False,
                 amplified: bool = False):
        from .carvers import ReleaseCarvers

        self.seed = _s64(seed)
        self.version = version
        self.minor = int(version.split(".")[1])
        self.caves = caves
        self.amplified = amplified
        self.carvers = ReleaseCarvers(self.seed, modern=True, wide=self.minor >= 8)
        self.stack = Stack17(version, self.seed, large_biomes)
        r = JavaRandom(self.seed)
        self.n_min = PerlinOctaves(r, 16)
        self.n_max = PerlinOctaves(r, 16)
        self.n_main = PerlinOctaves(r, 8)
        self.n_surface = SimplexOctaves(r, 4)
        PerlinOctaves(r, 10)                                   # (the old "scale" noise, unused)
        self.n_depth = PerlinOctaves(r, 16)
        pf = np.zeros(25, np.float32)
        for i in range(-2, 3):
            for j in range(-2, 3):
                pf[i + 2 + (j + 2) * 5] = _F(10.0) / np.sqrt(_F(i * i + j * j) + _F(0.2), dtype=np.float32)
        self.pf = pf
        if self.minor >= 8:
            # ChunkProviderSettings: floats, the divisions too
            coord = float(_F(684.412))
            self.scales = (coord, coord, float(_F(_F(684.412) / _F(80.0))), float(_F(_F(684.412) / _F(160.0))))
        else:
            self.scales = (684.412, 684.412, 684.412 / 80.0, 684.412 / 160.0)
        self.grass_noise = [Simplex(JavaRandom(2345))]       # Biome.GRASS_COLOR_NOISE (the swamp's puddles)
        self._mesa = None

    # ---------------------------------------------------------- density
    def _density(self, cx: int, cz: int, b4: np.ndarray) -> np.ndarray:
        x, z = cx * 4, cz * 4
        coord, height, main_xz, main_y = self.scales
        depth = self.n_depth.noise2d(x, z, 5, 5, 200.0, 200.0)
        main = self.n_main.noise(x, 0, z, 5, 33, 5, main_xz, main_y, main_xz)
        lo = self.n_min.noise(x, 0, z, 5, 33, 5, coord, height, coord)
        hi = self.n_max.noise(x, 0, z, 5, 33, 5, coord, height, coord)
        out = np.empty((5, 5, 33))
        k = np.arange(33, dtype=np.float64)
        fade = ((k - 29) / 3.0).astype(np.float32).astype(np.float64)
        for i in range(5):
            for j in range(5):
                f = f1 = f2 = _F(0)
                c_depth = _F(_BIOMES.get(int(b4[j + 2, i + 2]), _DEFAULT)[0])
                for di in range(-2, 3):
                    for dj in range(-2, 3):
                        d, s, _t = _BIOMES.get(int(b4[j + dj + 2, i + di + 2]), _DEFAULT)
                        d, s = _F(d), _F(s)
                        if self.amplified and d > 0:
                            d = _F(_F(1.0) + _F(d * _F(2.0)))
                            s = _F(_F(1.0) + _F(s * _F(4.0)))
                        w = _F(self.pf[di + 2 + (dj + 2) * 5] / _F(d + _F(2.0)))
                        if _F(_BIOMES.get(int(b4[j + dj + 2, i + di + 2]), _DEFAULT)[0]) > c_depth:
                            w = _F(w / _F(2.0))
                        f = _F(f + _F(s * w))
                        f1 = _F(f1 + _F(d * w))
                        f2 = _F(f2 + w)
                f = _F(_F(f / f2) * _F(0.9) + _F(0.1))
                f1 = _F(_F(_F(f1 / f2) * _F(4.0) - _F(1.0)) / _F(8.0))
                d2 = depth[i, j] / 8000.0
                if d2 < 0.0:
                    d2 = -d2 * 0.3
                d2 = d2 * 3.0 - 2.0
                if d2 < 0.0:
                    d2 /= 2.0
                    if d2 < -1.0:
                        d2 = -1.0
                    d2 /= 1.4
                    d2 /= 2.0
                else:
                    if d2 > 1.0:
                        d2 = 1.0
                    d2 /= 8.0
                d3 = float(f1) + d2 * 0.2
                d3 = d3 * 8.5 / 8.0
                center = 8.5 + d3 * 4.0
                off = (k - center) * 12.0 * 128.0 / 256.0 / float(f)
                off = np.where(off < 0.0, off * 4.0, off)
                a = lo[i, j] / 512.0
                b = hi[i, j] / 512.0
                t = (main[i, j] / 10.0 + 1.0) / 2.0
                v = np.where(t < 0.0, a, np.where(t > 1.0, b, a + (b - a) * t)) - off
                out[i, j] = np.where(k > 29, v * (1.0 - fade) + -10.0 * fade, v)
        return out

    @staticmethod
    def _terrain(q: np.ndarray) -> np.ndarray:
        """Stone, water and air from the density, interpolated as the game does (the same additions)."""
        blocks = np.zeros((16, 16, HEIGHT), np.uint8)
        for k1 in range(32):
            d1, d2, d3, d4 = q[:4, :4, k1], q[:4, 1:, k1], q[1:, :4, k1], q[1:, 1:, k1]
            d5 = (q[:4, :4, k1 + 1] - d1) * 0.125
            d6 = (q[:4, 1:, k1 + 1] - d2) * 0.125
            d7 = (q[1:, :4, k1 + 1] - d3) * 0.125
            d8 = (q[1:, 1:, k1 + 1] - d4) * 0.125
            for l1 in range(8):
                y = k1 * 8 + l1
                d10, d11 = d1.copy(), d2.copy()
                d12 = (d3 - d1) * 0.25
                d13 = (d4 - d2) * 0.25
                for i2 in range(4):
                    d16 = (d11 - d10) * 0.25
                    d15 = d10 - d16
                    for k2 in range(4):
                        d15 = d15 + d16
                        # x = i1 * 4 + i2, z = j1 * 4 + k2 of every cell (i1, j1)
                        blocks[i2::4, k2::4, y] = np.where(d15 > 0.0, STONE, WATER if y < SEA_LEVEL else 0)
                    d10 = d10 + d12
                    d11 = d11 + d13
                d1, d2, d3, d4 = d1 + d5, d2 + d6, d3 + d7, d4 + d8
        return blocks

    # ---------------------------------------------------------- surface
    def _surface(self, cx: int, cz: int, blocks: np.ndarray, data: np.ndarray, b1: np.ndarray, rnd: JavaRandom):
        noise = self.n_surface.noise(cx * 16, cz * 16, 16, 16, 0.0625 * 1.5, 0.0625 * 1.5, 0.5, 0.5)
        for lz in range(16):
            for lx in range(16):
                bid = int(b1[lz, lx])
                n = float(noise[lx, lz])
                wx, wz = cx * 16 + lz, cz * 16 + lx             # (swapped, as the game)
                col = blocks[lx, lz].tolist()
                dcol = [0] * len(col)
                if bid in _MESA:
                    self._mesa_column(bid, col, dcol, n, wx, wz, rnd)
                else:
                    self._column(bid, col, dcol, n, wx, wz, rnd)
                blocks[lx, lz] = col
                data[lx, lz] = dcol

    def _materials(self, bid, n):
        top, fill = _MATERIALS.get(bid, _GRASS)
        kind = _HILLS.get(bid)
        if kind is not None:
            top, fill = _GRASS
            if (n < -1.0 or n > 2.0) and kind == "mutated":
                top = fill = (GRAVEL, 0)
            elif n > 1.0 and kind != "trees":
                top = fill = (STONE, 0)
        elif bid in _MEGA_TAIGA:
            top, fill = _GRASS
            if n > 1.75:
                top = (DIRT, 1)                          # coarse dirt
            elif n > -0.95:
                top = (DIRT, 2)                          # podzol
        elif bid in _SHATTERED:
            top, fill = _GRASS
            if n > 1.75:
                top = fill = (STONE, 0)
            elif n > -0.5:
                top = (DIRT, 1)
        return top, fill

    def _column(self, bid, col, dcol, n, wx, wz, rnd):
        top0, fill0 = self._materials(bid, n)
        # 1.7's swamp stops at the first null (air) block of its array, at the top: no puddles before 1.8
        if bid in _SWAMP and self.minor >= 8:
            v = _octaves(self.grass_noise, wx * 0.25, wz * 0.25)
            if v > 0.0:
                for y in range(len(col) - 1, -1, -1):
                    if col[y] != 0:
                        if y == 62 and col[y] != WATER:
                            col[y] = WATER
                            if v < 0.12:
                                col[y + 1] = LILY
                        break
        top, fill = top0, fill0
        run = -1
        k = int(n / 3.0 + 3.0 + rnd.next_double() * 0.25)
        cold = _BIOMES.get(bid, _DEFAULT)[2] < 0.15
        modern_sand = self.minor >= 8
        seed = rnd.seed                          # rnd.next_int(5) of every block, inlined
        for y in range(len(col) - 1, -1, -1):
            seed = (seed * 0x5DEECE66D + 0xB) & 0xFFFFFFFFFFFF
            bits = seed >> 17
            val = bits % 5
            if bits - val + 4 >= 2147483648:     # rejected draw (1 in 400 million): the loop goes on
                rnd.seed = seed
                val = rnd.next_int(5)
                seed = rnd.seed
            if y <= val:
                col[y], dcol[y] = BEDROCK, 0
                continue
            cur = col[y]
            if cur == 0:
                run = -1
            elif cur == STONE:
                if run == -1:
                    if k <= 0:
                        top, fill = (0, 0), (STONE, 0)
                    elif SEA_LEVEL - 4 <= y <= SEA_LEVEL + 1:
                        top, fill = top0, fill0
                    if y < SEA_LEVEL and top[0] == 0:
                        top = (ICE, 0) if cold else (WATER, 0)
                    run = k
                    if y >= SEA_LEVEL - 1:
                        col[y], dcol[y] = top
                    elif y < SEA_LEVEL - 7 - k:
                        top, fill = (0, 0), (STONE, 0)
                        col[y], dcol[y] = GRAVEL, 0
                    else:
                        col[y], dcol[y] = fill
                elif run > 0:
                    run -= 1
                    col[y], dcol[y] = fill
                    if run == 0 and fill[0] == SAND and (k > 1 or not modern_sand):
                        rnd.seed = seed
                        run = rnd.next_int(4) + max(0, y - 63)
                        seed = rnd.seed
                        fill = (RED_SANDSTONE, 0) if fill[1] == 1 and modern_sand else (SANDSTONE, 0)
        rnd.seed = seed

    def _mesa_column(self, bid, col, dcol, n, wx, wz, rnd):
        if self._mesa is None:
            self._mesa = _Mesa(self.seed, java=True)
        m = self._mesa
        bryce, trees = _MESA[bid]
        pillar = 0.0
        if bryce:
            px = (wx & ~15) + (wz & 15)
            pz = (wz & ~15) + (wx & 15)
            d0 = min(abs(n), _octaves(m.pillar, px * 0.25, pz * 0.25))
            if d0 > 0.0:
                d1 = abs(_octaves(m.pillar_roof, px * 0.001953125, pz * 0.001953125))
                pillar = min(d0 * d0 * 2.5, math.ceil(d1 * 50.0) + 14.0) + 64.0
        fill = _WHITE
        k = int(n / 3.0 + 3.0 + rnd.next_double() * 0.25)
        cos_flag = math.cos(n / 3.0 * math.pi) > 0.0
        run = -1
        red_sand = False
        count = 0
        for y in range(len(col) - 1, -1, -1):
            if col[y] == 0 and y < int(pillar):
                col[y] = STONE
            if y <= rnd.next_int(5):
                col[y], dcol[y] = BEDROCK, 0
                continue
            if count >= 15 and not bryce:
                continue
            cur = col[y]
            if cur == 0:
                run = -1
                continue
            if cur != STONE:
                continue
            if run == -1:
                red_sand = False
                if k <= 0:
                    fill = (STONE, 0)
                elif SEA_LEVEL - 4 <= y <= SEA_LEVEL + 1:
                    fill = _WHITE
                run = k + max(0, y - SEA_LEVEL)
                if y < SEA_LEVEL - 1:
                    col[y], dcol[y] = _ORANGE if fill[0] == STAINED_CLAY else fill
                elif not trees or y <= 86 + k * 2:
                    if y <= SEA_LEVEL + 3 + k:
                        col[y], dcol[y] = SAND, 1
                        red_sand = True
                    elif y < 64 or y > 127:
                        col[y], dcol[y] = _ORANGE
                    elif cos_flag:
                        col[y], dcol[y] = HARDENED_CLAY, 0
                    else:
                        col[y], dcol[y] = self._band(wx, y)
                elif cos_flag:
                    col[y], dcol[y] = DIRT, 1
                else:
                    col[y], dcol[y] = GRASS, 0
            elif run > 0:
                run -= 1
                col[y], dcol[y] = _ORANGE if red_sand else self._band(wx, y)
            count += 1

    def _band(self, x: int, y: int):
        v = _octaves(self._mesa.offset, x / 512.0, x / 512.0) * 2.0      # the game passes x twice
        return self._mesa.bands[(y + int(math.floor(v + 0.5)) + 64) % 64]

    # ---------------------------------------------------------- public
    def chunk(self, cx: int, cz: int, lift=None) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Blocks (x, z, y) uint8 of a freshly generated chunk, its biome ids (x, z) and the blocks'
        data (x, z, y).  ``lift`` [x, z]: blocks (fractions too) to move the terrain up (down if negative)."""
        seed = _s64(cx * 341873128712 + cz * 132897987541)
        b4 = self.stack.biomes4(cx * 4 - 2, cz * 4 - 2, 10, 10)
        b1 = self.stack.biomes(cx * 16, cz * 16, 16, 16)
        q = self._density(cx, cz, b4)
        blocks = self._terrain(q)
        data = np.zeros_like(blocks)
        self._surface(cx, cz, blocks, data, b1, JavaRandom(seed))
        lifted = lift is not None and bool(np.any(lift))
        before = blocks.copy() if lifted and self.caves else None
        if self.caves:
            self._carve(cx, cz, blocks, data, b1)
        if not lifted:
            return blocks, b1.T.copy(), data
        moved = lifted_rock(density_field(q), lift, SEA_LEVEL - 1)
        mdata = np.zeros_like(moved)
        self._surface(cx, cz, moved, mdata, b1, JavaRandom(seed))
        if before is not None:
            move_caves(moved, before, blocks, lift)
            mdata[np.isin(moved, (0, 10, 11))] = 0
        keep = np.asarray(lift) == 0                        # the game's own columns, exactly
        moved[keep] = blocks[keep]
        mdata[keep] = data[keep]
        return moved, b1.T.copy(), mdata

    def _carve(self, cx, cz, blocks, data, b1=None):
        before = blocks.copy()
        top_of = self._top_of if b1 is None else _chunk_top_of(b1, cx, cz, self._top_block, self._top_of)
        self.carvers.carve(cx, cz, blocks, top_of)
        data[(blocks != before)] = 0

    def _top_of(self, x: int, z: int) -> int:
        return self._top_block(int(self.stack.biomes(x, z, 1, 1)[0, 0]))

    @staticmethod
    def _top_block(b: int) -> int:
        if b in _MESA:
            return SAND
        return _MATERIALS.get(b, _GRASS)[0][0]
