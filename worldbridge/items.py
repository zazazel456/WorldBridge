"""Item stack translation between

* legacy numeric items   {id: short, Count, Damage, tag}          (LCE, Java <= 1.12, hub)
* Java 1.13+ items       {id: "minecraft:x", Count, tag}  /  1.20.5+ {id, count, components}
* Bedrock items          {Name, Count, Damage, Block?, tag}

The canonical form is a small dict keyed on the flattened Java name.
"""

from __future__ import annotations

import functools
import json
import logging
from typing import Dict, Optional, Tuple

from . import ids, nbt

WOOL = ["white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan",
        "purple", "blue", "brown", "green", "red", "black"]
DYE_ITEMS = ["ink_sac", "red_dye", "green_dye", "cocoa_beans", "lapis_lazuli", "purple_dye", "cyan_dye",
             "light_gray_dye", "gray_dye", "pink_dye", "lime_dye", "yellow_dye", "light_blue_dye", "magenta_dye",
             "orange_dye", "bone_meal"]
SKULLS = ["skeleton_skull", "wither_skeleton_skull", "zombie_head", "player_head", "creeper_head", "dragon_head",
          "piglin_head"]
RECORDS = ["13", "cat", "blocks", "chirp", "far", "mall", "mellohi", "stal", "strad", "ward", "11", "wait"]

# numeric (legacy) item -> flattened name, keyed (id, damage); None damage = any
LEGACY_ITEM_RENAMES: Dict[Tuple[int, Optional[int]], str] = {
    (263, 0): "coal", (263, 1): "charcoal", (322, 0): "golden_apple", (322, 1): "enchanted_golden_apple",
    (349, 0): "cod", (349, 1): "salmon", (349, 2): "tropical_fish", (349, 3): "pufferfish",
    (350, 0): "cooked_cod", (350, 1): "cooked_salmon", (338, None): "sugar_cane", (382, None): "glistering_melon_slice",
    (360, None): "melon_slice", (401, None): "firework_rocket", (402, None): "firework_star",
    (405, None): "nether_brick", (333, None): "oak_boat", (324, None): "oak_door", (323, None): "oak_sign",
    (433, None): "popped_chorus_fruit", (358, None): "filled_map", (383, None): "spawn_egg",
    (355, None): "bed", (397, None): "skull", (425, None): "banner", (351, None): "dye",
}
for _i, _r in enumerate(RECORDS):
    LEGACY_ITEM_RENAMES[(2256 + _i, None)] = f"music_disc_{_r}"

LEGACY_ENCH = {0: "protection", 1: "fire_protection", 2: "feather_falling", 3: "blast_protection",
               4: "projectile_protection", 5: "respiration", 6: "aqua_affinity", 7: "thorns", 8: "depth_strider",
               9: "frost_walker", 10: "binding_curse", 16: "sharpness", 17: "smite", 18: "bane_of_arthropods",
               19: "knockback", 20: "fire_aspect", 21: "looting", 22: "sweeping", 32: "efficiency", 33: "silk_touch",
               34: "unbreaking", 35: "fortune", 48: "power", 49: "punch", 50: "flame", 51: "infinity",
               61: "luck_of_the_sea", 62: "lure", 70: "mending", 71: "vanishing_curse"}
LEGACY_ENCH_INV = {v: k for k, v in LEGACY_ENCH.items()}
LEGACY_ENCH_INV["sweeping_edge"] = 22
# enchantment ids Java renamed: (DataVersion of the rename, old name, new name)
_JAVA_ENCH_RENAMES = ((3837, "sweeping", "sweeping_edge"),)  # 1.20.5
BEDROCK_ENCH = ["protection", "fire_protection", "feather_falling", "blast_protection", "projectile_protection",
                "thorns", "respiration", "depth_strider", "aqua_affinity", "sharpness", "smite",
                "bane_of_arthropods", "knockback", "fire_aspect", "looting", "efficiency", "silk_touch",
                "unbreaking", "fortune", "power", "punch", "flame", "infinity", "luck_of_the_sea", "lure",
                "frost_walker", "mending", "binding_curse", "vanishing_curse", "impaling", "riptide", "loyalty",
                "channeling", "multishot", "piercing", "quick_charge", "soul_speed", "swift_sneak", "wind_burst",
                "density", "breach"]
BEDROCK_ENCH_INV = {n: i for i, n in enumerate(BEDROCK_ENCH)}
BEDROCK_ENCH_INV["sweeping"] = BEDROCK_ENCH_INV["sweeping_edge"] = None

# legacy potion damage low bits -> effect name
LEGACY_POTION_EFFECT = {1: "regeneration", 2: "swiftness", 3: "fire_resistance", 4: "poison", 5: "healing",
                        6: "night_vision", 8: "weakness", 9: "strength", 10: "slowness", 11: "leaping",
                        12: "harming", 13: "water_breathing", 14: "invisibility"}
LEGACY_POTION_EFFECT_INV = {v: k for k, v in LEGACY_POTION_EFFECT.items()}
BEDROCK_POTIONS = ["water", "mundane", "long_mundane", "thick", "awkward", "night_vision", "long_night_vision",
                   "invisibility", "long_invisibility", "leaping", "long_leaping", "strong_leaping",
                   "fire_resistance", "long_fire_resistance", "swiftness", "long_swiftness", "strong_swiftness",
                   "slowness", "long_slowness", "water_breathing", "long_water_breathing", "healing",
                   "strong_healing", "harming", "strong_harming", "poison", "long_poison", "strong_poison",
                   "regeneration", "long_regeneration", "strong_regeneration", "strength", "long_strength",
                   "strong_strength", "weakness", "long_weakness", "wither", "turtle_master",
                   "long_turtle_master", "strong_turtle_master", "slow_falling", "long_slow_falling",
                   "strong_slowness", "wind_charged", "weaving", "oozing", "infested"]
BEDROCK_POTIONS_INV = {n: i for i, n in enumerate(BEDROCK_POTIONS)}

# legacy spawn egg damage (Java numeric entity id) -> entity name
LEGACY_EGG = {4: "elder_guardian", 5: "wither_skeleton", 6: "stray", 23: "husk", 27: "zombie_villager",
              28: "skeleton_horse", 29: "zombie_horse", 31: "donkey", 32: "mule", 34: "evoker", 35: "vex",
              36: "vindicator", 50: "creeper", 51: "skeleton", 52: "spider", 54: "zombie", 55: "slime", 56: "ghast",
              57: "zombified_piglin", 58: "enderman", 59: "cave_spider", 60: "silverfish", 61: "blaze",
              62: "magma_cube", 65: "bat", 66: "witch", 67: "endermite", 68: "guardian", 69: "shulker", 90: "pig",
              91: "sheep", 92: "cow", 93: "chicken", 94: "squid", 95: "wolf", 96: "mooshroom", 98: "ocelot",
              100: "horse", 101: "rabbit", 102: "polar_bear", 103: "llama", 105: "parrot", 120: "villager"}
LEGACY_EGG_INV = {v: k for k, v in LEGACY_EGG.items()}
LEGACY_EGG_INV["zombie_pigman"] = 57

# Java flattened name -> Bedrock item name (non-block items that differ)
JAVA_TO_BEDROCK_NAME = {"nether_brick": "netherbrick", "oak_sign": "oak_sign", "firework_rocket": "firework_rocket",
                        "tipped_arrow": "arrow", "enchanted_golden_apple": "enchanted_golden_apple",
                        "snowball": "snowball", "turtle_scute": "turtle_scute", "scute": "turtle_scute",
                        "oak_door": "wooden_door", "item_frame": "frame", "glow_item_frame": "glow_frame",
                        "map": "empty_map", "zombified_piglin_spawn_egg": "zombie_pigman_spawn_egg",
                        "stone_stairs": "normal_stone_stairs"}   # Bedrock's own stone_stairs are the cobblestone ones
BEDROCK_TO_JAVA_NAME = {"netherbrick": "nether_brick", "appleenchanted": "enchanted_golden_apple",
                        "appleEnchanted": "enchanted_golden_apple", "clownfish": "tropical_fish",
                        "cooked_fish": "cooked_cod", "fish": "cod", "reeds": "sugar_cane", "speckled_melon":
                        "glistering_melon_slice", "melon": "melon_slice", "fireworks": "firework_rocket",
                        "fireworkscharge": "firework_star", "boat": "oak_boat", "wooden_door": "oak_door",
                        "sign": "oak_sign", "turtle_shell_piece": "turtle_scute", "chorus_fruit_popped":
                        "popped_chorus_fruit", "map": "filled_map", "emptymap": "map", "empty_map": "map",
                        "muttoncooked": "cooked_mutton", "muttonraw": "mutton", "short_grass": "grass",
                        "frame": "item_frame", "glow_frame": "glow_item_frame",
                        "zombie_pigman_spawn_egg": "zombified_piglin_spawn_egg",
                        "normal_stone_stairs": "stone_stairs"}
# 1.11 entity ids (spawn eggs of Java 1.11 - 1.12) -> 1.13+ names
_ENTITY_113 = {"vindication_illager": "vindicator", "evocation_illager": "evoker", "illusion_illager": "illusioner",
               "zombie_pigman": "zombified_piglin", "villager_golem": "iron_golem", "snowman": "snow_golem"}

log = logging.getLogger(__name__)

# Bedrock before 1.16.100 (its item flattening) named many items differently and told variants apart
# by Damage.  Newer games still read these names (they upgrade them), older ones know only them.
BEDROCK_ITEM_FLATTENING = (1, 16, 100)
BEDROCK_NEW_DYES = (1, 10, 0)            # black / brown / blue / white dye (dye 16 - 19); before: the old dyes
OLD_BEDROCK_BUCKETS = {"bucket": 0, "milk_bucket": 1, "cod_bucket": 2, "salmon_bucket": 3,
                       "tropical_fish_bucket": 4, "pufferfish_bucket": 5, "water_bucket": 8, "lava_bucket": 10}
OLD_BEDROCK_BOATS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak")       # boat + Damage
OLD_BEDROCK_PATTERNS = {"creeper_banner_pattern": 0, "skull_banner_pattern": 1, "flower_banner_pattern": 2,
                        "mojang_banner_pattern": 3, "piglin_banner_pattern": 6}     # banner_pattern + Damage
OLD_BEDROCK_NEW_DYES = {"black_dye": (16, "ink_sac"), "brown_dye": (17, "cocoa_beans"),
                        "blue_dye": (18, "lapis_lazuli"), "white_dye": (19, "bone_meal")}
# Java name -> Bedrock name before 1.16.100 (items without a Damage variant)
OLD_BEDROCK_NAMES = {
    "cod": "fish", "tropical_fish": "clownfish", "cooked_cod": "cooked_fish", "melon_slice": "melon",
    "glistering_melon_slice": "speckled_melon", "sugar_cane": "reeds", "firework_rocket": "fireworks",
    "firework_star": "fireworksCharge", "enchanted_golden_apple": "appleEnchanted", "mutton": "muttonRaw",
    "cooked_mutton": "muttonCooked", "popped_chorus_fruit": "chorus_fruit_popped", "nether_star": "netherstar",
    "fire_charge": "fireball", "carrot_on_a_stick": "carrotOnAStick", "totem_of_undying": "totem",
    "turtle_scute": "turtle_shell_piece", "scute": "turtle_shell_piece", "oak_sign": "sign",
    "dark_oak_sign": "darkoak_sign", "map": "emptyMap", "filled_map": "map", "lodestone_compass": "lodestonecompass",
    "leather_horse_armor": "horsearmorleather", "iron_horse_armor": "horsearmoriron",
    "golden_horse_armor": "horsearmorgold", "diamond_horse_armor": "horsearmordiamond",
    **{f"music_disc_{r}": f"record_{r}" for r in RECORDS + ["pigstep"]},
}
# Bedrock's numeric entity types: the Damage of an old "spawn_egg" (Java entity name -> number)
BEDROCK_ENTITY_IDS = {
    "chicken": 10, "cow": 11, "pig": 12, "sheep": 13, "wolf": 14, "villager": 115, "mooshroom": 16, "squid": 17,
    "rabbit": 18, "bat": 19, "iron_golem": 20, "snow_golem": 21, "ocelot": 22, "horse": 23, "donkey": 24,
    "mule": 25, "skeleton_horse": 26, "zombie_horse": 27, "polar_bear": 28, "llama": 29, "parrot": 30,
    "dolphin": 31, "zombie": 32, "creeper": 33, "skeleton": 34, "spider": 35, "zombified_piglin": 36,
    "slime": 37, "enderman": 38, "silverfish": 39, "cave_spider": 40, "ghast": 41, "magma_cube": 42,
    "blaze": 43, "zombie_villager": 116, "witch": 45, "stray": 46, "husk": 47, "wither_skeleton": 48,
    "guardian": 49, "elder_guardian": 50, "shulker": 54, "endermite": 55, "vindicator": 57, "phantom": 58,
    "ravager": 59, "turtle": 74, "cat": 75, "evoker": 104, "vex": 105, "pufferfish": 108, "salmon": 109,
    "drowned": 110, "tropical_fish": 111, "cod": 112, "panda": 113, "pillager": 114, "wandering_trader": 118,
    "fox": 121, "bee": 122, "piglin": 123, "hoglin": 124, "strider": 125, "zoglin": 126, "piglin_brute": 127,
}
BEDROCK_ENTITY_NAMES = {v: k for k, v in BEDROCK_ENTITY_IDS.items()}
BEDROCK_ENTITY_NAMES.update({15: "villager", 44: "zombie_villager"})  # before villager_v2 (Bedrock 1.11)
_OLD_BEDROCK_TO_JAVA = {v.lower(): k for k, v in OLD_BEDROCK_NAMES.items() if k != "scute"}


def old_bedrock_item(name: str, version: Tuple[int, ...]) -> Optional[Tuple[str, int]]:
    """(Bedrock name, Damage) of Java item ``name`` for a Bedrock ``version`` before the 1.16.100 item
    flattening, or None when the item kept its name there."""
    v = tuple(version)
    if v >= BEDROCK_ITEM_FLATTENING:
        return None
    if name in DYE_ITEMS:
        return "dye", DYE_ITEMS.index(name)
    if name in OLD_BEDROCK_NEW_DYES:
        aux, older = OLD_BEDROCK_NEW_DYES[name]
        return "dye", aux if v >= BEDROCK_NEW_DYES else DYE_ITEMS.index(older)
    if name in OLD_BEDROCK_BUCKETS:
        return "bucket", OLD_BEDROCK_BUCKETS[name]
    if name.endswith("_boat") and name[:-5] in OLD_BEDROCK_BOATS:
        return "boat", OLD_BEDROCK_BOATS.index(name[:-5])
    if name in OLD_BEDROCK_PATTERNS:
        return "banner_pattern", OLD_BEDROCK_PATTERNS[name]
    if name.endswith("_spawn_egg"):
        e = _ENTITY_113.get(name[:-10], name[:-10])
        eid = BEDROCK_ENTITY_IDS.get(e)
        if eid is None:
            return None
        if v < (1, 11) and e in ("villager", "zombie_villager"):
            eid = 15 if e == "villager" else 44
        return "spawn_egg", eid
    if name in OLD_BEDROCK_NAMES:
        return OLD_BEDROCK_NAMES[name], 0
    return None


def bedrock_item_name(name: str, version: Tuple[int, ...]) -> str:
    """The Bedrock name of a Java item that is not one of the numeric era's blocks."""
    v = tuple(version)
    if name in ("turtle_scute", "scute"):
        return "turtle_scute" if v >= (1, 20, 80) else "scute"    # renamed with the armadillo
    if name in ("iron_chain", "chain"):
        return "iron_chain" if v >= (1, 21, 110) else "chain"
    return JAVA_TO_BEDROCK_NAME.get(name, name)


def from_old_bedrock(name: str, dmg: int) -> Optional[str]:
    """The Java name of an item saved with a Bedrock name of before 1.16.100 (in any case), else None."""
    k = name.lower()
    if k == "bucket":
        return next((n for n, d in OLD_BEDROCK_BUCKETS.items() if d == dmg), "bucket")
    if k == "boat":
        return f"{OLD_BEDROCK_BOATS[dmg if 0 <= dmg < len(OLD_BEDROCK_BOATS) else 0]}_boat"
    if k == "dye":
        if 0 <= dmg < 16:
            return DYE_ITEMS[dmg]
        return next((n for n, (d, _o) in OLD_BEDROCK_NEW_DYES.items() if d == dmg), "ink_sac")
    if k == "banner_pattern":
        return next((n for n, d in OLD_BEDROCK_PATTERNS.items() if d == dmg), None)
    if k == "spawn_egg":
        e = BEDROCK_ENTITY_NAMES.get(dmg & 0xFF)
        return f"{e}_spawn_egg" if e else None
    if k.startswith("record_"):
        return "music_disc_" + k[7:]
    return _OLD_BEDROCK_TO_JAVA.get(k)


# ------------------------------------------------------------------ PyMCTranslate helpers
@functools.lru_cache(maxsize=1)
def _tm():
    from .amulet_bridge import translation_manager

    return translation_manager()


def _placed_data(bid: int, dmg: int) -> int:
    """The data value of the block an item of numeric block ``bid`` and Damage ``dmg`` places: the
    Damage is not always a placed state (a torch is 0 in an inventory, 5 on the ground)."""
    if bid == 145:
        return (dmg & 3) << 2
    if bid in (50, 75, 76):
        return 5
    if bid in (54, 61, 65, 130, 146, 23, 158):
        return 2
    return dmg & 15


@functools.lru_cache(maxsize=None)
def legacy_block_item_name(bid: int, dmg: int) -> Optional[str]:
    """(numeric block id, item damage) -> flattened Java name."""
    data = _placed_data(bid, dmg)
    try:
        v12 = _tm().get_version("java", (1, 12, 2))
        v13 = _tm().get_version("java", (1, 13, 2))
        u = v12.block.to_universal(v12.ints_to_block(bid, data))[0]
        j = v13.block.from_universal(u)[0]
        name = j.base_name
    except Exception:  # noqa: BLE001
        return ids.java_block_names().get(bid)
    if name in ("air", "numerical"):
        return None if bid else "air"
    return {"wall_torch": "torch", "redstone_wall_torch": "redstone_torch", "sign": "oak_sign",
            "wall_sign": "oak_sign", "stone_slab": "smooth_stone_slab",  # 1.13's stone_slab (1.14 rename)
            "grass_path": "dirt_path"}.get(name, name)


@functools.lru_cache(maxsize=1)
def _flat_to_legacy() -> Dict[str, Tuple[int, int]]:
    out: Dict[str, Tuple[int, int]] = {}
    # blocks that are not obtainable as items go last so real item ids win
    not_items = {8, 9, 10, 11, 26, 34, 36, 43, 51, 55, 59, 62, 63, 64, 68, 71, 74, 75, 83, 90, 92, 93, 94, 104, 105,
                 115, 117, 118, 119, 124, 125, 127, 132, 140, 141, 142, 144, 149, 150, 176, 177, 178, 181, 193, 194,
                 195, 196, 197, 204, 207, 209, 212}
    for bid in [b for b in range(256) if b not in not_items]:
        for d in range(16):
            n = legacy_block_item_name(bid, d)
            if n and n not in out:
                out[n] = (bid, d)
    for (iid, dmg), n in LEGACY_ITEM_RENAMES.items():
        if dmg is not None:
            out[n] = (iid, dmg)
        elif n not in ("spawn_egg", "bed", "skull", "banner", "dye"):
            out[n] = (iid, 0)
    for iid, n in ids.JAVA_ITEMS.items():
        out.setdefault(n, (iid, 0))
    for i, n in enumerate(DYE_ITEMS):
        out[n] = (351, i)
    for i, c in enumerate(WOOL):
        out[f"{c}_bed"] = (355, i)
        out[f"{c}_banner"] = (425, 15 - i)
    for i, n in enumerate(SKULLS[:6]):
        out[n] = (397, i)
    for bid in sorted(not_items):
        for d in range(16):
            n = legacy_block_item_name(bid, d)
            if n and n not in out:
                out[n] = (bid, d)
    out.update({"rose_red": (351, 1), "cactus_green": (351, 2), "dandelion_yellow": (351, 11), "sign": (323, 0),
                "grass": (31, 1), "short_grass": (31, 1), "dirt_path": (208, 0),
                "stone_slab": (44, 0)})  # the plain stone slab (1.14+): the nearest one
    out.pop("air", None)
    return out


def flat_to_legacy(name: str) -> Optional[Tuple[int, int]]:
    n = name.split(":", 1)[-1]
    if n.endswith("_spawn_egg"):
        e = n[: -len("_spawn_egg")]
        eid = LEGACY_EGG_INV.get(e)
        return (383, eid) if eid is not None else None
    return _flat_to_legacy().get(n)


def legacy_to_flat(iid: int, dmg: int) -> Optional[str]:
    if iid < 256:
        return legacy_block_item_name(iid, dmg)
    if iid == 351:
        return DYE_ITEMS[dmg & 15]
    if iid == 355:
        return f"{WOOL[dmg & 15]}_bed"
    if iid == 425:
        return f"{WOOL[15 - (dmg & 15)]}_banner"
    if iid == 397:
        return SKULLS[min(dmg, 5)]
    if iid == 383:
        e = LEGACY_EGG.get(dmg)
        return f"{e}_spawn_egg" if e else "spawn_egg"  # Java 1.9+: the mob is in tag.EntityTag
    n = LEGACY_ITEM_RENAMES.get((iid, dmg)) or LEGACY_ITEM_RENAMES.get((iid, None))
    if n:
        return n
    return ids.JAVA_ITEMS.get(iid)


# Minecraft's own numeric id fix (ItemIdFix, data version 102) only knows the ids of Java 1.7:
# items 409 - 416 and 423 - 453 (mutton, banners, doors, shield, elytra, totem...) and blocks
# 165 - 255 (slime, prismarine, red sandstone, concrete...) become air.  Data opened by Java
# 1.9+ names its items the way Java 1.8 - 1.12 saved them, with the same Damage.
@functools.lru_cache(maxsize=1)
def _registry_names() -> Dict[int, str]:
    out = {i: n for i, n in ids.java_block_names().items() if i}
    out.update(ids.JAVA_ITEMS)
    return out


def named_item(t):
    """A legacy item with its numeric id written as the Java 1.8 - 1.12 registry name."""
    if not isinstance(t, nbt.CompoundTag):
        return t
    iid = nbt.get_tag(t, "id")
    if iid is None or isinstance(iid, nbt.StringTag):
        return t
    name = _registry_names().get(int(iid.py_data))
    if name is None:
        return t
    t = nbt.copy(t)
    t["id"] = nbt.StringTag("minecraft:" + name)
    return t


def named_items(lst) -> nbt.ListTag:
    """:func:`named_item` on every stack of a list (empty slots of positional lists stay)."""
    return nbt.ListTag([named_item(t) for t in lst], 10)


# ------------------------------------------------------------------ potions
def legacy_potion_type(dmg: int) -> str:
    if dmg == 0:
        return "water"
    eff = dmg & 15
    if eff == 0:
        return {16: "awkward", 32: "thick"}.get(dmg & 63, "mundane")
    name = LEGACY_POTION_EFFECT.get(eff, "mundane")
    if dmg & 32:
        return "strong_" + name
    if dmg & 64:
        return "long_" + name
    return name


def potion_type_to_legacy(t: str, splash: bool) -> int:
    t = t.split(":", 1)[-1]
    base = {"water": 0, "awkward": 16, "thick": 32, "mundane": 64}.get(t)
    if base is not None:
        return base | (16384 if splash and base else 0)
    strong = t.startswith("strong_")
    long_ = t.startswith("long_")
    eff = LEGACY_POTION_EFFECT_INV.get(t.replace("strong_", "").replace("long_", ""), 0)
    return eff | (32 if strong else 0) | (64 if long_ else 0) | (16384 if splash else 8192)


# ------------------------------------------------------------------ text helpers
def json_text(s: str) -> str:
    return json.dumps({"text": s}, ensure_ascii=False)


def plain_text(s) -> str:
    if s is None:
        return ""
    s = str(s)
    if s.startswith(("{", "[", '"')):
        try:
            return _flatten_json(json.loads(s))
        except ValueError:
            return s
    return s


def _flatten_json(j) -> str:
    if isinstance(j, str):
        return j
    if isinstance(j, list):
        return "".join(_flatten_json(x) for x in j)
    if isinstance(j, dict):
        return str(j.get("text", "")) + "".join(_flatten_json(x) for x in j.get("extra", []))
    return str(j)


# ------------------------------------------------------------------ canonical form
class Item(dict):
    """keys: name (flat, no namespace), count, damage (durability or variant), slot,
    ench [(name, lvl)], stored [(name, lvl)], custom_name, lore, color, potion, pages, author, title, extra_tag"""


def _ench_list(lst, table) -> list:
    out = []
    for e in lst or []:
        try:
            eid = e["id"].py_data
            lvl = int(e["lvl"].py_data)
        except (KeyError, AttributeError, TypeError):
            continue
        name = table.get(eid) if isinstance(eid, int) else str(eid).split(":", 1)[-1]
        if name:
            out.append((name, lvl))
    return out


def _is_damageable(name: str) -> bool:
    return name.endswith(("_sword", "_shovel", "_pickaxe", "_axe", "_hoe", "_helmet", "_chestplate", "_leggings",
                          "_boots")) or name in ("bow", "fishing_rod", "flint_and_steel", "shears", "shield",
                                                 "elytra", "carrot_on_a_stick", "trident", "crossbow", "mace",
                                                 "warped_fungus_on_a_stick", "brush", "wolf_armor") \
        or name.endswith("_spear")


def from_legacy(t: nbt.CompoundTag) -> Optional[Item]:
    iid = nbt.get(t, "id")
    if iid is None:
        return None
    dmg = int(nbt.get(t, "Damage", 0) or 0)
    if isinstance(iid, str):
        num = ids.item_id_from_name(iid)
        if num is None:
            name = iid.split(":", 1)[-1]
            iid = None
        else:
            iid = num
    if iid is not None:
        iid = int(iid)
        name = legacy_to_flat(iid, dmg)
        if name is None:
            return None
    it = Item(name=name, count=int(nbt.get(t, "Count", 1) or 1), damage=dmg if _is_damageable(name) else 0,
              slot=nbt.get(t, "Slot"))
    if iid in (373, 438, 441):
        it["potion"] = legacy_potion_type(dmg)
        if iid == 373 and dmg & 16384:
            it["name"] = "splash_potion"
    if iid == 358:
        it["map"] = dmg
    tag = nbt.get_tag(t, "tag")
    if tag is not None:
        _read_java_tag(it, tag, LEGACY_ENCH)
    if it["name"] == "spawn_egg":  # an egg without its mob spawns nothing
        return None
    return it


def _read_java_tag(it: Item, tag: nbt.CompoundTag, ench_table):
    it["ench"] = _ench_list(nbt.get_tag(tag, "ench") or nbt.get_tag(tag, "Enchantments"), ench_table)
    it["stored"] = _ench_list(nbt.get_tag(tag, "StoredEnchantments"), ench_table)
    disp = nbt.get_tag(tag, "display")
    if disp is not None:
        if "Name" in disp:
            it["custom_name"] = plain_text(nbt.get(disp, "Name"))
        if "Lore" in disp:
            it["lore"] = [plain_text(x.py_data) for x in disp["Lore"]]
        if "color" in disp:
            it["color"] = int(nbt.get(disp, "color"))
    if "Potion" in tag:
        it["potion"] = str(nbt.get(tag, "Potion")).split(":", 1)[-1]
    if "pages" in tag:
        it["pages"] = [plain_text(p.py_data) for p in tag["pages"]]
        it["author"] = nbt.get(tag, "author")
        it["title"] = nbt.get(tag, "title")
    if "map" in tag:
        it["map"] = int(nbt.get(tag, "map"))
    ent = nbt.get_tag(tag, "EntityTag")
    if ent is not None and it["name"] == "spawn_egg":
        e = str(nbt.get(ent, "id", "pig")).split(":", 1)[-1]
        e = ids.ENTITY_OLD_TO_NEW.get(e, e)
        it["name"] = f"{_ENTITY_113.get(e, e)}_spawn_egg"


def to_legacy(it: Item) -> Optional[nbt.CompoundTag]:
    name = it["name"]
    num = None
    if name in ("potion", "splash_potion", "lingering_potion", "tipped_arrow"):
        splash = name != "potion"
        num = ({"potion": 373, "splash_potion": 373, "lingering_potion": 441, "tipped_arrow": 440}[name],
               potion_type_to_legacy(it.get("potion", "water"), splash) if name != "tipped_arrow" else 0)
    elif name == "filled_map":
        num = (358, int(it.get("map", 0)))
    else:
        num = flat_to_legacy(name)
    if num is None:
        return None
    iid, dmg = num
    if _is_damageable(name):
        dmg = int(it.get("damage", 0))
    out = nbt.CompoundTag({"id": nbt.ShortTag(iid), "Count": nbt.ByteTag(max(1, min(64, int(it.get("count", 1))))),
                           "Damage": nbt.ShortTag(dmg)})
    if it.get("slot") is not None:
        out["Slot"] = nbt.ByteTag(int(it["slot"]))
    tag = nbt.CompoundTag()
    if it.get("ench"):
        tag["ench"] = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(LEGACY_ENCH_INV[n]), "lvl": nbt.ShortTag(l)})
                                   for n, l in it["ench"] if n in LEGACY_ENCH_INV], 10)
    if it.get("stored"):
        tag["StoredEnchantments"] = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(LEGACY_ENCH_INV[n]),
                                                                   "lvl": nbt.ShortTag(l)})
                                                 for n, l in it["stored"] if n in LEGACY_ENCH_INV], 10)
    disp = nbt.CompoundTag()
    if it.get("custom_name"):
        disp["Name"] = nbt.StringTag(it["custom_name"])
    if it.get("lore"):
        disp["Lore"] = nbt.ListTag([nbt.StringTag(x) for x in it["lore"]], 8)
    if it.get("color") is not None:
        disp["color"] = nbt.IntTag(it["color"])
    if len(disp):
        tag["display"] = disp
    if it.get("pages") is not None:
        tag["pages"] = nbt.ListTag([nbt.StringTag(p) for p in it["pages"]], 8)
        if it.get("author"):
            tag["author"] = nbt.StringTag(it["author"])
        if it.get("title"):
            tag["title"] = nbt.StringTag(it["title"])
    if len(tag):
        out["tag"] = tag
    return out


# ------------------------------------------------------------------ Java 1.13+
# older Java names of items (see _JAVA_RENAMES) that no later version uses for anything else
_JAVA_OLD_NAMES = {"sign": "oak_sign", "grass_path": "dirt_path", "scute": "turtle_scute", "rose_red": "red_dye",
                   "cactus_green": "green_dye", "dandelion_yellow": "yellow_dye",
                   "zombie_pigman_spawn_egg": "zombified_piglin_spawn_egg",
                   "semi_weathered_cut_copper": "weathered_cut_copper",
                   "semi_weathered_cut_copper_slab": "weathered_cut_copper_slab",
                   "semi_weathered_cut_copper_stairs": "weathered_cut_copper_stairs"}


def from_java_modern(t: nbt.CompoundTag) -> Optional[Item]:
    iid = nbt.get(t, "id")
    if not isinstance(iid, str):
        return from_legacy(t)
    name = iid.split(":", 1)[-1]
    name = _JAVA_OLD_NAMES.get(name, name)
    count = nbt.get(t, "count", nbt.get(t, "Count", 1))
    it = Item(name=name, count=int(count or 1), damage=0, slot=nbt.get(t, "Slot"))
    tag = nbt.get_tag(t, "tag")
    if tag is not None:
        it["damage"] = int(nbt.get(tag, "Damage", 0) or 0)
        _read_java_tag(it, tag, LEGACY_ENCH)
    comps = nbt.get_tag(t, "components")
    if comps is not None:
        _read_components(it, comps)
    return it


def _read_components(it: Item, c: nbt.CompoundTag):
    def g(k):
        return nbt.get_tag(c, "minecraft:" + k)

    if g("damage") is not None:
        it["damage"] = int(g("damage").py_data)
    for key, dst in (("enchantments", "ench"), ("stored_enchantments", "stored")):
        e = g(key)
        if e is not None:
            lv = nbt.get_tag(e, "levels") if "levels" in e else e
            it[dst] = [(k.split(":", 1)[-1], int(v.py_data)) for k, v in lv.items()] if lv is not None else []
    cn = g("custom_name")
    if cn is not None:
        it["custom_name"] = plain_text(cn.py_data) if isinstance(cn, nbt.StringTag) else plain_text(json.dumps(_snbt_text(cn)))
    pc = g("potion_contents")
    if pc is not None:
        p = pc.py_data if isinstance(pc, nbt.StringTag) else nbt.get(pc, "potion")
        if p:
            it["potion"] = str(p).split(":", 1)[-1]
    lore = g("lore")
    if lore is not None:
        it["lore"] = [_component_text(x) for x in lore]
    for key in ("written_book_content", "writable_book_content"):
        book = g(key)
        if book is not None:
            it["pages"] = [_component_text(nbt.get_tag(p, "raw") if isinstance(p, nbt.CompoundTag) else p)
                           for p in (nbt.get_tag(book, "pages") or [])]
            if key == "written_book_content":
                title = nbt.get_tag(book, "title")
                it["title"] = str(nbt.get(title, "raw", "") if isinstance(title, nbt.CompoundTag) else
                                  (title.py_data if title is not None else ""))
                it["author"] = str(nbt.get(book, "author", "") or "")
    dc = g("dyed_color")
    if dc is not None:
        it["color"] = int(dc.py_data) if not isinstance(dc, nbt.CompoundTag) else int(nbt.get(dc, "rgb", 0))
    mid = g("map_id")
    if mid is not None:
        it["map"] = int(mid.py_data)


def _component_text(tag) -> str:
    """Plain text of a text component: a JSON string (1.20.5 - 1.21.4) or NBT (1.21.5+)."""
    if tag is None:
        return ""
    if isinstance(tag, nbt.StringTag):
        return plain_text(tag.py_data)
    return plain_text(json.dumps(_snbt_text(tag)))


def _snbt_text(tag):
    if isinstance(tag, nbt.CompoundTag):
        return {k: _snbt_text(v) for k, v in tag.items()}
    if isinstance(tag, nbt.ListTag):
        return [_snbt_text(v) for v in tag]
    return getattr(tag, "py_data", tag)


# Item renames of Minecraft's data fixers after 1.13: (data version, old name, new name).  Data
# older than that version is renamed when the game upgrades it, data as new or newer must carry
# the new name: an item is written with the name that, once upgraded, is the intended one.
_JAVA_RENAMES = ((1901, "rose_red", "red_dye"), (1901, "cactus_green", "green_dye"),  # 1.14
                 (1901, "dandelion_yellow", "yellow_dye"),
                 (2509, "zombie_pigman_spawn_egg", "zombified_piglin_spawn_egg"),  # 1.16
                 (2680, "grass_path", "dirt_path"),
                 # a 1.17 snapshot shifted the copper names: semi_weathered -> weathered -> oxidized
                 (2690, "semi_weathered_cut_copper", "weathered_cut_copper"),
                 (2690, "semi_weathered_cut_copper_slab", "weathered_cut_copper_slab"),
                 (2690, "semi_weathered_cut_copper_stairs", "weathered_cut_copper_stairs"),
                 (3692, "grass", "short_grass"), (3800, "scute", "turtle_scute"), (4541, "chain", "iron_chain"))


def java_ench_name(name: str, data_version: int) -> str:
    """An enchantment's name as Java data of ``data_version`` names it."""
    for dv, old, new in _JAVA_ENCH_RENAMES:
        if data_version >= dv and name == old:
            return new
        if data_version < dv and name == new:
            return old
    return name


def java_item_name(name: str, data_version: int) -> str:
    """``name`` (a WorldBridge name, 1.13 - 1.21) as Java data of ``data_version`` names it."""
    if data_version < 1952 and name == "oak_sign":  # before 1.14
        return "sign"
    if data_version < 1952 and name == "smooth_stone_slab":  # 1.13's stone slab is the smooth one
        return "stone_slab"
    for dv, old, new in _JAVA_RENAMES:
        if data_version >= dv and name == old:
            name = new
        elif data_version < dv and name == new:
            name = old
    return name


# PyMCTranslate's Java 1.21.5 (the DataVersion its chunks are written with): every DataFixer step of
# 1.21.5 (text components as NBT, flattened enchantments, dyed_color as a number) lies below it, so
# data written with it must already be in the 1.21.5 format
TEXT_NBT_DV = 4324


def to_java_modern(it: Item, data_version: int) -> nbt.CompoundTag:
    name = java_item_name(it["name"], data_version)
    out = nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + name)})
    if it.get("slot") is not None:
        out["Slot"] = nbt.ByteTag(int(it["slot"]))
    if data_version >= 3837:  # 1.20.5 components
        out["count"] = nbt.IntTag(int(it.get("count", 1)))
        comps = nbt.CompoundTag()
        if it.get("damage"):
            comps["minecraft:damage"] = nbt.IntTag(int(it["damage"]))
        for key, src in (("minecraft:enchantments", "ench"), ("minecraft:stored_enchantments", "stored")):
            if it.get(src):
                lv = nbt.CompoundTag({"minecraft:" + java_ench_name(n, data_version): nbt.IntTag(l) for n, l in it[src]})
                comps[key] = lv if data_version >= TEXT_NBT_DV else nbt.CompoundTag({"levels": lv})  # 1.21.5 flattened
        nbt_text = data_version >= TEXT_NBT_DV  # 1.21.5: text components are NBT, a plain string is plain text

        def text(s):
            return nbt.StringTag(s if nbt_text else json_text(s))

        if it.get("custom_name"):
            comps["minecraft:custom_name"] = text(it["custom_name"])
        if it.get("lore"):
            comps["minecraft:lore"] = nbt.ListTag([text(x) for x in it["lore"]], 8)
        if it.get("color") is not None:
            comps["minecraft:dyed_color"] = (nbt.IntTag(int(it["color"])) if nbt_text
                                             else nbt.CompoundTag({"rgb": nbt.IntTag(int(it["color"]))}))
        if it.get("pages") is not None and name in ("written_book", "writable_book"):
            if name == "written_book":
                comps["minecraft:written_book_content"] = nbt.CompoundTag({
                    "pages": nbt.ListTag([nbt.CompoundTag({"raw": text(p)}) for p in it["pages"]], 10),
                    "title": nbt.CompoundTag({"raw": nbt.StringTag(it.get("title") or "")}),
                    "author": nbt.StringTag(it.get("author") or "")})
            else:
                comps["minecraft:writable_book_content"] = nbt.CompoundTag({
                    "pages": nbt.ListTag([nbt.CompoundTag({"raw": nbt.StringTag(p)}) for p in it["pages"]], 10)})
        if it.get("potion"):
            comps["minecraft:potion_contents"] = nbt.CompoundTag({"potion": nbt.StringTag("minecraft:" + it["potion"])})
        if it.get("map") is not None and name == "filled_map":
            comps["minecraft:map_id"] = nbt.IntTag(int(it["map"]))
        if len(comps):
            out["components"] = comps
        return out
    out["Count"] = nbt.ByteTag(int(it.get("count", 1)))
    tag = nbt.CompoundTag()
    if it.get("damage"):
        tag["Damage"] = nbt.IntTag(int(it["damage"]))
    if it.get("ench"):
        tag["Enchantments"] = nbt.ListTag([nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + java_ench_name(n, data_version)),
                                                             "lvl": nbt.ShortTag(l)})
                                           for n, l in it["ench"]], 10)
    if it.get("stored"):
        tag["StoredEnchantments"] = nbt.ListTag([nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + java_ench_name(n, data_version)),
                                                                   "lvl": nbt.ShortTag(l)})
                                                 for n, l in it["stored"]], 10)
    disp = nbt.CompoundTag()
    if it.get("custom_name"):
        disp["Name"] = nbt.StringTag(json_text(it["custom_name"]))
    if it.get("lore"):
        disp["Lore"] = nbt.ListTag([nbt.StringTag(json_text(x)) for x in it["lore"]], 8)
    if it.get("color") is not None:
        disp["color"] = nbt.IntTag(it["color"])
    if len(disp):
        tag["display"] = disp
    if it.get("potion"):
        tag["Potion"] = nbt.StringTag("minecraft:" + it["potion"])
    if it.get("map") is not None and name == "filled_map":
        tag["map"] = nbt.IntTag(int(it["map"]))
    if it.get("pages") is not None:
        written = name == "written_book"
        tag["pages"] = nbt.ListTag([nbt.StringTag(json_text(p) if written else p) for p in it["pages"]], 8)
        if written:
            tag["author"] = nbt.StringTag(it.get("author") or "")
            tag["title"] = nbt.StringTag(it.get("title") or "")
    if len(tag):
        out["tag"] = tag
    return out


# ------------------------------------------------------------------ Bedrock
@functools.lru_cache(maxsize=None)
def _bedrock_block_for_flat(name: str, version: Tuple[int, ...]) -> Optional[Tuple[str, dict]]:
    if name == "stone_stairs":  # the numeric table has no plain stone stairs (67 is cobblestone): Bedrock's are normal_
        b = _bedrock_block_for_flat("cobblestone_stairs", version)
        return None if b is None else ("minecraft:normal_stone_stairs", b[1])
    leg = flat_to_legacy(name)
    if leg is None or leg[0] >= 256:
        return None
    bid, d = leg
    data = _placed_data(bid, d)
    try:
        v12 = _tm().get_version("java", (1, 12, 2))
        vb = _tm().get_version("bedrock", version)
        u = v12.block.to_universal(v12.ints_to_block(bid, data))[0]
        b = vb.block.from_universal(u)[0]
        if tuple(version) >= (1, 13, 0) and "block_data" in b.properties:
            return None  # no state of this block: written without a Block, the game places its default
        return b.namespaced_name, dict(b.properties)
    except Exception:  # noqa: BLE001
        return None


@functools.lru_cache(maxsize=1)
def _bedrock_variant_blocks() -> frozenset:
    """Bedrock blocks of the numeric era that several items share, told apart by the item's Damage
    (wool, planks, log, fence, stone_slab, shulker_box...)."""
    seen: Dict[str, set] = {}
    for n, (bid, _d) in _flat_to_legacy().items():
        if bid < 256:
            b = _bedrock_block_for_flat(n, (1, 12, 0))
            if b is not None:
                seen.setdefault(b[0], set()).add(n)
    return frozenset(k for k, v in seen.items() if len(v) > 1)


def _bedrock_block_item_aux(name: str, bname: str) -> Optional[int]:
    """The Damage of a Bedrock block item that shares its block with other variants: the variant's
    data value (red wool 14, birch planks 2, Bedrock's own order for slabs and fences).  Bedrock
    saves it next to the Block states, and before 1.13 the item is only its name and Damage."""
    b12 = _bedrock_block_for_flat(name, (1, 12, 0))
    if b12 is None or b12[0] != bname or bname not in _bedrock_variant_blocks():
        return None
    bd = b12[1].get("block_data")
    return None if bd is None else int(getattr(bd, "py_data", bd))


def to_bedrock(it: Item, version: Tuple[int, ...]) -> Optional[nbt.CompoundTag]:
    name = it["name"]
    dmg = int(it.get("damage", 0))
    bname = None
    block = None
    if name.endswith("_bed") and name[:-4] in WOOL:
        bname, dmg = "minecraft:bed", WOOL.index(name[:-4])
    elif name.endswith("_banner") and name[:-7] in WOOL:
        bname, dmg = "minecraft:banner", 15 - WOOL.index(name[:-7])
    elif name in SKULLS:
        bname, dmg = "minecraft:skull", SKULLS.index(name)
    elif name in ("potion", "splash_potion", "lingering_potion"):
        bname, dmg = "minecraft:" + name, BEDROCK_POTIONS_INV.get(it.get("potion", "water"), 0)
    elif name == "tipped_arrow":
        bname, dmg = "minecraft:arrow", BEDROCK_POTIONS_INV.get(it.get("potion", "water"), 0) + 1
    elif old_bedrock_item(name, version) is not None:  # before 1.16.100: old names, variants by Damage
        bname, dmg = old_bedrock_item(name, version)
        bname = "minecraft:" + bname
    else:
        b = _bedrock_block_for_flat(name, tuple(version))
        if b is not None:
            bname = b[0]
            block = b
            aux = _bedrock_block_item_aux(name, b[0])
            if aux is not None:
                dmg = aux
        else:
            bname = "minecraft:" + bedrock_item_name(name, version)
    out = nbt.CompoundTag({"Name": nbt.StringTag(bname), "Count": nbt.ByteTag(max(1, min(127, int(it.get("count", 1))))),
                           "Damage": nbt.ShortTag(dmg), "WasPickedUp": nbt.ByteTag(0)})
    if it.get("slot") is not None:
        out["Slot"] = nbt.ByteTag(int(it["slot"]))
    if block is not None:
        states = nbt.CompoundTag()
        for k, v in block[1].items():
            states[k.split(":", 1)[-1] if k.startswith("minecraft:") and False else k] = v
        out["Block"] = nbt.CompoundTag({"name": nbt.StringTag(block[0]), "states": states, "version": nbt.IntTag(_bedrock_block_version(version))})
    tag = nbt.CompoundTag()
    if name == "filled_map":
        out["Damage"] = nbt.ShortTag(0)  # Bedrock: 0 = ordinary map; the map is named by its uuid
        if it.get("map") is not None:
            tag["map_uuid"] = nbt.LongTag(bedrock_map_uuid(int(it["map"])))
    if _is_damageable(name) and it.get("damage"):
        tag["Damage"] = nbt.IntTag(int(it["damage"]))
    ench = [(BEDROCK_ENCH_INV.get(n), l) for n, l in (it.get("ench") or []) + (it.get("stored") or [])]
    ench = [(i, l) for i, l in ench if i is not None]
    if ench:
        tag["ench"] = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(i), "lvl": nbt.ShortTag(l)}) for i, l in ench], 10)
    disp = nbt.CompoundTag()
    if it.get("custom_name"):
        disp["Name"] = nbt.StringTag(it["custom_name"])
    if it.get("lore"):
        disp["Lore"] = nbt.ListTag([nbt.StringTag(x) for x in it["lore"]], 8)
    if len(disp):
        tag["display"] = disp
    if it.get("color") is not None:
        tag["customColor"] = nbt.IntTag(it["color"] | -16777216 if it["color"] < 0x1000000 else it["color"])
    if it.get("pages") is not None:
        tag["pages"] = nbt.ListTag([nbt.CompoundTag({"text": nbt.StringTag(p), "photoname": nbt.StringTag("")})
                                    for p in it["pages"]], 10)
        if name == "written_book":
            tag["author"] = nbt.StringTag(it.get("author") or "")
            tag["title"] = nbt.StringTag(it.get("title") or "")
    if len(tag):
        out["tag"] = tag
    return out


def _bedrock_block_version(version) -> int:
    """The block-state version of Bedrock ``version`` (26.50 writes 1.21.60.33, not 26.50)."""
    from .gameversion import bedrock_block_version as bbv

    return bbv(tuple(version))


@functools.lru_cache(maxsize=1)
def _latest(platform: str) -> Tuple[int, ...]:
    return max(tuple(v) for v in _tm().version_numbers(platform))


def bedrock_block_version(blk: nbt.CompoundTag) -> Tuple[int, ...]:
    """The game version a Bedrock block compound was saved with (its ``version``), else the latest:
    Bedrock renames blocks (stone_block_slab4 -> normal_stone_slab...), the names need the right table."""
    v = int(nbt.get(blk, "version", 0) or 0)
    ver = (v >> 24 & 255, v >> 16 & 255, v >> 8 & 255)
    return ver if ver[0] >= 1 else _latest("bedrock")


@functools.lru_cache(maxsize=1)
def _java_block_names() -> frozenset:
    """The block names of the newest Java version: what a block item of a Java target may be called."""
    try:
        return frozenset(_tm().get_version("java", _latest("java")).block.base_names("minecraft"))
    except Exception:  # noqa: BLE001
        return frozenset(_flat_to_legacy())


@functools.lru_cache(maxsize=None)
def _bedrock_block_to_flat(name: str, states_key: tuple, version: Optional[Tuple[int, ...]] = None) -> Optional[str]:
    try:
        from amulet.api.block import Block

        ver = _tm().get_version("bedrock", version or _latest("bedrock"))
        v13 = _tm().get_version("java", _latest("java"))
        ns, base = name.split(":", 1) if ":" in name else ("minecraft", name)
        blk = Block(ns, base, dict(states_key))
        u = ver.block.to_universal(blk)[0]
        j = v13.block.from_universal(u)[0]
        return j.base_name
    except Exception:  # noqa: BLE001
        return None


# Pocket Edition 0.9 - 0.16 item ids that are not Java's: (Java id, Damage) of the Java 1.8 - 1.12 item
_PE_ITEM_IDS = {457: (434, 0), 458: (435, 0), 459: (436, 0), 460: (349, 1), 461: (349, 2), 462: (349, 3),
                463: (350, 1), 466: (322, 1)}


def _from_pe_numeric(t: nbt.CompoundTag) -> Optional[Item]:
    """An item of a Pocket Edition 0.9 - 0.16 world: ``{id: short, Damage, Count, tag}`` with the numeric
    ids of the time (Java's, bar a few blocks and items) and no Name."""
    iid = nbt.get(t, "id")
    if isinstance(iid, str) or not isinstance(iid, int) or iid <= 0 or int(nbt.get(t, "Count", 1) or 0) <= 0:
        return None            # id 0, or Count 0 / -1: an empty slot (the hotbar's links are id 255, Count -1)
    dmg = int(nbt.get(t, "Damage", 0) or 0)
    if iid < 256:
        from .bedrock.pe_old import PE_TO_JAVA

        iid, dmg = PE_TO_JAVA.get(iid, (iid, dmg))
    iid, dmg = _PE_ITEM_IDS.get(iid, (iid, dmg))
    if iid == 383:  # a spawn egg: the Damage is Bedrock's entity number
        mob = BEDROCK_ENTITY_NAMES.get(dmg & 0xFF)
        if mob is None:
            return None
        it = Item(name=f"{mob}_spawn_egg", count=int(nbt.get(t, "Count", 1) or 1), damage=0, slot=nbt.get(t, "Slot"))
    else:
        t2 = nbt.CompoundTag({"id": nbt.ShortTag(iid), "Damage": nbt.ShortTag(dmg),
                              "Count": nbt.ByteTag(int(nbt.get(t, "Count", 1) or 1))})
        if nbt.get(t, "Slot") is not None:
            t2["Slot"] = nbt.ByteTag(int(nbt.get(t, "Slot")))
        it = from_legacy(t2)
        if it is None or it["name"] == "air":
            return None
    tag = nbt.get_tag(t, "tag")
    if tag is not None:
        ench = _ench_list(nbt.get_tag(tag, "ench"), dict(enumerate(BEDROCK_ENCH)))   # Bedrock's enchantment ids
        it["stored" if it["name"] == "enchanted_book" else "ench"] = ench
        disp = nbt.get_tag(tag, "display")
        if disp is not None:
            if "Name" in disp:
                it["custom_name"] = str(nbt.get(disp, "Name"))
            if "Lore" in disp:
                it["lore"] = [str(x.py_data) for x in disp["Lore"]]
        if "customColor" in tag:
            it["color"] = int(nbt.get(tag, "customColor")) & 0xFFFFFF
    return it


def from_bedrock(t: nbt.CompoundTag) -> Optional[Item]:
    name = str(nbt.get(t, "Name", "") or "")
    if not name:
        return _from_pe_numeric(t) if nbt.get(t, "id") is not None else None
    n = name.split(":", 1)[-1]
    dmg = int(nbt.get(t, "Damage", 0) or 0)
    it = Item(count=int(nbt.get(t, "Count", 1) or 1), damage=0, slot=nbt.get(t, "Slot"))
    if n in ("potion", "splash_potion", "lingering_potion"):
        it["name"] = n
        it["potion"] = BEDROCK_POTIONS[dmg] if dmg < len(BEDROCK_POTIONS) else "water"
    elif n == "arrow" and dmg > 0:
        it["name"] = "tipped_arrow"
        it["potion"] = BEDROCK_POTIONS[dmg - 1] if dmg - 1 < len(BEDROCK_POTIONS) else "water"
    elif n == "bed":
        it["name"] = f"{WOOL[dmg & 15]}_bed"
    elif n == "banner":
        it["name"] = f"{WOOL[15 - (dmg & 15)]}_banner"
    elif n == "skull":
        it["name"] = SKULLS[min(dmg, 6)]
    elif n == "spawn_egg":  # before 1.16.100: the mob is the Damage
        it["name"] = from_old_bedrock(n, dmg)
        if it["name"] is None:
            return None
    else:
        blk = nbt.get_tag(t, "Block")
        flat = None
        if blk is not None and "name" in blk:
            states = nbt.get_tag(blk, "states") or nbt.CompoundTag()
            bver = bedrock_block_version(blk)
            if bver >= (1, 13, 0):  # before it the translation tables return Bedrock's own numeric-era name
                flat = _bedrock_block_to_flat(str(nbt.get(blk, "name")),
                                              tuple(sorted(states.items(), key=lambda kv: kv[0])), bver)
                if flat is not None and flat not in _java_block_names():
                    flat = None  # not a Java id ("planks"): the numeric id and Damage name it
        if flat is None:  # names of before 1.16.100 (bucket / boat / dye + Damage, horsearmoriron...)
            flat = from_old_bedrock(n, dmg)
        # pre-1.19 Bedrock names are the numeric-era ones ("log", "wool" + Damage), also with Damage 0
        if flat is None and ids.item_id_from_name(n) is not None:
            leg = legacy_to_flat(ids.item_id_from_name(n), dmg)
            flat = leg
        if flat is None:
            flat = BEDROCK_TO_JAVA_NAME.get(n, n)
        it["name"] = flat
    tag = nbt.get_tag(t, "tag")
    if tag is not None:
        if _is_damageable(it["name"]):
            it["damage"] = int(nbt.get(tag, "Damage", 0) or 0)
        ench = []
        for e in nbt.get_tag(tag, "ench") or []:
            i = int(nbt.get(e, "id", -1))
            if 0 <= i < len(BEDROCK_ENCH):
                ench.append((BEDROCK_ENCH[i], int(nbt.get(e, "lvl", 1))))
        if it["name"] == "enchanted_book":
            it["stored"] = ench
        else:
            it["ench"] = ench
        disp = nbt.get_tag(tag, "display")
        if disp is not None:
            if "Name" in disp:
                it["custom_name"] = str(nbt.get(disp, "Name"))
            if "Lore" in disp:
                it["lore"] = [str(x.py_data) for x in disp["Lore"]]
        if "customColor" in tag:
            it["color"] = int(nbt.get(tag, "customColor")) & 0xFFFFFF
        if "pages" in tag:
            it["pages"] = [str(nbt.get(p, "text", "")) for p in tag["pages"]]
            it["author"] = nbt.get(tag, "author")
            it["title"] = nbt.get(tag, "title")
        if it["name"] == "filled_map" and nbt.get(tag, "map_uuid") is not None:
            it["map"] = java_map_id(int(nbt.get(tag, "map_uuid")))
    return it


# Bedrock names a map by a 64 bit id, Java / LCE by a small number (map_<n>.dat): a fixed,
# reversible mapping keeps the maps in item frames and inventories pointing at their data.
_MAP_BASE = -0x5742000000000000


def bedrock_map_uuid(n: int) -> int:
    return _MAP_BASE - n


def java_map_id(uuid: int) -> int:
    n = _MAP_BASE - uuid
    if 0 <= n < 1 << 30:
        return n  # one of ours
    return (uuid & 0x3FFFFFFF) | 0x40000000  # a map made in Bedrock: stable, far from Java's own numbers


# ------------------------------------------------------------------ players
# Java 1.21.5 moved a player's armour and off hand out of the inventory, into "equipment"
EQUIPMENT_SLOTS = {"feet": 100, "legs": 101, "chest": 102, "head": 103, "offhand": -106}


def player_stacks(p: nbt.CompoundTag) -> nbt.ListTag:
    """A Java / LCE player's inventory with the armour and off hand in their slots (100 - 103,
    -106), also when the player is Java 1.21.5+ data and keeps them in ``equipment``."""
    out = nbt.ListTag([t for t in (nbt.get_tag(p, "Inventory") or []) if isinstance(t, nbt.CompoundTag)], 10)
    eq = nbt.get_tag(p, "equipment")
    if isinstance(eq, nbt.CompoundTag):
        used = {int(nbt.get(t, "Slot", -1000)) for t in out}
        for key, slot in EQUIPMENT_SLOTS.items():
            t = nbt.get_tag(eq, key)
            if isinstance(t, nbt.CompoundTag) and len(t) and slot not in used:
                t = nbt.copy(t)
                t["Slot"] = nbt.ByteTag(slot)
                out.append(t)
    return out


# ------------------------------------------------------------------ list helpers
def convert_list(lst, src: str, dst: str, **kw) -> nbt.ListTag:
    reader = {"legacy": from_legacy, "java": from_java_modern, "bedrock": from_bedrock}[src]
    out = nbt.ListTag([], 10)
    for t in lst or []:
        if not isinstance(t, nbt.CompoundTag) or len(t) == 0:
            continue
        it = reader(t)
        if it is None or not it.get("name") or it["name"] == "air":
            continue
        w = write(it, dst, **kw)
        if w is not None:
            out.append(w)
    return out


def write(it: Item, dst: str, **kw):
    if dst == "legacy":
        return to_legacy(it)
    if dst == "java":
        return to_java_modern(it, kw.get("data_version", 3465))
    return to_bedrock(it, kw.get("version", (1, 21, 0)))


def convert_one(t, src: str, dst: str, **kw):
    reader = {"legacy": from_legacy, "java": from_java_modern, "bedrock": from_bedrock}[src]
    if not isinstance(t, nbt.CompoundTag) or len(t) == 0:
        return None
    it = reader(t)
    if it is None:
        return None
    return write(it, dst, **kw)
