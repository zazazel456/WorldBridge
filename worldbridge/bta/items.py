"""BTA item stacks ({id: short, Count, Damage, Expanded, Version, Data}) -> 1.17.1 item stacks
({id: "minecraft:x", Count: byte, tag: {...}}), which the vanilla DataFixer upgrades to 26.3.

Items that do not fit into one vanilla stack (a quiver full of arrows) produce extra stacks that
the caller must place somewhere (``overflow``): nothing is dropped silently.
"""

from __future__ import annotations

import functools
import os
from typing import Dict, List, NamedTuple, Optional, Tuple

from .. import nbt
from . import blockmap, legacyids, stats, text
from .nbtio import gc, gi, gs
from .palette import Palette


@functools.lru_cache(maxsize=None)
def items_26() -> frozenset:
    with open(os.path.join(os.path.dirname(__file__), "data", "items-26.3.txt"), encoding="utf-8") as f:
        return frozenset(line.strip() for line in f if line.strip())


def _v2730(iid: str) -> str:
    """Items renamed after 1.17.1: write the 1.17 name, the DataFixer renames it."""
    return {"minecraft:short_grass": "minecraft:grass", "minecraft:iron_chain": "minecraft:chain",
            "minecraft:turtle_scute": "minecraft:scute"}.get(iid, iid)


class _Def(NamedTuple):
    id: str
    bta_max: int
    vanilla_max: int


ITEMS: Dict[int, _Def] = {}


def _item(i: int, vanilla: str, bta_max: int = 0, vanilla_max: int = 0) -> None:
    if ":" not in vanilla:
        vanilla = "minecraft:" + vanilla
    if i in ITEMS:
        raise ValueError(f"duplicate item {i}")
    ITEMS[i] = _Def(vanilla, bta_max, vanilla_max)


def _table() -> None:
    I = _item  # noqa: E741
    I(16384, "iron_shovel", 384, 250); I(16385, "iron_pickaxe", 384, 250); I(16386, "iron_axe", 384, 250)
    I(16387, "flint_and_steel", 192, 64); I(16388, "apple"); I(16389, "bow", 384, 384); I(16390, "arrow")
    I(16391, "coal"); I(16392, "diamond"); I(16393, "iron_ingot"); I(16394, "gold_ingot")
    I(16395, "iron_sword", 384, 250); I(16396, "wooden_sword", 64, 59); I(16397, "wooden_shovel", 64, 59)
    I(16398, "wooden_pickaxe", 64, 59); I(16399, "wooden_axe", 64, 59); I(16400, "stone_sword", 128, 131)
    I(16401, "stone_shovel", 128, 131); I(16402, "stone_pickaxe", 128, 131); I(16403, "stone_axe", 128, 131)
    I(16404, "diamond_sword", 1536, 1561); I(16405, "diamond_shovel", 1536, 1561)
    I(16406, "diamond_pickaxe", 1536, 1561); I(16407, "diamond_axe", 1536, 1561); I(16408, "stick")
    I(16409, "bowl"); I(16410, "mushroom_stew"); I(16411, "golden_sword", 384, 32)
    I(16412, "golden_shovel", 384, 32); I(16413, "golden_pickaxe", 384, 32); I(16414, "golden_axe", 384, 32)
    I(16415, "string"); I(16416, "feather"); I(16417, "gunpowder"); I(16418, "wooden_hoe", 64, 59)
    I(16419, "stone_hoe", 128, 131); I(16420, "iron_hoe", 384, 250); I(16421, "diamond_hoe", 1536, 1561)
    I(16422, "golden_hoe", 384, 32); I(16423, "wheat_seeds"); I(16424, "wheat"); I(16425, "bread")
    I(16426, "leather_helmet", 163, 55); I(16427, "leather_chestplate", 180, 80)
    I(16428, "leather_leggings", 174, 75); I(16429, "leather_boots", 169, 65)
    I(16430, "chainmail_helmet", 218, 165); I(16431, "chainmail_chestplate", 240, 240)
    I(16432, "chainmail_leggings", 232, 225); I(16433, "chainmail_boots", 225, 195)
    I(16434, "iron_helmet", 182, 165); I(16435, "iron_chestplate", 200, 240); I(16436, "iron_leggings", 194, 225)
    I(16437, "iron_boots", 188, 195); I(16438, "diamond_helmet", 728, 363); I(16439, "diamond_chestplate", 800, 528)
    I(16440, "diamond_leggings", 776, 495); I(16441, "diamond_boots", 752, 429)
    I(16442, "golden_helmet", 109, 77); I(16443, "golden_chestplate", 120, 112)
    I(16444, "golden_leggings", 116, 105); I(16445, "golden_boots", 112, 91); I(16446, "flint")
    I(16447, "porkchop"); I(16448, "cooked_porkchop"); I(16449, "painting"); I(16450, "golden_apple")
    I(16451, "oak_sign"); I(16452, "oak_door"); I(16456, "minecart"); I(16457, "saddle"); I(16458, "iron_door")
    I(16459, "redstone"); I(16460, "snowball"); I(16461, "oak_boat"); I(16462, "leather"); I(16464, "brick")
    I(16465, "clay_ball"); I(16466, "sugar_cane"); I(16467, "paper"); I(16468, "book"); I(16469, "slime_ball")
    I(16470, "chest_minecart"); I(16471, "furnace_minecart"); I(16472, "egg"); I(16473, "compass")
    I(16474, "fishing_rod", 196, 64); I(16475, "clock"); I(16476, "glowstone_dust"); I(16477, "cod")
    I(16478, "cooked_cod"); I(16479, "white_dye"); I(16480, "bone"); I(16481, "sugar"); I(16482, "cake")
    I(16483, "red_bed"); I(16484, "repeater"); I(16485, "cookie"); I(16486, "map"); I(16487, "shears", 384, 238)
    I(16488, "coal"); I(16489, "netherite_helmet", 1092, 407); I(16490, "netherite_chestplate", 1200, 592)
    I(16491, "netherite_leggings", 1164, 555); I(16492, "netherite_boots", 1128, 481)
    I(16493, "netherite_sword", 4608, 2031); I(16494, "netherite_shovel", 4608, 2031)
    I(16495, "netherite_pickaxe", 4608, 2031); I(16496, "netherite_axe", 4608, 2031)
    I(16497, "netherite_hoe", 4608, 2031); I(16498, "netherite_ingot"); I(16499, "netherite_scrap")
    I(16500, "fire_charge"); I(16501, "spectral_arrow"); I(16502, "crossbow", 100, 465); I(16503, "iron_nugget")
    I(16504, "string"); I(16505, "fire_charge"); I(16506, "crossbow", 100, 465); I(16507, "spectral_arrow")
    I(16508, "bundle"); I(16509, "clock"); I(16510, "raw_gold"); I(16511, "raw_iron"); I(16512, "quartz")
    I(16513, "emerald"); I(16514, "stone_button"); I(16515, "sweet_berries"); I(16517, "arrow")
    I(16518, "name_tag"); I(16519, "glass_bottle"); I(16520, "copper_lantern"); I(16521, "soul_lantern")
    I(16522, "lantern"); I(16523, "lantern"); I(16524, "repeater"); I(16525, "barrel"); I(16526, "white_banner")
    I(16527, "leather_boots"); I(16528, "shears", 4608, 238); I(16529, "flint_and_steel", 4608, 64)
    I(16530, "pumpkin_seeds"); I(16531, "oak_slab"); I(16532, "oak_door"); I(16533, "waxed_copper_door")
    I(16534, "lead"); I(16535, "pumpkin_pie"); I(16536, "stick"); I(16537, "iron_door"); I(16538, "brush", 64, 64)
    for i in range(16539, 16543):
        I(i, "flower_pot")
    for i in range(16543, 16549):
        I(i, "armor_stand")
    I(16549, "oak_sign"); I(16550, "mutton"); I(16551, "cooked_mutton"); I(16552, "wheat"); I(16553, "debug_stick")
    I(16555, "amethyst_shard")
    for i, m in zip(range(16556, 16562), (180, 240, 200, 800, 120, 1200)):
        I(i, "wolf_armor", m, 64)
    I(16562, "bucket"); I(16563, "bucket"); I(16567, "sulfur"); I(16568, "arrow")
    for i in range(16571, 16575):
        I(i, "armor_stand")
    for i, disc in enumerate(("13", "cat", "blocks", "chirp", "far", "mall", "mellohi", "stal", "strad", "ward",
                              "wait", "11")):
        I(18384 + i, "music_disc_" + disc)


_table()


class BtaStack(NamedTuple):
    id: int
    count: int
    meta: int
    data: dict


def normalise(it: dict) -> BtaStack:
    """The stack after BTA's own lazy upgrades (Expanded ids, pre-19133 block ids, old buckets)."""
    iid = gi(it, "id") & 0xFFFF
    count = gi(it, "Count")
    meta = gi(it, "Damage") & 0xFFFF
    expanded = gi(it, "Expanded")
    version = gi(it, "Version", 0)
    if expanded == 0 and iid >= 256:
        iid += 16384 - 256
    if version < 19133 and iid < 16384:
        iid, meta = legacyids.convert(iid, meta)
    data = dict(gc(it, "Data") or {})
    if version < 19135:
        st = {16453: "minecraft:empty", 16454: "minecraft:water", 16455: "minecraft:lava", 16463: "minecraft:milk",
              16516: "minecraft:icecream"}.get(iid)
        if st is not None:
            iid = 16562
            if st != "minecraft:empty":
                data["State"] = st
                data["Charges"] = 1
    if iid == 680:
        iid = 682
    if iid == 681:
        iid = 683
    return BtaStack(iid, count, meta, data)


def simple_stack(iid: str, count: int) -> nbt.CompoundTag:
    return nbt.CompoundTag({"id": nbt.StringTag(_v2730(iid)), "Count": nbt.ByteTag(_byte(count))})


def _byte(v: int) -> int:
    v &= 0xFF
    return v - 256 if v >= 128 else v


def convert(it: Optional[dict], palette: Palette, overflow: List[nbt.CompoundTag]) -> Optional[nbt.CompoundTag]:
    """1.17 item stack (without Slot) or None for an empty / unknown stack."""
    if it is None:
        return None
    s = normalise(it)
    if s.count <= 0 or s.id == 0:
        return None
    return convert_stack(s, palette, overflow)


def convert_stack(s: BtaStack, palette: Palette, overflow: List[nbt.CompoundTag]) -> Optional[nbt.CompoundTag]:
    damage = 0
    tag = nbt.CompoundTag()
    count = min(s.count, 99)
    if s.id < 16384:
        iid = block_item(s.id, s.meta, palette)
        if iid is None:
            stats.inc(f"item.unknown.{s.id}")
            return None
    else:
        d = ITEMS.get(s.id)
        if d is None:
            stats.inc(f"item.unknown.{s.id}")
            return None
        iid = d.id
        if s.id == 16391:
            iid = "minecraft:charcoal" if s.meta == 1 else "minecraft:coal"
        elif s.id == 16479:
            iid = _dye(s.meta)
        elif s.id == 16532:
            iid = "minecraft:" + palette.wood(15 - (s.meta & 15)) + "_door"
        elif s.id == 16549:
            iid = "minecraft:" + palette.wood(15 - (s.meta & 15)) + "_sign"
        elif s.id in (16562, 16563):
            iid = _bucket(gs(s.data, "State", ""))
        elif s.id == 16508:
            # quiver: metadata counts used arrow slots out of 192; arrows go into a bundle, the rest overflows
            arrows = max(0, 192 - s.meta)
            in_bundle = min(64, arrows)
            items = nbt.ListTag([], 10)
            if in_bundle > 0:
                items.append(simple_stack("minecraft:arrow", in_bundle))
            tag["Items"] = items
            left = arrows - in_bundle
            while left > 0:
                overflow.append(simple_stack("minecraft:arrow", min(64, left)))
                left -= 64
        elif s.id == 16501:
            count = 64
        if d.vanilla_max > 0 and d.bta_max > 0 and s.meta > 0 and s.id != 16508:
            damage = _java_round(s.meta * d.vanilla_max / d.bta_max)
            damage = max(0, min(d.vanilla_max - 1, damage))
    if damage > 0:
        tag["Damage"] = nbt.IntTag(damage)
    _apply_display(s.data, tag, iid)
    out = nbt.CompoundTag({"id": nbt.StringTag(_v2730(iid)), "Count": nbt.ByteTag(_byte(count))})
    if len(tag):
        out["tag"] = tag
    return out


def _java_round(v: float) -> int:
    import math

    return int(math.floor(v + 0.5))


def armor_slot_for(item: nbt.CompoundTag, fallback: int) -> int:
    """Vanilla armour slot (0 feet, 1 legs, 2 chest, 3 head) decided by the item type."""
    iid = str(nbt.get(item, "id", ""))
    if iid.endswith("_boots"):
        return 0
    if iid.endswith("_leggings"):
        return 1
    if iid.endswith("_chestplate") or iid == "minecraft:elytra":
        return 2
    if iid.endswith("_helmet") or iid.endswith("carved_pumpkin") or iid.endswith("_skull") or iid.endswith("_head"):
        return 3
    return fallback


_DYES = ("ink_sac", "red_dye", "green_dye", "cocoa_beans", "lapis_lazuli", "purple_dye", "cyan_dye", "light_gray_dye",
         "gray_dye", "pink_dye", "lime_dye", "yellow_dye", "light_blue_dye", "magenta_dye", "orange_dye", "bone_meal")


def _dye(meta: int) -> str:
    return "minecraft:" + _DYES[meta & 15]


def _bucket(st: str) -> str:
    if st in ("minecraft:water", "minecraft:acid"):
        return "minecraft:water_bucket"
    if st == "minecraft:lava":
        return "minecraft:lava_bucket"
    if st in ("minecraft:milk", "minecraft:icecream"):
        return "minecraft:milk_bucket"
    return "minecraft:bucket"


def _apply_display(data: dict, tag: nbt.CompoundTag, iid: str) -> None:
    """Custom names (labels) and colours become the 1.17 display tag."""
    from .nbtio import gb

    if not data:
        return
    if gb(data, "overrideName") and gs(data, "name"):
        disp = tag.get("display") if "display" in tag else nbt.CompoundTag()
        disp["Name"] = nbt.StringTag(text.json_text(text.strip_formatting(gs(data, "name")), None))
        tag["display"] = disp
    if gb(data, "overrideColor") and "color" in data and iid.startswith("minecraft:leather_"):
        disp = tag.get("display") if "display" in tag else nbt.CompoundTag()
        disp["color"] = nbt.IntTag(text.DYE_RGB[gi(data, "color") & 15])
        tag["display"] = disp


_SPECIAL_BLOCK_ITEMS: Dict[int, str] = {
    111: "minecraft:lead", 523: "minecraft:piston", 522: "minecraft:piston", 525: "minecraft:piston",
    610: "minecraft:red_bed", 630: "minecraft:flint_and_steel", 633: "minecraft:flint_and_steel",
    634: "minecraft:flint_and_steel", 690: "minecraft:wheat_seeds", 691: "minecraft:pumpkin_seeds",
    874: "minecraft:flower_pot", 270: "minecraft:water_bucket", 271: "minecraft:water_bucket",
    272: "minecraft:lava_bucket", 273: "minecraft:lava_bucket", 1062: "minecraft:water_bucket",
    1063: "minecraft:water_bucket",
    **{i: "minecraft:armor_stand" for i in list(range(1010, 1022)) + list(range(1075, 1083))},
}
_BLOCK_TO_ITEM = {"minecraft:wall_torch": "minecraft:torch", "minecraft:redstone_wall_torch": "minecraft:redstone_torch",
                  "minecraft:redstone_wire": "minecraft:redstone", "minecraft:cave_vines_plant": "minecraft:lead",
                  "minecraft:cave_vines": "minecraft:lead", "minecraft:soul_fire": "minecraft:flint_and_steel",
                  "minecraft:fire": "minecraft:flint_and_steel", "minecraft:pumpkin_stem": "minecraft:pumpkin_seeds",
                  "minecraft:wheat": "minecraft:wheat_seeds"}


def block_item(block_id: int, meta: int, palette: Palette) -> Optional[str]:
    """Item id for a BTA block item, derived from the block mapping (items always match blocks)."""
    if not blockmap.known(block_id):
        return None
    if block_id in (830, 831):
        return None
    if block_id in (590, 591):
        return "minecraft:" + palette.oak_wood + "_door"
    if block_id in (594, 595):
        return "minecraft:" + palette.wood(meta >> 4) + "_door"
    if block_id in (710, 711):
        return "minecraft:" + palette.oak_wood + "_sign"
    if block_id in (713, 714):
        return "minecraft:" + palette.wood(meta >> 4) + "_sign"
    special = _SPECIAL_BLOCK_ITEMS.get(block_id)
    if special:
        return special
    st = blockmap.map_block(block_id, meta, blockmap.MapCtx(palette))
    if st is None or st.is_air:
        return None
    n = _BLOCK_TO_ITEM.get(st.name, st.name)
    if n.endswith("_wall_sign"):
        n = n.replace("_wall_sign", "_sign")
    if n.startswith("minecraft:potted_"):
        n = "minecraft:flower_pot"
    if n not in items_26():
        stats.inc(f"item.unknown.{block_id}")
        return None
    return n


def convert_inventory(bta_items: Optional[list], slot_count: int, palette: Palette,
                      spill: List[nbt.CompoundTag]) -> nbt.ListTag:
    """A BTA "Items" list (with Slot bytes) -> 1.17 list; overflow stacks go to free slots, then to ``spill``."""
    out = nbt.ListTag([], 10)
    if not bta_items:
        return out
    used = [False] * max(slot_count, 1)
    overflow: List[nbt.CompoundTag] = []
    converted: List[Tuple[int, nbt.CompoundTag]] = []
    for c in bta_items:
        if not isinstance(c, dict):
            continue
        slot = gi(c, "Slot") & 0xFF
        item = convert(c, palette, overflow)
        if item is None:
            continue
        if slot >= slot_count or used[slot]:
            overflow.append(item)
            continue
        used[slot] = True
        item["Slot"] = nbt.ByteTag(_byte(slot))
        converted.append((slot, item))
    free = 0
    for extra in overflow:
        while free < slot_count and used[free]:
            free += 1
        if free < slot_count:
            used[free] = True
            extra["Slot"] = nbt.ByteTag(_byte(free))
            converted.append((free, extra))
        else:
            spill.append(extra)
    converted.sort(key=lambda t: t[0])
    for _s, c in converted:
        out.append(c)
    return out
