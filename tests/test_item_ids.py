"""Items handed to Minecraft's data fixers must be named, not numbered.

The game's numeric id fix (ItemIdFix, data version 102) only knows the ids of Java 1.7: a
player or a chest written with numeric ids lost every cooked mutton (424), banner, shield,
elytra, slime block... on the way to the latest Java version (they became air)."""

from worldbridge import items, nbt
from worldbridge.bedrock.extra import bedrock_player_to_legacy
from worldbridge.java.numeric import JavaWriteOptions, _legacy_entities, _legacy_tiles, java_player_nbt

# numeric ids missing from the game's ItemIdFix
UNKNOWN_TO_THE_GAME = {165: "slime", 168: "prismarine", 179: "red_sandstone", 251: "concrete", 409: "prismarine_shard",
                       423: "mutton", 424: "cooked_mutton", 425: "banner", 427: "spruce_door", 442: "shield",
                       443: "elytra", 449: "totem_of_undying"}


def _bedrock_item(name, count=1, slot=0, damage=0):
    return nbt.CompoundTag({"Name": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(count),
                            "Damage": nbt.ShortTag(damage), "Slot": nbt.ByteTag(slot)})


def _bedrock_player():
    return nbt.CompoundTag({
        "Pos": nbt.ListTag([nbt.FloatTag(0.5), nbt.FloatTag(65.62), nbt.FloatTag(0.5)], 5),
        "Inventory": nbt.ListTag([_bedrock_item("cooked_mutton", 12, 0), _bedrock_item("mutton", 3, 1),
                                  _bedrock_item("cooked_beef", 5, 2), _bedrock_item("shield", 1, 3),
                                  _bedrock_item("charcoal", 7, 4)], 10),
        "EnderChestInventory": nbt.ListTag([_bedrock_item("elytra", 1, 0)], 10),
    })


def _stacks(lst):
    return {int(t["Slot"].py_data): (t["id"].py_data, int(t["Count"].py_data), int(t["Damage"].py_data)) for t in lst}


def test_bedrock_player_to_latest_java_keeps_cooked_mutton():
    p = java_player_nbt(bedrock_player_to_legacy(_bedrock_player()), JavaWriteOptions(kind="anvil", modern_players=True))
    assert all(isinstance(t["id"], nbt.StringTag) for t in p["Inventory"])
    assert _stacks(p["Inventory"]) == {0: ("minecraft:cooked_mutton", 12, 0), 1: ("minecraft:mutton", 3, 0),
                                       2: ("minecraft:cooked_beef", 5, 0), 3: ("minecraft:shield", 1, 0),
                                       4: ("minecraft:coal", 7, 1)}  # charcoal: flattened by the game
    assert _stacks(p["EnderItems"]) == {0: ("minecraft:elytra", 1, 0)}


def test_pre_19_player_stays_numeric():
    p = java_player_nbt(bedrock_player_to_legacy(_bedrock_player()), JavaWriteOptions(kind="mcregion"))
    assert all(isinstance(t["id"], nbt.ShortTag) for t in p["Inventory"])


def test_names_read_back_as_the_same_item():
    for iid, name in UNKNOWN_TO_THE_GAME.items():
        num = nbt.CompoundTag({"id": nbt.ShortTag(iid), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0)})
        named = items.named_item(num)
        assert named["id"].py_data == "minecraft:" + name
        assert items.from_legacy(named)["name"] == items.from_legacy(num)["name"]
    stone = nbt.CompoundTag({"id": nbt.StringTag("minecraft:stone"), "Count": nbt.ByteTag(1)})
    assert items.named_item(stone) is stone


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
