"""BTA entities and tile entities -> 1.17.1 entities / block entities.

Only entity types that exist in 1.17.1 are ever emitted: an entity id unknown to the DataFixer
schema of the chunk's data version would make the upgrade of the whole chunk fail (and Minecraft
would regenerate it).  Items that have no slot left become never-despawning item entities at the
original spot: nothing is lost.
"""

from __future__ import annotations

import math
import random
import uuid as _uuid
from typing import List, NamedTuple, Optional

import numpy as np

from .. import nbt
from . import blockmap, items, stats, text
from .nbtio import gb, gc, gf, gi, gl, glist, gs, num
from .palette import COLORS, Palette
from .states import BlockState, palette_tag


def _short(v: int) -> int:
    v &= 0xFFFF
    return v - 65536 if v >= 32768 else v


def _byte(v: int) -> int:
    v &= 0xFF
    return v - 256 if v >= 128 else v


def dlist(*vals) -> nbt.ListTag:
    return nbt.ListTag([nbt.DoubleTag(float(v)) for v in vals], 6)


def flist(*vals) -> nbt.ListTag:
    return nbt.ListTag([nbt.FloatTag(float(v)) for v in vals], 5)


def uuid_ints(u: _uuid.UUID) -> nbt.IntArrayTag:
    v = u.int
    vals = [(v >> s) & 0xFFFFFFFF for s in (96, 64, 32, 0)]
    return nbt.IntArrayTag(np.array([x - (1 << 32) if x >= 1 << 31 else x for x in vals], np.int32))


def random_uuid() -> nbt.IntArrayTag:
    return uuid_ints(_uuid.UUID(int=random.getrandbits(128), version=4))


def spill_to_entities(stacks: List[nbt.CompoundTag], x: float, y: float, z: float, out: List[nbt.CompoundTag]) -> None:
    for it in stacks:
        it.pop("Slot", None)
        e = nbt.CompoundTag({
            "id": nbt.StringTag("minecraft:item"), "Pos": dlist(x, y, z), "Motion": dlist(0, 0, 0),
            "Rotation": flist(0, 0), "Health": nbt.ShortTag(5), "Age": nbt.ShortTag(-32768),  # never despawns
            "PickupDelay": nbt.ShortTag(0), "OnGround": nbt.ByteTag(1), "UUID": random_uuid(), "Item": it,
        })
        out.append(e)
        stats.inc("items.spilled_as_entities")


# ======================================================================== entities
_LEGACY = {"Item": "item", "Lightning": "lightning", "Painting": "painting", "Arrow": "arrow", "Snowball": "snowball",
           "Fireball": "fireball", "PrimedTnt": "primed_tnt", "FallingSand": "falling_block", "Minecart": "minecart",
           "Boat": "boat", "ArmouredZombie": "zombie_armored", "ArrowGolden": "arrow_golden", "Cannonball": "cannonball",
           "ArrowPurple": "arrow_purple", "Pebble": "pebble", "FireflyCluster": "firefly_cluster", "Mob": "mob",
           "MobMonster": "human", "Creeper": "creeper", "Skeleton": "skeleton", "Spider": "spider", "Giant": "giant",
           "Zombie": "zombie", "Slime": "slime", "Ghast": "ghast", "PigZombie": "zombie_pigman", "Snowman": "snowman",
           "Scorpion": "scorpion", "Pig": "pig", "Sheep": "sheep", "Cow": "cow", "Chicken": "chicken", "Squid": "squid",
           "Wolf": "wolf", "FlamingArrow": "arrow_flaming"}


def normalise_entity_id(eid: Optional[str]) -> str:
    if eid is None:
        return ""
    if eid in _LEGACY:
        return _LEGACY[eid]
    return (eid.split(":", 1)[1] if ":" in eid else eid).lower()


_MOBS = {"zombie": "zombie", "zombie_armored": "zombie", "zombie_pigman": "zombified_piglin", "creeper": "creeper",
         "skeleton": "skeleton", "spider": "spider", "giant": "giant", "slime": "slime", "ghast": "ghast",
         "snowman": "snow_golem", "scorpion": "cave_spider", "pig": "pig", "sheep": "sheep", "cow": "cow",
         "chicken": "chicken", "squid": "squid", "wolf": "wolf", "deer": "goat"}


def vanilla_mob_id(bta_id: Optional[str]) -> Optional[str]:
    v = _MOBS.get(normalise_entity_id(bta_id))
    return None if v is None else "minecraft:" + v


def base_entity(eid: str, x: float, y: float, z: float, yaw: float, pitch: float) -> nbt.CompoundTag:
    return nbt.CompoundTag({
        "id": nbt.StringTag(eid), "Pos": dlist(x, y, z), "Motion": dlist(0, 0, 0), "Rotation": flist(yaw, pitch),
        "FallDistance": nbt.FloatTag(0), "Fire": nbt.ShortTag(-1), "Air": nbt.ShortTag(300), "OnGround": nbt.ByteTag(1),
        "Invulnerable": nbt.ByteTag(0), "PortalCooldown": nbt.IntTag(0), "UUID": random_uuid(),
    })


def _pos(bta: dict):
    p = glist(bta, "Pos")
    if p is not None and len(p) == 3:
        return num(p[0]), num(p[1]), num(p[2])
    return 0.0, 0.0, 0.0


def _clamp_motion(v: float) -> float:
    return max(-10.0, min(10.0, v)) if math.isfinite(v) else 0.0


def copy_base(bta: dict, eid: str) -> nbt.CompoundTag:
    x, y, z = _pos(bta)
    r = glist(bta, "Rotation")
    yaw, pitch = (num(r[0]), num(r[1])) if r is not None and len(r) == 2 else (0.0, 0.0)
    e = base_entity(eid, x, y, z, yaw, pitch)
    m = glist(bta, "Motion")
    if m is not None and len(m) == 3:
        e["Motion"] = dlist(*(_clamp_motion(num(v)) for v in m))
    e["FallDistance"] = nbt.FloatTag(gf(bta, "FallDistance", 0.0))
    e["Fire"] = nbt.ShortTag(_short(gi(bta, "Fire", -1)))
    e["Air"] = nbt.ShortTag(_short(gi(bta, "Air", 300)))
    e["OnGround"] = nbt.ByteTag(1 if gb(bta, "OnGround") else 0)
    return e


def valid_position(bta: dict) -> bool:
    p = glist(bta, "Pos")
    if p is None or len(p) != 3:
        return False
    return all(math.isfinite(num(v)) for v in p)


def _epos(e: nbt.CompoundTag):
    p = e["Pos"]
    return float(p[0].py_data), float(p[1].py_data), float(p[2].py_data)


def convert_entity(bta: dict, dimension: int, palette: Palette, out: List[nbt.CompoundTag]) -> Optional[nbt.CompoundTag]:
    """Converted entity (None when dropped); extra entities (spilled cargo...) go to ``out``."""
    eid = normalise_entity_id(gs(bta, "id"))
    if not valid_position(bta):
        stats.inc("entities.dropped.invalid_position")
        return None
    if eid == "item":
        extra: List[nbt.CompoundTag] = []
        it = items.convert(gc(bta, "Item"), palette, extra)
        if it is None:
            stats.inc("entities.dropped.item_unknown")
            return None
        e = copy_base(bta, "minecraft:item")
        e["Item"] = it
        e["Health"] = nbt.ShortTag(_short(max(1, gi(bta, "Health", 5))))
        e["Age"] = nbt.ShortTag(_short(gi(bta, "Age", 0)))
        e["PickupDelay"] = nbt.ShortTag(0)
        if extra:
            spill_to_entities(extra, *_epos(e), out)
    elif eid == "painting":
        e = _painting(bta, palette, out)
    elif eid == "minecart":
        e = _minecart(bta, palette, out)
    elif eid == "boat":
        e = copy_base(bta, "minecraft:boat")
        e["Type"] = nbt.StringTag("oak")
    elif eid == "primed_tnt":
        e = copy_base(bta, "minecraft:tnt")
        e["Fuse"] = nbt.ShortTag(_short(gi(bta, "Fuse", 80)))
    elif eid == "falling_block":
        e = _falling_block(bta, palette)
    elif eid in ("arrow", "arrow_golden", "arrow_purple", "arrow_flaming", "snowball", "fireball", "cannonball", "pebble",
                 "egg", "lightning"):
        stats.inc(f"entities.dropped.projectile.{eid}")
        return None
    elif eid in ("firefly_cluster", "butterfly"):
        stats.inc(f"entities.dropped.ambient.{eid}")
        return None
    else:
        mob = vanilla_mob_id(eid)
        if mob is None:
            stats.inc(f"entities.dropped.unknown.{eid}")
            return None
        e = _mob(bta, eid, mob, palette, out)
    if e is not None:
        stats.inc(f"entities.converted.{nbt.get(e, 'id')}")
    return e


def _simple_bta(iid: int) -> dict:
    return {"id": iid, "Count": 1, "Expanded": 1, "Version": 19135}


def _mob(bta: dict, bta_id: str, vanilla_id: str, palette: Palette, out: List[nbt.CompoundTag]) -> Optional[nbt.CompoundTag]:
    e = copy_base(bta, vanilla_id)
    health = gi(bta, "Health", 10)
    if health <= 0:
        stats.inc("entities.dropped.dead")
        return None
    e["Health"] = nbt.FloatTag(float(health))
    e["HurtTime"] = nbt.ShortTag(0)
    e["DeathTime"] = nbt.ShortTag(0)
    e["AbsorptionAmount"] = nbt.FloatTag(0)
    e["LeftHanded"] = nbt.ByteTag(1 if gb(bta, "LeftHanded") else 0)
    e["CanPickUpLoot"] = nbt.ByteTag(0)
    e["NoAI"] = nbt.ByteTag(1 if gb(bta, "noAI") else 0)
    nick = gs(bta, "Nickname", "")
    if nick:
        e["CustomName"] = nbt.StringTag(text.formatted_to_json(nick))
        e["PersistenceRequired"] = nbt.ByteTag(1)
    armor_slots: List[Optional[nbt.CompoundTag]] = [None] * 4
    main_hand = None
    spill: List[nbt.CompoundTag] = []
    bta_armor = glist(bta, "Armor")
    if bta_armor is not None and bta_id != "wolf":
        for c in bta_armor:
            if not isinstance(c, dict):
                continue
            extra: List[nbt.CompoundTag] = []
            it = items.convert(c, palette, extra)
            spill.extend(extra)
            if it is None:
                continue
            slot = items.armor_slot_for(it, 3 - max(0, min(3, gi(c, "Slot"))))
            if armor_slots[slot] is None:
                armor_slots[slot] = it
            else:
                spill.append(it)
        e["PersistenceRequired"] = nbt.ByteTag(1)
    if bta_id == "sheep":
        e["Color"] = nbt.ByteTag(gi(bta, "Color") & 15)
        e["Sheared"] = nbt.ByteTag(1 if gb(bta, "Sheared") else 0)
    elif bta_id == "pig":
        e["Saddle"] = nbt.ByteTag(1 if gb(bta, "Saddle") else 0)
    elif bta_id == "creeper":
        if gb(bta, "powered"):
            e["powered"] = nbt.ByteTag(1)
    elif bta_id == "slime":
        e["Size"] = nbt.IntTag(max(0, gi(bta, "Size")))
    elif bta_id == "zombie_pigman":
        if gi(bta, "Anger") > 0:
            e["AngerTime"] = nbt.IntTag(gi(bta, "Anger"))
    elif bta_id == "zombie_armored":
        if gb(bta, "hasSword"):
            main_hand = items.convert(_simple_bta(16395), palette, spill)
    elif bta_id == "wolf":
        e["Sitting"] = nbt.ByteTag(1 if gb(bta, "Sitting") else 0)
        msb, lsb = gl(bta, "OwnerUUID_msb", 0), gl(bta, "OwnerUUID_lsb", 0)
        if msb or lsb:
            e["Owner"] = uuid_ints(_uuid.UUID(int=((msb & (2 ** 64 - 1)) << 64) | (lsb & (2 ** 64 - 1))))
            e["PersistenceRequired"] = nbt.ByteTag(1)
        if gb(bta, "Angry"):
            e["AngerTime"] = nbt.IntTag(400)
        held = gc(bta, "HeldItem")
        if held is not None:
            main_hand = items.convert(held, palette, spill)
        wolf_armor = bta.get("Armor")
        if isinstance(wolf_armor, dict):
            it = items.convert(wolf_armor, palette, spill)
            if it is not None:  # 1.17 has no wolf body slot: dropped, non-despawning item next to the wolf
                spill.append(it)
    elif bta_id == "snowman":
        e["Pumpkin"] = nbt.ByteTag(1)
    elif bta_id == "chicken":
        e["EggLayTime"] = nbt.IntTag(6000)
    if vanilla_id in ("minecraft:pig", "minecraft:sheep", "minecraft:cow", "minecraft:chicken", "minecraft:wolf",
                      "minecraft:goat"):
        e["Age"] = nbt.IntTag(0)
        e["ForcedAge"] = nbt.IntTag(0)
        e["InLove"] = nbt.IntTag(0)
    e["ArmorItems"] = nbt.ListTag([s if s is not None else nbt.CompoundTag() for s in armor_slots], 10)
    e["HandItems"] = nbt.ListTag([main_hand if main_hand is not None else nbt.CompoundTag(), nbt.CompoundTag()], 10)
    if spill:
        spill_to_entities(spill, *_epos(e), out)
    return e


_PAINTINGS = {"Kebab": "kebab", "Aztec": "aztec", "Alban": "alban", "Aztec2": "aztec2", "Bomb": "bomb", "Plant": "plant",
              "Wasteland": "wasteland", "Geology": "meditative", "CactusBird": "plant", "Pool": "pool",
              "Courbet": "courbet", "Sea": "sea", "Sunset": "sunset", "Creebet": "creebet", "Allegory": "sea",
              "Wanderer": "wanderer", "Graham": "graham", "Monologue": "prairie_ride", "Match": "match", "Bust": "bust",
              "Stage": "stage", "Void": "void", "SkullAndRoses": "skull_and_roses", "Fighters": "fighters",
              "TheBull": "passage", "Dresses": "bouquet", "TheBlanket": "tides", "DodFagel": "cavebird",
              "Skeleton": "skeleton", "DonkeyKong": "donkey_kong", "DeathAndTheMaiden": "skeleton", "TheBox": "backyard",
              "TheGoldenApple": "pond", "Pointer": "pointer", "Pigscene": "pigscene", "BurningSkull": "burning_skull"}


def painting_variant(motive: str) -> str:
    """BTA paintings -> vanilla ones of exactly the same size (they cover the same wall)."""
    return _PAINTINGS.get(motive, "kebab")


def _painting(bta: dict, palette: Palette, out: List[nbt.CompoundTag]) -> nbt.CompoundTag:
    """BTA stores the wall block and a direction 0..3 = facing north, west, south, east; vanilla the
    block in front of the wall and a 2D facing (0 south, 1 west, 2 north, 3 east)."""
    d = gi(bta, "Dir") & 3
    wx, wy, wz = gi(bta, "TileX"), gi(bta, "TileY"), gi(bta, "TileZ")
    dx, dz, facing2d = ((0, -1, 2), (-1, 0, 1), (0, 1, 0), (1, 0, 3))[d]
    tx, ty, tz = wx + dx, wy, wz + dz
    e = copy_base(bta, "minecraft:painting")
    e["Pos"] = dlist(tx + 0.5 - dx * 0.46875, ty + 0.5, tz + 0.5 - dz * 0.46875)
    e["Motion"] = dlist(0, 0, 0)
    e["TileX"], e["TileY"], e["TileZ"] = nbt.IntTag(tx), nbt.IntTag(ty), nbt.IntTag(tz)
    e["Facing"] = nbt.ByteTag(facing2d)
    e["Rotation"] = flist(facing2d * 90.0, 0)
    e["Motive"] = nbt.StringTag("minecraft:" + painting_variant(gs(bta, "Motive", "Kebab")))
    if gb(bta, "itemExists"):
        stack = {"id": _short(gi(bta, "itemID")), "Count": 1, "Damage": _short(gi(bta, "itemMeta")), "Expanded": 1,
                 "Version": 19135}
        spill: List[nbt.CompoundTag] = []
        it = items.convert(stack, palette, spill)
        if it is not None:
            spill.append(it)
        spill_to_entities(spill, tx + 0.5, ty + 0.1, tz + 0.5, out)
    stats.inc("paintings")
    return e


def _minecart(bta: dict, palette: Palette, out: List[nbt.CompoundTag]) -> nbt.CompoundTag:
    t = gi(bta, "Type")
    eid = {1: "minecraft:chest_minecart", 2: "minecraft:furnace_minecart"}.get(t, "minecraft:minecart")
    e = copy_base(bta, eid)
    if t == 1:
        spill: List[nbt.CompoundTag] = []
        e["Items"] = items.convert_inventory(glist(bta, "Items"), 27, palette, spill)
        if spill:
            spill_to_entities(spill, *_epos(e), out)
    elif t == 2:
        e["PushX"] = nbt.DoubleTag(gf(bta, "PushX", 0.0))
        e["PushZ"] = nbt.DoubleTag(gf(bta, "PushZ", 0.0))
        e["Fuel"] = nbt.ShortTag(_short(min(32767, gi(bta, "Fuel"))))
    return e


def output_name(name: str) -> str:
    """Block names renamed after 1.18.2: write the old name so the DataFixer renames it."""
    return {"minecraft:short_grass": "minecraft:grass", "minecraft:iron_chain": "minecraft:chain"}.get(name, name)


def _falling_block(bta: dict, palette: Palette) -> Optional[nbt.CompoundTag]:
    s = blockmap.map_block(gi(bta, "Tile") & 16383, gi(bta, "TileData") & 0xFF, blockmap.MapCtx(palette))
    if s is None or s.is_air:
        stats.inc("entities.dropped.falling_block_unknown")
        return None
    e = copy_base(bta, "minecraft:falling_block")
    e["BlockState"] = palette_tag(s, output_name(s.name))
    e["Time"] = nbt.IntTag(1)
    e["DropItem"] = nbt.ByteTag(1)
    e["HurtEntities"] = nbt.ByteTag(0)
    return e


# =================================================================== tile entities
_TE_LEGACY = {"Furnace": "furnace", "Chest": "chest", "RecordPlayer": "jukebox", "Trap": "dispenser",
              "Activator": "activator", "Sign": "sign", "MobSpawner": "mob_spawner", "Music": "noteblock",
              "Piston": "piston_moving", "BlastFurnace": "furnace_blast", "Sensor": "sensor", "Trommel": "trommel",
              "Basket": "basket", "Flag": "flag", "Seat": "seat", "FlowerJar": "jar_flower", "MeshGold": "mesh_gold"}


def normalise_te_id(tid: Optional[str]) -> str:
    if tid is None:
        return ""
    if tid in _TE_LEGACY:
        return _TE_LEGACY[tid]
    return tid.split(":", 1)[1] if ":" in tid else tid


class TEResult(NamedTuple):
    state: Optional[BlockState]
    block_entity: Optional[nbt.CompoundTag]


def _base_be(bid: str, x: int, y: int, z: int) -> nbt.CompoundTag:
    return nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + bid), "x": nbt.IntTag(x), "y": nbt.IntTag(y),
                            "z": nbt.IntTag(z), "keepPacked": nbt.ByteTag(0)})


def convert_tile(bta: Optional[dict], st: BlockState, x: int, y: int, z: int, palette: Palette,
                 entities_out: List[nbt.CompoundTag]) -> TEResult:
    """``bta`` may be None when a vanilla block entity must be created for a block that had none."""
    bta_id = normalise_te_id(gs(bta, "id")) if bta is not None else ""
    spill: List[nbt.CompoundTag] = []
    r = _convert_tile(bta_id, bta, st, x, y, z, palette, spill, entities_out)
    if spill:
        spill_to_entities(spill, x + 0.5, y + 1.0, z + 0.5, entities_out)
    return r


def _items_of(lst: Optional[list], palette: Palette) -> List[nbt.CompoundTag]:
    out: List[nbt.CompoundTag] = []
    for c in lst or []:
        if not isinstance(c, dict):
            continue
        extra: List[nbt.CompoundTag] = []
        it = items.convert(c, palette, extra)
        if it is not None:
            out.append(it)
        out.extend(extra)
    return out


def _convert_tile(bta_id, bta, st: BlockState, x, y, z, palette, spill, entities_out) -> TEResult:
    name = st.name
    btl = glist(bta, "Items") if bta is not None else None
    if name == "minecraft:chest":
        be = _base_be("chest", x, y, z)
        be["Items"] = items.convert_inventory(btl, 27, palette, spill)
        return TEResult(None, be)
    if name in ("minecraft:furnace", "minecraft:blast_furnace"):
        be = _base_be(name[10:], x, y, z)
        be["Items"] = items.convert_inventory(btl, 3, palette, spill)
        if bta is not None:
            be["BurnTime"] = nbt.ShortTag(_short(gi(bta, "BurnTime")))
            be["CookTime"] = nbt.ShortTag(_short(gi(bta, "CookTime")))
        be["CookTimeTotal"] = nbt.ShortTag(200 if name == "minecraft:furnace" else 100)
        be["RecipesUsed"] = nbt.CompoundTag()
        return TEResult(None, be)
    if name in ("minecraft:dispenser", "minecraft:dropper"):
        be = _base_be(name[10:], x, y, z)
        be["Items"] = items.convert_inventory(btl, 9, palette, spill)
        return TEResult(None, be)
    if name == "minecraft:barrel":
        be = _base_be("barrel", x, y, z)
        if bta_id == "basket" and bta is not None:
            be["Items"] = _basket_to_slots(btl, palette, spill)
        else:
            be["Items"] = items.convert_inventory(btl, 27, palette, spill)
        return TEResult(None, be)
    if name == "minecraft:jukebox":
        be = _base_be("jukebox", x, y, z)
        if bta is not None:
            record = gi(bta, "Record")
            if gi(bta, "Expanded") == 0 and record >= 256:
                record += 16384 - 256
            if record > 0:
                stack = {"id": _short(record), "Count": 1, "Expanded": 1, "Version": 19135}
                it = items.convert(stack, palette, [])
                if it is not None:
                    be["RecordItem"] = it
                    return TEResult(st.with_("has_record", "true"), be)
        return TEResult(None, be)
    if name == "minecraft:spawner":
        be = _base_be("mob_spawner", x, y, z)
        mob = vanilla_mob_id(gs(bta, "EntityId")) if bta is not None else None
        if mob is not None:
            # 1.18+ layout (after SpawnerDataFix): SpawnData {entity:{id}}, SpawnPotentials [{weight, data}]
            spawn_data = nbt.CompoundTag({"entity": nbt.CompoundTag({"id": nbt.StringTag(mob)})})
            be["SpawnData"] = spawn_data
            be["SpawnPotentials"] = nbt.ListTag([nbt.CompoundTag({"weight": nbt.IntTag(1),
                                                                  "data": nbt.copy(spawn_data)})], 10)
        else:
            be["SpawnPotentials"] = nbt.ListTag([], 10)
        be["Delay"] = nbt.ShortTag(20 if bta is None else _short(max(0, gi(bta, "Delay"))))
        for k, v in (("MinSpawnDelay", 200), ("MaxSpawnDelay", 800), ("SpawnCount", 4), ("MaxNearbyEntities", 6),
                     ("RequiredPlayerRange", 16), ("SpawnRange", 4)):
            be[k] = nbt.ShortTag(v)
        return TEResult(None, be)
    if name == "minecraft:red_bed":
        return TEResult(None, _base_be("bed", x, y, z))
    if name == "minecraft:skeleton_skull":
        return TEResult(None, _base_be("skull", x, y, z))
    if name == "minecraft:campfire":
        be = _base_be("campfire", x, y, z)
        be["Items"] = nbt.ListTag([], 10)
        be["CookingTimes"] = nbt.IntArrayTag(np.zeros(4, np.int32))
        be["CookingTotalTimes"] = nbt.IntArrayTag(np.zeros(4, np.int32))
        return TEResult(None, be)
    if name == "minecraft:white_banner":
        be = _base_be("banner", x, y, z)
        be["Patterns"] = nbt.ListTag([], 10)
        if bta is not None:
            spill.extend(_items_of(btl, palette))
        return TEResult(None, be)
    if name.endswith("_sign") or name.endswith("_wall_sign"):
        be = _base_be("sign", x, y, z)
        for i in range(1, 5):
            line = gs(bta, f"Text{i}", "") if bta is not None else ""
            be[f"Text{i}"] = nbt.StringTag(text.formatted_to_json(line))
        col = 15 if bta is None else gi(bta, "Color", 15)
        be["Color"] = nbt.StringTag(COLORS[col & 15])
        be["GlowingText"] = nbt.ByteTag(1 if bta is not None and gb(bta, "Glowing") else 0)
        return TEResult(None, be)
    # block entities with no vanilla counterpart: keep whatever items they held
    if bta is not None:
        if bta_id == "mesh_gold":
            if gb(bta, "hasItem"):
                extra: List[nbt.CompoundTag] = []
                it = items.convert(gc(bta, "item"), palette, extra)
                if it is not None:
                    spill.append(it)
                spill.extend(extra)
        elif bta_id == "noteblock":
            if st.is_("minecraft:note_block") and "note" in bta:
                return TEResult(st.with_("note", str(max(0, min(24, gi(bta, "note"))))), None)
        else:
            if btl and bta_id != "statue_stone":
                spill.extend(_items_of(btl, palette))
                stats.inc(f"tileentity.items_spilled.{bta_id}")
    return TEResult(None, None)


def _basket_to_slots(entries: Optional[list], palette: Palette, spill: List[nbt.CompoundTag]) -> nbt.ListTag:
    """Baskets store (item, count) pairs with arbitrary counts: split into stacks of at most 64."""
    out = nbt.ListTag([], 10)
    slot = 0
    for c in entries or []:
        if not isinstance(c, dict):
            continue
        total = gi(c, "Count")
        while total > 0:
            n = min(64, total)
            total -= n
            stack = dict(c)
            stack["Count"] = _byte(n)
            extra: List[nbt.CompoundTag] = []
            it = items.convert(stack, palette, extra)
            if it is None:
                break
            for s in [it] + extra:
                if slot < 27:
                    s["Slot"] = nbt.ByteTag(slot)
                    slot += 1
                    out.append(s)
                else:
                    spill.append(s)
    return out


_POSES = ((0, 0, 0, 0, 0, 0), (-2.2, 0, 0, 0, 0, 0), (0, -2.2, 0, 0, 0, 0), (-2.2, -2.2, 0, 0, 0, 0),
          (0.75, -0.75, -0.5, 0.5, 0, 0), (0, 0, 0, 0, -0.3, 0), (0, 0, 0, 0, 0.3, 0), (0, 0, 0, 0, 0, -1),
          (0, 0, 0, 0, 0, 1))


def _deg(rad: float) -> float:
    return float(np.float32(math.degrees(float(np.float32(rad)))))


def statue_to_armor_stand(bta: dict, rotation: int, x: int, y: int, z: int, palette: Palette,
                          entities_out: List[nbt.CompoundTag]) -> nbt.CompoundTag:
    """Statues become armor stands wearing the statue's armour and holding its item."""
    e = base_entity("minecraft:armor_stand", x + 0.5, y, z + 0.5, rotation * 22.5, 0.0)
    e["ShowArms"] = nbt.ByteTag(1)
    e["NoBasePlate"] = nbt.ByteTag(0)
    e["Health"] = nbt.FloatTag(20.0)
    e["Invisible"] = nbt.ByteTag(0)
    slots: List[Optional[nbt.CompoundTag]] = [None] * 4  # 1.17 order: feet, legs, chest, head
    spill: List[nbt.CompoundTag] = []
    for c in glist(bta, "Armor") or []:
        if not isinstance(c, dict):
            continue
        bta_slot = gi(c, "Slot")  # 0 head, 1 chest, 2 legs, 3 boots
        extra: List[nbt.CompoundTag] = []
        it = items.convert(c, palette, extra)
        spill.extend(extra)
        if it is None:
            continue
        idx = items.armor_slot_for(it, 3 - max(0, min(3, bta_slot)))
        if slots[idx] is None:
            slots[idx] = it
        else:
            spill.append(it)
    e["ArmorItems"] = nbt.ListTag([s if s is not None else nbt.CompoundTag() for s in slots], 10)
    held = gc(bta, "HeldItem")
    held_item = None
    if held is not None:
        extra = []
        held_item = items.convert(held, palette, extra)
        spill.extend(extra)
    e["HandItems"] = nbt.ListTag([held_item if held_item is not None else nbt.CompoundTag(), nbt.CompoundTag()], 10)
    pose = gi(bta, "Pose", 0)
    v = _POSES[pose if 0 <= pose < len(_POSES) else 0]
    e["Pose"] = nbt.CompoundTag({
        "LeftArm": flist(_deg(v[0]), 0, 0), "RightArm": flist(_deg(v[1]), 0, 0), "LeftLeg": flist(_deg(v[2]), 0, 0),
        "RightLeg": flist(_deg(v[3]), 0, 0), "Head": flist(_deg(v[4]), _deg(v[5]), 0)})
    entities_out.append(e)
    if spill:
        spill_to_entities(spill, x + 0.5, y + 0.5, z + 0.5, entities_out)
    stats.inc("statues.to_armor_stands")
    return e
