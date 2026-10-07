"""Raw Bedrock LevelDB access for block entities, entities and players.

Amulet translates blocks; this module writes the rest natively:

* chunk key  = <i32 x><i32 z>[<i32 dim>]<u8 tag>   (dim omitted for the Overworld)
* tag 0x31   block entities   (concatenated little endian NBT)
* tag 0x32   entities         (before 1.18.30)
* 'digp'+key / 'actorprefix'+id   entities from 1.18.30
* '~local_player'                 the single player
"""

from __future__ import annotations

import os
import struct
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .. import entities as ent
from .. import items, nbt, tiles
from ..model import NETHER, OVERWORLD, THE_END, Progress, WorldInfo
from ..i18n import tr

BE_TAG = 0x31
ENTITY_TAG = 0x32
DIM_TO_BEDROCK = {OVERWORLD: 0, NETHER: 1, THE_END: 2}
DIM_FROM_BEDROCK = {v: k for k, v in DIM_TO_BEDROCK.items()}


def _db(path: str, create: bool = False):
    from leveldb import LevelDB

    return LevelDB(os.path.join(path, "db"), create)


def _get(db, key: bytes) -> Optional[bytes]:
    try:
        return db.get(key)
    except KeyError:
        return None


def chunk_prefix(cx: int, cz: int, dim: int) -> bytes:
    bd = DIM_TO_BEDROCK[dim]
    return struct.pack("<ii", cx, cz) if bd == 0 else struct.pack("<iii", cx, cz, bd)


def read_nbt_list(data: bytes) -> List[nbt.CompoundTag]:
    out = []
    off = 0
    n = len(data)
    while off < n:
        try:
            tag, off2 = nbt.load_with_offset(data, off, little_endian=True, escape=True)
        except Exception:  # noqa: BLE001
            break
        if off2 <= off:
            break
        off = off2
        if isinstance(tag.tag, nbt.CompoundTag):
            out.append(tag.tag)
    return out


def write_nbt_list(tags: List[nbt.CompoundTag]) -> bytes:
    return b"".join(nbt.dump(t, "", little_endian=True) for t in tags)


# ------------------------------------------------------------------ players

# Java 1.15.2.  A Bedrock player becomes a Java player of this version: its items keep their
# names (netherite, copper, tridents... have no numeric id), and the level.dat of a world from
# Bedrock carries this DataVersion too, so Minecraft upgrades the player from here.  From an
# older version the game's 1.13 - 1.14 renames would hit modern names (stone_slab ->
# smooth_stone_slab, melon -> melon_slice, purple_shulker_box -> shulker_box).
BEDROCK_PLAYER_DV = 2230


def _player_items(p: nbt.CompoundTag, write, offhand: bool = False):
    """(inventory, ender chest) of a Bedrock player, each stack written by ``write``."""
    inv = nbt.ListTag([], 10)

    def add(lst, it, slot=None):
        c = items.from_bedrock(it)
        if not c:
            return
        if slot is not None:
            c["slot"] = slot
        w = write(c)
        if w is not None:
            lst.append(w)

    for it in nbt.get_tag(p, "Inventory") or []:
        add(inv, it)
    for i, it in enumerate(nbt.get_tag(p, "Armor") or []):
        add(inv, it, 100 + (3 - i))
    if offhand:
        for it in (nbt.get_tag(p, "Offhand") or [])[:1]:
            add(inv, it, -106)
    ender = nbt.ListTag([], 10)
    for it in nbt.get_tag(p, "EnderChestInventory") or []:
        add(ender, it)
    return inv, ender


def bedrock_player_to_legacy(p: nbt.CompoundTag) -> nbt.CompoundTag:
    out = nbt.CompoundTag()
    pos = [float(v.py_data) for v in (nbt.get_tag(p, "Pos") or [])] or [0.0, 64.0, 0.0]
    out["Pos"] = nbt.ListTag([nbt.DoubleTag(pos[0]), nbt.DoubleTag(pos[1] - 1.62), nbt.DoubleTag(pos[2])], 6)
    rot = [float(v.py_data) for v in (nbt.get_tag(p, "Rotation") or [])] or [0.0, 0.0]
    out["Rotation"] = nbt.ListTag([nbt.FloatTag(rot[0]), nbt.FloatTag(rot[1])], 5)
    out["Motion"] = nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(0), nbt.DoubleTag(0)], 6)
    out["Dimension"] = nbt.IntTag(DIM_FROM_BEDROCK.get(int(nbt.get(p, "DimensionId", 0) or 0), 0))
    if nbt.get(p, "UniqueID") is not None:  # the same UUID as the owner of its tamed animals
        v = ent.bedrock_uuid(int(nbt.get(p, "UniqueID")))
        out["UUIDMost"] = nbt.LongTag(ent._signed(v >> 64, 64))
        out["UUIDLeast"] = nbt.LongTag(ent._signed(v, 64))
    gm = nbt.get(p, "PlayerGameMode")
    # Bedrock: 5 = the world's mode (Java: no playerGameType, the same), 6 = Spectator (Java 3)
    mode = {0: 0, 1: 1, 2: 2, 6: 3}.get(int(gm)) if gm is not None else None
    if mode is not None:
        out["playerGameType"] = nbt.IntTag(mode)
    out["Inventory"], out["EnderItems"] = _player_items(p, items.to_legacy)
    for a in nbt.get_tag(p, "Attributes") or []:
        name = nbt.get(a, "Name")
        if name == "minecraft:health":
            out["Health"] = nbt.FloatTag(float(nbt.get(a, "Current", 20.0)))
        elif name == "minecraft:player.hunger":
            out["foodLevel"] = nbt.IntTag(int(float(nbt.get(a, "Current", 20.0))))
        elif name == "minecraft:player.level":
            out["XpLevel"] = nbt.IntTag(int(float(nbt.get(a, "Current", 0.0))))
    return out


def bedrock_player_to_java(p: nbt.CompoundTag) -> nbt.CompoundTag:
    """A Bedrock player as a Java 1.15.2 player (see BEDROCK_PLAYER_DV): every item, the off
    hand included, by name.  The targets without these items translate it like any Java player."""
    out = bedrock_player_to_legacy(p)
    out["DataVersion"] = nbt.IntTag(BEDROCK_PLAYER_DV)
    out["Inventory"], out["EnderItems"] = _player_items(
        p, lambda c: items.to_java_modern(c, BEDROCK_PLAYER_DV), offhand=True)
    return out


# what Bedrock writes for a new player: without them the game keeps the generic mob values
# (movement 0.7 = seven times the player speed)
_PLAYER_ATTRIBUTES = (("minecraft:follow_range", 16.0, 2048.0), ("minecraft:knockback_resistance", 0.0, 1.0),
                      ("minecraft:movement", 0.1, 3.4028234663852886e38),
                      ("minecraft:underwater_movement", 0.02, 3.4028234663852886e38),
                      ("minecraft:lava_movement", 0.02, 3.4028234663852886e38),
                      ("minecraft:attack_damage", 1.0, 1.0), ("minecraft:absorption", 0.0, 16.0),
                      ("minecraft:luck", 0.0, 1024.0))
# the world's owner: operator, every ability (a single player world has no other player)
HOST_ABILITIES = {"attackmobs": 1, "attackplayers": 1, "build": 1, "doorsandswitches": 1, "flying": 0,
                  "instabuild": 0, "invulnerable": 0, "lightning": 0, "mayfly": 0, "mine": 1, "op": 1,
                  "opencontainers": 1, "teleport": 1}


def abilities_tag(values: dict) -> nbt.CompoundTag:
    t = nbt.CompoundTag({k: nbt.ByteTag(v) for k, v in values.items()})
    t["flySpeed"] = nbt.FloatTag(0.05)
    t["walkSpeed"] = nbt.FloatTag(0.1)
    t["verticalFlySpeed"] = nbt.FloatTag(1.0)
    return t


def legacy_player_to_bedrock(p: nbt.CompoundTag, version, uid: int, world_game_type: Optional[int] = None) -> nbt.CompoundTag:
    """world_game_type: the world's game mode; a player in that same mode follows the world
    setting (Bedrock "default" personal mode), so changing the world's mode changes the player's."""
    out = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:player")})
    pos = [float(v.py_data) for v in (nbt.get_tag(p, "Pos") or [])] or [0.0, 64.0, 0.0]
    out["Pos"] = nbt.ListTag([nbt.FloatTag(pos[0]), nbt.FloatTag(pos[1] + 1.62), nbt.FloatTag(pos[2])], 5)
    rot = [float(v.py_data) for v in (nbt.get_tag(p, "Rotation") or [])] or [0.0, 0.0]
    out["Rotation"] = nbt.ListTag([nbt.FloatTag(rot[0]), nbt.FloatTag(rot[1])], 5)
    out["Motion"] = nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(0), nbt.FloatTag(0)], 5)
    dim = nbt.get(p, "Dimension", 0)
    if isinstance(dim, str):
        dim = {"minecraft:the_nether": -1, "minecraft:the_end": 1}.get(dim, 0)
    out["DimensionId"] = nbt.IntTag(DIM_TO_BEDROCK.get(int(dim or 0), 0))
    out["UniqueID"] = nbt.LongTag(uid)
    lst = list(items.player_stacks(p))  # Java 1.21.5+: armour and off hand from "equipment"
    ender_lst = list(nbt.get_tag(p, "EnderItems") or [])
    src = "java" if int(nbt.get(p, "DataVersion", 0) or 0) >= 1451 else "legacy"  # Java 1.13+ items
    for t in lst + ender_lst:
        if isinstance(nbt.get(t, "id"), str) and items.flat_to_legacy(str(nbt.get(t, "id"))) is not None:
            src = "java"

    def slots(tags):
        for t in tags:
            c = items.from_legacy(t) if src == "legacy" else items.from_java_modern(t)
            if not c:
                continue
            slot = int(c.get("slot") or 0)
            c["slot"] = None
            b = items.to_bedrock(c, tuple(version))
            if b is not None:
                yield slot, b

    inv = [None] * 36
    armor = [None] * 4
    offhand = None
    for slot, b in slots(lst):
        if 0 <= slot < 36:
            b["Slot"] = nbt.ByteTag(slot)
            inv[slot] = b
        elif 100 <= slot <= 103:
            armor[3 - (slot - 100)] = b
        elif slot == -106:
            offhand = b
    ender = [None] * 27
    for slot, b in slots(ender_lst):
        if 0 <= slot < 27:
            b["Slot"] = nbt.ByteTag(slot)
            ender[slot] = b
    empty = lambda s=None: nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0),  # noqa: E731
                                            "WasPickedUp": nbt.ByteTag(0), **({"Slot": nbt.ByteTag(s)} if s is not None else {})})
    out["Inventory"] = nbt.ListTag([inv[i] if inv[i] is not None else empty(i) for i in range(36)], 10)
    out["Armor"] = nbt.ListTag([a if a is not None else empty() for a in armor], 10)
    out["Offhand"] = nbt.ListTag([offhand if offhand is not None else empty()], 10)
    out["EnderChestInventory"] = nbt.ListTag([ender[i] if ender[i] is not None else empty(i) for i in range(27)], 10)
    gt = nbt.get(p, "playerGameType")
    gt = int(gt) if gt is not None and int(gt) in (0, 1, 2, 3) else None
    # Spectator is 6 from Bedrock 1.21.40; before, the nearest is Creative
    spectator = 6 if tuple(version) >= (1, 21, 40) else 1
    mode = {3: spectator}.get(gt, gt)
    if gt is None or (world_game_type is not None and mode == {3: spectator}.get(world_game_type, world_game_type)):
        out["PlayerGameMode"] = nbt.IntTag(5)  # "default": follows the world
    else:
        out["PlayerGameMode"] = nbt.IntTag(mode)
    out["playerPermissionsLevel"] = nbt.IntTag(2)  # operator
    out["permissionsLevel"] = nbt.IntTag(1)
    ab = dict(HOST_ABILITIES)
    if mode == 1:
        ab.update(instabuild=1, mayfly=1)
    out["abilities"] = abilities_tag(ab)

    def attr(name, current, maximum, base=None):
        return nbt.CompoundTag({"Name": nbt.StringTag(name), "Base": nbt.FloatTag(maximum if base is None else base),
                                "Current": nbt.FloatTag(current), "Max": nbt.FloatTag(maximum),
                                "DefaultMax": nbt.FloatTag(maximum), "DefaultMin": nbt.FloatTag(0), "Min": nbt.FloatTag(0)})

    attrs = [attr(name, v, mx, v) for name, v, mx in _PLAYER_ATTRIBUTES]
    h = nbt.get(p, "Health")
    if h is not None:
        attrs.insert(0, attr("minecraft:health", max(0.0, min(float(h), 20.0)), 20.0))
    food = nbt.get(p, "foodLevel")
    if food is not None:
        attrs.append(attr("minecraft:player.hunger", max(0, min(int(food), 20)), 20.0))
        attrs.append(attr("minecraft:player.saturation", max(0.0, min(float(nbt.get(p, "foodSaturationLevel", 5.0) or 0), 20.0)),
                          20.0, 5.0))
    lvl = nbt.get(p, "XpLevel")
    if lvl is not None:
        attrs.append(attr("minecraft:player.level", max(0, min(int(lvl), 24791)), 24791.0, 0.0))
        attrs.append(attr("minecraft:player.experience", max(0.0, min(float(nbt.get(p, "XpP", 0.0) or 0), 1.0)), 1.0, 0.0))
    if attrs:
        out["Attributes"] = nbt.ListTag(attrs, 10)
    return out


def read_bedrock_players(path: str) -> Dict[str, nbt.CompoundTag]:
    db = _db(path)
    try:
        out = {}
        raw = _get(db, b"~local_player")
        if raw:
            out["host"] = bedrock_player_to_java(nbt.load(raw, little_endian=True, compressed=False).tag)
        for key, raw in db.iterate(b"player_server_", b"player_server_\xff"):
            if not key.startswith(b"player_server_") or len(out) >= 64:
                continue
            try:
                out[key.decode("utf-8", "replace")] = bedrock_player_to_java(
                    nbt.load(raw, little_endian=True, compressed=False).tag)
            except Exception:  # noqa: BLE001
                pass
        return out
    except Exception:  # noqa: BLE001
        return {}
    finally:
        db.close()


# ------------------------------------------------------------------ source side


def frame_canon(db, prefix: bytes, t: nbt.CompoundTag) -> Optional[dict]:
    """A Bedrock item frame (block + block entity) as a canonical item frame entity."""
    from . import terrain

    x, y, z = int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))
    raw = _get(db, prefix + bytes([terrain.SUBCHUNK]) + struct.pack("b", y >> 4)) if -128 <= y >> 4 < 128 else None
    sc = terrain.SubChunk.decode(raw) if raw else None
    f3 = 3
    if sc is not None and sc.storages:
        st = sc.storages[0]
        entry = st.palette[int(st.idx[(x & 15) << 8 | (z & 15) << 4 | (y & 15)])]
        try:
            f3 = int(entry["states"]["facing_direction"].py_int)
        except Exception:  # noqa: BLE001
            pass
    off = {0: (0, -1, 0), 1: (0, 1, 0), 2: (0, 0, -1), 3: (0, 0, 1), 4: (-1, 0, 0), 5: (1, 0, 0)}.get(f3, (0, 0, 1))
    c = {"name": "glow_item_frame" if str(nbt.get(t, "id")) == "GlowItemFrame" else "item_frame",
         "pos": (x + 0.5 - off[0] * 0.46875, y + 0.5 - off[1] * 0.46875, z + 0.5 - off[2] * 0.46875),
         "motion": (0.0, 0.0, 0.0), "rot": ({2: 180.0, 3: 0.0, 4: 90.0, 5: 270.0}.get(f3, 0.0), 0.0),
         "tile": (x, y, z), "facing": f3, "facing3d": True, "extra": {},
         "item_rot": int(round(float(nbt.get(t, "ItemRotation", 0.0) or 0.0) / 45.0)) % 8}
    if "Item" in t:
        c["item"] = items.from_bedrock(t["Item"])
    return c


def is_frame_tile(t) -> bool:
    return str(nbt.get(t, "id", "")) in ("ItemFrame", "GlowItemFrame")


class BedrockExtras:
    """Block entities / entities of a Bedrock world, converted to the legacy hub format on demand."""

    def __init__(self, path: str, progress: Progress):
        self.path = path
        self.progress = progress
        self.db = _db(path)
        self.errors = 0

    def _actors(self, prefix: bytes) -> List[nbt.CompoundTag]:
        out = []
        raw = _get(self.db, prefix + bytes([ENTITY_TAG]))
        if raw:
            out.extend(read_nbt_list(raw))
        digp = _get(self.db, b"digp" + prefix)
        if digp:
            for i in range(0, len(digp) // 8 * 8, 8):
                a = _get(self.db, b"actorprefix" + digp[i : i + 8])
                if a:
                    out.extend(read_nbt_list(a))
        return out

    def chunk_extras(self, dim: int, cx: int, cz: int):
        """At their height in the source world: extra._wrap_reader moves them with the blocks (depthfit)
        and drops those that end out of 0 - 255."""
        prefix = chunk_prefix(cx, cz, dim)
        try:
            raw = _get(self.db, prefix + bytes([BE_TAG]))
            tl = []
            frames = []
            if raw:
                raw_tiles = read_nbt_list(raw)
                canon = [c for c in (tiles.from_bedrock(t) for t in raw_tiles) if c is not None]
                tl = tiles.write_list(canon, "legacy")
                frames = [t for t in raw_tiles if is_frame_tile(t)]
            el = [e for e in (self._frame(prefix, t) for t in frames) if e is not None]
            for e in self._actors(prefix):
                c = ent.from_bedrock(e)
                if c is not None:
                    le = ent.to_legacy(c)
                    if le is not None:
                        el.append(le)
            return el, tl
        except Exception:  # noqa: BLE001
            self.errors += 1
            return None, None

    def _frame(self, prefix: bytes, t: nbt.CompoundTag) -> Optional[nbt.CompoundTag]:
        c = frame_canon(self.db, prefix, t)
        return ent.to_legacy(c) if c is not None else None

    def close(self):
        try:
            self.db.close()
        except Exception:  # noqa: BLE001
            pass


# ------------------------------------------------------------------ target side


class BedrockInjector:
    def __init__(self, out_dir: str, version, progress: Progress):
        self.db = _db(out_dir)
        self.version = tuple(version)
        self.progress = progress
        self.ids = ent.ActorIds()
        _key, self.player_uid = self.ids.next()  # tamed animals belong to the world's player
        self.modern_actors = self.version >= (1, 18, 30)
        self.n_tiles = 0
        self.n_ents = 0
        self.n_frames = 0
        self.n_maps = 0

    def put_chunk(self, dim: int, cx: int, cz: int, tile_canon: List[dict], ent_canon: List[dict]):
        prefix = chunk_prefix(cx, cz, dim)
        if tile_canon:
            key = prefix + bytes([BE_TAG])
            existing = read_nbt_list(_get(self.db, key) or b"")
            by_pos = {(int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))): t for t in existing}
            for t in tiles.write_list(tile_canon, "bedrock", version=self.version):
                by_pos[(int(t["x"].py_data), int(t["y"].py_data), int(t["z"].py_data))] = t
                self.n_tiles += 1
            self.db.put(key, write_nbt_list(list(by_pos.values())))
        frames = [c for c in ent_canon or [] if c.get("name") in ("item_frame", "glow_item_frame") and not c.get("skip")]
        if frames:
            self._put_frames(dim, frames)
            ent_canon = [c for c in ent_canon if c not in frames]
        if ent_canon:
            actors = []
            keys = []
            for c in ent_canon:
                key, uid = self.ids.next()
                e = ent.to_bedrock(c, uid, self.player_uid, self.version)
                if e is None:
                    continue
                actors.append((key, e))
            if not actors:
                return
            self.n_ents += len(actors)
            if self.modern_actors:
                old = _get(self.db, b"digp" + prefix) or b""
                for key, e in actors:
                    ic = nbt.CompoundTag({"EntityStorageKeyComponent": nbt.CompoundTag(
                        {"StorageKey": nbt.escape_string(key)})})
                    e["internalComponents"] = ic
                    self.db.put(b"actorprefix" + key, nbt.dump(e, "", little_endian=True, escape=True))
                    keys.append(key)
                self.db.put(b"digp" + prefix, old + b"".join(keys))
            else:
                key = prefix + bytes([ENTITY_TAG])
                old = _get(self.db, key) or b""
                self.db.put(key, old + write_nbt_list([e for _k, e in actors]))

    def _put_frames(self, dim: int, frames: List[dict]):
        """Item frames are blocks with a block entity in Bedrock."""
        from . import terrain

        glow_ok = self.version >= (1, 17, 0)
        blocks, tes = {}, {}
        for c in frames:
            x, y, z = (int(v) for v in c.get("tile", (0, 0, 0)))
            f = int(c.get("facing", 0))
            facing = f if c.get("facing3d") else {0: 3, 1: 4, 2: 2, 3: 5}.get(f & 3, 3)
            glow = c["name"] == "glow_item_frame" and glow_ok
            item = items.to_bedrock(c["item"], self.version) if c.get("item") else None
            if item is not None and "Slot" in item:
                del item["Slot"]
            is_map = item is not None and str(nbt.get(item, "Name", "")).endswith("filled_map")
            blocks[(x, y, z)] = ("minecraft:glow_frame" if glow else "minecraft:frame",
                                 {"facing_direction": nbt.IntTag(facing), "item_frame_map_bit": nbt.ByteTag(int(is_map)),
                                  "item_frame_photo_bit": nbt.ByteTag(0)})
            t = nbt.CompoundTag({"id": nbt.StringTag("GlowItemFrame" if glow else "ItemFrame"), "x": nbt.IntTag(x),
                                 "y": nbt.IntTag(y), "z": nbt.IntTag(z), "isMovable": nbt.ByteTag(1)})
            if item is not None:
                t["Item"] = item
                t["ItemRotation"] = nbt.FloatTag(float(int(c.get("item_rot", 0)) % 8 * 45))
                t["ItemDropChance"] = nbt.FloatTag(1.0)
            tes[(x, y, z)] = t
        placed = terrain.set_blocks(self.db, lambda cx, cz: chunk_prefix(cx, cz, dim), blocks)
        by_chunk = defaultdict(list)
        for pos in placed:
            by_chunk[(pos[0] >> 4, pos[2] >> 4)].append(tes[pos])
        for (cx, cz), new in by_chunk.items():
            key = chunk_prefix(cx, cz, dim) + bytes([BE_TAG])
            existing = read_nbt_list(_get(self.db, key) or b"")
            self.db.put(key, write_nbt_list(existing + new))
        self.n_frames += len(placed)

    def put_maps(self, world: str):
        """Map data of a Java / hub world, as Bedrock map records."""
        from .. import maps

        for n, data in maps.iter_java_maps(world):
            try:
                key, rec = maps.bedrock_record(n, data)
            except Exception:  # noqa: BLE001
                continue
            self.db.put(key, nbt.dump(rec, "", little_endian=True))
            self.n_maps += 1

    def finish_terrain(self):
        from . import terrain

        try:
            terrain.fix_height_maps(self.db)
        except Exception as ex:  # noqa: BLE001
            self.progress.warn(tr("Height maps not recomputed: {error}", error=ex))

    def put_player(self, player: nbt.CompoundTag, world_game_type: Optional[int] = None):
        p = legacy_player_to_bedrock(player, self.version, self.player_uid, world_game_type)
        self.db.put(b"~local_player", nbt.dump(p, "", little_endian=True))

    def close(self):
        self.db.close()


def _log_injector(inj: "BedrockInjector", progress: Progress) -> None:
    extra = "".join(", " + w for n, w in ((inj.n_frames, tr("{n} frames", n=inj.n_frames)),
                                          (inj.n_maps, tr("{n} maps", n=inj.n_maps))) if n)
    progress.log(tr("Bedrock: {tiles} block entities and {entities} entities written{extra}.", tiles=inj.n_tiles,
                    entities=inj.n_ents, extra=extra))


def _game_type(info: WorldInfo) -> Optional[int]:
    gt = nbt.get(info.level, "GameType") if info.level is not None else None
    return int(gt) if gt is not None else None


def inject_from_hub(hub_dir: str, out_dir: str, version, info: WorldInfo, progress: Progress):
    from ..java.numeric import JavaNumericWorld

    hub = JavaNumericWorld(hub_dir)
    inj = BedrockInjector(out_dir, version, progress)
    try:
        dims = hub.dimensions()
        total = sum(len(hub.chunk_coords(d)) for d in dims) or 1
        done = 0
        for dim in dims:
            for cx, cz in hub.chunk_coords(dim):
                c = hub.read_chunk(dim, cx, cz)
                done += 1
                if c is None:
                    continue
                tl = [x for x in (tiles.from_legacy(t) for t in c.tile_entities) if x is not None]
                el = ent.read_list(c.entities, "legacy")
                if tl or el:
                    inj.put_chunk(dim, cx, cz, tl, el)
                if done % 64 == 0:
                    progress.update(done / total, tr("Entities and containers {i}/{n}", i=done, n=total))
        if info.players:
            inj.put_player(next(iter(info.players.values())), _game_type(info))
        inj.put_maps(hub_dir)
        inj.finish_terrain()
    finally:
        inj.close()
    _log_injector(inj, progress)


def inject_from_java_modern(src: str, out_dir: str, version, info: WorldInfo, progress: Progress, move=None, depth=None):
    from ..java.modern import iter_modern_extras

    inj = BedrockInjector(out_dir, version, progress)
    try:
        for dim, cx, cz, tiles_raw, ents_raw in iter_modern_extras(src, progress, with_states=True):
            tl = [x for x in (t if isinstance(t, dict) else tiles.from_java_modern(t) for t in tiles_raw) if x is not None]
            el = ent.read_list(ents_raw, "java")
            if depth is not None and dim == OVERWORLD:
                tl, el = depth.move_canon(cx, cz, tl, el)       # with their blocks (worldbridge.depthfit)
            if tl or el:
                if move is not None:
                    cx, cz = move.canon_chunk(dim, cx, cz, tl, el)
                inj.put_chunk(dim, cx, cz, tl, el)
        if info.players:
            inj.put_player(next(iter(info.players.values())), _game_type(info))
        inj.put_maps(src)
        inj.finish_terrain()
    finally:
        inj.close()
    _log_injector(inj, progress)


def _dump_list(tags: List[nbt.CompoundTag]) -> bytes:
    return b"".join(nbt.dump(t, "", little_endian=True, escape=True) for t in tags)


class _DepthMoved:
    """The block entities and actors of the Overworld of a Caves & Cliffs world, moved with their
    blocks (worldbridge.depthfit) for the raw copy of ``copy_bedrock_extras``; the ones whose blocks
    were cut are dropped and counted in ``depth.lost``."""

    def __init__(self, depth, sdb):
        self.depth = depth
        self.lost: Dict[Tuple[int, int], List[int]] = defaultdict(lambda: [0, 0])
        self.digp: Dict[bytes, bytes] = {}                  # chunk's actor list -> the one that stays
        self.actors: Dict[bytes, Optional[bytes]] = {}      # actor record -> its new bytes (None: dropped)
        for key, value in sdb.iterate(b"digp", b"digp\xff"):
            k = bytes(key)
            if len(k) == 12 and k.startswith(b"digp"):      # the Overworld: no dimension in the key
                cx, cz = struct.unpack_from("<ii", k, 4)
                keep = b""
                value = bytes(value)
                for i in range(0, len(value) // 8 * 8, 8):
                    akey = b"actorprefix" + value[i:i + 8]
                    raw = _get(sdb, akey)
                    tags = read_nbt_list(raw) if raw else []
                    if tags and self._actor(cx, cz, tags[0]):
                        self.actors[akey] = _dump_list(tags[:1])
                        keep += value[i:i + 8]
                    else:
                        self.actors[akey] = None
                self.digp[k] = keep

    def _actor(self, cx: int, cz: int, e: nbt.CompoundTag) -> bool:
        pos = nbt.get_tag(e, "Pos")
        if pos is None or len(pos) != 3:
            return True
        x, y, z = (float(v.py_data) for v in pos)
        ny = self.depth.entity_y(x, y, z)
        if ny is None:
            self.lost[(cx, cz)][1] += 1
            return False
        e["Pos"] = nbt.ListTag([nbt.FloatTag(x), nbt.FloatTag(ny), nbt.FloatTag(z)], 5)
        return True

    def chunk_list(self, k: bytes, value: bytes) -> bytes:
        """A chunk's block entities (key tag 0x31) or legacy actors (0x32) of the Overworld."""
        cx, cz = struct.unpack_from("<ii", k, 0)
        out = []
        for t in read_nbt_list(value):
            if k[-1] == ENTITY_TAG:
                if self._actor(cx, cz, t):
                    out.append(t)
                continue
            try:
                x, y, z = (int(nbt.get(t, c)) for c in ("x", "y", "z"))
            except (TypeError, ValueError):
                out.append(t)
                continue
            ny = self.depth.block_y(x, y, z)
            if ny is None:
                self.lost[(cx, cz)][0] += 1
                continue
            t["y"] = nbt.IntTag(ny)
            out.append(t)
        return _dump_list(out)

    def player(self, value: bytes) -> bytes:
        """A player record (``~local_player``, ``player_server_*``): in the Overworld it stands on
        the moved ground."""
        try:
            root = nbt.load(value, little_endian=True, compressed=False).tag
            pos = nbt.get_tag(root, "Pos")
            if pos is None or len(pos) != 3 or int(nbt.get(root, "DimensionId", 0) or 0) != 0:
                return value
            x, y, z = (float(v.py_data) for v in pos)
            root["Pos"] = nbt.ListTag([nbt.FloatTag(x), nbt.FloatTag(self.depth.point(x, y, z)), nbt.FloatTag(z)], 5)
            return nbt.dump(root, "", little_endian=True)
        except Exception:  # noqa: BLE001
            return value

    def done(self) -> None:
        for (cx, cz), (t, e) in self.lost.items():
            self.depth.count_lost(cx, cz, t, e)


def copy_bedrock_extras(src: str, dst: str, progress: Progress, depth=None):
    """Bedrock -> Bedrock (other version): keep actors, block entities, players,
    maps and every other non-terrain record exactly as they were.  ``depth``: the
    depthfit.DepthFit that moved the blocks of the Overworld: they follow them."""
    sdb = _db(src)
    ddb = _db(dst)
    n = 0
    try:
        moved = _DepthMoved(depth, sdb) if depth is not None and depth.used else None
        for key, value in sdb.iterate():
            k = bytes(key)
            v = bytes(value)
            if len(k) in (9, 13) and k[-1] in (BE_TAG, ENTITY_TAG):
                if moved is not None and len(k) == 9:
                    v = moved.chunk_list(k, v)
                    if not v:
                        continue                              # everything in it stood on cut blocks
            elif len(k) in (9, 10, 13, 14) and (k[8 if len(k) in (9, 10) else 12] in range(0x2B, 0x3D) or k[8 if len(k) in (9, 10) else 12] == 0x76):
                continue  # terrain / version records written by Amulet
            elif len(k) in (10, 14) and k[-2] == 0x2F:
                continue  # sub chunks
            elif moved is not None and (k == b"~local_player" or k.startswith(b"player_server_")):
                v = moved.player(v)
            elif moved is not None and k in moved.digp:
                v = moved.digp[k]
                if not v:
                    continue
            elif moved is not None and moved.actors.get(k, b"") is None:
                continue  # an actor whose blocks were cut
            elif moved is not None and k in moved.actors:
                v = moved.actors[k]
            ddb.put(k, v)
            n += 1
        if moved is not None:
            moved.done()
        from . import terrain

        terrain.fix_height_maps(ddb)  # Amulet rewrote the terrain with empty height maps
    finally:
        sdb.close()
        ddb.close()
    progress.log(tr("Bedrock: {n} records copied (entities, block entities, players, maps…).", n=n))
