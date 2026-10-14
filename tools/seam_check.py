#!/usr/bin/env python3
"""Measure the seam between a converted world and the terrain the game generated around it.

    python tools/seam_check.py CONVERTED GAME --chunks SELECTION.csv [--dim overworld] [--json OUT.json] [--png OUT.png]

CONVERTED   the world WorldBridge wrote (its chunks: the selection plus, when a ring was written, the ring);
GAME        the same world after the game opened it and generated the surroundings (forceload, spawn at the
            border, ticking areas...) and saved it; any format WorldBridge can read;
--chunks    the converted chunks: an MCA Selector CSV (the selection that was converted), as the chunk
            coordinates of CONVERTED (``--shift DX,DZ`` moves the CSV when the converter moved the chunks).

Every chunk is classed as ``sel`` (a chunk of the selection), ``ring`` (in CONVERTED but not in the selection:
WorldBridge's ring, fill or 3D ring) or ``game`` (in GAME only).  For every pair of neighbouring columns across
a border between two classes the tool takes the y of the highest solid block that is not foliage (leaves,
logs, plants, snow layers and the water above the sea floor do not count) on each side, and reports

* ``outer``   the border seen by a player: (sel + ring) | game  (with ``--ring exclude``: sel | everything else);
* ``inner``   sel | ring  (where the ring starts, only when a ring was written);
* ``ring_game`` ring | game  (the ring's outer edge, only when a ring was written);

each with the number of pairs, mean / median / p95 / max of |jump|, the share of jumps above 3 and above 8
blocks ("walls"), the mean signed difference (inner minus outer side), the same per edge (N, S, E, W), the
water-versus-land mismatches (one side topped by water, the other dry; water higher than the dry neighbour's
ground = it would spill) and the columns that are void on one side only (no block at all).

``baseline`` is the same statistic between neighbouring columns inside natural game terrain at least
``--baseline-margin`` chunks away from the converted part, so the roughness of the game's own terrain is not
counted as a seam; ``baseline_sel`` is the same inside the converted chunks.  The verdict compares ``outer`` to
the baseline: OK (within it), STEP (some walls) or CUT (a wall along the edge).

Output: JSON (``--json``) and one summary line on stdout; ``--png`` writes a top-down height map of the border
area (left: ground height, right: |jump| across the border) with the class borders drawn.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import struct
import sys
import zlib
from typing import Dict, Iterable, List, Optional, Set, Tuple

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worldbridge import mapview  # noqa: E402

Chunk = Tuple[int, int]
EMPTY = -9999                       # no block in the column
SEL, RING, GAME = 1, 2, 3
CLASS_NAME = {SEL: "sel", RING: "ring", GAME: "game"}
DIMS = {"overworld": 0, "nether": -1, "end": 1}

# verdict thresholds (excess over the baseline): a seam is a STEP when it has more walls than natural terrain
# and a CUT when a good part of the edge is a wall or the average jump is far above the baseline
WALL_LOW, WALL_HIGH = 3, 8
STEP_EXCESS3, STEP_EXCESS8, STEP_EXCESS_MEAN = 0.05, 0.02, 1.5
CUT_EXCESS3, CUT_EXCESS_MEAN = 0.30, 4.0

# ---------------------------------------------------------------- reading a world

_SOFT = ("leaves", "log", "wood", "stem", "hyphae", "sapling", "grass", "fern", "flower", "bush", "vine", "snow",
         "tulip", "orchid", "allium", "bluet", "daisy", "poppy", "dandelion", "cornflower", "lily", "rose",
         "mushroom", "cactus", "reed", "sugar_cane", "bamboo", "kelp", "seagrass", "pickle", "coral", "torch",
         "pumpkin", "melon", "cocoa", "web", "berry", "dripleaf", "azalea", "moss_carpet", "roots", "propagule",
         "peony", "lilac", "sunflower", "dead_bush", "fungus", "sprouts", "weeping", "twisting", "chorus", "plant")
# numeric (pre-1.13) ids: sapling, logs, leaves, tall grass, dead bush, flowers, mushrooms, torch, snow layer,
# cactus, reeds, pumpkin, melon, vines, lily pad, cocoa, double plants, logs2, leaves2
_SOFT_IDS = (6, 17, 18, 31, 32, 37, 38, 39, 40, 50, 59, 78, 81, 83, 86, 99, 100, 103, 104, 105, 106, 111, 127,
             141, 142, 161, 162, 175)


def _is_soft(name: str, orig) -> bool:
    """Foliage and other things that are not the ground: ``orig`` is the map's own air test (air, glass, ...)."""
    if orig(name):
        return True
    n = name.split(":", 1)[-1].lower()
    if n in ("snow_block", "grass_block", "mushroom_stem"):
        return False
    return any(k in n for k in _SOFT)


@contextlib.contextmanager
def ground_mode():
    """Make the map tiles report the ground: vegetation, snow layers and logs count as air."""
    orig_air, orig_num = mapview.is_air, mapview._NUM_AIR
    cache: Dict[str, bool] = {}

    def soft(name: str) -> bool:
        v = cache.get(name)
        if v is None:
            v = cache[name] = _is_soft(name, orig_air)
        return v

    num = orig_num.copy()
    for bid in _SOFT_IDS:
        num[bid * 16:bid * 16 + 16] = True
    mapview.is_air, mapview._NUM_AIR = soft, num
    try:
        yield
    finally:
        mapview.is_air, mapview._NUM_AIR = orig_air, orig_num


Columns = Dict[Chunk, Tuple[np.ndarray, np.ndarray]]      # chunk -> (ground [z, x], water surface [z, x] or -1)


def tile_columns(tile) -> Tuple[np.ndarray, np.ndarray]:
    h = tile.height.astype(np.int32)
    has = h > -32000
    dep = tile.depth.astype(np.int32)
    ground = np.where(has, np.where(dep > 0, h - dep, h), EMPTY)
    water = np.where(has & (dep > 0), h, -1)
    return ground.astype(np.int32), water.astype(np.int32)


def read_columns(path: str, dim: int = 0, only: Optional[Iterable[Chunk]] = None) -> Columns:
    """{(cx, cz): (ground [z, x], water [z, x])} of one dimension of any world WorldBridge can read."""
    out: Columns = {}
    with ground_mode():
        src = mapview.open_map(path)
        try:
            if dim not in src.dimensions():
                return out
            want = None if only is None else set(only)
            for cx, cz in src.chunk_coords(dim):
                if want is not None and (cx, cz) not in want:
                    continue
                try:
                    t = src.tile(dim, cx, cz)
                except Exception:  # noqa: BLE001  an unreadable chunk is a hole, like for the game
                    t = None
                if t is not None:
                    out[(cx, cz)] = tile_columns(t)
        finally:
            src.close()
    return out


# ---------------------------------------------------------------- classes and grid

def classify(selection: Set[Chunk], converted: Iterable[Chunk], game: Iterable[Chunk]) -> Dict[Chunk, int]:
    """sel = selected and converted; ring = converted but not selected; game = in the game's save only."""
    conv = set(converted)
    k: Dict[Chunk, int] = {c: (SEL if c in selection else RING) for c in conv}
    for c in game:
        k.setdefault(c, GAME)
    return k


class Grid:
    """The columns of all classified chunks on one array (x first, then z)."""

    def __init__(self, cols: Columns, klass: Dict[Chunk, int]):
        cs = [c for c in klass if c in cols]
        self.x0 = min(c[0] for c in cs)
        self.z0 = min(c[1] for c in cs)
        nx = (max(c[0] for c in cs) - self.x0 + 1) * 16
        nz = (max(c[1] for c in cs) - self.z0 + 1) * 16
        self.ground = np.full((nx, nz), EMPTY, np.int32)
        self.water = np.full((nx, nz), -1, np.int32)
        self.klass = np.zeros((nx, nz), np.int8)
        self.chunk_class = np.zeros((nx // 16, nz // 16), np.int8)
        for c in cs:
            sx, sz = (c[0] - self.x0) * 16, (c[1] - self.z0) * 16
            g, w = cols[c]
            self.ground[sx:sx + 16, sz:sz + 16] = g.T          # tiles are [z, x]
            self.water[sx:sx + 16, sz:sz + 16] = w.T
            self.klass[sx:sx + 16, sz:sz + 16] = klass[c]
            self.chunk_class[c[0] - self.x0, c[1] - self.z0] = klass[c]

    def chunk_distance(self, mask: np.ndarray) -> np.ndarray:
        """Chebyshev distance in chunks from every chunk to the nearest chunk where ``mask`` is true (large if none)."""
        big = 10 ** 6
        d = np.where(mask, 0, big).astype(np.int64)
        nx, nz = d.shape
        for _ in range(max(nx, nz)):                         # relaxation; the grids are small
            m = d.copy()
            m[1:, :] = np.minimum(m[1:, :], d[:-1, :] + 1)
            m[:-1, :] = np.minimum(m[:-1, :], d[1:, :] + 1)
            m[:, 1:] = np.minimum(m[:, 1:], m[:, :-1] + 1)
            m[:, :-1] = np.minimum(m[:, :-1], m[:, 1:] + 1)
            m[1:, 1:] = np.minimum(m[1:, 1:], d[:-1, :-1] + 1)
            m[:-1, :-1] = np.minimum(m[:-1, :-1], d[1:, 1:] + 1)
            m[1:, :-1] = np.minimum(m[1:, :-1], d[:-1, 1:] + 1)
            m[:-1, 1:] = np.minimum(m[:-1, 1:], d[1:, :-1] + 1)
            if (m == d).all():
                break
            d = m
        return d


# ---------------------------------------------------------------- pairs and statistics

DIRS = {"E": (1, 0), "W": (-1, 0), "S": (0, 1), "N": (0, -1)}      # direction from side a to side b


def border_pairs(grid: Grid, in_a: np.ndarray, in_b: np.ndarray) -> Dict[str, Tuple[np.ndarray, ...]]:
    """Pairs (a, b) of neighbouring columns with a in ``in_a`` and b in ``in_b`` (boolean column masks), per
    direction a -> b: (xa, za, xb, zb) index arrays."""
    out = {}
    nx, nz = grid.ground.shape
    for name, (dx, dz) in DIRS.items():
        xa0, xa1 = max(0, -dx), nx - max(0, dx)
        za0, za1 = max(0, -dz), nz - max(0, dz)
        a = in_a[xa0:xa1, za0:za1]
        b = in_b[xa0 + dx:xa1 + dx, za0 + dz:za1 + dz]
        ix, iz = np.nonzero(a & b)
        out[name] = (ix + xa0, iz + za0, ix + xa0 + dx, iz + za0 + dz)
    return out


def stats(jumps: np.ndarray) -> dict:
    if jumps.size == 0:
        return {"n": 0}
    j = jumps.astype(np.float64)
    return {"n": int(j.size), "mean": round(float(j.mean()), 3), "p50": float(np.percentile(j, 50)),
            "p95": float(np.percentile(j, 95)), "max": float(j.max()),
            "share_gt3": round(float((j > WALL_LOW).mean()), 4), "share_gt8": round(float((j > WALL_HIGH).mean()), 4)}


def measure_pairs(grid: Grid, pairs: Dict[str, Tuple[np.ndarray, ...]]) -> dict:
    """Statistics over the pairs of all directions; ``jump`` = |ground a - ground b|."""
    allj, alla, allb = [], [], []
    wa_all, wb_all = [], []
    per_edge = {}
    void = 0
    for name, (xa, za, xb, zb) in pairs.items():
        ga, gb = grid.ground[xa, za], grid.ground[xb, zb]
        wa, wb = grid.water[xa, za], grid.water[xb, zb]
        ok = (ga > EMPTY) & (gb > EMPTY)
        void += int((~ok).sum())
        j = np.abs(ga[ok] - gb[ok])
        per_edge[name] = stats(j)
        allj.append(j)
        alla.append(ga[ok])
        allb.append(gb[ok])
        wa_all.append(wa[ok])
        wb_all.append(wb[ok])
    if not allj or sum(len(x) for x in allj) == 0:
        return {"n": 0, "void_pairs": void}
    j, a, b = np.concatenate(allj), np.concatenate(alla), np.concatenate(allb)
    wa, wb = np.concatenate(wa_all), np.concatenate(wb_all)
    res = stats(j)
    res["bias_a_minus_b"] = round(float((a - b).mean()), 3)
    res["per_edge"] = per_edge
    res["void_pairs"] = void
    # water against land: one side topped by water, the other dry
    wet_a, wet_b = wa >= 0, wb >= 0
    mism = wet_a != wet_b
    spill = (wet_a & ~wet_b & (wa > b)) | (wet_b & ~wet_a & (wb > a))
    res["water_land_share"] = round(float(mism.mean()), 4)
    res["water_spill_share"] = round(float(spill.mean()), 4)
    res["water_land_n"] = int(mism.sum())
    res["water_spill_n"] = int(spill.sum())
    return res


def baseline_pairs(grid: Grid, cls: int, away_from: np.ndarray, margin: int) -> Optional[Dict[str, Tuple[np.ndarray, ...]]]:
    """Neighbouring columns both in chunks of class ``cls`` whose chunk is at least ``margin`` chunks from the
    chunks in ``away_from`` (a chunk-level boolean array)."""
    dist = grid.chunk_distance(away_from)
    ok_chunk = (grid.chunk_class == cls) & (dist >= margin)
    col = np.kron(ok_chunk, np.ones((16, 16), bool))
    return border_pairs(grid, col, col)


def verdict(seam: dict, base: dict) -> str:
    """OK / STEP / CUT of the seam statistics against the baseline's."""
    if not seam.get("n"):
        return "NO-DATA"
    if not base.get("n"):
        base = {"mean": 0.0, "share_gt3": 0.0, "share_gt8": 0.0}
    e3 = seam["share_gt3"] - base["share_gt3"]
    e8 = seam["share_gt8"] - base["share_gt8"]
    em = seam["mean"] - base["mean"]
    if e3 >= CUT_EXCESS3 or em >= CUT_EXCESS_MEAN:
        return "CUT"
    if e3 >= STEP_EXCESS3 or e8 >= STEP_EXCESS8 or em >= STEP_EXCESS_MEAN:
        return "STEP"
    return "OK"


def seam_report_from_columns(conv: Columns, game: Columns, selection: Set[Chunk], ring: str = "include",
                             baseline_margin: int = 2, converted_from: str = "game") -> Tuple[dict, Grid]:
    """The whole measurement on already-read columns (see :func:`read_columns`)."""
    cols: Columns = dict(conv)
    if converted_from == "game":
        cols.update({c: v for c, v in game.items() if c in conv})
    klass = classify(selection & set(conv), conv, [c for c in game if c not in conv])
    cols.update({c: v for c, v in game.items() if klass.get(c) == GAME})
    grid = Grid(cols, klass)
    kc = grid.klass
    sel, rng, gm = kc == SEL, kc == RING, kc == GAME
    has_ring = bool(rng.any())
    rep: dict = {"chunks": {"sel": int((grid.chunk_class == SEL).sum()), "ring": int((grid.chunk_class == RING).sum()),
                            "game": int((grid.chunk_class == GAME).sum())}, "ring_written": has_ring,
                 "ring_mode": ring}
    if ring == "exclude":
        outer_a, outer_b = sel, ~sel & (kc > 0)
    else:
        outer_a, outer_b = sel | rng, gm
    outer = measure_pairs(grid, border_pairs(grid, outer_a, outer_b))
    rep["outer"] = outer
    if has_ring:
        rep["inner"] = measure_pairs(grid, border_pairs(grid, sel, rng))
        rep["ring_game"] = measure_pairs(grid, border_pairs(grid, rng, gm))
        rep["sel_game"] = measure_pairs(grid, border_pairs(grid, sel, gm))
    # the game's own roughness, away from the border; the converted terrain's, away from its edge
    cc = grid.chunk_class
    rep["baseline"] = measure_pairs(grid, baseline_pairs(grid, GAME, cc != GAME, baseline_margin))
    rep["baseline"].pop("per_edge", None)
    rep["baseline_sel"] = measure_pairs(grid, baseline_pairs(grid, SEL, cc != SEL, 1))
    rep["baseline_sel"].pop("per_edge", None)
    base = rep["baseline"] if rep["baseline"].get("n", 0) >= 200 else rep["baseline_sel"]
    rep["baseline_used"] = "baseline" if base is rep["baseline"] else "baseline_sel"
    rep["verdict"] = verdict(outer, base)
    if has_ring:
        rep["verdict_ring_game"] = verdict(rep["ring_game"], base)
        rep["verdict_inner"] = verdict(rep["inner"], base)
    return rep, grid


def summary_line(rep: dict, label: str = "") -> str:
    o, b = rep["outer"], rep.get("baseline", {})
    if not o.get("n"):
        return f"{label} no border pairs (chunks {rep['chunks']})"
    s = (f"{label} {rep['verdict']}: outer n={o['n']} mean {o['mean']:.2f} p95 {o['p95']:.0f} max {o['max']:.0f} "
         f">3 {o['share_gt3'] * 100:.1f}% >8 {o['share_gt8'] * 100:.1f}% bias {o['bias_a_minus_b']:+.1f}")
    if b.get("n"):
        s += (f" | baseline n={b['n']} mean {b['mean']:.2f} p95 {b['p95']:.0f} >3 {b['share_gt3'] * 100:.1f}% "
              f">8 {b['share_gt8'] * 100:.1f}%")
    rg = rep.get("ring_game")
    if rg and rg.get("n"):
        s += (f" | ring|game {rep['verdict_ring_game']} mean {rg['mean']:.2f} p95 {rg['p95']:.0f} "
              f">8 {rg['share_gt8'] * 100:.1f}%")
    return s


# ---------------------------------------------------------------- PNG

def write_png(path: str, rgb: np.ndarray) -> None:
    """A minimal PNG writer (8-bit RGB), no imaging library needed."""
    h, w, _ = rgb.shape
    raw = b"".join(b"\x00" + rgb[y].tobytes() for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        c = struct.pack(">I", len(data)) + tag + data
        return c + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def _ramp(h: np.ndarray, water: np.ndarray, lo: float, hi: float) -> np.ndarray:
    """Height colours: green lowlands to pale highlands, water in blue (darker where the floor is lower)."""
    t = np.clip((h - lo) / max(1.0, hi - lo), 0, 1)
    img = np.stack([40 + 190 * t, 100 + 110 * np.sin(t * np.pi), 60 + 70 * t], -1).astype(np.uint8)
    wet = water >= 0
    blue = np.stack([np.full(t.shape, 30.0), np.full(t.shape, 70.0), 150 - 70 * t], -1).astype(np.uint8)
    img[wet] = blue[wet]
    img[h <= EMPTY] = (0, 0, 0)
    return img


def render_png(grid: Grid, path: str, scale: int = 3, pad_chunks: int = 4) -> None:
    """Left: ground height (water bluish) with the chunk classes outlined (sel red, ring yellow); right: |jump| of
    each column against its neighbours across a class border (white = 16+ blocks)."""
    cc = grid.chunk_class
    xs, zs = np.nonzero((cc == SEL) | (cc == RING))
    if xs.size == 0:
        return
    near = grid.chunk_distance((cc == SEL) | (cc == RING)) <= pad_chunks
    xs, zs = np.nonzero(near & (cc > 0))
    x0, x1, z0, z1 = xs.min() * 16, (xs.max() + 1) * 16, zs.min() * 16, (zs.max() + 1) * 16
    g, w, k = grid.ground[x0:x1, z0:z1], grid.water[x0:x1, z0:z1], grid.klass[x0:x1, z0:z1]
    valid = g > EMPTY
    lo, hi = (float(np.percentile(g[valid], 2)), float(np.percentile(g[valid], 98))) if valid.any() else (0, 1)
    img = _ramp(g.astype(np.float64), w, lo, hi)                      # [x, z, 3]
    # class borders and the jump across them, per column
    edge = np.zeros(k.shape, bool)
    jm = np.zeros(g.shape, np.float64)
    for dx, dz in ((1, 0), (0, 1)):
        sa = (slice(0, g.shape[0] - dx), slice(0, g.shape[1] - dz))
        sb = (slice(dx, None), slice(dz, None))
        a, b = g[sa], g[sb]
        ka, kb = k[sa], k[sb]
        m = (ka != kb) & (ka > 0) & (kb > 0)
        edge[sa] |= m
        edge[sb] |= m
        d = np.where(m & (a > EMPTY) & (b > EMPTY), np.abs(a - b), 0).astype(np.float64)
        jm[sa] = np.maximum(jm[sa], d)
        jm[sb] = np.maximum(jm[sb], d)
    t = np.clip(jm / 16.0, 0, 1)
    jimg = np.stack([60 + 195 * t, 60 + 195 * (t > 0.5) * (t - 0.5) * 2, 60 + 60 * (1 - t)], -1).astype(np.uint8)
    jimg[jm == 0] = (45, 45, 55)
    left = img.copy()
    left[edge] = (255, 255, 255)
    # chunk class tint at the chunk grid: sel outlined red, ring yellow (chunk borders only)
    for cx in range(x0 // 16, x1 // 16):
        for cz in range(z0 // 16, z1 // 16):
            c = cc[cx, cz]
            if c in (SEL, RING):
                col = (230, 40, 40) if c == SEL else (240, 210, 40)
                sx, sz = cx * 16 - x0, cz * 16 - z0
                left[sx, sz:sz + 16] = col
                left[sx + 15, sz:sz + 16] = col
                left[sx:sx + 16, sz] = col
                left[sx:sx + 16, sz + 15] = col
    both = np.concatenate([left, np.full((4, left.shape[1], 3), 255, np.uint8), jimg], axis=0)   # [x, z]
    pic = np.transpose(both, (1, 0, 2))                                                            # rows = z (north up)
    pic = np.repeat(np.repeat(pic, scale, axis=0), scale, axis=1)
    write_png(path, np.ascontiguousarray(pic))


# ---------------------------------------------------------------- command line

def _parse_dim(s: str) -> int:
    return DIMS[s] if s in DIMS else int(s)


def run(converted: str, game: str, selection: Set[Chunk], dim: int = 0, ring: str = "include",
        baseline_margin: int = 2, converted_from: str = "game", png: Optional[str] = None) -> dict:
    conv = read_columns(converted, dim)
    gm = read_columns(game, dim)
    if not conv and not gm:
        return {"error": "no chunks in this dimension"}
    sel = {c for c in selection if c in conv}
    rep, grid = seam_report_from_columns(conv, gm, sel, ring, baseline_margin, converted_from)
    rep["dim"] = dim
    rep["selection_chunks"] = len(selection)
    rep["selection_present"] = len(sel)
    if png and rep["chunks"]["sel"]:
        render_png(grid, png)
        rep["png"] = png
    return rep


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("converted")
    ap.add_argument("game")
    ap.add_argument("--chunks", required=True, help="MCA Selector CSV of the converted chunks")
    ap.add_argument("--shift", default="0,0", help="DX,DZ in chunks added to the CSV chunks")
    ap.add_argument("--dim", default="overworld", help="overworld, nether, end or the number")
    ap.add_argument("--ring", choices=("include", "exclude"), default="include",
                    help="include: the ring counts as converted (outer = sel+ring | game); exclude: outer = sel | rest")
    ap.add_argument("--baseline-margin", type=int, default=2, help="chunks away from the converted part")
    ap.add_argument("--converted-from", choices=("game", "converted"), default="game",
                    help="read the converted chunks from the game's save (what a player sees) or as written")
    ap.add_argument("--json", help="write the report here")
    ap.add_argument("--png", help="write a height map of the border here")
    ap.add_argument("--label", default="")
    a = ap.parse_args(argv)
    from worldbridge.selection import load_csv

    dx, dz = (int(v) for v in a.shift.split(","))
    sel = {(x + dx, z + dz) for x, z in load_csv(a.chunks)}
    rep = run(a.converted, a.game, sel, _parse_dim(a.dim), a.ring, a.baseline_margin, a.converted_from, a.png)
    if a.json:
        with open(a.json, "w") as f:
            json.dump(rep, f, indent=1)
    print(rep["error"] if "error" in rep else summary_line(rep, a.label))
    return 0 if "error" not in rep else 1


if __name__ == "__main__":
    sys.exit(main())
