"""Items a Bedrock target older than the item lacks are dropped and counted (every route to Bedrock), and the string
items an LCE target has no id for are counted in the writer's report of removed items."""
import numpy as np
import pytest

from worldbridge import bedrock_item_since as since
from worldbridge import items, nbt
from worldbridge import newcontent as nc
from worldbridge.bedrock import extra as bx
from worldbridge.items import Item
from worldbridge.lce.world import LCEWriteOptions, LCEWriter, legacy_item, legacy_items
from worldbridge.model import NumericChunk, Progress

T = nbt.CompoundTag


def test_the_table_is_from_the_release_lists_and_unknown_is_kept():
    first = min(since.ITEMS_SINCE)
    assert first >= (1, 11, 0) and sum(len(v) for v in since.ITEMS_SINCE.values()) > 500
    assert nc.BEDROCK_ITEM_SINCE["netherite_ingot"] == (1, 16, 0) and nc.BEDROCK_ITEM_SINCE["amethyst_shard"] == (1, 17, 0)
    assert not nc.bedrock_item_exists("minecraft:netherite_ingot", (1, 14, 60))
    assert nc.bedrock_item_exists("minecraft:netherite_ingot", (1, 16, 0))
    assert nc.bedrock_item_exists("netherite_ingot", (1, 21, 0))
    assert nc.bedrock_item_exists("minecraft:diamond", (1, 2, 0)) and nc.bedrock_item_exists("made_up_item", (1, 2, 0))
    assert nc.bedrock_item_exists("appleEnchanted", (1, 12, 0))                # the pre-flattening spellings: not listed
    # a spawn egg follows its mob
    assert not nc.bedrock_item_exists("minecraft:allay_spawn_egg", (1, 18, 0))
    assert nc.bedrock_item_exists("minecraft:allay_spawn_egg", (1, 19, 0))
    assert nc.bedrock_item_exists("minecraft:pig_spawn_egg", (1, 12, 0))


def test_to_bedrock_drops_what_the_version_lacks_and_counts_it():
    t = nc.Tally()
    with nc.counting(t):
        assert items.to_bedrock(Item(name="netherite_ingot", count=3), (1, 14, 60)) is None
        assert items.to_bedrock(Item(name="amethyst_shard", count=1), (1, 16, 220)) is None
        assert items.to_bedrock(Item(name="crimson_planks", count=1), (1, 12, 0)) is None
        assert items.to_bedrock(Item(name="allay_spawn_egg", count=1), (1, 12, 0)) is None
        ok = items.to_bedrock(Item(name="netherite_ingot", count=3), (1, 16, 220))
        assert ok is not None and str(ok["Name"].py_data) == "minecraft:netherite_ingot"
        assert items.to_bedrock(Item(name="stick", count=1), (1, 12, 0)) is not None
    assert t.items == 4
    items.to_bedrock(Item(name="netherite_ingot", count=1), (1, 12, 0))      # no counting block: dropped, nothing to count


def test_the_name_the_target_uses_is_the_one_checked():
    """Before 1.16.100 a dye / bucket / boat is the old name with a Damage: they exist whatever the table says of the
    new name, and a bucket of axolotl (1.17) still follows its table entry."""
    t = nc.Tally()
    with nc.counting(t):
        d = items.to_bedrock(Item(name="red_dye", count=1), (1, 12, 0))
        assert d is not None and str(d["Name"].py_data) == "minecraft:dye"
        b = items.to_bedrock(Item(name="water_bucket", count=1), (1, 12, 0))
        assert b is not None and str(b["Name"].py_data) == "minecraft:bucket"
        assert items.to_bedrock(Item(name="axolotl_bucket", count=1), (1, 16, 220)) is None
    assert t.items == 1


def _stack(name, slot=0):
    return T({"Name": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(0),
              "WasPickedUp": nbt.ByteTag(0), "Slot": nbt.ByteTag(slot)})


def test_bedrock_to_older_bedrock_empties_the_slot_and_counts():
    t = nc.Tally()
    chest = T({"id": nbt.StringTag("Chest"),
               "Items": nbt.ListTag([_stack("stick", 0), _stack("netherite_ingot", 1), _stack("amethyst_shard", 2)], 10)})
    with nc.counting(t):
        assert bx.retarget_items(chest, (1, 14, 60)) is True
    names = [str(x["Name"].py_data) for x in chest["Items"]]
    assert names == ["minecraft:stick", "", ""] and [int(x["Slot"].py_data) for x in chest["Items"]] == [0, 1, 2]
    assert [int(x["Count"].py_data) for x in chest["Items"]] == [1, 0, 0]
    assert t.items == 2


def test_an_item_entity_with_nothing_left_is_gone_and_counted():
    t = nc.Tally()
    drop = T({"identifier": nbt.StringTag("minecraft:item"), "Item": _stack("netherite_ingot")})
    with nc.counting(t):
        assert bx.retarget_items(drop, (1, 14, 60)) is False and "Item" not in drop
        keep = T({"identifier": nbt.StringTag("minecraft:item"), "Item": _stack("stick")})
        assert bx.retarget_items(keep, (1, 14, 60)) is True and str(keep["Item"]["Name"].py_data) == "minecraft:stick"
    assert t.items == 1
    assert bx.retarget_stack(_stack("netherite_ingot"), (1, 21, 0)) is not None
    assert bx.retarget_stack(_stack("netherite_ingot"), (1, 14, 60)) is None


def test_the_missing_items_are_in_the_warning_the_conversion_gives():
    log = Progress()
    warned = []
    log.warn = warned.append
    t = nc.tally_of(log)
    with nc.counting(t):
        items.to_bedrock(Item(name="netherite_ingot", count=1), (1, 12, 0))
    nc.tally_of(log).warn(log, "Bedrock 1.12.0")
    assert len(warned) == 1 and "removed 1 items" in warned[0] and "Bedrock 1.12.0" in warned[0]


# ------------------------------------------------------------------ LCE: string items with no id are counted
def test_unmapped_string_items_are_counted_in_the_lce_writers_report(tmp_path):
    w = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64"), Progress())
    ok = T({"id": nbt.StringTag("minecraft:stick"), "Count": nbt.ByteTag(1), "Slot": nbt.ByteTag(0)})
    odd = T({"id": nbt.StringTag("minecraft:made_up_modern_thing"), "Count": nbt.ByteTag(1), "Slot": nbt.ByteTag(1)})
    air = T({"id": nbt.StringTag("minecraft:air"), "Count": nbt.ByteTag(0), "Slot": nbt.ByteTag(2)})
    from worldbridge.lce import world as lw

    with lw._counting_unmapped(w.compat):
        assert legacy_item(odd) is None
        legacy_item(air)                                                     # air is nothing, not a loss
        assert legacy_item(ok) is not None
        assert len(legacy_items(nbt.ListTag([ok, odd, odd], 10), modern=True)) == 1
        assert len(legacy_items(nbt.ListTag([ok, odd], 10))) == 1
    assert w.compat.dropped == {"item minecraft:made_up_modern_thing": 4}
    assert legacy_item(odd) is None                                          # outside a writer: nothing to count, no error


def test_the_writer_reports_them_with_the_removed_items(tmp_path):
    msgs = []
    log = Progress()
    log.warn = msgs.append
    w = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64"), log)
    c = NumericChunk(0, 0, 256)
    c.blocks[0, 0, 0] = 7
    odd = T({"id": nbt.StringTag("minecraft:made_up_modern_thing"), "Count": nbt.ByteTag(1), "Slot": nbt.ByteTag(0)})
    chest = T({"id": nbt.StringTag("Chest"), "x": nbt.IntTag(1), "y": nbt.IntTag(64), "z": nbt.IntTag(1),
               "Items": nbt.ListTag([odd], 10)})
    c.blocks[64, 1, 1] = 54
    c.tile_entities = [chest]
    w.add_chunk(0, c)
    assert w.dropped.get("item minecraft:made_up_modern_thing", 0) >= 1
