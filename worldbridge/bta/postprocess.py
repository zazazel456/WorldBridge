"""Second pass: the properties vanilla derives from neighbouring blocks, reproducing the vanilla 26.3
rules (StairBlock.getStairsShape, FenceBlock / IronBarsBlock connections,
RedstoneWireBlock.getConnectionState, LeavesBlock distance, SnowyDirtBlock, NoteBlock instrument,
chest pairing) with the exported vanilla state facts.  Neighbour chunks are read-only; only the
centre chunk is modified, and every read sees pre-processing data (results do not depend on order).
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np

from .. import nbt
from . import stats
from .chunks import Stage1, _Lut, index
from .states import AIR, BlockState, by_id, conductor, full_cube, in_tag, instrument, signal_source, state, sturdy
from .states import DOWN, EAST, NORTH, SOUTH, UP, WEST

H = ((0, -1), (0, 1), (-1, 0), (1, 0))  # north, south, west, east
H_NAMES = ("north", "south", "west", "east")
H_OPP = (SOUTH, NORTH, EAST, WEST)


def _is_bars(s: BlockState) -> bool:
    n = s.name
    return n == "minecraft:iron_bars" or n.endswith("_glass_pane") or n == "minecraft:glass_pane" or n.endswith("_bars")


def _interesting(s: BlockState) -> bool:
    n = s.name
    return ((s.has("snowy") and n in ("minecraft:grass_block", "minecraft:podzol", "minecraft:mycelium"))
            or in_tag(s, "stairs") or in_tag(s, "fences") or _is_bars(s)
            or n in ("minecraft:redstone_wire", "minecraft:note_block", "minecraft:cave_vines_plant", "minecraft:chest",
                     "minecraft:pointed_dripstone"))


INTERESTING = _Lut(_interesting)
LEAVES = _Lut(lambda s: s.has("distance") and in_tag(s, "leaves"))
LEAF_SOURCE = _Lut(lambda s: not s.is_air and in_tag(s, "prevents_nearby_leaf_decay"))


def _step(d: str):
    return {"north": (0, -1), "south": (0, 1), "west": (-1, 0)}.get(d, (1, 0))


def _same_axis(a: str, b: str) -> bool:
    return (a in ("east", "west")) == (b in ("east", "west"))


def _ccw(d: str) -> str:
    return {"north": "west", "west": "south", "south": "east"}.get(d, "north")


def _cw(d: str) -> str:
    return {"north": "east", "east": "south", "south": "west"}.get(d, "north")


def _opp(d: str) -> str:
    return {"north": "south", "south": "north", "east": "west"}.get(d, "east")


def _is_exception(s: BlockState) -> bool:
    n = s.name
    return (in_tag(s, "leaves") or n in ("minecraft:barrier", "minecraft:carved_pumpkin", "minecraft:jack_o_lantern",
                                         "minecraft:melon", "minecraft:pumpkin") or in_tag(s, "shulker_boxes"))


class PostProcessor:
    def __init__(self, center: Stage1, out: Stage1, neighbours: Callable[[int, int], Optional[Stage1]]):
        self.center = center
        self.out = out
        self.base_x = center.cx << 4
        self.base_z = center.cz << 4
        self._chunks = {}
        # 3x3 neighbourhood of original states, [y, z + 16, x + 16] (missing chunks read as air)
        grid = np.zeros((256, 48, 48), np.uint32)
        for dz in (-1, 0, 1):
            for dx in (-1, 0, 1):
                ch = center if dx == 0 and dz == 0 else neighbours(center.cx + dx, center.cz + dz)
                self._chunks[(center.cx + dx, center.cz + dz)] = ch
                if ch is not None:
                    grid[:, (dz + 1) * 16:(dz + 2) * 16, (dx + 1) * 16:(dx + 2) * 16] = ch.states
        self.grid = grid

    def chunk(self, cx: int, cz: int) -> Optional[Stage1]:
        return self._chunks.get((cx, cz))

    def get(self, x: int, y: int, z: int) -> BlockState:
        if y < 0 or y > 255:
            return AIR
        lx, lz = x - self.base_x + 16, z - self.base_z + 16
        if not (0 <= lx < 48 and 0 <= lz < 48):
            return AIR
        return by_id(int(self.grid[y, lz, lx]))

    def run(self) -> None:
        self._leaf_distances()
        states = self.center.states
        mask = INTERESTING.get()[states]
        out = self.out.states
        for y, lz, lx in zip(*np.nonzero(mask)):
            y, lz, lx = int(y), int(lz), int(lx)
            s = by_id(int(states[y, lz, lx]))
            n = self._fix(s, self.base_x + lx, y, self.base_z + lz)
            if n is not s:
                out[y, lz, lx] = n.id
        self._legacy_chests()

    def _fix(self, s: BlockState, x: int, y: int, z: int) -> BlockState:
        name = s.name
        if s.has("snowy") and name in ("minecraft:grass_block", "minecraft:podzol", "minecraft:mycelium"):
            return s.with_("snowy", "true" if in_tag(self.get(x, y + 1, z), "snow") else "false")
        if in_tag(s, "stairs"):
            return s.with_("shape", self._stairs_shape(s, x, y, z))
        if in_tag(s, "fences"):
            return self._fence(s, x, y, z)
        if _is_bars(s):
            return self._bars(s, x, y, z)
        if name == "minecraft:redstone_wire":
            return self._wire(s, x, y, z)
        if name == "minecraft:note_block":
            return s.with_("instrument", self._instrument(x, y, z))
        if name == "minecraft:cave_vines_plant":
            below = self.get(x, y - 1, z)
            if not below.is_("minecraft:cave_vines_plant") and not below.is_("minecraft:cave_vines"):
                return state("cave_vines", age="25", berries="false")
            return s
        if name == "minecraft:chest":
            return self._chest(s, x, y, z)
        if name == "minecraft:pointed_dripstone":
            return self._dripstone(s, x, y, z)
        return s

    # -------------------------------------------------------------- stairs
    def _stairs_shape(self, s: BlockState, x: int, y: int, z: int) -> str:
        facing, half = s.get("facing"), s.get("half")
        fx, fz = _step(facing)
        behind = self.get(x + fx, y, z + fz)
        if in_tag(behind, "stairs") and half == behind.get("half"):
            bf = behind.get("facing")
            if not _same_axis(bf, facing) and self._can_take_shape(s, x, y, z, _opp(bf)):
                return "outer_left" if bf == _ccw(facing) else "outer_right"
        front = self.get(x - fx, y, z - fz)
        if in_tag(front, "stairs") and half == front.get("half"):
            ff = front.get("facing")
            if not _same_axis(ff, facing) and self._can_take_shape(s, x, y, z, ff):
                return "inner_left" if ff == _ccw(facing) else "inner_right"
        return "straight"

    def _can_take_shape(self, s: BlockState, x: int, y: int, z: int, d: str) -> bool:
        dx, dz = _step(d)
        n = self.get(x + dx, y, z + dz)
        return not in_tag(n, "stairs") or s.get("facing") != n.get("facing") or s.get("half") != n.get("half")

    # -------------------------------------------------------------- fences / bars
    def _fence(self, s: BlockState, x: int, y: int, z: int) -> BlockState:
        wooden = in_tag(s, "wooden_fences")
        for i in range(4):
            n = self.get(x + H[i][0], y, z + H[i][1])
            face_solid = sturdy(n, H_OPP[i])
            same_fence = in_tag(n, "fences") and in_tag(n, "wooden_fences") == wooden
            gate = in_tag(n, "fence_gates") and _same_axis(n.get("facing"), _cw(H_NAMES[i]))
            connect = (not _is_exception(n) and face_solid) or same_fence or gate
            s = s.with_(H_NAMES[i], "true" if connect else "false")
        return s

    def _bars(self, s: BlockState, x: int, y: int, z: int) -> BlockState:
        for i in range(4):
            n = self.get(x + H[i][0], y, z + H[i][1])
            face_solid = sturdy(n, H_OPP[i])
            attach = (not _is_exception(n) and face_solid) or _is_bars(n) or in_tag(n, "walls")
            s = s.with_(H_NAMES[i], "true" if attach else "false")
        return s

    # -------------------------------------------------------------- redstone wire
    @staticmethod
    def _wire_connects_to(n: BlockState, direction: Optional[str]) -> bool:
        name = n.name
        if name == "minecraft:redstone_wire":
            return True
        if name in ("minecraft:repeater", "minecraft:comparator"):
            if direction is None:
                return False
            if name == "minecraft:comparator":
                return signal_source(n)
            return _same_axis(n.get("facing"), direction)
        if name == "minecraft:observer":
            return direction is not None and n.get("facing") == direction
        return signal_source(n) and direction is not None

    def _wire(self, s: BlockState, x: int, y: int, z: int) -> BlockState:
        above = self.get(x, y + 1, z)
        can_up = not conductor(above)
        side = [""] * 4
        connected = [False] * 4
        for i in range(4):
            nx, nz = x + H[i][0], z + H[i][1]
            rel = self.get(nx, y, nz)
            result = None
            if can_up:
                placeable = in_tag(rel, "trapdoors") or sturdy(rel, UP) or rel.is_("minecraft:hopper")
                if placeable and self._wire_connects_to(self.get(nx, y + 1, nz), None):
                    result = "up" if sturdy(rel, H_OPP[i]) else "side"
            if result is None:
                none = (not self._wire_connects_to(rel, H_NAMES[i])
                        and (conductor(rel) or not self._wire_connects_to(self.get(nx, y - 1, nz), None)))
                result = "none" if none else "side"
            side[i] = result
            connected[i] = result != "none"
        n, so, w, e = connected
        ns_empty = not n and not so
        ew_empty = not e and not w
        if not w and ns_empty:
            side[2] = "side"
        if not e and ns_empty:
            side[3] = "side"
        if not n and ew_empty:
            side[0] = "side"
        if not so and ew_empty:
            side[1] = "side"
        for i in range(4):
            s = s.with_(H_NAMES[i], side[i])
        return s

    # -------------------------------------------------------------- note blocks
    def _instrument(self, x: int, y: int, z: int) -> str:
        heads = ("skeleton", "zombie", "creeper", "dragon", "wither_skeleton", "piglin", "custom_head")
        above = instrument(self.get(x, y + 1, z))
        if above in heads:
            return above
        below = instrument(self.get(x, y - 1, z))
        return "harp" if below in heads else below

    # -------------------------------------------------------------- chests
    def _chest(self, s: BlockState, x: int, y: int, z: int) -> BlockState:
        """Double chests: the partner must be a chest facing the same way with the opposite type."""
        t = s.get("type")
        if t == "single":
            return s
        facing = s.get("facing")
        dx, dz = _step(_cw(facing) if t == "left" else _ccw(facing))
        other = self.get(x + dx, y, z + dz)
        want = "right" if t == "left" else "left"
        if other.is_("minecraft:chest") and facing == other.get("facing") and want == other.get("type"):
            return s
        stats.inc("chest.unpaired_fixed")
        return s.with_("type", "single")

    # -------------------------------------------------------------- spikes
    def _dripstone(self, s: BlockState, x: int, y: int, z: int) -> BlockState:
        up = s.get("vertical_direction") == "up"
        support = self.get(x, y + (-1 if up else 1), z)
        ok = sturdy(support, UP if up else DOWN) or support.is_("minecraft:pointed_dripstone")
        return s if ok else state("iron_bars")

    # -------------------------------------------------------------- leaves
    def _leaf_distances(self) -> None:
        """LeavesBlock distance: BFS from #prevents_nearby_leaf_decay through leaves, max 7."""
        leaves_lut = LEAVES.get()
        center_leaves = leaves_lut[self.out.states]
        if not center_leaves.any():
            return
        area = self.grid[:, 10:38, 10:38]            # the centre chunk +- 6 blocks
        src = LEAF_SOURCE.get()[area]
        leafy = LEAVES.get()[area]
        dist = np.full(area.shape, 7, np.int8)
        dist[src] = 0
        frontier = src
        for d in range(1, 7):
            nb = np.zeros_like(frontier)
            nb[1:] |= frontier[:-1]
            nb[:-1] |= frontier[1:]
            nb[:, 1:] |= frontier[:, :-1]
            nb[:, :-1] |= frontier[:, 1:]
            nb[:, :, 1:] |= frontier[:, :, :-1]
            nb[:, :, :-1] |= frontier[:, :, 1:]
            new = nb & leafy & (dist > d)
            if not new.any():
                break
            dist[new] = d
            frontier = new
        d_center = dist[:, 6:22, 6:22]
        out = self.out.states
        ys, zs, xs = np.nonzero(center_leaves)
        combos = {}
        for sid, dd in zip(out[ys, zs, xs].tolist(), d_center[ys, zs, xs].tolist()):
            key = (sid, dd)
            if key not in combos:
                b = by_id(sid)
                n = b.with_("distance", str(max(1, dd)))
                if dd >= 7 and n.get("persistent") == "false":
                    # would decay in vanilla (BTA only decays leaves after a log is broken): keep them
                    n = n.with_("persistent", "true")
                combos[key] = n.id
        new_ids = np.fromiter((combos[(sid, dd)] for sid, dd in zip(out[ys, zs, xs].tolist(),
                                                                       d_center[ys, zs, xs].tolist())), np.uint32, len(ys))
        persistent_made = sum(1 for sid, dd in zip(out[ys, zs, xs].tolist(), d_center[ys, zs, xs].tolist())
                              if dd >= 7 and by_id(sid).get("persistent") == "false")
        if persistent_made:
            stats.add("leaves.made_persistent", persistent_made)
        out[ys, zs, xs] = new_ids

    # -------------------------------------------------------------- BTA legacy chests
    def _legacy_at(self, x: int, y: int, z: int) -> bool:
        s = self.chunk(x >> 4, z >> 4)
        return s is not None and index(x & 15, y, z & 15) in s.legacy_chests

    def _opaque(self, x: int, y: int, z: int) -> bool:
        b = self.get(x, y, z)
        return not b.is_air and full_cube(b) and sturdy(b, UP)

    def _legacy_chests(self) -> None:
        """BlockLogicChestLegacy.updateLegacyChest."""
        for idx in self.center.legacy_chests:
            lx, lz, y = idx & 15, (idx >> 4) & 15, idx >> 8
            x, z = self.base_x + lx, self.base_z + lz
            other = None
            if self._legacy_at(x + 1, y, z):
                other = "east"
            if self._legacy_at(x - 1, y, z):
                other = "west"
            if self._legacy_at(x, y, z + 1):
                other = "south"
            if self._legacy_at(x, y, z - 1):
                other = "north"
            facing = "south"
            bta_type = "single"
            op = self._opaque
            if other is None:
                if op(x + 1, y, z) and not op(x - 1, y, z):
                    facing = "west"
                if op(x - 1, y, z) and not op(x + 1, y, z):
                    facing = "east"
                if op(x, y, z + 1) and not op(x, y, z - 1):
                    facing = "north"
                if op(x, y, z - 1) and not op(x, y, z + 1):
                    facing = "south"
            else:
                if other == "north":
                    facing = "west" if op(x + 1, y, z) or op(x + 1, y, z - 1) else "east"
                elif other == "south":
                    facing = "west" if op(x + 1, y, z) or op(x + 1, y, z + 1) else "east"
                elif other == "east":
                    facing = "north" if op(x, y, z + 1) or op(x + 1, y, z + 1) else "south"
                else:
                    facing = "north" if op(x, y, z + 1) or op(x - 1, y, z + 1) else "south"
                key = facing + ">" + other
                if key in ("north>east", "east>south", "south>west", "west>north"):
                    bta_type = "right"
                elif key in ("north>west", "east>north", "south>east", "west>south"):
                    bta_type = "left"
                # BTA swaps the two inventories for chests facing north or east
                if facing in ("north", "east"):
                    self._swap_with_partner(idx, x, y, z, other)
            # BTA LEFT = vanilla RIGHT
            t = {"left": "right", "right": "left"}.get(bta_type, "single")
            self.out.states[y, lz, lx] = state("chest", facing=facing, type=t).id
            stats.inc("chest.legacy_converted")

    def _swap_with_partner(self, idx: int, x: int, y: int, z: int, other: str) -> None:
        dx, dz = _step(other)
        ox, oz = x + dx, z + dz
        os_ = self.chunk(ox >> 4, oz >> 4)
        if os_ is None:
            return
        partner = os_.block_entities.get(index(ox & 15, y, oz & 15))
        mine = self.out.block_entities.get(idx)
        if partner is None or mine is None:
            return
        # each chunk only writes its own block entity: take the partner's (already converted) items
        items = nbt.get_tag(partner, "Items")
        mine["Items"] = nbt.copy(items) if items is not None else nbt.ListTag([], 10)
