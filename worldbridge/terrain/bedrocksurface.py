"""The surface pass of Bedrock's overworld generator before 1.18 (``buildSurfaces``: bedrock floor and the surface
builders of every biome), run on the stone / water / air volume of the terrain pass (bedrockgen.py).

    surface = SurfaceBuilder(seed)
    codes = surface.build(volume, biome_ids, cx, cz)        # [x, z, y] palette codes
    blocks, data = to_java(codes)                           # Java 1.12 ids and data

Blocks are small ints, ``PALETTE`` says which block each is (Bedrock name with its states, and the Java 1.12 id and
data it becomes in the ring).  The random numbers are those of the game: one generator per chunk, seeded from the
chunk's coordinates alone, drawn column by column (x outer, z inner): the bedrock floor, then the biome's builder.
Floats are float32 in the game's order of operations.  Behaviour observed in Bedrock Dedicated Server.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np

from .bedrocknoise import OverworldNoises, PerlinSimplex, Random
from .bedrockdata import SURFACES, SurfaceDef

F = np.float32
SEA_LEVEL = 63
AIR_V, STONE_V, WATER_V = 0, 1, 2           # the terrain pass' volume
_TO_UNIT = 2.3283064365386963e-10

COLORS = ["white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "silver", "cyan", "purple",
          "blue", "brown", "green", "red", "black"]       # the order of Java's colour data too

# Bedrock block (name[states]) -> Java 1.12 (id, data)
_JAVA = {
    "air": (0, 0), "stone": (1, 0), "grass": (2, 0), "dirt": (3, 0), "dirt[dirt_type=coarse]": (3, 1),
    "podzol": (3, 2), "bedrock": (7, 0), "water": (9, 0), "sand": (12, 0), "sand[sand_type=red]": (12, 1),
    "gravel": (13, 0), "sandstone": (24, 0), "ice": (79, 0), "snow": (80, 0), "mycelium": (110, 0),
    "hardened_clay": (172, 0), "packed_ice": (174, 0),
}
_JAVA.update({"stained_hardened_clay[color=%s]" % c: (159, i) for i, c in enumerate(COLORS)})


class Palette:
    """Block specs -> small ints."""

    def __init__(self) -> None:
        self.names: List[str] = []
        self._index: Dict[str, int] = {}

    def code(self, spec: str) -> int:
        if spec not in self._index:
            if spec not in _JAVA:
                raise KeyError("no Java block for " + spec)
            self._index[spec] = len(self.names)
            self.names.append(spec)
        return self._index[spec]


PALETTE = Palette()
AIR = PALETTE.code("air")
STONE = PALETTE.code("stone")
WATER = PALETTE.code("water")
BEDROCK = PALETTE.code("bedrock")
SAND = PALETTE.code("sand")
SANDSTONE = PALETTE.code("sandstone")
ICE = PALETTE.code("ice")
PACKED_ICE = PALETTE.code("packed_ice")
SNOW = PALETTE.code("snow")
GRASS = PALETTE.code("grass")
COARSE_DIRT = PALETTE.code("dirt[dirt_type=coarse]")
_CLAY = [PALETTE.code("stained_hardened_clay[color=%s]" % c) for c in COLORS]


def to_java(codes: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Palette codes -> (Java 1.12 block ids, data), both uint8 with the shape of ``codes``."""
    ids = np.array([_JAVA[n][0] for n in PALETTE.names], np.uint8)
    data = np.array([_JAVA[n][1] for n in PALETTE.names], np.uint8)
    return ids[codes], data[codes]


def names(codes: np.ndarray) -> np.ndarray:
    """Palette codes -> Bedrock block names with states (object array)."""
    return np.array(PALETTE.names, dtype=object)[codes]


_SLOTS = ("top", "mid", "floor", "base", "sea")


class _Surface:
    """A biome's surface, with the blocks as palette codes."""

    def __init__(self, d: SurfaceDef):
        self.kind = d.kind
        self.temp = F(d.temp)
        self.mats = [PALETTE.code(getattr(d, s)) for s in _SLOTS]
        self.floor_depth = d.floor_depth
        self.bryce, self.forest = d.bryce, d.forest
        self.adjust = [(F(a.scale), F(a.lo), F(a.hi), {_SLOTS.index(k): PALETTE.code(v) for k, v in a.slots.items()})
                       for a in d.adjust]


def _unit(u: int) -> np.float32:
    return F(np.float64(u) * _TO_UNIT)


class SurfaceBuilder:
    """``OverworldGenerator::buildSurfaces`` for one level seed."""

    def __init__(self, seed: int, noises: Optional[OverworldNoises] = None):
        self.seed = seed & 0xFFFFFFFF
        noises = noises or OverworldNoises(self.seed)
        self.noise = noises.surface              # 4 octaves, the depth driver
        self.extra = noises.extra                # 3 octaves, the material adjustments
        self.biomes = {i: _Surface(d) for i, d in SURFACES.items()}
        self._frozen = None
        self._frozen_temp_noise = None
        self._mesa = None

    # -------------------------------------------------- per chunk
    def build(self, volume: np.ndarray, biome_ids: np.ndarray, cx: int, cz: int) -> np.ndarray:
        """``volume`` [x, z, y] of terrain codes (0 air, 1 stone, 2 water; 128 high, or taller for lifted
        terrain), ``biome_ids`` [x, z]: the volume as palette codes after the bedrock floor and the surfaces."""
        height = volume.shape[2]
        noise = self.noise.region2(cx * 16, cz * 16, 16, 16, 0.125, 0.125)           # [z, x]
        rng = Random((cz * 0x7EBE2D5 + cx * 0x14609048) & 0xFFFFFFFF)
        codes = np.where(volume == STONE_V, STONE, np.where(volume == WATER_V, WATER, AIR)).astype(np.int32)
        for x in range(16):
            for z in range(16):
                col = codes[x, z].tolist()
                for y in range((rng.u32() & 3) + 2):                                   # the bedrock floor
                    col[y] = BEDROCK
                s = self.biomes.get(int(biome_ids[x, z]))
                if s is not None:
                    wx, wz = cx * 16 + x, cz * 16 + z
                    n = noise[z, x]
                    if s.kind == "default":
                        self._default(s, col, rng, wx, wz, n, height)
                    elif s.kind == "swamp":
                        # the game's patch loop stops at the first block, y = 127, which is air: nothing changes
                        self._default(s, col, rng, wx, wz, n, height)
                    elif s.kind == "frozen":
                        self._frozen_column(s, col, rng, wx, wz, n, height)
                    elif s.kind == "mesa":
                        self._mesa_column(s, col, rng, wx, wz, n, height)
                codes[x, z] = col
        return codes

    # -------------------------------------------------- the generic builder
    def _adjusted(self, s: _Surface, wx: int, wz: int) -> List[int]:
        base = list(s.mats)
        for scale, lo, hi, slots in s.adjust:
            v = self.extra.value3_normalized(F(wx) * scale, F(0.0) * scale, F(wz) * scale)
            if lo <= v < hi:
                for k, b in slots.items():
                    base[k] = b
        return base

    def _default(self, s: _Surface, col: List[int], rng: Random, wx: int, wz: int, n, height: int,
                 temp: Optional[np.float32] = None) -> None:
        """Dirt / sand / gravel skins over the stone, the sea floor and the water, column by column from the top."""
        top, mid, floor, found, sea_m = self._adjusted(s, wx, wz) if s.adjust else s.mats
        depth = int(_unit(rng.u32()) * F(0.25) + F(n) / F(3.0) + F(3.0))
        sea = SEA_LEVEL
        cur_top, cur_mid = top, mid
        counter = -1
        temp = s.temp if temp is None else temp
        for y in range(height - 1, 0, -1):
            b = col[y]
            if b == BEDROCK:
                continue
            if b == AIR:
                counter = -1
            elif b == WATER:
                col[y] = sea_m
            elif b == STONE:
                if counter == -1:
                    counter = depth
                    if depth < 1:
                        cur_top, cur_mid = AIR, found
                    elif sea - 4 <= y <= sea + 1:
                        cur_top, cur_mid = top, mid
                    if y < sea and cur_top == AIR:
                        cur_top = sea_m
                        if sea_m == WATER and not (temp >= F(0.15)):
                            cur_top = ICE
                    if y >= sea - 1:
                        col[y] = cur_top
                    elif y < sea - depth - s.floor_depth:
                        cur_top, cur_mid = AIR, found
                        col[y] = floor
                    else:
                        col[y] = cur_mid
                elif counter < 1:
                    col[y] = found
                else:
                    col[y] = cur_mid
                    counter -= 1
                    if counter == 0 and cur_mid == SAND:
                        counter = max(y - sea, 0) + (rng.u32() & 3)
                        cur_mid = SANDSTONE

    # -------------------------------------------------- frozen oceans
    def _frozen_temperature(self, s: _Surface, wx: int, wz: int) -> np.float32:
        """The frozen ocean's temperature at its surface: noise makes patches warmer than the biome."""
        if self._frozen_temp_noise is None:
            self._frozen_temp_noise = (PerlinSimplex(Random(3456), 3), PerlinSimplex(Random(2345), 1))
        big, info = self._frozen_temp_noise
        fx, fz = F(wx), F(wz)
        v = big.value2(fx * F(0.05), fz * F(0.05)) + info.value2(fx * F(0.2), fz * F(0.2))
        if F(0.3) <= v:
            return s.temp
        return F(0.2) if info.value2(fx * F(0.09), fz * F(0.09)) < F(0.8) else s.temp

    def _frozen_column(self, s: _Surface, col: List[int], rng: Random, wx: int, wz: int, n, height: int) -> None:
        """Icebergs (packed ice in and over the water, snow on top), a second random bedrock floor, then the
        generic builder with the noise-based temperature."""
        if self._frozen is None:
            r = Random(self.seed)
            self._frozen = (PerlinSimplex(r, 4), PerlinSimplex(r, 1))
        n4, n1 = self._frozen
        sea = SEA_LEVEL
        temp = self._frozen_temperature(s, wx, wz)
        fx, fz = F(wx), F(wz)
        a = F(abs(n))
        v = n4.value2(fx * F(0.1), fz * F(0.1))
        m = a if a < v else v
        if m > F(1.8):
            roof = F(abs(n1.value2(fx * F(0.9765624403953552), fz * F(0.9765624403953552))))
            m = (m * m) * F(0.8)
            t = F(int(np.ceil(roof * F(40.0)))) + F(14.0)
            t = t if t < m else m
            if F(0.1) < temp:
                t = t + F(-2.0)
            d3 = (F(sea + 1) - t) + F(-7.0)
            d2 = int(F(sea + 1) + t)
        else:
            d2, d3 = 0, F(0.0)
        ra, rb = rng.u32(), rng.u32()
        kmax = (ra & 3) + 2
        snow_y = sea + rb % 10 + 18
        d3i = int(d3)
        count = 0
        for y in range(height - 1, -1, -1):
            b = col[y]
            if b == BEDROCK:
                break
            if b == AIR and y < d2 and _unit(rng.u32()) > F(0.01):
                col[y] = b = PACKED_ICE
            elif b == WATER and y > d3i and d3 != F(0.0) and y < sea and _unit(rng.u32()) > F(0.15):
                col[y] = b = PACKED_ICE
            if y > rng.u32() % 5:
                if count <= kmax and b == PACKED_ICE and y > snow_y:
                    col[y] = SNOW
                    count += 1
            else:
                col[y] = BEDROCK
        self._default(s, col, rng, wx, wz, n, height, temp=temp)

    # -------------------------------------------------- badlands
    def _mesa_init(self) -> None:
        """The badlands' noises and the 64 coloured bands, from two generators seeded with the level seed."""
        r1 = Random(self.seed)
        pillar = PerlinSimplex(r1, 4)
        roof = PerlinSimplex(r1, 1)
        r2 = Random(self.seed)
        offset = PerlinSimplex(r2, 1)
        band = [0x10] * 64                       # 0x10: plain hardened clay
        u = r2.u32
        r = u()
        at = 0
        while True:                              # orange strips
            i1 = at + 1 + r % 5
            if i1 > 63:
                r = u()
                break
            band[i1] = 1
            at = i1 + 1
            r = u()
            if i1 == 63:
                break

        def fill(p: int, length: int, color: int) -> None:
            for k in range(p, min(64, p + length)):
                band[k] = color
        r3 = u()
        for _ in range((r & 3) + 2):             # yellow strips
            fill(u() & 63, 1 + r3 % 3, 4)
            r3 = u()
        r2v = u()
        for _ in range((r3 & 3) + 2):            # brown strips
            fill(u() & 63, 2 + r2v % 3, 12)
            r2v = u()
        r3 = u()
        for _ in range((r2v & 3) + 2):           # red strips
            fill(u() & 63, 1 + r3 % 3, 14)
            r3 = u()
        pos = 0
        for _ in range(r3 % 3 + 3):              # white strips with silver edges
            pos = (u() & 15) + pos + 4
            if pos < 64:
                band[pos] = 0
                if pos > 1:
                    if u() & 0x8000000:
                        band[pos - 1] = 8
                    if pos > 62:
                        continue
                if u() & 0x8000000:
                    band[pos + 1] = 8
        self._mesa = (pillar, roof, offset, band)

    def _band(self, wx: int, y: int, wz: int) -> int:
        offset, band = self._mesa[2], self._mesa[3]
        v = offset.value2(F(wx) * F(0.001953125), F(wz) * F(0.001953125))
        return band[int(np.fmod(y + int(np.rint(v + v)) + 64, 64))]

    def _clay(self, value: int, hard: int) -> int:
        return hard if value >= 0x10 else _CLAY[value]

    def _mesa_column(self, s: _Surface, col: List[int], rng: Random, wx: int, wz: int, n, height: int) -> None:
        if self._mesa is None:
            self._mesa_init()
        pillar_n, roof_n = self._mesa[0], self._mesa[1]
        sea = SEA_LEVEL
        top_b, filler_b, _floor, stone_b, _sea = s.mats
        hard = PALETTE.code("hardened_clay")
        pillar_top = 0
        if s.bryce:
            a = F(abs(n))
            v = pillar_n.value2(F(wx) * F(0.25), F(wz) * F(0.25))
            m = v if v <= a else a
            if m > F(0.0):
                rv = roof_n.value2(F(wx) * F(0.001953125), F(wz) * F(0.001953125))
                m = (m * m) * F(2.5)
                t = F(int(np.ceil(F(abs(rv)) * F(50.0)))) + F(14.0)
                t = m if m <= t else t
                pillar_top = int(t + F(64.0))
        n3 = F(n) / F(3.0)
        depth = int(_unit(rng.u32()) * F(0.25) + n3 + F(3.0))
        high = F(0.0) < np.float32(np.cos(np.float32(n3 * F(3.1415927))))
        counter = -1
        processed = 0
        banded = False                           # the column is in its red sand / band-free part
        filler = filler_b
        for y in range(height - 1, 0, -1):
            b = col[y]
            if b == BEDROCK:
                return
            step = 1
            if (b == AIR or b == WATER) and y < pillar_top:
                col[y] = b = STONE
                step = 0
            if processed < 15:
                if b == AIR:
                    counter = -1
                elif b == STONE:
                    if counter == -1:
                        if depth < 1:
                            filler = stone_b
                        elif sea - 4 <= y <= sea + 1:
                            filler = filler_b
                        counter = max(y - sea, 0) + depth
                        if y < sea - 1:
                            col[y] = filler
                            banded = False
                        elif s.forest and y > sea + 23 + 2 * depth:
                            col[y] = COARSE_DIRT if high else GRASS
                            banded = False
                        elif y > sea + 3 + depth:
                            in_range = sea < y <= sea + 64
                            value = 0x10 if in_range else 1
                            if not high and in_range:
                                value = self._band(wx, y, wz)
                            col[y] = self._clay(value, hard)
                            banded = False
                        else:
                            col[y] = top_b
                            banded = True
                    elif counter > 0:
                        counter -= 1
                        col[y] = _CLAY[1] if banded else self._clay(self._band(wx, y, wz), hard)
                    processed += step
