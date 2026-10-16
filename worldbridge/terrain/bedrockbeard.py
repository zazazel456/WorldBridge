"""Structure terrain adjustment of Bedrock's old overworld (1.6 - 1.17): the "beard" the game puts under and around
village pieces so the ground follows them, and the "bury" that sinks strongholds.

The game keeps, per chunk, the adjustments of the structures that reach it (``FeatureTerrainAdjustments`` in 1.17,
``BeardAndShaverStorage`` in 1.16) and hands them over once, when the chunk's stone is made.  This module is the
arithmetic on that list: ``TerrainAdjustments(beards, burys)`` gives the amount added to a block's density.  Which
adjustments a chunk gets comes from the structure placement (village layout), which is not made here: the caller
passes them in (``Beard.from_box`` takes the arguments the game's ``setBeardAndShaver`` gets from a village piece).

Everything is float32 in the game's operation order, checked against BDS 1.16.220 and 1.17.41 (BeardKernel table
bit for bit; 4 seeds, ~6 M adjusted blocks in 100 chunks next to villages, all equal).  Bury is the 1.17 code read
from the binary, unverified in a running game (no stronghold was in reach).
"""

from __future__ import annotations

import struct
from functools import lru_cache
from typing import Iterable, Sequence, Tuple

import numpy as np

F = np.float32
REACH = 12                              # the kernel table covers -12 .. 11 blocks around a description's box


@lru_cache(maxsize=1)
def kernel() -> np.ndarray:
    """BeardKernel: float32 [24, 24, 24] indexed [dz + 12, dx + 12, dy + 12].  The game's powf is the correctly
    rounded float of the double power (identical on all 13824 entries), its fast inverse square root the 0x5f3759df
    one with a single Newton step."""
    e = np.float64(struct.unpack("<f", struct.pack("<I", 0x402DF854))[0])          # the float nearest e
    c = np.arange(24) - REACH
    f = (c.astype(np.float64) + 0.5).astype(np.float32)[None, None, :]
    s = (c[:, None] ** 2 + c[None, :] ** 2).astype(np.float32)[:, :, None]
    p = np.power(e, -(f * f * F(0.0625) + s * F(0.0625)).astype(np.float64)).astype(np.float32)
    x = (f * f * F(0.5) + s * F(0.5)).astype(np.float32)
    y = (np.int32(0x5F3759DF) - (x.view(np.int32) >> 1)).view(np.float32)
    inv = (((x * F(-0.5)) * y * y + F(1.5)) * y).astype(np.float32)
    return (((inv * f) * F(-0.5)) * p).astype(np.float32)


class Beard:
    """BeardAndShaverDescription: the box of a village piece grown by 2 blocks, the ground level below which the
    ground is raised and the reach above and below it."""

    __slots__ = ("bounds", "ground", "half", "above", "below", "cx", "cz")

    def __init__(self, bounds: Sequence[int], ground: int, half: float, above: float, below: float):
        self.bounds = tuple(int(v) for v in bounds)       # x0, y0, z0, x1, y1, z1 of the grown box
        self.ground, self.half, self.above, self.below = int(ground), F(half), F(above), F(below)
        self.cx = (self.bounds[0] + self.bounds[3]) // 2
        self.cz = (self.bounds[2] + self.bounds[5]) // 2

    @classmethod
    def from_box(cls, box: Sequence[int], ground: int, above: float = 1.0, below: float = 5.0) -> "Beard":
        """The description ``setBeardAndShaver(box, ground, above, below)`` makes (box = x0, y0, z0, x1, y1, z1 of
        the piece; every village piece of 1.16 / 1.17 uses above 1.0 and below 5.0, ground 0, 1 or 2)."""
        x0, y0, z0, x1, y1, z1 = (int(v) for v in box)
        bx0, bz0 = x0 - 2, z0 - 2
        wx, wz = (x1 + 3) - bx0, (z1 + 3) - bz0
        half = max(F(F(wx) * F(0.5)), F(F(wz) * F(0.5)))
        out = cls((bx0, y0, bz0, x1 + 2, y1, z1 + 2), ground + y0, half, above, below)
        out.cx, out.cz = int(wx / 2) + bx0, int(wz / 2) + bz0           # C division truncates toward zero
        return out

    def term(self, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
        """BeardKernel::calculateBeardAndShaverContribution at the block positions (int arrays)."""
        b = self.bounds
        top = np.where(y >= self.ground, y, self.ground)
        top = np.where(y > b[4], b[4], top)
        dy = y - top
        dx = np.maximum(np.maximum(x - b[3], b[0] - x), 0)
        dz = np.maximum(np.maximum(z - b[5], b[2] - z), 0)
        fx, fy, fz = (x - self.cx).astype(np.float32), dy.astype(np.float32), (z - self.cz).astype(np.float32)
        dist = np.sqrt(fz * fz + (fy * fy + fx * fx)).astype(np.float32)
        reach = np.where(y > self.ground, self.below, self.above).astype(np.float32) + self.half
        with np.errstate(divide="ignore", invalid="ignore"):
            w = np.where((dist <= reach) & (reach > 0), F(1.5) - dist / reach, F(0.0)).astype(np.float32)
        inside = (dy + REACH < 24) & (dy + REACH >= 0) & (dx + REACH < 24) & (dz + REACH < 24)
        k = kernel()[np.clip(dz + REACH, 0, 23), np.clip(dx + REACH, 0, 23), np.clip(dy + REACH, 0, 23)]
        return (w * np.where(inside, k, F(0.0))).astype(np.float32)

    def reaches(self, x0: int, z0: int, x1: int, z1: int) -> bool:
        b = self.bounds
        return not (x1 < b[0] - REACH or x0 > b[3] + REACH or z1 < b[2] - REACH or z0 > b[5] + REACH)


def _bury_term(box: Sequence[int], x, y, z) -> np.ndarray:
    x0, y0, z0, x1, y1, z1 = box
    top = np.where(y >= y0, y, y0)
    top = np.where(y > y1, y1, top)
    dy = y - top
    dx = np.maximum(np.maximum(x0 - x, x - x1), 0)
    dz = np.maximum(np.maximum(z0 - z, z - z1), 0)
    s = (dz * dz).astype(np.float32) + ((dy * dy).astype(np.float32) * F(0.5) + (dx * dx).astype(np.float32))
    t = (np.sqrt(s.astype(np.float32)) / F(3.0)).astype(np.float32)
    v = F(0.024) - np.maximum(t, F(0.0)) * F(0.024)
    return np.where(F(1.0) < t, F(0.0), v).astype(np.float32)


class TerrainAdjustments:
    """What the game holds for one chunk: ``beards`` (:class:`Beard`, in the order the structures set them) and
    ``burys`` (boxes x0, y0, z0, x1, y1, z1 of stronghold pieces)."""

    def __init__(self, beards: Iterable[Beard] = (), burys: Iterable[Sequence[int]] = ()):
        self.beards = list(beards)
        self.burys = [tuple(int(v) for v in b) for b in burys]

    def __bool__(self) -> bool:
        return bool(self.beards or self.burys)

    def contribution(self, density: np.ndarray, x: np.ndarray, y: np.ndarray, z: np.ndarray) -> np.ndarray:
        """FeatureTerrainAdjustments::calculateContribution: the beards' sum, plus the bury boxes' where the
        block would be air even so.  ``density`` is the game's squashed density (float32), x, y, z block positions."""
        x0, x1, z0, z1 = int(x.min()), int(x.max()), int(z.min()), int(z.max())
        total = np.zeros(density.shape, np.float32)
        for b in self.beards:
            if b.reaches(x0, z0, x1, z1):
                total = (total + b.term(x, y, z)).astype(np.float32)
        if self.burys:
            air = (density + total) <= 0
            for box in self.burys:
                total = np.where(air, total + _bury_term(box, x, y, z), total).astype(np.float32)
        return total

    def stone(self, field: np.ndarray, cx: int, cz: int, divide: bool) -> np.ndarray:
        """bool [16, 16, H]: stone where the adjusted density is above 0.  ``field`` is the chunk's interpolated
        density; the game squashes it with clamp(v / 200) (1.16) or clamp(v * 0.005) (1.17) as c * 0.5 - c^3 / 24."""
        v = field / F(200.0) if divide else field * F(0.005)
        c = np.minimum(np.maximum(v, F(-1.0)), F(1.0)).astype(np.float32)
        squashed = ((c * c * c) / F(-24.0) + c * F(0.5)).astype(np.float32)
        shape = field.shape
        x = (cx * 16 + np.arange(16))[:, None, None] + np.zeros(shape, np.int64)
        z = (cz * 16 + np.arange(16))[None, :, None] + np.zeros(shape, np.int64)
        y = np.arange(shape[2])[None, None, :] + np.zeros(shape, np.int64)
        return ~((squashed + self.contribution(squashed, x, y, z)).astype(np.float32) <= 0)
