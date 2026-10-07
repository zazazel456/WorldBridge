"""Loot tables of containers (chests, barrels, dispensers...) and copper chests through the canonical block entities."""
from worldbridge import nbt, tiles
from worldbridge.java import modern


def _chest_java(**extra):
    t = nbt.CompoundTag({"id": nbt.StringTag("minecraft:chest"), "x": nbt.IntTag(3), "y": nbt.IntTag(64), "z": nbt.IntTag(5),
                         "Items": nbt.ListTag([], 10), "LootTable": nbt.StringTag("minecraft:chests/simple_dungeon"),
                         "LootTableSeed": nbt.LongTag(-5946147822115377411)})
    for k, v in extra.items():
        t[k] = v
    return t


def test_loot_table_of_a_chest_goes_from_java_to_bedrock_and_back():
    c = tiles.from_java_modern(_chest_java())
    assert c["loot"] == ("minecraft:chests/simple_dungeon", -5946147822115377411)
    be = tiles.to_bedrock(c, (1, 21, 50))
    assert nbt.get(be, "LootTable") == "loot_tables/chests/simple_dungeon.json"
    assert isinstance(be["LootTableSeed"], nbt.IntTag)
    back = tiles.from_bedrock(be)
    assert back["loot"][0] == "minecraft:chests/simple_dungeon"
    j = tiles.to_java_modern(back, 3955)
    assert nbt.get(j, "LootTable") == "minecraft:chests/simple_dungeon" and "LootTableSeed" in j


def test_loot_table_of_every_container_and_the_special_names():
    for jid in ("barrel", "dispenser", "dropper", "hopper", "shulker_box", "trapped_chest"):
        t = _chest_java()
        t["id"] = nbt.StringTag("minecraft:" + jid)
        c = tiles.from_java_modern(t)
        assert c["loot"], jid
        assert nbt.get(tiles.to_bedrock(c, (1, 21, 50)), "LootTable"), jid
        assert nbt.get(tiles.to_java_modern(c, 3955), "LootTable") == "minecraft:chests/simple_dungeon", jid
    t = _chest_java(LootTable=nbt.StringTag("minecraft:chests/buried_treasure"))
    be = tiles.to_bedrock(tiles.from_java_modern(t), (1, 20, 0))
    assert nbt.get(be, "LootTable") == "loot_tables/chests/buriedtreasure.json"


def test_loot_table_of_a_legacy_chest_is_read_and_written_back():
    t = nbt.CompoundTag({"id": nbt.StringTag("Chest"), "x": nbt.IntTag(1), "y": nbt.IntTag(5), "z": nbt.IntTag(1),
                         "LootTable": nbt.StringTag("chests/abandoned_mineshaft"), "LootTableSeed": nbt.LongTag(7)})
    c = tiles.from_legacy(t)
    assert c["loot"] == ("minecraft:chests/abandoned_mineshaft", 7)
    assert nbt.get(tiles.to_legacy(c), "LootTable") == "minecraft:chests/abandoned_mineshaft"
    assert "LootTable" not in tiles.to_legacy(c, lce=True)


# ------------------------------------------------------------------ copper chests


def _root_with(block):
    pal = nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag(block)})], 10)
    sec = nbt.CompoundTag({"Y": nbt.ByteTag(4), "block_states": nbt.CompoundTag({"palette": pal})})
    return nbt.CompoundTag({"DataVersion": nbt.IntTag(4800), "sections": nbt.ListTag([sec], 10)})


def test_a_copper_chest_block_entity_keeps_the_id_of_its_block():
    for block in ("minecraft:copper_chest", "minecraft:waxed_oxidized_copper_chest"):
        c = tiles.from_java_modern(_chest_java(id=nbt.StringTag(block)))
        assert c["kind"] == "chest"
        modern.resolve_kinds(_root_with(block), [c])
        assert nbt.get(tiles.to_java_modern(c, 4800), "id") == block
    wooden = tiles.from_java_modern(_chest_java(id=nbt.StringTag("minecraft:copper_chest")))
    modern.resolve_kinds(_root_with("minecraft:chest"), [wooden])        # the target has no copper chest: Amulet made it wooden
    assert nbt.get(tiles.to_java_modern(wooden, 3465), "id") == "minecraft:chest"
