"""The ring around a converted Nether or End (docs/SEAMLESS_BORDERS.md).

The Overworld's ring lifts a height field; the Nether is a cave world (floors, ceilings,
overhangs, a lava sea) and the End a set of floating islands, so their ring blends in 3D:

* every column of the ring takes, from the converted border column nearest to it, the pattern of
  rock and open space over the height, and from the target's own generator (nether.py, end.py,
  dims16.py: the game's terrain, bit for bit) its own pattern;
* both patterns become a vertical signed distance (how many blocks to the nearest change between
  rock and open space, positive in rock) and are mixed with a weight that is 1 at the converted
  border and 0 at the ring's outer edge (a smooth step over WIDTH chunks): floors, ceilings and
  islands slide from one height to the other instead of stopping against a wall;
* where the ring is rock its block is the generator's (netherrack, soul sand, gravel, end stone) or
  the converted border's natural block; open space below the lava sea is lava as in the game;
  the bedrock floor and roof of the Nether are the generator's.

Buildings, fortresses, glowstone, pillars and plants of the converted border are not carried into
the ring (they are not terrain).  At the outer edge the ring is exactly the game's terrain.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

from ..model import NETHER, THE_END, NumericChunk, Progress
from ..i18n import tr

WIDTH = 4               # chunks
BEND = 12.0             # blocks: how far a noise moves the point that looks for its border column
BEND_SCALE = 1.0 / 40.0
WOBBLE = 0.3            # share of the ring's width the weight's contour lines move by
CLIP = 64.0             # blocks: the farthest a change of kind is looked for
LAVA_Y = 32             # the Nether's lava sea: open space under this y is lava
NETHERRACK, SOUL_SAND, GRAVEL, BEDROCK, END_STONE = 87, 88, 13, 7, 121

# Java 1.12 ids of the terrain of each dimension (the rest is open space for the blend)
_NETHER_ROCK = np.zeros(4096, bool)
_NETHER_ROCK[[1, 2, 3, 4, 7, 12, 13, 49, 87, 88, 153, 213]] = True
_END_ROCK = np.zeros(4096, bool)
_END_ROCK[[121]] = True
# what the converted border's rock becomes in the ring
_NETHER_MAT = np.full(4096, NETHERRACK, np.uint16)
_NETHER_MAT[[SOUL_SAND, GRAVEL]] = [SOUL_SAND, GRAVEL]


def _axis_runs(solid: np.ndarray, axis: int, edge) -> np.ndarray:
    """Blocks from every cell to the nearest cell of the other kind along ``axis`` (both ways);
    ``edge``: the kind beyond the array's ends (None: unknown, nothing is found there)."""
    a = np.moveaxis(solid, axis, 0)
    n = a.shape[0]
    big = float(CLIP)
    out = np.full(a.shape, big)
    for order in (range(n), range(n - 1, -1, -1)):
        prev = np.full(a.shape[1:], bool(edge)) if edge is not None else None
        run = np.full(a.shape[1:], big if edge is not None else big)
        for i in order:
            s = a[i]
            if prev is None:
                run = np.full(a.shape[1:], big)
            else:
                run = np.where(s == prev, run + 1.0, 1.0)
            out[i] = np.minimum(out[i], np.minimum(run, big))
            prev = s
    return np.moveaxis(out, 0, axis)


def _signed_distance(solid: np.ndarray, edge_solid: bool) -> np.ndarray:
    """[X, Z, Y] bool -> signed distance (positive in rock): the nearest change of kind along x, z
    or y, whichever is closest (above and below the world count as rock when ``edge_solid``)."""
    d = np.minimum(np.minimum(_axis_runs(solid, 0, None), _axis_runs(solid, 1, None)),
                   _axis_runs(solid, 2, edge_solid))
    d = d - 0.5
    return np.where(solid, d, -d)


class Ring3D:
    """``gen.chunk(cx, cz)`` -> (blocks [x, z, y] Java ids, biomes [x, z]); ``dim``: NETHER or
    THE_END; ``noise_only``: the target finishes the chunks itself from its "noise" step (1.14 -
    1.17), so the ring has no bedrock of its own and only rock, lava and air."""

    def __init__(self, gen, dim: int, converted: Iterable[Tuple[int, int]], dy: int = 0, seed: int = 0,
                 width: int = WIDTH, noise_only: bool = False):
        self.gen = gen
        self.dim = dim
        self.dy = dy
        self.seed = seed
        self.width = width
        self.noise_only = noise_only
        self.H = int(getattr(gen, "height", 128))
        self.converted: Set[Tuple[int, int]] = set(converted)
        self.edge_chunks: Set[Tuple[int, int]] = {
            (x, z) for x, z in self.converted
            if any((x + dx, z + dz) not in self.converted for dx in (-1, 0, 1) for dz in (-1, 0, 1))}
        self.rock = _NETHER_ROCK if dim == NETHER else _END_ROCK
        # border columns: world x, z, rock [Y], material [Y]
        self._bx: List[int] = []
        self._bz: List[int] = []
        self._brock: List[np.ndarray] = []
        self._bmat: List[np.ndarray] = []
        self._arrays = None
        self.written: List[Tuple[int, int]] = []
        from .betagen import JavaRandom, Simplex

        r = JavaRandom((seed ^ 0x5EA11E55) & 0xFFFFFFFFFFFF)
        self._bend = (Simplex(r), Simplex(r))

    # ---------------------------------------------------------------- converted side
    def observe(self, dim: int, c: NumericChunk) -> None:
        if dim != self.dim or (c.cx, c.cz) not in self.edge_chunks:
            return
        H = self.H
        b = np.asarray(c.blocks).astype(np.int64)                  # y, z, x
        moved = np.zeros((H, 16, 16), np.int64)
        lo, hi = max(self.dy, 0), min(H, b.shape[0] + self.dy)
        if hi > lo:
            moved[lo:hi] = b[lo - self.dy:hi - self.dy]
        if self.dy > 0 and self.dim == NETHER:
            moved[:self.dy] = BEDROCK
        rock = self.rock[moved]
        mat = _NETHER_MAT[moved] if self.dim == NETHER else np.full(moved.shape, END_STONE)
        lava = np.isin(moved, (10, 11))
        mat = np.where(rock, mat, np.where(lava, 11, 0))
        conv = self.converted
        for z in range(16):
            for x in range(16):
                wx, wz = c.cx * 16 + x, c.cz * 16 + z
                if all(((wx + dx) >> 4, (wz + dz) >> 4) in conv for dx in (-1, 0, 1) for dz in (-1, 0, 1)):
                    continue
                self._bx.append(wx)
                self._bz.append(wz)
                self._brock.append(rock[:, z, x])
                self._bmat.append(mat[:, z, x].astype(np.uint16))
        self._arrays = None

    def _border(self):
        if self._arrays is None:
            if not self._bx:
                self._arrays = (np.zeros(0), np.zeros(0), np.zeros((0, self.H), bool), np.zeros((0, self.H), np.uint16))
            else:
                rock = np.array(self._brock)
                self._arrays = (np.array(self._bx, np.float64), np.array(self._bz, np.float64), rock,
                                np.array(self._bmat))
        return self._arrays

    # ---------------------------------------------------------------- targets
    def targets(self) -> List[Tuple[int, int]]:
        w = self.width
        out = set()
        for x, z in self.edge_chunks:
            for dx in range(-w, w + 1):
                for dz in range(-w, w + 1):
                    c = (x + dx, z + dz)
                    if c not in self.converted:
                        out.add(c)
        return sorted(out)

    # ---------------------------------------------------------------- blend
    def _nearest(self, x0: int, z0: int, n: int):
        """For the n x n columns from x0, z0: the nearest converted border column and the weight of
        the converted side (1 at the border, 0 WIDTH chunks away)."""
        bx, bz = self._border()[:2]
        L = float(self.width * 16)
        X = (x0 + np.arange(n, dtype=np.float64))[:, None]
        Z = (z0 + np.arange(n, dtype=np.float64))[None, :]
        near = (bx >= x0 - L - 24) & (bx <= x0 + n + L + 24) & (bz >= z0 - L - 24) & (bz <= z0 + n + L + 24)
        idx = np.nonzero(near)[0]
        if not len(idx):
            return None, np.zeros((n, n))
        X, Z = np.broadcast_arrays(X, Z)

        def search(QX, QZ):
            best = np.full((n, n), np.inf)
            out = np.zeros((n, n), np.int64)
            for chunk in np.array_split(idx, max(1, len(idx) // 512)):
                d2 = (QX[:, :, None] - bx[chunk][None, None, :]) ** 2 + (QZ[:, :, None] - bz[chunk][None, None, :]) ** 2
                k = np.argmin(d2, axis=2)
                v = np.take_along_axis(d2, k[:, :, None], axis=2)[:, :, 0]
                better = v < best
                best = np.where(better, v, best)
                out = np.where(better, chunk[k], out)
            return out, np.sqrt(best)

        src, dist = search(X, Z)
        # the border's rock is carried outwards along bent lines, not straight prisms: the point that
        # looks for its border column moves with a noise, not at all at the border itself
        from .modern16 import _simplex2

        amount = BEND * np.clip(dist / 16.0, 0.0, 1.0)
        dx = _simplex2(self._bend[0], X * BEND_SCALE, Z * BEND_SCALE) * amount
        dz = _simplex2(self._bend[1], X * BEND_SCALE, Z * BEND_SCALE) * amount
        src, _ = search(X + dx, Z + dz)
        # the weight's contour lines bend as well (else an island or a cliff of the game coming into
        # the ring would be cut along lines parallel to the converted border); not at the ring's two
        # edges, where the weight must be exactly 1 and 0
        t = np.clip(dist / L, 0.0, 1.0)
        wobble = _simplex2(self._bend[0], X * BEND_SCALE + 57.3, Z * BEND_SCALE - 11.9)
        t = np.clip(t + WOBBLE * wobble * np.sin(np.pi * t), 0.0, 1.0)
        return src, 1.0 - t * t * (3.0 - 2.0 * t)

    def blend(self, cx: int, cz: int, gen: Dict[Tuple[int, int], np.ndarray]) -> np.ndarray:
        """The ring chunk [x, z, y] from the generator's chunks around it (3 x 3) and the converted
        border: the rock of both sides as signed distances, mixed by the weight of each column."""
        H = self.H
        g = gen[(cx, cz)].astype(np.int64)
        brock, bmat = self._border()[2:4]
        src, w = self._nearest(cx * 16 - 16, cz * 16 - 16, 48)
        if src is None or not (w[16:32, 16:32] > 0).any():
            return g.astype(np.uint8)
        edge_solid = self.dim == NETHER
        grock = np.zeros((48, 48, H), bool)
        for i in range(3):
            for j in range(3):
                b = gen.get((cx + i - 1, cz + j - 1))
                if b is None:
                    b = g                                             # (never happens: the neighbours are generated)
                grock[i * 16:i * 16 + 16, j * 16:j * 16 + 16] = self.rock[b] | (b == BEDROCK)
        crock = brock[src]                                            # [48, 48, H] the border, carried outwards
        gsd = _signed_distance(grock, edge_solid)[16:32, 16:32]
        csd = _signed_distance(crock, edge_solid)[16:32, 16:32]
        w = w[16:32, 16:32]
        W = w[:, :, None]
        mix = W * csd + (1.0 - W) * gsd
        solid = np.where(mix == 0.0, np.where(W >= 0.5, csd > 0, gsd > 0), mix > 0)
        cmat = bmat[src[16:32, 16:32]].astype(np.int64)
        grock_c = grock[16:32, 16:32]
        default = NETHERRACK if self.dim == NETHER else END_STONE
        conv_rock = np.where((cmat > 0) & ~np.isin(cmat, (10, 11)), cmat, default)
        rock_block = np.where(grock_c & (g != BEDROCK), g, conv_rock)
        if self.dim == NETHER:
            y = np.arange(H)[None, None, :]
            gopen = np.where(np.isin(g, (10, 11)), 11, 0)
            copen = np.where(cmat == 11, 11, 0)
            open_block = np.where(W >= 0.5, copen, gopen)
            open_block = np.where((open_block == 0) & (y < LAVA_Y) & ((gopen == 11) | (copen == 11)), 11, open_block)
        else:
            open_block = 0
        out = np.where(solid, rock_block, open_block)
        if self.dim == NETHER and not self.noise_only:
            # the generator's bedrock floor and roof (and what lies between them there)
            out[:, :, :5] = g[:, :, :5]
            out[:, :, H - 5:] = g[:, :, H - 5:]
        keep = w <= 0.0
        out[keep] = g[keep]
        return out.astype(np.uint8)

    # ---------------------------------------------------------------- generation
    def _generated(self, targets):
        """(cx, cz, the generator's chunk) in order, made on every core (parallel.py)."""
        from ..parallel import ordered_map
        from .ring import _gen_chunk

        jobs = [(cx, cz, None) for cx, cz in targets]
        for (cx, cz), out in zip(targets, ordered_map(_gen_chunk, self.gen, jobs, batch=4, min_items=16)):
            yield cx, cz, out

    def chunks(self, progress: Optional[Progress] = None) -> Iterable[NumericChunk]:
        if not self.edge_chunks:
            return
        targets = self.targets()
        need = sorted({(x + dx, z + dz) for x, z in targets for dx in (-1, 0, 1) for dz in (-1, 0, 1)})
        gen: Dict[Tuple[int, int], np.ndarray] = {}
        biomes: Dict[Tuple[int, int], np.ndarray] = {}
        wanted = set(targets)
        nether = self.dim == NETHER
        for n, (cx, cz, out) in enumerate(self._generated(need)):
            gen[(cx, cz)] = np.asarray(out[0], np.uint8)
            if (cx, cz) in wanted:
                biomes[(cx, cz)] = np.asarray(out[1])
            if progress is not None and n % 32 == 0:
                progress.update(0.05 + 0.5 * n / max(1, len(need)), (tr("Nether terrain {i}/{n}", i=n, n=len(need)) if nether else tr("End terrain {i}/{n}", i=n, n=len(need))))
        self.written = []
        from ..parallel import ordered_map

        # the blend of every chunk on every core: the workers inherit the generated terrain
        for n, c in enumerate(ordered_map(_blend_chunk, (self, gen, biomes), targets, batch=4, min_items=16)):
            self.written.append((c.cx, c.cz))
            if progress is not None and n % 16 == 0:
                progress.update(0.55 + 0.45 * n / max(1, len(targets)), (tr("Nether ring {i}/{n}", i=n, n=len(targets)) if nether else tr("End ring {i}/{n}", i=n, n=len(targets))))
            yield c


def _blend_chunk(state, c: Tuple[int, int]) -> NumericChunk:
    """The ring chunk ``c`` (worker function, parallel.py): ``state`` = (ring, generated terrain, biomes)."""
    ring3d, gen, biomes = state
    cx, cz = c
    ring = ring3d.blend(cx, cz, gen)
    out = NumericChunk(cx, cz, max(ring3d.H, 128))
    out.blocks[:ring.shape[2]] = np.transpose(ring, (2, 1, 0))
    out.biomes = biomes[(cx, cz)].T.astype(np.uint8)
    out.terrain_populated = False
    return out


def generator(target, seed: int, dim: int):
    """The target's Nether or End generator and whether the game finishes the chunks from their
    noise step; None when WorldBridge has none (or the target has no such dimension)."""
    from . import ring as ring_mod

    lim = ring_mod._limit(target)
    if not lim:
        return None
    if dim == NETHER:
        if lim in ring_mod.BETA_GEN_LIMITS:
            from .nether import NetherGenerator

            return NetherGenerator(seed, "beta"), False
        if lim in ("b1.8", "1.0", "1.1", "1.2", "1.3", "1.4"):
            from .nether import NetherGenerator

            return NetherGenerator(seed, "mid"), False
        if lim in ("1.5", "1.6") or lim in ring_mod.MODERN_GEN_LIMITS:
            from .nether import NetherGenerator

            return NetherGenerator(seed, "modern"), False
        if lim == "1.13":
            from .nether import Nether13Generator

            return Nether13Generator(seed), False
        if lim in ring_mod.NOISE_GEN_LIMITS:
            from .dims16 import Nether16Generator

            return Nether16Generator(seed, lim), True
        return None
    if dim == THE_END:
        if lim in ring_mod.BETA_GEN_LIMITS or lim == "b1.8":
            return None                                  # no End before 1.0
        from .end import EndGenerator

        if lim in ("1.0", "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7", "1.8"):
            return EndGenerator(seed, islands=False), False
        if lim in ("1.9", "1.10", "1.11", "1.12"):
            return EndGenerator(seed, islands=True), False
        if lim == "1.13":
            return EndGenerator(seed, version="1.13"), False
        if lim in ring_mod.NOISE_GEN_LIMITS:
            from .dims16 import End16Generator

            return End16Generator(seed, lim), True
    return None

