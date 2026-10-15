"""The random numbers and noises of Bedrock's overworld generator before 1.18 (Bedrock Dedicated Server 1.16 - 1.17).

* ``Random``: the game's ``Core::Random``, a plain MT19937;
* ``PerlinNoise``: improved noise with the old worlds' quirk along y (3D regions and the 2D shortcut);
* ``PerlinSimplex``: simplex noise octaves (2D and 3D) for the surface;
* ``OverworldNoises``: the generator's noises built in the order of its constructor, which is the order they
  take their numbers from one stream.

Every value is a float32 and every expression is evaluated in the order the game evaluates it (one rounding per
operation, no fused multiply-add), so the results are those of the game bit for bit.  The behaviour was observed
in Bedrock Dedicated Server (see docs/SEAMLESS_BORDERS.md), not copied from any code.
"""

from __future__ import annotations

from typing import Sequence

import numpy as np

F = np.float32
_MT_N, _MT_M = 624, 397
_TO_UNIT = 2.3283064365386963e-10          # 2^-32


class Random:
    """``Core::Random``: MT19937 seeded with the unsigned 32-bit seed (the game initialises it lazily; the
    numbers are the standard stream)."""

    def __init__(self, seed: int):
        mt = [0] * _MT_N
        mt[0] = seed & 0xFFFFFFFF
        for i in range(1, _MT_N):
            p = mt[i - 1]
            mt[i] = (0x6C078965 * (p ^ (p >> 30)) + i) & 0xFFFFFFFF
        self._mt = mt
        self._i = _MT_N

    def _twist(self) -> None:
        mt = self._mt
        for k in range(_MT_N):
            y = (mt[k] & 0x80000000) | (mt[(k + 1) % _MT_N] & 0x7FFFFFFF)
            mt[k] = mt[(k + _MT_M) % _MT_N] ^ (y >> 1) ^ (0x9908B0DF if y & 1 else 0)
        self._i = 0

    def u32(self) -> int:
        """The next 32 bits."""
        if self._i >= _MT_N:
            self._twist()
        y = self._mt[self._i]
        self._i += 1
        y ^= y >> 11
        y ^= (y << 7) & 0x9D2C5680
        y ^= (y << 15) & 0xEFC60000
        y ^= y >> 18
        return y & 0xFFFFFFFF

    def next_int(self, n: int) -> int:
        """``u32 % n`` (the game's nextInt(n); 0 for n = 0)."""
        return self.u32() % n if n else 0

    def next_float(self) -> np.float32:
        """``(float)((double)u32 * 2^-32)``, in [0, 1] (rounding can reach 1.0)."""
        return F(self.u32() * _TO_UNIT)


# ------------------------------------------------------------------------------------------------ improved noise
_GRAD = np.array([(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0), (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
                  (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1), (1, 1, 0), (0, -1, 1), (-1, 1, 0), (0, -1, -1)],
                 np.float32)
_GX, _GY, _GZ = _GRAD[:, 0].copy(), _GRAD[:, 1].copy(), _GRAD[:, 2].copy()


def _fade(t):
    """((6t - 15) t + 10) t^3 with t^3 formed first (the other grouping rounds differently)."""
    return ((t * F(6.0) + F(-15.0)) * t + F(10.0)) * ((t * t) * t)


def _grad(h, x, y, z):
    g = h & 15
    return _GZ[g] * z + (_GY[g] * y + _GX[g] * x)


class ImprovedNoise:
    """One octave: three float offsets and the permutation table (256 entries, doubled)."""

    def __init__(self, rnd: Random):
        self.off = [rnd.next_float() * F(256.0) for _ in range(3)]
        p = list(range(256))
        for i in range(256):
            j = i + rnd.next_int(256 - i)
            p[i], p[j] = p[j], p[i]
        self.perm = np.array(p + p, np.int64)

    def add_region3(self, out: np.ndarray, weight: np.float32, pos: Sequence, nx: int, ny: int, nz: int,
                    scale: Sequence) -> None:
        """Add this octave's samples of a 3D region to ``out`` [x, z, y]; ``weight`` is the octave's amplitude
        divisor (the sample is multiplied by 1 / weight).  ``pos`` and ``scale`` are (x, y, z) float32.

        Along y the old worlds keep the corner values of the last cell whose index changed: a sample in the
        same cell as the previous one reuses its corner values with the previous fraction, and the samples in
        the cell that holds the octave's y offset use the offset's own fraction.  The y fade is always the
        sample's real fraction."""
        P = self.perm
        ox, oy, oz = self.off
        i = np.arange(nx, dtype=np.float32)[:, None, None]
        k = np.arange(nz, dtype=np.float32)[None, :, None]
        j = np.arange(ny, dtype=np.float32)[None, None, :]
        fx = (i + pos[0]) * scale[0] + ox
        fz = (k + pos[2]) * scale[2] + oz
        fy = (j + pos[1]) * scale[1] + oy
        xf, zf, yf = np.floor(fx), np.floor(fz), np.floor(fy)
        xr, zr, yr = fx - xf, fz - zf, fy - yf
        xi = xf.astype(np.int64) & 255
        zi = zf.astype(np.int64) & 255
        yi = yf.astype(np.int64) & 255
        xfade, zfade, yfade = _fade(xr), _fade(zr), _fade(yr)
        start = np.trunc(oy)
        at_start = np.trunc(fy) == start
        wrapped = yr - np.floor(yr / scale[1]) * scale[1]
        y_used = np.where(at_start, oy - start, wrapped).astype(np.float32)
        same_cell = np.zeros(np.broadcast(yi, at_start).shape, bool)
        same_cell[..., 1:] = yi[..., 1:] == yi[..., :-1]
        recompute = at_start | ~same_cell
        # a reused sample takes the corner values of the nearest earlier sample that was recomputed
        source = np.maximum.accumulate(np.where(recompute, np.arange(ny)[None, None, :], 0), axis=2)
        shape = np.broadcast(xi, yi, zi).shape
        xi, yi, zi = (np.broadcast_to(a, shape) for a in (xi, yi, zi))
        xr, zr, xfade = (np.broadcast_to(a, shape) for a in (xr, zr, xfade))
        y_used = np.broadcast_to(y_used, shape)
        A = P[xi] + yi
        B = P[xi + 1] + yi
        AA, AB = P[A] + zi, P[A + 1] + zi
        BA, BB = P[B] + zi, P[B + 1] + zi
        x0, x1 = xr, xr - F(1.0)
        y0, y1 = y_used, y_used - F(1.0)
        z0, z1 = zr, zr - F(1.0)
        g = _grad(P[AA], x0, y0, z0)
        c0 = (_grad(P[BA], x1, y0, z0) - g) * xfade + g
        g = _grad(P[AB], x0, y1, z0)
        c1 = (_grad(P[BB], x1, y1, z0) - g) * xfade + g
        g = _grad(P[AA + 1], x0, y0, z1)
        c2 = (_grad(P[BA + 1], x1, y0, z1) - g) * xfade + g
        g = _grad(P[AB + 1], x0, y1, z1)
        c3 = (_grad(P[BB + 1], x1, y1, z1) - g) * xfade + g
        take = np.broadcast_to(source, shape)
        c0, c1, c2, c3 = (np.take_along_axis(v, take, axis=2) for v in (c0, c1, c2, c3))
        yfade = np.broadcast_to(yfade, shape)
        v0 = (c1 - c0) * yfade + c0
        v1 = (c3 - c2) * yfade + c2
        out += ((v1 - v0) * np.broadcast_to(zfade, shape) + v0) * (F(1.0) / weight)

    def add_region2(self, out: np.ndarray, weight: np.float32, x: float, z: float, nx: int, nz: int,
                    scale: Sequence) -> None:
        """The 2D shortcut of the game (a region one block high, y ignored) added to ``out`` [x, z]."""
        P = self.perm
        ox, _oy, oz = self.off
        i = np.arange(nx, dtype=np.float32)[:, None]
        k = np.arange(nz, dtype=np.float32)[None, :]
        fx = (i + F(x)) * scale[0] + ox
        fz = (k + F(z)) * scale[2] + oz
        xf, zf = np.floor(fx), np.floor(fz)
        xr, zr = fx - xf, fz - zf
        xi = xf.astype(np.int64) & 255
        zi = zf.astype(np.int64) & 255
        xfade, zfade = _fade(xr), _fade(zr)
        shape = np.broadcast(xi, zi).shape
        xi, zi, xr, zr, xfade, zfade = (np.broadcast_to(a, shape) for a in (xi, zi, xr, zr, xfade, zfade))
        h0 = P[P[xi]] + zi
        h1 = P[P[xi + 1]] + zi

        def grad2(h, gx, gz):
            gi = h & 15
            return _GZ[gi] * gz + _GX[gi] * gx

        x1, z1 = xr - F(1.0), zr - F(1.0)
        a = grad2(P[h0], xr, zr)
        a = (grad2(P[h1], x1, zr) - a) * xfade + a
        b = grad2(P[h0 + 1], xr, z1)
        b = (grad2(P[h1 + 1], x1, z1) - b) * xfade + b
        out += ((b - a) * zfade + a) * (F(1.0) / weight)


class PerlinNoise:
    """Octave k of the sum is sampled at ``scale * 2^-k`` and weighs ``2^k`` less."""

    def __init__(self, rnd: Random, octaves: int):
        self.octaves = [ImprovedNoise(rnd) for _ in range(octaves)]

    def region3(self, pos: Sequence, nx: int, ny: int, nz: int, scale: Sequence) -> np.ndarray:
        """[x, z, y] samples of the box starting at ``pos`` (x, y, z)."""
        out = np.zeros((nx, nz, ny), np.float32)
        f = F(1.0)
        pos = [F(v) for v in pos]
        for octave in self.octaves:
            octave.add_region3(out, f, pos, nx, ny, nz, [F(s) * f for s in scale])
            f = f * F(0.5)
        return out

    def region2(self, x: float, z: float, nx: int, nz: int, sx: float, sz: float) -> np.ndarray:
        """[x, z] samples with the 2D shortcut."""
        out = np.zeros((nx, nz), np.float32)
        f = F(1.0)
        for octave in self.octaves:
            octave.add_region2(out, f, x, z, nx, nz, [F(sx) * f, f, F(sz) * f])
            f = f * F(0.5)
        return out


# ------------------------------------------------------------------------------------------------ simplex
_F2 = F(0.5) * (np.sqrt(F(3.0)) - F(1.0))
_G2 = F((3.0 - np.sqrt(3.0)) / 6.0)
_F3 = F(0.33333334)
_G3 = F(0.16666667)
_GRAD3 = np.array([(1, 1, 0), (-1, 1, 0), (1, -1, 0), (-1, -1, 0), (1, 0, 1), (-1, 0, 1), (1, 0, -1), (-1, 0, -1),
                   (0, 1, 1), (0, -1, 1), (0, 1, -1), (0, -1, -1)], np.float32)


def _lattice_floor(v):
    """``(int)v - (v <= 0)``: the game's floor for the simplex lattice (not the same as floor() for v <= 0)."""
    return np.trunc(v).astype(np.int64) - (v <= F(0.0)).astype(np.int64)


class SimplexOctave:
    """One simplex octave.  Its numbers come from the stream as three draws (the offsets are kept in reverse
    order: x takes the third) and the 256 permutation swaps."""

    def __init__(self, rnd: Random):
        d1, d2, d3 = rnd.u32(), rnd.u32(), rnd.u32()
        unit = lambda u: F(u * _TO_UNIT) * F(256.0)  # noqa: E731
        self.off = (unit(d3), unit(d2), unit(d1))
        p = list(range(256))
        for i in range(256):
            j = i + rnd.u32() % (256 - i)
            p[i], p[j] = p[j], p[i]
        self.perm = np.array(p + p, np.int64)

    def value2(self, x, y):
        """Noise at 2D points (float32 arrays)."""
        P = self.perm
        s = (x + y) * _F2
        i = _lattice_floor(x + s)
        j = _lattice_floor(s + y)
        t = (i + j).astype(np.float32) * _G2
        x0 = x - (i.astype(np.float32) - t)
        y0 = y - (j.astype(np.float32) - t)
        i1 = (y0 < x0).astype(np.int64)
        j1 = 1 - i1
        x1 = (x0 - i1.astype(np.float32)) + _G2
        y1 = (y0 - j1.astype(np.float32)) + _G2
        ii, jj = i & 255, j & 255
        g0 = P[ii + P[jj]] % 12
        g1 = P[ii + i1 + P[jj + j1]] % 12
        g2 = P[ii + 1 + P[jj + 1]] % 12
        x2 = ((x0 + F(-1.0)) + _G2) + _G2
        y2 = ((y0 + F(-1.0)) + _G2) + _G2

        def corner(cx, cy, g):
            tt = (F(0.5) - cx * cx) - cy * cy
            v = (cy * _GRAD3[g, 1] + cx * _GRAD3[g, 0]) * (((tt * tt) * tt) * tt)   # t^4 formed first
            return np.where(tt >= F(0.0), v, F(0.0)).astype(np.float32)

        return ((corner(x0, y0, g0) + corner(x1, y1, g1)) + corner(x2, y2, g2)) * F(70.0)

    def value3(self, x, y, z):
        """Noise at 3D points (float32 arrays)."""
        P = self.perm
        s = ((x + y) + z) * _F3
        i, j, k = _lattice_floor(x + s), _lattice_floor(y + s), _lattice_floor(s + z)
        t = (i + j + k).astype(np.float32) * _G3
        x0 = x - (i.astype(np.float32) - t)
        y0 = y - (j.astype(np.float32) - t)
        z0 = z - (k.astype(np.float32) - t)
        zero, one = np.zeros(x0.shape, np.int64), np.ones(x0.shape, np.int64)
        a, b, c, d, e = y0 <= x0, z0 <= y0, x0 < z0, y0 < z0, z0 > x0
        c1 = a & b                       # x >= y >= z
        c2 = a & ~b & ~c                 # x >= z > y
        c3 = a & ~b & c                  # z > x >= y
        c4 = ~a & d                      # z > y > x
        c5 = ~a & ~d                     # y >= z, y > x
        i1 = np.where(c1 | c2, one, zero)
        j1 = np.where(c5, one, zero)
        k1 = np.where(c3 | c4, one, zero)
        i2 = np.where(c1 | c2 | c3 | (c5 & ~e), one, zero)
        j2 = np.where(c1 | c4 | c5, one, zero)
        k2 = np.where(c2 | c3 | c4 | (c5 & e), one, zero)
        x1, y1, z1 = ((x0 - i1.astype(np.float32)) + _G3, (y0 - j1.astype(np.float32)) + _G3,
                      (z0 - k1.astype(np.float32)) + _G3)
        x2, y2, z2 = ((x0 - i2.astype(np.float32)) + _F3, (y0 - j2.astype(np.float32)) + _F3,
                      (z0 - k2.astype(np.float32)) + _F3)
        x3, y3, z3 = (x0 + F(-1.0)) + F(0.5), (y0 + F(-1.0)) + F(0.5), (z0 + F(-1.0)) + F(0.5)
        ii, jj, kk = i & 255, j & 255, k & 255
        g0 = P[ii + P[jj + P[kk]]] % 12
        g1 = P[ii + i1 + P[jj + j1 + P[kk + k1]]] % 12
        g2 = P[ii + i2 + P[jj + j2 + P[kk + k2]]] % 12
        g3 = P[ii + 1 + P[jj + 1 + P[kk + 1]]] % 12

        def corner(cx, cy, cz, g):
            tt = ((F(0.6) - cx * cx) - cy * cy) - cz * cz
            v = (cz * _GRAD3[g, 2] + (cy * _GRAD3[g, 1] + cx * _GRAD3[g, 0])) * (((tt * tt) * tt) * tt)
            return np.where(tt >= F(0.0), v, F(0.0)).astype(np.float32)

        return (((corner(x0, y0, z0, g0) + corner(x1, y1, z1, g1)) + corner(x2, y2, z2, g2))
                + corner(x3, y3, z3, g3)) * F(32.0)


class PerlinSimplex:
    """Octaves of simplex noise, each at twice the frequency and half the weight of the one before."""

    def __init__(self, rnd: Random, octaves: int):
        self.octaves = [SimplexOctave(rnd) for _ in range(octaves)]
        total = F(0.0)
        for j in range(octaves):
            total = total + F(2.0 ** j)
        self.norm = F(1.0) / total if octaves else F(0.0)

    def value2(self, x, y):
        """Sum of the octaves at 2D points (one point or arrays)."""
        x, y = np.asarray(x, np.float32), np.asarray(y, np.float32)
        acc = np.zeros(np.broadcast(x, y).shape, np.float32)
        f = F(1.0)
        for octave in self.octaves:
            acc = acc + octave.value2(f * x, f * y) / f
            f = f * F(0.5)
        return acc

    def value3_normalized(self, x, y, z):
        """Sum of the octaves at 3D points, divided by the sum of their weights."""
        x, y, z = (np.asarray(a, np.float32) for a in (x, y, z))
        acc = np.zeros(np.broadcast(x, y, z).shape, np.float32)
        f = F(1.0)
        for octave in self.octaves:
            acc = acc + octave.value3(f * x, f * y, f * z) / f
            f = f * F(0.5)
        return acc * self.norm

    def region2(self, px: float, pz: float, nx: int, nz: int, sx: float, sz: float) -> np.ndarray:
        """[z, x] values of a region (the surface noise): octave k, at f = 2^-k of the frequency, adds its
        noise weighted 0.55 / f."""
        out = np.zeros((nz, nx), np.float32)
        f = F(1.0)
        xs = np.arange(nx, dtype=np.float32)[None, :]
        zs = np.arange(nz, dtype=np.float32)[:, None]
        for octave in self.octaves:
            xx = np.broadcast_to((((xs + F(px)) * F(sx)) * F(1.0)) * f + octave.off[0], out.shape)
            zz = np.broadcast_to((((zs + F(pz)) * F(sz)) * F(1.0)) * f + octave.off[1], out.shape)
            out = octave.value2(xx, zz) * (F(0.55) / f) + out
            f = f * F(0.5)
        return out


# ------------------------------------------------------------------------------------------------ the generator's noises
def _skip(rnd: Random, octaves: int) -> None:
    """A noise whose numbers are drawn but never used: 3 + 256 draws per octave."""
    for _ in range(octaves * (3 + 256)):
        rnd.u32()


class OverworldNoises:
    """The noises of ``OverworldGenerator``, in the order of its constructor (one stream, so the order is the
    numbers): the lower and upper limit, the main noise, the surface simplex, the (unused) scale noise, the
    depth noise, the (unused) forest noise and the simplex of the surface material adjustments."""

    def __init__(self, seed: int):
        rnd = Random(seed)
        self.min_limit = PerlinNoise(rnd, 16)
        self.max_limit = PerlinNoise(rnd, 16)
        self.main = PerlinNoise(rnd, 8)
        self.surface = PerlinSimplex(rnd, 4)
        _skip(rnd, 10)
        self.depth = PerlinNoise(rnd, 16)
        _skip(rnd, 8)
        self.extra = PerlinSimplex(rnd, 3)
