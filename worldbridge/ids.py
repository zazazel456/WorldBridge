"""Identifier tables shared by the numeric formats.

The hub model stores entities / block entities with their *legacy* ids
("Pig", "Chest") and items with numeric ids, exactly like Java Edition
1.2 - 1.8 and Legacy Console Edition do.  Java Edition itself upgrades
this data (DataFixerUpper) when such a world is opened in any newer
version.  These tables are used when data coming from a newer format has
to be written back into a numeric/legacy format.
"""

from __future__ import annotations

import functools
from typing import Dict, Optional, Tuple

# ------------------------------------------------------------------ items

JAVA_ITEMS: Dict[int, str] = {
    256: "iron_shovel", 257: "iron_pickaxe", 258: "iron_axe", 259: "flint_and_steel", 260: "apple",
    261: "bow", 262: "arrow", 263: "coal", 264: "diamond", 265: "iron_ingot", 266: "gold_ingot",
    267: "iron_sword", 268: "wooden_sword", 269: "wooden_shovel", 270: "wooden_pickaxe", 271: "wooden_axe",
    272: "stone_sword", 273: "stone_shovel", 274: "stone_pickaxe", 275: "stone_axe", 276: "diamond_sword",
    277: "diamond_shovel", 278: "diamond_pickaxe", 279: "diamond_axe", 280: "stick", 281: "bowl",
    282: "mushroom_stew", 283: "golden_sword", 284: "golden_shovel", 285: "golden_pickaxe", 286: "golden_axe",
    287: "string", 288: "feather", 289: "gunpowder", 290: "wooden_hoe", 291: "stone_hoe", 292: "iron_hoe",
    293: "diamond_hoe", 294: "golden_hoe", 295: "wheat_seeds", 296: "wheat", 297: "bread",
    298: "leather_helmet", 299: "leather_chestplate", 300: "leather_leggings", 301: "leather_boots",
    302: "chainmail_helmet", 303: "chainmail_chestplate", 304: "chainmail_leggings", 305: "chainmail_boots",
    306: "iron_helmet", 307: "iron_chestplate", 308: "iron_leggings", 309: "iron_boots",
    310: "diamond_helmet", 311: "diamond_chestplate", 312: "diamond_leggings", 313: "diamond_boots",
    314: "golden_helmet", 315: "golden_chestplate", 316: "golden_leggings", 317: "golden_boots",
    318: "flint", 319: "porkchop", 320: "cooked_porkchop", 321: "painting", 322: "golden_apple",
    323: "sign", 324: "wooden_door", 325: "bucket", 326: "water_bucket", 327: "lava_bucket",
    328: "minecart", 329: "saddle", 330: "iron_door", 331: "redstone", 332: "snowball", 333: "boat",
    334: "leather", 335: "milk_bucket", 336: "brick", 337: "clay_ball", 338: "reeds", 339: "paper",
    340: "book", 341: "slime_ball", 342: "chest_minecart", 343: "furnace_minecart", 344: "egg",
    345: "compass", 346: "fishing_rod", 347: "clock", 348: "glowstone_dust", 349: "fish",
    350: "cooked_fish", 351: "dye", 352: "bone", 353: "sugar", 354: "cake", 355: "bed", 356: "repeater",
    357: "cookie", 358: "filled_map", 359: "shears", 360: "melon", 361: "pumpkin_seeds",
    362: "melon_seeds", 363: "beef", 364: "cooked_beef", 365: "chicken", 366: "cooked_chicken",
    367: "rotten_flesh", 368: "ender_pearl", 369: "blaze_rod", 370: "ghast_tear", 371: "gold_nugget",
    372: "nether_wart", 373: "potion", 374: "glass_bottle", 375: "spider_eye", 376: "fermented_spider_eye",
    377: "blaze_powder", 378: "magma_cream", 379: "brewing_stand", 380: "cauldron", 381: "ender_eye",
    382: "speckled_melon", 383: "spawn_egg", 384: "experience_bottle", 385: "fire_charge",
    386: "writable_book", 387: "written_book", 388: "emerald", 389: "item_frame", 390: "flower_pot",
    391: "carrot", 392: "potato", 393: "baked_potato", 394: "poisonous_potato", 395: "map",
    396: "golden_carrot", 397: "skull", 398: "carrot_on_a_stick", 399: "nether_star", 400: "pumpkin_pie",
    401: "fireworks", 402: "firework_charge", 403: "enchanted_book", 404: "comparator", 405: "netherbrick",
    406: "quartz", 407: "tnt_minecart", 408: "hopper_minecart", 409: "prismarine_shard",
    410: "prismarine_crystals", 411: "rabbit", 412: "cooked_rabbit", 413: "rabbit_stew", 414: "rabbit_foot",
    415: "rabbit_hide", 416: "armor_stand", 417: "iron_horse_armor", 418: "golden_horse_armor",
    419: "diamond_horse_armor", 420: "lead", 421: "name_tag", 422: "command_block_minecart", 423: "mutton",
    424: "cooked_mutton", 425: "banner", 426: "end_crystal", 427: "spruce_door", 428: "birch_door",
    429: "jungle_door", 430: "acacia_door", 431: "dark_oak_door", 432: "chorus_fruit",
    433: "chorus_fruit_popped", 434: "beetroot", 435: "beetroot_seeds", 436: "beetroot_soup",
    437: "dragon_breath", 438: "splash_potion", 439: "spectral_arrow", 440: "tipped_arrow",
    441: "lingering_potion", 442: "shield", 443: "elytra", 444: "spruce_boat", 445: "birch_boat",
    446: "jungle_boat", 447: "acacia_boat", 448: "dark_oak_boat", 449: "totem_of_undying",
    450: "shulker_shell", 452: "iron_nugget", 453: "knowledge_book",
    2256: "record_13", 2257: "record_cat", 2258: "record_blocks", 2259: "record_chirp", 2260: "record_far",
    2261: "record_mall", 2262: "record_mellohi", 2263: "record_stal", 2264: "record_strad",
    2265: "record_ward", 2266: "record_11", 2267: "record_wait",
}


@functools.lru_cache(maxsize=1)
def java_block_names() -> Dict[int, str]:
    """Java 1.12.2 numeric block id -> registry name (from PyMCTranslate)."""
    try:
        import PyMCTranslate

        tm = PyMCTranslate.new_translation_manager()
        v = tm.get_version("java", (1, 12, 2))
        out = {}
        for i in range(256):
            b = v.ints_to_block(i, 0)
            if b.base_name != "numerical":
                out[i] = b.base_name
        return out
    except Exception:  # noqa: BLE001
        return {0: "air", 1: "stone", 2: "grass", 3: "dirt", 4: "cobblestone"}


@functools.lru_cache(maxsize=1)
def item_name_to_id() -> Dict[str, int]:
    out = {v: k for k, v in java_block_names().items()}
    out.update({v: k for k, v in JAVA_ITEMS.items()})
    # 1.13+ names that map back onto numeric items (with damage where needed)
    return out


def item_id_from_name(name: str) -> Optional[int]:
    n = name.split(":", 1)[-1]
    return item_name_to_id().get(n)


# ------------------------------------------------------------------ entities
# Java 1.11 EntityIdFix: old id -> new id
ENTITY_OLD_TO_NEW: Dict[str, str] = {
    "AreaEffectCloud": "area_effect_cloud", "ArmorStand": "armor_stand", "Arrow": "arrow", "Bat": "bat",
    "Blaze": "blaze", "Boat": "boat", "CaveSpider": "cave_spider", "Chicken": "chicken", "Cow": "cow",
    "Creeper": "creeper", "Donkey": "donkey", "DragonFireball": "dragon_fireball",
    "ElderGuardian": "elder_guardian", "EnderCrystal": "ender_crystal", "EnderDragon": "ender_dragon",
    "Enderman": "enderman", "Endermite": "endermite", "EyeOfEnderSignal": "eye_of_ender_signal",
    "FallingSand": "falling_block", "Fireball": "fireball", "FireworksRocketEntity": "fireworks_rocket",
    "Ghast": "ghast", "Giant": "giant", "Guardian": "guardian", "Horse": "horse", "Husk": "husk",
    "Item": "item", "ItemFrame": "item_frame", "LavaSlime": "magma_cube", "LeashKnot": "leash_knot",
    "MinecartChest": "chest_minecart", "MinecartCommandBlock": "commandblock_minecart",
    "MinecartFurnace": "furnace_minecart", "MinecartHopper": "hopper_minecart",
    "MinecartRideable": "minecart", "MinecartSpawner": "spawner_minecart", "MinecartTNT": "tnt_minecart",
    "Mule": "mule", "MushroomCow": "mooshroom", "Ozelot": "ocelot", "Painting": "painting", "Pig": "pig",
    "PigZombie": "zombie_pigman", "PolarBear": "polar_bear", "PrimedTnt": "tnt", "Rabbit": "rabbit",
    "Sheep": "sheep", "Shulker": "shulker", "ShulkerBullet": "shulker_bullet", "Silverfish": "silverfish",
    "Skeleton": "skeleton", "SkeletonHorse": "skeleton_horse", "Slime": "slime",
    "SmallFireball": "small_fireball", "SnowMan": "snowman", "Snowball": "snowball",
    "SpectralArrow": "spectral_arrow", "Spider": "spider", "Squid": "squid", "Stray": "stray",
    "ThrownEgg": "egg", "ThrownEnderpearl": "ender_pearl", "ThrownExpBottle": "xp_bottle",
    "ThrownPotion": "potion", "Villager": "villager", "VillagerGolem": "villager_golem", "Witch": "witch",
    "WitherBoss": "wither", "WitherSkeleton": "wither_skeleton", "WitherSkull": "wither_skull",
    "Wolf": "wolf", "XPOrb": "xp_orb", "Zombie": "zombie", "ZombieHorse": "zombie_horse",
    "ZombieVillager": "zombie_villager", "EvocationIllager": "evocation_illager",
    "VindicationIllager": "vindication_illager", "Vex": "vex", "Llama": "llama", "LlamaSpit": "llama_spit",
    "EvocationFangs": "evocation_fangs", "IllusionIllager": "illusion_illager", "Parrot": "parrot",
}
ENTITY_NEW_TO_OLD: Dict[str, str] = {v: k for k, v in ENTITY_OLD_TO_NEW.items()}
ENTITY_NEW_TO_OLD.update({
    # 1.13+ renames
    "zombified_piglin": "PigZombie", "iron_golem": "VillagerGolem", "snow_golem": "SnowMan",
    "experience_orb": "XPOrb", "experience_bottle": "ThrownExpBottle", "tnt_minecart": "MinecartTNT",
    "command_block_minecart": "MinecartCommandBlock", "firework_rocket": "FireworksRocketEntity",
    "eye_of_ender": "EyeOfEnderSignal", "end_crystal": "EnderCrystal", "evoker": "EvocationIllager",
    "vindicator": "VindicationIllager", "illusioner": "IllusionIllager", "evoker_fangs": "EvocationFangs",
})

# (old id, extra NBT) used to express 1.11 split entities in the pre-1.11 format
ENTITY_SPLIT_TO_OLD: Dict[str, Tuple[str, dict]] = {
    "donkey": ("EntityHorse", {"Type": 1}), "mule": ("EntityHorse", {"Type": 2}),
    "zombie_horse": ("EntityHorse", {"Type": 3}), "skeleton_horse": ("EntityHorse", {"Type": 4}),
    "horse": ("EntityHorse", {"Type": 0}), "wither_skeleton": ("Skeleton", {"SkeletonType": 1}),
    "stray": ("Skeleton", {"SkeletonType": 2}), "zombie_villager": ("Zombie", {"IsVillager": 1}),
    "husk": ("Zombie", {"ZombieType": 6}), "elder_guardian": ("Guardian", {"Elder": 1}),
}

# ------------------------------------------------------------------ block entities
TILE_OLD_TO_NEW: Dict[str, str] = {
    "Airportal": "end_portal", "Banner": "banner", "Beacon": "beacon", "Cauldron": "brewing_stand",
    "Chest": "chest", "Comparator": "comparator", "Control": "command_block",
    "DLDetector": "daylight_detector", "Dropper": "dropper", "EnchantTable": "enchanting_table",
    "EndGateway": "end_gateway", "EnderChest": "ender_chest", "FlowerPot": "flower_pot",
    "Furnace": "furnace", "Hopper": "hopper", "MobSpawner": "mob_spawner", "Music": "noteblock",
    "Piston": "piston", "RecordPlayer": "jukebox", "Sign": "sign", "Skull": "skull",
    "Structure": "structure_block", "Trap": "dispenser", "Bed": "bed", "ShulkerBox": "shulker_box",
}
TILE_NEW_TO_OLD: Dict[str, str] = {v: k for k, v in TILE_OLD_TO_NEW.items()}
TILE_NEW_TO_OLD.update({"enchantment_table": "EnchantTable", "note_block": "Music", "spawner": "MobSpawner",
                        "trapped_chest": "Chest"})


def entity_to_old(eid: str) -> Tuple[Optional[str], dict]:
    """Namespaced/new entity id -> (legacy id, extra tags)."""
    if not eid:
        return None, {}
    if ":" not in eid and eid[:1].isupper():
        return eid, {}
    n = eid.split(":", 1)[-1]
    if n in ENTITY_SPLIT_TO_OLD:
        return ENTITY_SPLIT_TO_OLD[n]
    return ENTITY_NEW_TO_OLD.get(n), {}


def tile_to_old(tid: str) -> Optional[str]:
    if not tid:
        return None
    if ":" not in tid and tid[:1].isupper():
        return tid
    n = tid.split(":", 1)[-1]
    if n.endswith("_shulker_box"):
        n = "shulker_box"
    if n.endswith("_bed"):
        n = "bed"
    if n.endswith("_banner") or n.endswith("_wall_banner"):
        n = "banner"
    if n.endswith("sign"):
        n = "sign"
    return TILE_NEW_TO_OLD.get(n)


# ------------------------------------------------------------------ LCE Aquatic blocks
# LCE numeric id (256+, TU69+) -> (Java 1.13 block state, closest Java 1.12 (id, data))
LCE_MODERN_BLOCKS: Dict[int, Tuple[str, Tuple[int, int]]] = {
    256: ("minecraft:conduit", (138, 0)),
    257: ("minecraft:pumpkin", (86, 0)),
    258: ("minecraft:kelp", (9, 0)),
    259: ("minecraft:tube_coral_block", (35, 11)),
    263: ("minecraft:tube_coral", (9, 0)),
    264: ("minecraft:tube_coral_fan", (9, 0)),
    265: ("minecraft:dead_tube_coral_fan", (0, 0)),
    266: ("minecraft:tube_coral_wall_fan", (9, 0)),
    267: ("minecraft:brain_coral_wall_fan", (9, 0)),
    268: ("minecraft:fire_coral_wall_fan", (9, 0)),
    269: ("minecraft:dried_kelp_block", (35, 13)),
    270: ("minecraft:seagrass", (9, 0)),
    271: ("minecraft:sea_pickle", (0, 0)),
    272: ("minecraft:bubble_column", (9, 0)),
    273: ("minecraft:blue_ice", (174, 0)),
    274: ("minecraft:spruce_trapdoor", (96, 0)),
    275: ("minecraft:birch_trapdoor", (96, 0)),
    276: ("minecraft:jungle_trapdoor", (96, 0)),
    277: ("minecraft:acacia_trapdoor", (96, 0)),
    278: ("minecraft:dark_oak_trapdoor", (96, 0)),
    279: ("minecraft:turtle_egg", (0, 0)),
    291: ("minecraft:prismarine_stairs", (109, 0)),
    292: ("minecraft:prismarine_brick_stairs", (109, 0)),
    293: ("minecraft:dark_prismarine_stairs", (109, 0)),
    295: ("minecraft:stripped_spruce_log", (17, 1)),
    296: ("minecraft:stripped_birch_log", (17, 2)),
    297: ("minecraft:stripped_jungle_log", (17, 3)),
    298: ("minecraft:stripped_acacia_log", (162, 0)),
    299: ("minecraft:stripped_dark_oak_log", (162, 1)),
    300: ("minecraft:stripped_oak_log", (17, 0)),
    301: ("minecraft:acacia_pressure_plate", (72, 0)),
    302: ("minecraft:birch_pressure_plate", (72, 0)),
    303: ("minecraft:dark_oak_pressure_plate", (72, 0)),
    304: ("minecraft:jungle_pressure_plate", (72, 0)),
    305: ("minecraft:spruce_pressure_plate", (72, 0)),
    306: ("minecraft:acacia_button", (143, 0)),
    307: ("minecraft:birch_button", (143, 0)),
    308: ("minecraft:dark_oak_button", (143, 0)),
    309: ("minecraft:jungle_button", (143, 0)),
    310: ("minecraft:spruce_button", (143, 0)),
    311: ("minecraft:prismarine_slab[type=double]", (168, 0)),
    312: ("minecraft:prismarine_slab", (44, 5)),
    313: ("minecraft:spruce_wood", (17, 13)),
    314: ("minecraft:birch_wood", (17, 14)),
    315: ("minecraft:jungle_wood", (17, 15)),
    316: ("minecraft:acacia_wood", (162, 12)),
    317: ("minecraft:dark_oak_wood", (162, 13)),
    318: ("minecraft:oak_wood", (17, 12)),
}

_CORAL_TYPES = ["tube", "brain", "bubble", "fire", "horn"]
_WOOD_DIRS = {0: "y", 4: "x", 8: "z"}


def lce_modern_state(bid: int, data: int) -> Optional[str]:
    """Best Java 1.13 block state for an LCE Aquatic-era block id + data."""
    entry = LCE_MODERN_BLOCKS.get(bid)
    if entry is None:
        return None
    state = entry[0]
    if bid in (259, 263, 264, 265):  # coral families: type in data&7, dead flag in data&8
        kind = _CORAL_TYPES[(data & 7) % 5]
        dead = "dead_" if data & 8 else ""
        suffix = {259: "_coral_block", 263: "_coral", 264: "_coral_fan", 265: "_coral_fan"}[bid]
        if bid == 265:
            dead = "dead_"
        return f"minecraft:{dead}{kind}{suffix}"
    if bid == 270:
        return {1: "minecraft:tall_seagrass[half=upper]", 2: "minecraft:tall_seagrass[half=lower]"}.get(data, "minecraft:seagrass")
    if bid == 271:
        wl = "true" if data & 8 else "false"
        return f"minecraft:sea_pickle[pickles={(data & 3) + 1},waterlogged={wl}]"
    if bid == 279:
        return f"minecraft:turtle_egg[eggs={(data & 3) + 1},hatch={min(2, data >> 2)}]"
    if 295 <= bid <= 300:
        return f"{state}[axis={_WOOD_DIRS.get(data & 12, 'y')}]"
    if bid == 312:
        return f"minecraft:{['prismarine', 'prismarine_brick', 'dark_prismarine'][min(2, data & 7)]}_slab[type={'top' if data & 8 else 'bottom'}]"
    if 291 <= bid <= 293:
        facing = ["east", "west", "south", "north"][data & 3]
        half = "top" if data & 4 else "bottom"
        return f"{state}[facing={facing},half={half}]"
    if 274 <= bid <= 278:
        facing = ["north", "south", "west", "east"][data & 3]
        half = "top" if data & 8 else "bottom"
        return f"{state}[facing={facing},half={half},open={'true' if data & 4 else 'false'}]"
    if 301 <= bid <= 305:
        return f"{state}[powered={'true' if data & 1 else 'false'}]"
    if 306 <= bid <= 310:
        facing = {0: "down", 1: "east", 2: "west", 3: "south", 4: "north", 5: "up"}.get(data & 7, "north")
        face = "ceiling" if facing == "down" else ("floor" if facing == "up" else "wall")
        if face != "wall":
            facing = "north"
        return f"{state}[face={face},facing={facing},powered={'true' if data & 8 else 'false'}]"
    if bid == 258:
        return f"minecraft:kelp[age={min(25, data)}]" if data else "minecraft:kelp_plant"
    return state


def lce_modern_fallback(bid: int) -> Tuple[int, int]:
    entry = LCE_MODERN_BLOCKS.get(bid)
    return entry[1] if entry else (1, 0)
