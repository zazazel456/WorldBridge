"""The Nether's surface in Minecraft Java 1.18 and later: bedrock floor and roof, nylium, soul sand and
soil, basalt and blackstone, gravel and soul sand patches, for the ring WorldBridge writes around a converted
Nether (ring3d.py), where the game no longer adds them (its "terrain" step makes noise, surface and caves in
one go, so a chunk saved at that status is final but for its features).

Read from the rules of the 26.3 jar and checked against the surfaces of a 26.3 Nether, in our own words:

* the Nether keeps the random source of 1.16 (a `java.util.Random`); the world seed makes one positional
  factory, a name gives a generator seeded with the name's Java string hash XOR the factory seed, a
  position one seeded with the game's 3D position hash XOR the factory seed;
* a "normal noise" is two Perlin noises of the same octaves drawn from the same generator, each octave
  from the generator of the name "octave_N" of a factory forked from it, added (the second sampled
  1.0181268882175227 times farther) and scaled so that its deviation is about constant;
* every position of netherrack is looked at from the top of its column: ``above`` is the number of solid
  blocks in the column since the last air (lava does not count and does not reset), ``below`` the number of
  solid blocks from it down to the next non-solid one; the surface depth of the column is
  ``int(surface noise * 2.75 + 3 + 0.25 * random)`` and a column with a depth of 0 or less is a "hole";
  *on the floor* means ``above <= 1``, *under the floor* ``above <= 1 + depth``, *under the ceiling*
  ``below <= 1 + depth``;
* the first rule that matches decides (netherrack when none does): bedrock in the 5 lowest layers and the 5
  highest (a chance that falls by a fifth per layer, decided by a random of the position); netherrack from
  y 122 up; basalt deltas: basalt under ceilings, under floors gravel patches, basalt where the state
  noise is non-negative, else blackstone; soul sand valley: soul sand or soil by the state noise
  under floors and ceilings; on the floor, lava under y 32 in holes, then nylium of the warped and
  crimson forests (with wart blocks where the wart noise is above 1.17) unless the netherrack noise is
  at least 0.54; nether wastes: soul sand patches under floors near the lava level and gravel patches on
  floors.
"""

from __future__ import annotations

from typing import Dict, Tuple

import numpy as np

from .betagen import JavaRandom, Perlin
from .modern16 import _improved, _wrap
from . import netherbiomes as nb

M64 = (1 << 64) - 1
MAIN_Y = 122                    # netherrack from here up (the roof's biome-free layer)
BEDROCK, SOUL_SAND, SOUL_SOIL, BASALT, BLACKSTONE, GRAVEL, LAVA, WARPED_NYLIUM, WARPED_WART, CRIMSON_NYLIUM, \
    WART_BLOCK, NETHERRACK = range(1, 13)
BLOCKS = {BEDROCK: "minecraft:bedrock", SOUL_SAND: "minecraft:soul_sand", SOUL_SOIL: "minecraft:soul_soil",
          BASALT: "minecraft:basalt", BLACKSTONE: "minecraft:blackstone", GRAVEL: "minecraft:gravel",
          LAVA: "minecraft:lava", WARPED_NYLIUM: "minecraft:warped_nylium", WARPED_WART: "minecraft:warped_wart_block",
          CRIMSON_NYLIUM: "minecraft:crimson_nylium", WART_BLOCK: "minecraft:nether_wart_block",
          NETHERRACK: "minecraft:netherrack"}
# (first octave, amplitudes) of the noises
NOISES = {
    "surface": (-6, (1.0, 1.0, 1.0)),
    "soul_sand_layer": (-8, (1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.013333333333333334)),
    "gravel_layer": (-8, (1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.013333333333333334)),
    "patch": (-5, (1.0, 0.0, 0.0, 0.0, 0.0, 0.013333333333333334)),
    "netherrack": (-3, (1.0, 0.0, 0.0, 0.35)),
    "nether_wart": (-3, (1.0, 0.0, 0.0, 0.9)),
    "nether_state_selector": (-4, (1.0,)),
}


def _jhash(s: str) -> int:
    h = 0
    for ch in s:
        h = (31 * h + ord(ch)) & 0xFFFFFFFF
    return h - (1 << 32) if h >= 1 << 31 else h


def _pos_seed(x: int, y: int, z: int) -> int:
    """Mth.getSeed(x, y, z)."""
    x32 = ((x * 3129871) + (1 << 31)) % (1 << 32) - (1 << 31)
    l = (x32 ^ ((z * 116129781) & M64) ^ y) & M64
    l = (l * l * 42317861 + l * 11) & M64
    return (l - (1 << 64) if l >= 1 << 63 else l) >> 16


class _Positional:
    def __init__(self, seed: int):
        self.seed = seed & M64

    def from_hash(self, name: str) -> JavaRandom:
        return JavaRandom((_jhash(name) ^ self.seed) & M64)

    def at(self, x: int, y: int, z: int) -> JavaRandom:
        return JavaRandom((_pos_seed(x, y, z) ^ self.seed) & M64)

    def fork_hash(self, name: str) -> "_Positional":
        return _Positional(self.from_hash(name).next_long())


class _Octaves:
    def __init__(self, rnd: JavaRandom, first: int, amps):
        pr = _Positional(rnd.next_long())
        n = len(amps)
        self.levels = []
        lac = 2.0 ** first
        per = 2.0 ** (n - 1) / (2.0 ** n - 1.0)
        for i, a in enumerate(amps):
            if a != 0.0:
                self.levels.append((Perlin(pr.from_hash(f"octave_{first + i}")), a * per, lac))
            lac *= 2.0
            per /= 2.0

    def value(self, x, y, z):
        t = 0.0
        for o, amp, lac in self.levels:
            t = t + _improved(o, _wrap(x * lac), _wrap(y * lac), _wrap(z * lac)) * amp
        return t


class _Noise:
    def __init__(self, rnd: JavaRandom, first: int, amps):
        self.a = _Octaves(rnd, first, amps)
        self.b = _Octaves(rnd, first, amps)
        nz = [i for i, v in enumerate(amps) if v != 0.0]
        self.factor = (1.0 / 6.0) / (0.1 * (1.0 + 1.0 / (nz[-1] - nz[0] + 1)))

    def value(self, x, y, z):
        k = 1.0181268882175227
        return (self.a.value(x, y, z) + self.b.value(x * k, y * k, z * k)) * self.factor


class NetherSurface:
    """``apply(cx, cz, cat, biomes)`` -> [128, 16, 16] codes (0: unchanged) for the chunk's netherrack."""

    def __init__(self, seed: int):
        self.seed = seed
        self.main = _Positional(JavaRandom(seed).next_long())
        self.noises = {name: _Noise(self.main.from_hash("minecraft:" + name), first, amps)
                       for name, (first, amps) in NOISES.items()}
        self.floor = self.main.fork_hash("minecraft:bedrock_floor")
        self.roof = self.main.fork_hash("minecraft:bedrock_roof")

    # ------------------------------------------------------------------ per column
    def columns(self, cx: int, cz: int) -> Dict[str, np.ndarray]:
        X = (cx * 16 + np.arange(16, dtype=np.float64))[None, :]
        Z = (cz * 16 + np.arange(16, dtype=np.float64))[:, None]
        X, Z = np.broadcast_arrays(X, Z)                       # [z, x]
        out = {name: n.value(X, 0.0, Z).astype(np.float32).astype(np.float64) for name, n in self.noises.items()}
        r = np.zeros((16, 16))
        for z in range(16):
            for x in range(16):
                r[z, x] = self.main.at(cx * 16 + x, 0, cz * 16 + z).next_double()
        out["depth"] = np.trunc(out["surface"] * 2.75 + 3.0 + r * 0.25).astype(np.int64)
        return out

    def bedrock(self, cx: int, cz: int) -> np.ndarray:
        """[128, 16, 16] bool: where the bedrock floor and roof are."""
        out = np.zeros((128, 16, 16), bool)
        for y in range(0, 5):
            p = 1.0 - y / 5.0                                    # the floor's gradient: true at 0, false at 5
            for z in range(16):
                for x in range(16):
                    if y == 0:
                        out[y, z, x] = True
                    elif float(self.floor.at(cx * 16 + x, y, cz * 16 + z).next_float()) < p:
                        out[y, z, x] = True
        for y in range(123, 128):
            p = (127.0 - y) / 5.0 if y < 127 else 0.0           # the roof's gradient (122 true .. 127 false), negated
            for z in range(16):
                for x in range(16):
                    if y == 127:
                        out[y, z, x] = True
                    elif not float(self.roof.at(cx * 16 + x, y, cz * 16 + z).next_float()) < p:
                        out[y, z, x] = True
        return out

    # ------------------------------------------------------------------ rules
    def apply(self, cx: int, cz: int, cat: np.ndarray, biomes: np.ndarray, bedrock: bool = True) -> np.ndarray:
        """``cat`` [128, 16, 16] (y, z, x): 0 air, 1 lava, 2 netherrack (what the rules may change), 3 other
        solid; ``biomes`` [4, 4] biome indices (netherbiomes) of the chunk's cells [qx, qz]."""
        col = self.columns(cx, cz)
        solid = cat >= 2
        air = cat == 0
        above = np.zeros(cat.shape, np.int32)
        run = np.zeros((16, 16), np.int32)
        for y in range(127, -1, -1):
            run = np.where(air[y], 0, run + solid[y])
            above[y] = run
        below = np.zeros(cat.shape, np.int32)
        run = np.zeros((16, 16), np.int32)
        for y in range(128):
            run = np.where(solid[y], run + 1, 0)
            below[y] = run
        Y = np.arange(128, dtype=np.int32)[:, None, None]
        depth = col["depth"][None]
        hole = depth <= 0
        on_floor = above <= 1
        under_floor = above <= 1 + depth
        under_ceiling = below <= 1 + depth
        y31 = Y >= 31
        start30 = (Y + above) >= 30
        not_start35 = ~((Y + above) >= 35)
        sel = (col["nether_state_selector"] >= 0.0)[None]
        patch = (col["patch"] >= -0.012)[None]
        ssl = (col["soul_sand_layer"] >= -0.012)[None]
        gravel_layer = (col["gravel_layer"] >= -0.012)[None]
        nrack = (col["netherrack"] >= 0.54)[None]
        wart = (col["nether_wart"] >= 1.17)[None]
        bio = np.repeat(np.repeat(np.asarray(biomes), 4, axis=0), 4, axis=1).T[None]       # [1, z, x]
        gravel19 = patch & start30 & not_start35
        res = np.zeros(cat.shape, np.int8)
        free = cat == 2

        def put(cond, code):
            nonlocal free
            m = free & cond
            res[m] = code
            free = free & ~m

        if bedrock:
            put(self.bedrock(cx, cz), BEDROCK)
        put(Y >= MAIN_Y, NETHERRACK)
        d, s, c, w, wa = (bio == nb.BASALT_DELTAS), (bio == nb.SOUL_SAND_VALLEY), (bio == nb.CRIMSON_FOREST), \
            (bio == nb.WARPED_FOREST), (bio == nb.WASTES)
        put(d & under_ceiling, BASALT)
        put(d & under_floor & gravel19, GRAVEL)
        put(d & under_floor & sel, BASALT)
        put(d & under_floor, BLACKSTONE)
        put(s & under_ceiling & sel, SOUL_SAND)
        put(s & under_ceiling, SOUL_SOIL)
        put(s & under_floor & gravel19, GRAVEL)
        put(s & under_floor & sel, SOUL_SAND)
        put(s & under_floor, SOUL_SOIL)
        put(on_floor & (Y < 32) & hole, LAVA)
        put(w & on_floor & ~nrack & y31 & wart, WARPED_WART)
        put(w & on_floor & ~nrack & y31, WARPED_NYLIUM)
        put(c & on_floor & ~nrack & y31 & wart, WART_BLOCK)
        put(c & on_floor & ~nrack & y31, CRIMSON_NYLIUM)
        put(wa & under_floor & ssl & ~hole & start30 & not_start35, SOUL_SAND)
        put(wa & under_floor & ssl, NETHERRACK)
        put(wa & on_floor & y31 & not_start35 & gravel_layer & (Y >= 32), GRAVEL)
        put(wa & on_floor & y31 & not_start35 & gravel_layer & ~hole, GRAVEL)
        return np.where(res == NETHERRACK, 0, res)
