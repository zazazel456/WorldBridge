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

Chests, mobs, the player and the spawn point move with their column.  Two passes: the first
reads every column's ground height, the second rewrites the chunks.
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


class HeightFit:
    def __init__(self, ceiling: int):
        """ceiling: first y the target cannot store (128), in the coordinates of the source."""
        self.ceiling = ceiling
        self.top_ground = ceiling - 1 - HEADROOM
        self.heights: Dict[Tuple[int, int], np.ndarray] = {}
        self.max_ground = -1
        self._shifts: Dict[Tuple[int, int], np.ndarray] = {}
        self._starts: Dict[Tuple[int, int], np.ndarray] = {}
        self._base: Dict[Tuple[int, int], np.ndarray] = {}
        self.built: Dict[Tuple[int, int], np.ndarray] = {}      # columns with a building near the top
        self.trunks: Dict[Tuple[int, int], np.ndarray] = {}     # columns with a tree trunk on the ground
        self._rigid: Optional[Dict[Tuple[int, int], np.ndarray]] = None
        self.buildings = 0
        self.moved_columns = 0
        self.lost_tiles = 0

    # -------------------------------------------------------------- pass 1
    def observe(self, c: NumericChunk) -> None:
        h = ground_heights(c)
        self.heights[(c.cx, c.cz)] = h
        self.max_ground = max(self.max_ground, int(h.max()))
        b = np.asarray(c.blocks, np.int64)
        y = np.arange(c.height)[:, None, None]
        near_top = y > (h[None].astype(np.int32) - KEEP)
        built = (PROTECTED[b] & near_top).any(axis=0) & (h >= 0)
        if built.any():
            self.built[(c.cx, c.cz)] = built
        # trunks: logs stacked on the ground; the y of their top log (-1: no trunk)
        logs = LOGS[b]
        top = np.full((16, 16), -1, np.int32)
        on_ground = logs[np.clip(h.astype(np.int64) + 1, 0, c.height - 1), np.arange(16)[:, None], np.arange(16)[None, :]]
        for z, x in zip(*np.nonzero(on_ground & (h >= 0))):
            y0 = int(h[z, x]) + 1
            y1 = y0
            while y1 + 1 < c.height and logs[y1 + 1, z, x]:
                y1 += 1
            if y1 - y0 + 1 >= TRUNK_MIN:
                top[z, x] = y1
        if (top >= 0).any():
            self.trunks[(c.cx, c.cz)] = top

    @property
    def needed(self) -> bool:
        return self.max_ground > self.top_ground

    @property
    def ratio(self) -> float:
        """How much of the ground above the knee is kept (1 = nothing compressed)."""
        if not self.needed:
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

    def _rigid_shifts(self) -> Dict[Tuple[int, int], np.ndarray]:
        """One shift for every column of a building (its ground included): the building comes
        down as a whole.  Columns with a building near the top, BUILD_RADIUS apart at most, are
        one building (houses of a village are separate, their paths are ground)."""
        if self._rigid is not None:
            return self._rigid
        self._rigid = {}
        cols = set()
        for (cx, cz), m in self.built.items():
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
            base = [int(self._base_shifts(x >> 4, z >> 4)[z & 15, x & 15]) for x, z in comp]
            if not any(base):
                continue
            hs = [int(self.heights[(x >> 4, z >> 4)][z & 15, x & 15]) for x, z in comp]
            # the median shift, but enough for the highest ground under it to fit
            sh = max(int(np.median(base)), max(hs) - self.top_ground, 0)
            for x, z in comp:
                a = self._rigid.setdefault((x >> 4, z >> 4), np.full((16, 16), -1, np.int32))
                a[z & 15, x & 15] = sh
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
        else:
            a = int(self.heights[(xi >> 4, zi >> 4)][zi & 15, xi & 15]) - KEEP + 1 - s
        if y >= a + s:
            return y - s
        if y >= a:
            return float(a)                                       # inside the removed band: onto it
        return y

    def _band_starts(self, c: NumericChunk, s: np.ndarray) -> np.ndarray:
        """First removed y of every column: just under the surface, or deeper where that band
        would go through a built block (a base inside the mountain comes down whole)."""
        h = self.heights[(c.cx, c.cz)].astype(np.int32)
        start = h - KEEP + 1 - s
        prot = PROTECTED[np.asarray(c.blocks, np.int64)]
        for t in c.tile_entities:
            try:
                prot[int(nbt.get(t, "y")), int(nbt.get(t, "z")) & 15, int(nbt.get(t, "x")) & 15] = True
            except (TypeError, ValueError, IndexError):
                pass
        cs = np.concatenate([np.zeros((1, 16, 16), np.int32), np.cumsum(prot, axis=0, dtype=np.int32)])
        for z, x in zip(*np.nonzero(s)):
            sh, a0 = int(s[z, x]), int(start[z, x])
            col = cs[:, z, x]
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
        if not s.any():
            return c
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
        return c


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
