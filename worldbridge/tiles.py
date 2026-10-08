"""Block entity translation (legacy / Java 1.13+ / Bedrock) through a
canonical dict representation."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from . import entities as ent
from . import ids, items, nbt

# canonical kind -> (legacy id, java modern id, bedrock id)
KINDS: Dict[str, Tuple[Optional[str], Optional[str], Optional[str]]] = {
    "chest": ("Chest", "chest", "Chest"),
    "trapped_chest": ("Chest", "trapped_chest", "Chest"),
    "dispenser": ("Trap", "dispenser", "Dispenser"),
    "dropper": ("Dropper", "dropper", "Dropper"),
    "hopper": ("Hopper", "hopper", "Hopper"),
    "furnace": ("Furnace", "furnace", "Furnace"),
    "blast_furnace": ("Furnace", "blast_furnace", "BlastFurnace"),
    "smoker": ("Furnace", "smoker", "Smoker"),
    "brewing_stand": ("Cauldron", "brewing_stand", "BrewingStand"),
    "shulker_box": ("ShulkerBox", "shulker_box", "ShulkerBox"),
    "barrel": ("Chest", "barrel", "Barrel"),
    "sign": ("Sign", "sign", "Sign"),
    "hanging_sign": ("Sign", "hanging_sign", "HangingSign"),
    "mob_spawner": ("MobSpawner", "mob_spawner", "MobSpawner"),
    "banner": ("Banner", "banner", "Banner"),
    "skull": ("Skull", "skull", "Skull"),
    "flower_pot": ("FlowerPot", None, "FlowerPot"),
    "jukebox": ("RecordPlayer", "jukebox", "Jukebox"),
    "noteblock": ("Music", None, "Music"),
    "enchanting_table": ("EnchantTable", "enchanting_table", "EnchantTable"),
    "ender_chest": ("EnderChest", "ender_chest", "EnderChest"),
    "beacon": ("Beacon", "beacon", "Beacon"),
    "command_block": ("Control", "command_block", "CommandBlock"),
    "comparator": ("Comparator", "comparator", "Comparator"),
    "daylight_detector": ("DLDetector", "daylight_detector", "DaylightDetector"),
    "end_portal": ("Airportal", "end_portal", "EndPortal"),
    "end_gateway": ("EndGateway", "end_gateway", "EndGateway"),
    "bed": ("Bed", "bed", "Bed"),
    # Java 1.14+ / Bedrock only (no legacy block entity): see the section "newer block entities" below
    "decorated_pot": (None, "decorated_pot", "DecoratedPot"),
    "campfire": (None, "campfire", "Campfire"),
    "soul_campfire": (None, "soul_campfire", "Campfire"),
    "beehive": (None, "beehive", "Beehive"),
    "bee_nest": (None, "bee_nest", "Beehive"),
    "lectern": (None, "lectern", "Lectern"),
    "chiseled_bookshelf": (None, "chiseled_bookshelf", "ChiseledBookshelf"),
    "brushable_block": (None, "brushable_block", "BrushableBlock"),
    "crafter": (None, "crafter", "Crafter"),
    "shelf": (None, "shelf", "Shelf"),
    "bell": (None, "bell", "Bell"),
    "conduit": (None, "conduit", "Conduit"),
    "sculk_sensor": (None, "sculk_sensor", "SculkSensor"),
    "calibrated_sculk_sensor": (None, "calibrated_sculk_sensor", "CalibratedSculkSensor"),
    "sculk_catalyst": (None, "sculk_catalyst", "SculkCatalyst"),
    "sculk_shrieker": (None, "sculk_shrieker", "SculkShrieker"),
    "trial_spawner": (None, "trial_spawner", "TrialSpawner"),
    "vault": (None, "vault", "Vault"),
    "creaking_heart": (None, "creaking_heart", "CreakingHeart"),
    "copper_golem_statue": (None, "copper_golem_statue", "CopperGolemStatue"),
    "jigsaw": (None, "jigsaw", "JigsawBlock"),
    "structure_block": ("Structure", "structure_block", "StructureBlock"),
    # Bedrock keeps a PistonArm on every piston (retracted / extended / in motion); Java has a block entity only for
    # the block that is moving, legacy Java too (its "Piston")
    "piston_arm": (None, None, "PistonArm"),
    "moving_piston": ("Piston", "piston", None),
    "lodestone": (None, None, "Lodestone"),               # Bedrock only: the handle that compasses point at
    "cauldron": (None, None, "Cauldron"),                 # Bedrock (potions, dyed water) and LCE PS4; Java has it in the block
    "test_block": (None, "test_block", None),             # Java 1.21.5+, no other game has them
    "test_instance_block": (None, "test_instance_block", None),
}
CONTAINERS = {"chest", "trapped_chest", "dispenser", "dropper", "hopper", "furnace", "blast_furnace", "smoker",
              "brewing_stand", "shulker_box", "barrel"}
LEGACY_TO_KIND = {}
for _k, (_l, _j, _b) in KINDS.items():
    if _l and _l not in LEGACY_TO_KIND:
        LEGACY_TO_KIND[_l] = _k
JAVA_TO_KIND = {j: k for k, (l, j, b) in KINDS.items() if j}
JAVA_TO_KIND.update({"spawner": "mob_spawner", "enchantment_table": "enchanting_table", "note_block": "noteblock",
                     "suspicious_sand": "brushable_block"})  # 1.19.4's name of the brushable block entity
# Java 1.21.9+ copper chests: the older games have only the wooden chest (the block becomes one too)
JAVA_TO_KIND.update({f"{w}{a}copper_chest": "chest" for w in ("", "waxed_")
                     for a in ("", "exposed_", "weathered_", "oxidized_")})
BEDROCK_TO_KIND = {}
for _k, (_l, _j, _b) in KINDS.items():
    if _b and _b not in BEDROCK_TO_KIND:
        BEDROCK_TO_KIND[_b] = _k
BEDROCK_TO_KIND["Chest"] = "chest"
# kinds that share their Bedrock id with another one (Chest: chest / trapped chest, Campfire, Beehive): reading
# Bedrock gives the first, the block of the Java chunk tells which one it is (java.modern.resolve_kinds)
SHARED_BEDROCK_ID = frozenset(k for k, (_l, _j, b) in KINDS.items() if b and sum(1 for v in KINDS.values() if v[2] == b) > 1)


# ------------------------------------------------------------------ flower pot plants
# The canonical plant is the legacy (Item, Data) pair of the Java 1.7-1.12 FlowerPot block entity.
# Java 1.13+ keeps it in the block (potted_<plant>), Bedrock in the block entity's PlantBlock.
POT_PLANTS = {"poppy": ("red_flower", 38, 0), "blue_orchid": ("red_flower", 38, 1), "allium": ("red_flower", 38, 2),
              "azure_bluet": ("red_flower", 38, 3), "red_tulip": ("red_flower", 38, 4),
              "orange_tulip": ("red_flower", 38, 5), "white_tulip": ("red_flower", 38, 6),
              "pink_tulip": ("red_flower", 38, 7), "oxeye_daisy": ("red_flower", 38, 8),
              "dandelion": ("yellow_flower", 37, 0), "oak_sapling": ("sapling", 6, 0), "spruce_sapling": ("sapling", 6, 1),
              "birch_sapling": ("sapling", 6, 2), "jungle_sapling": ("sapling", 6, 3), "acacia_sapling": ("sapling", 6, 4),
              "dark_oak_sapling": ("sapling", 6, 5), "red_mushroom": ("red_mushroom", 40, 0),
              "brown_mushroom": ("brown_mushroom", 39, 0), "cactus": ("cactus", 81, 0), "dead_bush": ("deadbush", 32, 0),
              "fern": ("tallgrass", 31, 2)}
_POT_BY_LEGACY = {}
for _flat, (_n, _i, _d) in POT_PLANTS.items():
    _POT_BY_LEGACY[(_n, _d)] = _POT_BY_LEGACY[(_i, _d)] = _flat


def pot_flat(plant) -> Optional[str]:
    """Canonical plant -> Java 1.13 name ("poppy"), None for an empty pot / unknown plant."""
    if not plant:
        return None
    item, data = plant
    if isinstance(item, str):
        item = item.split(":", 1)[-1]
        if item.isdigit():
            item = int(item)
    return _POT_BY_LEGACY.get((item, int(data or 0)))


def pot_plant(flat: str):
    v = POT_PLANTS.get(flat.split(":", 1)[-1])
    return ("minecraft:" + v[0], v[2]) if v else None


def _pos(t) -> Tuple[int, int, int]:
    return int(nbt.get(t, "x", 0)), int(nbt.get(t, "y", 0)), int(nbt.get(t, "z", 0))


def _items_from(lst, src) -> list:
    reader = {"legacy": items.from_legacy, "java": items.from_java_modern, "bedrock": items.from_bedrock}[src]
    out = []
    for t in lst or []:
        if isinstance(t, nbt.CompoundTag) and len(t):
            it = reader(t)
            if it is not None and it.get("name") and it["name"] != "air":
                out.append(it)
    return out


def _items_to(its, dst, **kw) -> nbt.ListTag:
    out = nbt.ListTag([], 10)
    for it in its:
        w = items.write(it, dst, **kw)
        if w is not None:
            out.append(w)
    return out


# ============================================================= readers


def from_legacy(t: nbt.CompoundTag) -> Optional[dict]:
    tid = nbt.get(t, "id", "")
    kind = LEGACY_TO_KIND.get(tid)
    if kind is None and tid == "minecraft:cauldron":      # LCE PS4 / Xbox One: the cauldron has a block entity (the 1.12 hub has none)
        kind = "cauldron"
    if kind is None:
        n = str(tid).split(":", 1)[-1]
        kind = JAVA_TO_KIND.get(n)  # 1.11 - 1.12 names
    if kind is None:
        return None
    c = {"kind": kind, "pos": _pos(t)}
    src = "legacy"
    if kind in CONTAINERS or "Items" in t:
        c["items"] = _items_from(nbt.get_tag(t, "Items"), src)
    if kind in CONTAINERS and nbt.get(t, "LootTable"):   # Java 1.9 - 1.12 chests of dungeons, mineshafts...
        name = str(nbt.get(t, "LootTable"))
        c["loot"] = (name if ":" in name else "minecraft:" + name, int(nbt.get(t, "LootTableSeed", 0) or 0))
    if "CustomName" in t:
        c["custom_name"] = items.plain_text(nbt.get(t, "CustomName"))
    if kind == "sign":
        c["front"] = [items.plain_text(nbt.get(t, f"Text{i}", "")) for i in range(1, 5)]
    elif kind == "mob_spawner":
        eid = nbt.get(t, "EntityId")
        if eid is None:
            sd = nbt.get_tag(t, "SpawnData")
            eid = nbt.get(sd, "id") if sd is not None else "Pig"
        e = str(eid).split(":", 1)[-1]
        c["entity"] = ids.ENTITY_OLD_TO_NEW.get(e, e.lower())
        for k in ("Delay", "MinSpawnDelay", "MaxSpawnDelay", "SpawnCount", "MaxNearbyEntities", "RequiredPlayerRange", "SpawnRange"):
            if k in t:
                c[k] = int(nbt.get(t, k))
    elif kind == "bed":
        c["color"] = int(nbt.get(t, "color", 14))
    elif kind == "banner":
        c["base"] = 15 - int(nbt.get(t, "Base", 0))  # legacy dye index -> wool index
        c["patterns"] = [(str(nbt.get(p, "Pattern")), 15 - int(nbt.get(p, "Color", 0))) for p in nbt.get_tag(t, "Patterns") or []]
    elif kind == "skull":
        c["type"] = int(nbt.get(t, "SkullType", 0))
        c["rot"] = int(nbt.get(t, "Rot", 0))
        owner = nbt.get_tag(t, "Owner")
        if owner is not None:
            c["owner"] = owner
    elif kind == "flower_pot":
        item = nbt.get(t, "Item")
        c["plant"] = (item, int(nbt.get(t, "Data", 0)))
    elif kind == "jukebox":
        rec = nbt.get_tag(t, "RecordItem")
        if rec is not None:
            it = items.from_legacy(rec)
            if it:
                c["record"] = it
        elif nbt.get(t, "Record"):
            it = items.from_legacy(nbt.CompoundTag({"id": nbt.ShortTag(int(nbt.get(t, "Record"))), "Count": nbt.ByteTag(1)}))
            if it:
                c["record"] = it
    elif kind == "noteblock":
        c["note"] = int(nbt.get(t, "note", 0))
    elif kind == "command_block":
        _command_from(c, t, "legacy")
    elif kind == "structure_block":
        _structure_from_java(c, t)
    elif kind == "moving_piston":
        _moving_piston_from_legacy(c, t)
    elif kind == "cauldron":
        _cauldron_from_lce(c, t)
    elif kind == "furnace":
        c["burn"] = int(nbt.get(t, "BurnTime", 0))
        c["cook"] = int(nbt.get(t, "CookTime", 0))
    elif kind == "beacon":
        c["primary"] = int(nbt.get(t, "Primary", 0))
        c["secondary"] = int(nbt.get(t, "Secondary", 0))
        c["levels"] = int(nbt.get(t, "Levels", 0))
    return c


def from_java_modern(t: nbt.CompoundTag) -> Optional[dict]:
    tid = str(nbt.get(t, "id", "")).split(":", 1)[-1]
    kind = JAVA_TO_KIND.get(tid)
    if kind is None:
        return from_legacy(t) if tid[:1].isupper() else None
    c = {"kind": kind, "pos": _pos(t)}
    if kind in CONTAINERS:
        c["items"] = _items_from(nbt.get_tag(t, "Items"), "java")
        _read_loot_java(c, t)
    if "CustomName" in t:
        cn = nbt.get_tag(t, "CustomName")
        c["custom_name"] = items._component_text(cn)
    if kind in ("sign", "hanging_sign"):
        if "front_text" in t:
            ft = t["front_text"]
            c["front"] = [_msg(m) for m in nbt.get_tag(ft, "messages") or []]
            c["color"] = str(nbt.get(ft, "color", "black"))
            c["glow"] = bool(nbt.get(ft, "has_glowing_text", 0))
            bt = nbt.get_tag(t, "back_text")
            if bt is not None:
                c["back"] = [_msg(m) for m in nbt.get_tag(bt, "messages") or []]
            c["waxed"] = bool(nbt.get(t, "is_waxed", 0))
        else:
            c["front"] = [items.plain_text(nbt.get(t, f"Text{i}", "")) for i in range(1, 5)]
            c["color"] = str(nbt.get(t, "Color", "black"))
            c["glow"] = bool(nbt.get(t, "GlowingText", 0))
    elif kind == "mob_spawner":
        sd = nbt.get_tag(t, "SpawnData")
        e = None
        if sd is not None:
            ent = nbt.get_tag(sd, "entity")
            e = nbt.get(ent if ent is not None else sd, "id")
        c["entity"] = str(e or "minecraft:pig").split(":", 1)[-1]
        for k in ("Delay", "MinSpawnDelay", "MaxSpawnDelay", "SpawnCount", "MaxNearbyEntities", "RequiredPlayerRange", "SpawnRange"):
            if k in t:
                c[k] = int(nbt.get(t, k))
    elif kind == "banner":
        c["patterns"] = []
        for p in nbt.get_tag(t, "patterns") or nbt.get_tag(t, "Patterns") or []:
            col = nbt.get(p, "color", nbt.get(p, "Color", 0))
            col = items.WOOL.index(col) if isinstance(col, str) and col in items.WOOL else int(col) if not isinstance(col, str) else 0
            c["patterns"].append((str(nbt.get(p, "pattern", nbt.get(p, "Pattern", "b"))).split(":", 1)[-1], col))
    elif kind == "jukebox":
        rec = nbt.get_tag(t, "RecordItem")
        if rec is not None:
            it = items.from_java_modern(rec)
            if it:
                c["record"] = it
    elif kind == "command_block":
        _command_from(c, t, "java")
    elif kind == "beacon":
        c["levels"] = int(nbt.get(t, "Levels", 0))
    if kind in _JAVA_READ:
        _JAVA_READ[kind](c, t)
    return c


def _msg(m) -> str:
    v = m.py_data if isinstance(m, nbt.StringTag) else None
    if v is None:
        try:
            import json

            return items.plain_text(json.dumps(items._snbt_text(m)))
        except Exception:  # noqa: BLE001
            return ""
    return items.plain_text(v)


def from_bedrock(t: nbt.CompoundTag) -> Optional[dict]:
    tid = str(nbt.get(t, "id", ""))
    kind = BEDROCK_TO_KIND.get(tid)
    if kind is None:
        return None
    c = {"kind": kind, "pos": _pos(t)}
    if kind in CONTAINERS:
        c["items"] = _items_from(nbt.get_tag(t, "Items"), "bedrock")
        _read_loot_bedrock(c, t)
        if kind == "chest" and "pairx" in t:
            c["pair"] = (int(nbt.get(t, "pairx")), int(nbt.get(t, "pairz")))
    if "CustomName" in t:
        c["custom_name"] = str(nbt.get(t, "CustomName"))
    if kind in ("sign", "hanging_sign"):
        ft = nbt.get_tag(t, "FrontText")
        text = nbt.get(ft, "Text", "") if ft is not None else nbt.get(t, "Text", "")
        c["front"] = (str(text).split("\n") + ["", "", "", ""])[:4]
        bt = nbt.get_tag(t, "BackText")
        if bt is not None:
            c["back"] = (str(nbt.get(bt, "Text", "")).split("\n") + ["", "", "", ""])[:4]
        c["waxed"] = bool(nbt.get(t, "IsWaxed", 0))
    elif kind == "mob_spawner":
        c["entity"] = str(nbt.get(t, "EntityIdentifier", "minecraft:pig")).split(":", 1)[-1]
        for k in ("Delay", "MinSpawnDelay", "MaxSpawnDelay", "SpawnCount", "MaxNearbyEntities", "RequiredPlayerRange", "SpawnRange"):
            if k in t:
                c[k] = int(nbt.get(t, k))
    elif kind == "bed":
        c["color"] = int(nbt.get(t, "color", 14))
    elif kind == "banner":
        c["base"] = 15 - int(nbt.get(t, "Base", 0))
        c["patterns"] = [(str(nbt.get(p, "Pattern")), 15 - int(nbt.get(p, "Color", 0))) for p in nbt.get_tag(t, "Patterns") or []]
    elif kind == "skull":
        c["type"] = int(nbt.get(t, "SkullType", 0))
        c["rot"] = int(round(float(nbt.get(t, "Rotation", 0.0)) / 22.5)) & 15
    elif kind == "jukebox":
        rec = nbt.get_tag(t, "RecordItem")
        if rec is not None:
            it = items.from_bedrock(rec)
            if it:
                c["record"] = it
    elif kind == "flower_pot":
        pb = nbt.get_tag(t, "PlantBlock")
        if pb is not None and "name" in pb:
            states = nbt.get_tag(pb, "states") or nbt.CompoundTag()
            key = tuple(sorted(states.items(), key=lambda kv: kv[0]))
            v = int(nbt.get(pb, "version", 0) or 0)
            for ver in ((v >> 24 & 255, v >> 16 & 255, v >> 8 & 255), (1, 21, 0), (1, 16, 0)):
                if ver[0] < 1:
                    continue
                flat = items._bedrock_block_to_flat(str(nbt.get(pb, "name")), key, ver)
                if flat and pot_plant(flat):
                    c["plant"] = pot_plant(flat)
                    break
    elif kind == "noteblock":
        c["note"] = int(nbt.get(t, "note", 0))
    elif kind == "command_block":
        _command_from(c, t, "bedrock")
    if kind in _BEDROCK_READ:
        _BEDROCK_READ[kind](c, t)
    return c


# ============================================================= writers


def to_legacy(c: dict, lce: bool = False) -> Optional[nbt.CompoundTag]:
    kind = c["kind"]
    lid = KINDS[kind][0]
    if lid is None:
        return None
    x, y, z = c["pos"]
    t = nbt.CompoundTag({"id": nbt.StringTag(lid), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z)})
    if "items" in c:
        t["Items"] = _items_to(c["items"], "legacy")
    if kind in CONTAINERS and not lce:                    # Java 1.9+; the older games ignore them
        _write_loot_java(c, t)
    if c.get("custom_name"):
        t["CustomName"] = nbt.StringTag(c["custom_name"])
    if kind in ("sign", "hanging_sign"):
        lines = (list(c.get("front") or []) + ["", "", "", ""])[:4]
        for i, line in enumerate(lines, 1):
            t[f"Text{i}"] = nbt.StringTag(line[:15] if lce else line)
    elif kind == "mob_spawner":
        old, _extra = ids.entity_to_old(c.get("entity", "pig"))
        t["EntityId"] = nbt.StringTag(old or "Pig")
        for k in ("Delay", "MinSpawnDelay", "MaxSpawnDelay", "SpawnCount", "MaxNearbyEntities", "RequiredPlayerRange", "SpawnRange"):
            if k in c:
                t[k] = nbt.ShortTag(c[k])
        t.setdefault("Delay", nbt.ShortTag(20))
    elif kind == "bed":
        t["color"] = nbt.IntTag(c.get("color", 14))
    elif kind == "banner":
        t["Base"] = nbt.IntTag(15 - c.get("base", 0))
        t["Patterns"] = nbt.ListTag([nbt.CompoundTag({"Pattern": nbt.StringTag(p), "Color": nbt.IntTag(15 - col)})
                                     for p, col in c.get("patterns", []) if len(p) <= 4], 10)
    elif kind == "skull":
        t["SkullType"] = nbt.ByteTag(c.get("type", 0))
        t["Rot"] = nbt.ByteTag(c.get("rot", 0))
    elif kind == "flower_pot":
        plant = c.get("plant")
        flat = pot_flat(plant)
        if flat:  # numeric id: read by Java 1.7 - 1.12 and LCE alike
            t["Item"] = nbt.IntTag(POT_PLANTS[flat][1])
            t["Data"] = nbt.IntTag(POT_PLANTS[flat][2])
        elif plant:
            t["Item"] = nbt.IntTag(plant[0]) if isinstance(plant[0], int) else nbt.StringTag(str(plant[0]))
            t["Data"] = nbt.IntTag(plant[1])
    elif kind == "jukebox" and c.get("record"):
        r = items.to_legacy(c["record"])
        if r is not None:
            t["Record"] = nbt.IntTag(int(r["id"].py_data))
            t["RecordItem"] = r
    elif kind == "noteblock":
        t["note"] = nbt.ByteTag(c.get("note", 0))
    elif kind == "command_block":
        _command_to_java(c, t, 0)
    elif kind == "structure_block":
        _structure_to_java(c, t, 0)
    elif kind == "moving_piston":
        _moving_piston_to_legacy(c, t)
    elif kind == "furnace":
        t["BurnTime"] = nbt.ShortTag(c.get("burn", 0))
        t["CookTime"] = nbt.ShortTag(c.get("cook", 0))
    elif kind == "beacon":
        t["Primary"] = nbt.IntTag(c.get("primary", 0))
        t["Secondary"] = nbt.IntTag(c.get("secondary", 0))
        t["Levels"] = nbt.IntTag(c.get("levels", 0))
    return t


SIGN_COLORS_BEDROCK = {"black": -16777216, "white": -1, "red": -5231066, "blue": -12827478}


def to_bedrock(c: dict, version) -> Optional[nbt.CompoundTag]:
    kind = c["kind"]
    bid = KINDS[kind][2]
    if bid is None or not exists_in_bedrock(kind, version):
        return None
    x, y, z = c["pos"]
    t = nbt.CompoundTag({"id": nbt.StringTag(bid), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z),
                         "isMovable": nbt.ByteTag(1)})
    if "items" in c:
        t["Items"] = _items_to(c["items"], "bedrock", version=tuple(version))
        t["Findable"] = nbt.ByteTag(0)
        if kind in CONTAINERS:
            _write_loot_bedrock(c, t)
    if c.get("pair"):
        t["pairx"], t["pairz"] = nbt.IntTag(c["pair"][0]), nbt.IntTag(c["pair"][1])
        t["pairlead"] = nbt.ByteTag(1 if (x, z) < tuple(c["pair"]) else 0)
    if c.get("custom_name"):
        t["CustomName"] = nbt.StringTag(c["custom_name"])
    if kind in ("sign", "hanging_sign"):
        front = "\n".join((list(c.get("front") or []) + ["", "", "", ""])[:4]).rstrip("\n")
        back = "\n".join((list(c.get("back") or []) + ["", "", "", ""])[:4]).rstrip("\n")
        color = nbt.IntTag(SIGN_COLORS_BEDROCK.get(c.get("color", "black"), -16777216))
        if tuple(version) >= (1, 19, 80):
            def side(text):
                return nbt.CompoundTag({"Text": nbt.StringTag(text), "SignTextColor": color,
                                        "IgnoreLighting": nbt.ByteTag(1 if c.get("glow") else 0),
                                        "HideGlowOutline": nbt.ByteTag(0), "PersistFormatting": nbt.ByteTag(1),
                                        "TextOwner": nbt.StringTag("")})

            t["FrontText"] = side(front)
            t["BackText"] = side(back)
            t["IsWaxed"] = nbt.ByteTag(1 if c.get("waxed") else 0)
        else:
            t["Text"] = nbt.StringTag(front)
            t["TextOwner"] = nbt.StringTag("")
            t["SignTextColor"] = color
    elif kind == "mob_spawner":
        t["EntityIdentifier"] = nbt.StringTag("minecraft:" + _bedrock_entity(c.get("entity", "pig")))
        for k in ("Delay", "MinSpawnDelay", "MaxSpawnDelay", "SpawnCount", "MaxNearbyEntities", "RequiredPlayerRange", "SpawnRange"):
            if k in c:
                t[k] = nbt.ShortTag(c[k])
    elif kind == "bed":
        t["color"] = nbt.ByteTag(c.get("color", 14))
    elif kind == "banner":
        t["Base"] = nbt.IntTag(15 - c.get("base", 0))
        t["Patterns"] = nbt.ListTag([nbt.CompoundTag({"Pattern": nbt.StringTag(p), "Color": nbt.IntTag(15 - col)})
                                     for p, col in c.get("patterns", [])], 10)
        t["Type"] = nbt.IntTag(0)
    elif kind == "skull":
        t["SkullType"] = nbt.ByteTag(c.get("type", 0))
        t["Rotation"] = nbt.FloatTag(c.get("rot", 0) * 22.5)
    elif kind == "jukebox" and c.get("record"):
        r = items.to_bedrock(c["record"], tuple(version))
        if r is not None:
            t["RecordItem"] = r
    elif kind == "flower_pot" and pot_flat(c.get("plant")):
        b = items._bedrock_block_for_flat(pot_flat(c["plant"]), tuple(version))
        if b is not None:
            t["PlantBlock"] = nbt.CompoundTag({"name": nbt.StringTag(b[0]), "states": nbt.CompoundTag(dict(b[1])),
                                               "version": nbt.IntTag(items._bedrock_block_version(version))})
    elif kind == "noteblock":
        t["note"] = nbt.ByteTag(c.get("note", 0))
    elif kind == "command_block":
        _command_to_bedrock(c, t)
    elif kind == "furnace":
        t["BurnTime"] = nbt.ShortTag(c.get("burn", 0))
        t["CookTime"] = nbt.ShortTag(c.get("cook", 0))
    elif kind == "beacon":
        t["primary"] = nbt.IntTag(c.get("primary", 0))
        t["secondary"] = nbt.IntTag(c.get("secondary", 0))
    if kind in _BEDROCK_WRITE:
        _BEDROCK_WRITE[kind](c, t, version)
    return t


def to_java_modern(c: dict, data_version: int) -> Optional[nbt.CompoundTag]:
    kind = c["kind"]
    jid = KINDS[kind][1]
    if jid is None or not exists_in_java(kind, data_version):
        return None
    if kind == "chest" and c.get("java_id"):             # a copper chest block (java.modern.resolve_kinds)
        jid = c["java_id"]
    if kind == "mob_spawner" and data_version >= 3818:
        jid = "spawner"
    x, y, z = c["pos"]
    t = nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + jid), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z)})
    if "items" in c:
        t["Items"] = _items_to(c["items"], "java", data_version=data_version)
    if kind in CONTAINERS:
        _write_loot_java(c, t)
    if c.get("custom_name"):
        t["CustomName"] = nbt.StringTag(c["custom_name"] if data_version >= items.TEXT_NBT_DV
                                        else items.json_text(c["custom_name"]))
    if kind in ("sign", "hanging_sign"):
        front = (list(c.get("front") or []) + ["", "", "", ""])[:4]
        back = (list(c.get("back") or []) + ["", "", "", ""])[:4]
        color = c.get("color", "black")
        if data_version >= 3463:  # 1.20 two-sided signs
            def side(lines):
                msgs = nbt.ListTag([nbt.StringTag(l) if data_version >= items.TEXT_NBT_DV else nbt.StringTag(items.json_text(l)) for l in lines], 8)
                return nbt.CompoundTag({"messages": msgs, "color": nbt.StringTag(color),
                                        "has_glowing_text": nbt.ByteTag(1 if c.get("glow") else 0)})

            t["front_text"] = side(front)
            t["back_text"] = side(back)
            t["is_waxed"] = nbt.ByteTag(1 if c.get("waxed") else 0)
        else:
            for i, l in enumerate(front, 1):
                t[f"Text{i}"] = nbt.StringTag(items.json_text(l))
            t["Color"] = nbt.StringTag(color)
            t["GlowingText"] = nbt.ByteTag(1 if c.get("glow") else 0)
    elif kind == "mob_spawner":
        e = nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + c.get("entity", "pig"))})
        t["SpawnData"] = nbt.CompoundTag({"entity": e}) if data_version >= 2825 else e
        for k in ("Delay", "MinSpawnDelay", "MaxSpawnDelay", "SpawnCount", "MaxNearbyEntities", "RequiredPlayerRange", "SpawnRange"):
            if k in c:
                t[k] = nbt.ShortTag(c[k])
    elif kind == "banner":
        if data_version >= 3819:
            t["patterns"] = nbt.ListTag([nbt.CompoundTag({"pattern": nbt.StringTag("minecraft:" + _pattern_name(p)),
                                                          "color": nbt.StringTag(items.WOOL[col])})
                                         for p, col in c.get("patterns", [])], 10)
        else:
            t["Patterns"] = nbt.ListTag([nbt.CompoundTag({"Pattern": nbt.StringTag(p), "Color": nbt.IntTag(col)})
                                         for p, col in c.get("patterns", [])], 10)
    elif kind == "jukebox" and c.get("record"):
        t["RecordItem"] = items.to_java_modern(c["record"], data_version)
    elif kind == "command_block":
        _command_to_java(c, t, data_version)
    elif kind == "beacon":
        t["Levels"] = nbt.IntTag(c.get("levels", 0))
    if kind in _JAVA_WRITE:
        _JAVA_WRITE[kind](c, t, data_version)
    return t


_PATTERNS = {"b": "base", "bs": "stripe_bottom", "ts": "stripe_top", "ls": "stripe_left", "rs": "stripe_right",
             "cs": "stripe_center", "ms": "stripe_middle", "drs": "stripe_downright", "dls": "stripe_downleft",
             "ss": "small_stripes", "cr": "cross", "sc": "straight_cross", "ld": "diagonal_left",
             "rud": "diagonal_right", "lud": "diagonal_up_left", "rd": "diagonal_up_right", "vh": "half_vertical",
             "vhr": "half_vertical_right", "hh": "half_horizontal", "hhb": "half_horizontal_bottom",
             "bl": "square_bottom_left", "br": "square_bottom_right", "tl": "square_top_left",
             "tr": "square_top_right", "bt": "triangle_bottom", "tt": "triangle_top", "bts": "triangles_bottom",
             "tts": "triangles_top", "mc": "circle", "mr": "rhombus", "bo": "border", "cbo": "curly_border",
             "bri": "bricks", "gra": "gradient", "gru": "gradient_up", "cre": "creeper", "sku": "skull",
             "flo": "flower", "moj": "mojang", "glb": "globe", "pig": "piglin"}


def _pattern_name(p: str) -> str:
    return _PATTERNS.get(p, p)


def _bedrock_entity(name: str) -> str:
    return {"zombified_piglin": "zombie_pigman", "zombie_pigman": "zombie_pigman", "snow_golem": "snow_golem",
            "snowman": "snow_golem", "villager_golem": "iron_golem", "mooshroom": "mooshroom",
            "villager": "villager_v2", "zombie_villager": "zombie_villager_v2"}.get(name, name)


# ============================================================= newer block entities
# Block entities of Java 1.14+ / Bedrock that the legacy hub does not know.  Each kind has up to four
# small functions: read from Java (``_JAVA_READ``) / Bedrock (``_BEDROCK_READ``) into the canonical dict
# and write it as Java (``_JAVA_WRITE``) / Bedrock (``_BEDROCK_WRITE``); kinds that hold nothing are
# written as their id only, the game fills them in again.  Item stacks go through ``items`` and so follow
# the version of the target (Java components from 1.20.5, Bedrock names / block versions).
#
# kind -> (first Java DataVersion, first Bedrock version) that has the block, from PyMCTranslate's tables
# (the first version whose block list holds it); a target older than that gets no block entity (its block is
# replaced by Amulet).  Exceptions: crafter / trial_spawner / vault were only an experiment before the 1.21
# release (3953, Bedrock 1.21.0) and their data changed on the way, so they start with it.
MIN_VERSION: Dict[str, Tuple[int, Tuple[int, ...]]] = {
    "conduit": (1519, (1, 5, 0)),
    "campfire": (1952, (1, 11, 0)), "lectern": (1952, (1, 10, 0)), "bell": (1952, (1, 11, 0)),
    "beehive": (2225, (1, 14, 0)), "bee_nest": (2225, (1, 14, 0)),
    "soul_campfire": (2566, (1, 16, 0)),
    "sculk_sensor": (2724, (1, 19, 0)), "sculk_shrieker": (3104, (1, 19, 0)), "sculk_catalyst": (3104, (1, 19, 0)),
    "chiseled_bookshelf": (3218, (1, 19, 60)),
    "decorated_pot": (3337, (1, 19, 70)), "brushable_block": (3337, (1, 19, 70)),
    "calibrated_sculk_sensor": (3463, (1, 19, 80)),
    "crafter": (3953, (1, 21, 0)), "trial_spawner": (3953, (1, 21, 0)), "vault": (3953, (1, 21, 0)),
    "creaking_heart": (4080, (1, 21, 50)),
    "shelf": (4553, (1, 21, 110)), "copper_golem_statue": (4553, (1, 21, 110)),
    "jigsaw": (1952, (1, 13, 0)),
    "lodestone": (2566, (1, 16, 0)),
    "test_block": (4325, (999, 0, 0)), "test_instance_block": (4325, (999, 0, 0)),   # 1.21.5, Java only
}
DECORATED_POT_SHERDS_DV = 3438   # 1.20: "shards" -> "sherds" (Bedrock 1.20.0)
TRIAL_CONFIG_REF_DV = 4556       # a trial spawner's configuration as the name of a data pack one (a string): seen in 1.21.10 worlds
BEEHIVE_RENAME_DV = 3818         # 1.20.5: Bees / EntityData / MinOccupationTicks -> bees / entity_data / min_ticks_in_hive
GOLEM_POSES = ("standing", "sitting", "running", "star")


def exists_in_java(kind: str, data_version: int) -> bool:
    """Whether Java data of ``data_version`` has the block entity ``kind``."""
    m = MIN_VERSION.get(kind)
    return m is None or data_version >= m[0]


def exists_in_bedrock(kind: str, version) -> bool:
    m = MIN_VERSION.get(kind)
    return m is None or tuple(version) >= m[1]


# loot tables: Java "minecraft:chests/simple_dungeon" <-> Bedrock "loot_tables/chests/simple_dungeon.json"
# (je2be's LootTable); these are the ones that are not the plain rename
_LOOT_BEDROCK = {"minecraft:chests/buried_treasure": "loot_tables/chests/buriedtreasure.json",
                 "minecraft:chests/jungle_temple_dispenser": "loot_tables/chests/dispenser_trap.json",
                 "minecraft:chests/shipwreck_map": "loot_tables/chests/shipwreck.json",
                 "minecraft:chests/shipwreck_supply": "loot_tables/chests/shipwrecksupply.json",
                 "minecraft:chests/shipwreck_treasure": "loot_tables/chests/shipwrecktreasure.json",
                 "minecraft:archaeology/desert_pyramid": "loot_tables/entities/desert_pyramid_brushable_block.json",
                 "minecraft:archaeology/desert_well": "loot_tables/entities/desert_well_brushable_block.json",
                 "minecraft:archaeology/ocean_ruin_cold": "loot_tables/entities/cold_ocean_ruins_brushable_block.json",
                 "minecraft:archaeology/ocean_ruin_warm": "loot_tables/entities/warm_ocean_ruins_brushable_block.json",
                 "minecraft:archaeology/trail_ruins_common": "loot_tables/entities/trail_ruins_brushable_block_common.json",
                 "minecraft:archaeology/trail_ruins_rare": "loot_tables/entities/trail_ruins_brushable_block_rare.json"}
_LOOT_JAVA = {v: k for k, v in _LOOT_BEDROCK.items()}


def loot_to_bedrock(name: str) -> Optional[str]:
    if name in _LOOT_BEDROCK:
        return _LOOT_BEDROCK[name]
    if name.startswith("minecraft:") and "/" in name:
        return "loot_tables/" + name[10:] + ".json"
    return None


def loot_from_bedrock(name: str) -> Optional[str]:
    if name in _LOOT_JAVA:
        return _LOOT_JAVA[name]
    if name.startswith("loot_tables/") and name.endswith(".json"):
        return "minecraft:" + name[12:-5]
    return None


def _seed_to_int(seed: int) -> int:
    """Java's 64 bit loot table seed folded into Bedrock's 32 bit one."""
    v = (seed ^ (seed >> 32)) & 0xFFFFFFFF
    return v - (1 << 32) if v >= 1 << 31 else v


def _item_from(t, src) -> Optional[dict]:
    if not isinstance(t, nbt.CompoundTag) or not len(t):
        return None
    got = _items_from([t], src)
    return got[0] if got else None


def _item_to(it, dst, **kw) -> Optional[nbt.CompoundTag]:
    """A single item stack, without a slot."""
    it = dict(it)
    it["slot"] = None
    return items.write(it, dst, **kw)


def _empty_bedrock_item() -> nbt.CompoundTag:
    return nbt.CompoundTag({"Count": nbt.ByteTag(0), "Damage": nbt.ShortTag(0), "Name": nbt.StringTag(""),
                            "WasPickedUp": nbt.ByteTag(0)})


def _slots_from_java(t, key="Items") -> list:
    return [it for it in _items_from(nbt.get_tag(t, key), "java") if it.get("slot") is not None]


def _slots_from_bedrock(t, key="Items") -> list:
    """The stacks of a Bedrock container that has no Slot tags: the list index is the slot."""
    out = []
    for i, it in enumerate(nbt.get_tag(t, key) or []):
        s = _item_from(it, "bedrock") if isinstance(it, nbt.CompoundTag) and int(nbt.get(it, "Count", 0) or 0) > 0 else None
        if s is not None:
            s["slot"] = i
            out.append(s)
    return out


def _slots_to_bedrock_list(slots, size: int, version) -> nbt.ListTag:
    out = [None] * size
    for it in slots:
        i = it.get("slot")
        if i is not None and 0 <= int(i) < size:
            out[int(i)] = _item_to(it, "bedrock", version=tuple(version))
    return nbt.ListTag([o if o is not None else _empty_bedrock_item() for o in out], 10)


def _slots_to_java_list(slots, data_version: int) -> nbt.ListTag:
    return _items_to([it for it in slots if it.get("slot") is not None], "java", data_version=data_version)


def _ints(tag) -> list:
    return [int(v) for v in tag.py_data] if tag is not None else []


def _int_array(values) -> nbt.IntArrayTag:
    import numpy as np

    return nbt.IntArrayTag(np.array(list(values), np.int32))


# ---- loot table + item (decorated pot, brushable block)
def _read_loot_java(c, t):
    if "LootTable" in t:
        c["loot"] = (str(nbt.get(t, "LootTable")), int(nbt.get(t, "LootTableSeed", 0) or 0))


def _read_loot_bedrock(c, t):
    name = loot_from_bedrock(str(nbt.get(t, "LootTable", "")))
    if name is not None and not name.endswith("/empty_brushable_block"):  # Bedrock's "nothing to find"
        c["loot"] = (name, int(nbt.get(t, "LootTableSeed", 0) or 0))


def _write_loot_java(c, t) -> bool:
    if not c.get("loot"):
        return False
    t["LootTable"] = nbt.StringTag(c["loot"][0])
    if c["loot"][1]:
        t["LootTableSeed"] = nbt.LongTag(c["loot"][1])
    return True


def _write_loot_bedrock(c, t) -> bool:
    name = loot_to_bedrock(c["loot"][0]) if c.get("loot") else None
    if name is None:
        return False
    t["LootTable"] = nbt.StringTag(name)
    t["LootTableSeed"] = nbt.IntTag(_seed_to_int(c["loot"][1]))
    return True


# ---- decorated pot
def _sherds(names) -> Optional[list]:
    names = [str(n).split(":", 1)[-1] or "brick" for n in names][:4]
    names += ["brick"] * (4 - len(names))
    return names if any(n != "brick" for n in names) else None


def _decorated_pot_from_java(c, t):
    sh = nbt.get_tag(t, "sherds")
    if sh is None:
        sh = nbt.get_tag(t, "shards")
    c["sherds"] = _sherds(s.py_data for s in sh or [] if isinstance(s, nbt.StringTag))
    _read_loot_java(c, t)
    c["item"] = _item_from(nbt.get_tag(t, "item"), "java")


def _decorated_pot_from_bedrock(c, t):
    sh = nbt.get_tag(t, "sherds")
    if sh is None:
        sh = nbt.get_tag(t, "shards")
    c["sherds"] = _sherds(s.py_data for s in sh or [] if isinstance(s, nbt.StringTag))
    _read_loot_bedrock(c, t)
    c["item"] = _item_from(nbt.get_tag(t, "item"), "bedrock")


def _decorated_pot_to_java(c, t, dv):
    if c.get("sherds"):
        t["sherds" if dv >= DECORATED_POT_SHERDS_DV else "shards"] = nbt.ListTag(
            [nbt.StringTag("minecraft:" + s) for s in c["sherds"]], 8)
    if not _write_loot_java(c, t) and c.get("item"):
        t["item"] = _item_to(c["item"], "java", data_version=dv)


def _decorated_pot_to_bedrock(c, t, version):
    t["animation"] = nbt.ByteTag(0)
    if c.get("sherds"):
        t["sherds" if tuple(version) >= (1, 20, 0) else "shards"] = nbt.ListTag(
            [nbt.StringTag("minecraft:" + s) for s in c["sherds"]], 8)
    if not _write_loot_bedrock(c, t) and c.get("item"):
        w = _item_to(c["item"], "bedrock", version=tuple(version))
        if w is not None:
            t["item"] = w


# ---- brushable block (suspicious sand / gravel): the block itself is in ``block``, how far it was brushed in ``dusted``
def _brushable_from_java(c, t):
    _read_loot_java(c, t)
    c["item"] = _item_from(nbt.get_tag(t, "item"), "java")


def _brushable_from_bedrock(c, t):
    _read_loot_bedrock(c, t)
    c["item"] = _item_from(nbt.get_tag(t, "item"), "bedrock")
    c["block"] = str(nbt.get(t, "type", "minecraft:suspicious_sand")).split(":", 1)[-1]
    c["dusted"] = int(nbt.get(t, "brush_count", 0) or 0)


def _brushable_to_java(c, t, dv):
    if dv < 3438:  # 1.20 renamed the block entity
        t["id"] = nbt.StringTag("minecraft:suspicious_sand")
    if not _write_loot_java(c, t) and c.get("item"):
        t["item"] = _item_to(c["item"], "java", data_version=dv)


def _brushable_to_bedrock(c, t, version):
    t["type"] = nbt.StringTag("minecraft:" + c.get("block", "suspicious_sand"))
    t["brush_count"] = nbt.IntTag(int(c.get("dusted", 0)))
    t["brush_direction"] = nbt.ByteTag(6)
    if not _write_loot_bedrock(c, t) and c.get("item"):
        w = _item_to(c["item"], "bedrock", version=tuple(version))
        if w is not None:
            t["item"] = w


# ---- campfire: 4 stacks with their cooking times
def _campfire_from_java(c, t):
    c["slots"] = [it for it in _slots_from_java(t) if 0 <= it["slot"] < 4]
    c["cook"] = (_ints(nbt.get_tag(t, "CookingTimes")) + [0] * 4)[:4]
    c["cook_total"] = (_ints(nbt.get_tag(t, "CookingTotalTimes")) + [0] * 4)[:4]


def _campfire_from_bedrock(c, t):
    c["slots"], c["cook"] = [], []
    for i in range(4):
        it = _item_from(nbt.get_tag(t, f"Item{i + 1}"), "bedrock")
        if it is not None:
            it["slot"] = i
            c["slots"].append(it)
        c["cook"].append(int(nbt.get(t, f"ItemTime{i + 1}", 0) or 0))
    c["cook_total"] = [600 if any(s["slot"] == i for s in c["slots"]) or c["cook"][i] > 0 else 0 for i in range(4)]


def _campfire_to_java(c, t, dv):
    t["Items"] = _slots_to_java_list(c.get("slots", []), dv)
    cook = (list(c.get("cook") or []) + [0] * 4)[:4]
    total = (list(c.get("cook_total") or []) + [0] * 4)[:4]
    for i, s in enumerate(c.get("slots", [])):  # a stack that cooks needs a total time
        j = s.get("slot")
        if j is not None and 0 <= j < 4 and not total[j]:
            total[j] = 600
    t["CookingTimes"] = _int_array(cook)
    t["CookingTotalTimes"] = _int_array(total)


def _campfire_to_bedrock(c, t, version):
    cook = (list(c.get("cook") or []) + [0] * 4)[:4]
    for it in c.get("slots", []):
        i = it.get("slot")
        if i is not None and 0 <= i < 4:
            w = _item_to(it, "bedrock", version=tuple(version))
            if w is not None:
                t[f"Item{i + 1}"] = w
    for i in range(4):
        t[f"ItemTime{i + 1}"] = nbt.IntTag(cook[i])


# ---- beehive / bee nest: the bees inside, as canonical entities
def _bee(entity: dict, minimum: int, ticks: int, nectar: bool, stung: bool = False) -> dict:
    return {"entity": entity, "min": minimum, "ticks": ticks, "nectar": nectar, "stung": stung}


def _beehive_from_java(c, t):
    c["bees"] = []
    lst = nbt.get_tag(t, "bees")
    if lst is None:
        lst = nbt.get_tag(t, "Bees")
    for b in lst or []:
        data = nbt.get_tag(b, "entity_data")
        if data is None:
            data = nbt.get_tag(b, "EntityData")
        e = ent.from_java_modern(data) if data is not None else None
        if e is None or e.get("name") != "bee":
            continue
        c["bees"].append(_bee(e, int(nbt.get(b, "min_ticks_in_hive", nbt.get(b, "MinOccupationTicks", 0)) or 0),
                              int(nbt.get(b, "ticks_in_hive", nbt.get(b, "TicksInHive", 0)) or 0),
                              bool(nbt.get(data, "HasNectar", 0)), bool(nbt.get(data, "HasStung", 0))))


def _beehive_from_bedrock(c, t):
    c["bees"] = []
    for o in nbt.get_tag(t, "Occupants") or []:
        data = nbt.get_tag(o, "SaveData")
        e = ent.from_bedrock(data if data is not None else o)
        if e is None or e.get("name") != "bee":
            continue
        props = nbt.get_tag(data if data is not None else o, "properties")
        c["bees"].append(_bee(e, int(nbt.get(o, "TicksLeftToStay", 0) or 0), 0,
                              bool(nbt.get(props, "minecraft:has_nectar", 0)) if props is not None else False))


_BEE_DROP = ("Pos", "Motion", "Rotation", "OnGround", "UUID")  # what the game itself strips from a bee in a hive


def _beehive_to_java(c, t, dv):
    new = dv >= BEEHIVE_RENAME_DV
    bees = nbt.ListTag([], 10)
    for b in c.get("bees", []):
        e = ent.to_java_modern(b["entity"], dv)
        if e is None:
            continue
        for k in _BEE_DROP:
            e.pop(k, None)
        e["HasNectar"] = nbt.ByteTag(1 if b.get("nectar") else 0)
        e["HasStung"] = nbt.ByteTag(1 if b.get("stung") else 0)
        bees.append(nbt.CompoundTag({
            "entity_data" if new else "EntityData": e,
            "min_ticks_in_hive" if new else "MinOccupationTicks": nbt.IntTag(int(b.get("min", 0))),
            "ticks_in_hive" if new else "TicksInHive": nbt.IntTag(int(b.get("ticks", 0)))}))
    t["bees" if new else "Bees"] = bees


_BEE_IDS = ent.ActorIds()


def _beehive_to_bedrock(c, t, version):
    occupants = nbt.ListTag([], 10)
    x, y, z = c["pos"]
    for b in c.get("bees", []):
        e = dict(b["entity"])
        if not any(e.get("pos") or ()):
            e["pos"] = (x + 0.5, y + 0.5, z + 0.5)
        _key, uid = _BEE_IDS.next()
        save = ent.to_bedrock(e, uid, None, tuple(version))
        if save is None:
            continue
        if b.get("nectar"):
            save["properties"] = nbt.CompoundTag({"minecraft:has_nectar": nbt.ByteTag(1)})
            save["definitions"].append(nbt.StringTag("+has_nectar"))
        left = max(0, int(b.get("min", 0)) - int(b.get("ticks", 0)))
        occupants.append(nbt.CompoundTag({"ActorIdentifier": nbt.StringTag("minecraft:bee<>"), "SaveData": save,
                                          "TicksLeftToStay": nbt.IntTag(left)}))
    t["Occupants"] = occupants
    t["ShouldSpawnBees"] = nbt.ByteTag(0)


# ---- lectern: the book (a canonical item) and the page
def _lectern_from_java(c, t):
    c["book"] = _item_from(nbt.get_tag(t, "Book"), "java")
    c["page"] = int(nbt.get(t, "Page", 0) or 0)


def _lectern_from_bedrock(c, t):
    c["book"] = _item_from(nbt.get_tag(t, "book"), "bedrock")
    c["page"] = max(0, int(nbt.get(t, "page", 0) or 0))


def _lectern_to_java(c, t, dv):
    if c.get("book"):
        t["Book"] = _item_to(c["book"], "java", data_version=dv)
        t["Page"] = nbt.IntTag(int(c.get("page", 0)))


def _lectern_to_bedrock(c, t, version):
    w = _item_to(c["book"], "bedrock", version=tuple(version)) if c.get("book") else None
    if w is not None:
        t["book"] = w
        t["page"] = nbt.IntTag(int(c.get("page", 0)))
        t["hasBook"] = nbt.ByteTag(1)
        t["totalPages"] = nbt.IntTag(len(c["book"].get("pages") or []))


# ---- chiseled bookshelf / shelf: stacks by slot (6 / 3)
def _chiseled_bookshelf_from_java(c, t):
    c["slots"] = [it for it in _slots_from_java(t) if 0 <= it["slot"] < 6]
    c["last_slot"] = int(nbt.get(t, "last_interacted_slot", -1))


def _chiseled_bookshelf_from_bedrock(c, t):
    c["slots"] = [it for it in _slots_from_bedrock(t) if it["slot"] < 6]
    c["last_slot"] = int(nbt.get(t, "LastInteractedSlot", -1))


def _chiseled_bookshelf_to_java(c, t, dv):
    t["Items"] = _slots_to_java_list(c.get("slots", []), dv)
    t["last_interacted_slot"] = nbt.IntTag(int(c.get("last_slot", -1)))


def _chiseled_bookshelf_to_bedrock(c, t, version):
    t["Items"] = _slots_to_bedrock_list(c.get("slots", []), 6, version)
    t["LastInteractedSlot"] = nbt.IntTag(int(c.get("last_slot", -1)))


def _shelf_from_java(c, t):
    c["slots"] = [it for it in _slots_from_java(t) if 0 <= it["slot"] < 3]
    c["align_bottom"] = bool(nbt.get(t, "align_items_to_bottom", 0))


def _shelf_from_bedrock(c, t):
    c["slots"] = [it for it in _slots_from_bedrock(t) if it["slot"] < 3]


def _shelf_to_java(c, t, dv):
    t["Items"] = _slots_to_java_list(c.get("slots", []), dv)
    t["align_items_to_bottom"] = nbt.ByteTag(1 if c.get("align_bottom") else 0)


def _shelf_to_bedrock(c, t, version):
    if c.get("slots"):
        t["Items"] = _slots_to_bedrock_list(c["slots"], 3, version)


# ---- crafter: 9 stacks, the disabled slots (a list in Java, a bit mask in Bedrock)
def _crafter_from_java(c, t):
    c["slots"] = [it for it in _slots_from_java(t) if 0 <= it["slot"] < 9]
    c["disabled"] = [i for i in _ints(nbt.get_tag(t, "disabled_slots")) if 0 <= i < 9]
    c["triggered"] = int(nbt.get(t, "triggered", 0) or 0)
    c["ticks"] = int(nbt.get(t, "crafting_ticks_remaining", 0) or 0)


def _crafter_from_bedrock(c, t):
    c["slots"] = [it for it in _items_from(nbt.get_tag(t, "Items"), "bedrock") if it.get("slot") is not None]
    mask = int(nbt.get(t, "disabled_slots", 0) or 0) & 0x1FF
    c["disabled"] = [i for i in range(9) if mask >> i & 1]


def _crafter_to_java(c, t, dv):
    t["Items"] = _slots_to_java_list(c.get("slots", []), dv)
    t["disabled_slots"] = _int_array(c.get("disabled", []))
    t["triggered"] = nbt.IntTag(int(c.get("triggered", 0)))
    t["crafting_ticks_remaining"] = nbt.IntTag(int(c.get("ticks", 0)))


def _crafter_to_bedrock(c, t, version):
    t["Items"] = _items_to(c.get("slots", []), "bedrock", version=tuple(version))
    t["disabled_slots"] = nbt.ShortTag(sum(1 << i for i in c.get("disabled", []) if 0 <= i < 9))


# ---- bell / conduit: the Bedrock ones carry their (idle) state
def _bell_to_bedrock(c, t, version):
    t["Direction"] = nbt.IntTag(255)
    t["Ringing"] = nbt.ByteTag(0)
    t["Ticks"] = nbt.IntTag(0)


def _conduit_to_bedrock(c, t, version):
    t["Active"] = nbt.ByteTag(0)
    t["Target"] = nbt.LongTag(-1)


# ---- copper golem statue: the pose is in the block state in Java (``copper_golem_pose``)
def _statue_from_bedrock(c, t):
    p = int(nbt.get(t, "Pose", 0) or 0)
    c["pose"] = GOLEM_POSES[p] if 0 <= p < len(GOLEM_POSES) else "standing"


def _statue_to_bedrock(c, t, version):
    t["Actor"] = nbt.CompoundTag({"ActorIdentifier": nbt.StringTag("minecraft:copper_golem<>"),
                                  "SaveData": nbt.CompoundTag()})
    pose = c.get("pose", "standing")
    t["Pose"] = nbt.IntTag(GOLEM_POSES.index(pose) if pose in GOLEM_POSES else 0)


# ---- jigsaw block: the strings that name its pool, target and what it turns into (Bedrock calls the pool target_pool)
_JIGSAW = (("final_state", "final_state"), ("joint", "joint"), ("target", "target"), ("pool", "target_pool"), ("name", "name"))


def _jigsaw_from_java(c, t):
    for java, _bedrock in _JIGSAW:
        if isinstance(nbt.get(t, java), str):
            c[java] = str(nbt.get(t, java))
    for k in ("selection_priority", "placement_priority"):    # 1.20.3+, Java only
        if k in t:
            c[k] = int(nbt.get(t, k))


def _jigsaw_from_bedrock(c, t):
    for java, bedrock in _JIGSAW:
        if isinstance(nbt.get(t, bedrock), str):
            c[java] = str(nbt.get(t, bedrock))


def _jigsaw_to_java(c, t, dv):
    for java, _bedrock in _JIGSAW:
        if java in c:
            t[java] = nbt.StringTag(c[java])
    for k in ("selection_priority", "placement_priority"):
        if k in c and dv >= 3698:
            t[k] = nbt.IntTag(c[k])


def _jigsaw_to_bedrock(c, t, version):
    for java, bedrock in _JIGSAW:
        if java in c:
            t[bedrock] = nbt.StringTag(c[java])


# ---- trial spawner: the mob and the configuration, when it is stored in the block entity itself
_TRIAL_DEFAULTS = {"spawn_range": nbt.IntTag(4), "total_mobs": nbt.FloatTag(6), "total_mobs_added_per_player": nbt.FloatTag(1),
                   "ticks_between_spawn": nbt.IntTag(20), "simultaneous_mobs": nbt.FloatTag(2),
                   "simultaneous_mobs_added_per_player": nbt.FloatTag(1)}


def _trial_config(cfg, convert) -> nbt.CompoundTag:
    """A copy of a trial spawner configuration with its loot table names turned by ``convert`` (table name -> name)."""
    out = nbt.copy(cfg)
    drop = nbt.get(out, "items_to_drop_when_ominous")
    if isinstance(drop, str):
        out["items_to_drop_when_ominous"] = nbt.StringTag(convert(drop) or drop)
    for e in nbt.get_tag(out, "loot_tables_to_eject") or []:
        d = nbt.get(e, "data")
        if isinstance(d, str):
            e["data"] = nbt.StringTag(convert(d) or d)
    return out


def _trial_spawner_from_java(c, t):
    sd = nbt.get_tag(t, "spawn_data")
    ent_t = nbt.get_tag(sd, "entity") if sd is not None else None
    if ent_t is not None and nbt.get(ent_t, "id"):
        c["entity"] = str(nbt.get(ent_t, "id"))
    for k in ("normal_config", "ominous_config"):
        cfg = nbt.get_tag(t, k)
        if isinstance(cfg, (nbt.CompoundTag, nbt.StringTag)):  # newer games name a configuration of the data pack instead
            c[k] = nbt.copy(cfg)
    for k in ("next_mob_spawns_at", "cooldown_end_at"):
        if k in t:
            c[k] = int(nbt.get(t, k))


def _trial_spawner_from_bedrock(c, t):
    sd = nbt.get_tag(t, "spawn_data")
    if sd is not None and nbt.get(sd, "TypeId"):
        c["entity"] = str(nbt.get(sd, "TypeId"))
    for k in ("normal_config", "ominous_config"):
        cfg = nbt.get_tag(t, k)
        if isinstance(cfg, nbt.CompoundTag):
            c[k] = _trial_config(cfg, loot_from_bedrock)
    for k in ("next_mob_spawns_at", "cooldown_end_at"):
        if k in t:
            c[k] = int(nbt.get(t, k))


def _trial_spawner_to_java(c, t, dv):
    if c.get("entity"):
        t["spawn_data"] = nbt.CompoundTag({"entity": nbt.CompoundTag({"id": nbt.StringTag(c["entity"])})})
    for k in ("normal_config", "ominous_config"):
        if k in c and (isinstance(c[k], nbt.CompoundTag) or dv >= TRIAL_CONFIG_REF_DV):
            t[k] = nbt.copy(c[k])
    for k in ("next_mob_spawns_at", "cooldown_end_at"):
        if k in c:
            t[k] = nbt.LongTag(c[k])


def _trial_spawner_to_bedrock(c, t, version):
    if c.get("entity"):
        t["spawn_data"] = nbt.CompoundTag({"TypeId": nbt.StringTag(c["entity"]), "Weight": nbt.IntTag(1)})
    cfg = {k: c[k] for k in ("normal_config", "ominous_config") if isinstance(c.get(k), nbt.CompoundTag)}
    if cfg:
        t["normal_config"] = _trial_config(cfg["normal_config"], loot_to_bedrock) if "normal_config" in cfg else nbt.CompoundTag()
        if "ominous_config" in cfg:
            t["ominous_config"] = _trial_config(cfg["ominous_config"], loot_to_bedrock)
    else:  # a spawner placed by a player (or one that names its configuration): the defaults of the game
        for k, v in _TRIAL_DEFAULTS.items():
            t[k] = nbt.copy(v)
    for k in ("next_mob_spawns_at", "cooldown_end_at"):
        if k in c:
            t[k] = nbt.LongTag(c[k])
    t["required_player_range"] = nbt.IntTag(14)


# ---- vault: key, loot table, display item, what is waiting to be ejected
_VAULT_LOOT = "minecraft:chests/trial_chambers/reward"


def _vault_from_java(c, t):
    cfg = nbt.get_tag(t, "config")
    if cfg is not None:
        c["key"] = _item_from(nbt.get_tag(cfg, "key_item"), "java")
        if isinstance(nbt.get(cfg, "loot_table"), str):
            c["loot_table"] = str(nbt.get(cfg, "loot_table"))
    shared = nbt.get_tag(t, "shared_data")
    if shared is not None:
        c["display"] = _item_from(nbt.get_tag(shared, "display_item"), "java")
    sv = nbt.get_tag(t, "server_data")
    if sv is not None:
        c["eject"] = _items_from(nbt.get_tag(sv, "items_to_eject"), "java")
        for k in ("state_updating_resumes_at", "total_ejections_needed"):
            if k in sv:
                c[k] = int(nbt.get(sv, k))


def _vault_from_bedrock(c, t):
    cfg = nbt.get_tag(t, "config")
    if cfg is not None:
        c["key"] = _item_from(nbt.get_tag(cfg, "key_item"), "bedrock")
        name = loot_from_bedrock(str(nbt.get(cfg, "loot_table", "")))
        if name:
            c["loot_table"] = name
    data = nbt.get_tag(t, "data")
    if data is not None:
        c["display"] = _item_from(nbt.get_tag(data, "display_item"), "bedrock")
        c["eject"] = _items_from(nbt.get_tag(data, "items_to_eject"), "bedrock")
        for k in ("state_updating_resumes_at", "total_ejections_needed"):
            if k in data:
                c[k] = int(nbt.get(data, k))


def _vault_to_java(c, t, dv):
    cfg = nbt.CompoundTag()
    if c.get("key"):
        cfg["key_item"] = _item_to(c["key"], "java", data_version=dv)
    if c.get("loot_table") and c["loot_table"] != _VAULT_LOOT:
        cfg["loot_table"] = nbt.StringTag(c["loot_table"])
    if len(cfg):
        t["config"] = cfg
    sv = nbt.CompoundTag()
    if c.get("eject"):
        sv["items_to_eject"] = _items_to([dict(i, slot=None) for i in c["eject"]], "java", data_version=dv)
    for k in ("state_updating_resumes_at", "total_ejections_needed"):
        if k in c:
            sv[k] = nbt.LongTag(c[k])
    if len(sv):
        t["server_data"] = sv
    shared = nbt.CompoundTag()
    if c.get("display"):
        shared["display_item"] = _item_to(c["display"], "java", data_version=dv)
    t["shared_data"] = shared


def _vault_to_bedrock(c, t, version):
    cfg = nbt.CompoundTag({"activation_range": nbt.FloatTag(4), "deactivation_range": nbt.FloatTag(4.5)})
    cfg["loot_table"] = nbt.StringTag(loot_to_bedrock(c.get("loot_table") or _VAULT_LOOT)
                                      or "loot_tables/chests/trial_chambers/reward.json")
    cfg["override_loot_table_to_display"] = nbt.StringTag("")
    if c.get("key"):
        w = _item_to(c["key"], "bedrock", version=tuple(version))
        if w is not None:
            cfg["key_item"] = w
    data = nbt.CompoundTag({"rewarded_players": nbt.ListTag([], 4)})
    data["items_to_eject"] = _items_to([dict(i, slot=None) for i in c.get("eject", [])], "bedrock", version=tuple(version))
    for k in ("state_updating_resumes_at", "total_ejections_needed"):
        if k in c:
            data[k] = nbt.LongTag(c[k])
    if c.get("display"):
        w = _item_to(c["display"], "bedrock", version=tuple(version))
        if w is not None:
            data["display_item"] = w
    t["config"] = cfg
    t["data"] = data


# ---- command block: all its state (Java and legacy share the names; Bedrock has its own, plus a few of the editor's)
_CMD_FLAGS = (("auto", "auto"), ("powered", "powered"), ("condition_met", "conditionMet"), ("track_output", "TrackOutput"))
_CMD_BEDROCK_ONLY = (("tick_delay", "TickDelay", nbt.IntTag), ("lp_command_mode", "LPCommandMode", nbt.IntTag),
                     ("lp_conditional_mode", "LPCondionalMode", nbt.IntTag), ("lp_redstone_mode", "LPRedstoneMode", nbt.IntTag))


def _command_from(c, t, src):
    c["command"] = str(nbt.get(t, "Command", ""))
    for k, key in _CMD_FLAGS:
        if key in t:
            c[k] = bool(nbt.get(t, key))
    if "SuccessCount" in t:
        c["success_count"] = int(nbt.get(t, "SuccessCount") or 0)
    if "LastExecution" in t:
        c["last_execution"] = int(nbt.get(t, "LastExecution") or 0)
    if "LastOutput" in t:
        lo = nbt.get_tag(t, "LastOutput")
        if src == "bedrock" and isinstance(lo, nbt.StringTag):
            c["last_output"] = str(lo.py_data)
        else:
            try:
                c["last_output"] = items._component_text(lo)
            except (TypeError, ValueError):                 # a component with arrays in it (a command's output text): cosmetic
                c["last_output"] = ""
    if src == "java" and "UpdateLastExecution" in t:
        c["update_last_execution"] = bool(nbt.get(t, "UpdateLastExecution"))
    if src == "bedrock":
        if "ExecuteOnFirstTick" in t:
            c["execute_on_first_tick"] = bool(nbt.get(t, "ExecuteOnFirstTick"))
        for k, key, _tag in _CMD_BEDROCK_ONLY:
            if key in t:
                c[k] = int(nbt.get(t, key) or 0)


def _command_to_java(c, t, dv: int):
    """``dv`` 0: the legacy block entity."""
    t["Command"] = nbt.StringTag(c.get("command", ""))
    for k, key in _CMD_FLAGS:
        if k in c:
            t[key] = nbt.ByteTag(1 if c[k] else 0)
    if "success_count" in c:
        t["SuccessCount"] = nbt.IntTag(c["success_count"])
    if "last_execution" in c:
        t["LastExecution"] = nbt.LongTag(c["last_execution"])
    if dv:
        t["UpdateLastExecution"] = nbt.ByteTag(1 if c.get("update_last_execution", True) else 0)
    if c.get("last_output"):
        t["LastOutput"] = nbt.StringTag(c["last_output"] if dv >= items.TEXT_NBT_DV else items.json_text(c["last_output"]))


def _command_to_bedrock(c, t):
    t["Command"] = nbt.StringTag(c.get("command", ""))
    t["Version"] = nbt.IntTag(34)
    t["TickDelay"] = nbt.IntTag(c.get("tick_delay", 0))
    t["ExecuteOnFirstTick"] = nbt.ByteTag(1 if c.get("execute_on_first_tick") else 0)
    for k, key in _CMD_FLAGS:
        if k in c or k == "track_output":
            t[key] = nbt.ByteTag(1 if c.get(k, True) else 0)
    t["SuccessCount"] = nbt.IntTag(c.get("success_count", 0))
    if "last_execution" in c:
        t["LastExecution"] = nbt.LongTag(c["last_execution"])
    if c.get("last_output"):
        t["LastOutput"] = nbt.StringTag(c["last_output"])
    for k, key, tag in _CMD_BEDROCK_ONLY[1:]:
        if k in c:
            t[key] = tag(c[k])


# ---- structure block (Java and the 1.10 - 1.12 "Structure" share their fields; je2be's StructureBlock for Bedrock's)
_STRUCT_MODES = ("DATA", "SAVE", "LOAD", "CORNER")                       # Bedrock's ``data``: 0 .. 3
_STRUCT_ROT = ("NONE", "CLOCKWISE_90", "CLOCKWISE_180", "COUNTERCLOCKWISE_90")
_STRUCT_MIRROR = ("NONE", "LEFT_RIGHT", "FRONT_BACK")
_AXES = ("X", "Y", "Z")
_STRUCT_FLAGS_JAVA = (("ignore_entities", "ignoreEntities"), ("powered", "powered"), ("show_air", "showair"),
                      ("show_bounding_box", "showboundingbox"))
_STRUCT_FLAGS_BEDROCK = (("ignore_entities", "ignoreEntities"), ("powered", "isPowered"), ("show_bounding_box", "showBoundingBox"),
                         ("include_players", "includePlayers"), ("remove_blocks", "removeBlocks"),
                         ("animation_mode", "animationMode"))


def _structure_from_java(c, t):
    for k in ("name", "author", "metadata"):
        if isinstance(nbt.get(t, k), str):
            c[k] = str(nbt.get(t, k))
    c["offset"] = tuple(int(nbt.get(t, "pos" + a, 0) or 0) for a in _AXES)
    c["size"] = tuple(int(nbt.get(t, "size" + a, 0) or 0) for a in _AXES)
    mode, rot, mirror = (str(nbt.get(t, k, d)) for k, d in (("mode", "DATA"), ("rotation", "NONE"), ("mirror", "NONE")))
    c["mode"] = mode if mode in _STRUCT_MODES else "DATA"
    c["rotation"] = _STRUCT_ROT.index(rot) if rot in _STRUCT_ROT else 0
    c["mirror"] = _STRUCT_MIRROR.index(mirror) if mirror in _STRUCT_MIRROR else 0
    for k, key in _STRUCT_FLAGS_JAVA:
        c[k] = bool(nbt.get(t, key, 0))
    c["integrity"] = float(nbt.get(t, "integrity", 1.0))
    c["seed"] = int(nbt.get(t, "seed", 0) or 0)


def _structure_to_java(c, t, dv):
    for k in ("name", "author", "metadata"):
        t[k] = nbt.StringTag(c.get(k, ""))
    for a, v in zip(_AXES, c.get("offset", (0, 1, 0))):
        t["pos" + a] = nbt.IntTag(v)
    for a, v in zip(_AXES, c.get("size", (0, 0, 0))):
        t["size" + a] = nbt.IntTag(v)
    t["mode"] = nbt.StringTag(c.get("mode", "DATA"))
    t["rotation"] = nbt.StringTag(_STRUCT_ROT[int(c.get("rotation", 0)) & 3])
    t["mirror"] = nbt.StringTag(_STRUCT_MIRROR[min(int(c.get("mirror", 0)), 2)])
    for k, key in _STRUCT_FLAGS_JAVA:
        t[key] = nbt.ByteTag(1 if c.get(k) else 0)
    t["integrity"] = nbt.FloatTag(c.get("integrity", 1.0))
    t["seed"] = nbt.LongTag(c.get("seed", 0))


def _structure_from_bedrock(c, t):
    for k, key in (("name", "structureName"), ("metadata", "dataField")):
        if isinstance(nbt.get(t, key), str):
            c[k] = str(nbt.get(t, key))
    c["offset"] = tuple(int(nbt.get(t, a.lower() + "StructureOffset", 0) or 0) for a in _AXES)
    c["size"] = tuple(int(nbt.get(t, a.lower() + "StructureSize", 0) or 0) for a in _AXES)
    mode = int(nbt.get(t, "data", 1) or 0)
    c["mode"] = _STRUCT_MODES[mode] if 0 <= mode < len(_STRUCT_MODES) else "LOAD"   # anything unknown loads, as je2be does
    c["rotation"] = int(nbt.get(t, "rotation", 0) or 0) & 3
    c["mirror"] = min(max(int(nbt.get(t, "mirror", 0) or 0), 0), 2)
    for k, key in _STRUCT_FLAGS_BEDROCK:
        c[k] = bool(nbt.get(t, key, 0))
    c["integrity"] = float(nbt.get(t, "integrity", 1.0))
    c["seed"] = int(nbt.get(t, "seed", 0) or 0)
    c["animation_seconds"] = float(nbt.get(t, "animationSeconds", 0.0))
    c["redstone_save_mode"] = int(nbt.get(t, "redstoneSaveMode", 0) or 0)


def _structure_to_bedrock(c, t, version):
    t["structureName"] = nbt.StringTag(c.get("name", ""))
    t["dataField"] = nbt.StringTag(c.get("metadata", ""))
    for a, v in zip(_AXES, c.get("offset", (0, 1, 0))):
        t[a.lower() + "StructureOffset"] = nbt.IntTag(v)
    for a, v in zip(_AXES, c.get("size", (0, 0, 0))):
        t[a.lower() + "StructureSize"] = nbt.IntTag(v)
    mode = c.get("mode", "DATA")
    t["data"] = nbt.IntTag(_STRUCT_MODES.index(mode) if mode in _STRUCT_MODES else 2)
    t["rotation"] = nbt.ByteTag(int(c.get("rotation", 0)) & 3)
    t["mirror"] = nbt.ByteTag(min(int(c.get("mirror", 0)), 2))
    for k, key in _STRUCT_FLAGS_BEDROCK:
        t[key] = nbt.ByteTag(1 if c.get(k) else 0)
    t["integrity"] = nbt.FloatTag(c.get("integrity", 1.0))
    t["seed"] = nbt.LongTag(c.get("seed", 0))
    t["animationSeconds"] = nbt.FloatTag(c.get("animation_seconds", 0.0))
    t["redstoneSaveMode"] = nbt.IntTag(c.get("redstone_save_mode", 0))


# ---- pistons.  Bedrock's PistonArm: State / NewState 0 retracted, 1 extending, 2 extended, 3 retracting.  Java has no
# block entity for a piston (the block state says whether it is extended): the arm is built from the state, as je2be does
# (java.modern.state_tiles).  A Bedrock arm that is in motion has nothing to become in Java and is counted as lost.
def _piston_arm_from_bedrock(c, t):
    c["sticky"] = bool(nbt.get(t, "Sticky", 0))
    c["state"] = int(nbt.get(t, "State", 0) or 0)
    c["new_state"] = int(nbt.get(t, "NewState", c["state"]) or 0)
    c["progress"] = float(nbt.get(t, "Progress", 0.0))
    c["last_progress"] = float(nbt.get(t, "LastProgress", 0.0))
    c["attached"] = _ints(nbt.get_tag(t, "AttachedBlocks"))
    c["breaks"] = _ints(nbt.get_tag(t, "BreakBlocks"))


def _piston_arm_to_bedrock(c, t, version):
    state = int(c["state"]) if "state" in c else (2 if c.get("extended") else 0)
    still = 1.0 if state else 0.0
    t["State"] = nbt.ByteTag(state)
    t["NewState"] = nbt.ByteTag(int(c.get("new_state", state)))
    t["Progress"] = nbt.FloatTag(c.get("progress", still))
    t["LastProgress"] = nbt.FloatTag(c.get("last_progress", still))
    t["Sticky"] = nbt.ByteTag(1 if c.get("sticky") else 0)
    t["AttachedBlocks"] = nbt.ListTag([nbt.IntTag(v) for v in c.get("attached", [])], 3)
    t["BreakBlocks"] = nbt.ListTag([nbt.IntTag(v) for v in c.get("breaks", [])], 3)
    t["isMovable"] = nbt.ByteTag(0 if state else 1)


# the moving piston (the block that is travelling): Java 1.13+ blockState / facing / progress / extending / source, legacy
# blockId / blockData / facing / progress / extending / source.  Bedrock has the MovingBlock, which needs the position of
# its piston: not translated (counted as lost)
def _moving_piston_from_java(c, t):
    st = nbt.get_tag(t, "blockState")
    if st is not None:
        c["state"] = nbt.copy(st)
    c["facing"] = int(nbt.get(t, "facing", 0) or 0)
    c["progress"] = float(nbt.get(t, "progress", 0.0))
    c["extending"] = bool(nbt.get(t, "extending", 0))
    c["source"] = bool(nbt.get(t, "source", 0))


def _moving_piston_from_legacy(c, t):
    c["legacy_block"] = (int(nbt.get(t, "blockId", 0) or 0), int(nbt.get(t, "blockData", 0) or 0))
    c["facing"] = int(nbt.get(t, "facing", 0) or 0)
    c["progress"] = float(nbt.get(t, "progress", 0.0))
    c["extending"] = bool(nbt.get(t, "extending", 0))
    c["source"] = bool(nbt.get(t, "source", 0))


def _moving_piston_to_java(c, t, dv):
    st = c.get("state")
    if st is None and c.get("legacy_block"):
        name = items.legacy_to_flat(*c["legacy_block"])
        st = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:" + name)}) if name else None
    t["blockState"] = nbt.copy(st) if st is not None else nbt.CompoundTag({"Name": nbt.StringTag("minecraft:air")})
    t["facing"] = nbt.IntTag(c.get("facing", 0))
    t["progress"] = nbt.FloatTag(c.get("progress", 0.0))
    t["extending"] = nbt.ByteTag(1 if c.get("extending") else 0)
    t["source"] = nbt.ByteTag(1 if c.get("source") else 0)


def _moving_piston_to_legacy(c, t):
    bid, data = c.get("legacy_block") or (0, 0)
    if not c.get("legacy_block") and c.get("state") is not None:
        leg = items.flat_to_legacy(nbt.state_name(c["state"], "minecraft:air"))
        bid, data = leg if leg and leg[0] < 256 else (0, 0)
    t["blockId"] = nbt.IntTag(bid)
    t["blockData"] = nbt.IntTag(data)
    t["facing"] = nbt.IntTag(c.get("facing", 0))
    t["progress"] = nbt.FloatTag(c.get("progress", 0.0))
    t["extending"] = nbt.ByteTag(1 if c.get("extending") else 0)
    t["source"] = nbt.ByteTag(1 if c.get("source") else 0)


# ---- lodestone: Bedrock's tracking handle (the key of the compass records in the database, see bedrock.extra)
def _lodestone_from_bedrock(c, t):
    if "trackingHandle" in t:
        c["handle"] = int(nbt.get(t, "trackingHandle"))


def _lodestone_to_bedrock(c, t, version):
    if c.get("handle") is not None:
        t["trackingHandle"] = nbt.IntTag(c["handle"])


# ---- cauldron: Bedrock holds potions and dyed water in the block entity (PotionId / PotionType / CustomColor); Java 1.17+ has
# the content in the block (water / lava / powder snow with a level) and nothing else exists there.  LCE PS4 / Xbox One:
# "minecraft:cauldron" with a string PotionId and a PotionType
def _cauldron_from_bedrock(c, t):
    c["potion_id"] = int(nbt.get(t, "PotionId", -1))
    c["potion_type"] = int(nbt.get(t, "PotionType", -1))
    if "CustomColor" in t:
        c["color"] = int(nbt.get(t, "CustomColor"))


def _cauldron_from_lce(c, t):
    pid = nbt.get(t, "PotionId", "")
    c["potion_id"] = pid if isinstance(pid, str) else int(pid)
    c["potion_type"] = int(nbt.get(t, "PotionType", -1))


def _cauldron_to_bedrock(c, t, version):
    pid, ptype = c.get("potion_id", -1), c.get("potion_type", -1)
    if isinstance(pid, str):                               # LCE names the potion with a string, Bedrock numbers the effect
        pid, ptype = -1, -1
    t["PotionId"] = nbt.ShortTag(pid)
    t["PotionType"] = nbt.ShortTag(ptype)
    t["Items"] = nbt.ListTag([], 10)
    if c.get("color") is not None:
        t["CustomColor"] = nbt.IntTag(c["color"])


# ---- Java 1.21.5 test blocks: no other game has them; a Java target gets them back as they were
def _raw_from_java(c, t):
    c["raw"] = nbt.CompoundTag({k: nbt.copy(v) for k, v in t.items() if k not in ("id", "x", "y", "z")})


def _raw_to_java(c, t, dv):
    for k, v in (c.get("raw") or {}).items():
        t[k] = nbt.copy(v)


_JAVA_READ = {"decorated_pot": _decorated_pot_from_java, "brushable_block": _brushable_from_java,
              "campfire": _campfire_from_java, "soul_campfire": _campfire_from_java,
              "beehive": _beehive_from_java, "bee_nest": _beehive_from_java, "lectern": _lectern_from_java,
              "chiseled_bookshelf": _chiseled_bookshelf_from_java, "shelf": _shelf_from_java,
              "crafter": _crafter_from_java, "trial_spawner": _trial_spawner_from_java, "vault": _vault_from_java,
              "jigsaw": _jigsaw_from_java, "structure_block": _structure_from_java,
              "moving_piston": _moving_piston_from_java, "test_block": _raw_from_java,
              "test_instance_block": _raw_from_java}
_BEDROCK_READ = {"decorated_pot": _decorated_pot_from_bedrock, "brushable_block": _brushable_from_bedrock,
                 "campfire": _campfire_from_bedrock, "soul_campfire": _campfire_from_bedrock,
                 "beehive": _beehive_from_bedrock, "bee_nest": _beehive_from_bedrock, "lectern": _lectern_from_bedrock,
                 "chiseled_bookshelf": _chiseled_bookshelf_from_bedrock, "shelf": _shelf_from_bedrock,
                 "crafter": _crafter_from_bedrock, "copper_golem_statue": _statue_from_bedrock,
                 "trial_spawner": _trial_spawner_from_bedrock, "vault": _vault_from_bedrock,
                 "jigsaw": _jigsaw_from_bedrock, "structure_block": _structure_from_bedrock,
                 "piston_arm": _piston_arm_from_bedrock, "lodestone": _lodestone_from_bedrock,
                 "cauldron": _cauldron_from_bedrock}
_JAVA_WRITE = {"decorated_pot": _decorated_pot_to_java, "brushable_block": _brushable_to_java,
               "campfire": _campfire_to_java, "soul_campfire": _campfire_to_java,
               "beehive": _beehive_to_java, "bee_nest": _beehive_to_java, "lectern": _lectern_to_java,
               "chiseled_bookshelf": _chiseled_bookshelf_to_java, "shelf": _shelf_to_java,
               "crafter": _crafter_to_java, "trial_spawner": _trial_spawner_to_java, "vault": _vault_to_java,
               "jigsaw": _jigsaw_to_java, "structure_block": _structure_to_java,
               "moving_piston": _moving_piston_to_java, "test_block": _raw_to_java, "test_instance_block": _raw_to_java}
_BEDROCK_WRITE = {"decorated_pot": _decorated_pot_to_bedrock, "brushable_block": _brushable_to_bedrock,
                  "campfire": _campfire_to_bedrock, "soul_campfire": _campfire_to_bedrock,
                  "beehive": _beehive_to_bedrock, "bee_nest": _beehive_to_bedrock, "lectern": _lectern_to_bedrock,
                  "chiseled_bookshelf": _chiseled_bookshelf_to_bedrock, "shelf": _shelf_to_bedrock,
                  "crafter": _crafter_to_bedrock, "bell": _bell_to_bedrock, "conduit": _conduit_to_bedrock,
                  "copper_golem_statue": _statue_to_bedrock, "trial_spawner": _trial_spawner_to_bedrock,
                  "vault": _vault_to_bedrock, "jigsaw": _jigsaw_to_bedrock,
                  "structure_block": _structure_to_bedrock, "piston_arm": _piston_arm_to_bedrock,
                  "lodestone": _lodestone_to_bedrock, "cauldron": _cauldron_to_bedrock}


# ============================================================= helpers


def pair_chests(tiles: List[dict]) -> None:
    """Bedrock needs explicit pairing of double chests."""
    pos = {}
    for c in tiles:
        if c["kind"] in ("chest", "trapped_chest"):
            pos[c["pos"]] = c
    for (x, y, z), c in pos.items():
        if "pair" in c:
            continue
        for dx, dz in ((1, 0), (0, 1), (-1, 0), (0, -1)):
            o = pos.get((x + dx, y, z + dz))
            if o is not None and o["kind"] == c["kind"] and "pair" not in o:
                c["pair"] = (x + dx, z + dz)
                o["pair"] = (x, z)
                break


def convert_list(tiles, src: str, dst: str, **kw) -> List[nbt.CompoundTag]:
    return write_list(read_canon(tiles, src), dst, **kw)


UNKNOWN = "unknown"          # kind of a block entity whose id no table knows: only its id and place are kept


def read_canon(tags, src: str) -> List[dict]:
    """The canonical dicts of the block entities ``tags`` of ``src`` ("legacy" / "java" / "bedrock").  Nothing is
    dropped silently: an id that no table knows becomes ``{"kind": UNKNOWN, "pos", "id"}``, which ``write_list``
    counts as lost (the caller may remove it before when the target keeps its own copy).  Canonical dicts in
    ``tags`` (the ones built from block states) pass as they are."""
    reader = {"legacy": from_legacy, "java": from_java_modern, "bedrock": from_bedrock}[src]
    out = []
    for t in tags:
        if isinstance(t, dict):
            out.append(t)
            continue
        c = reader(t)
        if c is None:
            c = {"kind": UNKNOWN, "pos": _pos(t), "id": str(nbt.get(t, "id", "") or "?")}
        out.append(c)
    return out


# Block entities that a game does not have and whose absence loses nothing: what the game keeps in the block (Java: the
# cauldron's level, the note, the flower), or builds itself (the piston arm of Bedrock's pistons, the lodestone's handle),
# or that is an empty marker (a bell, a conduit, the sculk blocks).  Anything else a target lacks is counted (loss_name).
_NOTHING_LOST = {
    "java": frozenset({"piston_arm", "lodestone", "noteblock", "flower_pot"}),
    "legacy": frozenset({"piston_arm", "lodestone", "bell", "conduit", "sculk_sensor", "calibrated_sculk_sensor",
                         "sculk_catalyst", "sculk_shrieker", "creaking_heart"}),
    "bedrock": frozenset(),
}


def loss_name(c: dict, dst: str) -> Optional[str]:
    """The id to report when the canonical block entity ``c`` could not be written for ``dst`` ("legacy" / "java" /
    "bedrock"), or None when nothing that matters is lost."""
    kind = c.get("kind")
    if kind == UNKNOWN:
        return c.get("id") or "?"
    if kind in _NOTHING_LOST.get(dst, ()):
        # an arm that was in motion (extending / retracting) leaves nothing behind in Java: the blocks stay where they are
        return "PistonArm" if kind == "piston_arm" and int(c.get("state", 0)) in (1, 3) else None
    if kind == "cauldron" and dst != "bedrock":                # potions and dyed water do not exist there
        pid = c.get("potion_id", -1)
        has = (isinstance(pid, int) and pid >= 0) or (isinstance(pid, str) and bool(pid)) or c.get("color") is not None
        return "Cauldron" if has else None
    return kind


def write_list(canon: List[dict], dst: str, tally=None, **kw) -> List[nbt.CompoundTag]:
    """``canon`` as block entities of ``dst``.  ``tally`` (newcontent.Tally): what could not be written and is
    a loss is counted in it, per id."""
    if dst == "bedrock":
        pair_chests(canon)
    out = []
    for c in canon:
        t = None
        if c["kind"] != UNKNOWN:
            if dst == "legacy":
                t = to_legacy(c, kw.get("lce", False))
            elif dst == "java":
                t = to_java_modern(c, kw.get("data_version", 3465))
            else:
                t = to_bedrock(c, kw.get("version", (1, 21, 0)))
        if t is not None:
            out.append(t)
        elif tally is not None:
            name = loss_name(c, dst)
            if name:
                tally.lose_tile(name)
    return out


# numeric blocks drawn by their block entity: without one they are invisible
_ENTITY_DRAWN = {54: "Chest", 146: "Chest", 130: "EnderChest"}


def ensure_drawn_tiles(c) -> int:
    """Chests (and ender chests) of a numeric chunk that have no block entity get an empty one: the
    old games draw them through it, without it they are invisible.  Returns how many were missing."""
    import numpy as np

    blocks = getattr(c, "blocks", None)
    if blocks is None:
        return 0
    ys, zs, xs = np.nonzero(np.isin(blocks, list(_ENTITY_DRAWN)))
    if not len(ys):
        return 0
    have = set()
    for t in c.tile_entities:
        try:
            have.add((int(nbt.get(t, "x")), int(nbt.get(t, "y")), int(nbt.get(t, "z"))))
        except (TypeError, ValueError):
            continue
    added = 0
    for y, z, x in zip(ys.tolist(), zs.tolist(), xs.tolist()):
        pos = (c.cx * 16 + x, y, c.cz * 16 + z)
        if pos in have:
            continue
        tid = _ENTITY_DRAWN[int(blocks[y, z, x])]
        t = nbt.CompoundTag({"id": nbt.StringTag(tid), "x": nbt.IntTag(pos[0]), "y": nbt.IntTag(pos[1]),
                             "z": nbt.IntTag(pos[2])})
        if tid == "Chest":
            t["Items"] = nbt.ListTag([], 10)
        c.tile_entities.append(t)
        added += 1
    return added
