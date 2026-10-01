"""Smooth border between a converted world and the terrain the game generates around it.

Games older than 1.18 (Java) do not blend.  WorldBridge writes terrain around the converted area
with a generator:

* **ring** (infinite worlds): the game's own generator (betagen for Alpha 1.2 - Beta 1.7.3,
  releasegen for Beta 1.8 - 1.1, bit for bit);
* **fill** (finite worlds, LCE and PE 0.x): every chunk of the map that the conversion does not
  write is written, from the fast filler (filler.py): the game never generates anything, so there
  is nothing to meet.

The ring is the generator's real terrain (its hills, valleys, overhangs, surfaces, beaches and
caves), *lifted*: every column's rock moves up or down by a smooth amount that is, at the converted
border, the difference between the converted ground and the generator's, and goes to 0 at the
ring's outer edge, where the ring is exactly what the game generates next.  The lift is the
smoothest surface between the two borders (a harmonic function, solved once over the whole ring),
so it has no seams at chunk borders and no streaks; the last few blocks of difference right at the
border fade within SEAM blocks.

The width follows the height difference to cover: 3 chunks, up to 12 where a mountain meets the
plain, so the slope stays natural.  The chunks are written unpopulated, so the game adds its ores,
lakes and trees; the ring also gets the converted border's own trees, thinning out towards its
outer edge, so that a forest does not stop dead at the border.  Water never stands as a wall: the ring
does not go under the sea where the converted border is dry there, and its blocks where water would
run into air are sealed with ground (``Ring._seal``).
"""

from __future__ import annotations

import math
import os
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

from ..model import LIGHT_OPACITY, NumericChunk, OVERWORLD, Progress
from . import lift as lift_mod
from . import trees
from .betagen import DIRT, GRASS, GRAVEL, ICE, SAND, SANDSTONE, STONE, WATER, BetaGenerator
from ..i18n import tr

# targets whose world generator is the one of Alpha 1.2 - Beta 1.7.3, and of Beta 1.8 - 1.1
BETA_GEN_LIMITS = {"alpha", "b1.2", "b1.3", "b1.4", "b1.5", "b1.6", "b1.7"}
RELEASE_GEN_LIMITS = {"b1.8": "b1.8", "1.0": "1.0", "1.1": "1.1", "1.2": "1.2", "1.3": "1.3", "1.4": "1.4",
                      "1.5": "1.5", "1.6": "1.6"}
MODERN_GEN_LIMITS = {"1.7", "1.8", "1.9", "1.10", "1.11", "1.12"}      # modern.py (Anvil, 256 high)
NOISE_GEN_LIMITS = {"1.13", "1.14", "1.15", "1.16", "1.17"}            # modern16.py (Amulet targets)
# the status of the ring's chunks in 1.14 - 1.17: noise and surface done, the game carves and decorates
RING_STATUS = "surface"
RING = 3        # chunks, the narrowest ring
MAX_RING = 12   # chunks, the widest
SLOPE = 0.5     # the steepest average slope of the ring: 1 block every 2 columns
OUTER = 0.08    # the lift is 0 where phi (1 at the converted border, 0 outside) is below this
BEND = 14.0     # blocks: how far the noise moves the ring's contour lines
SWELL = 0.25    # swells laid on the ring's slope (share of the lift, in the middle of the ring)
SEAM = 8        # blocks: the last differences at the converted border fade within this distance
MAX_TREES = 12  # per chunk, planted by WorldBridge (the game adds the trees of its biomes)
_MAX_CELLS = 2_500_000   # cells of the lift field per connected piece of ring

# Java 1.12 ids of natural ground (the height the ring starts from); water / ice are "above ground"
_GROUND = np.zeros(4096, bool)
_GROUND[[1, 2, 3, 7, 12, 13, 14, 15, 16, 21, 24, 49, 56, 73, 74, 80, 82, 110, 159, 172, 174, 179, 208]] = True
# Java 1.12 ids water and lava flow into (air and plants), the fluids, and what a sealed block is made of
_OPEN = np.zeros(4096, bool)
_OPEN[[0, 6, 31, 32, 37, 38, 39, 40, 50, 51, 59, 78, 83, 104, 105, 106, 111, 141, 142, 175]] = True
_FLUID = np.zeros(4096, bool)
_FLUID[[8, 9, 10, 11]] = True
_SEAL = np.full(4096, STONE, np.uint16)
_SEAL[[STONE, DIRT, SAND, GRAVEL, SANDSTONE, 82, 159, 172]] = [STONE, DIRT, SAND, GRAVEL, SANDSTONE, 82, 159, 172]
_SEAL[[GRASS, 110]] = DIRT
# ground block ids -> a surface every old game has (top, filler)
_SURFACE = {2: (GRASS, DIRT), 3: (GRASS, DIRT), 110: (GRASS, DIRT), 208: (GRASS, DIRT), 12: (SAND, SAND),
            24: (SAND, SANDSTONE), 13: (GRAVEL, GRAVEL), 82: (DIRT, DIRT), 80: (GRASS, DIRT)}


def _limit(target) -> str:
    mode = getattr(target, "java_mode", "")
    if getattr(target, "family", "") == "java" and mode == "amulet":
        v = tuple(getattr(target, "version", None) or (99,))
        return f"1.{v[1]}" if len(v) > 1 and v[0] == 1 and 13 <= v[1] <= 17 else ""
    if getattr(target, "family", "") != "java" or mode not in ("mcregion", "alpha", "numeric"):
        return ""
    return getattr(target, "java_version_limit", None) or {"alpha": "b1.2", "mcregion": "b1.7"}.get(mode, "1.12")


def beta_sea(target) -> bool:
    """Alpha 1.2 - Beta 1.7.3: their sea is one block higher than in every later version."""
    return _limit(target) in BETA_GEN_LIMITS


def supported(target, world_type: str = "default") -> bool:
    """WorldBridge has the target's own world generator (so it can write the ring).  ``world_type``:
    the level's generatorName; "customized" worlds (1.8+) have settings of their own."""
    lim = _limit(target)
    if lim in MODERN_GEN_LIMITS or lim in NOISE_GEN_LIMITS:
        return world_type.lower() != "customized"
    return lim in BETA_GEN_LIMITS or lim in RELEASE_GEN_LIMITS


def generator(target, seed: int, world_type: str = "default"):
    """The target's world generator and the y of its sea surface (the highest water block).
    ``world_type``: the generatorName of the level (largeBiomes: 1.3+)."""
    lim = _limit(target)
    kind = world_type.lower()
    if lim == "1.13":
        from .modern16 import Modern13Generator

        return Modern13Generator(seed, large_biomes=kind == "largebiomes", amplified=kind == "amplified"), 62
    if lim in NOISE_GEN_LIMITS:
        from .modern16 import Modern16Generator

        return Modern16Generator(seed, lim, large_biomes=kind == "largebiomes", amplified=kind == "amplified"), 62
    if lim in MODERN_GEN_LIMITS:
        from .modern import ModernGenerator

        return ModernGenerator(seed, lim, large_biomes=kind == "largebiomes", amplified=kind == "amplified"), 62
    if lim in RELEASE_GEN_LIMITS:
        from .releasegen import ReleaseGenerator

        return ReleaseGenerator(seed, RELEASE_GEN_LIMITS[lim], large_biomes=world_type.lower() == "largebiomes"), 62
    return BetaGenerator(seed), 63


def _surface_ids(v: np.ndarray, below: np.ndarray):
    lut_top = np.full(4096, GRASS, np.uint8)
    lut_fill = np.full(4096, DIRT, np.uint8)
    for k, (t, f) in _SURFACE.items():
        lut_top[k], lut_fill[k] = t, f
    return lut_top[v], lut_fill[np.where(v == 2, 3, below)]


class Ring:
    """Terrain written around (or, for a finite world, everywhere outside) the converted chunks.

    ``gen.chunk(cx, cz, lift=None)`` -> (blocks [x, z, y] uint8 Java ids, biomes [x, z][, data [x, z, y]]); ``sea`` = y
    of the generator's sea surface; ``dy`` = how far the converted chunks move up when written;
    ``fill`` = every chunk to write (finite worlds), None = a ring around the converted area."""

    def __init__(self, gen, sea: int, converted: Iterable[Tuple[int, int]], dy: int = 0,
                 fill: Optional[Iterable[Tuple[int, int]]] = None, seed: int = 0):
        self.gen = gen
        self.sea = sea
        self.seed = seed
        self.dy = dy
        self.converted: Set[Tuple[int, int]] = set(converted)
        self.fill = None if fill is None else sorted(set(fill) - self.converted)
        self.edge_chunks: Set[Tuple[int, int]] = {
            (x, z) for x, z in self.converted
            if any((x + dx, z + dz) not in self.converted for dx in (-1, 0, 1) for dz in (-1, 0, 1))}
        # per edge chunk: ground height, surface (top, filler), known flag of every column [x, z]
        self.edges: Dict[Tuple[int, int], Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
        # per edge chunk: trees (trunks), fraction of spruces, fraction of birches
        self.trees: Dict[Tuple[int, int], Tuple[int, float, float]] = {}
        self.cover: Dict[Tuple[int, int], Tuple[int, int]] = {}  # per edge chunk: tall grass, flowers
        # per edge chunk: its four outer faces (x = 0, x = 15, z = 0, z = 15) as written, [y, 16] block ids
        self.faces: Dict[Tuple[int, int], Tuple[np.ndarray, ...]] = {}
        self.sealed = 0
        self.gen_h: Dict[Tuple[int, int], np.ndarray] = {}     # the generator's ground at the edge chunks
        self.widths: Dict[Tuple[int, int], int] = {}
        self._targets: Optional[List[Tuple[int, int]]] = None
        self._pieces: list = []
        self._piece_of: Dict[Tuple[int, int], int] = {}
        self._cols = None
        self.planted = 0
        self.written: List[Tuple[int, int]] = []

    # backwards compatible name of the old fixed ring
    @property
    def ring(self) -> int:
        return max(self.widths.values(), default=RING)

    # -------------------------------------------------------------- converted side
    def observe(self, dim: int, c: NumericChunk) -> None:
        if dim != OVERWORLD or (c.cx, c.cz) not in self.edge_chunks:
            return
        b = np.asarray(c.blocks).astype(np.int64)                  # y, z, x
        H = b.shape[0]
        ground = _GROUND[b]
        has = ground.any(axis=0)
        top = np.where(has, H - 1 - np.argmax(ground[::-1], axis=0), 0)   # z, x
        tb = np.take_along_axis(b, top[None], axis=0)[0]
        below = np.take_along_axis(b, np.maximum(top - 1, 0)[None], axis=0)[0]
        surf_top, surf_fill = _surface_ids(tb, below)
        # dry ground under the sea (1.18+ canyons and valleys, quarries): the old generators fill
        # everything under the sea with water, so the ring stays at the sea's level there instead
        # of making a pond whose water would stand as a wall against the dry side
        over = np.take_along_axis(b, np.minimum(top + 1, H - 1)[None], axis=0)[0]
        dry = has & ~np.isin(over, (8, 9, ICE)) & (top + self.dy < self.sea)
        ground_y = np.where(dry, self.sea, top + self.dy)
        self.edges[(c.cx, c.cz)] = (ground_y.T.astype(np.int32), surf_top.T, surf_fill.T, has.T)
        moved = np.zeros((max(H + self.dy, 256), 16, 16), np.uint16)
        moved[:max(self.dy, 0)] = STONE                          # (below a world moved up: never open)
        moved[max(self.dy, 0):H + self.dy] = b[max(-self.dy, 0):]
        self.faces[(c.cx, c.cz)] = (moved[:, :, 0], moved[:, :, 15], moved[:, 0, :], moved[:, 15, :])
        # trees: a trunk within 5 blocks over the ground (mangroves stand on roots, which older
        # games do not have); log 162 (acacia, dark oak) is planted as oak
        near = np.zeros_like(has)
        kind = np.zeros(has.shape, np.int64)
        for dy in range(5, 0, -1):
            y = np.clip(top + dy, 0, H - 1)
            v = np.take_along_axis(b, y[None], axis=0)[0]
            d = np.take_along_axis(np.asarray(c.data).astype(np.int64), y[None], axis=0)[0]
            log = has & np.isin(v, (17, 162))
            near |= log
            kind = np.where(log, np.where(v == 17, d & 3, 0), kind)
        # big crowns (acacia, dark oak, mangrove) cover as much as several small old trees: the
        # count follows the ground the leaves cover, about 20 columns per old tree
        canopy = int((b == 18).any(axis=0).sum())
        n = max(int(near.sum()), int(round(canopy / 20.0)))
        if n:
            k = kind[near] if near.any() else np.zeros(1, np.int64)
            self.trees[(c.cx, c.cz)] = (n, float((k == 1).mean()), float((k == 2).mean()))
        else:
            self.trees[(c.cx, c.cz)] = (0, 0.0, 0.0)
        on_grass = np.isin(b[:-1], (2, 3))
        self.cover[(c.cx, c.cz)] = (int((np.isin(b[1:], (31, 175)) & on_grass).sum()),
                                    int((np.isin(b[1:], (37, 38)) & on_grass).sum()))

    # -------------------------------------------------------------- width and targets
    @staticmethod
    def _heights(blocks: np.ndarray) -> np.ndarray:
        solid = (blocks != 0) & (blocks != WATER) & (blocks != ICE) & (blocks != 8)
        return np.where(solid.any(2), blocks.shape[2] - 1 - np.argmax(solid[:, :, ::-1], axis=2), 0)

    def _width(self, e: Tuple[int, int], g: Optional[np.ndarray] = None) -> int:
        """Chunks of ring the edge chunk ``e`` needs: its height difference from the generator's
        terrain there (``g``, its ground heights [x, z]), at the ring's slope."""
        h, _t, _f, has = self.edges.get(e, (None, None, None, None))
        if h is None or not has.any():
            return RING
        if g is None:
            g = _gen_heights(self, e)
        self.gen_h[e] = g
        diff = float(np.abs(h[has] - g[has]).max())
        return int(max(RING, min(MAX_RING, math.ceil(diff / SLOPE / 16.0))))

    def targets(self, progress: Optional[Progress] = None) -> List[Tuple[int, int]]:
        if self._targets is not None:
            return self._targets
        from ..parallel import ordered_map

        raw = {}
        edges = sorted(self.edge_chunks)
        # the generator's terrain under every edge chunk that has converted ground, on every core
        need = [e for e in edges if self.edges and e in self.edges and self.edges[e][3].any()]
        heights = dict(zip(need, ordered_map(_gen_heights, self, need, batch=4, min_items=8)))
        for n, e in enumerate(edges):
            raw[e] = self._width(e, heights.get(e)) if self.edges else RING
            if progress is not None and n % 16 == 0:
                progress.update(n / max(1, len(self.edge_chunks)) * 0.1, tr("Height differences at the world's edge"))
        # the width changes gradually along the border: each edge chunk takes the widest within 2
        # chunks; the ring reaches 2 chunks further, so it always covers them
        self.widths = _dilate(raw, 2)
        reach = _dilate(self.widths, 2)
        near = set()
        for (x, z), w in reach.items():
            near.update((x + dx, z + dz) for dx in range(-w, w + 1) for dz in range(-w, w + 1))
        near -= self.converted
        if self.fill is not None:
            near &= set(self.fill)
            self._targets = sorted(self.fill, key=lambda c: (c[0] >> 5, c[1] >> 5, c[0], c[1]))  # region by region
        else:
            self._targets = sorted(near)
        self._solve(near, progress)
        return self._targets

    # -------------------------------------------------------------- the lift field
    def _solve(self, ring: Set[Tuple[int, int]], progress: Optional[Progress]) -> None:
        """The lift of every ring column, as a harmonic field over each connected piece of ring:
        psi = the converted border's values carried outwards (lift, trees, spruce and birch share),
        phi = 1 on the converted chunks, 0 outside the ring."""
        edges = {e: v for e, v in self.edges.items() if v[3].any() and e in self.gen_h}
        self._pieces, self._piece_of, self._cols = [], {}, None
        if not edges or not ring:
            return
        nodes = set(ring) | set(edges)
        seen: Set[Tuple[int, int]] = set()
        for start in sorted(nodes):
            if start in seen:
                continue
            comp, todo = [], [start]
            seen.add(start)
            while todo:
                x, z = todo.pop()
                comp.append((x, z))
                for dx in (-1, 0, 1):
                    for dz in (-1, 0, 1):
                        n = (x + dx, z + dz)
                        if n in nodes and n not in seen:
                            seen.add(n)
                            todo.append(n)
            members = [c for c in comp if c in ring]
            if not members:
                continue
            k = len(self._pieces)
            self._pieces.append(self._solve_piece(comp, ring, edges))
            for c in members:
                self._piece_of[c] = k
            if progress is not None:
                progress.update(0.1, tr("Joining the terrain to the world's edge"))
        # what the field leaves at the border columns fades within SEAM blocks
        xs, zs, rs = [], [], []
        gx, gz = np.meshgrid(np.arange(16), np.arange(16), indexing="ij")
        for e, (h, _t, _f, has) in edges.items():
            wx, wz = (e[0] * 16 + gx)[has], (e[1] * 16 + gz)[has]
            off = (h - self.gen_h[e])[has].astype(np.float64)
            k = self._piece_at(e)
            if k is None:
                continue
            lift = self._lift_at(k, wx.astype(np.float64), wz.astype(np.float64))
            xs.append(wx)
            zs.append(wz)
            rs.append(off - lift)
        if xs:
            self._cols = tuple(np.concatenate(a) for a in (xs, zs, rs))

    def _piece_at(self, c: Tuple[int, int]) -> Optional[int]:
        for dx in (-1, 0, 1):
            for dz in (-1, 0, 1):
                k = self._piece_of.get((c[0] + dx, c[1] + dz))
                if k is not None:
                    return k
        return None

    def _solve_piece(self, comp, ring, edges):
        xs = [c[0] for c in comp]
        zs = [c[1] for c in comp]
        x0, z0 = min(xs) - 1, min(zs) - 1                       # one chunk of the outside all around
        W, H = max(xs) - x0 + 2, max(zs) - z0 + 2
        cs = 4
        while cs < 16 and (W * 16 // cs) * (H * 16 // cs) > _MAX_CELLS:
            cs *= 2
        coarse = self._grids(16, x0, z0, W, H, ring, edges)
        psi, phi = _harmonic(*coarse, init=None)
        if cs < 16:
            n = 16 // cs
            fine = self._grids(cs, x0, z0, W, H, ring, edges)
            up = lambda a: np.repeat(np.repeat(a, n, axis=-2), n, axis=-1)  # noqa: E731
            psi, phi = _harmonic(*fine, init=(up(psi), up(phi)))
        return (x0, z0, cs, psi.astype(np.float32), phi.astype(np.float32))

    def _grids(self, cs, x0, z0, W, H, ring, edges):
        """Cells of ``cs`` blocks over the piece: values and fixed flags of psi (lift, trees, spruce and
        birch share, tall grass, flowers) and phi."""
        n = 16 // cs
        GX, GZ = W * n, H * n
        val = np.zeros((6, GX, GZ), np.float64)
        fixed = np.zeros((6, GX, GZ), bool)
        domain = np.zeros((GX, GZ), bool)          # psi lives on the ring and the converted border
        phi = np.zeros((GX, GZ), np.float64)
        phi_fixed = np.ones((GX, GZ), bool)
        for i in range(W):
            for j in range(H):
                c = (x0 + i, z0 + j)
                sl = (slice(i * n, i * n + n), slice(j * n, j * n + n))
                if c in ring:
                    domain[sl] = True
                    phi_fixed[sl] = False
                elif c in self.converted:
                    phi[sl] = 1.0
                    e = edges.get(c)
                    if e is None:
                        continue
                    domain[sl] = True
                    h, _t, _f, has = e
                    off = (h - self.gen_h[c]).astype(np.float64)
                    s = (off * has).reshape(n, cs, n, cs).sum(axis=(1, 3))
                    m = has.reshape(n, cs, n, cs).sum(axis=(1, 3))
                    val[0][sl] = np.where(m > 0, s / np.maximum(m, 1), 0.0)
                    fixed[0][sl] = m > 0
                    t, sp, bi = self.trees.get(c, (0, 0.0, 0.0))
                    val[1][sl], fixed[1][sl] = float(t), True
                    if t:
                        val[2][sl], val[3][sl] = sp, bi
                        fixed[2][sl] = fixed[3][sl] = True
                    g, fl = self.cover.get(c, (0, 0))
                    val[4][sl], val[5][sl] = float(g), float(fl)
                    fixed[4][sl] = fixed[5][sl] = True
        return val, fixed, domain, phi, phi_fixed

    def _fields(self, k: int, wx: np.ndarray, wz: np.ndarray):
        """psi [4, n] and phi [n] at world columns (bilinear between the cells' centres)."""
        x0, z0, cs, psi, phi = self._pieces[k]
        u = (wx - x0 * 16 - (cs - 1) / 2.0) / cs
        v = (wz - z0 * 16 - (cs - 1) / 2.0) / cs
        GX, GZ = phi.shape
        u = np.clip(u, 0, GX - 1.001)
        v = np.clip(v, 0, GZ - 1.001)
        i, j = u.astype(int), v.astype(int)
        fu, fv = u - i, v - j

        def at(a):
            return (a[..., i, j] * (1 - fu) * (1 - fv) + a[..., i + 1, j] * fu * (1 - fv)
                    + a[..., i, j + 1] * (1 - fu) * fv + a[..., i + 1, j + 1] * fu * fv)

        return at(psi), at(phi)

    @staticmethod
    def _ease(psi0: np.ndarray, phi: np.ndarray) -> np.ndarray:
        """How much of the border's lift a column keeps: smooth at both ends; converted land higher
        than the game's terrain holds out a little longer (land, not sea, next to the border)."""
        # 0 already a little inside the outer edge: the last columns are exactly the game's
        s = np.clip((phi - OUTER) / (1.0 - OUTER), 0.0, 1.0)
        s = s * s * (3.0 - 2.0 * s)
        return np.where(psi0 > 0, s ** 0.7, s)

    def _lift_at(self, k: int, wx: np.ndarray, wz: np.ndarray) -> np.ndarray:
        # the lift's contour lines would run parallel to the converted border (rings around the
        # world): a noise bends them and lays gentle swells on the slope, nothing at either end
        n1 = lift_mod.value_noise(wx, wz, self.seed, 40.0)
        n2 = lift_mod.value_noise(wx, wz, self.seed + 1, 40.0)
        psi, phi = self._fields(k, wx + BEND * n1, wz + BEND * n2)
        e = self._ease(psi[0], phi)
        swell = lift_mod.value_noise(wx, wz, self.seed + 2, 28.0)
        # never beyond the outer edge, whatever the noise: there the ring is the game's terrain
        _psi, phi0 = self._fields(k, wx, wz)
        gate = np.clip((phi0 - OUTER) / 0.12, 0.0, 1.0)
        return psi[0] * np.clip(e + SWELL * swell * 4.0 * e * (1.0 - e), 0.0, 1.0) * gate * gate * (3.0 - 2.0 * gate)

    def lift(self, cx: int, cz: int) -> Optional[np.ndarray]:
        """[x, z] blocks the generator's rock moves up in chunk (cx, cz); None = the game's terrain."""
        k = self._piece_of.get((cx, cz))
        if k is None:
            return None
        gx, gz = np.meshgrid(np.arange(16), np.arange(16), indexing="ij")
        wx = (cx * 16 + gx).reshape(-1).astype(np.float64)
        wz = (cz * 16 + gz).reshape(-1).astype(np.float64)
        lift = self._lift_at(k, wx, wz)
        cols = self._cols
        if cols is not None:
            r = SEAM + 16
            m = (np.abs(cols[0] - (cx * 16 + 8)) <= r) & (np.abs(cols[1] - (cz * 16 + 8)) <= r)
            if m.any():
                ex, ez, er = cols[0][m], cols[1][m], cols[2][m]
                d2 = (wx[:, None] - ex[None, :]) ** 2 + (wz[:, None] - ez[None, :]) ** 2
                kk = min(8, d2.shape[1])
                idx = np.argpartition(d2, kk - 1, axis=1)[:, :kk]
                dd = np.take_along_axis(d2, idx, axis=1)
                wgt = 1.0 / (dd * dd + 0.01)                  # the closest border column counts most
                res = (er[idx] * wgt).sum(axis=1) / wgt.sum(axis=1)
                fade = np.clip(1.0 - (np.sqrt(dd.min(axis=1)) - 1.0) / SEAM, 0.0, 1.0) ** 2
                lift = lift + res * fade
        return np.nan_to_num(lift, nan=0.0).reshape(16, 16)

    def _plan(self, cx: int, cz: int) -> Tuple[float, float, float, float, float]:
        """Trees, spruce share, birch share, tall grass and flowers for ring chunk (cx, cz)."""
        k = self._piece_of.get((cx, cz))
        if k is None:
            return 0.0, 0.0, 0.0, 0.0, 0.0
        psi, phi = self._fields(k, np.array([cx * 16 + 8.0]), np.array([cz * 16 + 8.0]))
        s = float(np.clip(np.nan_to_num((phi[0] - OUTER) / (1.0 - OUTER), nan=0.0), 0, 1))
        s = s * s * (3 - 2 * s)
        # the relaxation can overshoot a little (or leave a NaN on a degenerate piece): densities and
        # shares are never negative, shares never above 1
        v = [float(np.nan_to_num(psi[i][0], nan=0.0)) for i in range(1, 6)]
        dens, spruce, birch, grass, flowers = (max(0.0, x) for x in v)
        return dens * s, min(spruce, 1.0), min(birch, 1.0), grass * s, flowers * s

    # -------------------------------------------------------------- generation
    def _gen_chunk(self, cx: int, cz: int, lift):
        return _call(self.gen, cx, cz, lift, self.sea)

    def _ring_chunk(self, cx: int, cz: int) -> Tuple[NumericChunk, int, int]:
        """Ring chunk (cx, cz), finished (lift, the generator's terrain, trees, seals); with the trees
        planted and the blocks sealed in it."""
        lift = self.lift(cx, cz)
        blocks, biomes, *data = self._gen_chunk(cx, cz, lift)
        c = NumericChunk(cx, cz, 256)
        c.blocks[:blocks.shape[2]] = np.transpose(blocks, (2, 1, 0))    # -> y, z, x
        if data:                                                        # generators with block data
            c.data[:blocks.shape[2]] = np.transpose(data[0], (2, 1, 0))
        planted = 0
        dens, spruce, birch, grass, flowers = self._plan(cx, cz)
        if dens > 0.05 or grass > 0.5:
            rng = np.random.default_rng([self.seed & 0xFFFFFFFF, cx & 0xFFFFFFFF, cz & 0xFFFFFFFF, 7])
            count = min(MAX_TREES, int(rng.poisson(min(dens, MAX_TREES))))
            planted = trees.plant(c.blocks, c.data, count, spruce, birch, rng, self.sea)
            trees.cover(c.blocks, c.data, int(rng.poisson(min(grass, 120))), int(rng.poisson(min(flowers, 20))),
                        rng, self.sea)
        sealed = self._seal(c)
        if self.fill is not None:
            # up to 100,000 chunks: the light straight from the sky is enough for open terrain
            op = LIGHT_OPACITY[np.asarray(c.blocks, np.int64)]
            c.sky_light = np.clip(15 - np.cumsum(op[::-1], axis=0)[::-1], 0, 15).astype(np.uint8)
            c.block_light = np.zeros_like(c.sky_light)
        b = np.asarray(biomes)
        c.biomes = (b.T if b.dtype.kind in "iu" else np.ones((16, 16))).astype(np.uint8)
        if lift is not None and b.dtype.kind in "iu":
            sea_biomes(c, lift, self.sea)
        c.terrain_populated = False                          # the game decorates it
        return c, planted, sealed

    def chunks(self, progress: Optional[Progress] = None) -> Iterable[NumericChunk]:
        """The ring's chunks, in order; made on every core (parallel.py), the same as in one."""
        if not self.edges and self.fill is None:
            return
        from ..parallel import ordered_map

        targets = self.targets(progress)
        self.written = []
        for n, (c, planted, sealed) in enumerate(ordered_map(_ring_chunk, self, targets, batch=4)):
            self.written.append((c.cx, c.cz))
            self.planted += planted
            self.sealed += sealed
            if progress is not None and n % 16 == 0:
                progress.update(0.1 + 0.9 * n / max(1, len(targets)), tr("Terrain around the world {i}/{n}", i=n, n=len(targets)))
            yield c

    def _seal(self, c: NumericChunk) -> int:
        """No water walls: where the ring's water would run into the converted world's air (a dry
        canyon, a cave mouth lower than the sea), or the converted world's water into the ring's air,
        or the ring's own water into a cave the lift brought next to it, the ring's block becomes
        ground.  The converted world is never touched."""
        B = c.blocks
        Y = B.shape[0]
        pad = np.full((Y, 18, 18), STONE, np.uint16)             # unknown neighbours never leak
        pad[:, 1:17, 1:17] = B
        conv = np.zeros((18, 18), bool)
        for (dx, dz), side, put in (((-1, 0), 1, (slice(1, 17), 0)), ((1, 0), 0, (slice(1, 17), 17)),
                                    ((0, -1), 3, (0, slice(1, 17))), ((0, 1), 2, (17, slice(1, 17)))):
            f = self.faces.get((c.cx + dx, c.cz + dz))
            if f is not None:
                face = np.zeros((Y, 16), np.uint16)
                n = min(Y, f[side].shape[0])
                face[:n] = f[side][:n]
                pad[(slice(None),) + put] = face
                conv[put] = True
        opn, fl = _OPEN[pad], _FLUID[pad]
        copen = opn & conv[None]

        def beside(m):
            return m[:, :-2, 1:-1] | m[:, 2:, 1:-1] | m[:, 1:-1, :-2] | m[:, 1:-1, 2:]
        here_open, here_fluid = opn[:, 1:-1, 1:-1], fl[:, 1:-1, 1:-1]
        under_fluid = np.zeros_like(here_open)
        under_fluid[:-1] = here_fluid[1:]
        # fluid would enter the ring's open block / the ring's fluid would run into the converted air
        seal = (here_open & (beside(fl) | under_fluid)) | (here_fluid & beside(copen))
        if not seal.any():
            return 0
        for y in np.nonzero(seal.any(axis=(1, 2)))[0]:
            m = seal[y]
            B[y][m] = _SEAL[B[y - 1][m]] if y else STONE
            c.data[y][m] = 0
        top = seal.copy()
        top[:-1] &= _OPEN[B[1:]] & ~_FLUID[B[1:]]
        top[-1] = False
        B[top & (B == DIRT)] = GRASS
        return int(seal.sum())


def _harmonic(val, fixed, domain, phi, phi_fixed, init=None):
    """Red-black over-relaxation of Laplace's equation.  psi: Dirichlet where ``fixed``, no flow
    across the edge of ``domain``; phi: Dirichlet where ``phi_fixed``."""
    if init is not None:
        val = np.where(fixed, val, init[0])
        phi = np.where(phi_fixed, phi, init[1])
    GX, GZ = domain.shape
    ii, jj = np.indices((GX, GZ))
    red = (ii + jj) % 2 == 0

    def nsum(a):
        out = np.zeros_like(a)
        out[..., 1:, :] += a[..., :-1, :]
        out[..., :-1, :] += a[..., 1:, :]
        out[..., :, 1:] += a[..., :, :-1]
        out[..., :, :-1] += a[..., :, 1:]
        return out

    dom = domain.astype(np.float64)
    cnt = nsum(dom)
    free_psi = [(~fixed) & domain & (cnt > 0) & c for c in (red, ~red)]
    free_phi = [(~phi_fixed) & c for c in (red, ~red)]
    omega = 1.85
    iters = 4 * max(GX, GZ) + 50 if init is None else 2 * max(GX, GZ) + 50
    for _ in range(iters):
        delta = 0.0
        for fp, ff in zip(free_psi, free_phi):
            d = (nsum(val * dom) / np.maximum(cnt, 1) - val) * fp
            val += omega * d
            e = (nsum(phi) / 4.0 - phi) * ff
            phi += omega * e
            delta = max(delta, float(np.abs(d).max(initial=0)), 100.0 * float(np.abs(e).max(initial=0)))
        if delta < 0.01:
            break
    return val, phi


def _call(gen, cx, cz, lift, sea):
    """The generator's chunk, lifted; generators without a lift of their own are lifted afterwards."""
    if lift is None:
        return gen.chunk(cx, cz)
    try:
        return gen.chunk(cx, cz, lift=lift)
    except TypeError:
        blocks, biomes, *data = gen.chunk(cx, cz)
        lift_mod.lift_terrain(blocks, lift, sea)
        return (blocks, biomes, *data)


def _dilate(widths: Dict[Tuple[int, int], int], r: int) -> Dict[Tuple[int, int], int]:
    return {(x, z): max(widths.get((x + dx, z + dz), 0) for dx in range(-r, r + 1) for dz in range(-r, r + 1))
            for (x, z) in widths}


def _gen_heights(ring: "Ring", e: Tuple[int, int]) -> np.ndarray:
    """The generator's ground heights [x, z] in chunk ``e`` (worker function, parallel.py)."""
    return Ring._heights(ring._gen_chunk(e[0], e[1], None)[0])


# biomes whose water is water (seas, rivers, beaches), and the cold ones (their sea freezes)
WATER_BIOMES = frozenset((0, 7, 10, 11, 16, 24, 25, 26))
COLD_BIOMES = frozenset((12, 13, 26, 30, 31, 140, 158))
_WATER_TOP = (8, 9, 79)


def sea_biomes(c: NumericChunk, lift: np.ndarray, sea: int) -> int:
    """The ring's biomes are the game's generator's, not the converted world's: where the ring's
    ground was lowered under the sea (towards a converted sea floor) a land biome would stay, and
    the game, decorating the chunk, would dress the water as that land (a swamp's lily pads and
    trees in the open sea).  Those columns become ocean (frozen ocean where the biome is cold).
    ``lift`` [x, z] as Ring.lift; returns the columns changed."""
    wet = np.isin(c.blocks[sea], _WATER_TOP)                      # [z, x]
    m = wet & (np.asarray(lift).T < -1.0) & ~np.isin(c.biomes, tuple(WATER_BIOMES))
    if not m.any():
        return 0
    c.biomes[m] = np.where(np.isin(c.biomes[m], tuple(COLD_BIOMES)), 10, 0)
    return int(m.sum())


def _ring_chunk(ring: "Ring", c: Tuple[int, int]):
    return ring._ring_chunk(c[0], c[1])


def _gen_chunk(gen, job):
    """(cx, cz, lift) -> the generator's chunk (worker function for ring3d)."""
    cx, cz, lift = job
    return _call(gen, cx, cz, lift, 0)


# the old name (Alpha 1.2 - 1.1 targets)
def BetaRing(seed: int, converted, ring: int = RING, dy: int = 0, target=None) -> Ring:
    gen, sea = generator(target, seed) if target is not None else (BetaGenerator(seed), 63)
    return Ring(gen, sea, converted, dy=dy, seed=seed)


def ring_status(target) -> str:
    """The status of the ring's chunks: 1.13 calls the chunk with its noise, surface and bedrock
    "base", 1.14 - 1.17 "surface"."""
    return "base" if _limit(target) == "1.13" else RING_STATUS


def mark_proto_chunks(world_dir: str, coords: Iterable[Tuple[int, int]], status: str = RING_STATUS,
                      sub: str = "region", biomes=None) -> int:
    """Give the ring's chunks of a Java 1.14 - 1.17 world (written by Amulet as finished chunks) the
    status of chunks the game has only shaped: it carves them and adds its lakes, ores and trees.
    ``sub``: the dimension's region folder; ``biomes``: "drop" (the game computes them from its
    own biome source) or a function (cx, cz) -> biome id for the whole chunk (1.13)."""
    from .. import nbt as wnbt
    from ..java.region import JavaRegion, RegionWriter

    by_region: Dict[Tuple[int, int], Set[Tuple[int, int]]] = {}
    for cx, cz in coords:
        by_region.setdefault((cx >> 5, cz >> 5), set()).add((cx & 31, cz & 31))
    done = 0
    for (rx, rz), locs in by_region.items():
        path = os.path.join(world_dir, sub, f"r.{rx}.{rz}.mca")
        if not os.path.isfile(path):
            continue
        reg = JavaRegion(path)
        out = RegionWriter()
        for lx, lz in reg.chunks():
            raw = reg.read(lx, lz)
            if raw is None:
                continue
            if (lx, lz) in locs:
                root = wnbt.load(raw, compressed=False).tag
                lvl = wnbt.get_tag(root, "Level")
                if lvl is not None:
                    lvl["Status"] = wnbt.StringTag(status)
                    lvl["isLightOn"] = wnbt.ByteTag(0)
                    if biomes == "drop":
                        lvl.pop("Biomes", None)
                    elif callable(biomes):
                        lvl["Biomes"] = wnbt.IntArrayTag(np.full(256, biomes(rx * 32 + lx, rz * 32 + lz), np.int32))
                    raw = wnbt.dump(root, "")
                    done += 1
            out.put(lx, lz, raw)
        if any(len(c) + 5 > 255 * 4096 for c in out.chunks.values()):
            continue                     # a chunk too large for the region itself (.mcc): leave the file as it is
        out.write(path)
    return done
