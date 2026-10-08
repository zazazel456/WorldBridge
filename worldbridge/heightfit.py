"""Tall terrain into worlds 128 blocks high (Alpha, Beta, Java 1.0 - 1.1, Pocket Edition 0.x).

Caves & Cliffs worlds go up to y 319 (Amplified ones really use it): cutting them at y 127 leaves
flat stone tables where the mountains were.  Here the overworld is compressed column by column
instead, and only where it is needed:

* below the *knee* nothing moves: y 80 for the highest worlds (Amplified), higher when the
  mountains are only a little too high (only as much as needed is compressed);
* a column whose ground is higher loses a band of rock just under its surface: the surface (grass,
  snow, trees, buildings on the mountain) comes down whole, intact, onto the rock below.  The
  higher the ground, the thicker the band, so the mountains keep their shape - lower - and their
  peaks end ~10 blocks under the ceiling, with room for trees;
* the band thickness is smoothed between neighbouring columns (and chunks); a building (village
  house, player build) comes down as one rigid piece, the ground under it included, and every
  tree follows its own trunk, so neither gets sheared on a slope.

* floating islands and sky builds (no natural ground in their columns, or a tower far above the
  ground) are rigid pieces as well: their columns are lowered together by what the highest block of
  the piece needs to fit, and where possible the removed band is plain air (the void or the cave
  under them), so nothing is lost;
* in every column a run of air is removed in preference to rock (caves, void under an island).

Chests, mobs, the player and the spawn point move with their column.  Two passes: the first
reads every column's ground height and top, the second rewrites the chunks.  What the compression
could not bring under the ceiling is cut and counted (never silently).
"""

from __future__ import annotations

from typing import Dict, Optional, Tuple

import numpy as np

from . import nbt
from .model import NumericChunk

KNEE = 80          # ground up to here is never moved (the lowest knee: Amplified worlds)
HEADROOM = 10      # the highest ground ends this far under the world's ceiling (trees, snow)
KEEP = 4           # blocks of the surface kept above the removed band (grass, dirt, snow)
SMOOTH = 4         # radius (blocks) of the smoothing of the band thickness
SLACK = 2          # a column may differ from its own ideal shift by this much (cliffs)

# Java 1.12 ids of natural ground and of the liquids / ice lying on it (lakes keep a flat surface)
GROUND = np.zeros(4096, bool)
GROUND[[1, 2, 3, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 21, 24, 49, 56, 73, 74, 79, 80, 82, 87, 88, 110, 121,
        153, 159, 172, 174, 179, 208]] = True


# Java 1.12 ids of blocks made by players or structures (bases, mineshafts, dungeons): the removed
# band never goes through them, it is looked for deeper in the column
PROTECTED = np.zeros(4096, bool)
PROTECTED[[4, 5, 20, 22, 23, 25, 26, 27, 28, 29, 33, 34, 35, 41, 42, 43, 44, 45, 46, 47, 48, 50, 52, 53, 54, 55, 57,
           58, 61, 62, 63, 64, 65, 66, 67, 68, 69, 71, 75, 76, 77, 84, 85, 89, 91, 92, 93, 94, 95, 96, 98, 101, 102,
           107, 108, 109, 113, 114, 116, 117, 118, 120, 123, 124, 125, 126, 128, 130, 133, 134, 135, 136, 137, 138,
           139, 140, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 154, 155, 156, 157, 158, 160, 163, 164, 165,
           167, 169, 171, 176, 177, 178, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194,
           195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 210, 211, 213, 215, 216, 218] + list(range(219, 256))] = True


# natural things standing on the ground that must keep their shape: they follow their trunk
LOGS = np.zeros(4096, bool)
LOGS[[17, 162, 99, 100]] = True                                  # logs, huge mushroom blocks
TREE = LOGS.copy()
TREE[[18, 161, 106, 127]] = True                                # + leaves, vines, cocoa
TRUNK_MIN = 1      # logs stacked on the ground to be a trunk (bushes have one)
TREE_REACH = 5     # leaves and branches this far from a trunk (horizontally) belong to it
BUILD_RADIUS = 2   # built columns this close belong to the same building


def ground_heights(c: NumericChunk) -> np.ndarray:
    """[z, x] y of the highest natural ground block, -1 where there is none."""
    g = GROUND[np.asarray(c.blocks, np.int64)]
    has = g.any(axis=0)
    return np.where(has, c.height - 1 - np.argmax(g[::-1], axis=0), -1).astype(np.int16)


def content_tops(c: NumericChunk, h: np.ndarray) -> np.ndarray:
    """[z, x] y of the highest block that has to fit under the ceiling, -1 where the column is empty.
    Natural trees (logs, leaves, vines) do not count in columns with ground: they follow their
    trunk, and the ground of a whole forest is not lowered for the crown of a tall tree."""
    b = np.asarray(c.blocks, np.int64)
    solid = b != 0
    keep = solid & ~(TREE[b] & (h[None] >= 0))
    has = keep.any(axis=0)
    return np.where(has, c.height - 1 - np.argmax(keep[::-1], axis=0), -1).astype(np.int16)


def cut_above(c: NumericChunk, ceiling: int) -> Tuple[int, int, int]:
    """Cut everything at y >= ceiling off a chunk: (blocks, block entities, entities) removed.  The
    block entities and entities go here, with their blocks, so they are not reported as something
    else later; the count is also kept in ``c.cut_above``.  (An entity at y 128.0 stands on the
    highest block the target can store: it stays.)"""
    nb = nt = ne = 0
    if c.height > ceiling:
        above = np.asarray(c.blocks[ceiling:]) != 0
        nb = int(above.sum())
        if nb:
            c.blocks[ceiling:] = 0
            c.data[ceiling:] = 0
            if c.waterlogged is not None:
                c.waterlogged[ceiling:] = False
        elif c.waterlogged is not None and c.waterlogged[ceiling:].any():
            c.waterlogged[ceiling:] = False
    c.modern_blocks = {k: v for k, v in c.modern_blocks.items() if k[1] < ceiling}

    def y_of(t):
        try:
            return int(nbt.get(t, "y"))
        except (TypeError, ValueError):
            return None

    kept = []
    for t in c.tile_entities:
        y = y_of(t)
        if y is not None and y >= ceiling:
            nt += 1
        else:
            kept.append(t)
    c.tile_entities = kept
    c.tile_ticks = [t for t in c.tile_ticks if (y_of(t) is None or y_of(t) < ceiling)]
    kept = []
    for e in c.entities:
        pos = nbt.get_tag(e, "Pos")
        if pos is not None and len(pos) == 3 and float(pos[1].py_data) >= ceiling + 1:       # y 128.0: standing on block 127
            ne += 1
        else:
            kept.append(e)
    c.entities = kept
    c.cut_above = (nb, nt, ne)
    return nb, nt, ne


class HeightFit:
    def __init__(self, ceiling: int):
        """ceiling: first y the target cannot store (128), in the coordinates of the source."""
        self.ceiling = ceiling
        self.top_ground = ceiling - 1 - HEADROOM
        self.heights: Dict[Tuple[int, int], np.ndarray] = {}
        self.tops: Dict[Tuple[int, int], np.ndarray] = {}       # y of the highest block to fit, per column
        self.max_ground = -1
        self.max_top = -1
        self._shifts: Dict[Tuple[int, int], np.ndarray] = {}
        self._starts: Dict[Tuple[int, int], np.ndarray] = {}
        self._base: Dict[Tuple[int, int], np.ndarray] = {}
        self.built: Dict[Tuple[int, int], np.ndarray] = {}      # columns with a building near the top
        self.floating: Dict[Tuple[int, int], np.ndarray] = {}   # columns with blocks and no natural ground
        self.trunks: Dict[Tuple[int, int], np.ndarray] = {}     # columns with a tree trunk on the ground
        self._rigid: Optional[Dict[Tuple[int, int], np.ndarray]] = None
        self.buildings = 0
        self.moved_columns = 0
        self.lost_tiles = 0                                      # block entities inside the removed rock
        # blocks of a floating piece (no natural ground in the column) or of a build that no air band could take
        # the place of: the band went through them
        self.lost_band_blocks = 0
        # what was still above the ceiling after the compression (cut, never silently)
        self.lost_blocks = 0
        self.lost_tiles_above = 0
        self.lost_entities = 0

    # -------------------------------------------------------------- pass 1
    def observe(self, c: NumericChunk) -> None:
        h = ground_heights(c)
        self.heights[(c.cx, c.cz)] = h
        self.max_ground = max(self.max_ground, int(h.max()))
        top = content_tops(c, h)
        self.tops[(c.cx, c.cz)] = top
        self.max_top = max(self.max_top, int(top.max()))
        floating = (h < 0) & (top >= 0)
        if floating.any():
            self.floating[(c.cx, c.cz)] = floating
        b = np.asarray(c.blocks, np.int64)
        y = np.arange(c.height)[:, None, None]
        near_top = y > (h[None].astype(np.int32) - KEEP)
        built = (PROTECTED[b] & near_top).any(axis=0) & (h >= 0)
        if built.any():
            self.built[(c.cx, c.cz)] = built
        # trunks: logs stacked on the ground; the y of their top log (-1: no trunk)
        logs = LOGS[b]
        trunk = np.full((16, 16), -1, np.int32)
        on_ground = logs[np.clip(h.astype(np.int64) + 1, 0, c.height - 1), np.arange(16)[:, None], np.arange(16)[None, :]]
        for z, x in zip(*np.nonzero(on_ground & (h >= 0))):
            y0 = int(h[z, x]) + 1
            y1 = y0
            while y1 + 1 < c.height and logs[y1 + 1, z, x]:
                y1 += 1
            if y1 - y0 + 1 >= TRUNK_MIN:
                trunk[z, x] = y1
        if (trunk >= 0).any():
            self.trunks[(c.cx, c.cz)] = trunk

    # what pass 1 learns: every field written by observe(), so that the state can cross a process
    # boundary (Amulet workers) as a whole; a new field goes here and nowhere else
    _DICTS = ("heights", "tops", "built", "floating", "trunks")
    _MAXES = ("max_ground", "max_top")

    def observed_state(self) -> dict:
        """Everything observe() learned, as a picklable dict (see merge_observed)."""
        state = {k: getattr(self, k) for k in self._DICTS + self._MAXES}
        return state

    def merge_observed(self, state: dict) -> None:
        """Adds the state another HeightFit (maybe in another process) observed."""
        for k in self._DICTS:
            getattr(self, k).update(state[k])
        for k in self._MAXES:
            setattr(self, k, max(getattr(self, k), state[k]))
        self._rigid = None
        self._shifts.clear()
        self._base.clear()

    @property
    def ground_needed(self) -> bool:
        return self.max_ground > self.top_ground

    @property
    def needed(self) -> bool:
        """Ground higher than the target, or something built above its ceiling."""
        return self.ground_needed or self.max_top >= self.ceiling

    @property
    def ratio(self) -> float:
        """How much of the ground above the knee is kept (1 = nothing compressed)."""
        if not self.ground_needed:
            return 1.0
        return (self.top_ground - self.knee) / float(self.max_ground - self.knee)

    @property
    def knee(self) -> int:
        """Ground below this height does not move.  Only as much as needed is compressed: at least
        half of the height above the knee is kept (mountains a little too high are only trimmed at
        the top), down to KNEE for the highest worlds."""
        return int(max(KNEE, self.top_ground - max(self.max_ground - self.top_ground, 0)))

    def _ideal(self, h: np.ndarray) -> np.ndarray:
        """Per column: how many blocks its ground has to come down."""
        over = np.maximum(h.astype(np.float64) - self.knee, 0.0)
        return over * (1.0 - self.ratio)

    # -------------------------------------------------------------- shifts
    def shifts(self, cx: int, cz: int) -> np.ndarray:
        """[z, x] blocks removed under the surface of every column of the chunk."""
        got = self._shifts.get((cx, cz))
        if got is not None:
            return got
        s = self._base_shifts(cx, cz).copy()
        rigid = self._rigid_shifts().get((cx, cz))
        if rigid is not None:
            s = np.where(rigid >= 0, rigid, s)
        self._shifts[(cx, cz)] = s
        return s

    def _need(self, cx: int, cz: int) -> np.ndarray:
        """[z, x] blocks the column has to come down so that its highest block fits."""
        t = self.tops.get((cx, cz))
        if t is None:
            return np.zeros((16, 16), np.int32)
        return np.maximum(t.astype(np.int32) - (self.ceiling - 1), 0)

    def _rigid_shifts(self) -> Dict[Tuple[int, int], np.ndarray]:
        """One shift for every column of a building (its ground included): the building comes
        down as a whole.  Columns with a building near the top, BUILD_RADIUS apart at most, are
        one building (houses of a village are separate, their paths are ground).  Floating islands
        and sky builds (columns with blocks and no natural ground) are buildings too, their island
        included; the piece comes down by enough for its highest block to fit."""
        if self._rigid is not None:
            return self._rigid
        self._rigid = {}
        cols = set()
        for src in (self.built, self.floating):
            for (cx, cz), m in src.items():
                zs, xs = np.nonzero(m)
                cols.update(zip((cx * 16 + xs).tolist(), (cz * 16 + zs).tolist()))
        seen = set()
        r = BUILD_RADIUS
        near = [(dx, dz) for dx in range(-r, r + 1) for dz in range(-r, r + 1) if dx or dz]
        for start in cols:
            if start in seen:
                continue
            comp, todo = [], [start]
            seen.add(start)
            while todo:
                x, z = todo.pop()
                comp.append((x, z))
                for dx, dz in near:
                    q = (x + dx, z + dz)
                    if q in cols and q not in seen:
                        seen.add(q)
                        todo.append(q)
            # a column of a chunk with no known heights or tops is unknown: left out
            comp = [(x, z) for x, z in comp if (x >> 4, z >> 4) in self.heights and (x >> 4, z >> 4) in self.tops]
            if not comp:
                continue
            hs = [int(self.heights[(x >> 4, z >> 4)][z & 15, x & 15]) for x, z in comp]
            tops = [int(self.tops[(x >> 4, z >> 4)][z & 15, x & 15]) for x, z in comp]
            need = max(max(tops) - (self.ceiling - 1), 0)
            base = [int(self._base_shifts(x >> 4, z >> 4)[z & 15, x & 15]) for (x, z), h in zip(comp, hs) if h >= 0]
            if not any(base) and not need:
                continue
            # the median shift, but enough for the highest ground under it - and the highest block - to fit
            sh = max(int(np.median(base)) if base else 0, max(hs) - self.top_ground, need, 0)
            if not sh:
                continue
            for (x, z), h, t in zip(comp, hs, tops):
                a = self._rigid.setdefault((x >> 4, z >> 4), np.full((16, 16), -1, np.int32))
                # a column with no ground whose blocks are all under the band stays where it is
                a[z & 15, x & 15] = sh if (h >= 0 or t + 1 - sh >= 1) else 0
            self.buildings += 1
        return self._rigid

    def _base_shifts(self, cx: int, cz: int) -> np.ndarray:
        got = self._base.get((cx, cz))
        if got is not None:
            return got
        h = self.heights.get((cx, cz))
        if h is None:
            return np.zeros((16, 16), np.int32)
        r = SMOOTH
        # the chunk and a border of r blocks from its neighbours: ideal shift + known mask
        big = np.zeros((16 + 2 * r, 16 + 2 * r))
        known = np.zeros_like(big)
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nh = self.heights.get((cx + dx, cz + dz))
                if nh is None:
                    continue
                full = np.zeros((48, 48))
                fk = np.zeros((48, 48))
                full[16 + dz * 16:32 + dz * 16, 16 + dx * 16:32 + dx * 16] = self._ideal(nh)
                fk[16 + dz * 16:32 + dz * 16, 16 + dx * 16:32 + dx * 16] = nh >= 0
                big += full[16 - r:32 + r, 16 - r:32 + r] * fk[16 - r:32 + r, 16 - r:32 + r]
                known += fk[16 - r:32 + r, 16 - r:32 + r]
        # box mean over (2r+1)^2 with a summed area table
        k = 2 * r + 1

        def box(a):
            s = np.pad(a, ((1, 0), (1, 0))).cumsum(0).cumsum(1)
            return s[k:, k:] - s[:-k, k:] - s[k:, :-k] + s[:-k, :-k]

        mean = box(big) / np.maximum(box(known), 1)
        own = self._ideal(h)
        s = np.clip(mean, own - SLACK, own + SLACK)
        s = np.where(h > self.knee, np.minimum(s, h - self.knee), 0)  # never below the knee
        s = np.rint(np.maximum(s, 0)).astype(np.int32)
        s = np.maximum(s, self._need(cx, cz))                     # the highest block has to fit
        s[h < 0] = 0
        self._base[(cx, cz)] = s
        return s

    def shift_at(self, x: float, y: float, z: float) -> float:
        """New y of a point (entity, player, spawn) at world x, y, z."""
        xi, zi = int(np.floor(x)), int(np.floor(z))
        s = self.shifts(xi >> 4, zi >> 4)[zi & 15, xi & 15]
        if not s:
            return y
        starts = self._starts.get((xi >> 4, zi >> 4))
        if starts is not None:
            a = int(starts[zi & 15, xi & 15])
        else:                                                         # chunk not rewritten (yet): a guess
            hh = self.heights.get((xi >> 4, zi >> 4))
            if hh is None:                                            # unknown chunk: no shift
                return y
            h = int(hh[zi & 15, xi & 15])
            if h < 0:                                                 # floating: the band is under the blocks
                tt = self.tops.get((xi >> 4, zi >> 4))
                if tt is None:
                    return y
                top = int(tt[zi & 15, xi & 15])
                return y - s if y >= top + 1 - s else y
            a = h - KEEP + 1 - s
        if y >= a + s:
            return y - s
        if y >= a:
            return float(a)                                       # inside the removed band: onto it
        return y

    def _band_starts(self, c: NumericChunk, s: np.ndarray) -> np.ndarray:
        """First removed y of every column.  In preference a run of air under the surface (a cave,
        the void under an island): nothing is lost.  Else just under the surface, or deeper where
        that band would go through a built block (a base inside the mountain comes down whole).
        A column with no ground (floating island) loses the cheapest band under its highest block."""
        H = c.height
        h = self.heights[(c.cx, c.cz)].astype(np.int32)
        top = self.tops[(c.cx, c.cz)].astype(np.int32)
        start = h - KEEP + 1 - s
        blocks = np.asarray(c.blocks, np.int64)
        prot = PROTECTED[blocks]
        solid = blocks != 0
        for t in c.tile_entities:
            try:
                prot[int(nbt.get(t, "y")), int(nbt.get(t, "z")) & 15, int(nbt.get(t, "x")) & 15] = True
            except (TypeError, ValueError, IndexError):
                pass
        zero = np.zeros((1, 16, 16), np.int32)
        cs = np.concatenate([zero, np.cumsum(prot, axis=0, dtype=np.int32)])       # built blocks under y
        cn = np.concatenate([zero, np.cumsum(solid, axis=0, dtype=np.int32)])      # non-air blocks under y
        rigid = self._rigid_shifts().get((c.cx, c.cz))
        need = self._need(c.cx, c.cz)
        knee = max(self.knee, 1)
        for z, x in zip(*np.nonzero(s)):
            sh, a0 = int(s[z, x]), int(start[z, x])
            pc = np.append(prot[:, z, x], False)                      # pc[H]: nothing above the column
            col, ncol = cs[:, z, x], cn[:, z, x]
            if h[z, x] < 0:
                # no ground: the band that costs the least blocks under the highest one, the highest
                # of them (the void under the island); a room between two built blocks is kept
                hi = int(top[z, x]) + 1 - sh
                if hi < 1:
                    start[z, x] = 1
                    continue
                a = np.arange(1, hi + 1)
                cost = (ncol[a + sh] - ncol[a]) + 20 * (col[a + sh] - col[a]) + 1000 * (pc[a - 1] & pc[a + sh])
                start[z, x] = a[np.nonzero(cost == cost.min())[0][-1]]
                continue
            if a0 < 1:                                                # surface at the very bottom: nothing to move
                start[z, x] = 1
                continue
            # air, not a room between two built blocks, from the knee (buildings and tall blocks: anywhere)
            lo = 1 if (rigid is not None and rigid[z, x] >= 0) or need[z, x] else knee
            if lo <= a0:
                a = np.arange(lo, a0 + 1)
                free = ((ncol[a + sh] - ncol[a]) == 0) & ~(pc[a - 1] & pc[a + sh])
                idx = np.nonzero(free)[0]
                if len(idx):
                    start[z, x] = a[idx[-1]]
                    continue
            if col[a0 + sh] == col[a0]:
                continue
            a = np.arange(1, a0 + 1)
            hits = col[a + sh] - col[a]
            free = np.nonzero(hits == 0)[0]
            start[z, x] = a[free[-1]] if len(free) else a[np.argmin(hits[::-1]) * -1 - 1]
        return start

    # -------------------------------------------------------------- trees
    def _tree_blocks(self, c: NumericChunk, s: np.ndarray):
        """Leaves, logs and vines above the ground whose trunk moves differently from the ground
        under them: (y, z, x, ids, data, new y).  A block belongs to the nearest trunk within
        TREE_REACH whose height suits it (from its base to 4 blocks above its top log)."""
        if not any((c.cx + dx, c.cz + dz) in self.trunks for dx in (-1, 0, 1) for dz in (-1, 0, 1)):
            return None
        h = self.heights[(c.cx, c.cz)].astype(np.int32)
        b = np.asarray(c.blocks, np.int64)
        yy = np.arange(c.height)[:, None, None]
        ys, zs, xs = np.nonzero(TREE[b] & (yy > h[None]))
        if not len(ys):
            return None
        top = np.full((48, 48), -1, np.int32)
        base = np.zeros((48, 48), np.int32)
        sh = np.zeros((48, 48), np.int32)
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                t = self.trunks.get((c.cx + dx, c.cz + dz))
                if t is None:
                    continue
                win = (slice(16 + dz * 16, 32 + dz * 16), slice(16 + dx * 16, 32 + dx * 16))
                top[win] = t
                base[win] = self.heights[(c.cx + dx, c.cz + dz)] + 1
                sh[win] = s if (dx, dz) == (0, 0) else self.shifts(c.cx + dx, c.cz + dz)
        anchor = np.full(len(ys), -1, np.int32)
        R = TREE_REACH
        offs = sorted(((dx, dz) for dx in range(-R, R + 1) for dz in range(-R, R + 1)), key=lambda o: o[0] ** 2 + o[1] ** 2)
        for dx, dz in offs:
            tz, tx = zs + 16 + dz, xs + 16 + dx
            t = top[tz, tx]
            ok = (anchor < 0) & (t >= 0) & (ys >= base[tz, tx]) & (ys <= t + 4)
            anchor[ok] = sh[tz, tx][ok]
        move = (anchor >= 0) & (anchor != s[zs, xs])
        if not move.any():
            return None
        ys, zs, xs, anchor = ys[move], zs[move], xs[move], anchor[move]
        return ys, zs, xs, b[ys, zs, xs].copy(), np.asarray(c.data)[ys, zs, xs].copy(), ys - anchor

    def _place_trees(self, c: NumericChunk, s, ys, zs, xs, ids, data, new_y) -> None:
        """Move the tree blocks found by _tree_blocks from where their column put them to where
        their trunk goes; they never replace the ground or other blocks."""
        h = self.heights[(c.cx, c.cz)].astype(np.int32)
        cur = ys - s[zs, xs]
        c.blocks[cur, zs, xs] = 0
        c.data[cur, zs, xs] = 0
        for y, z, x, i, d in zip(new_y.tolist(), zs.tolist(), xs.tolist(), ids.tolist(), data.tolist()):
            if h[z, x] - s[z, x] < y < c.height and c.blocks[y, z, x] == 0:
                c.blocks[y, z, x] = i
                c.data[y, z, x] = d

    # -------------------------------------------------------------- pass 2
    def apply(self, c: NumericChunk) -> NumericChunk:
        s = self.shifts(c.cx, c.cz)
        if s.any():
            self._remap(c, s)
        self._cut_above(c)
        return c

    def _cut_above(self, c: NumericChunk) -> None:
        """What the compression could not lower under the ceiling is cut here, counted."""
        nb, nt, ne = cut_above(c, self.ceiling)
        self.lost_blocks += nb
        self.lost_tiles_above += nt
        self.lost_entities += ne

    def _count_band_loss(self, c: NumericChunk, s: np.ndarray, start: np.ndarray) -> None:
        """Counts the blocks the removed band takes with it where it should have been air: every block of a column
        with no natural ground (a floating island, a sky build under which no air band was tall enough) and any
        built block (PROTECTED) anywhere.  The natural ground the compression of a mountain removes is the design,
        not a loss."""
        h = self.heights.get((c.cx, c.cz))
        if h is None:
            return
        b = np.asarray(c.blocks, np.int64)
        y = np.arange(c.height)[:, None, None]
        inband = (y >= start[None]) & (y < (start + s)[None])
        lost = inband & (b != 0) & ((h < 0)[None] | PROTECTED[b])
        self.lost_band_blocks += int(lost.sum())

    def _remap(self, c: NumericChunk, s: np.ndarray) -> None:
        start = self._band_starts(c, s)                           # [z, x] first removed y
        self._starts[(c.cx, c.cz)] = start
        H = c.height
        y = np.arange(H)[:, None, None]
        src = np.where(y >= start[None], y + s[None], y)          # [y, z, x] source y of every block
        inside = src < H
        src_c = np.minimum(src, H - 1)

        def remap(arr, fill=0):
            if arr is None:
                return None
            out = np.take_along_axis(arr, src_c, axis=0)
            return np.where(inside, out, fill).astype(arr.dtype)

        self._count_band_loss(c, s, start)
        trees = self._tree_blocks(c, s)
        c.blocks = remap(c.blocks)
        c.data = remap(c.data)
        c.waterlogged = remap(c.waterlogged, False)
        if trees is not None:
            self._place_trees(c, s, *trees)
        c.sky_light = c.block_light = None                        # recomputed by the writer
        c.lce_heightmap = None
        self.moved_columns += int((s > 0).sum())

        def new_y(lx: int, ly: int, lz: int) -> Optional[int]:
            sh = int(s[lz, lx])
            if not sh or ly < start[lz, lx]:
                return ly
            if ly < start[lz, lx] + sh:
                return None                                       # in the removed band
            return ly - sh

        mb = {}
        for (x, yy, z), st in c.modern_blocks.items():
            ny = new_y(x, yy, z)
            if ny is not None:
                mb[(x, ny, z)] = st
        c.modern_blocks = mb
        for name in ("tile_entities", "tile_ticks"):
            kept = []
            for t in getattr(c, name):
                try:
                    lx, ly, lz = int(nbt.get(t, "x")) & 15, int(nbt.get(t, "y")), int(nbt.get(t, "z")) & 15
                except (TypeError, ValueError):
                    kept.append(t)
                    continue
                ny = new_y(lx, ly, lz)
                if ny is None:
                    if name == "tile_entities":
                        self.lost_tiles += 1
                    continue
                if ny != ly:
                    t["y"] = nbt.IntTag(ny)
                kept.append(t)
            setattr(c, name, kept)
        for e in c.entities:
            _move_entity(e, self)


def _move_entity(e: nbt.CompoundTag, fit: HeightFit) -> None:
    pos = nbt.get_tag(e, "Pos")
    if pos is None or len(pos) != 3:
        return
    x, y, z = (float(v.py_data) for v in pos)
    ny = fit.shift_at(x, y, z)
    if ny != y:
        e["Pos"] = nbt.pos_list(x, ny, z)
        for key in ("TileY", "APY"):                              # paintings / frames, leashed
            if key in e:
                e[key] = nbt.IntTag(int(nbt.get(e, key)) - int(round(y - ny)))
    for p in nbt.get_tag(e, "Passengers") or []:
        _move_entity(p, fit)


def move_players_and_spawn(info, fit: HeightFit) -> None:
    """The overworld players and the spawn point follow the compressed ground."""
    lvl = info.level
    seen = set()
    for p in list(info.players.values()) + ([lvl["Player"]] if "Player" in lvl else []):
        if id(p) in seen:
            continue                                              # level.dat's player is also "host"
        seen.add(id(p))
        if nbt.get(p, "Dimension", 0) in (0, "minecraft:overworld", None):
            _move_entity(p, fit)
    x, y, z = info.spawn
    ny = int(round(fit.shift_at(x + 0.5, y, z + 0.5)))
    if ny != y:
        if "SpawnY" in lvl:
            lvl["SpawnY"] = nbt.IntTag(ny)
        sp = nbt.get_tag(lvl, "spawn")
        if sp is not None and nbt.get_tag(sp, "pos") is not None and len(sp["pos"]) == 3:
            sp["pos"] = nbt.IntArrayTag(np.array([x, ny, z], np.int32))
