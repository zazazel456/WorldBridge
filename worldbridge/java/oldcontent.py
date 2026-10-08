"""What the old Java versions (Alpha, Beta, 1.0 - 1.8) can load.

The hub carries the content of the source world: a Java 26.x or LCE world has items, mobs and
block entities that did not exist yet in Beta 1.2, and player / level.dat fields written with
NBT types that an old game cannot read.  An old game does not skip what it does not know:

* its NBT reader only knows the tag types 1-10 (11 = int array arrived with Anvil 1.2, 12 = long
  array with 1.12): one TAG_Int_Array anywhere in level.dat makes the whole file unreadable and
  the world slot shows up as empty;
* the typed getters cast (``getShort("Health")`` on a float tag throws);
* an item id without an Item class crashes the game as soon as the stack is used or drawn.

So for an old target everything is rebuilt from a whitelist, with the NBT types that version reads.
"""

from __future__ import annotations

import json
import math
import os
from collections import Counter
from typing import Dict, Iterable, Optional

from .. import blocks as blk
from .. import ids
from .. import nbt
from ..entities import HANGING, PAINTINGS, hanging_to_old


def rank(version: str) -> int:
    return blk.version_rank(version)


def _effect_known(eid: int, r: int) -> bool:
    """Whether a status effect id is registered by the game of rank ``r``: old games index
    Potion.potionTypes[id] without a null check, so an effect they lack crashes them when it ticks.
    1.0 - 1.3 have 1 - 19 without invisibility (14) and night vision (16), which came with
    wither (20) in 1.4.2; health boost, absorption and saturation (21 - 23) came in 1.6."""
    if r < rank("1.4"):
        return 1 <= eid <= 19 and eid not in (14, 16)
    return 1 <= eid <= (20 if r < rank("1.6") else 23)


def version_label(version: str) -> str:
    if version == "alpha":
        return "Alpha 1.2"
    if version.startswith("b"):
        return "Beta " + version[1:]
    return "Java " + version


# ------------------------------------------------------------------------------ items
def _item_intro() -> Dict[int, int]:
    t: Dict[int, int] = {}

    def s(nums: Iterable[int], v: str):
        for i in nums:
            t[i] = rank(v)

    s(list(range(256, 351)) + [2256, 2257], "alpha")
    s(range(351, 355), "b1.2")
    s([355, 356], "b1.3")
    s([357], "b1.4")
    s([358], "b1.6")
    s([359], "b1.7")
    s(range(360, 369), "b1.8")
    s(list(range(369, 383)) + list(range(2258, 2267)), "1.0")
    s([383], "1.1")
    s([384, 385], "1.2")
    s(range(386, 389), "1.3")
    s(list(range(389, 404)) + [2267], "1.4")
    s(range(404, 409), "1.5")
    s(range(417, 422), "1.6")
    s([422], "1.7")
    s(list(range(409, 417)) + [423, 424, 425] + list(range(427, 432)), "1.8")
    s([426] + list(range(432, 449)), "1.9")
    s([449, 450, 452], "1.11")
    s([453], "1.12")
    return t


ITEM_INTRO = _item_intro()


def item_known(num: int, r: int) -> bool:
    v = blk.INTRO.get(num) if num < 256 else ITEM_INTRO.get(num)
    return v is not None and v <= r


# --------------------------------------------------------------------------- entities
def _named_intro(table: Dict[str, Iterable[str]]) -> Dict[str, int]:
    return {name: rank(v) for v, names in table.items() for name in names}


ENTITY_INTRO = _named_intro({
    "alpha": ["Item", "Arrow", "Snowball", "Painting", "PrimedTnt", "FallingSand", "Minecart", "Boat", "Creeper",
              "Skeleton", "Spider", "Giant", "Zombie", "Slime", "Pig", "Sheep", "Cow", "Chicken", "Ghast",
              "PigZombie", "Mob", "Monster"],
    "b1.2": ["Squid"],
    "b1.4": ["Wolf"],
    "b1.8": ["XPOrb", "Enderman", "CaveSpider", "Silverfish"],
    "1.0": ["Blaze", "LavaSlime", "MushroomCow", "SnowMan", "EnderDragon", "Villager", "EnderCrystal",
            "ThrownPotion", "EyeOfEnderSignal", "SmallFireball", "Fireball", "ThrownEnderpearl"],
    "1.2": ["Ozelot", "VillagerGolem"],
    "1.3": ["ThrownExpBottle"],
    "1.4": ["WitherBoss", "Bat", "Witch", "ItemFrame", "WitherSkull", "FireworksRocketEntity"],
    "1.5": ["MinecartRideable", "MinecartChest", "MinecartFurnace", "MinecartTNT", "MinecartHopper",
            "MinecartSpawner"],
    "1.6": ["EntityHorse", "LeashKnot"],
    "1.7": ["MinecartCommandBlock"],
    "1.8": ["Rabbit", "Guardian", "Endermite", "ArmorStand"],
    "1.9": ["Shulker", "ShulkerBullet", "DragonFireball", "SpectralArrow", "TippedArrow", "AreaEffectCloud"],
    "1.10": ["PolarBear"],
    "1.11": ["Llama", "LlamaSpit", "EvocationIllager", "VindicationIllager", "Vex", "EvocationFangs"],
    "1.12": ["Parrot", "IllusionIllager"],
})

# before 1.5 every minecart was "Minecart" + Type
_OLD_MINECART = {"MinecartRideable": 0, "MinecartChest": 1, "MinecartFurnace": 2}

TILE_INTRO = _named_intro({
    "alpha": ["Furnace", "Sign", "MobSpawner", "Chest", "RecordPlayer"],
    "b1.2": ["Trap", "Music"],
    "b1.7": ["Piston"],
    "1.0": ["Cauldron", "EnchantTable", "Airportal"],
    "1.3": ["EnderChest"],
    "1.4": ["Beacon", "Skull", "Control"],
    "1.5": ["DLDetector", "Hopper", "Comparator", "Dropper"],
    "1.7": ["FlowerPot"],
    "1.8": ["Banner"],
    "1.9": ["EndGateway", "Structure"],
    "1.11": ["ShulkerBox"],
    "1.12": ["Bed"],
})

# NBT types an old game reads with a typed getter (a wrong type throws a ClassCastException)
_T = {"b": nbt.ByteTag, "s": nbt.ShortTag, "i": nbt.IntTag, "l": nbt.LongTag, "f": nbt.FloatTag,
      "d": nbt.DoubleTag, "S": nbt.StringTag}
_ENTITY_TYPES = {
    "FallDistance": "f", "Fire": "s", "Air": "s", "OnGround": "b", "Dimension": "i", "PortalCooldown": "i",
    "HurtTime": "s", "DeathTime": "s", "AttackTime": "s", "Age": "i", "InLove": "i", "Saddle": "b",
    "Sheared": "b", "Color": "b", "powered": "b", "Size": "i", "Angry": "b", "Sitting": "b", "Owner": "S",
    "Fuse": "b", "Tile": "b", "Type": "i", "Dir": "b", "Direction": "b", "Motive": "S", "TileX": "i",
    "TileY": "i", "TileZ": "i", "xTile": "s", "yTile": "s", "zTile": "s", "inTile": "b", "inData": "b",
    "shake": "b", "inGround": "b", "player": "b", "Anger": "s", "CanPickUpLoot": "b", "PersistenceRequired": "b",
    "Profession": "i", "Riches": "i", "carried": "s", "carriedData": "s", "Value": "s", "Invulnerable": "b",
    "Fuel": "s", "PushX": "d", "PushZ": "d",
}
# the item entity reads its "Health"/"Age" as shorts, mobs "Age" as int
_ITEM_ENTITY_TYPES = {"Health": "s", "Age": "s", "PickupDelay": "s"}
_TILE_TYPES = {
    "BurnTime": "s", "CookTime": "s", "Delay": "s", "note": "b", "Record": "i", "blockId": "i", "blockData": "i",
    "facing": "i", "progress": "f", "extending": "b", "MinSpawnDelay": "s", "MaxSpawnDelay": "s",
    "SpawnCount": "s", "BrewTime": "s", "SkullType": "b", "Rot": "b", "Levels": "i", "Primary": "i",
    "Secondary": "i", "Item": "i", "Data": "i", "OutputSignal": "i",
}


def _num(tag) -> Optional[float]:
    v = getattr(tag, "py_data", None)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _coerce(tag, code: str):
    cls = _T[code]
    if isinstance(tag, cls):
        return tag
    if code == "S":
        return None
    v = _num(tag)
    if v is None:
        return None
    if code in "fd":
        return cls(float(v))
    v = int(round(v)) if isinstance(v, float) else int(v)
    bits = {"b": 8, "s": 16, "i": 32, "l": 64}[code]
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    return cls(max(lo, min(hi, v)))


def _coerce_fields(c: nbt.CompoundTag, types: Dict[str, str]):
    for key, code in types.items():
        if key in c:
            t = _coerce(c[key], code)
            if t is None:
                del c[key]
            else:
                c[key] = t


def _num_list(lst, code: str, n: int, default=0.0) -> nbt.ListTag:
    vals = []
    if isinstance(lst, nbt.ListTag):
        vals = [_num(x) for x in lst]
    vals = [float(v) if v is not None and math.isfinite(v) else default for v in vals[:n]]
    vals += [default] * (n - len(vals))
    return nbt.ListTag([_T[code](v) for v in vals], 6 if code == "d" else 5)


def strip_new_types(tag, keep_int_array: bool = False, keep_long_array: bool = False):
    """Recursively drop the NBT types an old reader does not know (in place, returns the tag)."""
    bad = set()
    if not keep_int_array:
        bad.add(nbt.IntArrayTag)
    if not keep_long_array:
        bad.add(nbt.LongArrayTag)
    bad_t = tuple(bad)

    def walk(t):
        if isinstance(t, nbt.CompoundTag):
            for k in list(t.keys()):
                v = t[k]
                if bad_t and isinstance(v, bad_t):
                    del t[k]
                    continue
                if isinstance(v, nbt.ListTag):
                    t[k] = walk_list(v)
                else:
                    walk(v)
        return t

    def walk_list(lst: nbt.ListTag) -> nbt.ListTag:
        items = [x for x in lst if not (bad_t and isinstance(x, bad_t))]
        if len(items) == len(lst) and (len(lst) or lst.list_data_type not in (11, 12)):
            for x in lst:
                walk(x)
            return lst
        out = nbt.ListTag([], 10 if not items else lst.list_data_type)
        for x in items:
            out.append(walk_list(x) if isinstance(x, nbt.ListTag) else walk(x))
        return out

    if bad_t:
        walk(tag)
    return tag


# ------------------------------------------------------------------------------ filter
class OldContent:
    """Filters the content of chunks / players / level.dat for the Java version ``version``."""

    def __init__(self, version: str):
        self.version = version
        self.r = rank(version)
        self.label = version_label(version)
        self.tile_ids = frozenset(k for k, v in TILE_INTRO.items() if v <= self.r)
        self.dropped_items = 0
        self.dropped_entities = 0
        self.dropped_tiles = 0
        self.dropped_tile_ids: Counter = Counter()     # which ones (per id) among them are known not to exist / not to be known

    # anvil (1.2+) reads int arrays, 1.12 long arrays
    def strip(self, tag):
        return strip_new_types(tag, keep_int_array=self.r >= rank("1.2"), keep_long_array=self.r >= rank("1.12"))

    # ------------------------------------------------------------------ items
    def item(self, it) -> Optional[nbt.CompoundTag]:
        """A legacy (numeric id) item, or None when the version does not have it."""
        if not isinstance(it, nbt.CompoundTag) or not len(it):
            return None
        num = _num(nbt.get_tag(it, "id"))
        if num is None or not item_known(int(num), self.r):
            self.dropped_items += 1
            return None
        count = _num(nbt.get_tag(it, "Count"))
        count = 1 if count is None else int(count)
        if count <= 0:
            return None
        dmg = _num(nbt.get_tag(it, "Damage")) or 0
        out = nbt.CompoundTag({"id": nbt.ShortTag(int(num)), "Count": nbt.ByteTag(max(1, min(127, count))),
                               "Damage": nbt.ShortTag(max(-32768, min(32767, int(dmg))))})
        if "Slot" in it and _num(it["Slot"]) is not None:
            out["Slot"] = nbt.ByteTag(max(-128, min(127, int(_num(it["Slot"])))))
        if self.r >= rank("1.0") and isinstance(nbt.get_tag(it, "tag"), nbt.CompoundTag):
            out["tag"] = self.strip(nbt.copy(it["tag"]))
        return out

    def items(self, lst, slots: Optional[range] = None) -> nbt.ListTag:
        out = nbt.ListTag([], 10)
        if not isinstance(lst, nbt.ListTag):
            return out
        for it in lst:
            li = self.item(it)
            if li is None:
                continue
            if slots is not None and ("Slot" not in li or int(li["Slot"].py_data) & 0xFF not in slots):
                continue
            out.append(li)
        return out

    # --------------------------------------------------------------- entities
    def entity(self, e: nbt.CompoundTag) -> Optional[nbt.CompoundTag]:
        eid = str(nbt.get(e, "id", "") or "")
        if eid in _OLD_MINECART and self.r < rank("1.5"):
            e = nbt.copy(e)
            e["id"] = nbt.StringTag("Minecart")
            e["Type"] = nbt.IntTag(_OLD_MINECART[eid])
            eid = "Minecart"
        v = ENTITY_INTRO.get(eid)
        if v is None or v > self.r:
            self.dropped_entities += 1
            return None
        if eid == "Minecart" and self.r < rank("1.5") and int(_num(nbt.get_tag(e, "Type")) or 0) not in (0, 1, 2):
            self.dropped_entities += 1
            return None
        e = nbt.copy(e)
        e["Pos"] = _num_list(nbt.get_tag(e, "Pos"), "d", 3)
        e["Motion"] = _num_list(nbt.get_tag(e, "Motion"), "d", 3)
        e["Rotation"] = _num_list(nbt.get_tag(e, "Rotation"), "f", 2)
        if eid in HANGING and self.r < rank("1.8"):
            hanging_to_old(e)  # before 1.8 TileX/Y/Z is the wall block
        if eid == "Painting":
            mot = str(nbt.get(e, "Motive", "") or "")
            if mot not in PAINTINGS or (mot == "Wither" and self.r < rank("1.4")):
                e["Motive"] = nbt.StringTag("Kebab")
        if "FallDistance" not in e and "fall_distance" in e:
            e["FallDistance"] = e["fall_distance"]
        _coerce_fields(e, _ENTITY_TYPES)
        if eid == "Item":
            _coerce_fields(e, _ITEM_ENTITY_TYPES)
            it = self.item(nbt.get_tag(e, "Item"))
            if it is None:
                self.dropped_entities += 1
                return None
            it.pop("Slot", None)
            e["Item"] = it
        else:
            self._health(e)
        for key in ("Items", "Inventory"):
            if key in e:
                e[key] = self.items(e[key])
        if "Equipment" in e:
            if self.r >= rank("1.0"):
                eq = nbt.ListTag([], 10)
                for it in e["Equipment"]:
                    li = self.item(it)
                    eq.append(li if li is not None else nbt.CompoundTag())
                e["Equipment"] = eq
            else:
                del e["Equipment"]
        if isinstance(nbt.get_tag(e, "Riding"), nbt.CompoundTag):
            rid = self.entity(e["Riding"])
            if rid is None:
                del e["Riding"]
            else:
                e["Riding"] = rid
        return self.strip(e)

    def _health(self, e: nbt.CompoundTag):
        hp = _num(nbt.get_tag(e, "HealF"))
        if hp is None:
            hp = _num(nbt.get_tag(e, "Health"))
        if hp is None:
            return
        if self.r >= rank("1.9"):
            e["Health"] = nbt.FloatTag(float(hp))
            e.pop("HealF", None)
            return
        e["Health"] = nbt.ShortTag(max(0, min(32767, int(math.ceil(hp)))))
        if self.r >= rank("1.6"):
            e["HealF"] = nbt.FloatTag(float(hp))
        else:
            e.pop("HealF", None)

    # ----------------------------------------------------------- tile entities
    def tile(self, t: nbt.CompoundTag) -> Optional[nbt.CompoundTag]:
        tid = str(nbt.get(t, "id", "") or "")
        v = TILE_INTRO.get(tid)
        if v is None or v > self.r:
            return None
        t = nbt.copy(t)
        for k in ("x", "y", "z"):
            c = _coerce(nbt.get_tag(t, k), "i") if k in t else None
            if c is None:
                return None
            t[k] = c
        if tid == "FlowerPot" and isinstance(nbt.get_tag(t, "Item"), nbt.StringTag):
            num = ids.item_id_from_name(nbt.get(t, "Item"))  # 1.7 reads the plant as an int id
            if num is not None:
                t["Item"] = nbt.IntTag(num)
        _coerce_fields(t, _TILE_TYPES)
        if "Items" in t:
            t["Items"] = self.items(t["Items"])
        if tid == "MobSpawner":
            self._spawner(t)
        elif tid == "RecordPlayer":
            rec = int(_num(nbt.get_tag(t, "Record")) or 0)
            if rec and not item_known(rec, self.r):
                t["Record"] = nbt.IntTag(0)
                t.pop("RecordItem", None)
            if "RecordItem" in t:
                ri = self.item(t["RecordItem"])
                if ri is None or self.r < rank("1.2"):
                    t.pop("RecordItem")
                else:
                    t["RecordItem"] = ri
        elif tid == "Sign" and self.r < rank("1.8"):
            for i in range(1, 5):
                k = f"Text{i}"
                t[k] = nbt.StringTag(plain_text(str(nbt.get(t, k, "") or ""))[:15])
        return self.strip(t)

    def _spawner(self, t: nbt.CompoundTag):
        eid = str(nbt.get(t, "EntityId", "") or "")
        if not eid:
            sd = nbt.get_tag(t, "SpawnData")
            if isinstance(sd, nbt.CompoundTag):
                eid = ids.entity_to_old(str(nbt.get(sd, "id", "") or ""))[0] or ""
        eid = ids.entity_to_old(eid)[0] or ""
        v = ENTITY_INTRO.get(eid)
        if v is None or v > self.r or eid in ("Item", "Painting", "Mob", "Monster"):
            eid = "Pig"
        t["EntityId"] = nbt.StringTag(eid)
        if "Delay" not in t:
            t["Delay"] = nbt.ShortTag(20)
        if self.r < rank("1.3"):
            for k in ("SpawnData", "SpawnPotentials"):
                t.pop(k, None)

    # ----------------------------------------------------------------- player
    def player(self, p: nbt.CompoundTag) -> nbt.CompoundTag:
        """A player compound with only the fields (and NBT types) this version reads."""
        r = self.r
        out = nbt.CompoundTag()
        out["Pos"] = _num_list(nbt.get_tag(p, "Pos"), "d", 3)
        out["Motion"] = _num_list(nbt.get_tag(p, "Motion"), "d", 3)
        out["Rotation"] = _num_list(nbt.get_tag(p, "Rotation"), "f", 2)
        src_types = {"FallDistance": "f", "Fire": "s", "Air": "s", "OnGround": "b", "HurtTime": "s",
                     "DeathTime": "s", "AttackTime": "s", "Dimension": "i"}
        if "FallDistance" not in p and "fall_distance" in p:
            out["FallDistance"] = _coerce(p["fall_distance"], "f")
        for k, code in src_types.items():
            if k in p:
                c = _coerce(p[k], code)
                if c is not None:
                    out[k] = c
        for k, d in (("FallDistance", 0.0), ("Fire", -20), ("Air", 300), ("OnGround", 1), ("HurtTime", 0),
                     ("DeathTime", 0), ("AttackTime", 0), ("Dimension", 0)):
            if k not in out:
                out[k] = _T[src_types[k]](d)
        if int(out["Dimension"].py_data) not in (-1, 0, 1) or (r < rank("1.0") and int(out["Dimension"].py_data) == 1):
            out["Dimension"] = nbt.IntTag(0)
        if r < rank("b1.2") and int(out["Dimension"].py_data) != 0:
            out["Dimension"] = nbt.IntTag(0)
        hp = _num(nbt.get_tag(p, "HealF"))
        if hp is None:
            hp = _num(nbt.get_tag(p, "Health"))
        hp = 20.0 if hp is None or hp <= 0 else float(hp)
        out["Health"] = nbt.ShortTag(max(1, min(20, int(math.ceil(hp)))))
        if r >= rank("1.6"):
            out["HealF"] = nbt.FloatTag(hp)
        # main inventory 0-35, armour 100-103 (the off-hand slot -106 did not exist)
        out["Inventory"] = self.items(nbt.get_tag(p, "Inventory"), slots=_PLAYER_SLOTS)
        if r >= rank("b1.3"):
            out["Sleeping"] = nbt.ByteTag(0)
            out["SleepTimer"] = nbt.ShortTag(0)
            spawn = _player_spawn(p)
            if spawn is not None:
                for k, v in zip(("SpawnX", "SpawnY", "SpawnZ"), spawn):
                    out[k] = nbt.IntTag(v)
        if r >= rank("b1.8"):
            for k, code, d in (("foodLevel", "i", 20), ("foodTickTimer", "i", 0), ("foodSaturationLevel", "f", 5.0),
                               ("foodExhaustionLevel", "f", 0.0), ("XpP", "f", 0.0), ("XpLevel", "i", 0),
                               ("XpTotal", "i", 0), ("playerGameType", "i", 0)):
                c = _coerce(p[k], code) if k in p else None
                out[k] = c if c is not None else _T[code](d)
            if int(out["playerGameType"].py_data) not in (0, 1) and r < rank("1.3"):
                out["playerGameType"] = nbt.IntTag(0)
            if int(out["playerGameType"].py_data) not in (0, 1, 2) and r < rank("1.8"):
                out["playerGameType"] = nbt.IntTag(0)
        if r >= rank("1.0"):
            ab = nbt.get_tag(p, "abilities")
            ab_out = nbt.CompoundTag()
            for k in ("invulnerable", "flying", "mayfly", "instabuild", "mayBuild"):
                c = _coerce(ab[k], "b") if isinstance(ab, nbt.CompoundTag) and k in ab else None
                ab_out[k] = c if c is not None else nbt.ByteTag(1 if k == "mayBuild" else 0)
            if r >= rank("1.2"):
                for k, d in (("flySpeed", 0.05), ("walkSpeed", 0.1)):
                    c = _coerce(ab[k], "f") if isinstance(ab, nbt.CompoundTag) and k in ab else None
                    ab_out[k] = c if c is not None else nbt.FloatTag(d)
            out["abilities"] = ab_out
            eff = nbt.get_tag(p, "ActiveEffects")
            if isinstance(eff, nbt.ListTag) and len(eff):
                lst = nbt.ListTag([], 10)
                for e in eff:
                    if isinstance(e, nbt.CompoundTag) and _num(nbt.get_tag(e, "Id")) is not None:
                        c = nbt.CompoundTag({"Id": _coerce(e["Id"], "b"),
                                             "Amplifier": _coerce(nbt.get_tag(e, "Amplifier", nbt.ByteTag(0)), "b") or nbt.ByteTag(0),
                                             "Duration": _coerce(nbt.get_tag(e, "Duration", nbt.IntTag(0)), "i") or nbt.IntTag(0)})
                        if _effect_known(int(c["Id"].py_data), r):
                            lst.append(c)
                if len(lst):
                    out["ActiveEffects"] = lst
        if r >= rank("1.3"):
            out["EnderItems"] = self.items(nbt.get_tag(p, "EnderItems"), slots=range(0, 27))
            out["SelectedItemSlot"] = _coerce(nbt.get_tag(p, "SelectedItemSlot", nbt.IntTag(0)), "i") or nbt.IntTag(0)
        return out

    # --------------------------------------------------------------- level.dat
    def level(self, src: nbt.CompoundTag, name: str, player: Optional[nbt.CompoundTag],
              size_on_disk: int, y_offset: int = 0) -> nbt.CompoundTag:
        r = self.r
        out = nbt.CompoundTag()
        seed = _num(nbt.get_tag(src, "RandomSeed"))
        if seed is None:
            wgs = nbt.get_tag(src, "WorldGenSettings")
            seed = _num(nbt.get_tag(wgs, "seed")) if isinstance(wgs, nbt.CompoundTag) else None
        out["RandomSeed"] = nbt.LongTag(int(seed or 0))
        sx, sy, sz = level_spawn(src)
        for k, v in zip(("SpawnX", "SpawnY", "SpawnZ"), (sx, max(1, min(255 if r >= rank("1.2") else 127, sy + y_offset)), sz)):
            out[k] = nbt.IntTag(v)
        tm = int(_num(nbt.get_tag(src, "Time")) or 0)
        out["Time"] = nbt.LongTag(tm)
        out["LastPlayed"] = _coerce(nbt.get_tag(src, "LastPlayed", nbt.LongTag(0)), "l") or nbt.LongTag(0)
        out["SizeOnDisk"] = nbt.LongTag(int(size_on_disk))
        if r >= rank("b1.3"):
            out["LevelName"] = nbt.StringTag(name)
            out["version"] = nbt.IntTag(19133 if r >= rank("1.2") else 19132)
            for k, code, d in (("rainTime", "i", 0), ("raining", "b", 0), ("thunderTime", "i", 0),
                               ("thundering", "b", 0)):
                c = _coerce(src[k], code) if k in src else None
                out[k] = c if c is not None else _T[code](d)
        if r >= rank("b1.8"):
            gt = int(_num(nbt.get_tag(src, "GameType")) or 0)
            out["GameType"] = nbt.IntTag(gt if gt in ((0, 1) if r < rank("1.3") else (0, 1, 2, 3) if r >= rank("1.8") else (0, 1, 2)) else 0)
            out["MapFeatures"] = _coerce(nbt.get_tag(src, "MapFeatures", nbt.ByteTag(1)), "b") or nbt.ByteTag(1)
        if r >= rank("1.0"):
            out["hardcore"] = _coerce(nbt.get_tag(src, "hardcore", nbt.ByteTag(0)), "b") or nbt.ByteTag(0)
        if r >= rank("1.1"):
            gen = str(nbt.get(src, "generatorName", "default") or "default")
            ok = ("default", "flat") if r < rank("1.3") else ("default", "flat", "largeBiomes") if r < rank("1.7") \
                else ("default", "flat", "largeBiomes", "amplified")
            if gen.lower() == "largebiomes":
                gen = "largeBiomes"
            out["generatorName"] = nbt.StringTag(gen if gen in ok else "default")
            out["generatorVersion"] = nbt.IntTag(1 if gen == "default" else 0)
        if r >= rank("1.3"):
            out["allowCommands"] = _coerce(nbt.get_tag(src, "allowCommands", nbt.ByteTag(0)), "b") or nbt.ByteTag(0)
            out["initialized"] = nbt.ByteTag(1)
            dt = _num(nbt.get_tag(src, "DayTime"))
            out["DayTime"] = nbt.LongTag(int(dt) if dt is not None else tm % 24000)
            opts = nbt.get_tag(src, "generatorOptions")
            out["generatorOptions"] = opts if isinstance(opts, nbt.StringTag) and out["generatorName"].py_data == "flat" \
                else nbt.StringTag("")
        if r >= rank("1.4"):
            gr = nbt.get_tag(src, "GameRules")
            if isinstance(gr, nbt.CompoundTag):
                rules = nbt.CompoundTag({k: v for k, v in gr.items() if isinstance(v, nbt.StringTag)})
                if len(rules):
                    out["GameRules"] = rules
        if player is not None:
            out["Player"] = player
        return out


_PLAYER_SLOTS = set(range(0, 36)) | set(range(100, 104))


def _player_spawn(p: nbt.CompoundTag):
    if all(isinstance(nbt.get_tag(p, k), nbt.IntTag) for k in ("SpawnX", "SpawnY", "SpawnZ")):
        return tuple(int(p[k].py_data) for k in ("SpawnX", "SpawnY", "SpawnZ"))
    rs = nbt.get_tag(p, "respawn")
    if isinstance(rs, nbt.CompoundTag):
        dim = str(nbt.get(rs, "dimension", "minecraft:overworld") or "")
        pos = nbt.get_tag(rs, "pos")
        if dim.endswith("overworld") and pos is not None and len(pos) == 3:
            return tuple(int(v) for v in pos)
    return None


def level_spawn(src: nbt.CompoundTag):
    """World spawn from an old (SpawnX/Y/Z) or a Java 1.21.9+ (spawn: {pos}) level.dat."""
    if all(_num(nbt.get_tag(src, k)) is not None for k in ("SpawnX", "SpawnY", "SpawnZ")):
        return tuple(int(_num(src[k])) for k in ("SpawnX", "SpawnY", "SpawnZ"))
    sp = nbt.get_tag(src, "spawn")
    if isinstance(sp, nbt.CompoundTag):
        pos = nbt.get_tag(sp, "pos")
        if pos is not None and len(pos) == 3:
            return tuple(int(v) for v in pos)
    return 0, 64, 0


def plain_text(s: str) -> str:
    """Sign text: a JSON text component (Java 1.8+) -> its plain text."""
    t = s.strip()
    if not t or t[0] not in '{["':
        return s

    def flat(c) -> str:
        if isinstance(c, str):
            return c
        if isinstance(c, list):
            return "".join(flat(x) for x in c)
        if isinstance(c, dict):
            return flat(c.get("text", "")) + "".join(flat(x) for x in c.get("extra", []) or [])
        return ""

    try:
        return flat(json.loads(t))
    except (ValueError, TypeError):
        return s


def size_on_disk(folder: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total
