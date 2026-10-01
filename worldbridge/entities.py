"""Entity translation (legacy Java/LCE <-> Java 1.13+ <-> Bedrock) via a canonical dict."""

from __future__ import annotations

import random
import re
import struct
import uuid
from typing import List, Optional

from . import ids, items, nbt

# canonical (java 1.13 style name) -> bedrock identifier when different
TO_BEDROCK = {"zombified_piglin": "zombie_pigman", "zombie_pigman": "zombie_pigman", "iron_golem": "iron_golem",
              "villager_golem": "iron_golem", "snow_golem": "snow_golem", "snowman": "snow_golem",
              "villager": "villager_v2", "zombie_villager": "zombie_villager_v2", "experience_orb": "xp_orb",
              "xp_orb": "xp_orb", "chest_minecart": "chest_minecart", "furnace_minecart": "minecart",
              "tnt_minecart": "tnt_minecart", "hopper_minecart": "hopper_minecart",
              "commandblock_minecart": "command_block_minecart", "command_block_minecart": "command_block_minecart",
              "ender_crystal": "ender_crystal", "end_crystal": "ender_crystal", "tnt": "tnt", "falling_block": "falling_block",
              "evocation_illager": "evocation_illager", "evoker": "evocation_illager", "vindication_illager": "vindicator",
              "item_frame": None, "glow_item_frame": None, "leash_knot": "leash_knot", "fireworks_rocket": "fireworks_rocket"}
FROM_BEDROCK = {"zombie_pigman": "zombified_piglin", "villager_v2": "villager", "villager": "villager",
                "zombie_villager_v2": "zombie_villager", "xp_orb": "experience_orb", "evocation_illager": "evoker",
                "command_block_minecart": "command_block_minecart", "ender_crystal": "end_crystal",
                "iron_golem": "iron_golem", "snow_golem": "snow_golem"}
# 1.13 -> 1.11 names for the legacy writer
TO_OLDNEW = {"zombified_piglin": "zombie_pigman", "iron_golem": "villager_golem", "snow_golem": "snowman",
             "experience_orb": "xp_orb", "end_crystal": "ender_crystal", "evoker": "evocation_illager",
             "vindicator": "vindication_illager", "command_block_minecart": "commandblock_minecart",
             "firework_rocket": "fireworks_rocket", "eye_of_ender": "eye_of_ender_signal",
             "experience_bottle": "xp_bottle", "illusioner": "illusion_illager", "evoker_fangs": "evocation_fangs"}

PAINTINGS = ["Kebab", "Aztec", "Alban", "Aztec2", "Bomb", "Plant", "Wasteland", "Pool", "Courbet", "Sea", "Sunset",
             "Creebet", "Wanderer", "Graham", "Match", "Bust", "Stage", "Void", "SkullAndRoses", "Wither", "Fighters",
             "Pointer", "Pigscene", "BurningSkull", "Skeleton", "DonkeyKong"]
_PAINT_LOWER = {p.lower(): p for p in PAINTINGS}
_PAINT_LOWER.update({"skull_and_roses": "SkullAndRoses", "burning_skull": "BurningSkull", "donkey_kong": "DonkeyKong"})
_PAINT_TO_MODERN = {v: k for k, v in _PAINT_LOWER.items()}

# painting size in blocks (width, height)
PAINT_SIZE = {"Pool": (2, 1), "Courbet": (2, 1), "Sea": (2, 1), "Sunset": (2, 1), "Creebet": (2, 1),
              "Wanderer": (1, 2), "Graham": (1, 2), "Match": (2, 2), "Bust": (2, 2), "Stage": (2, 2), "Void": (2, 2),
              "SkullAndRoses": (2, 2), "Wither": (2, 2), "Fighters": (4, 2), "Pointer": (4, 4), "Pigscene": (4, 4),
              "BurningSkull": (4, 4), "Skeleton": (4, 3), "DonkeyKong": (4, 3)}

# ------------------------------------------------------------------ hanging entities
# Paintings and item frames are stored in two layouts:
#   Java 1.8+ (and the hub): TileX/Y/Z = the block in front of the wall, "Facing" = horizontal
#     index (0 south, 1 west, 2 north, 3 east);
#   Java <= 1.7 and LCE: TileX/Y/Z = the wall block, "Direction" = the same index ("Dir" before
#     1.6, numbered 2 1 0 3).
# A painting written with the wrong layout sits inside the wall and pops off as an item.
_HANG_OFF = {0: (0, 1), 1: (-1, 0), 2: (0, -1), 3: (1, 0)}
_DIR_OLD = {0: 2, 1: 1, 2: 0, 3: 3}  # "Dir" <-> horizontal index (its own inverse)
HANGING = ("Painting", "ItemFrame")


def facing_from_yaw(yaw: float) -> int:
    return int(round(yaw / 90.0)) & 3


def hanging_tile_from_pos(pos, facing: int, motive: Optional[str] = None):
    """The block (in front of the wall) of a hanging entity, from its position (inverse of Java's
    HangingEntity bounding box placement)."""
    w, h = PAINT_SIZE.get(motive, (1, 1)) if motive else (1, 1)
    fx, fz = _HANG_OFF[facing & 3]
    cx, cz = _HANG_OFF[(facing + 3) & 3]  # counter-clockwise neighbour direction
    ow = 0.5 if w % 2 == 0 else 0.0
    oh = 0.5 if h % 2 == 0 else 0.0
    x, y, z = pos
    return (int(round(x - 0.5 + fx * 0.46875 - ow * cx)), int(round(y - 0.5 - oh)),
            int(round(z - 0.5 + fz * 0.46875 - ow * cz)))


def _tile_of(e):
    bp = nbt.get_tag(e, "block_pos")
    if bp is not None and len(bp) == 3:
        return tuple(int(v) for v in bp)
    if "TileX" in e:
        return int(nbt.get(e, "TileX", 0)), int(nbt.get(e, "TileY", 0)), int(nbt.get(e, "TileZ", 0))
    return None


def _broken_tile(tile, pos) -> bool:
    """TileX/Y/Z missing, or left at 0 0 0 by an older WorldBridge conversion."""
    return tile is None or (tile == (0, 0, 0) and max(abs(v) for v in pos) > 3)


def hanging_to_modern(e: nbt.CompoundTag) -> nbt.CompoundTag:
    """Legacy hanging entity (any layout) -> TileX in front of the wall + Facing (in place)."""
    if str(nbt.get(e, "id", "")) not in HANGING:
        return e
    tile = _tile_of(e)
    pos = _list3(e, "Pos")
    if "Facing" in e:
        f = int(nbt.get(e, "Facing")) & 3
    elif "Direction" in e or "Dir" in e:
        f = int(nbt.get(e, "Direction")) & 3 if "Direction" in e else _DIR_OLD[int(nbt.get(e, "Dir")) & 3]
        if tile is not None and not _broken_tile(tile, pos):
            dx, dz = _HANG_OFF[f]
            tile = (tile[0] + dx, tile[1], tile[2] + dz)
    else:
        f = facing_from_yaw(_list3(e, "Rotation", (0.0, 0.0))[0])
    if _broken_tile(tile, pos):
        f = facing_from_yaw(_list3(e, "Rotation", (0.0, 0.0))[0])
        tile = hanging_tile_from_pos(pos, f, nbt.get(e, "Motive"))
    for k in ("Direction", "Dir", "block_pos", "facing"):
        e.pop(k, None)
    e["TileX"], e["TileY"], e["TileZ"] = nbt.IntTag(tile[0]), nbt.IntTag(tile[1]), nbt.IntTag(tile[2])
    e["Facing"] = nbt.ByteTag(f)
    return e


def hanging_to_old(e: nbt.CompoundTag) -> nbt.CompoundTag:
    """Hub hanging entity -> TileX on the wall + Direction + Dir (Java <= 1.7, LCE; in place)."""
    if str(nbt.get(e, "id", "")) not in HANGING or "Facing" not in e:
        return e
    hanging_to_modern(e)
    f = int(nbt.get(e, "Facing")) & 3
    dx, dz = _HANG_OFF[f]
    e["TileX"] = nbt.IntTag(int(nbt.get(e, "TileX")) - dx)
    e["TileZ"] = nbt.IntTag(int(nbt.get(e, "TileZ")) - dz)
    del e["Facing"]
    e["Direction"] = nbt.ByteTag(f)
    e["Dir"] = nbt.ByteTag(_DIR_OLD[f])
    return e


MOB_KEEP = ("Age", "InLove", "Sheared", "Color", "Size", "powered", "Saddle", "Sitting", "CollarColor", "Variant",
            "Profession", "CatType", "Type", "IsChickenJockey", "Anger", "PlayerCreated", "Tame", "Temper")


# ------------------------------------------------------------------ owners of tamed animals
# Canonical form: c["tamed"] (bool) and c["owner"] (the owner's UUID as a 128-bit int) or
# c["owner_name"] (Java <= 1.7 player name).  Wolves, cats and parrots are tamed exactly when they
# have an owner; horses and llamas also keep their own "Tame" flag.
OWNED_BY_PLAYER = {"wolf", "cat", "ocelot", "parrot"}
RIDEABLE = {"horse", "donkey", "mule", "llama", "trader_llama", "skeleton_horse", "zombie_horse", "camel"}
_UUID_RE = re.compile(r"^(?:ent)?([0-9a-fA-F]{8})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{4})-?([0-9a-fA-F]{12})$")
_BEDROCK_NS = uuid.UUID("5b1d9e5c-2f7e-4d4b-9a51-776f726c6462")
# Bedrock collar / tame component groups (behaviour packs of the vanilla mobs)
_BEDROCK_TAME_GROUP = {"wolf": "wolf_tame", "cat": "cat_tame", "horse": "horse_tamed", "donkey": "donkey_tamed",
                       "mule": "mule_tamed", "llama": "llama_tamed"}


def uuid_from_string(s: str) -> Optional[int]:
    m = _UUID_RE.match(s.strip())
    return int("".join(m.groups()), 16) if m else None


def uuid_string(v: int) -> str:
    return str(uuid.UUID(int=v & ((1 << 128) - 1)))


def uuid_int_array(v: int) -> nbt.IntArrayTag:
    import numpy as np

    parts = [(v >> s) & 0xFFFFFFFF for s in (96, 64, 32, 0)]
    return nbt.IntArrayTag(np.array([x - (1 << 32) if x >= 1 << 31 else x for x in parts], np.int32))


def bedrock_uuid(unique_id: int) -> int:
    """Stable Java UUID for a Bedrock actor / player unique id (the same player keeps its pets)."""
    return uuid.uuid5(_BEDROCK_NS, str(int(unique_id))).int


def _signed(v: int, bits: int) -> int:
    v &= (1 << bits) - 1
    return v - (1 << bits) if v >= 1 << (bits - 1) else v


def _read_owner(c: dict, e: nbt.CompoundTag):
    owner = None
    tag = nbt.get_tag(e, "Owner")
    if isinstance(tag, nbt.IntArrayTag) and len(tag) == 4:
        owner = 0
        for x in tag:
            owner = (owner << 32) | (int(x) & 0xFFFFFFFF)
    elif "OwnerUUIDMost" in e and "OwnerUUIDLeast" in e:
        owner = ((int(nbt.get(e, "OwnerUUIDMost")) & (2**64 - 1)) << 64) | (int(nbt.get(e, "OwnerUUIDLeast")) & (2**64 - 1))
    else:
        for key in ("OwnerUUID", "Owner"):
            s = nbt.get(e, key)
            if isinstance(s, str) and s.strip():
                owner = uuid_from_string(s)
                if owner is None:
                    c["owner_name"] = s.strip()
                break
    if owner:
        c["owner"] = owner
    if c["name"] in OWNED_BY_PLAYER:
        c["tamed"] = bool(owner or c.get("owner_name"))
    elif c["name"] in RIDEABLE:
        c["tamed"] = bool(nbt.get(e, "Tame", 0))


def _write_owner_java(e: nbt.CompoundTag, c: dict, data_version: Optional[int]):
    """data_version None = legacy hub (Java 1.12)."""
    owner = c.get("owner")
    if owner:
        if data_version is not None and data_version >= 2514:  # 1.16: EntityUUIDFix
            e["Owner"] = uuid_int_array(owner)
        else:
            e["OwnerUUID"] = nbt.StringTag(uuid_string(owner))
    elif c.get("owner_name") and (data_version is None or data_version < 2514):
        e["Owner"] = nbt.StringTag(c["owner_name"])
    if c.get("tamed") and c["name"] in RIDEABLE:
        e["Tame"] = nbt.ByteTag(1)


def _uuid_ints(rng=random) -> nbt.IntArrayTag:
    import numpy as np

    return nbt.IntArrayTag(np.array([rng.randint(-2**31, 2**31 - 1) for _ in range(4)], np.int32))


def _list3(t, key, default=(0.0, 0.0, 0.0)):
    lst = nbt.get_tag(t, key)
    if lst is None or len(lst) < 2:
        return tuple(default)
    return tuple(float(v.py_data) for v in lst)


# ============================================================= readers


def from_legacy(e: nbt.CompoundTag) -> Optional[dict]:
    eid = str(nbt.get(e, "id", ""))
    n = eid.split(":", 1)[-1]
    if ":" not in eid and n[:1].isupper():
        if n == "EntityHorse":
            n = ["horse", "donkey", "mule", "zombie_horse", "skeleton_horse"][int(nbt.get(e, "Type", 0)) % 5]
        elif n == "Skeleton" and int(nbt.get(e, "SkeletonType", 0)) == 1:
            n = "wither_skeleton"
        elif n == "Zombie" and int(nbt.get(e, "IsVillager", 0)):
            n = "zombie_villager"
        elif n == "Minecart":
            n = ["minecart", "chest_minecart", "furnace_minecart"][int(nbt.get(e, "Type", 0)) % 3]
        else:
            n = ids.ENTITY_OLD_TO_NEW.get(n)
            if n is None:
                return None
    c = _common(e)
    c["name"] = FROM_BEDROCK.get(n, n) if n in ("zombie_pigman", "villager_golem", "snowman", "xp_orb", "ender_crystal") else n
    c["name"] = {"villager_golem": "iron_golem", "snowman": "snow_golem", "xp_orb": "experience_orb",
                 "ender_crystal": "end_crystal", "zombie_pigman": "zombified_piglin"}.get(c["name"], c["name"])
    _read_java_specific(c, e, "legacy")
    _read_owner(c, e)
    return c


def _common(e) -> dict:
    c = {"pos": _list3(e, "Pos"), "motion": _list3(e, "Motion"), "rot": _list3(e, "Rotation", (0.0, 0.0))[:2]}
    h = nbt.get(e, "HealF", nbt.get(e, "Health"))
    if h is not None:
        c["health"] = float(h)
    cn = nbt.get(e, "CustomName")
    if cn:
        c["custom_name"] = items.plain_text(cn) if isinstance(cn, str) else ""
    if nbt.get(e, "CustomNameVisible"):
        c["name_visible"] = True
    c["extra"] = {k: nbt.copy(e[k]) if isinstance(e[k], nbt.CompoundTag) else e[k] for k in MOB_KEEP if k in e}
    return c


def _read_java_specific(c: dict, e: nbt.CompoundTag, src: str):
    reader = items.from_legacy if src == "legacy" else items.from_java_modern
    if c["name"] == "item" and "Item" in e:
        c["item"] = reader(e["Item"])
        if c["item"] is None:
            c["skip"] = True
    if c["name"] in ("item_frame", "glow_item_frame", "painting"):
        if c["name"] == "painting":
            mot = nbt.get(e, "Motive", nbt.get(e, "variant", "Kebab"))
            mot = str(mot).split(":", 1)[-1]
            c["motive"] = _PAINT_LOWER.get(mot.lower(), mot)
        else:
            if "Item" in e:
                c["item"] = reader(e["Item"])
            c["item_rot"] = int(nbt.get(e, "ItemRotation", 0) or 0)
        if src == "java" and c["name"] != "painting":
            # Java 1.13+ item frames: 3D facing (0 down, 1 up, 2 north, 3 south, 4 west, 5 east)
            f3 = int(nbt.get(e, "Facing", 3) or 0)
            tile = _tile_of(e)
            if _broken_tile(tile, c["pos"]) and f3 >= 2:
                tile = hanging_tile_from_pos(c["pos"], {2: 2, 3: 0, 4: 1, 5: 3}[f3])
            c["tile"] = tile or (0, 0, 0)
            c["facing"] = f3
            c["facing3d"] = True
        else:
            h = nbt.CompoundTag({k: e[k] for k in ("id", "Pos", "Rotation", "TileX", "TileY", "TileZ", "block_pos",
                                                   "Facing", "facing", "Direction", "Dir") if k in e})
            h["id"] = nbt.StringTag("Painting" if c["name"] == "painting" else "ItemFrame")
            if "facing" in e and "Facing" not in e:  # Java 1.21+ paintings
                h["Facing"] = e["facing"]
            if c["name"] == "painting":
                h["Motive"] = nbt.StringTag(c["motive"])
            hanging_to_modern(h)
            c["tile"] = (int(h["TileX"].py_data), int(h["TileY"].py_data), int(h["TileZ"].py_data))
            c["facing"] = int(h["Facing"].py_data)
    if c["name"] == "experience_orb":
        c["xp"] = int(nbt.get(e, "Value", 1) or 1)
    for key in ("Items",):
        if key in e:
            c["items"] = [it for it in (reader(t) for t in e[key]) if it]
    for key in ("Equipment", "ArmorItems", "HandItems"):
        if key in e:
            c.setdefault("equipment", {})[key] = [reader(t) if len(t) else None for t in e[key]]


def from_java_modern(e: nbt.CompoundTag) -> Optional[dict]:
    eid = str(nbt.get(e, "id", ""))
    if not eid:
        return None
    if ":" not in eid and eid[:1].isupper():
        return from_legacy(e)
    n = eid.split(":", 1)[-1]
    if n == "player":
        return None
    c = _common(e)
    c["name"] = n
    _read_java_specific(c, e, "java")
    _read_owner(c, e)
    return c


def from_bedrock(e: nbt.CompoundTag) -> Optional[dict]:
    ident = str(nbt.get(e, "identifier", "") or "")
    if not ident:
        return None
    n = ident.split(":", 1)[-1]
    if n == "player":
        return None
    n = FROM_BEDROCK.get(n, n)
    c = {"name": n, "pos": _list3(e, "Pos"), "motion": _list3(e, "Motion"), "rot": _list3(e, "Rotation", (0.0, 0.0))[:2]}
    cn = nbt.get(e, "CustomName")
    if cn:
        c["custom_name"] = str(cn)
    if nbt.get(e, "CustomNameVisible"):
        c["name_visible"] = True
    for a in nbt.get_tag(e, "Attributes") or []:
        if nbt.get(a, "Name") == "minecraft:health":
            c["health"] = float(nbt.get(a, "Current", 20.0))
    c["extra"] = {}
    if nbt.get(e, "IsBaby"):
        c["extra"]["Age"] = nbt.IntTag(-24000)
    if "Color" in e and n == "sheep":
        c["extra"]["Color"] = nbt.ByteTag(int(nbt.get(e, "Color")))
    if nbt.get(e, "Sheared"):
        c["extra"]["Sheared"] = nbt.ByteTag(1)
    if nbt.get(e, "IsTamed"):
        c["tamed"] = True
        owner = int(nbt.get(e, "OwnerNew", nbt.get(e, "OwnerID", -1)) or -1)
        if owner != -1:
            c["owner"] = bedrock_uuid(owner)
        if n in RIDEABLE:
            c["extra"]["Tame"] = nbt.ByteTag(1)
    if nbt.get(e, "Sitting"):
        c["extra"]["Sitting"] = nbt.ByteTag(1)
    if n == "wolf" and "Color" in e:
        c["extra"]["CollarColor"] = nbt.ByteTag(int(nbt.get(e, "Color")))
    if n == "item" and "Item" in e:
        c["item"] = items.from_bedrock(e["Item"])
        if c["item"] is None:
            return None
    if n == "painting":
        c["motive"] = str(nbt.get(e, "Motive", "Kebab"))
        c["facing"] = int(nbt.get(e, "Direction", 0) or 0) & 3
        c["tile"] = hanging_tile_from_pos(c["pos"], c["facing"], c["motive"])
    if n == "experience_orb":
        c["xp"] = int(nbt.get(e, "experience value", 1) or 1)
    if "Items" in e:
        c["items"] = [it for it in (items.from_bedrock(t) for t in e["Items"]) if it]
    return c


# ============================================================= writers


def to_legacy(c: dict, allowed: Optional[set] = None) -> Optional[nbt.CompoundTag]:
    if c.get("skip"):
        return None
    name = TO_OLDNEW.get(c["name"], c["name"])
    old, extra = ids.entity_to_old(name)
    if old is None:
        return None
    if allowed is not None:
        if old in ("MinecartRideable", "MinecartChest", "MinecartFurnace") and "Minecart" in allowed:
            extra = {"Type": {"MinecartRideable": 0, "MinecartChest": 1, "MinecartFurnace": 2}[old]}
            old = "Minecart"
        if old not in allowed:
            return None
    e = nbt.CompoundTag({"id": nbt.StringTag(old)})
    e["Pos"] = nbt.ListTag([nbt.DoubleTag(v) for v in c["pos"]], 6)
    e["Motion"] = nbt.ListTag([nbt.DoubleTag(v) for v in c["motion"]], 6)
    e["Rotation"] = nbt.ListTag([nbt.FloatTag(v) for v in c["rot"]], 5)
    e["OnGround"] = nbt.ByteTag(1)
    e["FallDistance"] = nbt.FloatTag(0)
    e["Fire"] = nbt.ShortTag(-1)
    e["Air"] = nbt.ShortTag(300)
    for k, v in extra.items():
        e[k] = nbt.ByteTag(v) if k in ("SkeletonType", "IsVillager", "Elder") else nbt.IntTag(v)
    if "health" in c:
        e["Health"] = nbt.ShortTag(int(round(c["health"])))
        e["HealF"] = nbt.FloatTag(c["health"])
    if c.get("custom_name"):
        e["CustomName"] = nbt.StringTag(c["custom_name"])
        e["CustomNameVisible"] = nbt.ByteTag(1 if c.get("name_visible") else 0)
    for k, v in (c.get("extra") or {}).items():
        e[k] = v
    _write_owner_java(e, c, None)
    if c.get("item") is not None:
        it = items.to_legacy(c["item"])
        if it is None:
            if c["name"] == "item":
                return None
        else:
            if "Slot" in it:
                del it["Slot"]
            e["Item"] = it
    if c["name"] == "item":
        e["Age"] = nbt.ShortTag(0)
        e["Health"] = nbt.ShortTag(5)
    if c["name"] in ("painting", "item_frame", "glow_item_frame"):
        tx, ty, tz = c.get("tile", (0, 0, 0))
        e["TileX"], e["TileY"], e["TileZ"] = nbt.IntTag(tx), nbt.IntTag(ty), nbt.IntTag(tz)
        f = c.get("facing", 0)
        if c.get("facing3d"):
            if f < 2:  # on a floor / ceiling: only possible since 1.13
                return None
            f = {2: 2, 3: 0, 4: 1, 5: 3}[f]
        e["Facing"] = nbt.ByteTag(f & 3)  # hub layout (Java 1.8 - 1.12): TileX = block in front of the wall
        if c["name"] == "painting":
            e["Motive"] = nbt.StringTag(c.get("motive", "Kebab"))
        else:
            e["ItemRotation"] = nbt.ByteTag(c.get("item_rot", 0))
    if c["name"] == "experience_orb":
        e["Value"] = nbt.ShortTag(c.get("xp", 1))
    if c.get("items"):
        e["Items"] = nbt.ListTag([t for t in (items.to_legacy(it) for it in c["items"]) if t is not None], 10)
    return e


def to_java_modern(c: dict, data_version: int) -> Optional[nbt.CompoundTag]:
    if c.get("skip"):
        return None
    name = c["name"]
    if data_version < 2566 and name == "zombified_piglin":
        name = "zombie_pigman"
    e = nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + name)})
    e["Pos"] = nbt.ListTag([nbt.DoubleTag(v) for v in c["pos"]], 6)
    e["Motion"] = nbt.ListTag([nbt.DoubleTag(v) for v in c["motion"]], 6)
    e["Rotation"] = nbt.ListTag([nbt.FloatTag(v) for v in c["rot"]], 5)
    e["OnGround"] = nbt.ByteTag(1)
    e["UUID"] = _uuid_ints()
    if "health" in c:
        e["Health"] = nbt.FloatTag(c["health"])
    if c.get("custom_name"):
        e["CustomName"] = nbt.StringTag(items.json_text(c["custom_name"]))
        e["CustomNameVisible"] = nbt.ByteTag(1 if c.get("name_visible") else 0)
    for k, v in (c.get("extra") or {}).items():
        if k in ("Age", "Sheared", "Color", "Size", "Saddle", "CollarColor", "Variant", "Sitting", "Tame", "Temper"):
            e[k] = v
    _write_owner_java(e, c, data_version)
    if c.get("item") is not None:
        e["Item"] = items.to_java_modern(c["item"], data_version)
        if "Slot" in e["Item"]:
            del e["Item"]["Slot"]
    if name in ("painting", "item_frame", "glow_item_frame"):
        tx, ty, tz = c.get("tile", (0, 0, 0))
        if data_version >= 3807:  # 1.20.5+ (BlockPosFormatAndRenamesFix)
            import numpy as np

            e["block_pos"] = nbt.IntArrayTag(np.array([tx, ty, tz], np.int32))
        else:
            e["TileX"], e["TileY"], e["TileZ"] = nbt.IntTag(tx), nbt.IntTag(ty), nbt.IntTag(tz)
        f = c.get("facing", 0)
        if name == "painting":
            if data_version >= 3818:
                e["facing"] = nbt.ByteTag(f)
                e["variant"] = nbt.StringTag("minecraft:" + _PAINT_TO_MODERN.get(c.get("motive", "Kebab"), "kebab"))
            else:
                e["Facing"] = nbt.ByteTag(f)
                key = "variant" if data_version >= 3120 else "Motive"
                e[key] = nbt.StringTag("minecraft:" + _PAINT_TO_MODERN.get(c.get("motive", "Kebab"), "kebab"))
        else:
            e["Facing"] = nbt.ByteTag({0: 3, 1: 4, 2: 2, 3: 5}.get(f, 3) if not c.get("facing3d") else f)
            e["ItemRotation"] = nbt.ByteTag(c.get("item_rot", 0))
    if name == "experience_orb":
        e["Value"] = nbt.ShortTag(c.get("xp", 1))
    if c.get("items"):
        e["Items"] = nbt.ListTag([items.to_java_modern(it, data_version) for it in c["items"]], 10)
    return e


class ActorIds:
    """Bedrock actor unique ids for one conversion session."""

    def __init__(self):
        self.session = -random.randint(0x10000, 0x7FFF0000)
        self.counter = 0

    def next(self):
        self.counter += 1
        key = struct.pack(">ii", -self.session, self.counter)
        uid = struct.unpack(">q", struct.pack(">ii", self.session, self.counter))[0]
        return key, uid


def to_bedrock(c: dict, uid: int, owner_uid: Optional[int] = None) -> Optional[nbt.CompoundTag]:
    """owner_uid: UniqueID of the world's player - a single player world has only one possible owner."""
    if c.get("skip"):
        return None
    name = c["name"]
    bname = TO_BEDROCK.get(name, name)
    if bname is None:
        return None
    e = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:" + bname)})
    e["Pos"] = nbt.ListTag([nbt.FloatTag(v) for v in c["pos"]], 5)
    e["Rotation"] = nbt.ListTag([nbt.FloatTag(v) for v in c["rot"]], 5)
    e["Motion"] = nbt.ListTag([nbt.FloatTag(v) for v in c["motion"]], 5)
    e["UniqueID"] = nbt.LongTag(uid)
    e["definitions"] = nbt.ListTag([nbt.StringTag("+minecraft:" + bname)], 8)
    e["Persistent"] = nbt.ByteTag(1)
    e["OnGround"] = nbt.ByteTag(1)
    e["Invulnerable"] = nbt.ByteTag(0)
    if c.get("custom_name"):
        e["CustomName"] = nbt.StringTag(c["custom_name"])
        e["CustomNameVisible"] = nbt.ByteTag(1 if c.get("name_visible") else 0)
    extra = c.get("extra") or {}
    if "Age" in extra and int(extra["Age"].py_data) < 0:
        e["IsBaby"] = nbt.ByteTag(1)
        e["definitions"].append(nbt.StringTag(f"+minecraft:{bname}_baby"))
    else:
        if bname in ("pig", "cow", "sheep", "chicken", "mooshroom", "rabbit", "wolf", "horse", "donkey", "mule", "llama",
                     "villager_v2", "ocelot", "cat", "panda", "fox", "bee", "goat", "turtle", "polar_bear"):
            e["definitions"].append(nbt.StringTag(f"+minecraft:{bname}_adult"))
    if "Color" in extra and bname == "sheep":
        e["Color"] = nbt.ByteTag(int(extra["Color"].py_data))
    if "Sheared" in extra:
        e["Sheared"] = nbt.ByteTag(int(extra["Sheared"].py_data))
    if c.get("tamed"):
        e["IsTamed"] = nbt.ByteTag(1)
        if owner_uid is not None:
            e["OwnerNew"] = nbt.LongTag(owner_uid)
        if bname in _BEDROCK_TAME_GROUP:
            e["definitions"].append(nbt.StringTag("+minecraft:" + _BEDROCK_TAME_GROUP[bname]))
        if "Sitting" in extra:
            e["Sitting"] = nbt.ByteTag(int(extra["Sitting"].py_data))
        if bname == "wolf":
            e["Color"] = nbt.ByteTag(int(extra["CollarColor"].py_data) if "CollarColor" in extra else 14)
    if "health" in c and bname not in ("item", "xp_orb", "painting"):
        h = float(c["health"])
        e["Attributes"] = nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag("minecraft:health"), "Base": nbt.FloatTag(h),
                                                        "Current": nbt.FloatTag(h), "Max": nbt.FloatTag(max(h, 1.0)),
                                                        "DefaultMax": nbt.FloatTag(max(h, 1.0)), "DefaultMin": nbt.FloatTag(0),
                                                        "Min": nbt.FloatTag(0)})], 10)
    if bname == "item":
        it = items.to_bedrock(c["item"], (1, 21, 0)) if c.get("item") else None
        if it is None:
            return None
        if "Slot" in it:
            del it["Slot"]
        e["Item"] = it
        e["definitions"] = nbt.ListTag([], 8)
    if bname == "painting":
        e["Motive"] = nbt.StringTag(c.get("motive", "Kebab"))
        e["Direction"] = nbt.ByteTag(c.get("facing", 0))
        tx, ty, tz = c.get("tile", (0, 0, 0))
        e["Pos"] = nbt.ListTag([nbt.FloatTag(tx + 0.5), nbt.FloatTag(ty + 0.5), nbt.FloatTag(tz + 0.5)], 5)
        e["definitions"] = nbt.ListTag([], 8)
    if bname == "xp_orb":
        e["experience value"] = nbt.IntTag(c.get("xp", 1))
    if c.get("items"):
        e["Items"] = nbt.ListTag([t for t in (items.to_bedrock(it, (1, 21, 0)) for it in c["items"]) if t is not None], 10)
    return e


# ============================================================= list helpers

def read_list(ents, src: str) -> List[dict]:
    reader = {"legacy": from_legacy, "java": from_java_modern, "bedrock": from_bedrock}[src]
    out = []
    for e in ents or []:
        if isinstance(e, nbt.CompoundTag):
            try:
                c = reader(e)
            except Exception:  # noqa: BLE001
                c = None
            if c is not None:
                out.append(c)
    return out
