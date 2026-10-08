"""Items and mobs that a newer game version added: what a target older than the source world does not have.

An older game silently drops an unknown item / mob (or shows it as an unknown item), so the conversion
removes them and says how many (the warning "Content that does not exist in <version>: removed ..." the
old-game routes already give).  PyMCTranslate has no item or entity lists, only block ones: a block item
exists in a version when its block does; the other items and the mobs come from the tables below (the
release that added them).  A name the tables do not know is kept: a missing entry only costs a
silent drop by the game, a wrong one would destroy valid content.
"""

from __future__ import annotations

import functools
from typing import Dict, Iterable, Optional, Tuple

from .i18n import tr

Version = Tuple[int, ...]


def _since(table: Dict[Version, Iterable[str]]) -> Dict[str, Version]:
    return {name: v for v, names in table.items() for name in names}


_WOODS = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak")

# Java release that added each mob (entity id without the namespace)
JAVA_ENTITY_SINCE = _since({
    (1, 13, 0): ["cod", "dolphin", "drowned", "phantom", "pufferfish", "salmon", "tropical_fish", "turtle", "trident"],
    (1, 14, 0): ["cat", "fox", "panda", "pillager", "ravager", "trader_llama", "wandering_trader"],
    (1, 15, 0): ["bee"],
    (1, 16, 0): ["hoglin", "piglin", "strider", "zoglin"],
    (1, 16, 2): ["piglin_brute"],
    (1, 17, 0): ["axolotl", "glow_squid", "goat", "glow_item_frame", "marker"],
    (1, 19, 0): ["allay", "frog", "tadpole", "warden", "chest_boat"],
    (1, 19, 4): ["item_display", "block_display", "text_display", "interaction"],
    (1, 20, 0): ["camel", "sniffer"],
    (1, 20, 5): ["armadillo"],
    (1, 21, 0): ["breeze", "bogged", "wind_charge", "breeze_wind_charge", "ominous_item_spawner"],
    (1, 21, 4): ["creaking"],
    (1, 21, 6): ["happy_ghast"],
    (1, 21, 9): ["copper_golem"],
})

# the same for Bedrock (release that added the mob; only the ones whose release is certain: the older mobs of
# Java 1.13 / 1.14 were in Bedrock long before its own 1.13 / 1.14)
BEDROCK_ENTITY_SINCE = _since({
    (1, 2, 0): ["parrot"],
    (1, 4, 0): ["cod", "salmon", "pufferfish", "tropicalfish", "dolphin", "drowned", "thrown_trident"],
    (1, 5, 0): ["turtle"],
    (1, 6, 0): ["phantom"],
    (1, 8, 0): ["panda", "cat"],
    (1, 10, 0): ["pillager"],
    (1, 11, 0): ["ravager", "wandering_trader"],
    (1, 13, 0): ["fox"],
    (1, 14, 0): ["bee"],
    (1, 16, 0): ["hoglin", "piglin", "strider", "zoglin"],
    (1, 16, 200): ["piglin_brute"],
    (1, 17, 0): ["axolotl", "glow_squid", "goat"],
    (1, 19, 0): ["allay", "frog", "tadpole", "warden", "chest_boat"],
    (1, 20, 0): ["camel", "sniffer"],
    (1, 20, 80): ["armadillo"],
    (1, 21, 0): ["breeze", "bogged", "wind_charge", "breeze_wind_charge", "ominous_item_spawner"],
    (1, 21, 50): ["creaking"],
    (1, 21, 90): ["happy_ghast"],
    (1, 21, 110): ["copper_golem"],
    (1, 21, 130): ["camel_husk", "nautilus", "parched", "zombie_nautilus"],
    (26, 20, 0): ["sulfur_cube"],                       # 26.x versions are (26, minor, 0), as amulet_bridge.versions lists them
})

# A mob that an older Bedrock holds under another identifier: (version it changed in, the older identifier, the
# definitions the older identifier needs).  Renamed, not dropped: a villager must never get lost for an old target.
BEDROCK_ENTITY_RENAMES = {
    "villager_v2": ((1, 11, 0), "villager", ()),
    "zombie_villager_v2": ((1, 11, 0), "zombie_villager", ()),
    "trader_llama": ((1, 19, 10), "llama", ("+minecraft:llama_wandering_trader",)),
}

_SMITHING = ["netherite_upgrade", "sentry", "dune", "coast", "wild", "ward", "eye", "vex", "tide", "snout", "rib", "spire",
             "silence", "raiser", "host", "wayfinder", "shaper"]
_SHERDS = ["angler", "archer", "arms_up", "blade", "brewer", "burn", "danger", "explorer", "friend", "heart", "heartbreak",
           "howl", "miner", "mourner", "plenty", "prize", "sheaf", "shelter", "skull", "snort"]
_COLORS = ["white", "orange", "magenta", "light_blue", "yellow", "lime", "pink", "gray", "light_gray", "cyan", "purple",
           "blue", "brown", "green", "red", "black"]

# Java release that added each item that is not a block's own item
JAVA_ITEM_SINCE = _since({
    (1, 14, 0): ["crossbow", "sweet_berries", "suspicious_stew", "creeper_banner_pattern", "skull_banner_pattern",
                 "flower_banner_pattern", "mojang_banner_pattern"],
    (1, 15, 0): ["honey_bottle", "honeycomb"],
    (1, 16, 0): ["netherite_ingot", "netherite_scrap", "warped_fungus_on_a_stick", "music_disc_pigstep",
                 "piglin_banner_pattern"] + ["netherite_" + t for t in ("sword", "shovel", "pickaxe", "axe", "hoe", "helmet",
                                                                      "chestplate", "leggings", "boots")],
    (1, 17, 0): ["amethyst_shard", "spyglass", "glow_ink_sac", "raw_iron", "raw_gold", "raw_copper", "copper_ingot",
                 "axolotl_bucket", "powder_snow_bucket", "glow_berries", "glow_item_frame"],
    (1, 18, 0): ["music_disc_otherside"],
    (1, 19, 0): ["disc_fragment_5", "music_disc_5", "recovery_compass", "echo_shard", "goat_horn", "tadpole_bucket",
                 "mangrove_boat"] + [w + "_chest_boat" for w in _WOODS + ("mangrove",)],
    (1, 20, 0): ["brush", "torchflower_seeds", "pitcher_pod", "bamboo_raft", "bamboo_chest_raft", "cherry_boat",
                 "cherry_chest_boat", "music_disc_relic"] + [s + "_pottery_sherd" for s in _SHERDS]
                + [s + ("_smithing_template" if s == "netherite_upgrade" else "_armor_trim_smithing_template")
                   for s in _SMITHING],
    (1, 20, 5): ["armadillo_scute", "wolf_armor"],
    (1, 21, 0): ["mace", "wind_charge", "ominous_bottle", "trial_key", "ominous_trial_key", "breeze_rod",
                 "flow_banner_pattern", "guster_banner_pattern", "flow_pottery_sherd", "guster_pottery_sherd",
                 "scrape_pottery_sherd", "bolt_armor_trim_smithing_template", "flow_armor_trim_smithing_template",
                 "music_disc_creator", "music_disc_creator_music_box", "music_disc_precipice"],
    (1, 21, 4): ["pale_oak_boat", "pale_oak_chest_boat", "resin_clump", "resin_brick"],
    (1, 21, 6): ["music_disc_tears"] + [c + "_harness" for c in _COLORS],
    (1, 21, 9): ["copper_nugget"] + ["copper_" + t for t in ("sword", "shovel", "pickaxe", "axe", "hoe", "helmet", "chestplate",
                                                             "leggings", "boots", "horse_armor")],
})


def _entity_since(table: Dict[str, Version], name: str) -> Optional[Version]:
    return table.get(name.split(":", 1)[-1])


def java_entity_exists(name: str, version: Version) -> bool:
    v = _entity_since(JAVA_ENTITY_SINCE, name)
    return v is None or tuple(version) >= v


def bedrock_entity_rename(name: str, version: Version) -> Optional[Tuple[str, Tuple[str, ...]]]:
    """(older identifier, definitions to add) when Bedrock ``version`` holds the mob ``name`` under another one."""
    r = BEDROCK_ENTITY_RENAMES.get(name.split(":", 1)[-1])
    if r is not None and tuple(version) < r[0]:
        return r[1], r[2]
    return None


def downgrade_actor(e, version: Version) -> Optional[str]:
    """Rewrites the identifier (and the definitions) of the Bedrock actor ``e`` for ``version`` in place.  Returns
    "renamed", "removed" (``version`` lacks the mob: the caller drops it) or None (unchanged)."""
    from . import nbt

    ident = str(nbt.get(e, "identifier", "") or "")
    if not ident:
        return None
    r = bedrock_entity_rename(ident, version)
    if r is not None:
        old = ident.split(":", 1)[-1]
        e["identifier"] = nbt.StringTag("minecraft:" + r[0])
        defs = []
        for d in nbt.get_tag(e, "definitions") or []:
            s = str(d.py_data) if hasattr(d, "py_data") else str(d)
            defs.append(s.replace(old, r[0]) if old.endswith("_v2") else s)
        for d in (f"+minecraft:{r[0]}",) + tuple(r[1]):
            if d not in defs:
                defs.append(d)
        e["definitions"] = nbt.ListTag([nbt.StringTag(d) for d in defs], 8)
        return "renamed"
    return None if bedrock_entity_exists(ident, version) else "removed"


def bedrock_entity_exists(name: str, version: Version) -> bool:
    v = _entity_since(BEDROCK_ENTITY_SINCE, name)
    return v is None or tuple(version) >= v


@functools.lru_cache(maxsize=None)
def _java_blocks(version: Version) -> frozenset:
    """The block names (no namespace) of a Java version; empty when PyMCTranslate does not know it."""
    from . import amulet_bridge as ab

    try:
        tr_ = ab.translation_manager().get_version("java", tuple(version)).block
        return frozenset(n for ns in tr_.namespaces() for n in tr_.base_names(ns))
    except Exception:  # noqa: BLE001
        return frozenset()


@functools.lru_cache(maxsize=1)
def _latest_java_blocks() -> frozenset:
    from . import amulet_bridge as ab

    return _java_blocks(ab.latest("java"))


def java_item_exists(name: str, version: Version) -> bool:
    """Whether Java ``version`` has the item ``name`` (a flat 1.13+ name, with or without ``minecraft:``)."""
    n = name.split(":", 1)[-1]
    version = tuple(version)
    since = JAVA_ITEM_SINCE.get(n)
    if since is None and n.endswith("_spawn_egg"):
        since = _entity_since(JAVA_ENTITY_SINCE, n[:-10])
    if since is not None:
        return version >= since
    if n in _latest_java_blocks():                        # a block item exists with its block
        blocks = _java_blocks(version)
        return not blocks or n in blocks
    return True


def java_version_label(version: Version) -> str:
    return "Java " + ".".join(str(i) for i in version)


# ------------------------------------------------------------------ removing it from canonical block entities / mobs
class Tally:
    """What was removed from one conversion (the items, mobs and block entities the target does not have)."""

    def __init__(self):
        self.items = 0
        self.entities = 0
        self.tiles = 0
        self.renamed = 0                  # mobs the older game holds under another identifier (villager_v2...)

    def __bool__(self) -> bool:
        return bool(self.items or self.entities or self.tiles or self.renamed)

    def warn(self, progress, label: str) -> None:
        if self.items or self.entities or self.tiles:
            progress.warn(tr("Content that does not exist in {version}: removed {items} items, {entities} "
                             "entities and {tiles} block entities.", version=label, items=self.items,
                             entities=self.entities, tiles=self.tiles))
        if self.renamed:
            progress.warn(tr("{n} entities were renamed to the identifiers of {version} (villagers, trader llamas).",
                             n=self.renamed, version=label))


def tally_of(progress) -> Tally:
    """The conversion's Tally (kept on its Progress so every writer adds to the same one)."""
    t = getattr(progress, "removed_content", None)
    if t is None:
        t = Tally()
        try:
            progress.removed_content = t
        except AttributeError:
            pass
    return t


def _strip(obj, exists, key: str = "") -> int:
    """Removes the item stacks ``exists`` refuses from a canonical dict / list; returns how many.  Stacks in a
    list that has positions (the equipment of a mob) become None, the others leave the list."""
    from .items import Item

    n = 0
    if isinstance(obj, dict) and not isinstance(obj, Item):
        for k in list(obj):
            v = obj[k]
            if isinstance(v, Item):
                if not exists(str(v.get("name", ""))):
                    obj[k] = None
                    n += 1
            elif isinstance(v, (dict, list, tuple)):
                n += _strip(v, exists, k)
    elif isinstance(obj, list):
        keep = []
        for v in obj:
            if isinstance(v, Item):
                if exists(str(v.get("name", ""))):
                    keep.append(v)
                else:
                    n += 1
                    if key in ("hand", "armor"):
                        keep.append(None)
            else:
                if isinstance(v, (dict, list)):
                    n += _strip(v, exists, key)
                keep.append(v)
        obj[:] = keep
    return n


def clean_tile(c: dict, exists_item, tally: Tally) -> None:
    tally.items += _strip(c, exists_item)


def clean_entities(el: list, exists_entity, exists_item, tally: Tally) -> list:
    """``el`` without the mobs the target lacks, and the items they hold; an item entity of a missing item goes."""
    out = []
    for c in el:
        if not isinstance(c, dict):
            out.append(c)
            continue
        name = str(c.get("name", ""))
        if name and not exists_entity(name):
            tally.entities += 1
            continue
        tally.items += _strip(c, exists_item)
        if name == "item" and not c.get("item"):
            tally.entities += 1
            continue
        out.append(c)
    return out


def clean_player(p, version: Version, tally: Optional[Tally] = None) -> int:
    """A Java 1.13+ player (NBT): the stacks of its inventory and ender chest that Java ``version`` lacks removed."""
    from . import nbt

    def exists(name: str) -> bool:
        return java_item_exists(name, version)

    n = 0
    for key in ("Inventory", "EnderItems"):
        lst = nbt.get_tag(p, key)
        if lst is None:
            continue
        keep = [it for it in lst if not isinstance(it, nbt.CompoundTag) or not nbt.get(it, "id") or exists(str(nbt.get(it, "id")))]
        if len(keep) != len(lst):
            n += len(lst) - len(keep)
            p[key] = nbt.compound_list(keep)
    if tally is not None:
        tally.items += n
    return n


def clean_extras(tl: list, el: list, version: Version, tally: Tally):
    """The canonical block entities and mobs of a chunk without what Java ``version`` lacks."""
    def item_ok(name: str) -> bool:
        return java_item_exists(name, version)

    for c in tl:
        if isinstance(c, dict):
            clean_tile(c, item_ok, tally)
    el = clean_entities(el, lambda n: java_entity_exists(n, version), item_ok, tally)
    return tl, el
