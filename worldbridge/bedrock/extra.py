"""Raw Bedrock LevelDB access for block entities, entities and players.

Amulet translates blocks; this module writes the rest natively:

* chunk key  = <i32 x><i32 z>[<i32 dim>]<u8 tag>   (dim omitted for the Overworld)
* tag 0x31   block entities   (concatenated little endian NBT)
* tag 0x32   entities         (before 1.18.30)
* 'digp'+key / 'actorprefix'+id   entities from 1.18.30
* '~local_player'                 the single player
"""

from __future__ import annotations

import functools
import os
import struct
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .. import entities as ent
from .. import items, nbt, newcontent, placement, tiles
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


BEDROCK_SPECTATOR = 6                      # GameType / PlayerGameMode of Spectator
BEDROCK_SPECTATOR_FROM = (1, 21, 40)       # before it Bedrock has no Spectator


def bedrock_game_mode(java_mode: Optional[int], version) -> Optional[int]:
    """A Java game mode (0 - 3) as Bedrock ``version`` stores it: Spectator is 6 from Bedrock 1.21.40,
    before it the nearest is Creative.  The world's GameType and the player's PlayerGameMode use the
    same mapping, so a player in the world's mode still follows it."""
    if java_mode is None:
        return None
    m = int(java_mode)
    if m == 3:
        return BEDROCK_SPECTATOR if tuple(version)[:3] >= BEDROCK_SPECTATOR_FROM else 1
    return m if m in (0, 1, 2) else 0


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
    mode = bedrock_game_mode(gt, version)
    # compared with the world's mode as write_bedrock_level_dat writes it
    if gt is None or (world_game_type is not None and mode == bedrock_game_mode(world_game_type, version)):
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
    n = (x & 15) << 8 | (z & 15) << 4 | (y & 15)
    data = None
    if sc is not None and sc.storages:
        st = sc.storages[0]
        entry = st.palette[int(st.idx[n])]
        try:
            if "states" in entry:
                f3 = int(entry["states"]["facing_direction"].py_int)
            elif "val" in entry:                    # 1.2.13 - 1.12: {name, val}
                data = int(entry["val"].py_int)
        except Exception:  # noqa: BLE001
            pass
    elif raw:                                       # before 1.2.13: block ids and data nibbles
        b = terrain.legacy_block_at(bytes(raw), n)
        data = b[1] if b is not None else None
    if data is not None:                            # before 1.13: east 0, west 1, south 2, north 3 (+8 with a map)
        f3 = (5, 4, 3, 2)[data & 3]
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
                canon = tiles.read_canon(raw_tiles, "bedrock")
                tl = tiles.write_list(canon, "legacy", newcontent.tally_of(self.progress) if getattr(self, "progress", None) is not None else None)
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


# PyMCTranslate's 1.17.30 frame (the first version with every state), translated to each target version:
# block states from 1.13 (``item_frame_photo_bit`` only from 1.17.30), ``{block_data}`` before
_FRAME_REF = (1, 17, 30)
FRAME_ID = {"minecraft:frame": 199}          # the numeric id, for the sub chunks of before 1.2.13


@functools.lru_cache(maxsize=None)
def _frame_block(version: tuple, facing: int, is_map: bool, glow: bool):
    from ..items import _tm

    if version < (1, 13, 0) and facing < 2:
        return None                            # on a floor / ceiling: Bedrock 1.13+ only
    try:
        import amulet_nbt as anbt
        from amulet.api.block import Block

        ref = _tm().get_version("bedrock", _FRAME_REF)
        dst = _tm().get_version("bedrock", version)
        u = ref.block.to_universal(Block("minecraft", "glow_frame" if glow else "frame", {
            "facing_direction": anbt.IntTag(facing), "item_frame_map_bit": anbt.ByteTag(int(is_map)),
            "item_frame_photo_bit": anbt.ByteTag(0)}))[0]
        b = dst.block.from_universal(u)[0]
        if not b.base_name.endswith("frame"):
            return None
        props = dict(b.properties)
        if version < (1, 13, 0) and set(props) != {"block_data"}:
            return None
        return b.namespaced_name, props, FRAME_ID.get(b.namespaced_name)
    except Exception:  # noqa: BLE001
        return None


def frame_block(version, facing: int, is_map: bool, glow: bool = False):
    """The item frame block of ``version`` as terrain.set_blocks takes it: (name, states, numeric id).
    ``item_frame_photo_bit`` exists from 1.17.30; before 1.13 the states are ``{block_data}`` (east 0,
    west 1, south 2, north 3, +8 with a map).  None: the frame cannot exist in that version."""
    return _frame_block(tuple(version)[:3], int(facing), bool(is_map), bool(glow))


def _counted(fn):
    """The items a method drops because the Bedrock target lacks them are counted in the conversion's Tally."""
    @functools.wraps(fn)
    def wrapper(self, *a, **k):
        with newcontent.counting(self.tally):
            return fn(self, *a, **k)
    return wrapper


class BedrockInjector:
    def __init__(self, out_dir: str, version, progress: Progress):
        self.db = _db(out_dir)
        self.version = tuple(version)
        self.progress = progress
        self.tally = newcontent.tally_of(progress)
        self.ids = ent.ActorIds()
        _key, self.player_uid = self.ids.next()  # tamed animals belong to the world's player
        self.modern_actors = self.version >= (1, 18, 30)
        self.n_tiles = 0
        self.n_ents = 0
        self.n_frames = 0
        self.n_frames_lost = 0
        self.n_maps = 0

    @_counted
    def put_chunk(self, dim: int, cx: int, cz: int, tile_canon: List[dict], ent_canon: List[dict]):
        prefix = chunk_prefix(cx, cz, dim)
        if tile_canon:
            key = prefix + bytes([BE_TAG])
            existing = read_nbt_list(_get(self.db, key) or b"")
            by_pos = {(int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))): t for t in existing}
            for c in tile_canon:  # a block entity this version does not have: Amulet's copy of Java's goes too
                if c["kind"] == tiles.UNKNOWN or not tiles.exists_in_bedrock(c["kind"], self.version):
                    by_pos.pop(tuple(c["pos"]), None)
            tally = newcontent.tally_of(self.progress)
            for t in tiles.write_list(tile_canon, "bedrock", tally, version=self.version):
                by_pos[(int(t["x"].py_data), int(t["y"].py_data), int(t["z"].py_data))] = t
                self.n_tiles += 1
            self.db.put(key, write_nbt_list(list(by_pos.values())))
        frames = [c for c in ent_canon or [] if c.get("name") in ("item_frame", "glow_item_frame") and not c.get("skip")]
        if frames:
            self._put_frames(dim, frames)
            ent_canon = [c for c in ent_canon if c not in frames]
        # an actor goes with the chunk its position is in (a shifted or moved world, a mob that walked over a border)
        stay, away = [], {}
        for c in ent_canon or []:
            home = placement.chunk_of(c.get("pos")) if isinstance(c, dict) else None
            if home is None or home == (cx, cz) or not self._has_chunk(dim, *home):
                stay.append(c)
            else:
                away.setdefault(home, []).append(c)
        for (hx, hz), lst in away.items():
            self._put_actors(dim, hx, hz, lst)
        self._put_actors(dim, cx, cz, stay)

    def _has_chunk(self, dim: int, cx: int, cz: int) -> bool:
        prefix = chunk_prefix(cx, cz, dim)
        return any(_get(self.db, prefix + bytes([tag])) is not None for tag in (0x2C, 0x76))

    def _put_actors(self, dim: int, cx: int, cz: int, ent_canon: List[dict]):
        prefix = chunk_prefix(cx, cz, dim)
        if ent_canon:
            actors = []
            keys = []
            tally = newcontent.tally_of(self.progress)
            for c in ent_canon:
                key, uid = self.ids.next()
                e = ent.to_bedrock(c, uid, self.player_uid, self.version)
                if e is None:
                    if not c.get("skip") and ent.TO_BEDROCK.get(c.get("name"), c.get("name")) and \
                            not newcontent.bedrock_entity_exists(ent.TO_BEDROCK.get(c["name"], c["name"]), self.version):
                        tally.entities += 1               # a mob this Bedrock version does not have
                    continue
                if str(e["identifier"].py_data) != "minecraft:" + ent.TO_BEDROCK.get(c["name"], c["name"]):
                    tally.renamed += 1                    # villager_v2 -> villager, trader_llama -> llama
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

    def put_raw_tiles(self, dim: int, cx: int, cz: int, tags: List[nbt.CompoundTag]):
        """Block entities that keep their own tags (no canonical form), next to the ones of ``put_chunk``."""
        key = chunk_prefix(cx, cz, dim) + bytes([BE_TAG])
        existing = read_nbt_list(_get(self.db, key) or b"")
        have = {(int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))) for t in existing}
        new = [t for t in tags if (int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))) not in have]
        self.db.put(key, _dump_list(existing + new))
        self.n_tiles += len(new)

    def put_raw_actors(self, dim: int, cx: int, cz: int, actors: List[nbt.CompoundTag]):
        """Actors that keep their own tags (and unique ids), stored the way this version reads them."""
        prefix = chunk_prefix(cx, cz, dim)
        self.n_ents += len(actors)
        if self.modern_actors:
            keys = []
            for e in actors:
                key, _uid = self.ids.next()
                e["internalComponents"] = nbt.CompoundTag({"EntityStorageKeyComponent": nbt.CompoundTag(
                    {"StorageKey": nbt.escape_string(key)})})
                self.db.put(b"actorprefix" + key, nbt.dump(e, "", little_endian=True, escape=True))
                keys.append(key)
            self.db.put(b"digp" + prefix, (_get(self.db, b"digp" + prefix) or b"") + b"".join(keys))
        else:
            for e in actors:
                if "internalComponents" in e:
                    del e["internalComponents"]
            key = prefix + bytes([ENTITY_TAG])
            self.db.put(key, (_get(self.db, key) or b"") + _dump_list(actors))

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
            block = frame_block(self.version, facing, is_map, glow)
            if block is None:
                self.n_frames_lost += 1
                continue
            blocks[(x, y, z)] = block
            t = nbt.CompoundTag({"id": nbt.StringTag("GlowItemFrame" if glow else "ItemFrame"), "x": nbt.IntTag(x),
                                 "y": nbt.IntTag(y), "z": nbt.IntTag(z), "isMovable": nbt.ByteTag(1)})
            if item is not None:
                t["Item"] = item
                t["ItemRotation"] = nbt.FloatTag(float(int(c.get("item_rot", 0)) % 8 * 45))
                t["ItemDropChance"] = nbt.FloatTag(1.0)
            tes[(x, y, z)] = t
        # the stone under a frame is the stand-in older versions of WorldBridge wrote for Java's missing block
        placed = terrain.set_blocks(self.db, lambda cx, cz: chunk_prefix(cx, cz, dim), blocks, replace_stone=True)
        self.n_frames_lost += len(blocks) - len(placed)
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

    @_counted
    def put_player(self, player: nbt.CompoundTag, world_game_type: Optional[int] = None):
        p = legacy_player_to_bedrock(player, self.version, self.player_uid, world_game_type)
        self.db.put(b"~local_player", nbt.dump(p, "", little_endian=True))

    def close(self):
        self.db.close()


def _log_injector(inj: "BedrockInjector", progress: Progress) -> None:
    if inj.n_frames_lost:
        progress.warn(tr("{n} item frames could not be placed in Bedrock {version} (on a floor or ceiling before 1.13, "
                         "or where the block is not air): they are not in the converted world.", n=inj.n_frames_lost,
                         version=".".join(str(v) for v in inj.version[:3])))
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
                tl = tiles.read_canon(c.tile_entities, "legacy")
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
            tl = tiles.read_canon(tiles_raw, "java")
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
        for key, value in sdb.iterate(b"digp", b"digq"):
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


# ------------------------------------------------------------------ Bedrock -> Bedrock

_ITEM_LISTS = ("Inventory", "Armor", "Offhand", "Mainhand", "EnderChestInventory", "Items", "ChestItems")
_NOT_CHUNK = (b"map_", b"digp", b"actorprefix", b"~", b"player", b"portals", b"scoreboard", b"mobevents")


def _chunk_key(k: bytes) -> Optional[Tuple[int, int, int, int]]:
    """(cx, cz, dimension index, tag) of a chunk record (a sub chunk has tag 0x2F), None for the other keys."""
    if k.startswith(_NOT_CHUNK):
        return None
    if len(k) in (9, 13):
        tag = k[-1]
    elif len(k) in (10, 14) and k[-2] == 0x2F:
        tag = 0x2F
    else:
        return None
    cx, cz = struct.unpack_from("<ii", k, 0)
    dim = struct.unpack_from("<i", k, 8)[0] if len(k) in (13, 14) else 0
    return cx, cz, dim, tag


def level_version(path: str) -> Optional[Tuple[int, ...]]:
    """The game version a Bedrock world was last saved with (level.dat ``lastOpenedWithVersion``), as WorldBridge
    numbers it; None when level.dat does not say."""
    from .. import gameversion as gv

    try:
        with open(os.path.join(path, "level.dat"), "rb") as f:
            root = nbt.load(f.read()[8:], little_endian=True, compressed=False).tag
        v = [int(x.py_data) for x in nbt.get_tag(root, "lastOpenedWithVersion")]
        return gv.bedrock(tuple(v[:3])) if len(v) >= 3 and v[0] >= 1 else None
    except Exception:  # noqa: BLE001
        return None


def retarget_stack(t, version):
    """A Bedrock item stack written the way Bedrock ``version`` names / stores it (an empty slot stays).  None when
    that version lacks the item (counted by items.to_bedrock in the Tally of the conversion)."""
    try:
        it = items.from_bedrock(t)
        if it is None:
            return t
        return items.to_bedrock(it, tuple(version))
    except Exception:  # noqa: BLE001
        return t


def _empty_stack(t: nbt.CompoundTag) -> nbt.CompoundTag:
    """The empty slot that replaces a stack the version lacks (it keeps the slot number)."""
    e = nbt.CompoundTag({"Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0), "Name": nbt.StringTag(""),
                         "WasPickedUp": nbt.ByteTag(0)})
    if "Slot" in t:
        e["Slot"] = t["Slot"]
    return e


def retarget_items(tag: nbt.CompoundTag, version) -> bool:
    """The item stacks held by an actor / player / block entity (inventory, armour, hands, ``Item``...), for
    ``version``; a stack it lacks becomes an empty slot.  Returns False when the single ``Item`` of the tag (an
    item entity, a record) was one of those: there is nothing left to hold."""
    ok = True
    for k in _ITEM_LISTS:
        lst = nbt.get_tag(tag, k)
        if isinstance(lst, nbt.ListTag):
            out = []
            for x in lst:
                if isinstance(x, nbt.CompoundTag):
                    r = retarget_stack(x, version)
                    x = _empty_stack(x) if r is None else r
                out.append(x)
            tag[k] = nbt.ListTag(out, 10)
    for k in ("Item", "RecordItem"):
        if isinstance(nbt.get_tag(tag, k), nbt.CompoundTag):
            r = retarget_stack(tag[k], version)
            if r is None:
                del tag[k]
                ok = False
            else:
                tag[k] = r
    return ok


def _shift_pos(e: nbt.CompoundTag, dx: int, dz: int) -> None:
    pos = nbt.get_tag(e, "Pos")
    if (dx or dz) and pos is not None and len(pos) == 3:
        e["Pos"] = nbt.ListTag([nbt.FloatTag(float(pos[0].py_data) + dx * 16), pos[1],
                                nbt.FloatTag(float(pos[2].py_data) + dz * 16)], 5)


def _shift_tile(t: nbt.CompoundTag, dx: int, dz: int) -> None:
    for k, d in (("x", dx * 16), ("z", dz * 16), ("pairx", dx * 16), ("pairz", dz * 16)):
        if d and k in t:
            t[k] = nbt.IntTag(int(t[k].py_data) + d)


_RAW_KINDS = frozenset({"piston_arm", "lodestone", "cauldron"})   # Bedrock only: no change to make going to Bedrock


class _Downgrade:
    """The block entities and actors of a Bedrock world written for an older version of Bedrock than the source's:
    each in the form and the place that version has.  The block entities that have a canonical form (tiles) go through
    it (signs, flower pots, items...), the others keep their tags; the actors keep their tags (variants, owners, unique
    ids) with the items they hold renamed for the version, and go to the 0x32 list or to ``digp`` / ``actorprefix`` as
    the version reads them.  What the version cannot hold is dropped and counted."""

    def __init__(self, inj: "BedrockInjector", move, tally):
        self.inj = inj
        self.version = inj.version
        self.move = move
        self.tally = tally

    def chunk(self, dim: int, cx: int, cz: int, tiles_raw: List[nbt.CompoundTag], actors_raw: List[nbt.CompoundTag]):
        dx, dz = self.move.delta(dim) if self.move is not None else (0, 0)
        canon, raw = [], []
        for t in tiles_raw:
            c = tiles.from_bedrock(t)
            if c is not None and c["kind"] in _RAW_KINDS:          # only Bedrock has them: kept as they are
                c = None
            if c is not None:
                if not tiles.exists_in_bedrock(c["kind"], self.version):
                    self.tally.lose_tile(str(nbt.get(t, "id", "")))
                    continue
                if dx or dz:
                    c["pos"] = (c["pos"][0] + dx * 16, c["pos"][1], c["pos"][2] + dz * 16)
                    if c.get("pair"):
                        c["pair"] = (c["pair"][0] + dx * 16, c["pair"][1] + dz * 16)
                canon.append(c)
                continue
            if str(nbt.get(t, "id", "")) == "GlowItemFrame" and self.version < (1, 17, 0):
                self.tally.lose_tile("GlowItemFrame")
                continue
            retarget_items(t, self.version)
            _shift_tile(t, dx, dz)
            raw.append(t)
        keep = []
        for e in actors_raw:
            verdict = newcontent.downgrade_actor(e, self.version)   # villager_v2 -> villager...; None: as it is
            if verdict == "removed":
                self.tally.entities += 1
                continue
            if verdict == "renamed":
                self.tally.renamed += 1
            if not retarget_items(e, self.version) and str(nbt.get(e, "identifier", "")).endswith(":item"):
                self.tally.entities += 1                    # a dropped item whose item entity has nothing left
                continue
            _shift_pos(e, dx, dz)
            keep.append(e)
        if canon:
            self.inj.put_chunk(dim, cx + dx, cz + dz, canon, [])
        if raw:
            self.inj.put_raw_tiles(dim, cx + dx, cz + dz, raw)
        if keep:
            self.inj.put_raw_actors(dim, cx + dx, cz + dz, keep)


def _retarget_player(root: nbt.CompoundTag, version) -> None:
    retarget_items(root, version)
    gm = nbt.get(root, "PlayerGameMode")
    if gm is not None and int(gm) == 6 and tuple(version) < (1, 21, 40):    # Spectator came with 1.21.40
        root["PlayerGameMode"] = nbt.IntTag(1)


def _player_record(v: bytes, moved, move, convert: bool, version) -> bytes:
    """A player record of the source as the target has it: on the moved ground (depthfit), with its chunk (relocate),
    with the items and the game mode of an older version."""
    if moved is not None:
        v = moved.player(v)
    if move is None and not convert:
        return v
    try:
        root = nbt.load(v, little_endian=True, compressed=False).tag
        if move is not None:
            move.move_bedrock_player(root)
        if convert:
            _retarget_player(root, version)
        return nbt.dump(root, "", little_endian=True)
    except Exception:  # noqa: BLE001
        return v


def drop_orphan_actors(db) -> int:
    """The ``actorprefix`` records no ``digp`` list names (left behind when a chunk's list is replaced)."""
    used = set()
    for _k, v in db.iterate(b"digp", b"digq"):
        v = bytes(v)
        used.update(b"actorprefix" + v[i:i + 8] for i in range(0, len(v) // 8 * 8, 8))
    orphans = [bytes(k) for k, _v in db.iterate(b"actorprefix", b"actorprefiy") if bytes(k) not in used]
    for k in orphans:
        try:
            db.delete(k)
        except KeyError:
            pass
    return len(orphans)


def _delete_chunk_extras(db, tags) -> None:
    """Every actor record (0x32 lists, ``digp``, ``actorprefix``) and the chunk records with a tag of ``tags``."""
    out = []
    for k, _v in db.iterate():
        k = bytes(k)
        c = _chunk_key(k)
        if k.startswith((b"digp", b"actorprefix")) or (c is not None and c[3] in tags):
            out.append(k)
    for k in out:
        try:
            db.delete(k)
        except KeyError:
            pass


def copy_bedrock_extras(src: str, dst: str, progress: Progress, depth=None, move=None, version=None,
                        keep_state: bool = False):
    with newcontent.counting(newcontent.tally_of(progress)):
        return _copy_bedrock_extras(src, dst, progress, depth, move, version, keep_state)


def _copy_bedrock_extras(src: str, dst: str, progress: Progress, depth=None, move=None, version=None,
                         keep_state: bool = False):
    """Bedrock -> Bedrock: the block entities, actors, players, maps and every other record of the source that
    Amulet does not write, for the target ``version``.

    * target not older than the source (copy): everything is copied as it was; Amulet's own actors go first (the
      source's replace them: they would be stored twice, and the old ones left unreferenced);
    * target older (convert): block entities and actors are rewritten for its version (``_Downgrade``) and go to the
      format it reads (0x32 lists before 1.18.30, ``digp`` after), players keep their tags with the items renamed;
    * chunks moved with --move-to (``move``): their block entities and actors are Amulet's own, already moved; the
      players move with them.

    ``depth``: the depthfit.DepthFit that moved the blocks of the Overworld: the extras follow them.  ``keep_state``:
    the chunks the game had not finished keep their FinalizedState."""
    from .. import gameversion as gv

    sdb = _db(src)
    ddb = _db(dst)
    tally = newcontent.tally_of(progress)
    version = gv.bedrock(tuple(version)) if version is not None else None
    src_version = level_version(src)
    used_depth = depth is not None and depth.used
    convert = version is not None and (version[:3] < src_version[:3] if src_version is not None else used_depth)
    n = 0
    try:
        moved = _DepthMoved(depth, sdb) if used_depth else None
        inj = down = None
        if convert:
            _delete_chunk_extras(ddb, (BE_TAG, ENTITY_TAG))
            ddb.close()
            inj = BedrockInjector(dst, version, progress)       # opens the database again
            ddb = inj.db
            down = _Downgrade(inj, move, tally)
        elif move is None:
            _delete_chunk_extras(ddb, (ENTITY_TAG,))
        pending: Dict[Tuple[int, int, int], List[list]] = defaultdict(lambda: [[], []])
        for key, value in sdb.iterate():
            k = bytes(key)
            v = bytes(value)
            ck = _chunk_key(k)
            if k == b"~local_player" or k.startswith(b"player_server_"):
                v = _player_record(v, moved, move, convert, version)
            elif k.startswith(b"digp"):
                if move is not None and not convert:
                    continue                                    # Amulet's own, moved with the chunk
                ref = moved.digp.get(k, v) if moved is not None else v
                if convert:
                    actors = []
                    for i in range(0, len(ref) // 8 * 8, 8):
                        akey = b"actorprefix" + ref[i:i + 8]
                        raw = moved.actors.get(akey, _get(sdb, akey)) if moved is not None else _get(sdb, akey)
                        actors.extend(read_nbt_list(raw)[:1] if raw else [])
                    dim = DIM_FROM_BEDROCK.get(struct.unpack_from("<i", k, 12)[0] if len(k) == 16 else 0)
                    if dim is not None:
                        pending[(dim,) + struct.unpack_from("<ii", k, 4)][1].extend(actors)
                    continue
                if not ref:
                    continue
                v = ref
            elif k.startswith(b"actorprefix"):
                if convert or move is not None:
                    continue
                if moved is not None and k in moved.actors:
                    if moved.actors[k] is None:
                        continue                                # an actor whose blocks were cut
                    v = moved.actors[k]
            elif ck is not None and ck[3] in (BE_TAG, ENTITY_TAG):
                if move is not None and not convert:
                    continue                                    # Amulet's own, moved with the chunk
                if moved is not None and len(k) == 9:
                    v = moved.chunk_list(k, v)
                    if not v:
                        continue                                # everything in it stood on cut blocks
                if convert:
                    dim = DIM_FROM_BEDROCK.get(ck[2])
                    if dim is not None:
                        pending[(dim, ck[0], ck[1])][0 if ck[3] == BE_TAG else 1].extend(read_nbt_list(v))
                    continue
            elif ck is not None and ck[3] == 0x36:
                if not keep_state or move is not None or _get(ddb, k) is None:
                    continue
            elif ck is not None and (0x2B <= ck[3] < 0x3D or ck[3] == 0x76):
                continue  # terrain / version records written by Amulet
            elif ck is not None and 0x3D <= ck[3] <= 0x41 and version is not None and version < (1, 18, 0):
                continue  # records of 1.18+ (blending data, digests...) in a world that does not know them
            elif ck is not None and ck[3] == 0x2F:
                continue  # sub chunks
            ddb.put(k, v)
            n += 1
        if down is not None:
            for (dim, cx, cz), (tl, al) in pending.items():
                down.chunk(dim, cx, cz, tl, al)
            n += inj.n_tiles + inj.n_ents
        if moved is not None:
            moved.done()
        drop_orphan_actors(ddb)
        from . import terrain

        terrain.fix_height_maps(ddb)  # Amulet rewrote the terrain with empty height maps
    finally:
        sdb.close()
        ddb.close()
    progress.log(tr("Bedrock: {n} records copied (entities, block entities, players, maps…).", n=n))
