"""Entity translation (legacy Java/LCE <-> Java 1.13+ <-> Bedrock) via a canonical dict."""

from __future__ import annotations

import random
import re
import struct
import uuid
from typing import List, Optional

from . import ids, items, nbt, newcontent

# canonical (java 1.13 style name) -> bedrock identifier when different
TO_BEDROCK = {"zombified_piglin": "zombie_pigman", "zombie_pigman": "zombie_pigman", "iron_golem": "iron_golem",
              "villager_golem": "iron_golem", "snow_golem": "snow_golem", "snowman": "snow_golem",
              "villager": "villager_v2", "zombie_villager": "zombie_villager_v2", "experience_orb": "xp_orb",
              "xp_orb": "xp_orb", "chest_minecart": "chest_minecart", "furnace_minecart": "minecart",
              "tnt_minecart": "tnt_minecart", "hopper_minecart": "hopper_minecart",
              "commandblock_minecart": "command_block_minecart", "command_block_minecart": "command_block_minecart",
              "ender_crystal": "ender_crystal", "end_crystal": "ender_crystal", "tnt": "tnt", "falling_block": "falling_block",
              "evocation_illager": "evocation_illager", "evoker": "evocation_illager", "vindication_illager": "vindicator",
              "item_frame": None, "glow_item_frame": None, "leash_knot": "leash_knot", "fireworks_rocket": "fireworks_rocket",
              "firework_rocket": "fireworks_rocket", "tropical_fish": "tropicalfish", "trident": "thrown_trident",
              "potion": "splash_potion", "experience_bottle": "xp_bottle", "eye_of_ender": "eye_of_ender_signal",
              "evoker_fangs": "evocation_fang", "fishing_bobber": "fishing_hook"}
FROM_BEDROCK = {"zombie_pigman": "zombified_piglin", "villager_v2": "villager", "villager": "villager",
                "zombie_villager_v2": "zombie_villager", "xp_orb": "experience_orb", "evocation_illager": "evoker",
                "command_block_minecart": "command_block_minecart", "ender_crystal": "end_crystal",
                "iron_golem": "iron_golem", "snow_golem": "snow_golem", "tropicalfish": "tropical_fish",
                "thrown_trident": "trident", "splash_potion": "potion", "lingering_potion": "potion",
                "xp_bottle": "experience_bottle", "eye_of_ender_signal": "eye_of_ender", "evocation_fang": "evoker_fangs",
                "fishing_hook": "fishing_bobber", "fireworks_rocket": "firework_rocket", "vindicator": "vindicator"}
# boats: Java <= 1.21.1 "boat" + Type, Java 1.21.2+ one id per wood, Bedrock "boat" + Variant
BOAT_WOODS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "bamboo", "cherry", "pale_oak")
_BOAT_IDS = {f"{w}_{k}": (k if k in ("boat", "chest_boat") else k.replace("raft", "boat"), w)
             for w in BOAT_WOODS for k in (("raft", "chest_raft") if w == "bamboo" else ("boat", "chest_boat"))}
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

_FROM_OLDNEW = {v: k for k, v in TO_OLDNEW.items()}

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
            "Profession", "CatType", "Type", "IsChickenJockey", "Anger", "PlayerCreated", "Tame", "Temper", "VillagerData",
            "Career", "CareerLevel", "CatType", "RabbitType", "variant")


# ------------------------------------------------------------------ villager professions
# Java <= 1.13 (and LCE): Profession + Career numbers; Java 1.14+: VillagerData.  The mapping is the
# game's own upgrade (VillagerProfessionFix / VillagerDataFix).
_PROFESSIONS = {0: {2: "fisherman", 3: "shepherd", 4: "fletcher", None: "farmer"},
                1: {2: "cartographer", None: "librarian"}, 2: {None: "cleric"},
                3: {2: "weaponsmith", 3: "toolsmith", None: "armorer"}, 4: {2: "leatherworker", None: "butcher"},
                5: {None: "nitwit"}}
_PROFESSION_OLD = {name: (p, car if car is not None else 1) for p, cars in _PROFESSIONS.items() for car, name in cars.items()}


def villager_data(extra: dict) -> Optional[nbt.CompoundTag]:
    """VillagerData (Java 1.14+) of a villager's kept data: its own, or one from Profession / Career."""
    vd = extra.get("VillagerData")
    if isinstance(vd, nbt.CompoundTag):
        return nbt.copy(vd)
    if "Profession" not in extra:
        return None
    prof = int(extra["Profession"].py_data)
    career = int(extra["Career"].py_data) if "Career" in extra else None
    cars = _PROFESSIONS.get(prof)
    name = (cars.get(career) or cars[None]) if cars else "none"
    level = int(extra["CareerLevel"].py_data) if "CareerLevel" in extra else 1
    return nbt.CompoundTag({"profession": nbt.StringTag("minecraft:" + name), "level": nbt.IntTag(max(1, min(5, level))),
                            "type": nbt.StringTag("minecraft:plains")})


def legacy_profession(vd: nbt.CompoundTag) -> dict:
    """Profession / Career / CareerLevel (Java <= 1.13) of a VillagerData."""
    name = str(nbt.get(vd, "profession", "")).split(":", 1)[-1]
    if name not in _PROFESSION_OLD:
        return {}
    prof, career = _PROFESSION_OLD[name]
    return {"Profession": nbt.IntTag(prof), "Career": nbt.IntTag(career),
            "CareerLevel": nbt.IntTag(int(nbt.get(vd, "level", 1) or 1))}


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
    c["name"] = _FROM_OLDNEW.get(c["name"], c["name"])  # 1.11 ids (vindication_illager...) -> 1.13
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
    _read_java_equipment(c, e, reader)
    if c["name"] in EQUIDS:
        _read_java_chest(c, e, src)


# Canonical chest of donkeys, mules and llamas: c["chested"] (the animal carries a chest) and c["chest"], the
# stacks of the chest with ``slot`` = 0-based position in the chest (0 .. 14).  Java keeps them in "Items" with
# the saddle / armour / carpet slots in front of them in the old inventory: slots 2 .. 16 before 24w05a (1.20.5,
# data version 3809), 0 .. 14 after it.  Bedrock keeps the chest in ChestItems slots 1 .. 15 (slot 0: the saddle
# of a donkey / mule, the carpet of a llama).
CHESTED = ("donkey", "mule", "llama", "trader_llama")
CHEST_SLOTS = 15
CHEST_DV = 3809                  # Java 24w05a (1.20.5): the chest starts at slot 0
EQUIPMENT_COMPOUND_DV = 4325     # Java 1.21.5: "equipment" holds the saddle and the body armour
DV_STAMP = "_wb_dv"              # DataVersion of the chunk an entity was read from (set by java.modern.iter_modern_extras)


def _java_chest_new_layout(e: nbt.CompoundTag, src: str, slots) -> bool:
    """Whether the chest of a Java entity starts at slot 0 (data version >= 3809); the version of its chunk when known,
    else the keys of the entity (body_armor_item / equipment: new; ArmorItem / DecorItem: old), else the slots."""
    if src == "legacy":
        return False
    dv = nbt.get(e, DV_STAMP)
    if dv is not None:
        return int(dv) >= CHEST_DV
    if "equipment" in e or "body_armor_item" in e:
        return True
    if "ArmorItem" in e or "DecorItem" in e:
        return False
    if slots:
        if max(slots) >= CHEST_SLOTS:
            return False
        if min(slots) < 2:
            return True
    return True


def _read_java_chest(c: dict, e: nbt.CompoundTag, src: str) -> None:
    its = c.pop("items", None) or []                   # an equid's "Items" are its inventory, not a container
    if c["name"] not in CHESTED:
        return
    slots = [int(it["slot"]) for it in its if it.get("slot") is not None]
    off = 0 if _java_chest_new_layout(e, src, slots) else 2
    chest = []
    for it in its:
        if it.get("slot") is None:
            continue
        idx = int(it["slot"]) - off
        if 0 <= idx < CHEST_SLOTS:
            it["slot"] = idx
            chest.append(it)
    if nbt.get(e, "ChestedHorse") or chest:
        c["chested"] = True
        c["chest"] = sorted(chest, key=lambda it: it["slot"])


# Canonical equipment: c["equip"] = {"hand": [main, off], "armor": [feet, legs, chest, head],
# "saddle": item, "body": item} (canonical items or None), read from every Java layout:
#   Java <= 1.8 and LCE: "Equipment" [hand, feet, legs, chest, head]
#   Java 1.9 - 1.21.4:   "HandItems" [main, off], "ArmorItems" [feet .. head]; horses "SaddleItem" and
#                        "ArmorItem" (1.20.5: "body_armor_item"), llamas "DecorItem"
#   Java 1.21.5+:        "equipment" {mainhand, offhand, feet, legs, chest, head, body, saddle}
_EQUIP_121 = (("mainhand", "hand", 0), ("offhand", "hand", 1), ("feet", "armor", 0), ("legs", "armor", 1),
              ("chest", "armor", 2), ("head", "armor", 3))


def _read_java_equipment(c: dict, e: nbt.CompoundTag, reader) -> None:
    def item(t):
        return reader(t) if isinstance(t, nbt.CompoundTag) and len(t) and "id" in t else None

    eq = {"hand": [None, None], "armor": [None, None, None, None], "saddle": None, "body": None}
    old = nbt.get_tag(e, "Equipment")
    if isinstance(old, nbt.ListTag) and len(old):
        lst = [item(t) for t in old]
        eq["hand"][0] = lst[0]
        for i, it in enumerate(lst[1:5]):
            eq["armor"][i] = it
    for key, slot in (("HandItems", "hand"), ("ArmorItems", "armor")):
        lst = nbt.get_tag(e, key)
        if isinstance(lst, nbt.ListTag):
            for i, t in enumerate(list(lst)[:len(eq[slot])]):
                eq[slot][i] = item(t)
    new = nbt.get_tag(e, "equipment")
    if isinstance(new, nbt.CompoundTag):
        for key, slot, i in _EQUIP_121:
            eq[slot][i] = item(nbt.get_tag(new, key))
        eq["body"] = item(nbt.get_tag(new, "body"))
        eq["saddle"] = item(nbt.get_tag(new, "saddle"))
    eq["saddle"] = eq["saddle"] or item(nbt.get_tag(e, "SaddleItem"))
    eq["body"] = eq["body"] or item(nbt.get_tag(e, "body_armor_item")) or item(nbt.get_tag(e, "ArmorItem")) or \
        item(nbt.get_tag(e, "DecorItem"))
    if any(eq["hand"]) or any(eq["armor"]) or eq["saddle"] or eq["body"]:
        c["equip"] = eq


def _write_java_equipment(e: nbt.CompoundTag, c: dict, write, data_version: Optional[int] = None) -> None:
    """Equipment in the Java 1.9 - 1.20.4 layout (the game upgrades it); ``write``: item writer.  The horse armour
    / llama carpet and the saddle follow ``data_version`` where the layout changed: body_armor_item from 1.20.5
    (3809), the "equipment" compound from 1.21.5 (4325)."""
    eq = c.get("equip")
    if not eq:
        return

    def stack(it):
        t = write(it) if it else None
        if t is None:
            return nbt.CompoundTag()
        t.pop("Slot", None)
        return t

    if any(eq["hand"]) or any(eq["armor"]):
        e["HandItems"] = nbt.ListTag([stack(it) for it in eq["hand"]], 10)
        e["ArmorItems"] = nbt.ListTag([stack(it) for it in eq["armor"]], 10)
    if c["name"] in RIDEABLE or c["name"] in ("horse", "donkey", "mule", "skeleton_horse", "zombie_horse"):
        saddle = stack(eq["saddle"]) if eq.get("saddle") else None
        body = stack(eq["body"]) if eq.get("body") else None
        saddle = saddle if saddle is not None and len(saddle) else None
        body = body if body is not None and len(body) else None
        dv = data_version or 0
        if dv >= EQUIPMENT_COMPOUND_DV:
            if saddle is not None or body is not None:
                new_eq = e["equipment"] if isinstance(nbt.get_tag(e, "equipment"), nbt.CompoundTag) else nbt.CompoundTag()
                if saddle is not None:
                    new_eq["saddle"] = saddle
                if body is not None:
                    new_eq["body"] = body
                e["equipment"] = new_eq
            return
        if saddle is not None:
            e["SaddleItem"] = saddle
        if body is not None:
            e["body_armor_item" if dv >= CHEST_DV else
              "DecorItem" if c["name"] in ("llama", "trader_llama") else "ArmorItem"] = body


def _write_java_chest(e: nbt.CompoundTag, c: dict, write, data_version: Optional[int]) -> None:
    """ChestedHorse and the chest "Items" of a donkey / mule / llama in the layout of ``data_version`` (None: the
    legacy one, slots 2 .. 16)."""
    if c["name"] not in CHESTED or not c.get("chested"):
        return
    e["ChestedHorse"] = nbt.ByteTag(1)
    off = 0 if data_version is not None and data_version >= CHEST_DV else 2
    out = []
    for it in c.get("chest") or []:
        idx = it.get("slot")
        t = write(it)
        if t is None or idx is None or not 0 <= int(idx) < CHEST_SLOTS:
            continue
        t["Slot"] = nbt.ByteTag(int(idx) + off)
        out.append(t)
    e["Items"] = nbt.ListTag(out, 10)


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
    c["name"] = _FROM_OLDNEW.get(n, n)
    if n in _BOAT_IDS:  # Java 1.21.2+: oak_boat... -> boat + Type (the game splits it again)
        c["name"], wood = _BOAT_IDS[n]
        c["extra"]["Type"] = nbt.StringTag(wood)
    _read_java_specific(c, e, "java")
    _read_owner(c, e)
    return c


# ------------------------------------------------------------------ variants, saddles, armour
# Java keeps a mob's look in Variant (horse: colour | marking << 8; llama, parrot, axolotl), CatType (cat, before
# 1.19) / variant, RabbitType, Type (fox, mooshroom: "red" / "snow" / "brown"); Bedrock in Variant (+ MarkVariant for
# the horse's marking) and, redundantly, in the "+minecraft:<group>" definitions.
HORSE_BASE = ("white", "creamy", "chestnut", "brown", "black", "gray", "darkbrown")
HORSE_MARKINGS = ("none", "white_details", "white_fields", "white_dots", "black_dots")
LLAMA_COATS = ("creamy", "white", "brown", "gray")
CAT_NAMES = ("tabby", "black", "red", "siamese", "british_shorthair", "calico", "persian", "ragdoll", "white", "jellie",
             "all_black")                                        # Java's, by CatType
CAT_BEDROCK = (8, 1, 2, 3, 4, 5, 6, 7, 0, 10, 9)                  # Java CatType -> Bedrock Variant (an involution)
AXOLOTL_BEDROCK = (0, 3, 2, 1, 4)                                 # Java lucy, wild, gold, cyan, blue -> Bedrock (also its own inverse)
FOX_TYPES = ("red", "snow")
MOOSHROOM_TYPES = ("red", "brown")
EQUIDS = ("horse", "donkey", "mule", "skeleton_horse", "zombie_horse", "llama", "trader_llama", "camel")
JAVA_CAT_VARIANT_DV = 3105                                        # 1.19: cats have a variant name, not CatType
# Bedrock's preferred professions (villager_v2) by Java's profession name
BEDROCK_PROFESSIONS = ("farmer", "fisherman", "shepherd", "fletcher", "librarian", "cartographer", "cleric", "armorer",
                       "weaponsmith", "toolsmith", "butcher", "leatherworker", "mason", "nitwit")
# villager_v2.json of the vanilla behaviour pack (identical from 1.11 to 1.26): the component groups are not
# namespaced ("+farmer", "+adult"), each profession group sets the ``minecraft:variant`` below, and the biome
# skin groups set ``minecraft:mark_variant`` (plains: no group, 0).
VILLAGER_VARIANT = {"unskilled": 0, "farmer": 1, "fisherman": 2, "shepherd": 3, "fletcher": 4, "librarian": 5,
                    "cartographer": 6, "cleric": 7, "armorer": 8, "weaponsmith": 9, "toolsmith": 10, "butcher": 11,
                    "leatherworker": 12, "mason": 13, "nitwit": 14}
VILLAGER_PEASANTS = ("unskilled", "farmer", "fisherman", "shepherd", "fletcher", "nitwit")   # behavior_peasant
VILLAGER_BIOMES = ("plains", "desert", "jungle", "savanna", "snow", "swamp", "taiga")        # = MarkVariant


def _int_extra(extra: dict, key: str) -> Optional[int]:
    v = extra.get(key)
    try:
        return int(v.py_data) if v is not None else None
    except (AttributeError, TypeError, ValueError):
        return None


def _str_extra(extra: dict, key: str) -> Optional[str]:
    v = extra.get(key)
    return str(v.py_data).split(":", 1)[-1] if isinstance(v, nbt.StringTag) else None


def _empty_slot(i: int) -> nbt.CompoundTag:
    return nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0),
                            "Slot": nbt.ByteTag(i), "WasPickedUp": nbt.ByteTag(0)})


def write_bedrock_variants(e: nbt.CompoundTag, c: dict, bname: str, version) -> None:
    """Variant / MarkVariant, Saddled, the saddle and armour slots and the villager's profession of a mob."""
    extra = c.get("extra") or {}
    eq = c.get("equip") or {}
    defs = e["definitions"]
    variant = None
    if bname == "horse":
        v = _int_extra(extra, "Variant")
        if v is not None:
            variant = v & 0xFF
            mark = (v >> 8) & 0xFF
            e["MarkVariant"] = nbt.IntTag(mark)
            defs.append(nbt.StringTag("+minecraft:base_" + HORSE_BASE[min(variant, 6)]))
            defs.append(nbt.StringTag("+minecraft:markings_" + HORSE_MARKINGS[min(mark, 4)]))
    elif bname in ("llama", "trader_llama", "parrot"):
        variant = _int_extra(extra, "Variant")
        if variant is not None and bname != "parrot":
            defs.append(nbt.StringTag("+minecraft:llama_" + LLAMA_COATS[min(max(variant, 0), 3)]))
    elif bname == "axolotl":
        v = _int_extra(extra, "Variant")
        variant = AXOLOTL_BEDROCK[v] if v is not None and 0 <= v < 5 else None
    elif bname == "cat":
        v = _int_extra(extra, "CatType")
        if v is None and _str_extra(extra, "variant") in CAT_NAMES:
            v = CAT_NAMES.index(_str_extra(extra, "variant"))
        variant = CAT_BEDROCK[v] if v is not None and 0 <= v < len(CAT_BEDROCK) else None
    elif bname == "rabbit":
        variant = _int_extra(extra, "RabbitType")
    elif bname == "fox":
        t = _str_extra(extra, "Type")
        variant = FOX_TYPES.index(t) if t in FOX_TYPES else None
    elif bname == "mooshroom":
        t = _str_extra(extra, "Type")
        if t in MOOSHROOM_TYPES:
            variant = MOOSHROOM_TYPES.index(t)
            defs.append(nbt.StringTag("+minecraft:mooshroom_" + t))
    if variant is not None:
        e["Variant"] = nbt.IntTag(variant)
    saddle = eq.get("saddle")
    saddled = bool(saddle) or bool(_int_extra(extra, "Saddle"))
    if bname in ("pig", "strider"):
        e["Saddled"] = nbt.ByteTag(int(saddled))
        defs.append(nbt.StringTag(f"+minecraft:{bname}_" + ("saddled" if saddled else "unsaddled")))
    elif bname in EQUIDS:
        body = eq.get("body")
        if saddled:
            e["Saddled"] = nbt.ByteTag(1)
        chested_kind = bname in CHESTED
        chested = chested_kind and bool(c.get("chested"))
        if chested_kind:
            e["Chested"] = nbt.ByteTag(int(chested))
            if chested:
                key = "llama" if bname in ("llama", "trader_llama") else bname
                defs.append(nbt.StringTag(f"-minecraft:{key}_unchested"))
                defs.append(nbt.StringTag(f"+minecraft:{key}_chested"))
        # slot 0 of the animal's inventory: the saddle (a llama wears a carpet there), slot 1 the horse armour,
        # slots 1 .. 15 the chest of a donkey / mule / llama
        first = body if bname in ("llama", "trader_llama") else saddle
        second = None if chested_kind else body
        chest = {}
        if chested:
            for it in c.get("chest") or []:
                idx = it.get("slot")
                if idx is not None and 0 <= int(idx) < CHEST_SLOTS:
                    chest[int(idx) + 1] = it
        if first or second or chest:
            slots = []
            for i in range(CHEST_SLOTS + 1 if chested else 2):
                it = first if i == 0 else second if i == 1 and not chested_kind else chest.get(i)
                t = items.to_bedrock(it, tuple(version)) if it else None
                if t is None:
                    t = _empty_slot(i)
                else:
                    t["Slot"] = nbt.ByteTag(i)
                slots.append(t)
            e["ChestItems"] = nbt.ListTag(slots, 10)
    elif bname == "villager_v2":
        vd = villager_data(extra)
        prof = str(nbt.get(vd, "profession", "")).split(":", 1)[-1] if vd is not None else ""
        if prof in BEDROCK_PROFESSIONS:
            e["PreferredProfession"] = nbt.StringTag(prof)
            e["TradeTier"] = nbt.IntTag(max(0, int(nbt.get(vd, "level", 1) or 1) - 1))
        # the component groups the game itself adds (entity_spawned / entity_born / ageable_grow_up events)
        job = prof if prof in VILLAGER_VARIANT else "unskilled"
        if nbt.get(e, "IsBaby"):
            job = "unskilled"
            groups = ["baby", "unskilled", "child_schedule"]
        elif job == "nitwit":
            groups = ["adult", "nitwit", "behavior_peasant", "jobless_schedule"]
        else:
            groups = ["adult", job, "behavior_peasant" if job in VILLAGER_PEASANTS else "behavior_non_peasant",
                      "basic_schedule"]
        defs.extend(nbt.StringTag("+" + g) for g in groups)
        e["Variant"] = nbt.IntTag(VILLAGER_VARIANT[job])
        biome = str(nbt.get(vd, "type", "plains")).split(":", 1)[-1] if vd is not None else "plains"
        mark = VILLAGER_BIOMES.index(biome) if biome in VILLAGER_BIOMES else 0
        e["MarkVariant"] = nbt.IntTag(mark)
        if mark:
            defs.append(nbt.StringTag("+" + biome + "_villager"))


def read_bedrock_variants(c: dict, e: nbt.CompoundTag, n: str, version=None) -> None:
    """The inverse of :func:`write_bedrock_variants`, into the canonical extras and equipment."""
    extra = c["extra"]
    var = nbt.get(e, "Variant")
    var = int(var) if var is not None else None
    if n == "horse" and var is not None:
        extra["Variant"] = nbt.IntTag((var & 0xFF) | (max(0, int(nbt.get(e, "MarkVariant", 0) or 0)) & 0xFF) << 8)
    elif n in ("llama", "trader_llama", "parrot") and var is not None:
        extra["Variant"] = nbt.IntTag(var)
    elif n == "axolotl" and var is not None and 0 <= var < 5:
        extra["Variant"] = nbt.IntTag(AXOLOTL_BEDROCK[var])
    elif n == "cat" and var is not None and 0 <= var < len(CAT_BEDROCK):
        extra["CatType"] = nbt.IntTag(CAT_BEDROCK[var])
    elif n == "rabbit" and var is not None:
        extra["RabbitType"] = nbt.IntTag(var)
    elif n == "fox" and var in (0, 1):
        extra["Type"] = nbt.StringTag(FOX_TYPES[var])
    elif n == "mooshroom" and var in (0, 1):
        extra["Type"] = nbt.StringTag(MOOSHROOM_TYPES[var])
    saddled = bool(nbt.get(e, "Saddled"))
    if n in ("pig", "strider"):
        if saddled:
            extra["Saddle"] = nbt.ByteTag(1)
        return
    if n in EQUIDS:
        slots = {}
        for i, t in enumerate(nbt.get_tag(e, "ChestItems") or []):
            if isinstance(t, nbt.CompoundTag) and str(nbt.get(t, "Name", "") or ""):
                it = items.from_bedrock(t)
                if it is not None:
                    slots[int(nbt.get(t, "Slot", i))] = it
        llama = n in ("llama", "trader_llama")
        first, second = slots.get(0), slots.get(1)
        saddle, body = (None, first) if llama else (first, None if n in CHESTED else second)
        if body is None and not llama:               # horse armour is also kept in the Armor list
            for t in nbt.get_tag(e, "Armor") or []:
                if isinstance(t, nbt.CompoundTag) and str(nbt.get(t, "Name", "") or "").endswith("horse_armor"):
                    body = items.from_bedrock(t)
        if n in CHESTED:
            chest = []
            for s_, it in sorted(slots.items()):
                if 1 <= s_ <= CHEST_SLOTS:
                    it["slot"] = s_ - 1
                    chest.append(it)
            if nbt.get(e, "Chested") or chest:
                c["chested"] = True
                c["chest"] = chest
        if saddle is None and saddled and not llama:
            saddle = items.Item(name="saddle", count=1, damage=0, slot=None)
        if saddle or body:
            eq = c.setdefault("equip", {"hand": [None, None], "armor": [None] * 4, "saddle": None, "body": None})
            eq["saddle"], eq["body"] = saddle, body
    if n == "villager":
        prof = nbt.get(e, "PreferredProfession")
        mark = int(nbt.get(e, "MarkVariant", 0) or 0)
        biome = VILLAGER_BIOMES[mark] if 0 <= mark < len(VILLAGER_BIOMES) else "plains"
        if prof or biome != "plains":
            extra["VillagerData"] = nbt.CompoundTag({
                "profession": nbt.StringTag("minecraft:" + (str(prof).split(":", 1)[-1] if prof else "none")),
                "level": nbt.IntTag(max(1, min(5, int(nbt.get(e, "TradeTier", 0) or 0) + 1))),
                "type": nbt.StringTag("minecraft:" + biome)})


# Pocket Edition 0.9 - 0.16 (LevelDB) saved an entity by its number, ``id`` (a few later versions OR the
# category into the high bytes): the numbers are Bedrock's legacy ones.  The names are Java's, or the
# Bedrock identifier FROM_BEDROCK translates.
PE_ENTITY_NUMBERS = {
    **items.BEDROCK_ENTITY_NAMES, 51: "npc", 52: "wither", 53: "ender_dragon", 63: "player", 64: "item", 65: "tnt",
    66: "falling_block", 68: "xp_bottle", 69: "xp_orb", 70: "eye_of_ender_signal", 71: "ender_crystal",
    72: "fireworks_rocket", 73: "thrown_trident", 76: "shulker_bullet", 77: "fishing_hook", 79: "dragon_fireball",
    80: "arrow", 81: "snowball", 82: "egg", 83: "painting", 84: "minecart", 85: "fireball", 86: "splash_potion",
    87: "ender_pearl", 88: "leash_knot", 89: "wither_skull", 90: "boat", 91: "wither_skull", 93: "lightning_bolt",
    94: "small_fireball", 95: "area_effect_cloud", 96: "hopper_minecart", 97: "tnt_minecart", 98: "chest_minecart",
    100: "command_block_minecart", 101: "lingering_potion", 102: "llama_spit", 103: "evocation_fang"}


def from_bedrock(e: nbt.CompoundTag) -> Optional[dict]:
    ident = str(nbt.get(e, "identifier", "") or "")
    pe_numeric = False
    if not ident:
        num = nbt.get(e, "id")
        if isinstance(num, int) and not isinstance(num, bool):     # Pocket Edition 0.9 - 0.16
            ident = PE_ENTITY_NUMBERS.get(num & 0xFF, "")
            pe_numeric = True
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
        if nbt.get(a, "Name") in ("minecraft:health", "generic.health"):
            c["health"] = float(nbt.get(a, "Current", 20.0))
    c["extra"] = {}
    if nbt.get(e, "IsBaby") or (pe_numeric and int(nbt.get(e, "Age", 0) or 0) < 0):
        c["extra"]["Age"] = nbt.IntTag(-24000)
    if "Color" in e and n == "sheep":
        c["extra"]["Color"] = nbt.ByteTag(int(nbt.get(e, "Color")))
    if nbt.get(e, "Sheared"):
        c["extra"]["Sheared"] = nbt.ByteTag(1)
    if n in ("boat", "chest_boat"):
        v = int(nbt.get(e, "Variant", 0) or 0)
        c["extra"]["Type"] = nbt.StringTag(BOAT_WOODS[v] if 0 <= v < len(BOAT_WOODS) else "oak")
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

    def stack(t):
        return items.from_bedrock(t) if isinstance(t, nbt.CompoundTag) and str(nbt.get(t, "Name", "") or "") else None

    hand = [stack((nbt.get_tag(e, k) or [None])[0]) for k in ("Mainhand", "Offhand")]
    armor = [stack(t) for t in list(nbt.get_tag(e, "Armor") or [])[:4]]
    armor = (armor + [None] * 4)[:4][::-1]                  # Bedrock: head .. feet; canonical: feet .. head
    if n in EQUIDS:                                          # horse armour is not worn armour
        armor = [None if it is not None and it["name"].endswith("horse_armor") else it for it in armor]
    if any(hand) or any(armor):
        c["equip"] = {"hand": hand, "armor": armor, "saddle": None, "body": None}
    if not pe_numeric:
        read_bedrock_variants(c, e, n)
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
        if k != "VillagerData":
            e[k] = v
    if "VillagerData" in (c.get("extra") or {}) and "Profession" not in e:
        e.update(legacy_profession(c["extra"]["VillagerData"]))
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
    _write_java_chest(e, c, items.to_legacy, None)
    _write_java_equipment(e, c, items.to_legacy)
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
        if k in ("Age", "Sheared", "Color", "Size", "Saddle", "CollarColor", "Variant", "Sitting", "Tame", "Temper",
                 "RabbitType"):
            e[k] = v
        elif k == "Type" and name in ("fox", "mooshroom"):
            e[k] = v
        elif k == "CatType" and name == "cat":
            if data_version >= JAVA_CAT_VARIANT_DV:
                i = int(v.py_data)
                e["variant"] = nbt.StringTag("minecraft:" + CAT_NAMES[i if 0 <= i < len(CAT_NAMES) else 0])
            else:
                e[k] = v
    if name in ("boat", "chest_boat") and "Type" in (c.get("extra") or {}):
        e["Type"] = c["extra"]["Type"]
    if name in ("villager", "zombie_villager") and data_version >= 1952:  # 1.14: VillagerData
        vd = villager_data(c.get("extra") or {})
        if vd is not None:
            e["VillagerData"] = vd
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
    _write_java_chest(e, c, lambda it: items.to_java_modern(it, data_version), data_version)
    _write_java_equipment(e, c, lambda it: items.to_java_modern(it, data_version), data_version)
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


def to_bedrock(c: dict, uid: int, owner_uid: Optional[int] = None, version=(1, 21, 0)) -> Optional[nbt.CompoundTag]:
    """owner_uid: UniqueID of the world's player - a single player world has only one possible owner;
    version: the Bedrock version written (block items carry its names)."""
    version = tuple(version)
    if c.get("skip"):
        return None
    name = c["name"]
    bname = TO_BEDROCK.get(name, name)
    if bname is None:
        return None
    renamed = newcontent.bedrock_entity_rename(bname, version)   # villager_v2 -> villager for Bedrock < 1.11...
    if renamed is not None:
        bname = renamed[0]
    elif not newcontent.bedrock_entity_exists(bname, version):
        return None                                           # a mob this Bedrock version does not have
    e = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:" + bname)})
    e["Pos"] = nbt.ListTag([nbt.FloatTag(v) for v in c["pos"]], 5)
    e["Rotation"] = nbt.ListTag([nbt.FloatTag(v) for v in c["rot"]], 5)
    e["Motion"] = nbt.ListTag([nbt.FloatTag(v) for v in c["motion"]], 5)
    e["UniqueID"] = nbt.LongTag(uid)
    e["definitions"] = nbt.ListTag([nbt.StringTag("+minecraft:" + bname)] +
                                   [nbt.StringTag(d) for d in (renamed[1] if renamed else ())], 8)
    e["Persistent"] = nbt.ByteTag(1)
    e["OnGround"] = nbt.ByteTag(1)
    e["Invulnerable"] = nbt.ByteTag(0)
    if c.get("custom_name"):
        e["CustomName"] = nbt.StringTag(c["custom_name"])
        e["CustomNameVisible"] = nbt.ByteTag(1 if c.get("name_visible") else 0)
    extra = c.get("extra") or {}
    baby = "Age" in extra and int(extra["Age"].py_data) < 0
    if baby:
        e["IsBaby"] = nbt.ByteTag(1)
    if bname == "villager_v2":
        pass                                       # adult / baby are the plain groups of write_bedrock_variants
    elif baby:
        e["definitions"].append(nbt.StringTag(f"+minecraft:{bname}_baby"))
    else:
        if bname in ("pig", "cow", "sheep", "chicken", "mooshroom", "rabbit", "wolf", "horse", "donkey", "mule", "llama",
                     "ocelot", "cat", "panda", "fox", "bee", "goat", "turtle", "polar_bear"):
            e["definitions"].append(nbt.StringTag(f"+minecraft:{bname}_adult"))
    if "Color" in extra and bname == "sheep":
        e["Color"] = nbt.ByteTag(int(extra["Color"].py_data))
    if "Sheared" in extra:
        e["Sheared"] = nbt.ByteTag(int(extra["Sheared"].py_data))
    if bname in ("boat", "chest_boat"):
        wood = str(extra["Type"].py_data) if "Type" in extra else "oak"
        e["Variant"] = nbt.IntTag(BOAT_WOODS.index(wood) if wood in BOAT_WOODS else 0)
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
    write_bedrock_variants(e, c, bname, version)
    if "health" in c and bname not in ("item", "xp_orb", "painting"):
        h = float(c["health"])
        e["Attributes"] = nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag("minecraft:health"), "Base": nbt.FloatTag(h),
                                                        "Current": nbt.FloatTag(h), "Max": nbt.FloatTag(max(h, 1.0)),
                                                        "DefaultMax": nbt.FloatTag(max(h, 1.0)), "DefaultMin": nbt.FloatTag(0),
                                                        "Min": nbt.FloatTag(0)})], 10)
    if bname == "item":
        it = items.to_bedrock(c["item"], version) if c.get("item") else None
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
    if c.get("items") and bname not in EQUIDS:
        e["Items"] = nbt.ListTag([t for t in (items.to_bedrock(it, version) for it in c["items"]) if t is not None], 10)
    eq = c.get("equip")
    if eq and (any(eq["hand"]) or any(eq["armor"])):
        def stack(it):
            t = items.to_bedrock(it, version) if it else None
            if t is None:
                return nbt.CompoundTag({"Name": nbt.StringTag(""), "Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0),
                                        "WasPickedUp": nbt.ByteTag(0)})
            t.pop("Slot", None)
            return t

        e["Mainhand"] = nbt.ListTag([stack(eq["hand"][0])], 10)
        e["Offhand"] = nbt.ListTag([stack(eq["hand"][1])], 10)
        e["Armor"] = nbt.ListTag([stack(it) for it in reversed(eq["armor"])], 10)  # head, chest, legs, feet
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
