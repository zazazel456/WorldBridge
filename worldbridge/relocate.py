"""Selected chunks moved somewhere else in the converted world (map tab: "Sposta i chunk selezionati",
command line ``--move-to``).

The centre of the selection of each dimension lands on the chosen point (the world's centre 0, 0 by
default; the Nether's point is the overworld's divided by 8): chunks far from the origin fit into
the finite LCE / Pocket Edition worlds, or a build can be brought next to spawn.  Chunks move by
whole chunks, with their entities, block entities and scheduled ticks; the spawn and the players
standing in the moved chunks move with them, the others go to the new spawn.  Works on every route:
the numeric one (LCE, old Java, Pocket Edition, the DFU hub) moves the hub chunks, the Amulet one
(modern Java and Bedrock) the universal chunks while they are read.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np

from . import nbt
from .model import NETHER, OVERWORLD, Progress, WorldInfo, dimension_of
from .i18n import tr

Chunk = Tuple[int, int]


def _floordiv(a: int, b: int) -> int:
    return a // b


class Relocation:
    def __init__(self, sel):
        self.sel = sel
        self.dest: Optional[Tuple[int, int]] = getattr(sel, "move_to", None)
        self.moves: Dict[int, Chunk] = {}
        self.top: Optional[int] = None              # ground height at the destination (new spawn)
        if self.dest is None or not sel.chunks:
            return
        bx, bz = (int(v) for v in self.dest)
        for dim, cs in sel.chunks.items():
            if not cs:
                continue
            xs = [c[0] for c in cs]
            zs = [c[1] for c in cs]
            ccx, ccz = (min(xs) + max(xs)) >> 1, (min(zs) + max(zs)) >> 1
            scale = 8 if dim == NETHER else 1
            tx, tz = _floordiv(bx, scale) >> 4, _floordiv(bz, scale) >> 4
            self.moves[dim] = (tx - ccx, tz - ccz)

    @property
    def active(self) -> bool:
        return any(self.moves.values())

    def delta(self, dim: int) -> Chunk:
        return self.moves.get(dim, (0, 0))

    def coords(self, dim: int, coords: Iterable[Chunk]) -> List[Chunk]:
        dx, dz = self.delta(dim)
        return [(cx + dx, cz + dz) for cx, cz in coords]

    def describe(self) -> str:
        bx, bz = self.dest or (0, 0)
        dx, dz = self.delta(OVERWORLD)
        return tr("Selected chunks moved: their centre goes to x {x}, z {z} ({dx}, {dz} blocks).", x=bx, z=bz,
                  dx=f"{dx * 16:+d}", dz=f"{dz * 16:+d}")

    # ------------------------------------------------------------------ numeric chunks
    def numeric_chunk(self, dim: int, c) -> None:
        """Moves a hub chunk (NumericChunk) with everything that has a position in it."""
        dx, dz = self.delta(dim)
        if not (dx or dz):
            return
        c.cx += dx
        c.cz += dz
        bx, bz = dx * 16, dz * 16
        c.entities = [shift_entity(e, bx, bz) for e in c.entities]
        for t in list(c.tile_entities) + list(getattr(c, "tile_ticks", []) or []):
            shift_xyz(t, bx, bz)
        if dim == OVERWORLD and self.dest is not None:
            x, z = self.dest
            if (x >> 4, z >> 4) == (c.cx, c.cz):
                col = c.blocks[:, z & 15, x & 15]
                solid = np.nonzero(col)[0]
                self.top = int(solid[-1]) + 1 if solid.size else None

    # ------------------------------------------------------------------ Amulet chunks
    def amulet_chunk(self, dim: int, chunk) -> None:
        """Moves an Amulet universal chunk (while it is read, before it is written elsewhere)."""
        dx, dz = self.delta(dim)
        if not (dx or dz):
            return
        chunk._cx += dx
        chunk._cz += dz
        bx, bz = dx * 16, dz * 16
        chunk.block_entities = [be.new_at_location(be.x + bx, be.y, be.z + bz)
                                for be in list(chunk.block_entities.values())]
        for e in chunk.entities:
            e.x, e.z = e.x + bx, e.z + bz
        if dim == OVERWORLD and self.dest is not None:
            x, z = self.dest
            if (x >> 4, z >> 4) == (chunk.cx, chunk.cz):
                self.top = _amulet_top(chunk, x & 15, z & 15)

    # ------------------------------------------------------------------ canonical block entities / entities
    def canon_chunk(self, dim: int, cx: int, cz: int, tl: list, el: list) -> Chunk:
        """Moves the canonical block entities and entities of a source chunk (see tiles / entities);
        returns where the chunk went."""
        dx, dz = self.delta(dim)
        if not (dx or dz):
            return cx, cz
        bx, bz = dx * 16, dz * 16
        for c in list(tl) + list(el):
            if not isinstance(c, dict):
                continue
            for key in ("pos", "tile"):
                p = c.get(key)
                if p is not None and len(p) == 3:
                    c[key] = type(p)((p[0] + bx, p[1], p[2] + bz)) if isinstance(p, (tuple, list)) else p
        return cx + dx, cz + dz

    # ------------------------------------------------------------------ spawn and players
    def _moved(self, dim: int, x: float, z: float) -> Optional[Tuple[float, float]]:
        """Where a point of a moved chunk goes (None: its chunk was not selected)."""
        cs = (self.sel.chunks or {}).get(dim) or set()
        if (int(x) >> 4, int(z) >> 4) not in cs:
            return None
        dx, dz = self.delta(dim)
        return x + dx * 16, z + dz * 16

    def spawn(self, info: WorldInfo) -> Tuple[int, int, int]:
        """The new spawn: moved with its chunk, or on the destination when its chunk stays behind."""
        from .java.oldcontent import level_spawn

        x, y, z = level_spawn(info.level)
        p = self._moved(OVERWORLD, x, z)
        if p is not None:
            return int(p[0]), int(y), int(p[1])
        bx, bz = self.dest or (0, 0)
        return int(bx), int(self.top if self.top is not None else y), int(bz)

    def apply_info(self, info: WorldInfo, progress: Optional[Progress] = None) -> None:
        if not self.active:
            return
        sx, sy, sz = self.spawn(info)
        lv = info.level
        lv["SpawnX"], lv["SpawnY"], lv["SpawnZ"] = nbt.IntTag(sx), nbt.IntTag(sy), nbt.IntTag(sz)
        if isinstance(nbt.get_tag(lv, "spawn"), nbt.CompoundTag):
            del lv["spawn"]                           # Java 1.21.9+: the plain keys are the spawn now
        sent = 0
        for p in info.players.values():
            pos = nbt.get_tag(p, "Pos")
            if pos is None or len(pos) != 3:
                continue
            x, y, z = (float(v.py_data) for v in pos)
            dim = dimension_of(p)
            new = self._moved(dim, x, z)
            if new is not None:
                p["Pos"] = nbt.pos_list(new[0], pos[1], new[1])
                continue
            old = nbt.get(p, "Dimension", 0)
            p["Dimension"] = nbt.StringTag("minecraft:overworld") if isinstance(old, str) else nbt.IntTag(0)
            p["Pos"] = nbt.ListTag([nbt.DoubleTag(sx + 0.5), nbt.DoubleTag(float(sy)), nbt.DoubleTag(sz + 0.5)], 6)
            sent += 1
        if progress:
            progress.log(self.describe() + " " + tr("Spawn: {x}, {y}, {z}.", x=sx, y=sy, z=sz))
            if sent:
                progress.log(tr("{n} players were outside the moved chunks: they start at the new spawn.", n=sent))

    def moved_selection(self):
        """The selection in the coordinates of the converted world."""
        import copy

        out = copy.copy(self.sel)
        if self.sel.chunks is not None:
            out.chunks = {d: set(self.coords(d, cs)) for d, cs in self.sel.chunks.items()}
        if self.sel.exclude:
            out.exclude = {d: set(self.coords(d, cs)) for d, cs in self.sel.exclude.items()}
        out.move_to = None
        return out


def shift_xyz(t, bx: int, bz: int) -> None:
    if not isinstance(t, nbt.CompoundTag):
        return
    for k, d in (("x", bx), ("z", bz)):
        v = nbt.get_tag(t, k)
        if isinstance(v, (nbt.IntTag, nbt.ShortTag, nbt.LongTag)):
            t[k] = type(v)(int(v.py_data) + d)


def shift_entity(e, bx: int, bz: int):
    """An entity (and the ones riding it) moved by whole blocks."""
    if not isinstance(e, nbt.CompoundTag):
        return e
    pos = nbt.get_tag(e, "Pos")
    if pos is not None and len(pos) == 3:
        e["Pos"] = nbt.pos_list(float(pos[0].py_data) + bx, pos[1], float(pos[2].py_data) + bz)
    for kx, kz in (("TileX", "TileZ"), ("xTile", "zTile"), ("HomePosX", "HomePosZ"), ("BoundX", "BoundZ")):
        if kx in e and kz in e:
            for k, d in ((kx, bx), (kz, bz)):
                v = e[k]
                e[k] = type(v)(int(v.py_data) + d)
    leash = nbt.get_tag(e, "Leash")
    if isinstance(leash, nbt.CompoundTag):
        for k, d in (("X", bx), ("Z", bz)):
            if k in leash:
                leash[k] = nbt.IntTag(int(leash[k].py_data) + d)
    riders = nbt.get_tag(e, "Passengers")
    if isinstance(riders, nbt.ListTag):
        for r in riders:
            shift_entity(r, bx, bz)
    rider = nbt.get_tag(e, "Riding")
    if isinstance(rider, nbt.CompoundTag):
        shift_entity(rider, bx, bz)
    return e


def _amulet_top(chunk, x: int, z: int) -> Optional[int]:
    air = {"air", "cave_air", "void_air"}
    pal = chunk.block_palette
    for cy in sorted(chunk.blocks.sub_chunks, reverse=True):
        col = chunk.blocks.get_sub_chunk(cy)[x, :, z]
        for yy in range(15, -1, -1):
            if getattr(pal[int(col[yy])], "base_name", "air") not in air:
                return cy * 16 + yy + 1
    return None
