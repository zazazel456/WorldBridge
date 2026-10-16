"""The Nether's caves in Minecraft Java 1.18 and later (the "nether_cave" carver), for the ring WorldBridge
writes around a converted Nether (ring3d.py): the game carves them in the same step that makes the terrain, so
a ring chunk saved as finished has to have them, or every tunnel of the game's terrain would end in a wall at
the ring's edge.

Read from the 26.3 jar and checked against the caves of a 26.3 Nether, in our own words:

* every chunk within 8 chunks of the one being carved is a possible source: its generator is the
  `java.util.Random` seeded from the world seed, the chunk's x and z (two numbers drawn from the seed, one
  times x, one times z, XORed with the seed); a source starts caves when its first float is at most 0.2;
* a source makes 0..9 caves (the count is biased to the bottom: the next integer is drawn below a bound that
  is itself drawn below a bound...); a cave starts at a random x, z of the source chunk and a height of 0..126;
  one in four first makes a round room (radius 1.5 + 1 .. 7 blocks, half as tall) and then 1..4 more tunnels
  than the one it always makes;
* a tunnel has its own generator (seeded by a number the cave drew): it walks up to 112 - 0..27 steps of one
  block, turning (yaw and pitch change with decaying random velocities), its radius is 1.5 + sin(pi step / steps)
  * its thickness (a trapezoidal random 0 - 6), 5 times that tall; one step in four it does not carve; once,
  at a random step, a tunnel thicker than 1 splits in two that go on at +-90 degrees;
* a step carves the ellipsoid around the tunnel's point: the cells whose distance to it, in radii, is below 1
  and which are higher than 0.7 radii below its centre; from y 2 to y 120; bedrock is never carved; what is
  carved becomes lava under y 32 and air above.

The sine and cosine are the game's lookup table (65,536 floats) and the walk is done in single precision where
the game does, so the tunnels are the game's, block for block.
"""

from __future__ import annotations

import math
from typing import Dict, List, Tuple

import numpy as np

from .betagen import JavaRandom

_F = np.float32
M64 = (1 << 64) - 1
_SIN = np.sin(np.arange(65536, dtype=np.float64) * math.pi * 2.0 / 65536.0).astype(np.float32)
RANGE = 8                       # chunks a source may be away from the chunk carved
CARVER_RANGE = 4                # the cave carver's own range (sections): its tunnels are at most 112 blocks long
START_CHANCE = _F(0.2)
FLOOR_LEVEL = float(_F(-0.7))
MIN_Y, MAX_Y = 1, 120           # the carving mask's bounds: y from MIN_Y + 1 to MAX_Y
LAVA_Y = 32
ROOM_VERTICAL, START_VERTICAL = float(_F(0.5)), float(_F(5.0))
HALF_PI_F = _F(1.5707964)
PI_F = _F(3.1415927)
TWO_PI_F = _F(6.2831855)
_S10430 = 10430.378350470453


def _sin(v) -> "np.float32":
    return _SIN[int(float(v) * _S10430) & 65535]


def _cos(v) -> "np.float32":
    return _SIN[int(float(v) * _S10430 + 16384.0) & 65535]


def _long(v: int) -> int:
    v &= M64
    return v - (1 << 64) if v >= 1 << 63 else v


class NetherCaves:
    def __init__(self, seed: int):
        self.seed = _long(seed)
        self._sources: Dict[Tuple[int, int], np.ndarray] = {}

    # ------------------------------------------------------------------ one source chunk
    def _large_feature_seed(self, sx: int, sz: int) -> JavaRandom:
        r = JavaRandom(self.seed)
        l, m = r.next_long(), r.next_long()
        r.set_seed(_long(_long(sx * l) ^ _long(sz * m) ^ self.seed))
        return r

    def source(self, sx: int, sz: int) -> np.ndarray:
        """[n, 5] (x, y, z, horizontal radius, vertical radius) of the ellipsoids the source chunk carves."""
        got = self._sources.get((sx, sz))
        if got is not None:
            return got
        r = self._large_feature_seed(sx, sz)
        out: List[Tuple[float, float, float, float, float]] = []
        if r.next_float() <= START_CHANCE:
            self._carve(r, sx, sz, out)
        arr = np.array(out, np.float64).reshape(-1, 5)
        self._sources[(sx, sz)] = arr
        return arr

    def _carve(self, r: JavaRandom, sx: int, sz: int, out) -> None:
        span = (CARVER_RANGE * 2 - 1) * 16
        count = r.next_int(r.next_int(r.next_int(10) + 1) + 1)
        for _ in range(count):
            x = float(sx * 16 + r.next_int(16))
            y = float(r.next_int(127))
            z = float(sz * 16 + r.next_int(16))
            tunnels = 1
            if r.next_int(4) == 0:
                size = _F(1.0) + r.next_float() * _F(6.0)
                d = 1.5 + float(_sin(1.5707963705062866) * size)
                out.append((x, y + 1.0, z, d, d * ROOM_VERTICAL))
                tunnels += r.next_int(4)
            for _ in range(tunnels):
                yaw = r.next_float() * TWO_PI_F
                pitch = (r.next_float() - _F(0.5)) / _F(4.0)
                thick = self._thickness(r)
                steps = span - r.next_int(span // 4)
                self._tunnel(r.next_long(), x, y, z, 1.0, 1.0, thick, yaw, pitch, 0, steps, START_VERTICAL, out)

    @staticmethod
    def _thickness(r: JavaRandom) -> "np.float32":
        # trapezoid(min 0, max 6, plateau 2): range 6, side 2, so 4 for the first draw and 2 for the second
        return r.next_float() * _F(4.0) + r.next_float() * _F(2.0)

    def _tunnel(self, seed: int, x: float, y: float, z: float, hmul: float, vmul: float, thick, yaw, pitch,
                start: int, steps: int, yscale: float, out) -> None:
        r = JavaRandom(seed)
        split = r.next_int(steps // 2) + steps // 4
        steep = r.next_int(6) == 0
        yaw_v = _F(0.0)
        pitch_v = _F(0.0)
        for i in range(start, steps):
            radius = 1.5 + float(_sin(float(_F(PI_F * _F(i)) / _F(steps))) * thick)
            vradius = radius * yscale
            cp = _cos(float(pitch))
            x += float(_cos(float(yaw)) * cp)
            y += float(_sin(float(pitch)))
            z += float(_sin(float(yaw)) * cp)
            pitch = pitch * (_F(0.92) if steep else _F(0.7))
            pitch = pitch + pitch_v * _F(0.1)
            yaw = yaw + yaw_v * _F(0.1)
            pitch_v = pitch_v * _F(0.9)
            yaw_v = yaw_v * _F(0.75)
            a, b, c = r.next_float(), r.next_float(), r.next_float()
            pitch_v = pitch_v + (a - b) * c * _F(2.0)
            a, b, c = r.next_float(), r.next_float(), r.next_float()
            yaw_v = yaw_v + (a - b) * c * _F(4.0)
            if i == split and thick > _F(1.0):
                self._tunnel(r.next_long(), x, y, z, hmul, vmul, r.next_float() * _F(0.5) + _F(0.5),
                             yaw - HALF_PI_F, pitch / _F(3.0), i, steps, 1.0, out)
                self._tunnel(r.next_long(), x, y, z, hmul, vmul, r.next_float() * _F(0.5) + _F(0.5),
                             yaw + HALF_PI_F, pitch / _F(3.0), i, steps, 1.0, out)
                return
            if r.next_int(4) == 0:
                continue
            out.append((x, y, z, radius * hmul, vradius * vmul))

    # ------------------------------------------------------------------ one target chunk
    def mask(self, cx: int, cz: int) -> np.ndarray:
        """[128, 16, 16] (y, z, x) bool: the cells the caves carve in chunk (cx, cz)."""
        out = np.zeros((128, 16, 16), bool)
        mid_x, mid_z = cx * 16 + 8, cz * 16 + 8
        min_x, min_z = cx * 16, cz * 16
        xs_all = min_x + np.arange(16, dtype=np.float64)
        zs_all = min_z + np.arange(16, dtype=np.float64)
        for sx in range(cx - RANGE, cx + RANGE + 1):
            for sz in range(cz - RANGE, cz + RANGE + 1):
                ell = self.source(sx, sz)
                if not len(ell):
                    continue
                near = (np.abs(ell[:, 0] - mid_x) <= 16.0 + ell[:, 3] * 2.0) & (np.abs(ell[:, 2] - mid_z) <= 16.0 + ell[:, 3] * 2.0)
                for x, y, z, hr, vr in ell[near]:
                    xlo = max(math.floor(x - hr) - min_x - 1, 0)
                    xhi = min(math.floor(x + hr) - min_x, 15)
                    zlo = max(math.floor(z - hr) - min_z - 1, 0)
                    zhi = min(math.floor(z + hr) - min_z, 15)
                    ylo = max(math.floor(y - vr) - 1, MIN_Y)
                    yhi = min(math.floor(y + vr) + 1, MAX_Y)
                    if xlo > xhi or zlo > zhi or yhi <= ylo:
                        continue
                    dx = (xs_all[xlo:xhi + 1] + 0.5 - x) / hr
                    dz = (zs_all[zlo:zhi + 1] + 0.5 - z) / hr
                    ys = np.arange(ylo + 1, yhi + 1, dtype=np.float64)
                    dy = (ys - 0.5 - y) / vr
                    inside = (dx[None, None, :] ** 2 + dz[None, :, None] ** 2) < 1.0
                    r2 = dx[None, None, :] ** 2 + dy[:, None, None] ** 2 + dz[None, :, None] ** 2
                    m = inside & (dy[:, None, None] > FLOOR_LEVEL) & (r2 < 1.0)
                    out[ylo + 1:yhi + 1, zlo:zhi + 1, xlo:xhi + 1] |= m
        return out
