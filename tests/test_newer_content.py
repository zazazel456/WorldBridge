"""Items and mobs that a Java target older than the source does not have are removed and reported."""
from worldbridge import newcontent as nc
from worldbridge import nbt
from worldbridge.items import Item
from worldbridge.model import Progress


def test_item_and_mob_tables_by_release():
    assert not nc.java_item_exists("armadillo_scute", (1, 20, 4)) and nc.java_item_exists("armadillo_scute", (1, 20, 5))
    assert not nc.java_item_exists("breeze_spawn_egg", (1, 20, 4)) and nc.java_item_exists("breeze_spawn_egg", (1, 21, 0))
    assert not nc.java_item_exists("allay_spawn_egg", (1, 18, 0)) and not nc.java_item_exists("tadpole_bucket", (1, 18, 0))
    assert not nc.java_item_exists("copper_golem_spawn_egg", (1, 20, 4))
    assert not nc.java_item_exists("copper_chest", (1, 20, 4)) and nc.java_item_exists("copper_chest", (1, 21, 9))   # block items: PyMCTranslate
    assert not nc.java_item_exists("mangrove_door", (1, 18, 0)) and not nc.java_item_exists("pale_oak_door", (1, 20, 4))
    assert nc.java_item_exists("diamond", (1, 13, 0)) and nc.java_item_exists("made_up_item", (1, 13, 0))
    assert not nc.java_entity_exists("warden", (1, 18, 0)) and nc.java_entity_exists("warden", (1, 19, 0))
    assert not nc.java_entity_exists("minecraft:camel", (1, 19, 4)) and nc.java_entity_exists("camel", (1, 20, 0))
    assert nc.java_entity_exists("zombie", (1, 13, 0))
    assert not nc.bedrock_entity_exists("allay", (1, 18, 0)) and nc.bedrock_entity_exists("allay", (1, 19, 0))


def _item(name, count=1):
    return Item(name=name, count=count)


def test_clean_extras_removes_what_the_target_lacks_and_counts_it():
    tally = nc.Tally()
    chest = {"kind": "chest", "pos": (1, 64, 1), "items": [_item("stick", 3), _item("armadillo_scute"), _item("diamond")]}
    jukebox = {"kind": "jukebox", "pos": (2, 64, 2), "record": _item("music_disc_creator")}
    mobs = [{"name": "armadillo", "pos": (0, 0, 0)}, {"name": "pig", "pos": (0, 0, 0)},
            {"name": "item", "item": _item("wolf_armor")},
            {"name": "zombie", "equip": {"hand": [_item("mace"), _item("stick")], "armor": [None, _item("iron_boots"), None, None]}}]
    tl, el = nc.clean_extras([chest, jukebox], mobs, (1, 20, 4), tally)
    assert [i["name"] for i in chest["items"]] == ["stick", "diamond"]
    assert jukebox["record"] is None
    assert [e["name"] for e in el] == ["pig", "zombie"]
    assert el[1]["equip"]["hand"][0] is None and el[1]["equip"]["hand"][1]["name"] == "stick"     # the slot stays
    assert (tally.items, tally.entities) == (1 + 1 + 1 + 1, 2)                                    # scute, disc, wolf armor, mace; armadillo, item entity


def test_the_warning_is_the_one_the_old_routes_give():
    logs = Progress(None, lambda m: None)
    tally = nc.tally_of(logs)
    assert nc.tally_of(logs) is tally
    nc.Tally().warn(logs, "Java 1.20.4")
    assert not logs.warnings
    tally.items, tally.entities, tally.tiles = 5, 2, 1
    tally.warn(logs, "Java 1.20.4")
    assert logs.warnings == ["Content that does not exist in Java 1.20.4: removed 5 items, 2 entities and 1 block entities."]


def test_a_bedrock_player_loses_the_items_an_older_java_target_lacks():
    def it(name):
        return nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(1), "Slot": nbt.ByteTag(0)})

    p = nbt.CompoundTag({"Inventory": nbt.ListTag([it("stick"), it("copper_chest"), it("birch_shelf"), it("armadillo_scute")], 10),
                         "EnderItems": nbt.ListTag([it("diamond")], 10)})
    tally = nc.Tally()
    assert nc.clean_player(p, (1, 20, 4), tally) == 3
    assert [str(nbt.get(i, "id")) for i in p["Inventory"]] == ["minecraft:stick"] and tally.items == 3
    assert len(p["EnderItems"]) == 1
