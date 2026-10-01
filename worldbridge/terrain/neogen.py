"""Terrain generator of neoLegacy (the PC port of Legacy Console Edition), for the ring of terrain
WorldBridge writes around a world converted to LCE.

Code read from the neoLegacy source (Minecraft.World: RandomLevelSource, Biome and its subclasses,
LargeCaveFeature, CanyonFeature):

* the density is the one of Java 1.1 - 1.6 (5 x 5 x 17 noise, 128 blocks high), with the biome
  depth / scale of neoLegacy's Biome.cpp;
* 4J's edge of the map: in the last 32 blocks before the border the ground sinks into the sea (the
  density must beat a threshold growing up to 128), and the very last column is sea over stone;
* the surface is Biome::buildSurfaceAtDefault and its overrides (extreme hills gravel and stone,
  mega taiga podzol, swamp puddles, mesa clay bands and pillars), with 4J's bedrock (y <= 1 + 0..1);
* the caves and ravines are the ones of TU19, the same as Java 1.0 - 1.1 (carvers).

Biomes: neolayers.  Validated on a neoLegacy world (seed -3112930505348390392, 192 x 192 chunks):
biomes identical in every column; see docs/SEAMLESS_BORDERS.md for the terrain figures.
"""

from __future__ import annotations

import math
from typing import Optional, Tuple

import numpy as np

from .betagen import BEDROCK, DIRT, GRASS, GRAVEL, ICE, SAND, SANDSTONE, STONE, WATER, WATER_FLOWING, JavaRandom, \
    Perlin, PerlinOctaves, Simplex, _GRAD2, _F2, _G2, _s64
from .carvers import chunk_top_of as _chunk_top_of
from .lift import density_field, lifted_rock, move_caves
from .neolayers import NeoStack, _TEMP
from .releasegen import ReleaseGenerator

SEA_LEVEL = 63                      # water up to y 62
TALL = 256                          # blocks of an LCE world
MYCELIUM, LILY, SNOW_BLOCK, CLAY_STAINED, CLAY_HARDENED, RED_SANDSTONE = 110, 111, 80, 159, 172, 179
_F = np.float32

# Biome.cpp (and subclasses): depth, scale
_DEPTH_SCALE = {
    0: (-1, 0.4), 1: (0.1, 0.3), 2: (0.1, 0.2), 3: (0.3, 1.5), 4: (0.1, 0.3), 5: (0.1, 0.4), 6: (-0.2, 0.1),
    7: (-0.5, 0), 8: (0.1, 0.3), 9: (0.1, 0.3), 10: (-1, 0.5), 11: (-0.5, 0), 12: (0, 0.5), 13: (0.3, 1.3),
    14: (0.2, 1.0), 15: (-1, 0.1), 16: (0, 0.1), 17: (0.3, 0.8), 18: (0.3, 0.7), 19: (0.3, 0.8), 20: (0.2, 0.8),
    21: (0.2, 0.4), 22: (1.8, 0.5), 23: (0.1, 0.3), 24: (-1.8, 0.1), 25: (0.1, 0.8), 26: (0, 0.025), 27: (0.1, 0.3),
    28: (0.45, 0.3), 29: (0.1, 0.3), 30: (0.1, 0.4), 31: (0.3, 0.8), 32: (0.1, 0.4), 33: (0.3, 0.8), 34: (0.3, 1.5),
    35: (0.1, 0.3), 36: (1.5, 0.025), 37: (0.1, 0.3), 38: (1.5, 0.025), 39: (1.5, 0.025),
    129: (0.1, 0.3), 130: (0.225, 0.25), 131: (0.3, 1.5), 132: (0.1, 0.3), 133: (0.3, 0.4), 134: (-0.1, 0.3),
    140: (0.1, 0.3), 149: (0.2, 0.4), 151: (0.1, 0.3), 155: (0.2, 0.5), 156: (0.55, 0.5), 157: (0.2, 0.5),
    158: (0.3, 0.4), 160: (0.2, 0.2), 161: (0.2, 0.2), 162: (0.3, 1.5), 163: (0.35, 1.3), 164: (1.05, 1.2125),
    165: (0.1, 0.3), 166: (0.1, 0.3), 167: (0.1, 0.3)}

# top block, its data, filler, its data (the biome's own, before any override)
_MATERIALS = {b: (SAND, 0, SAND, 0) for b in (2, 16, 17, 26, 130)}
_MATERIALS.update({25: (STONE, 0, STONE, 0), 14: (MYCELIUM, 0, DIRT, 0), 15: (MYCELIUM, 0, DIRT, 0),
                   140: (SNOW_BLOCK, 0, DIRT, 0)})
_DEFAULT = (GRASS, 0, DIRT, 0)
_HILLS = {3: "normal", 20: "normal", 34: "trees", 131: "mutated", 162: "mutated"}
_MEGA_TAIGA = {32, 33, 160, 161}
_SWAMP = {6, 134}
_MESA = {37: (False, False), 38: (True, True), 39: (True, False), 165: (True, False), 166: (True, True),
         167: (True, False)}                      # id: (plateau, trees)
_MESA_BRYCE = 165
_BAND_ORANGE, _BAND_YELLOW, _BAND_BROWN, _BAND_RED, _BAND_WHITE, _BAND_SILVER = 1, 4, 12, 14, 0, 8


def _improved(n: Perlin, x: float, y: float, z: float) -> float:
    """ImprovedNoise::noise at one point."""
    x, y, z = x + n.xo, y + n.yo, z + n.zo
    xf, yf, zf = math.floor(x), math.floor(y), math.floor(z)
    X, Y, Z = xf & 255, yf & 255, zf & 255
    x, y, z = x - xf, y - yf, z - zf
    u, v, w = (t * t * t * (t * (t * 6 - 15) + 10) for t in (x, y, z))
    p = n.p

    def grad(h, a, b, c):
        h &= 15
        g1 = a if h < 8 else b
        g2 = b if h < 4 else (a if h in (12, 14) else c)
        return (-g1 if h & 1 else g1) + (-g2 if h & 2 else g2)

    def lerp(t, a, b):
        return a + t * (b - a)

    A = p[X] + Y
    AA, AB = p[A] + Z, p[A + 1] + Z
    B = p[X + 1] + Y
    BA, BB = p[B] + Z, p[B + 1] + Z
    return lerp(w, lerp(v, lerp(u, grad(p[AA], x, y, z), grad(p[BA], x - 1, y, z)),
                        lerp(u, grad(p[AB], x, y - 1, z), grad(p[BB], x - 1, y - 1, z))),
                lerp(v, lerp(u, grad(p[AA + 1], x, y, z - 1), grad(p[BA + 1], x - 1, y, z - 1)),
                     lerp(u, grad(p[AB + 1], x, y - 1, z - 1), grad(p[BB + 1], x - 1, y - 1, z - 1))))


def _simplex(s: Simplex, xin: float, yin: float) -> float:
    """SimplexNoise::getValue(x, y) (without the noise's offsets, as the game)."""
    def fastfloor(v):
        return int(v) if v > 0 else int(v) - 1

    t = (xin + yin) * _F2
    i, j = fastfloor(xin + t), fastfloor(yin + t)
    t = (i + j) * _G2
    x0, y0 = xin - (i - t), yin - (j - t)
    i1, j1 = (1, 0) if x0 > y0 else (0, 1)
    x1, y1 = x0 - i1 + _G2, y0 - j1 + _G2
    x2, y2 = x0 - 1.0 + 2.0 * _G2, y0 - 1.0 + 2.0 * _G2
    p = s.p
    ii, jj = i & 255, j & 255
    total = 0.0
    for g, a, b in ((p[ii + p[jj]] % 12, x0, y0), (p[ii + i1 + p[jj + j1]] % 12, x1, y1),
                    (p[ii + 1 + p[jj + 1]] % 12, x2, y2)):
        c = 0.5 - a * a - b * b
        if c >= 0:
            c *= c
            total += c * c * (_GRAD2[g, 0] * a + _GRAD2[g, 1] * b)
    return 70.0 * total


def _octaves(levels, x, y) -> float:
    """PerlinSimplexNoise::getValue(x, y)."""
    v, pw = 0.0, 1.0
    for s in levels:
        v += _simplex(s, x * pw, y * pw) / pw
        pw /= 2
    return v


class _Mesa:
    """MesaBiome's clay bands and pillars (generateBands, getBand)."""

    def __init__(self, seed: int, java: bool = False):
        r = JavaRandom(seed)
        self.offset = [Simplex(r)]
        bands = [(CLAY_HARDENED, 0)] * 64
        i = 0
        while i < 64:
            i += r.next_int(5) + 1
            if i < 64:
                bands[i] = (CLAY_STAINED, _BAND_ORANGE)
            if java:            # Java's for (i = 0; i < 64; i++) { i += nextInt(5) + 1; ...  (neoLegacy: while)
                i += 1
        for colour, extra in ((_BAND_YELLOW, 1), (_BAND_BROWN, 2), (_BAND_RED, 1)):
            for _ in range(r.next_int(4) + 2):
                n = r.next_int(3) + extra
                start = r.next_int(64)
                for k in range(n):
                    if start + k >= 64:
                        break
                    bands[start + k] = (CLAY_STAINED, colour)
        cursor = 0
        for _ in range(r.next_int(3) + 3):
            cursor += r.next_int(16) + 4
            if cursor >= 64:
                break
            bands[cursor] = (CLAY_STAINED, _BAND_WHITE)
            if cursor > 1 and r.next(1):
                bands[cursor - 1] = (CLAY_STAINED, _BAND_SILVER)
            if cursor < 63 and r.next(1):
                bands[cursor + 1] = (CLAY_STAINED, _BAND_SILVER)
        self.bands = bands
        r = JavaRandom(seed)
        self.pillar = [Simplex(r) for _ in range(4)]
        self.pillar_roof = [Simplex(r)]

    def band(self, x: int, y: int):
        v = _octaves(self.offset, x * 0.001953125, x * 0.001953125)       # the game passes x twice
        off = int(math.floor(abs(v + v) + 0.5)) * (1 if v + v >= 0 else -1)  # std::round
        return self.bands[(y + off + 64) % 64]


class NeoGenerator(ReleaseGenerator):
    """``chunk(cx, cz, lift=None)`` -> (blocks [x, z, y], biomes [x, z], data [x, z, y]).

    ``xz_size``: the map's width in chunks (the edge of the map sinks into the sea); ``offset``: the
    chunk of the target world is (cx - offset x, cz - offset z) (WorldBridge's chunk coordinates are
    the ones of the source world)."""

    def __init__(self, seed: int, xz_size: Optional[int] = None, large_biomes: bool = False, caves: bool = True,
                 offset: Tuple[int, int] = (0, 0)):
        from .carvers import ReleaseCarvers, lce_sin_table

        self.seed = _s64(seed)
        self.caves = caves
        self.carvers = ReleaseCarvers(self.seed, lce_sin_table(), msvc=True)
        self.stack = NeoStack(self.seed, large_biomes)
        self.table = {b: (d, s, _TEMP.get(b, 0.5)) for b, (d, s) in _DEPTH_SCALE.items()}
        r = JavaRandom(self.seed)
        self.n1 = PerlinOctaves(r, 16)
        self.n2 = PerlinOctaves(r, 16)
        self.n3 = PerlinOctaves(r, 8)
        self.n4 = PerlinOctaves(r, 4)
        self.n5 = PerlinOctaves(r, 10)
        self.n6 = PerlinOctaves(r, 16)
        pf = np.zeros(25, np.float32)
        for i in range(-2, 3):
            for j in range(-2, 3):
                pf[i + 2 + (j + 2) * 5] = _F(10.0) / np.sqrt(_F(i * i + j * j) + _F(0.2), dtype=np.float32)
        self.pf = pf
        self.world = xz_size * 16 if xz_size else None
        self.offset = offset
        self.swamp_noise = Perlin(JavaRandom(2345))
        self._mesa = None

    # ---------------------------------------------------------- the edge of the map
    def _falloff(self, tx: int, tz: int):
        """(threshold [x, z] the density must beat, columns on the very edge [x, z])."""
        if self.world is None:
            return np.zeros((16, 16), np.float32), np.zeros((16, 16), bool)
        half = self.world // 2
        xs = tx * 16 + np.arange(16)
        zs = tz * 16 + np.arange(16)
        ex = np.minimum(np.maximum(xs + half, 0), np.maximum(half - 1 - xs, 0))[:, None]
        ez = np.minimum(np.maximum(zs + half, 0), np.maximum(half - 1 - zs, 0))[None, :]
        emin = np.minimum(ex, ez)
        comp = np.where(emin < 32, (32 - emin).astype(np.float32) / _F(32) * _F(128), _F(0)).astype(np.float32)
        return comp, emin == 0

    @staticmethod
    def _edge_columns(blocks: np.ndarray, edge: np.ndarray) -> None:
        y = np.arange(blocks.shape[2])
        col = blocks[edge]
        col[:, y <= SEA_LEVEL - 10] = STONE
        col[:, (y > SEA_LEVEL - 10) & (y < SEA_LEVEL)] = WATER
        blocks[edge] = col

    def _rock(self, d: np.ndarray, comp: np.ndarray, edge: np.ndarray) -> np.ndarray:
        y = np.arange(d.shape[2])[None, None, :]
        blocks = np.where(d > comp[:, :, None], STONE, np.where(y < SEA_LEVEL, WATER, 0)).astype(np.uint8)
        self._edge_columns(blocks, edge)
        return blocks

    # ---------------------------------------------------------- surface
    def _surface(self, tx, tz, blocks, data, b1, rnd):
        d = 0.03125
        stone = self.n4.noise(tx * 16, tz * 16, 0.0, 16, 16, 1, d * 2.0, d * 2.0, d * 2.0)[:, 0, :].tolist()
        for k in range(16):          # z
            for l in range(16):      # x
                bid = int(b1[k, l])
                noise = stone[l][k]
                col = blocks[l, k].tolist()
                dcol = [0] * len(col)
                # the game passes the column's x and z swapped inside the chunk
                px, pz = tx * 16 + k, tz * 16 + l
                if bid in _MESA:
                    self._mesa_column(bid, col, dcol, noise, px, pz, rnd)
                else:
                    self._column(bid, col, dcol, noise, px, pz, rnd)
                blocks[l, k] = col
                data[l, k] = dcol

    def _materials(self, bid, noise):
        top, td, fill, fd = _MATERIALS.get(bid, _DEFAULT)
        kind = _HILLS.get(bid)
        if kind is not None:
            top, td, fill, fd = GRASS, 0, DIRT, 0
            if (noise < -1.0 or noise > 2.0) and kind == "mutated":
                top = fill = GRAVEL
            elif noise > 1.0 and kind != "trees":
                top, td, fill, fd = STONE, 0, STONE, 0
        elif bid in _MEGA_TAIGA:
            top, td, fill = GRASS, 0, DIRT
            if noise > 1.75:
                top, td = DIRT, 1                   # coarse dirt
            elif noise > -0.95:
                top, td = DIRT, 2                   # podzol
        return top, td, fill, fd

    def _column(self, bid, col, dcol, noise, px, pz, rnd):
        top0, td0, fill0, fd0 = self._materials(bid, noise)
        if bid in _SWAMP:
            v = _improved(self.swamp_noise, px * 0.25, pz * 0.25, 0.0)
            if v > 0.0:
                for y in range(len(col) - 1, -1, -1):
                    if col[y] != 0:
                        if y == 62 and col[y] != WATER_FLOWING:
                            col[y] = WATER_FLOWING
                            if v < 0.12:
                                col[y + 1] = LILY
                        break
        top, fill, fd = top0, fill0, fd0
        run = -1
        nd = int(noise / 3.0 + 3.0 + rnd.next_double() * 0.25)
        cold = _TEMP.get(bid, 0.5) < 0.15
        seed = rnd.seed                          # rnd.next_int(2) of every block, inlined
        for y in range(len(col) - 1, -1, -1):
            seed = (seed * 0x5DEECE66D + 0xB) & 0xFFFFFFFFFFFF
            if y <= 1 + (seed >> 47):
                col[y] = BEDROCK
                continue
            cur = col[y]
            if cur == 0:
                run = -1
            elif cur == STONE:
                if run == -1:
                    if nd <= 0:
                        top, fill, fd = 0, STONE, 0
                    elif SEA_LEVEL - 7 - nd <= y < SEA_LEVEL - 1:
                        top, fill, fd = top0, fill0, fd0
                    if y < SEA_LEVEL and top == 0:
                        top = ICE if cold else WATER
                    run = nd
                    if y >= SEA_LEVEL - 1:
                        col[y] = top
                    elif y < SEA_LEVEL - 7 - nd:
                        top, fill, fd = 0, STONE, 0
                        col[y] = GRAVEL
                    else:
                        col[y] = fill
                elif run > 0:
                    run -= 1
                    col[y] = fill
                    if run == 0 and fill == SAND:
                        rnd.seed = seed
                        run = rnd.next_int(4)
                        seed = rnd.seed
                        fill = RED_SANDSTONE if fd == 1 else SANDSTONE
                        fd = 0
        rnd.seed = seed
        # the data of the biome's blocks (buildSurfaceAtDefault with chunkData)
        for y in range(len(col)):
            if col[y] == top0 and td0:
                dcol[y] = td0
            elif col[y] == fill0 and fd0:
                dcol[y] = fd0

    def _mesa_column(self, bid, col, dcol, noise, px, pz, rnd):
        if self._mesa is None:
            self._mesa = _Mesa(self.seed)
        m = self._mesa
        plateau, trees = _MESA[bid]
        pillar = 0.0
        if plateau and bid == _MESA_BRYCE:
            nx = (px & ~15) + (pz & 15)
            nz = (pz & ~15) + (px & 15)
            d0 = abs(noise) - _octaves(m.pillar, nx * 0.25, nz * 0.25)
            if d0 > 0.0:
                scale = math.ceil(abs(_octaves(m.pillar_roof, nx * 0.001953125, nz * 0.001953125)) * 50.0)
                pillar = min(d0 * d0 * 2.5, scale + 14.0) + 64.0
        nd = int(noise / 3.0 + 3.0 + rnd.next_double() * 0.25)
        cos_flag = math.cos(noise / 3.0 * math.pi) > 0.0
        run = -1
        red_sand = False
        for y in range(len(col) - 1, -1, -1):
            if col[y] == 0 and pillar > 0.0 and y < int(pillar):
                col[y] = STONE
            if y <= rnd.next_int(5):
                col[y] = BEDROCK
                continue
            cur = col[y]
            if cur == 0:
                run = -1
                continue
            if cur != STONE:
                continue
            if run == -1:
                red_sand = False
                run = nd + max(0, y - SEA_LEVEL)
                if y < SEA_LEVEL - 1:
                    if nd <= 0:
                        col[y] = STONE
                    else:
                        col[y], dcol[y] = CLAY_STAINED, _BAND_ORANGE
                elif trees and y > 86 + nd * 2:
                    if cos_flag:
                        col[y], dcol[y] = DIRT, 1
                    else:
                        col[y] = GRASS
                elif y <= SEA_LEVEL + 3 + nd:
                    col[y], dcol[y] = SAND, 1
                    red_sand = True
                elif cos_flag:
                    col[y] = CLAY_HARDENED
                else:
                    col[y], dcol[y] = m.band(px, y)
            elif run > 0:
                run -= 1
                if red_sand:
                    col[y], dcol[y] = CLAY_STAINED, _BAND_ORANGE
                else:
                    col[y], dcol[y] = m.band(px, y)

    # ---------------------------------------------------------- public
    def chunk(self, cx: int, cz: int, lift=None):
        """Blocks (x, z, y) uint8 of a freshly generated chunk, its biome ids (x, z) and the blocks'
        data (x, z, y).  ``lift`` [x, z]: blocks (fractions too) to move the terrain up (down if
        negative), see lift.py."""
        tx, tz = cx - self.offset[0], cz - self.offset[1]
        seed = _s64(tx * 341873128712 + tz * 132897987541)
        b4 = self.stack.biomes4(tx * 4 - 2, tz * 4 - 2, 10, 10)
        b1 = self.stack.biomes(tx * 16, tz * 16, 16, 16)
        q = self._density(tx, tz, b4)
        comp, edge = self._falloff(tx, tz)
        d = density_field(q)
        blocks = self._rock(d, comp, edge)
        data = np.zeros_like(blocks)
        self._surface(tx, tz, blocks, data, b1, JavaRandom(seed))
        lifted = lift is not None and bool(np.any(lift))
        before = blocks.copy() if lifted and self.caves else None
        if self.caves:
            self.carvers.carve(tx, tz, blocks, self._top_lookup(b1, tx, tz))
        if not lifted:
            return blocks, b1.T.copy(), data
        # LCE worlds are 256 blocks high: a column lifted above the generator's 128 keeps its top
        height = TALL if float(np.max(lift)) > 0 else blocks.shape[2]
        moved = lifted_rock(d - comp[:, :, None], lift, SEA_LEVEL - 1, height=height)
        self._edge_columns(moved, edge)
        mdata = np.zeros_like(moved)
        self._surface(tx, tz, moved, mdata, b1, JavaRandom(seed))
        if before is not None:
            move_caves(moved, before, blocks, lift)
        keep = np.asarray(lift) == 0                        # the game's own columns, exactly
        moved[keep] = 0
        moved[keep, :blocks.shape[2]] = blocks[keep]
        mdata[keep, :blocks.shape[2]] = data[keep]
        return moved, b1.T.copy(), mdata

    def _top_of(self, x: int, z: int) -> int:
        return self._top_block(int(self.stack.biomes(x, z, 1, 1)[0, 0]))

    @staticmethod
    def _top_block(b: int) -> int:
        if b in _MESA:
            return SAND
        return _MATERIALS.get(b, _DEFAULT)[0]

    def _top_lookup(self, b1: np.ndarray, tx: int, tz: int):
        """_top_of for the columns of chunk (tx, tz), read from its biomes ``b1`` [z, x]."""
        return _chunk_top_of(b1, tx, tz, self._top_block, self._top_of)
