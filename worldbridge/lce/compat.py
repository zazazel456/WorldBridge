"""What a Legacy Console Edition game knows besides its blocks: items, enchantments and entities,
and the player file as the game itself writes it.

The hub speaks Java 1.12's numeric ids; an LCE version knows fewer.  neoLegacy (the Windows64
target) is checked against its own source (Minecraft.World: Item.cpp, Tile.cpp, Enchantment.cpp,
EntityIO.cpp): it has the items of 1.8 plus beetroots, registers the banner item under the banner
block's id (176, not 425), the fishing enchantments at 64 / 65 (Java: 62 / 61) and Mending, and none
of the entities added after 1.10.  An item, enchantment or entity the game does not have is changed
to the closest one it has, or left out (counted in the conversion's report).

A player file is rebuilt with the fields and tag types the game writes (a neoLegacy players/<XUID>.dat):
the player of a Java 1.13+ world carries much more (Paper / Bukkit data, brain, recipe book, string
dimensions, modern attributes) and its armour in "equipment" instead of the inventory."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Dict, FrozenSet, Optional, Tuple

import numpy as np

from .. import blocks as blk
from .. import ids, nbt
from .. import items as _items

RECORDS = frozenset(range(2256, 2268))
# Java item ids by the version that added them (above 431 all are 1.9+)
_ITEMS_18 = frozenset(range(256, 432)) | RECORDS
_ITEMS_19 = _ITEMS_18 | frozenset(range(432, 449))
_ITEMS_112 = _ITEMS_19 | frozenset(range(449, 454))
# neoLegacy (Item.cpp): no command block minecart (422), banner item (425, see ITEM_MAP) or end
# crystal (426); beetroots (434 - 436) backported
NEOLEGACY_ITEMS = (_ITEMS_18 - {422, 425, 426}) | {434, 435, 436, 176}

_ENCH_18 = frozenset(list(range(0, 9)) + list(range(16, 22)) + list(range(32, 36)) + list(range(48, 52)) + [61, 62])
_ENCH_19 = _ENCH_18 | {9, 70}
_ENCH_112 = _ENCH_19 | {10, 22, 71}
NEOLEGACY_ENCH = frozenset(list(range(0, 10)) + list(range(16, 22)) + list(range(32, 36)) + list(range(48, 52))
                           + [64, 65, 70])

# neoLegacy's EntityIO.cpp registrations (the ids it loads; anything else is skipped by the game)
NEOLEGACY_ENTITIES = frozenset((
    "ArmorStand", "Arrow", "Bat", "Blaze", "Boat", "CaveSpider", "Chicken", "Cow", "Creeper", "DragonFireball",
    "ElderGuardian", "EnderCrystal", "EnderDragon", "Enderman", "Endermite", "EntityHorse", "EyeOfEnderSignal",
    "FallingSand", "Fireball", "FireworksRocketEntity", "Ghast", "Giant", "Guardian", "Item", "ItemFrame",
    "LavaSlime", "LeashKnot", "MinecartChest", "MinecartFurnace", "MinecartHopper", "MinecartRideable",
    "MinecartSpawner", "MinecartTNT", "Mob", "Monster", "MushroomCow", "Ozelot", "Painting", "Pig", "PigZombie",
    "PolarBear", "PrimedTnt", "Rabbit", "Sheep", "Silverfish", "Skeleton", "Slime", "SmallFireball", "SnowMan",
    "Snowball", "Spider", "Squid", "ThrownEnderpearl", "ThrownExpBottle", "ThrownPotion", "Villager",
    "VillagerGolem", "Witch", "WitherBoss", "WitherSkull", "Wolf", "XPOrb", "Zombie",
))

# neoLegacy's attribute ids (SharedMonsterAttributes): 0 max health, 1 follow range, 2 knockback resistance,
# 3 movement speed, 4 attack damage, 5 horse jump strength, 6 zombie reinforcements.  An entity only has the
# attributes its registerAttributes() registers (LivingEntity 0, 2, 3; Mob adds 1; Monster adds 4; the horse 5;
# the zombie 6; read off the game's executable, checked against the save the game writes): a saved one the
# class lacks makes the game log "Ignoring unknown attribute '4'".  The wolf lacks the attack damage.
_ATTR_MONSTERS = frozenset((
    "Blaze", "CaveSpider", "Creeper", "ElderGuardian", "Enderman", "Endermite", "Giant", "Guardian", "Monster",
    "PigZombie", "PolarBear", "Silverfish", "Skeleton", "Spider", "Witch", "WitherBoss", "Zombie",
))
_ATTR_BASE = frozenset((0, 1, 2, 3))


def neolegacy_attribute_ids(eid: str) -> FrozenSet[int]:
    """The attribute ids neoLegacy's entity ``eid`` registers."""
    if eid == "ArmorStand":
        return frozenset((0, 2, 3))
    ids = set(_ATTR_BASE)
    if eid in _ATTR_MONSTERS:
        ids.add(4)
    if eid in ("PigZombie", "Zombie"):
        ids.add(6)
    if eid == "EntityHorse":
        ids.add(5)
    return frozenset(ids)


# neoLegacy's TileEntity::staticCtor registrations (read off the executable): no Bed (the colour is not kept by that
# game), ShulkerBox, EndGateway or Structure; whatever else is saved is skipped by the game when it loads the chunk
NEOLEGACY_TILES = frozenset((
    "Airportal", "Banner", "Beacon", "Cauldron", "Chest", "Comparator", "Control", "DLDetector", "Dropper",
    "EnchantTable", "EnderChest", "FlowerPot", "Furnace", "Hopper", "MobSpawner", "Music", "Piston", "RecordPlayer",
    "Sign", "Skull", "Trap",
))

_SPLASH = 0x4000


def _splash(it):
    it["Damage"] = nbt.ShortTag(int(nbt.get(it, "Damage", 0) or 0) | _SPLASH)


# item replacements of 1.9+ items by the closest older one: id -> (new id, fix-up)
_SUBSTITUTES: Dict[int, Tuple[int, Optional[Callable]]] = {
    439: (262, None), 440: (262, None),                          # spectral / tipped arrow -> arrow
    438: (373, _splash), 441: (373, _splash),                    # splash / lingering potion
    444: (333, None), 445: (333, None), 446: (333, None), 447: (333, None), 448: (333, None),  # boats
    422: (328, None),                                            # command block minecart -> minecart
}


@dataclass
class Compat:
    """The ids a target LCE game knows (None: no limit)."""

    blocks: Optional[FrozenSet[int]]
    items: Optional[FrozenSet[int]]
    enchantments: Optional[FrozenSet[int]]
    entities: Optional[FrozenSet[str]] = None
    # the attribute ids an entity of the game has (None: the saved lists are kept as they are)
    attribute_ids: Optional[Callable[[str], FrozenSet[int]]] = None
    tiles: Optional[FrozenSet[str]] = None          # the block entity ids the game registers (None: no limit)
    item_map: Dict[int, int] = field(default_factory=dict)
    ench_map: Dict[int, int] = field(default_factory=dict)
    string_items: bool = False          # item ids as registry names ("minecraft:egg"), as the console saves have them
    dropped: Dict[str, int] = field(default_factory=dict)

    # ------------------------------------------------------------------ items
    def item(self, it) -> Optional[nbt.CompoundTag]:
        """The item as the game knows it (a new tag), or None when it has nothing like it."""
        if not isinstance(it, nbt.CompoundTag) or "id" not in it:
            return None
        iid = nbt.get(it, "id")
        if not isinstance(iid, int):
            self._drop(f"item {iid}")
            return None
        it = nbt.copy(it)
        if iid in self.item_map:
            iid = self.item_map[iid]
        elif self.items is not None and iid >= 256 and iid not in self.items and iid in _SUBSTITUTES:
            iid, fix = _SUBSTITUTES[iid]
            if fix is not None:
                fix(it)
        if iid < 256:
            if iid <= 0:
                return None
            if self.blocks is not None and iid not in self.blocks:
                dmg = int(nbt.get(it, "Damage", 0) or 0)
                b, d, _n = blk.downgrade(np.array([[[iid]]], np.uint16), np.array([[[dmg & 15]]], np.uint8),
                                         self.blocks)
                if int(b[0, 0, 0]) == 0:
                    self._drop(f"item {iid}")
                    return None
                iid = int(b[0, 0, 0])
                it["Damage"] = nbt.ShortTag(int(d[0, 0, 0]))
        elif self.items is not None and iid not in self.items:
            self._drop(f"item {iid}")
            return None
        it["id"] = nbt.ShortTag(iid)
        if self.string_items:
            it = _items.named_item(it)          # after the filtering above, which works on the number
        tag = nbt.get_tag(it, "tag")
        if isinstance(tag, nbt.CompoundTag):
            for key in ("ench", "StoredEnchantments"):
                lst = nbt.get_tag(tag, key)
                if lst is not None:
                    tag[key] = self._enchantments(lst)
            bet = nbt.get_tag(tag, "BlockEntityTag")
            if isinstance(bet, nbt.CompoundTag):
                self.holder(bet)
        return it

    def _enchantments(self, lst) -> nbt.ListTag:
        out = nbt.ListTag([], 10)
        for e in lst:
            eid = nbt.get(e, "id")
            if not isinstance(eid, int):
                continue
            eid = self.ench_map.get(eid, eid)
            if self.enchantments is not None and eid not in self.enchantments:
                self._drop(f"enchantment {eid}")
                continue
            e = nbt.copy(e)
            e["id"] = nbt.ShortTag(eid)
            out.append(e)
        return out

    def items_list(self, lst) -> nbt.ListTag:
        out = nbt.ListTag([], 10)
        for it in lst or []:
            fixed = self.item(it)
            if fixed is not None:
                out.append(fixed)
        return out

    def _drop(self, what: str):
        self.dropped[what] = self.dropped.get(what, 0) + 1

    # ------------------------------------------------------------------ holders of items
    def holder(self, t: nbt.CompoundTag) -> nbt.CompoundTag:
        """Fixes the items an entity / block entity / player holds, in place."""
        for key in ("Items", "Inventory", "EnderItems"):
            lst = nbt.get_tag(t, key)
            if isinstance(lst, nbt.ListTag):
                t[key] = self.items_list(lst)
        for key in ("Equipment", "ArmorStandEquipment", "ArmorItems", "HandItems"):
            lst = nbt.get_tag(t, key)
            if isinstance(lst, nbt.ListTag) and len(lst):
                fixed = nbt.ListTag([], 10)
                for it in lst:
                    f = self.item(it) if len(it) else None
                    fixed.append(f if f is not None else nbt.CompoundTag())
                t[key] = fixed
        for key in ("Item", "RecordItem", "ArmorItem", "SaddleItem"):
            it = nbt.get_tag(t, key)
            if isinstance(it, nbt.CompoundTag):
                f = self.item(it)
                if f is None:
                    del t[key]
                else:
                    t[key] = f
        rec = nbt.get(t, "Record")
        if isinstance(rec, int) and rec and self.items is not None and rec not in self.items:
            del t["Record"]
        offers = nbt.get_tag(t, "Offers")
        if isinstance(offers, nbt.CompoundTag):
            recipes = nbt.ListTag([], 10)
            for r in nbt.get_tag(offers, "Recipes") or []:
                r = nbt.copy(r)
                ok = True
                for key in ("buy", "buyB", "sell"):
                    if key in r:
                        f = self.item(r[key])
                        if f is None:
                            ok = False
                            break
                        r[key] = f
                if ok:
                    recipes.append(r)
            offers["Recipes"] = recipes
        return t

    def attributes(self, e: nbt.CompoundTag) -> None:
        """Takes out of the entity's saved ``Attributes`` the ones its class in the game does not have."""
        lst = nbt.get_tag(e, "Attributes")
        if self.attribute_ids is None or not isinstance(lst, nbt.ListTag):
            return
        known = self.attribute_ids(nbt.get(e, "id", ""))
        kept = nbt.ListTag([a for a in lst if not isinstance(nbt.get(a, "ID"), int) or nbt.get(a, "ID") in known], 10)
        if len(kept) != len(lst):
            e["Attributes"] = kept

    def entity(self, e: nbt.CompoundTag) -> Optional[nbt.CompoundTag]:
        """The entity for the game (None when it has no such entity, or it is an item it lacks)."""
        eid = nbt.get(e, "id", "")
        if self.entities is not None and eid not in self.entities:
            self._drop(f"entity {eid}")
            return None
        had_item = isinstance(nbt.get_tag(e, "Item"), nbt.CompoundTag)
        self.holder(e)
        self.attributes(e)
        if had_item and eid == "Item" and "Item" not in e:
            return None                                   # a dropped item the game does not have
        riding = nbt.get_tag(e, "Riding")
        if isinstance(riding, nbt.CompoundTag):
            r = self.entity(riding)
            if r is None:
                del e["Riding"]
            else:
                e["Riding"] = r
        return e


def compat_for(profile_key: str, platform: str, blocks: Optional[FrozenSet[int]]) -> Compat:
    if platform == "win64":            # neoLegacy, checked against its source
        return Compat(blocks, NEOLEGACY_ITEMS, NEOLEGACY_ENCH, NEOLEGACY_ENTITIES, neolegacy_attribute_ids,
                      NEOLEGACY_TILES, item_map={425: 176}, ench_map={61: 65, 62: 64})
    allowed = {"tu31": _ITEMS_18, "tu46": _ITEMS_19}.get(profile_key, _ITEMS_112)
    ench = {"tu31": _ENCH_18, "tu46": _ENCH_19}.get(profile_key, _ENCH_112)
    # the console saves (X360 TU31+, Wii U v112+, PS3 / PS4 / Vita) name their items; only the oldest ones
    # (X360 TU12 / TU19, Wii U v1) and neoLegacy use numbers
    return Compat(blocks, allowed, ench, string_items=True)


# ============================================================ namespaced ids (TU54+)

_HORSE_TYPES = {0: "Horse", 1: "Donkey", 2: "Mule", 3: "ZombieHorse", 4: "SkeletonHorse"}
_ENDER_CHEST = "minecraft:ender_Chest"        # as the game itself spells it (capital C)


def _modern_name(old: str, e: Optional[nbt.CompoundTag] = None) -> str:
    """The registry name ("minecraft:..." of Java 1.11 - 1.12) of an entity of the pre-1.11 id ``old``;
    the 1.11 splits (EntityHorseSplitFix, EntitySkeletonSplitFix, EntityZombieSplitFix, the elder
    guardian) are read from the discriminator tags of ``e``, which are then removed."""
    if e is not None:
        if old == "EntityHorse":
            old = _HORSE_TYPES.get(_i(nbt.get(e, "Type", 0)), "Horse")
            e.pop("Type", None)
        elif old == "Skeleton":
            kind = _i(nbt.get(e, "SkeletonType", 0))
            e.pop("SkeletonType", None)
            old = {1: "WitherSkeleton", 2: "Stray"}.get(kind, old)
        elif old == "Zombie":
            ztype = _i(nbt.get(e, "ZombieType", 0))
            villager = bool(nbt.get(e, "IsVillager", 0)) or 1 <= ztype <= 5
            for k in ("ZombieType", "IsVillager"):
                e.pop(k, None)
            if ztype == 6:
                old = "Husk"
            elif villager:
                old = "ZombieVillager"
                if "Profession" not in e:      # the profession of the villager the zombie was
                    prof = nbt.get(e, "VillagerProfession")
                    e["Profession"] = nbt.IntTag(_i(prof) if prof is not None else max(0, ztype - 1))
                e.pop("VillagerProfession", None)
        elif old == "Guardian":
            elder = bool(nbt.get(e, "Elder", 0))
            e.pop("Elder", None)
            if elder:
                old = "ElderGuardian"
    new = ids.ENTITY_OLD_TO_NEW.get(old)
    return "minecraft:" + new if new else old


def modern_entity(e: nbt.CompoundTag) -> nbt.CompoundTag:
    """The entity (in place) with the namespaced id of the TU54+ games; what rides it too."""
    old = nbt.get(e, "id", "")
    if isinstance(old, str) and old and ":" not in old:
        e["id"] = nbt.StringTag(_modern_name(old, e))
    for key in ("Riding",):
        r = nbt.get_tag(e, key)
        if isinstance(r, nbt.CompoundTag):
            modern_entity(r)
    for r in nbt.get_tag(e, "Passengers") or []:
        if isinstance(r, nbt.CompoundTag):
            modern_entity(r)
    _modern_spawner(e)
    return e


def _spawn_name(eid) -> Optional[str]:
    """The namespaced name of the mob a spawner spawns (``eid``: any id scheme)."""
    old, extra = ids.entity_to_old(str(eid or ""))
    if old is None:
        return None
    probe = nbt.CompoundTag({"id": nbt.StringTag(old)})
    for k, v in extra.items():
        probe[k] = nbt.IntTag(v)
    return _modern_name(old, probe)


def _modern_spawner(t: nbt.CompoundTag) -> None:
    """A spawner (block entity or minecart) in the layout the TU54+ games write: the mob in SpawnData
    and SpawnPotentials (no ``EntityId``)."""
    eid = nbt.get(t, "EntityId")
    sd = nbt.get_tag(t, "SpawnData")
    pots = nbt.get_tag(t, "SpawnPotentials")
    if eid is None and sd is None and pots is None:
        return
    name = _spawn_name(eid) if isinstance(eid, str) and eid else None
    if isinstance(sd, nbt.CompoundTag) and "id" in sd:
        name = _spawn_name(nbt.get(sd, "id")) or name
    name = name or "minecraft:pig"
    t.pop("EntityId", None)
    if not isinstance(sd, nbt.CompoundTag):
        sd = nbt.CompoundTag()
        t["SpawnData"] = sd
    sd["id"] = nbt.StringTag(name)
    if isinstance(pots, nbt.ListTag) and len(pots):
        for entry in pots:
            ent = nbt.get_tag(entry, "Entity")
            if isinstance(ent, nbt.CompoundTag) and "id" in ent:
                ent["id"] = nbt.StringTag(_spawn_name(nbt.get(ent, "id")) or name)
    else:
        t["SpawnPotentials"] = nbt.ListTag([nbt.CompoundTag({
            "Entity": nbt.CompoundTag({"id": nbt.StringTag(name)}), "Weight": nbt.IntTag(1)})], 10)


def modern_tile(t: nbt.CompoundTag) -> nbt.CompoundTag:
    """The block entity (in place) with the namespaced id of the TU54+ games."""
    old = nbt.get(t, "id", "")
    if isinstance(old, str) and old and ":" not in old:
        if old == "EnderChest":
            t["id"] = nbt.StringTag(_ENDER_CHEST)
        elif old in ids.TILE_OLD_TO_NEW:
            t["id"] = nbt.StringTag("minecraft:" + ids.TILE_OLD_TO_NEW[old])
    if nbt.get(t, "id") == "minecraft:mob_spawner":
        _modern_spawner(t)
    return t


# ============================================================ players


_SIGN_CODE = re.compile("§.")


def plain_sign_line(line: str) -> str:
    """Sign text without Java's formatting codes (the console signs show them as they are)."""
    return _SIGN_CODE.sub("", line)


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _i(v, default=0) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


_ARMOR_SLOTS = {"feet": 100, "legs": 101, "chest": 102, "head": 103}


def lce_player(p: nbt.CompoundTag, compat: Compat, spawn: Tuple[float, float, float],
               name: Optional[str] = None) -> nbt.CompoundTag:
    """A player file with the fields and types an LCE game writes (see the module's doc).
    ``p`` has already legacy items / position; ``spawn`` is where a player without a position
    goes; ``name`` the player's name for neoLegacy's "UUID" field."""
    from .world import legacy_item

    g = lambda k, d=None: nbt.get(p, k, d)  # noqa: E731
    out = nbt.CompoundTag()
    pos = nbt.get_tag(p, "Pos")
    if pos is not None and len(pos) == 3:
        xyz = [_f(v.py_data) for v in pos]
    else:
        xyz = [spawn[0] + 0.5, spawn[1], spawn[2] + 0.5]
    out["Pos"] = nbt.ListTag([nbt.DoubleTag(v) for v in xyz], 6)
    mot = nbt.get_tag(p, "Motion")
    mv = [_f(v.py_data) for v in mot] if mot is not None and len(mot) == 3 else [0.0, 0.0, 0.0]
    out["Motion"] = nbt.ListTag([nbt.DoubleTag(v) for v in mv], 6)
    rot = nbt.get_tag(p, "Rotation")
    rv = [_f(v.py_data) for v in rot] if rot is not None and len(rot) == 2 else [0.0, 0.0]
    out["Rotation"] = nbt.ListTag([nbt.FloatTag(v) for v in rv], 5)
    out["FallDistance"] = nbt.FloatTag(_f(g("FallDistance", g("fall_distance", 0))))
    out["Fire"] = nbt.ShortTag(max(-32768, min(32767, _i(g("Fire", -20)))))
    out["Air"] = nbt.ShortTag(max(0, min(300, _i(g("Air", 300)))))
    out["OnGround"] = nbt.ByteTag(1 if g("OnGround") else 0)
    dim = g("Dimension", 0)
    out["Dimension"] = nbt.IntTag(dim if isinstance(dim, int) and dim in (-1, 0, 1) else 0)
    out["Invulnerable"] = nbt.ByteTag(1 if g("Invulnerable") else 0)
    out["PortalCooldown"] = nbt.IntTag(_i(g("PortalCooldown", 0)))
    out["AbsorptionAmount"] = nbt.FloatTag(_f(g("AbsorptionAmount", 0)))
    health = _f(g("HealF", g("Health", 20)), 20.0)
    health = max(0.0, min(health, 20.0)) or 20.0
    out["HealF"] = nbt.FloatTag(health)
    out["Health"] = nbt.ShortTag(int(round(health)))
    for k in ("HurtTime", "DeathTime", "AttackTime"):
        out[k] = nbt.ShortTag(0)
    inv = compat.items_list(nbt.get_tag(p, "Inventory") or [])
    # Java 1.20.5+ keeps the armour (and the off hand) outside the inventory
    equip = nbt.get_tag(p, "equipment")
    if isinstance(equip, nbt.CompoundTag):
        used = {int(nbt.get(it, "Slot", -1)) for it in inv}
        for key, slot in _ARMOR_SLOTS.items():
            src = nbt.get_tag(equip, key)
            if isinstance(src, nbt.CompoundTag) and slot not in used:
                li = legacy_item(src)
                li = compat.item(li) if li is not None else None
                if li is not None:
                    li["Slot"] = nbt.ByteTag(slot)
                    inv.append(li)
    out["Inventory"] = inv
    out["SelectedItemSlot"] = nbt.IntTag(max(0, min(8, _i(g("SelectedItemSlot", 0)))))
    out["Sleeping"] = nbt.ByteTag(0)
    out["SleepTimer"] = nbt.ShortTag(0)
    out["XpP"] = nbt.FloatTag(max(0.0, min(1.0, _f(g("XpP", 0)))))
    out["XpLevel"] = nbt.IntTag(max(0, _i(g("XpLevel", 0))))
    out["XpTotal"] = nbt.IntTag(max(0, _i(g("XpTotal", 0))))
    out["Score"] = nbt.IntTag(_i(g("Score", 0)))
    out["enchSeed"] = nbt.IntTag(_i(g("enchSeed", g("XpSeed", 0))))
    out["foodLevel"] = nbt.IntTag(max(0, min(20, _i(g("foodLevel", 20)))))
    out["foodTickTimer"] = nbt.IntTag(_i(g("foodTickTimer", 0)))
    out["foodSaturationLevel"] = nbt.FloatTag(_f(g("foodSaturationLevel", 5)))
    out["foodExhaustionLevel"] = nbt.FloatTag(_f(g("foodExhaustionLevel", 0)))
    ab = nbt.get_tag(p, "abilities")
    a = nbt.CompoundTag()
    for k, default in (("flying", 0), ("instabuild", 0), ("invulnerable", 0), ("mayBuild", 1), ("mayfly", 0)):
        a[k] = nbt.ByteTag(1 if (nbt.get(ab, k, default) if ab is not None else default) else 0)
    a["flySpeed"] = nbt.FloatTag(_f(nbt.get(ab, "flySpeed", 0.05) if ab is not None else 0.05, 0.05))
    a["walkSpeed"] = nbt.FloatTag(_f(nbt.get(ab, "walkSpeed", 0.1) if ab is not None else 0.1, 0.1))
    out["abilities"] = a
    out["EnderItems"] = compat.items_list(nbt.get_tag(p, "EnderItems") or [])
    if name:
        out["UUID"] = nbt.StringTag(name)
    return out
