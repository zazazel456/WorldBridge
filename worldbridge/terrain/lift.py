"""Moving a generator's terrain up or down (the ring around a converted world).

The lift acts on the generator's density field, before the surface and the caves: a column lifted
by 3.4 blocks is the game's own terrain sampled 3.4 blocks lower, so the ground stays the game's
shape (its contour lines follow the game's hills, not the lift).  The caves, carved by the game in
the unlifted terrain, move with the rock: a mountain lowered by 40 blocks keeps its caves inside,
instead of having them cut open at the surface.
"""

from __future__ import annotations

from typing import Optional

import numpy as np

from .betagen import BEDROCK, ICE, STONE, WATER

LAVA = 10
_FLUID = np.zeros(256, bool)
_FLUID[[0, 8, WATER, ICE]] = True
_XS = np.arange(16)
_YS = np.arange(128)


def density_field(q: np.ndarray) -> np.ndarray:
    """[x, z, y] density of every block from the generator's 5 x 5 x 17 (or 33) noise (trilinear, as
    the game interpolates it: 4 blocks per cell along x and z, 8 along y)."""
    ys = _YS if q.shape[2] == 17 else np.arange((q.shape[2] - 1) * 8)      # 33 levels: 256 blocks (1.7+)
    i, fi = _XS // 4, (_XS % 4) / 4.0
    k, fk = ys // 8, (ys % 8) / 8.0
    x0, x1 = (1 - fi)[:, None, None], fi[:, None, None]
    z0, z1 = (1 - fi)[None, :, None], fi[None, :, None]
    y0, y1 = (1 - fk)[None, None, :], fk[None, None, :]

    def g(di, dj, dk):
        return q[np.ix_(i + di, i + dj, k + dk)]

    return (g(0, 0, 0) * x0 * z0 * y0 + g(1, 0, 0) * x1 * z0 * y0 + g(0, 1, 0) * x0 * z1 * y0
            + g(1, 1, 0) * x1 * z1 * y0 + g(0, 0, 1) * x0 * z0 * y1 + g(1, 0, 1) * x1 * z0 * y1
            + g(0, 1, 1) * x0 * z1 * y1 + g(1, 1, 1) * x1 * z1 * y1)


def lifted_rock(d: np.ndarray, lift: np.ndarray, sea_top: int, ice: Optional[np.ndarray] = None,
                height: Optional[int] = None) -> np.ndarray:
    """Stone where the density ``d`` [x, z, y], moved up by ``lift`` [x, z] (a fraction of a block
    too), is positive; water up to ``sea_top`` elsewhere, as the game's terrain pass.  ``height``:
    blocks of the result (targets taller than the generator: a mountain lifted above its top)."""
    H = d.shape[2]
    ys = np.arange(height or H)
    t = ys[None, None, :] - np.asarray(lift, np.float64)[:, :, None]
    t0 = np.floor(t).astype(np.int64)
    f = t - t0
    a = np.take_along_axis(d, np.clip(t0, 0, H - 1), axis=2)
    b = np.take_along_axis(d, np.clip(t0 + 1, 0, H - 1), axis=2)
    v = a * (1 - f) + b * f
    v = np.where(t < 0, 1.0, np.where(t > H - 1, -1.0, v))
    y = ys[None, None, :]
    sea = np.where(y <= sea_top, WATER, 0)
    if ice is not None:
        sea = np.where((y == sea_top) & np.asarray(ice, bool)[:, :, None], ICE, sea)
    return np.where(v > 0.0, STONE, sea).astype(np.uint8)


def move_caves(moved: np.ndarray, before: np.ndarray, carved: np.ndarray, lift: np.ndarray) -> None:
    """Carve into ``moved`` the caves the game carved into the unlifted chunk (``before`` ->
    ``carved``), each column shifted by its lift; never into water, nor right under it."""
    x, z, y = np.nonzero((before != carved) & np.isin(carved, (0, LAVA, 11)))
    if not len(x):
        return
    ny = y + np.rint(np.asarray(lift)[x, z]).astype(np.int64)
    ok = (ny >= 1) & (ny <= moved.shape[2] - 2)
    x, z, ny = x[ok], z[ok], ny[ok]
    here, above = moved[x, z, ny], moved[x, z, ny + 1]
    ok = ~_FLUID[here] & (here != BEDROCK) & (above != WATER) & (above != ICE)
    x, z, ny = x[ok], z[ok], ny[ok]
    moved[x, z, ny] = np.where(ny < 10, LAVA, 0)


def lift_terrain(blocks: np.ndarray, lift: Optional[np.ndarray], sea_top: int,
                 ice: Optional[np.ndarray] = None) -> None:
    """Generators without a density field: move each column's blocks up or down by the rounded
    ``lift`` and fill the water again up to ``sea_top``."""
    if lift is None:
        return
    L = np.rint(np.asarray(lift, np.float64)).astype(np.int64)
    if not L.any():
        return
    H = blocks.shape[2]
    y = np.arange(H)[None, None, :]
    src = y - L[:, :, None]
    moved = np.take_along_axis(blocks, np.clip(src, 0, H - 1), axis=2)
    moved = np.where(src < 0, STONE, np.where(src >= H, 0, moved)).astype(blocks.dtype)
    sea = np.where(y <= sea_top, WATER, 0).astype(blocks.dtype)
    if ice is not None:
        sea = np.where((y == sea_top) & np.asarray(ice, bool)[:, :, None], ICE, sea).astype(blocks.dtype)
    moved = np.where(_FLUID[moved], sea, moved)
    moved[:, :, 0] = np.where(moved[:, :, 0] == STONE, BEDROCK, moved[:, :, 0])
    blocks[...] = moved


def value_noise(x: np.ndarray, z: np.ndarray, seed: int, scale: float) -> np.ndarray:
    """A smooth noise in [-1, 1] at any world points (lattice every ``scale`` blocks)."""
    u, v = np.asarray(x, np.float64) / scale, np.asarray(z, np.float64) / scale
    i, j = np.floor(u).astype(np.int64), np.floor(v).astype(np.int64)
    fu, fv = u - i, v - j
    fu, fv = fu * fu * (3 - 2 * fu), fv * fv * (3 - 2 * fv)

    def h(a, b):
        n = (a * 374761393 + b * 668265263 + (seed & 0xFFFFFF) * 22468225) & 0xFFFFFFFF
        n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
        return (n ^ (n >> 16)) / 2147483647.5 - 1.0

    return (h(i, j) * (1 - fu) * (1 - fv) + h(i + 1, j) * fu * (1 - fv)
            + h(i, j + 1) * (1 - fu) * fv + h(i + 1, j + 1) * fu * fv)
