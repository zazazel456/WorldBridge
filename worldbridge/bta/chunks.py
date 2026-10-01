"""First pass: a BTA chunk -> mapped vanilla states, block entities, entities and biomes."""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .. import nbt
from . import biomes as bio
from . import blockmap, stats
from .blockmap import MapCtx
from .entities import convert_entity, convert_tile, normalise_te_id, statue_to_armor_stand
from .nbtio import gb, gc, gi, gs
from .palette import Palette
from .states import AIR, BlockState, by_id, count as state_count
from .world import BtaChunk


def index(lx: int, y: int, lz: int) -> int:
    return (y << 8) | (lz << 4) | lx


class Stage1:
    """A chunk after per-block mapping, before neighbour-dependent post processing."""

    __slots__ = ("cx", "cz", "states", "block_entities", "entities", "biomes", "legacy_chests", "ticks_on_unload",
                 "stats")

    def __init__(self, cx: int, cz: int):
        self.cx = cx
        self.cz = cz
        self.states = np.zeros((256, 16, 16), np.uint32)          # state ids, [y, z, x]
        self.block_entities: Dict[int, nbt.CompoundTag] = {}       # index(lx, y, lz) -> 1.17 block entity
        self.entities: List[nbt.CompoundTag] = []
        self.biomes: List[Optional[str]] = [None] * 1024           # 4x4x4 cells, (y>>2)<<4 | (z>>2)<<2 | (x>>2)
        self.legacy_chests: List[int] = []
        self.ticks_on_unload = -1
        self.stats: Dict[str, int] = {}

    def copy_for_output(self) -> "Stage1":
        c = Stage1(self.cx, self.cz)
        c.states = self.states.copy()
        c.block_entities = {k: nbt.copy(v) for k, v in self.block_entities.items()}
        c.entities = list(self.entities)
        c.biomes = self.biomes
        c.legacy_chests = list(self.legacy_chests)
        c.ticks_on_unload = self.ticks_on_unload
        return c


_NEEDS_BE_NAMES = {"minecraft:chest", "minecraft:furnace", "minecraft:blast_furnace", "minecraft:dispenser",
                   "minecraft:dropper", "minecraft:barrel", "minecraft:jukebox", "minecraft:spawner", "minecraft:red_bed",
                   "minecraft:skeleton_skull", "minecraft:campfire", "minecraft:white_banner"}


def needs_block_entity(s: BlockState) -> bool:
    """Vanilla blocks that need a block entity even when the BTA block had no tile entity."""
    return s.name in _NEEDS_BE_NAMES or s.name.endswith("_sign")


class _Lut:
    """Boolean table over state ids, extended as new states get interned."""

    def __init__(self, pred):
        self.pred = pred
        self.table = np.zeros(0, bool)

    def get(self) -> np.ndarray:
        n = state_count()
        if len(self.table) < n:
            extra = np.fromiter((self.pred(by_id(i)) for i in range(len(self.table), n)), bool, n - len(self.table))
            self.table = np.concatenate([self.table, extra])
        return self.table


NEEDS_BE = _Lut(needs_block_entity)


def _utf16_units(s: str):
    b = s.encode("utf-16-be")
    return [int.from_bytes(b[i:i + 2], "big") for i in range(0, len(b), 2)]


class ChunkConverter:
    def __init__(self, palette: Palette, dimension: int):
        self.palette = palette
        self.dimension = dimension
        self.cache: Dict[int, int] = {}          # (id << 8 | meta) -> state id, for blocks without tile entity
        self._biome_memo: Dict[str, str] = {}
        self._bucket: Dict[str, int] = {}

    def _map_key(self, key: int, ctx: MapCtx) -> int:
        sid = self.cache.get(key)
        if sid is None:
            st = blockmap.map_block(key >> 8, key & 0xFF, ctx)
            if st is None:
                stats.inc(f"block.unknown.{key >> 8}")
                st = AIR
            sid = st.id
            self.cache[key] = sid
        return sid

    def convert(self, c: BtaChunk) -> Stage1:
        s = Stage1(c.x, c.z)
        s.ticks_on_unload = c.ticks_on_unload
        base_x, base_z = c.x << 4, c.z << 4
        tes: Dict[int, dict] = {}
        for te in c.tile_entities:
            x, y, z = gi(te, "x"), gi(te, "y"), gi(te, "z")
            if x >> 4 != c.x or z >> 4 != c.z or not 0 <= y <= 255:
                stats.inc("tileentity.dropped.outside_chunk")
                continue
            tes[index(x & 15, y, z & 15)] = te
        ctx = MapCtx(self.palette)
        ctx.dimension = self.dimension
        ids = c.blocks.astype(np.uint32)
        keys = (ids << 8) | c.data.astype(np.uint32)
        flat_ids = ids.reshape(-1)
        flat_keys = keys.reshape(-1)
        nonzero = flat_ids != 0
        # histogram of the BTA blocks for the report
        hist = np.bincount(flat_ids[nonzero], minlength=1)
        for bid in np.flatnonzero(hist):
            name = blockmap.bta_name(int(bid))
            stats.add(f"bta_block.{name if name is not None else f'unknown_{bid}'}", int(hist[bid]))
        special = np.zeros(65536, bool)
        if tes:
            special[np.fromiter(tes.keys(), np.int64, len(tes))] = True
        special |= flat_ids == 523
        plain = nonzero & ~special
        out = np.zeros(65536, np.uint32)  # AIR is state 0
        if plain.any():
            uniq, inv = np.unique(flat_keys[plain], return_inverse=True)
            lut = np.fromiter((self._map_key(int(k), ctx) for k in uniq), np.uint32, len(uniq))
            out[plain] = lut[inv]
        for idx in np.flatnonzero(nonzero & special):
            idx = int(idx)
            bid = int(flat_ids[idx])
            meta = int(flat_keys[idx] & 0xFF)
            te = tes.get(idx)
            y, lz, lx = idx >> 8, (idx >> 4) & 15, idx & 15
            ctx.tile_entity = te
            ctx.x, ctx.y, ctx.z = base_x + lx, y, base_z + lz
            st = self._moving_piston(te) if bid == 523 else blockmap.map_block(bid, meta, ctx)
            ctx.tile_entity = None
            if st is None:
                stats.inc(f"block.unknown.{bid}")
                st = AIR
            out[idx] = st.id
        # legacy chests and statues
        s.legacy_chests = [int(i) for i in np.flatnonzero((flat_ids == 680) | (flat_ids == 681))]
        if tes:
            for idx in sorted(tes):
                bid = int(flat_ids[idx])
                if blockmap.is_statue_lower(bid):
                    y, lz, lx = idx >> 8, (idx >> 4) & 15, idx & 15
                    statue_to_armor_stand(tes.pop(idx), int(flat_keys[idx] & 15), base_x + lx, y, base_z + lz,
                                          self.palette, s.entities)
        # block entities: every BTA tile entity, plus a fresh one for vanilla blocks that require it
        sections_used = out.reshape(16, 4096).any(axis=1)
        need = NEEDS_BE.get()[out]
        need &= np.repeat(sections_used, 4096)
        te_idx = set(i for i in tes if sections_used[i >> 12])
        todo = sorted(set(int(i) for i in np.flatnonzero(need)) | te_idx)
        for idx in todo:
            te = tes.pop(idx, None)
            st = by_id(int(out[idx]))
            y, lz, lx = idx >> 8, (idx >> 4) & 15, idx & 15
            src = te
            if te is not None and normalise_te_id(gs(te, "id")) == "piston_moving":
                src = gc(te, "tileEntity")
            r = convert_tile(src, st, base_x + lx, y, base_z + lz, self.palette, s.entities)
            if r.state is not None:
                out[idx] = r.state.id
            if r.block_entity is not None:
                s.block_entities[idx] = r.block_entity
        # tile entities left over sit on blocks that were not converted to anything needing them
        for idx, te in tes.items():
            y, lz, lx = idx >> 8, (idx >> 4) & 15, idx & 15
            convert_tile(te, AIR, base_x + lx, y, base_z + lz, self.palette, s.entities)
            stats.inc("tileentity.orphan")
        s.states = out.reshape(256, 16, 16)
        for e in c.entities:
            extra: List[nbt.CompoundTag] = []
            conv = convert_entity(e, self.dimension, self.palette, extra)
            if conv is not None:
                s.entities.append(conv)
            s.entities.extend(extra)
        self._biomes(c, s)
        return s

    def _moving_piston(self, te: Optional[dict]) -> BlockState:
        """Moving pistons are frozen at their final state."""
        if te is None:
            return AIR
        bid = gi(te, "blockId") & 16383
        data = gi(te, "blockData") & 0xFF
        if bid in (522, 525) and not gb(te, "extending"):
            return AIR
        ctx = MapCtx(self.palette)
        ctx.tile_entity = gc(te, "tileEntity")
        st = blockmap.map_block(bid, data, ctx)
        stats.inc("block.moving_piston_resolved")
        return AIR if st is None else st

    def _mapped(self, name: str) -> str:
        v = self._biome_memo.get(name)
        if v is None:
            v = self._biome_memo[name] = bio.map_biome(name, self.dimension)
        return v

    def _biomes(self, c: BtaChunk, s: Stage1) -> None:
        """BTA biomes are per column and per 8 blocks of height; vanilla uses 4x4x4 cells: take the
        majority of each cell (ties broken in the reference conversion's order)."""
        names = [self._mapped(n) for n in c.biome_names]
        # sample of cell (cy, cz, cx) = BTA biome at (cx*4+dx, cy*4, cz*4+dz)
        raw = c.biomes[np.arange(64) * 4 >> 3]                        # [64, 16 z, 16 x]
        cells = raw.reshape(64, 4, 4, 4, 4).transpose(0, 1, 3, 2, 4).reshape(64, 4, 4, 16)  # [cy, cz, cx, dz*4+dx]
        result: List[Optional[str]] = [None] * 1024
        known = [False] * 1024
        first = cells[..., 0]
        uniform = (cells == first[..., None]).all(axis=-1)
        for cy in range(64):
            for cz in range(4):
                for cx in range(4):
                    i = (cy << 4) | (cz << 2) | cx
                    if uniform[cy, cz, cx]:
                        v = int(first[cy, cz, cx])
                        if v >= 0:
                            result[i] = names[v]
                            known[i] = True
                        continue
                    votes: Dict[str, int] = {}
                    for v in cells[cy, cz, cx]:
                        v = int(v)
                        if v < 0:
                            continue
                        b = names[v]
                        votes[b] = votes.get(b, 0) + 1
                    if not votes:
                        continue
                    order = sorted(enumerate(votes), key=lambda t: (self._bucket_of(t[1]), t[0]))
                    best, best_n = None, 0
                    for _pos, b in order:
                        if votes[b] > best_n:
                            best, best_n = b, votes[b]
                    result[i] = best
                    known[i] = best is not None
        fb = bio.fallback(self.dimension)
        for col in range(16):
            last = None
            for cy in range(64):
                i = (cy << 4) | col
                if known[i]:
                    last = result[i]
                else:
                    result[i] = last
            nxt = None
            for cy in range(63, -1, -1):
                i = (cy << 4) | col
                if known[i]:
                    nxt = result[i]
                elif result[i] is None:
                    result[i] = nxt if nxt is not None else fb
        s.biomes = result

    def _bucket_of(self, name: str) -> int:
        b = self._bucket.get(name)
        if b is None:
            h = 0
            for cu in _utf16_units(name):
                h = (31 * h + cu) & 0xFFFFFFFF
            h ^= h >> 16
            b = self._bucket[name] = h & 15
        return b
