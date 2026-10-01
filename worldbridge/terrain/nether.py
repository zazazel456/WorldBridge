"""The Nether of Minecraft Alpha 1.2 - 1.12 (ChunkProviderHell), for the ring WorldBridge writes
around a converted Nether (ring3d.py).

Read from the 1.12.2 jar and compared with the b1.8.1, 1.0, 1.2.5, 1.6.4 and 1.7.10 code (the same
terrain in all of them):

* a 5 x 17 x 5 density field (two 16-octave limit noises blended by an 8-octave noise) minus a
  cosine curve over the height that closes the floor and the roof, interpolated block by block:
  netherrack where it is positive, still lava under y 32, air elsewhere;
* the surface: bedrock 0 - 4 blocks thick at the floor and the roof; between y 60 and 65 soul sand
  and gravel patches (two 4-octave noises), and lava where the ground is only a thin crust;
* the caves (MapGenCavesHell): rarer than the Overworld's (1 source chunk in 5), flatter (half as
  tall), anywhere from y 0 to 127, cut through netherrack only, never next to lava.

Alpha 1.2 - Beta 1.7.3: the same terrain; the caves use the Beta seeds and angles (``beta``).
Glowstone, fire, lava springs, quartz and fortresses come with the game's decoration.
"""

from __future__ import annotations

from typing import Tuple

import numpy as np

from .betagen import JavaRandom, PerlinOctaves, _s64
from .carvers import HALF_PI, PI, RANGE, ReleaseCarvers, _F, _floor

HEIGHT = 128
NETHERRACK, SOUL_SAND, GLOWSTONE, GRAVEL, BEDROCK, LAVA, LAVA_FLOWING = 87, 88, 89, 13, 7, 11, 10
HELL = 8
LAVA_LEVEL = 32         # still lava under this y
SURFACE = 64            # soul sand and gravel between SURFACE - 4 and SURFACE + 1


def _curve() -> np.ndarray:
    ny = 17
    c = np.empty(ny)
    for y in range(ny):
        c[y] = np.cos(y * np.pi * 6.0 / ny) * 2.0
        d = float(y if y <= ny // 2 else ny - 1 - y)
        if d < 4.0:
            d = 4.0 - d
            c[y] -= d * d * d * 10.0
    return c


_CURVE = _curve()
_ROOF = np.array([float(_F(y - 13) / _F(3.0)) if y > 13 else 0.0 for y in range(17)])


def interpolate(q: np.ndarray, ny: int, sy: int, n: int = 4, s: int = 4) -> np.ndarray:
    """The game's interpolation of a density grid [n + 1, n + 1, ny + 1] (cells of s x s x ``sy``
    blocks) into [n * s, n * s, ny * sy] densities, adding step by step in the same order (same
    rounding)."""
    out = np.empty((n, s, n, s, ny, sy))                     # cell x, x, cell z, z, cell y, y
    d1 = q[:-1, :-1, :-1].copy()
    d2 = q[:-1, 1:, :-1].copy()
    d3 = q[1:, :-1, :-1].copy()
    d4 = q[1:, 1:, :-1].copy()
    k = 1.0 / sy
    h = 1.0 / s
    d5 = (q[:-1, :-1, 1:] - d1) * k
    d6 = (q[:-1, 1:, 1:] - d2) * k
    d7 = (q[1:, :-1, 1:] - d3) * k
    d8 = (q[1:, 1:, 1:] - d4) * k
    for ly in range(sy):
        d10 = d1.copy()
        d11 = d2.copy()
        d12 = (d3 - d1) * h
        d13 = (d4 - d2) * h
        for lx in range(s):
            d15 = d10.copy()
            d16 = (d11 - d10) * h
            for lz in range(s):
                out[:, lx, :, lz, :, ly] = d15
                d15 = d15 + d16
            d10 = d10 + d12
            d11 = d11 + d13
        d1 = d1 + d5
        d2 = d2 + d6
        d3 = d3 + d7
        d4 = d4 + d8
    return out.reshape(n * s, n * s, ny * sy)


class HellCarvers(ReleaseCarvers):
    """MapGenCavesHell, in its three forms:

    * ``beta`` (Alpha 1.2 - Beta 1.7.3): Beta's source seeds and angles (3.141593F, sine table
      10430.38F); each tunnel draws its own random from the source's;
    * ``mid`` (Beta 1.8 - 1.4.7): the release seeds and angles, but still the tunnel's random drawn
      from the source's when it starts (branches included);
    * ``modern`` (1.5 - 1.12): the tunnel's seed is drawn before it is called (as the Overworld's).
    """

    def __init__(self, seed: int, era: str = "modern"):
        super().__init__(seed)
        self.era = era
        if era == "beta":
            from .betagen import _cos as bcos, _sin as bsin

            self._s, self._c = bsin, bcos
            self._pi, self._half = _F(3.141593), _F(1.570796)
        else:
            self._s, self._c = self._sin, self._cos
            self._pi, self._half = PI, HALF_PI

    def carve(self, cx: int, cz: int, blocks: np.ndarray, top_of=None) -> None:
        rnd = JavaRandom(self.seed)
        if self.era == "beta":
            a = _jdiv2(rnd.next_long()) * 2 + 1
            b = _jdiv2(rnd.next_long()) * 2 + 1
        else:
            a, b = rnd.next_long(), rnd.next_long()
        for i in range(cx - RANGE, cx + RANGE + 1):
            for j in range(cz - RANGE, cz + RANGE + 1):
                if self.era == "beta":
                    rnd.set_seed(_s64(_s64(i * a) + _s64(j * b)) ^ self.seed)
                else:
                    rnd.set_seed(_s64(i * a) ^ _s64(j * b) ^ self.seed)
                self._cave_source(rnd, i, j, cx, cz, blocks)

    def _cave_source(self, rnd: JavaRandom, i: int, j: int, cx: int, cz: int, blocks):
        n = rnd.next_int(rnd.next_int(rnd.next_int(10) + 1) + 1)
        if rnd.next_int(5) != 0:
            n = 0
        for _ in range(n):
            d = float(i * 16 + rnd.next_int(16))
            d1 = float(rnd.next_int(HEIGHT))
            d2 = float(j * 16 + rnd.next_int(16))
            k1 = 1
            if rnd.next_int(4) == 0:
                self._start(rnd, cx, cz, blocks, d, d1, d2, lambda: _F(_F(1.0) + _F(rnd.next_float() * _F(6.0))),
                            _F(0.0), _F(0.0), -1, 0.5)
                k1 += rnd.next_int(4)
            for _ in range(k1):
                f = _F(_F(rnd.next_float() * self._pi) * _F(2.0))
                f1 = _F(_F(_F(rnd.next_float() - _F(0.5)) * _F(2.0)) / _F(8.0))
                f2 = _F(_F(rnd.next_float() * _F(2.0)) + rnd.next_float())
                self._start(rnd, cx, cz, blocks, d, d1, d2, lambda: _F(f2 * _F(2.0)), f, f1, 0, 0.5)

    def _start(self, rnd, cx, cz, blocks, d, d1, d2, width, f1, f2, k, d3):
        if self.era == "modern":
            seed = rnd.next_long()
            self._tunnel(seed, cx, cz, blocks, d, d1, d2, width(), f1, f2, k, -1 if k == -1 else 0, d3)
        else:
            # the width first, then the tunnel's random from the source's
            self._old_tunnel(rnd, cx, cz, blocks, d, d1, d2, width(), f1, f2, k, -1 if k == -1 else 0, d3)

    def _carve(self, blocks, i, j, d, d1, d2, d6, d7, inside=None, wide=False) -> bool:
        x0 = max(_floor(d - d6) - i * 16 - 1, 0)
        x1 = min(_floor(d + d6) - i * 16 + 1, 16)
        y0 = max(_floor(d1 - d7) - 1, 1)
        y1 = min(_floor(d1 + d7) + 1, 120)
        z0 = max(_floor(d2 - d6) - j * 16 - 1, 0)
        z1 = min(_floor(d2 + d6) - j * 16 + 1, 16)
        if x0 >= x1 or z0 >= z1:
            return True
        # never next to lava: the box's side columns all the way, its top and bottom layers
        ya, yb = max(y0 - 1, 0), min(y1 + 1, HEIGHT - 1)
        if ya <= yb:
            box = blocks[x0:x1, z0:z1, ya:yb + 1]
            lava = (box == LAVA) | (box == LAVA_FLOWING)
            side = np.zeros(box.shape[:2], bool)
            side[0, :] = side[-1, :] = side[:, 0] = side[:, -1] = True
            if (lava & side[:, :, None]).any():
                return False
            ends = [y - ya for y in (y1 + 1, y0 - 1) if 0 <= y < HEIGHT]
            if ends and lava[:, :, ends].any():
                return False
        if y1 <= y0:
            return True
        d12 = ((np.arange(x0, x1) + i * 16) + 0.5 - d) / d6
        d13 = ((np.arange(z0, z1) + j * 16) + 0.5 - d2) / d6
        yw = np.arange(y0 + 1, y1 + 1)
        d14 = ((yw - 1) + 0.5 - d1) / d7
        inside = (d14[None, None, :] > -0.7) & (d12[:, None, None] ** 2 + d14[None, None, :] ** 2
                                                   + d13[None, :, None] ** 2 < 1.0)
        box = blocks[x0:x1, z0:z1, y0 + 1:y1 + 1]
        box[inside & ((box == NETHERRACK) | (box == 3) | (box == 2))] = 0
        return True

    def _old_tunnel(self, rnd, i, j, blocks, d, d1, d2, f, f1, f2, k, l, d3):
        sin, cos, pi, half = self._s, self._c, self._pi, self._half
        d4 = float(i * 16 + 8)
        d5 = float(j * 16 + 8)
        f3 = _F(0.0)
        f4 = _F(0.0)
        random = JavaRandom(rnd.next_long())
        if l <= 0:
            i1 = RANGE * 16 - 16
            l = i1 - random.next_int(i1 // 4)
        room = False
        if k == -1:
            k = l // 2
            room = True
        j1 = random.next_int(l // 2) + l // 4
        steep = random.next_int(6) == 0
        while k < l:
            d6 = 1.5 + float(_F(_F(sin(_F(_F(k) * pi) / _F(l))) * f) * _F(1.0))
            d7 = d6 * d3
            f5 = cos(f2)
            f6 = sin(f2)
            d += float(_F(cos(f1) * f5))
            d1 += float(f6)
            d2 += float(_F(sin(f1) * f5))
            f2 = _F(f2 * (_F(0.92) if steep else _F(0.7)))
            f2 = _F(f2 + _F(f4 * _F(0.1)))
            f1 = _F(f1 + _F(f3 * _F(0.1)))
            f4 = _F(f4 * _F(0.9))
            f3 = _F(f3 * _F(0.75))
            a, b, c = random.next_float(), random.next_float(), random.next_float()
            f4 = _F(f4 + _F(_F(_F(a - b) * c) * _F(2.0)))
            a, b, c = random.next_float(), random.next_float(), random.next_float()
            f3 = _F(f3 + _F(_F(_F(a - b) * c) * _F(4.0)))
            if not room and k == j1 and f > _F(1.0):
                w1 = _F(_F(random.next_float() * _F(0.5)) + _F(0.5))
                self._old_tunnel(rnd, i, j, blocks, d, d1, d2, w1, _F(f1 - half), _F(f2 / _F(3.0)), k, l, 1.0)
                w2 = _F(_F(random.next_float() * _F(0.5)) + _F(0.5))
                self._old_tunnel(rnd, i, j, blocks, d, d1, d2, w2, _F(f1 + half), _F(f2 / _F(3.0)), k, l, 1.0)
                return
            if room or random.next_int(4) != 0:
                d8, d9 = d - d4, d2 - d5
                d10 = float(l - k)
                d11 = float(_F(_F(f + _F(2.0)) + _F(16.0)))
                if d8 * d8 + d9 * d9 - d10 * d10 > d11 * d11:
                    return
                if not (d < d4 - 16.0 - d6 * 2.0 or d2 < d5 - 16.0 - d6 * 2.0
                        or d > d4 + 16.0 + d6 * 2.0 or d2 > d5 + 16.0 + d6 * 2.0):
                    carved = self._carve(blocks, i, j, d, d1, d2, d6, d7)
                    if room and carved:
                        break
            k += 1


def _jdiv2(v: int) -> int:
    """Java's v / 2 (rounds towards 0)."""
    return -((-v) // 2) if v < 0 else v // 2


class NetherGenerator:
    """``era`` of the caves (HellCarvers): "beta" (Alpha 1.2 - Beta 1.7.3), "mid" (Beta 1.8 - 1.4.7),
    "modern" (1.5 - 1.12)."""

    height = HEIGHT

    def __init__(self, seed: int, era: str = "modern"):
        self.seed = _s64(seed)
        r = JavaRandom(self.seed)
        self.lo = PerlinOctaves(r, 16)
        self.hi = PerlinOctaves(r, 16)
        self.main = PerlinOctaves(r, 8)
        self.patches = PerlinOctaves(r, 4)
        self.depth = PerlinOctaves(r, 4)
        self.carvers = HellCarvers(self.seed, era)

    def density(self, cx: int, cz: int) -> np.ndarray:
        """The density grid [5, 5, 17] of a chunk (netherrack where > 0 once interpolated)."""
        x, z = cx * 4, cz * 4
        main = self.main.noise(x, 0, z, 5, 17, 5, 684.412 / 80.0, 2053.236 / 60.0, 684.412 / 80.0)
        lo = self.lo.noise(x, 0, z, 5, 17, 5, 684.412, 2053.236, 684.412)
        hi = self.hi.noise(x, 0, z, 5, 17, 5, 684.412, 2053.236, 684.412)
        t = (main / 10.0 + 1.0) / 2.0
        a, b = lo / 512.0, hi / 512.0
        v = np.where(t < 0.0, a, np.where(t > 1.0, b, a + (b - a) * t))
        v = v - _CURVE[None, None, :]
        roof = _ROOF[None, None, :]
        return np.where(roof > 0.0, v * (1.0 - roof) + -10.0 * roof, v)

    def terrain(self, cx: int, cz: int) -> np.ndarray:
        d = interpolate(self.density(cx, cz), 16, 8)
        y = np.arange(HEIGHT)[None, None, :]
        return np.where(d > 0.0, NETHERRACK, np.where(y < LAVA_LEVEL, LAVA, 0)).astype(np.uint8)

    def surface(self, cx: int, cz: int, blocks: np.ndarray) -> None:
        # java.util.Random inlined (nextDouble, nextInt(5)): about 64,000 draws per chunk
        M, MASK, TOP = 0x5DEECE66D, (1 << 48) - 1, HEIGHT - 1
        st = (_s64(cx * 341873128712 + cz * 132897987541) ^ M) & MASK
        d = 0.03125
        soul = self.patches.noise(cx * 16, cz * 16, 0.0, 16, 16, 1, d, d, 1.0)[:, 0, :].tolist()
        gravel = self.patches.noise(cx * 16, 109.0, cz * 16, 16, 1, 16, d, 1.0, d).tolist()
        depth = self.depth.noise(cx * 16, cz * 16, 0.0, 16, 16, 1, d * 2.0, d * 2.0, d * 2.0)[:, 0, :].tolist()
        rows = blocks.tolist()
        for z in range(16):
            for x in range(16):
                u = []
                for _ in range(3):
                    st = (st * M + 11) & MASK
                    hi = st >> 22
                    st = (st * M + 11) & MASK
                    u.append(((hi << 27) + (st >> 21)) * (1.0 / (1 << 53)))
                sand = soul[x][z] + u[0] * 0.2 > 0.0
                grav = gravel[x][z] + u[1] * 0.2 > 0.0
                n = int(depth[x][z] / 3.0 + 3.0 + u[2] * 0.25)
                run = -1
                top = filler = NETHERRACK
                col = rows[x][z]
                for y in range(TOP, -1, -1):
                    while True:
                        st = (st * M + 11) & MASK
                        bits = st >> 17
                        r = bits % 5
                        if bits - r + 4 < 1 << 31:
                            break
                    inside = False
                    if y < TOP - r:
                        while True:
                            st = (st * M + 11) & MASK
                            bits = st >> 17
                            r = bits % 5
                            if bits - r + 4 < 1 << 31:
                                break
                        inside = y > r
                    if not inside:
                        col[y] = BEDROCK
                        continue
                    v = col[y]
                    if v == 0:
                        run = -1
                    elif v == NETHERRACK:
                        if run == -1:
                            if n <= 0:
                                top, filler = 0, NETHERRACK
                            elif SURFACE - 4 <= y <= SURFACE + 1:
                                top = filler = NETHERRACK
                                if grav:
                                    top = GRAVEL
                                if sand:
                                    top = filler = SOUL_SAND
                            if y < SURFACE and top == 0:
                                top = LAVA
                            run = n
                            col[y] = top if y >= SURFACE - 1 else filler
                        elif run > 0:
                            run -= 1
                            col[y] = filler
        blocks[:] = np.array(rows, np.uint8)

    def chunk(self, cx: int, cz: int, lift=None) -> Tuple[np.ndarray, np.ndarray]:
        """Blocks [x, z, y] of the unpopulated chunk (128 high) and its biomes (Hell)."""
        blocks = self.terrain(cx, cz)
        self.surface(cx, cz, blocks)
        self.carvers.carve(cx, cz, blocks)
        return blocks, np.full((16, 16), HELL, np.uint8)


def _point(octaves, x: float, y: float, z: float) -> float:
    """NoiseGeneratorOctaves.getValue(x, y, z) of 1.13 (one point, octave i at frequency 2^-i)."""
    total, f = 0.0, 1.0
    for o in octaves:
        total += _improved_point(o, x * f, y * f, z * f) / f
        f /= 2.0
    return total


_GX = (1, -1, 1, -1, 1, -1, 1, -1, 0, 0, 0, 0, 1, 0, -1, 0)
_GY = (1, 1, -1, -1, 0, 0, 0, 0, 1, -1, 1, -1, 1, -1, 1, -1)
_GZ = (0, 0, 0, 0, 1, 1, -1, -1, 1, 1, -1, -1, 0, 1, 0, -1)


def _improved_point(n, x: float, y: float, z: float) -> float:
    p = n.p
    x += n.xo
    y += n.yo
    z += n.zo
    xi, yi, zi = int(x), int(y), int(z)
    xi -= x < xi
    yi -= y < yi
    zi -= z < zi
    X, Y, Z = xi & 255, yi & 255, zi & 255
    x -= xi
    y -= yi
    z -= zi
    u = x * x * x * (x * (x * 6.0 - 15.0) + 10.0)
    v = y * y * y * (y * (y * 6.0 - 15.0) + 10.0)
    w = z * z * z * (z * (z * 6.0 - 15.0) + 10.0)
    a = int(p[X]) + Y
    aa = int(p[a]) + Z
    ab = int(p[a + 1]) + Z
    b = int(p[X + 1]) + Y
    ba = int(p[b]) + Z
    bb = int(p[b + 1]) + Z

    def g(h, dx, dy, dz):
        h = int(h) & 15
        return _GX[h] * dx + _GY[h] * dy + _GZ[h] * dz

    def lerp(t, a0, b0):
        return a0 + t * (b0 - a0)

    return lerp(w, lerp(v, lerp(u, g(p[aa], x, y, z), g(p[ba], x - 1.0, y, z)),
                        lerp(u, g(p[ab], x, y - 1.0, z), g(p[bb], x - 1.0, y - 1.0, z))),
                lerp(v, lerp(u, g(p[aa + 1], x, y, z - 1.0), g(p[ba + 1], x - 1.0, y, z - 1.0)),
                     lerp(u, g(p[ab + 1], x, y - 1.0, z - 1.0), g(p[bb + 1], x - 1.0, y - 1.0, z - 1.0))))


class Nether13Generator(NetherGenerator):
    """The Nether of 1.13 (ChunkGeneratorNether): the terrain of 1.12, the surface of the Nether's
    surface builder (its own noises) and the bedrock written afterwards over a 17 x 17 box that
    wraps around the chunk (so its first row and column get it twice), as the game.  No caves: the
    game carves 1.13 chunks after their "base" step."""

    def __init__(self, seed: int):
        super().__init__(seed, "modern")
        from .betagen import Perlin

        r = JavaRandom(self.seed)
        PerlinOctaves(r, 16)
        PerlinOctaves(r, 16)
        PerlinOctaves(r, 8)
        for _ in range(1048):
            r.next(1)
        self.depth13 = PerlinOctaves(r, 4)
        s = JavaRandom(self.seed)
        self.patch13 = [Perlin(s) for _ in range(4)]

    def surface(self, cx: int, cz: int, blocks: np.ndarray) -> None:
        rnd = JavaRandom(_s64(cx * 341873128712 + cz * 132897987541))
        arr = self.depth13.noise(cx * 16, cz * 16, 0.0, 16, 16, 1, 0.0625, 0.0625, 0.0625)[:, 0, :]
        rows = blocks.tolist()
        for x in range(16):
            for z in range(16):
                wx, wz = cx * 16 + x, cz * 16 + z
                sand = _point(self.patch13, wx * 0.03125, wz * 0.03125, 0.0) + rnd.next_double() * 0.2 > 0.0
                grav = _point(self.patch13, wx * 0.03125, 109.0, wz * 0.03125) + rnd.next_double() * 0.2 > 0.0
                n = int(arr[z, x] / 3.0 + 3.0 + rnd.next_double() * 0.25)
                run = -1
                top = filler = NETHERRACK
                col = rows[x][z]
                for y in range(HEIGHT - 1, -1, -1):
                    v = col[y]
                    if v == 0:
                        run = -1
                    elif v == NETHERRACK:
                        if run == -1:
                            if n <= 0:
                                top, filler = 0, NETHERRACK
                            elif SURFACE - 4 <= y <= SURFACE + 1:
                                top = filler = NETHERRACK
                                if grav:
                                    top = GRAVEL
                                if sand:
                                    top = filler = SOUL_SAND
                            if y < SURFACE and top == 0:
                                top = LAVA
                            run = n
                            col[y] = top if y >= SURFACE - 1 else filler
                        elif run > 0:
                            run -= 1
                            col[y] = filler
        for z in range(17):
            for x in range(17):
                col = rows[x & 15][z & 15]
                for y in range(HEIGHT - 1, HEIGHT - 6, -1):
                    if y >= HEIGHT - 1 - rnd.next_int(5):
                        col[y] = BEDROCK
                for y in range(4, -1, -1):
                    if y <= rnd.next_int(5):
                        col[y] = BEDROCK
        blocks[:] = np.array(rows, np.uint8)

    def chunk(self, cx: int, cz: int, lift=None) -> Tuple[np.ndarray, np.ndarray]:
        blocks = self.terrain(cx, cz)
        self.surface(cx, cz, blocks)
        return blocks, np.full((16, 16), HELL, np.uint8)
