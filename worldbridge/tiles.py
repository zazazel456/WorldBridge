"""Block entity translation (legacy / Java 1.13+ / Bedrock) through a
canonical dict representation."""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

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
}
CONTAINERS = {"chest", "trapped_chest", "dispenser", "dropper", "hopper", "furnace", "blast_furnace", "smoker",
              "brewing_stand", "shulker_box", "barrel"}
LEGACY_TO_KIND = {}
for _k, (_l, _j, _b) in KINDS.items():
    if _l and _l not in LEGACY_TO_KIND:
        LEGACY_TO_KIND[_l] = _k
JAVA_TO_KIND = {j: k for k, (l, j, b) in KINDS.items() if j}
JAVA_TO_KIND.update({"spawner": "mob_spawner", "enchantment_table": "enchanting_table", "note_block": "noteblock"})
# Java 1.21.9+ copper chests: the older games have only the wooden chest (the block becomes one too)
JAVA_TO_KIND.update({f"{w}{a}copper_chest": "chest" for w in ("", "waxed_")
                     for a in ("", "exposed_", "weathered_", "oxidized_")})
BEDROCK_TO_KIND = {}
for _k, (_l, _j, _b) in KINDS.items():
    if _b and _b not in BEDROCK_TO_KIND:
        BEDROCK_TO_KIND[_b] = _k
BEDROCK_TO_KIND["Chest"] = "chest"


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
    if kind is None:
        n = str(tid).split(":", 1)[-1]
        kind = JAVA_TO_KIND.get(n)  # 1.11 - 1.12 names
    if kind is None:
        return None
    c = {"kind": kind, "pos": _pos(t)}
    src = "legacy"
    if kind in CONTAINERS or "Items" in t:
        c["items"] = _items_from(nbt.get_tag(t, "Items"), src)
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
        c["command"] = str(nbt.get(t, "Command", ""))
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
    if "CustomName" in t:
        cn = nbt.get_tag(t, "CustomName")
        c["custom_name"] = items.plain_text(cn.py_data) if isinstance(cn, nbt.StringTag) else ""
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
        c["command"] = str(nbt.get(t, "Command", ""))
    elif kind == "beacon":
        c["levels"] = int(nbt.get(t, "Levels", 0))
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
        c["command"] = str(nbt.get(t, "Command", ""))
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
        t["Command"] = nbt.StringTag(c.get("command", ""))
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
    if bid is None:
        return None
    x, y, z = c["pos"]
    t = nbt.CompoundTag({"id": nbt.StringTag(bid), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z),
                         "isMovable": nbt.ByteTag(1)})
    if "items" in c:
        t["Items"] = _items_to(c["items"], "bedrock", version=tuple(version))
        t["Findable"] = nbt.ByteTag(0)
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
        t["Command"] = nbt.StringTag(c.get("command", ""))
        t["Version"] = nbt.IntTag(19)
    elif kind == "furnace":
        t["BurnTime"] = nbt.ShortTag(c.get("burn", 0))
        t["CookTime"] = nbt.ShortTag(c.get("cook", 0))
    elif kind == "beacon":
        t["primary"] = nbt.IntTag(c.get("primary", 0))
        t["secondary"] = nbt.IntTag(c.get("secondary", 0))
    return t


def to_java_modern(c: dict, data_version: int) -> Optional[nbt.CompoundTag]:
    kind = c["kind"]
    jid = KINDS[kind][1]
    if jid is None:
        return None
    if kind == "mob_spawner" and data_version >= 3818:
        jid = "spawner"
    x, y, z = c["pos"]
    t = nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + jid), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z)})
    if "items" in c:
        t["Items"] = _items_to(c["items"], "java", data_version=data_version)
    if c.get("custom_name"):
        t["CustomName"] = nbt.StringTag(items.json_text(c["custom_name"]))
    if kind in ("sign", "hanging_sign"):
        front = (list(c.get("front") or []) + ["", "", "", ""])[:4]
        back = (list(c.get("back") or []) + ["", "", "", ""])[:4]
        color = c.get("color", "black")
        if data_version >= 3463:  # 1.20 two-sided signs
            def side(lines):
                msgs = nbt.ListTag([nbt.StringTag(l) if data_version >= 4325 else nbt.StringTag(items.json_text(l)) for l in lines], 8)
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
        t["Command"] = nbt.StringTag(c.get("command", ""))
    elif kind == "beacon":
        t["Levels"] = nbt.IntTag(c.get("levels", 0))
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
    reader = {"legacy": from_legacy, "java": from_java_modern, "bedrock": from_bedrock}[src]
    canon = [c for c in (reader(t) for t in tiles) if c is not None]
    return write_list(canon, dst, **kw)


def write_list(canon: List[dict], dst: str, **kw) -> List[nbt.CompoundTag]:
    if dst == "bedrock":
        pair_chests(canon)
    out = []
    for c in canon:
        if dst == "legacy":
            t = to_legacy(c, kw.get("lce", False))
        elif dst == "java":
            t = to_java_modern(c, kw.get("data_version", 3465))
        else:
            t = to_bedrock(c, kw.get("version", (1, 21, 0)))
        if t is not None:
            out.append(t)
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
