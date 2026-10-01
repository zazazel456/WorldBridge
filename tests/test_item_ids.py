"""Items handed to Minecraft's data fixers must reach the latest version as the same items.

* The game's numeric id fix (ItemIdFix, data version 102) only knows the ids of Java 1.7: a
  player or a chest written with numeric ids lost every cooked mutton (424), banner, shield,
  elytra, slime block... on the way to the latest Java version (they became air).
* Items newer than Java 1.12 have no numeric id at all: a Bedrock player lost every netherite
  tool, trident, copper block... on the way to Java.
* Minecraft upgrades the player inside level.dat from the level's DataVersion: from 1.12.2 its
  1.13 - 1.14 renames turn modern names into other items (melon -> melon_slice,
  stone_slab -> smooth_stone_slab, purple_shulker_box -> shulker_box)."""

import os

from worldbridge import amulet_bridge as ab
from worldbridge import items, nbt
from worldbridge.bedrock.extra import (BEDROCK_PLAYER_DV, bedrock_player_to_java, bedrock_player_to_legacy,
                                       legacy_player_to_bedrock)
from worldbridge.java.numeric import JavaWriteOptions, _legacy_entities, _legacy_tiles, java_player_nbt
from worldbridge.lce.world import legacy_items
from worldbridge.model import WorldInfo

# numeric ids missing from the game's ItemIdFix
UNKNOWN_TO_THE_GAME = {165: "slime", 168: "prismarine", 179: "red_sandstone", 251: "concrete", 409: "prismarine_shard",
                       423: "mutton", 424: "cooked_mutton", 425: "banner", 427: "spruce_door", 442: "shield",
                       443: "elytra", 449: "totem_of_undying"}
# Bedrock item -> the Java 1.15.2 name it is written with
BEDROCK_ITEMS = {"cooked_mutton": "cooked_mutton", "netherite_sword": "netherite_sword", "trident": "trident",
                 "crossbow": "crossbow", "copper_ingot": "copper_ingot", "spyglass": "spyglass", "mace": "mace",
                 "honey_bottle": "honey_bottle", "melon_slice": "melon_slice"}
# Bedrock 1.21.60 block items (with their Block compound, as the game saves them)
BEDROCK_BLOCKS = {"normal_stone_slab": ({"minecraft:vertical_half": "bottom"}, "stone_slab"),
                  "smooth_stone_slab": ({"minecraft:vertical_half": "bottom"}, "smooth_stone_slab"),
                  "melon_block": ({}, "melon"), "purple_shulker_box": ({}, "purple_shulker_box"),
                  "cherry_log": ({"pillar_axis": "y"}, "cherry_log"), "short_grass": ({}, "grass"),
                  "weathered_cut_copper": ({}, "semi_weathered_cut_copper")}  # renamed by the 1.17 fix
EXPECTED = list(BEDROCK_ITEMS.values()) + [v for _s, v in BEDROCK_BLOCKS.values()]


def _bedrock_item(name, count=1, slot=0, damage=0, states=None):
    t = nbt.CompoundTag({"Name": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(count),
                         "Damage": nbt.ShortTag(damage)})
    if states is not None:
        t["Block"] = nbt.CompoundTag({"name": nbt.StringTag("minecraft:" + name), "version": nbt.IntTag(18168865),
                                      "states": nbt.CompoundTag({k: nbt.StringTag(v) for k, v in states.items()})})
    if slot is not None:
        t["Slot"] = nbt.ByteTag(slot)
    return t


def _bedrock_player():
    inv = [_bedrock_item(n, 2, i) for i, n in enumerate(BEDROCK_ITEMS)]
    inv += [_bedrock_item(n, 2, len(inv) + i, states=st) for i, (n, (st, _j)) in enumerate(BEDROCK_BLOCKS.items())]
    return nbt.CompoundTag({
        "Pos": nbt.ListTag([nbt.FloatTag(0.5), nbt.FloatTag(65.62), nbt.FloatTag(0.5)], 5),
        "UniqueID": nbt.LongTag(-5),
        "Inventory": nbt.ListTag(inv, 10),
        "Armor": nbt.ListTag([_bedrock_item("netherite_helmet", slot=None)] + [nbt.CompoundTag()] * 3, 10),
        "Offhand": nbt.ListTag([_bedrock_item("shield", slot=None)], 10),
        "EnderChestInventory": nbt.ListTag([_bedrock_item("elytra", 1, 0)], 10),
    })


def _slot(name):
    return EXPECTED.index(name)


def _stacks(lst):
    return {int(t["Slot"].py_data): t["id"].py_data.split(":", 1)[1] for t in lst}


def _level(path):
    return nbt.load(open(os.path.join(path, "level.dat"), "rb").read()).tag["Data"]


def _info(player, level=None):
    info = WorldInfo()
    info.level = level if level is not None else nbt.CompoundTag(
        {"LevelName": nbt.StringTag("t"), "RandomSeed": nbt.LongTag(5), "generatorName": nbt.StringTag("default")})
    info.players = {"host": player}
    return info


def test_bedrock_player_becomes_a_java_player_with_every_item():
    p = bedrock_player_to_java(_bedrock_player())
    assert int(p["DataVersion"].py_data) == BEDROCK_PLAYER_DV
    got = _stacks(p["Inventory"])
    assert [got[i] for i in range(len(EXPECTED))] == EXPECTED
    assert got[103] == "netherite_helmet" and got[-106] == "shield"
    assert _stacks(p["EnderItems"]) == {0: "elytra"}


def test_bedrock_world_to_latest_java_keeps_the_player_as_it_is(tmp_path):
    p = bedrock_player_to_java(_bedrock_player())
    ab.write_java_level_dat(str(tmp_path), _info(p), ab.latest("java"))
    data = _level(str(tmp_path))
    # level and player upgraded from 1.15.2: past the 1.13 - 1.14 renames, before WorldGenSettings
    assert int(data["DataVersion"].py_data) == BEDROCK_PLAYER_DV
    assert int(data["Player"]["DataVersion"].py_data) == BEDROCK_PLAYER_DV
    assert _stacks(data["Player"]["Inventory"]) == _stacks(p["Inventory"])
    assert int(data["RandomSeed"].py_data) == 5


def test_flat_bedrock_world_gets_the_113_flat_settings(tmp_path):
    info = _info(bedrock_player_to_java(_bedrock_player()))
    info.level["generatorName"] = nbt.StringTag("flat")
    ab.write_java_level_dat(str(tmp_path), info, ab.latest("java"))
    opts = _level(str(tmp_path))["generatorOptions"]
    assert [str(l["block"].py_data) for l in opts["layers"]] == ["minecraft:bedrock", "minecraft:dirt", "minecraft:grass_block"]


def test_bedrock_player_to_java_113_is_written_in_the_numeric_layout(tmp_path):
    p = bedrock_player_to_java(_bedrock_player())
    ab.write_java_level_dat(str(tmp_path), _info(p), (1, 13, 2))
    data = _level(str(tmp_path))
    assert int(data["DataVersion"].py_data) == ab.LEGACY_LEVEL_DV and "DataVersion" not in data["Player"]
    got = _stacks(data["Player"]["Inventory"])
    # 1.12 names: the plain stone slab (1.14) has none, the nearest is the stone slab of 1.12
    assert got[_slot("cooked_mutton")] == "cooked_mutton" and got[_slot("melon")] == "melon_block"
    assert got[_slot("stone_slab")] == got[_slot("smooth_stone_slab")] == "stone_slab"
    assert "netherite_sword" not in got.values()  # no such item before 1.16


def test_java_source_keeps_its_own_level(tmp_path):
    item = nbt.CompoundTag({"id": nbt.StringTag("minecraft:melon"), "count": nbt.IntTag(3), "Slot": nbt.ByteTag(0)})
    player = nbt.CompoundTag({"DataVersion": nbt.IntTag(4189), "Inventory": nbt.ListTag([item], 10)})
    level = nbt.CompoundTag({"DataVersion": nbt.IntTag(4189), "LevelName": nbt.StringTag("j"),
                             "WorldGenSettings": nbt.CompoundTag({"seed": nbt.LongTag(9)}), "Player": player})
    ab.write_java_level_dat(str(tmp_path), _info(player, level), ab.latest("java"))
    data = _level(str(tmp_path))
    assert int(data["DataVersion"].py_data) == 4189  # the game upgrades level and player from 1.21.3
    assert data["Player"]["Inventory"][0]["id"].py_data == "minecraft:melon"
    assert int(data["WorldGenSettings"]["seed"].py_data) == 9


def test_java_1219_spawn_compound_is_rebuilt(tmp_path):
    level = nbt.CompoundTag({"DataVersion": nbt.IntTag(4556), "SpawnX": nbt.IntTag(10), "SpawnY": nbt.IntTag(70),
                             "SpawnZ": nbt.IntTag(-3)})  # a 1.21.9 level whose spawn the selection moved
    info = _info(nbt.CompoundTag({"DataVersion": nbt.IntTag(4556)}), level)
    info.split_world_gen = True
    info.level["WorldGenSettings"] = nbt.CompoundTag()
    ab.write_java_level_dat(str(tmp_path), info, ab.latest("java"))
    data = _level(str(tmp_path))
    assert list(data["spawn"]["pos"]) == [10, 70, -3] and "SpawnX" not in data
    assert "WorldGenSettings" not in data  # 26.1+: in its own file


def test_names_follow_the_games_renames():
    assert items.java_item_name("grass", 3465) == "grass" and items.java_item_name("grass", 4189) == "short_grass"
    assert items.java_item_name("short_grass", 2230) == "grass"
    assert items.java_item_name("chain", 4189) == "chain" and items.java_item_name("chain", 5020) == "iron_chain"
    assert items.java_item_name("weathered_cut_copper", 2230) == "semi_weathered_cut_copper"
    assert items.java_item_name("weathered_cut_copper", 3465) == "weathered_cut_copper"
    assert items.java_item_name("dirt_path", 2230) == "grass_path"


def test_modern_player_to_legacy_targets_reads_modern_names():
    p = bedrock_player_to_java(_bedrock_player())
    leg = {int(t["Slot"].py_data): (int(t["id"].py_data), int(t["Damage"].py_data))
           for t in legacy_items(p["Inventory"], modern=True)}
    assert leg[_slot("melon")] == (103, 0) and leg[_slot("melon_slice")] == (360, 0)
    assert leg[_slot("smooth_stone_slab")] == (44, 0) and leg[_slot("cooked_mutton")] == (424, 0)
    assert leg[_slot("grass")] == (31, 1)  # short grass, not the grass block
    be = legacy_player_to_bedrock(p, (1, 21, 50), 1)
    names = [str(t["Name"].py_data) for t in be["Inventory"] if str(t["Name"].py_data)]
    assert "minecraft:netherite_sword" in names and "minecraft:cooked_mutton" in names


def test_legacy_player_to_19_plus_names_numeric_ids():
    p = java_player_nbt(bedrock_player_to_legacy(_bedrock_player()), JavaWriteOptions(kind="anvil"))
    assert all(isinstance(t["id"], nbt.StringTag) for t in p["Inventory"])
    assert _stacks(p["Inventory"])[0] == "cooked_mutton"
    p = java_player_nbt(bedrock_player_to_legacy(_bedrock_player()), JavaWriteOptions(kind="mcregion"))
    assert all(isinstance(t["id"], nbt.ShortTag) for t in p["Inventory"])


def test_numeric_names_match_the_games_table_and_read_back():
    for iid, name in UNKNOWN_TO_THE_GAME.items():
        num = nbt.CompoundTag({"id": nbt.ShortTag(iid), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
        named = items.named_item(num)
        assert named["id"].py_data == "minecraft:" + name
        assert items.from_legacy(named)["name"] == items.from_legacy(num)["name"]
    stone = nbt.CompoundTag({"id": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1)})
    assert items.named_item(stone) is stone
    assert items.legacy_to_flat(44, 0) == "smooth_stone_slab"  # 1.13's stone_slab, renamed in 1.14


def test_hub_chests_and_entities_are_named():
    chest = nbt.CompoundTag({"id": nbt.StringTag("Chest"), "x": nbt.IntTag(0), "y": nbt.IntTag(64), "z": nbt.IntTag(0),
                             "Items": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(424), "Count": nbt.ByteTag(9),
                                                                    "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(0)})], 10)})
    (t,) = _legacy_tiles([chest], named=True)
    assert t["Items"][0]["id"].py_data == "minecraft:cooked_mutton"
    (t,) = _legacy_tiles([chest])
    assert int(t["Items"][0]["id"].py_data) == 424
    drop = nbt.CompoundTag({"id": nbt.StringTag("Item"), "Pos": nbt.ListTag([nbt.DoubleTag(0)] * 3, 6),
                            "Item": nbt.CompoundTag({"id": nbt.ShortTag(425), "Count": nbt.ByteTag(1),
                                                     "Damage": nbt.ShortTag(4)})})
    (e,) = _legacy_entities([drop], named=True)
    assert e["Item"]["id"].py_data == "minecraft:banner" and int(e["Item"]["Damage"].py_data) == 4
