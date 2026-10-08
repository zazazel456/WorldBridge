"""What each game version registers: status effects, map colours, biomes, blocks, and the item ids of
Bedrock before and after its 1.16.100 item flattening."""

import os

import numpy as np

from worldbridge import biomes, items, maps, nbt, tiles
from worldbridge import newcontent as nc
from worldbridge import blocks as blk
from worldbridge.convert import TargetSpec
from worldbridge.items import Item
from worldbridge.java import modern
from worldbridge.java.oldcontent import OldContent
from worldbridge.model import Progress

from .helpers import SyntheticWorld
from .test_losses import _at, _chunk


# ------------------------------------------------------------------ status effects (old Java players)
def _effects_kept(version, ids):
    p = nbt.CompoundTag({"ActiveEffects": nbt.ListTag([
        nbt.CompoundTag({"Id": nbt.ByteTag(i), "Amplifier": nbt.ByteTag(0), "Duration": nbt.IntTag(600)}) for i in ids], 10)})
    eff = nbt.get_tag(OldContent(version).player(p), "ActiveEffects")
    return sorted(int(e["Id"].py_data) for e in eff) if eff is not None else []


def test_status_effects_the_old_game_registers():
    ids = [1, 13, 14, 15, 16, 19, 20, 21, 22, 23, 24]
    assert _effects_kept("1.2", ids) == [1, 13, 15, 19]               # no invisibility / night vision / wither
    assert _effects_kept("1.4", ids) == [1, 13, 14, 15, 16, 19, 20]   # 1.4.2: invisibility, night vision, wither
    assert _effects_kept("1.5", ids) == [1, 13, 14, 15, 16, 19, 20]   # absorption (golden apples) is 1.6
    assert _effects_kept("1.6", ids) == [1, 13, 14, 15, 16, 19, 20, 21, 22, 23]


# ------------------------------------------------------------------ map colours
def _map_blob(colors, **extra):
    data = nbt.CompoundTag({"scale": nbt.ByteTag(0), "dimension": nbt.StringTag("minecraft:overworld"),
                            "xCenter": nbt.IntTag(64), "zCenter": nbt.IntTag(-64),
                            "colors": nbt.ByteArrayTag(np.asarray(colors, np.uint8).view(np.int8)), **extra})
    return nbt.dump(nbt.CompoundTag({"data": data, "DataVersion": nbt.IntTag(2730)}), "", compressed=True)


def _colors(blob):
    root = nbt.load(blob, compressed=None).tag
    return np.asarray(root["data"]["colors"]).astype(np.uint8), root


def _sample():
    c = np.full(128 * 128, 1 * 4 + 2, np.uint8)            # grass
    c[:100] = 35 * 4 + 1                                   # 1.7 - 1.11's last colour
    c[100:200] = 51 * 4 + 2                                # 1.12 terracotta
    c[200:300] = 55 * 4 + 2                                # 1.16 crimson
    c[300:400] = 60 * 4 + 1                                # 1.17 raw iron
    c[400:500] = 0                                         # transparent
    return c


def test_map_colours_each_java_version_registers():
    mc = maps.java_map_colors
    assert [mc("b1.6"), mc("1.6"), mc("1.7"), mc("1.11"), mc("1.12"), mc(None)] == [14, 14, 36, 36, 52, 52]
    assert [mc((1, 6, 4)), mc((1, 8, 9)), mc((1, 12, 2)), mc((1, 15, 2)), mc((1, 16, 5)), mc((1, 17)), mc((26, 3))] \
        == [14, 36, 52, 52, 59, 62, 62]
    assert len(maps.BASE_COLORS) == 62


def test_capped_map_keeps_what_the_target_knows():
    blob = _map_blob(_sample(), locked=nbt.ByteTag(1))
    assert maps.capped_map_file(blob, 62) is blob                       # nothing to change
    for max_base in (14, 36, 52, 59):
        cols, root = _colors(maps.capped_map_file(blob, max_base))
        assert (cols >> 2).max() < max_base
        assert (cols[500:] == 1 * 4 + 2).all() and (cols[400:500] == 0).all()   # known colours stay as they are
        assert int(root["data"]["xCenter"].py_data) == 64 and int(root["data"]["locked"].py_data) == 1
        assert int(root["DataVersion"].py_data) == 2730
    cols, _ = _colors(maps.capped_map_file(blob, 59))
    assert (cols[200:300] == 55 * 4 + 2).all() and (cols[100:200] == 51 * 4 + 2).all()
    assert maps.capped_map_file(b"not a map", 14) == b"not a map"       # never a crash


def test_numeric_targets_get_the_colours_of_their_version(tmp_path):
    from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions

    for kind, limit, max_base in (("anvil", "1.8", 36), ("mcregion", "b1.7", 14), ("anvil", None, 52)):
        src = SyntheticWorld(radius=0)
        src.info.extra_files["data/map_3.dat"] = maps.java_map_file(maps.legacy_map_data(
            nbt.load(_map_blob(_sample()), compressed=None).tag["data"], 62))
        out = str(tmp_path / f"{kind}{limit}")
        JavaNumericWriter(out, JavaWriteOptions(kind=kind, version_limit=limit), Progress()).finish(src.info)
        cols, _ = _colors(open(os.path.join(out, "data", "map_3.dat"), "rb").read())
        assert (cols >> 2).max() < max_base
        assert (cols[100:200] == 51 * 4 + 2).all() == (max_base == 52)   # the hub (1.12) keeps terracotta


def test_java_to_older_java_copies_maps_with_the_targets_colours(tmp_path):
    from worldbridge.extra import _copy_java_side_files, _map_colors

    src, dst = tmp_path / "src", tmp_path / "dst"
    (src / "data").mkdir(parents=True)
    (src / "data" / "map_0.dat").write_bytes(_map_blob(_sample()))
    (src / "data" / "idcounts.dat").write_bytes(b"x")
    dst.mkdir()
    max_base = _map_colors(TargetSpec(family="java", java_mode="amulet", version=(1, 15, 2)))
    assert max_base == 52
    _copy_java_side_files(str(src), str(dst), False, max_base)
    cols, root = _colors((dst / "data" / "map_0.dat").read_bytes())
    assert (cols >> 2).max() < 52 and int(root["data"]["zCenter"].py_data) == -64
    assert (dst / "data" / "idcounts.dat").read_bytes() == b"x"
    assert _map_colors(TargetSpec(family="java", java_mode="amulet", version=(1, 16, 5))) == 59
    assert _map_colors(TargetSpec(family="java", java_mode="amulet", version=(1, 21, 4))) == 62


# ------------------------------------------------------------------ biomes and blocks
def test_the_void_exists_from_java_1_9():
    assert 127 not in biomes.available("java", (1, 8)) and 127 in biomes.available("java", (1, 9))
    assert 127 in biomes.available("java", (1, 12, 2)) and 127 in biomes.available("java", (1, 13))
    assert biomes.game_name(127, "java", (1, 12)) == "The Void"
    assert 127 not in biomes.available("lce")


def test_tall_grass_and_dead_bush_came_with_beta_1_6():
    assert not {31, 32, 96} & blk.java_upto("b1.5")
    assert {31, 32, 96} <= blk.java_upto("b1.6")
    dst_id, _dd, _ch = blk._lut(blk.java_upto("b1.5"))
    assert dst_id[31 << 4 | 1] == 0 and dst_id[32 << 4] == 0


def test_inverted_daylight_detector_becomes_a_daylight_detector():
    dst_id, dst_data, _ch = blk._lut(blk.java_upto("1.5"))
    assert (dst_id[178 << 4 | 7], dst_data[178 << 4 | 7]) == (151, 7)
    assert blk._lut(blk.java_upto("1.4"))[0][178 << 4] == 0                       # none before 1.5


# ------------------------------------------------------------------ Bedrock item ids
def _bedrock(name, version, **kw):
    t = items.to_bedrock(Item(name=name, count=1, damage=0, **kw), version)
    return t["Name"].py_data.split(":", 1)[1], int(t["Damage"].py_data)


def _from_bedrock(name, dmg=0):
    it = items.from_bedrock(nbt.CompoundTag({"Name": nbt.StringTag("minecraft:" + name), "Count": nbt.ByteTag(1),
                                             "Damage": nbt.ShortTag(dmg)}))
    return it and it["name"]


def test_old_bedrock_items_read_with_their_variants():
    assert [_from_bedrock("bucket", d) for d in (0, 1, 2, 4, 5, 8, 10)] == [
        "bucket", "milk_bucket", "cod_bucket", "tropical_fish_bucket", "pufferfish_bucket", "water_bucket", "lava_bucket"]
    assert [_from_bedrock("boat", d) for d in range(6)] == [
        "oak_boat", "spruce_boat", "birch_boat", "jungle_boat", "acacia_boat", "dark_oak_boat"]
    assert [_from_bedrock(n) for n in ("horsearmorleather", "horsearmoriron", "horsearmorgold", "horsearmordiamond")] == [
        "leather_horse_armor", "iron_horse_armor", "golden_horse_armor", "diamond_horse_armor"]
    assert _from_bedrock("dye", 1) == "red_dye" and _from_bedrock("dye", 16) == "black_dye"
    assert _from_bedrock("spawn_egg", 33) == "creeper_spawn_egg" and _from_bedrock("spawn_egg", 15) == "villager_spawn_egg"
    assert _from_bedrock("spawn_egg", 36) == "zombified_piglin_spawn_egg" and _from_bedrock("spawn_egg", 0) is None
    assert [_from_bedrock(n) for n in ("map", "emptyMap", "totem", "fireball", "carrotOnAStick", "muttonRaw",
                                       "record_cat", "fireworksCharge", "turtle_shell_piece")] == [
        "filled_map", "map", "totem_of_undying", "fire_charge", "carrot_on_a_stick", "mutton", "music_disc_cat",
        "firework_star", "turtle_scute"]
    assert _from_bedrock("water_bucket") == "water_bucket" and _from_bedrock("oak_boat") == "oak_boat"   # 1.16.100+


def test_old_bedrock_targets_get_the_old_item_ids():
    old, new = (1, 12, 0), (1, 21, 50)
    for name, before, after in (
            ("red_dye", ("dye", 1), ("red_dye", 0)), ("cod", ("fish", 0), ("cod", 0)),
            ("oak_boat", ("boat", 0), ("oak_boat", 0)), ("dark_oak_boat", ("boat", 5), ("dark_oak_boat", 0)),
            ("water_bucket", ("bucket", 8), ("water_bucket", 0)), ("milk_bucket", ("bucket", 1), ("milk_bucket", 0)),
            ("creeper_spawn_egg", ("spawn_egg", 33), ("creeper_spawn_egg", 0)),
            ("melon_slice", ("melon", 0), ("melon_slice", 0)), ("firework_rocket", ("fireworks", 0), ("firework_rocket", 0)),
            ("music_disc_cat", ("record_cat", 0), ("music_disc_cat", 0)),
            ("iron_horse_armor", ("horsearmoriron", 0), ("iron_horse_armor", 0)),
            ("filled_map", ("map", 0), ("filled_map", 0)), ("map", ("emptyMap", 0), ("empty_map", 0)),
            ("turtle_scute", ("turtle_shell_piece", 0), ("turtle_scute", 0))):
        assert _bedrock(name, old) == before, name
        assert _bedrock(name, new) == after, name
        assert _from_bedrock(*before) == ("map" if name == "map" else name)          # and back
    assert _bedrock("villager_spawn_egg", (1, 10, 0)) == ("spawn_egg", 15)
    assert _bedrock("villager_spawn_egg", (1, 12, 0)) == ("spawn_egg", 115)
    assert _bedrock("black_dye", (1, 9, 0)) == ("dye", 0) and _bedrock("black_dye", (1, 14, 0)) == ("dye", 16)
    assert _bedrock("turtle_scute", (1, 18, 0)) == ("scute", 0)
    assert _bedrock("iron_chain", (1, 21, 50))[0] == "chain" and _bedrock("iron_chain", (1, 21, 110))[0] == "iron_chain"


def test_bedrock_block_items_carry_their_variant_in_damage():
    for v in ((1, 12, 0), (1, 16, 20)):
        assert _bedrock("red_wool", v) == ("wool", 14)
        assert _bedrock("birch_planks", v) == ("planks", 2)
        assert _bedrock("quartz_slab", v) == ("stone_slab", 6)       # Bedrock's own slab order
        assert _bedrock("spruce_fence", v) == ("fence", 1)
        assert _bedrock("chest", v) == ("chest", 0)                  # one item per block: no facing in Damage
    t = items.to_bedrock(Item(name="red_wool", count=1, damage=0), (1, 16, 20))
    assert t["Block"]["states"]["color"].py_data == "red"
    assert _bedrock("red_wool", (1, 21, 50)) == ("red_wool", 0)
    assert _from_bedrock("wool", 14) == "red_wool"


def test_block_items_of_bedrock_1_13_plus_never_carry_block_data():
    """Bedrock 1.13+ has block states, no block_data: a torch's Damage is not a placed state."""
    for v in ((1, 13, 0), (1, 16, 220), (1, 21, 60), (26, 50, 0)):
        for name in ("torch", "redstone_torch", "furnace", "ladder", "ender_chest", "trapped_chest", "chest", "pumpkin",
                     "structure_block", "dispenser", "anvil", "oak_planks", "red_wool"):
            t = items.to_bedrock(Item(name=name, count=1, damage=0), v)
            blk = t.get("Block")
            assert blk is None or "block_data" not in blk["states"], (name, v)
        t = items.to_bedrock(Item(name="torch", count=1, damage=0), v)
        assert "Block" not in t or t["Block"]["name"].py_data == "minecraft:torch"
    # a valid state is still written
    assert items.to_bedrock(Item(name="red_wool", count=1, damage=0), (1, 16, 20))["Block"]["states"]["color"].py_data == "red"
    # before 1.13 the numeric era's block_data is the state
    assert "block_data" in items.to_bedrock(Item(name="torch", count=1, damage=0), (1, 12, 0))["Block"]["states"]


def test_java_stone_stairs_are_bedrocks_normal_stone_stairs():
    for v in ((1, 12, 0), (1, 16, 220), (1, 21, 60)):
        assert _bedrock("stone_stairs", v)[0] == "normal_stone_stairs", v
        assert _bedrock("cobblestone_stairs", v)[0] == "stone_stairs", v
        t = items.to_bedrock(Item(name="stone_stairs", count=1, damage=0), v)
        assert t["Block"]["name"].py_data == "minecraft:normal_stone_stairs"
        # and back, with and without the Block compound
        assert items.from_bedrock(t)["name"] == "stone_stairs"
        t.pop("Block")
        assert items.from_bedrock(t)["name"] == "stone_stairs"
    assert _from_bedrock("stone_stairs") == "cobblestone_stairs"


# ------------------------------------------------------------------ block entities of Java 1.14+ / Bedrock
JAVA_NEW, BEDROCK_NEW = 4189, (1, 21, 60)          # 1.21.4 / Bedrock 1.21.60
JAVA_OLD, BEDROCK_OLD = 3700, (1, 20, 40)          # 1.20.4 (items with tag) / Bedrock 1.20.40


def _jstack(name, count=1, slot=None, dv=JAVA_NEW, **extra):
    return items.to_java_modern(Item(name=name, count=count, damage=0, slot=slot, **extra), dv)


def _jtile(tid, x=4, y=70, z=-9, **fields):
    t = nbt.CompoundTag({"id": nbt.StringTag("minecraft:" + tid), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z)})
    for k, v in fields.items():
        t[k] = v
    return t


def _jlist(*stacks):
    return nbt.ListTag(list(stacks), 10)


def _strs(*names):
    return nbt.ListTag([nbt.StringTag(n) for n in names], 8)


def _round(t, dv=JAVA_NEW, version=BEDROCK_NEW):
    """Java block entity -> Bedrock block entity -> Java block entity (canonical forms between)."""
    b = tiles.to_bedrock(tiles.from_java_modern(t), version)
    assert b is not None, t
    back = tiles.to_java_modern(tiles.from_bedrock(b), dv)
    assert back is not None
    return b, back


def test_decorated_pot_keeps_sherds_item_and_loot_table():
    pot = _jtile("decorated_pot", sherds=_strs("minecraft:angler_pottery_sherd", "minecraft:brick", "minecraft:brick",
                                               "minecraft:flow_pottery_sherd"),
                 item=_jstack("emerald", 3))
    b, back = _round(pot)
    assert b["id"].py_data == "DecoratedPot" and [s.py_data for s in b["sherds"]] == [
        "minecraft:angler_pottery_sherd", "minecraft:brick", "minecraft:brick", "minecraft:flow_pottery_sherd"]
    assert b["item"]["Name"].py_data == "minecraft:emerald" and int(b["item"]["Count"].py_data) == 3
    assert [s.py_data for s in back["sherds"]] == [s.py_data for s in pot["sherds"]]
    assert back["id"].py_data == "minecraft:decorated_pot" and int(back["item"]["count"].py_data) == 3
    # a loot table replaces the item (Bedrock names its files, the seed is folded into 32 bits)
    pot = _jtile("decorated_pot", LootTable=nbt.StringTag("minecraft:pots/trial_chambers/corridor"),
                 LootTableSeed=nbt.LongTag(-3101238399747803554))
    b, back = _round(pot)
    assert b["LootTable"].py_data == "loot_tables/pots/trial_chambers/corridor.json" and "sherds" not in b
    assert back["LootTable"].py_data == "minecraft:pots/trial_chambers/corridor"
    assert tiles.loot_to_bedrock("minecraft:chests/shipwreck_map") == "loot_tables/chests/shipwreck.json"
    assert tiles.loot_from_bedrock("loot_tables/chests/shipwreck.json") == "minecraft:chests/shipwreck_map"
    assert tiles.loot_to_bedrock("minecraft:chests/simple_dungeon") == "loot_tables/chests/simple_dungeon.json"


def test_decorated_pot_sherds_are_shards_before_java_1_20():
    pot = tiles.from_java_modern(_jtile("decorated_pot", sherds=_strs("minecraft:brick", "minecraft:brick",
                                                                      "minecraft:brick", "minecraft:skull_pottery_sherd")))
    assert "shards" in tiles.to_java_modern(pot, 3337) and "sherds" in tiles.to_java_modern(pot, 3463)
    assert "shards" in tiles.to_bedrock(pot, (1, 19, 80)) and "sherds" in tiles.to_bedrock(pot, (1, 20, 0))
    assert tiles.from_java_modern(tiles.to_java_modern(pot, 3337))["sherds"][3] == "skull_pottery_sherd"
    assert tiles.from_java_modern(_jtile("decorated_pot"))["sherds"] is None          # no sherds: nothing written
    assert "sherds" not in tiles.to_bedrock(tiles.from_java_modern(_jtile("decorated_pot")), BEDROCK_NEW)


def test_campfires_keep_their_stacks_and_cooking_times():
    for name in ("campfire", "soul_campfire"):
        t = _jtile(name, Items=_jlist(_jstack("beef", 1, 0), _jstack("chicken", 1, 2)),
                   CookingTimes=nbt.IntArrayTag(np.array([120, 0, 30, 0], np.int32)),
                   CookingTotalTimes=nbt.IntArrayTag(np.array([600, 0, 600, 0], np.int32)))
        b, back = _round(t)
        assert b["id"].py_data == "Campfire" and b["Item1"]["Name"].py_data == "minecraft:beef"
        assert b["Item3"]["Name"].py_data == "minecraft:chicken" and "Item2" not in b and "Slot" not in b["Item1"]
        assert [int(b[f"ItemTime{i}"].py_data) for i in (1, 2, 3, 4)] == [120, 0, 30, 0]
        assert back["id"].py_data == "minecraft:campfire"   # Bedrock has one id: java.modern.resolve_kinds tells them apart
        assert [(int(i["Slot"].py_data), i["id"].py_data) for i in back["Items"]] == [
            (0, "minecraft:beef"), (2, "minecraft:chicken")]
        assert list(back["CookingTimes"].py_data) == [120, 0, 30, 0] and list(back["CookingTotalTimes"].py_data) == [600, 0, 600, 0]
        old = tiles.to_java_modern(tiles.from_bedrock(b), JAVA_OLD)       # items of the target: Count / tag, not components
        assert int(old["Items"][0]["Count"].py_data) == 1 and "count" not in old["Items"][0]
    soul = tiles.from_java_modern(_jtile("soul_campfire"))
    assert tiles.to_java_modern(soul, 2500) is None and tiles.to_java_modern(soul, 2566)["id"].py_data == "minecraft:campfire"   # the registry has no soul_campfire type
    assert tiles.to_bedrock(soul, (1, 14, 0)) is None and tiles.to_bedrock(soul, (1, 16, 0)) is not None
    camp = tiles.from_java_modern(_jtile("campfire"))
    assert tiles.to_java_modern(camp, 1519) is None and tiles.to_bedrock(camp, (1, 10, 0)) is None


def _bee(java=True, nectar=1, left=1000):
    entity = nbt.CompoundTag({"id": nbt.StringTag("minecraft:bee"), "Health": nbt.FloatTag(10.0), "Age": nbt.IntTag(0),
                              "HasNectar": nbt.ByteTag(nectar), "HasStung": nbt.ByteTag(0),
                              "Pos": nbt.ListTag([nbt.DoubleTag(1.0)] * 3, 6)})
    return nbt.CompoundTag({"entity_data" if java else "EntityData": entity,
                            "min_ticks_in_hive" if java else "MinOccupationTicks": nbt.IntTag(2400),
                            "ticks_in_hive" if java else "TicksInHive": nbt.IntTag(2400 - left)})


def test_hives_keep_their_bees():
    for name in ("beehive", "bee_nest"):
        t = _jtile(name, bees=_jlist(_bee(), _bee(nectar=0, left=40)))
        b, back = _round(t)
        assert b["id"].py_data == "Beehive" and len(b["Occupants"]) == 2
        occ = b["Occupants"][0]
        assert occ["ActorIdentifier"].py_data == "minecraft:bee<>" and occ["SaveData"]["identifier"].py_data == "minecraft:bee"
        assert int(occ["TicksLeftToStay"].py_data) == 1000 and int(b["Occupants"][1]["TicksLeftToStay"].py_data) == 40
        assert int(occ["SaveData"]["properties"]["minecraft:has_nectar"].py_data) == 1
        assert "properties" not in b["Occupants"][1]["SaveData"]
        bee = back["bees"][0]
        assert bee["entity_data"]["id"].py_data == "minecraft:bee" and int(bee["min_ticks_in_hive"].py_data) == 1000
        assert int(bee["entity_data"]["HasNectar"].py_data) == 1 and "Pos" not in bee["entity_data"] and "UUID" not in bee["entity_data"]
        assert back["bees"][1]["entity_data"]["HasNectar"].py_data == 0
    # 1.15 - 1.20.4 name the fields differently
    old = tiles.to_java_modern(tiles.from_java_modern(_jtile("beehive", bees=_jlist(_bee()))), JAVA_OLD)
    assert "bees" not in old and old["Bees"][0]["EntityData"]["id"].py_data == "minecraft:bee"
    assert int(old["Bees"][0]["MinOccupationTicks"].py_data) == 2400
    again = tiles.from_java_modern(old)
    assert len(again["bees"]) == 1 and again["bees"][0]["min"] == 2400 and again["bees"][0]["ticks"] == 1400
    assert tiles.to_java_modern(tiles.from_java_modern(_jtile("beehive")), 2000) is None      # 1.14: no hives yet


def test_lecterns_keep_their_book_and_page():
    book = _jstack("writable_book", 1, pages=["uno", "due", "tre"])
    b, back = _round(_jtile("lectern", Book=book, Page=nbt.IntTag(2)))
    assert b["id"].py_data == "Lectern" and b["book"]["Name"].py_data == "minecraft:writable_book"
    assert int(b["page"].py_data) == 2 and int(b["totalPages"].py_data) == 3 and int(b["hasBook"].py_data) == 1
    assert [str(nbt.get(p, "text")) for p in b["book"]["tag"]["pages"]] == ["uno", "due", "tre"]
    assert int(back["Page"].py_data) == 2 and back["Book"]["id"].py_data == "minecraft:writable_book"
    pages = back["Book"]["components"]["minecraft:writable_book_content"]["pages"]
    assert [str(nbt.get(p, "raw")) for p in pages] == ["uno", "due", "tre"]
    empty = tiles.to_bedrock(tiles.from_java_modern(_jtile("lectern")), BEDROCK_NEW)
    assert "book" not in empty and "hasBook" not in empty


def test_chiseled_bookshelves_and_crafters_keep_their_slots():
    t = _jtile("chiseled_bookshelf", Items=_jlist(_jstack("book", 1, 1), _jstack("enchanted_book", 1, 5)),
               last_interacted_slot=nbt.IntTag(5))
    b, back = _round(t)
    assert len(b["Items"]) == 6 and int(b["LastInteractedSlot"].py_data) == 5
    assert [i["Name"].py_data for i in b["Items"]] == ["", "minecraft:book", "", "", "", "minecraft:enchanted_book"]
    assert "Slot" not in b["Items"][1] and int(b["Items"][0]["Count"].py_data) == 0
    assert [(int(i["Slot"].py_data), i["id"].py_data) for i in back["Items"]] == [(1, "minecraft:book"), (5, "minecraft:enchanted_book")]
    assert int(back["last_interacted_slot"].py_data) == 5
    t = _jtile("crafter", Items=_jlist(_jstack("birch_log", 64, 0), _jstack("stick", 2, 4)),
               disabled_slots=nbt.IntArrayTag(np.array([1, 8], np.int32)), triggered=nbt.IntTag(1),
               crafting_ticks_remaining=nbt.IntTag(3))
    b, back = _round(t)
    assert int(b["disabled_slots"].py_data) == 0b100000010 and int(b["Items"][1]["Slot"].py_data) == 4
    assert list(back["disabled_slots"].py_data) == [1, 8] and [int(i["Slot"].py_data) for i in back["Items"]] == [0, 4]
    assert tiles.to_java_modern(tiles.from_java_modern(t), JAVA_OLD) is None              # 1.20.4: no crafter yet
    assert tiles.to_bedrock(tiles.from_java_modern(t), BEDROCK_OLD) is None


def test_shelves_need_java_1_21_9_and_bedrock_1_21_110():
    t = _jtile("shelf", Items=_jlist(_jstack("book", 1, 0), _jstack("stick", 1, 2)), align_items_to_bottom=nbt.ByteTag(1))
    c = tiles.from_java_modern(t)
    assert tiles.to_java_modern(c, 4439) is None and tiles.to_bedrock(c, (1, 21, 100)) is None
    b, back = _round(t, dv=4553, version=(1, 21, 110))
    assert b["id"].py_data == "Shelf" and [i["Name"].py_data for i in b["Items"]] == ["minecraft:book", "", "minecraft:stick"]
    assert [(int(i["Slot"].py_data), i["id"].py_data) for i in back["Items"]] == [(0, "minecraft:book"), (2, "minecraft:stick")]
    assert back["id"].py_data == "minecraft:shelf" and int(back["align_items_to_bottom"].py_data) == 0      # Bedrock has no such flag
    assert int(tiles.to_java_modern(c, 4553)["align_items_to_bottom"].py_data) == 1                         # Java to Java keeps it


def test_brushable_blocks_keep_their_find():
    c = tiles.from_java_modern(_jtile("suspicious_sand", item=_jstack("brick", 1)))      # 1.19.4's id of the block entity
    c.update({"block": "suspicious_gravel", "dusted": 2})
    b = tiles.to_bedrock(c, BEDROCK_NEW)
    assert b["id"].py_data == "BrushableBlock" and b["type"].py_data == "minecraft:suspicious_gravel"
    assert int(b["brush_count"].py_data) == 2 and b["item"]["Name"].py_data == "minecraft:brick" and int(b["brush_direction"].py_data) == 6
    back = tiles.from_bedrock(b)
    assert back["block"] == "suspicious_gravel" and back["dusted"] == 2
    assert tiles.to_java_modern(back, JAVA_NEW)["id"].py_data == "minecraft:brushable_block"
    assert tiles.to_java_modern(back, 3337)["id"].py_data == "minecraft:suspicious_sand"
    loot = tiles.from_java_modern(_jtile("brushable_block", LootTable=nbt.StringTag("minecraft:archaeology/desert_well"),
                                         LootTableSeed=nbt.LongTag(7)))
    assert tiles.to_bedrock(loot, BEDROCK_NEW)["LootTable"].py_data == "loot_tables/entities/desert_well_brushable_block.json"
    # Bedrock's empty find is no loot table in Java
    empty = nbt.CompoundTag({"id": nbt.StringTag("BrushableBlock"), "x": nbt.IntTag(1), "y": nbt.IntTag(2), "z": nbt.IntTag(3),
                             "LootTable": nbt.StringTag("loot_tables/entities/empty_brushable_block.json"), "LootTableSeed": nbt.IntTag(0)})
    assert "LootTable" not in tiles.to_java_modern(tiles.from_bedrock(empty), JAVA_NEW)


def test_vaults_and_trial_spawners_keep_what_maps_cleanly():
    t = _jtile("vault", config=nbt.CompoundTag({"key_item": _jstack("ominous_trial_key"),
                                                "loot_table": nbt.StringTag("minecraft:chests/trial_chambers/reward_ominous")}),
               server_data=nbt.CompoundTag({"state_updating_resumes_at": nbt.LongTag(99),
                                            "items_to_eject": _jlist(_jstack("diamond", 2))}),
               shared_data=nbt.CompoundTag({"display_item": _jstack("emerald")}))
    b, back = _round(t)
    assert b["config"]["key_item"]["Name"].py_data == "minecraft:ominous_trial_key"
    assert b["config"]["loot_table"].py_data == "loot_tables/chests/trial_chambers/reward_ominous.json"
    assert b["data"]["display_item"]["Name"].py_data == "minecraft:emerald" and int(b["data"]["state_updating_resumes_at"].py_data) == 99
    assert back["config"]["loot_table"].py_data == "minecraft:chests/trial_chambers/reward_ominous"
    assert back["server_data"]["items_to_eject"][0]["id"].py_data == "minecraft:diamond"
    assert back["shared_data"]["display_item"]["id"].py_data == "minecraft:emerald"
    plain = tiles.to_bedrock(tiles.from_java_modern(_jtile("vault")), BEDROCK_NEW)     # nothing in it: the usual loot table
    assert plain["config"]["loot_table"].py_data == "loot_tables/chests/trial_chambers/reward.json"
    config = nbt.CompoundTag({"spawn_range": nbt.IntTag(5), "total_mobs": nbt.FloatTag(9.0),
                              "loot_tables_to_eject": nbt.ListTag([nbt.CompoundTag({"data": nbt.StringTag("minecraft:spawners/trial_chamber/key"),
                                                                                    "weight": nbt.IntTag(1)})], 10)})
    t = _jtile("trial_spawner", spawn_data=nbt.CompoundTag({"entity": nbt.CompoundTag({"id": nbt.StringTag("minecraft:husk")})}),
               normal_config=config, next_mob_spawns_at=nbt.LongTag(5))
    b, back = _round(t)
    assert b["spawn_data"]["TypeId"].py_data == "minecraft:husk" and int(b["normal_config"]["spawn_range"].py_data) == 5
    assert b["normal_config"]["loot_tables_to_eject"][0]["data"].py_data == "loot_tables/spawners/trial_chamber/key.json"
    assert back["spawn_data"]["entity"]["id"].py_data == "minecraft:husk" and int(back["next_mob_spawns_at"].py_data) == 5
    assert back["normal_config"]["loot_tables_to_eject"][0]["data"].py_data == "minecraft:spawners/trial_chamber/key"
    # a configuration named by a data pack is only written to the games that read it; Bedrock gets the defaults
    named = _jtile("trial_spawner", normal_config=nbt.StringTag("minecraft:trial_chamber/melee/zombie/normal"))
    c = tiles.from_java_modern(named)
    assert "normal_config" in tiles.to_java_modern(c, 4556) and "normal_config" not in tiles.to_java_modern(c, JAVA_NEW)
    assert float(tiles.to_bedrock(c, BEDROCK_NEW)["total_mobs"].py_data) == 6.0
    assert tiles.to_java_modern(c, JAVA_OLD) is None and tiles.to_bedrock(c, BEDROCK_OLD) is None


def test_jigsaw_blocks_keep_their_pool_and_target():
    t = _jtile("jigsaw", pool=nbt.StringTag("minecraft:village/plains/houses"), name=nbt.StringTag("minecraft:bottom"),
               target=nbt.StringTag("minecraft:building_entrance"), joint=nbt.StringTag("aligned"),
               final_state=nbt.StringTag("minecraft:stone"), placement_priority=nbt.IntTag(2))
    b, back = _round(t)
    assert b["id"].py_data == "JigsawBlock" and b["target_pool"].py_data == "minecraft:village/plains/houses" and "pool" not in b
    assert b["joint"].py_data == "aligned" and b["final_state"].py_data == "minecraft:stone"
    assert back["pool"].py_data == "minecraft:village/plains/houses" and back["target"].py_data == "minecraft:building_entrance"
    assert "placement_priority" not in back and int(tiles.to_java_modern(tiles.from_java_modern(t), JAVA_NEW)["placement_priority"].py_data) == 2


def test_golem_statue_pose_and_id_only_kinds():
    c = tiles.from_bedrock(nbt.CompoundTag({"id": nbt.StringTag("CopperGolemStatue"), "x": nbt.IntTag(1), "y": nbt.IntTag(2),
                                            "z": nbt.IntTag(3), "Pose": nbt.IntTag(3)}))
    assert c["pose"] == "star"
    b = tiles.to_bedrock(c, (1, 21, 110))
    assert int(b["Pose"].py_data) == 3 and b["Actor"]["ActorIdentifier"].py_data == "minecraft:copper_golem<>"
    assert tiles.to_java_modern(c, 4553)["id"].py_data == "minecraft:copper_golem_statue"
    assert tiles.to_java_modern(c, 4439) is None and tiles.to_bedrock(c, (1, 21, 100)) is None
    # nothing but the block entity itself (the games fill the rest in again)
    for kind, jv, bv in (("sculk_sensor", 2724, (1, 19, 0)), ("sculk_shrieker", 3104, (1, 19, 0)),
                         ("sculk_catalyst", 3104, (1, 19, 0)), ("calibrated_sculk_sensor", 3463, (1, 20, 0)),
                         ("creaking_heart", 4080, (1, 21, 50)), ("bell", 1952, (1, 11, 0)), ("conduit", 1519, (1, 5, 0))):
        c = {"kind": kind, "pos": (1, 2, 3)}
        assert tiles.to_java_modern(c, jv)["id"].py_data == "minecraft:" + kind and tiles.to_java_modern(c, jv - 1) is None, kind
        b = tiles.to_bedrock(c, bv)
        assert b is not None and tiles.to_bedrock(c, bv[:2] + (bv[2] - 1,) if bv[2] else (bv[0], bv[1] - 1, 99)) is None, kind
        assert tiles.from_bedrock(b)["kind"] == kind
        assert tiles.from_java_modern(tiles.to_java_modern(c, jv))["kind"] == kind
    assert tiles.to_bedrock({"kind": "bell", "pos": (0, 0, 0)}, BEDROCK_NEW)["Direction"].py_data == 255
    assert tiles.to_bedrock({"kind": "conduit", "pos": (0, 0, 0)}, BEDROCK_NEW)["Target"].py_data == -1
    # none of them exist in the legacy block entities of the hub
    assert all(tiles.to_legacy({"kind": k, "pos": (0, 0, 0)}) is None for k in tiles.MIN_VERSION if k != "hanging_sign")


def test_first_versions_are_not_before_the_blocks_exist():
    """A block entity is only written for the versions whose block list has the block (PyMCTranslate)."""
    from worldbridge.amulet_bridge import translation_manager

    tm = translation_manager()
    blocks = {"decorated_pot": "decorated_pot", "campfire": "campfire", "soul_campfire": "soul_campfire", "beehive": "beehive",
              "bee_nest": "bee_nest", "lectern": "lectern", "chiseled_bookshelf": "chiseled_bookshelf",
              "brushable_block": "suspicious_sand", "crafter": "crafter", "shelf": "oak_shelf", "bell": "bell",
              "conduit": "conduit", "sculk_sensor": "sculk_sensor", "calibrated_sculk_sensor": "calibrated_sculk_sensor",
              "sculk_catalyst": "sculk_catalyst", "sculk_shrieker": "sculk_shrieker", "trial_spawner": "trial_spawner",
              "vault": "vault", "creaking_heart": "creaking_heart", "copper_golem_statue": "copper_golem_statue",
              "jigsaw": "jigsaw", "lodestone": "lodestone", "hanging_sign": "oak_hanging_sign"}
    assert set(blocks) == set(tiles.MIN_VERSION) - {"test_block", "test_instance_block"}   # Java 1.21.5 only, no Bedrock block
    for platform, pos in (("java", 0), ("bedrock", 1)):
        versions = sorted(tuple(v) for v in tm.version_numbers(platform))
        for kind, block in blocks.items():
            first = next(v for v in versions if block in tm.get_version(platform, v).block.base_names("minecraft"))
            have = tiles.MIN_VERSION[kind][pos]
            if platform == "java":
                assert have >= tm.get_version("java", first).data_version, (kind, first)
            else:
                assert have >= first, (kind, first)


def _blocks_chunk(names, dv=3465):
    """A 1.13+ chunk (section Y=4) with the blocks (name, properties, (x, y, z) in the section's chunk) and stone elsewhere."""
    palette = [("minecraft:stone", None)] + [(n, p) for n, p, _pos in names]
    fill = np.zeros(4096, np.int64)
    for i, (_n, _p, (x, y, z)) in enumerate(names, 1):
        fill[_at(x, y, z)] = i
    return _chunk(dv, palette, fill)


def test_bedrock_kinds_follow_the_block_of_the_java_chunk():
    root = _blocks_chunk([("minecraft:trapped_chest", None, (3, 70, 5)), ("minecraft:soul_campfire", None, (4, 70, 5)),
                          ("minecraft:bee_nest", None, (5, 70, 5)), ("minecraft:campfire", None, (6, 70, 5))])
    canon = [{"kind": k, "pos": (32 + x, 70, -11)} for k, x in (("chest", 3), ("campfire", 4), ("beehive", 5), ("campfire", 6))]
    assert modern.blocks_at(root, [c["pos"] for c in canon])[(35, 70, -11)] == "trapped_chest"
    assert modern.resolve_kinds(root, canon) == 3
    assert [c["kind"] for c in canon] == ["trapped_chest", "soul_campfire", "bee_nest", "campfire"]
    assert tiles.to_java_modern(canon[0], 3465)["id"].py_data == "minecraft:trapped_chest"
    assert tiles.to_java_modern(canon[1], 3465)["id"].py_data == "minecraft:campfire"   # no soul_campfire type in the registry
    other = [{"kind": "mob_spawner", "pos": (35, 70, -11)}, {"kind": "chest", "pos": (40, 70, -11)}]   # not shared / no such block
    assert modern.resolve_kinds(root, other) == 0 and other[1]["kind"] == "chest"


def test_block_states_follow_the_block_entities_that_were_read_from_bedrock():
    for dv in (1976, 3465):
        names = [("minecraft:lectern", {"facing": nbt.StringTag("north"), "has_book": nbt.StringTag("false")}, (1, 70, 1)),
                 ("minecraft:chiseled_bookshelf", {"slot_0_occupied": nbt.StringTag("false"), "slot_3_occupied": nbt.StringTag("false")}, (2, 70, 1)),
                 ("minecraft:suspicious_sand", {"dusted": nbt.StringTag("0")}, (3, 70, 1)),
                 ("minecraft:waxed_oxidized_copper_golem_statue", {"copper_golem_pose": nbt.StringTag("standing")}, (4, 70, 1)),
                 ("minecraft:jukebox", {"has_record": nbt.StringTag("false")}, (5, 70, 1))]
        root = _blocks_chunk(names, dv)
        book = {"name": "writable_book", "count": 1, "damage": 0, "slot": None}
        canon = [{"kind": "lectern", "pos": (33, 70, -15), "book": book},
                 {"kind": "chiseled_bookshelf", "pos": (34, 70, -15), "slots": [{"name": "book", "count": 1, "slot": 3}]},
                 {"kind": "brushable_block", "pos": (35, 70, -15), "dusted": 3},
                 {"kind": "copper_golem_statue", "pos": (36, 70, -15), "pose": "star"},
                 {"kind": "jukebox", "pos": (37, 70, -15), "record": book}]
        assert modern.apply_state_tiles(root, canon) == 5
        sec = (root["sections"] if dv >= 2860 else root["Level"]["Sections"])[0]
        palette = sec["block_states"]["palette"] if dv >= 2860 else sec["Palette"]
        props = {str(nbt.get(p, "Name")): nbt.get_tag(p, "Properties") for p in palette}
        assert str(props["minecraft:lectern"]["has_book"].py_data) == "true"
        assert str(props["minecraft:chiseled_bookshelf"]["slot_3_occupied"].py_data) == "true"
        assert str(props["minecraft:suspicious_sand"]["dusted"].py_data) == "3"
        assert str(props["minecraft:waxed_oxidized_copper_golem_statue"]["copper_golem_pose"].py_data) == "star"
        assert str(props["minecraft:jukebox"]["has_record"].py_data) == "true"


def test_state_tiles_complete_the_block_entities_of_brushable_blocks_and_statues():
    names = [("minecraft:suspicious_gravel", {"dusted": nbt.StringTag("2")}, (3, 70, 5)),
             ("minecraft:copper_golem_statue", {"copper_golem_pose": nbt.StringTag("running")}, (4, 70, 5)),
             ("minecraft:suspicious_sand", {"dusted": nbt.StringTag("1")}, (5, 70, 5))]        # no block entity of its own
    root = _blocks_chunk(names)
    states = modern.state_tiles(root, 2, -1)
    assert {t["kind"] for t in states} == {"brushable_block", "copper_golem_statue"} and all(t["merge"] for t in states)
    te = [_jtile("brushable_block", 35, 70, -11, item=_jstack("brick")), _jtile("sign", 1, 2, 3)]
    out = modern.merge_state_tiles(te, states)
    merged = {tuple(c["pos"]): c for c in out if isinstance(c, dict)}
    assert len(out) == 4 and out[1] is te[1] and not any("merge" in c for c in merged.values())
    gravel = merged[(35, 70, -11)]
    assert gravel["block"] == "suspicious_gravel" and gravel["dusted"] == 2 and gravel["item"]["name"] == "brick"
    assert merged[(36, 70, -11)]["pose"] == "running" and merged[(37, 70, -11)]["block"] == "suspicious_sand"
    assert tiles.to_bedrock(gravel, BEDROCK_NEW)["type"].py_data == "minecraft:suspicious_gravel"
    assert tiles.to_bedrock(merged[(36, 70, -11)], (1, 21, 110))["Pose"].py_data == 2


# ------------------------------------------------------------------ structure / piston / lodestone / cauldron / command block
def test_structure_blocks_go_round_between_java_bedrock_and_the_legacy_hub():
    j = _jtile("structure_block", name=nbt.StringTag("a:b"), author=nbt.StringTag("me"), metadata=nbt.StringTag("m"),
               posX=nbt.IntTag(1), posY=nbt.IntTag(-2), posZ=nbt.IntTag(3), sizeX=nbt.IntTag(4), sizeY=nbt.IntTag(5),
               sizeZ=nbt.IntTag(6), mode=nbt.StringTag("SAVE"), rotation=nbt.StringTag("CLOCKWISE_90"),
               mirror=nbt.StringTag("LEFT_RIGHT"), ignoreEntities=nbt.ByteTag(0), powered=nbt.ByteTag(1),
               showair=nbt.ByteTag(1), showboundingbox=nbt.ByteTag(0), integrity=nbt.FloatTag(0.5), seed=nbt.LongTag(77))
    c = tiles.from_java_modern(j)
    assert c["kind"] == "structure_block" and c["mode"] == "SAVE" and c["rotation"] == 1 and c["mirror"] == 1
    b = tiles.to_bedrock(c, BEDROCK_NEW)
    assert b["id"].py_data == "StructureBlock" and b["structureName"].py_data == "a:b" and b["data"].py_data == 1
    assert (b["xStructureOffset"].py_data, b["yStructureOffset"].py_data, b["zStructureOffset"].py_data) == (1, -2, 3)
    assert (b["xStructureSize"].py_data, b["yStructureSize"].py_data, b["zStructureSize"].py_data) == (4, 5, 6)
    assert b["rotation"].py_data == 1 and b["mirror"].py_data == 1 and b["integrity"].py_data == 0.5 and b["seed"].py_data == 77
    back = tiles.to_java_modern(tiles.from_bedrock(b), JAVA_NEW)
    for key in ("name", "author", "mode", "rotation", "mirror", "posX", "posY", "posZ", "sizeX", "sizeY", "sizeZ", "powered",
                "ignoreEntities", "integrity", "seed"):
        assert key in back, key
    assert back["name"].py_data == "a:b" and back["mode"].py_data == "SAVE" and back["rotation"].py_data == "CLOCKWISE_90"
    assert (back["sizeX"].py_data, back["posY"].py_data, back["seed"].py_data) == (4, -2, 77)
    leg = tiles.to_legacy(c)
    assert leg["id"].py_data == "Structure" and tiles.from_legacy(leg)["mode"] == "SAVE" and leg["sizeZ"].py_data == 6


def test_every_java_piston_gets_a_piston_arm_in_bedrock_and_none_comes_back():
    root = _blocks_chunk([("minecraft:piston", {"extended": nbt.StringTag("false"), "facing": nbt.StringTag("up")}, (1, 70, 1)),
                          ("minecraft:sticky_piston", {"extended": nbt.StringTag("true"), "facing": nbt.StringTag("up")}, (2, 70, 1)),
                          ("minecraft:lodestone", None, (3, 70, 1)), ("minecraft:water_cauldron", None, (4, 70, 1))])
    states = {t["kind"] + str(t.get("sticky", "")): t for t in modern.state_tiles(root, 0, 0)}
    assert set(states) == {"piston_armFalse", "piston_armTrue", "lodestone", "cauldron"}
    plain, sticky = states["piston_armFalse"], states["piston_armTrue"]
    assert not plain["extended"] and sticky["extended"]
    bp, bs = tiles.to_bedrock(plain, BEDROCK_NEW), tiles.to_bedrock(sticky, BEDROCK_NEW)
    assert bp["id"].py_data == "PistonArm" and bp["State"].py_data == 0 and bp["Sticky"].py_data == 0
    assert bs["State"].py_data == 2 and bs["Sticky"].py_data == 1 and bs["Progress"].py_data == 1.0
    assert tiles.to_bedrock(states["lodestone"], BEDROCK_NEW)["id"].py_data == "Lodestone"
    assert tiles.to_bedrock(states["cauldron"], BEDROCK_NEW)["id"].py_data == "Cauldron"
    # back to Java: a piston at rest (and the lodestone, the empty cauldron) is just its block: dropped, not reported
    tally = nc.Tally()
    for b in (bp, bs):
        canon = tiles.read_canon([b], "bedrock")
        assert canon[0]["kind"] == "piston_arm" and tiles.write_list(canon, "java", tally, data_version=JAVA_NEW) == []
    assert tiles.write_list(tiles.read_canon([tiles.to_bedrock(states["lodestone"], BEDROCK_NEW)], "bedrock"), "java", tally,
                            data_version=JAVA_NEW) == []
    assert not tally and not tally.tile_ids
    # an arm in motion cannot be represented: counted
    moving = tiles.from_bedrock(bp)
    moving["state"] = 1
    assert tiles.write_list([moving], "java", tally, data_version=JAVA_NEW) == [] and tally.tile_ids == {"PistonArm": 1}
    # the moving piston block of Java and of the legacy games
    mj = tiles.from_java_modern(_jtile("piston", blockState=nbt.CompoundTag({"Name": nbt.StringTag("minecraft:stone")}),
                                       facing=nbt.IntTag(1), progress=nbt.FloatTag(0.5), extending=nbt.ByteTag(1),
                                       source=nbt.ByteTag(0)))
    assert mj["kind"] == "moving_piston"
    leg = tiles.to_legacy(mj)
    assert leg["id"].py_data == "Piston" and leg["blockId"].py_data == 1 and leg["progress"].py_data == 0.5
    assert tiles.to_java_modern(tiles.from_legacy(leg), JAVA_NEW)["blockState"]["Name"].py_data == "minecraft:stone"


def test_lodestone_and_cauldron_of_bedrock_and_the_lce_cauldron():
    lode = tiles.from_bedrock(nbt.CompoundTag({"id": nbt.StringTag("Lodestone"), "x": nbt.IntTag(1), "y": nbt.IntTag(2),
                                               "z": nbt.IntTag(3), "trackingHandle": nbt.IntTag(9)}))
    assert lode["kind"] == "lodestone" and tiles.to_bedrock(lode, BEDROCK_NEW)["trackingHandle"].py_data == 9
    assert tiles.to_java_modern(lode, JAVA_NEW) is None and tiles.to_legacy(lode) is None
    caul = tiles.from_bedrock(nbt.CompoundTag({"id": nbt.StringTag("Cauldron"), "x": nbt.IntTag(1), "y": nbt.IntTag(2),
                                               "z": nbt.IntTag(3), "PotionId": nbt.ShortTag(8), "PotionType": nbt.ShortTag(0),
                                               "CustomColor": nbt.IntTag(-65536), "Items": nbt.ListTag([], 10)}))
    assert caul["kind"] == "cauldron" and caul["potion_id"] == 8 and caul["color"] == -65536
    b = tiles.to_bedrock(caul, BEDROCK_NEW)
    assert (b["PotionId"].py_data, b["PotionType"].py_data, b["CustomColor"].py_data) == (8, 0, -65536)
    # Java and the hub have no such block entity: the potion / dyed water are counted, plain water is not
    tally = nc.Tally()
    assert tiles.write_list([caul, {"kind": "cauldron", "pos": (0, 0, 0)}], "java", tally, data_version=JAVA_NEW) == []
    assert tally.tile_ids == {"Cauldron": 1} and tally.tiles == 1
    # LCE (PS4 / Xbox One): "minecraft:cauldron"; the legacy "Cauldron" stays the brewing stand
    lce = nbt.CompoundTag({"id": nbt.StringTag("minecraft:cauldron"), "x": nbt.IntTag(-222), "y": nbt.IntTag(66),
                           "z": nbt.IntTag(260), "Items": nbt.ListTag([], 10), "PotionId": nbt.StringTag(""),
                           "PotionType": nbt.ShortTag(-32640)})
    c = tiles.from_legacy(lce)
    assert c["kind"] == "cauldron" and c["pos"] == (-222, 66, 260) and c["potion_type"] == -32640
    assert tiles.loss_name(c, "legacy") is None
    c["potion_id"] = "minecraft:healing"
    assert tiles.loss_name(c, "legacy") == "Cauldron"
    brewing = tiles.from_legacy(nbt.CompoundTag({"id": nbt.StringTag("Cauldron"), "x": nbt.IntTag(0), "y": nbt.IntTag(0),
                                                 "z": nbt.IntTag(0), "Items": nbt.ListTag([], 10)}))
    assert brewing["kind"] == "brewing_stand"


def test_command_blocks_keep_all_their_state_between_java_and_bedrock():
    j = _jtile("command_block", Command=nbt.StringTag("say hi"), CustomName=nbt.StringTag("Bob"), auto=nbt.ByteTag(1),
               powered=nbt.ByteTag(1), conditionMet=nbt.ByteTag(1), TrackOutput=nbt.ByteTag(0), LastOutput=nbt.StringTag("out"),
               SuccessCount=nbt.IntTag(3), UpdateLastExecution=nbt.ByteTag(0), LastExecution=nbt.LongTag(123456))
    c = tiles.from_java_modern(j)
    assert c["auto"] and c["powered"] and c["condition_met"] and not c["track_output"] and c["success_count"] == 3
    b = tiles.to_bedrock(c, BEDROCK_NEW)
    assert b["Command"].py_data == "say hi" and b["CustomName"].py_data == "Bob" and b["auto"].py_data == 1
    assert b["conditionMet"].py_data == 1 and b["TrackOutput"].py_data == 0 and b["SuccessCount"].py_data == 3
    assert b["LastExecution"].py_data == 123456 and b["LastOutput"].py_data == "out"
    for key in ("Version", "TickDelay", "ExecuteOnFirstTick"):
        assert key in b, key
    b["TickDelay"] = nbt.IntTag(7)
    b["ExecuteOnFirstTick"] = nbt.ByteTag(1)
    b["LPCommandMode"], b["LPCondionalMode"], b["LPRedstoneMode"] = nbt.IntTag(2), nbt.IntTag(1), nbt.IntTag(1)
    cb = tiles.from_bedrock(b)
    assert cb["tick_delay"] == 7 and cb["execute_on_first_tick"] and cb["lp_command_mode"] == 2
    assert tiles.to_bedrock(cb, BEDROCK_NEW)["LPCommandMode"].py_data == 2
    back = tiles.to_java_modern(cb, JAVA_NEW)
    assert (back["Command"].py_data, back["auto"].py_data, back["conditionMet"].py_data, back["TrackOutput"].py_data) == ("say hi", 1, 1, 0)
    assert back["SuccessCount"].py_data == 3 and back["LastExecution"].py_data == 123456 and "UpdateLastExecution" in back
    leg = tiles.to_legacy(cb)
    assert leg["id"].py_data == "Control" and leg["auto"].py_data == 1 and tiles.from_legacy(leg)["success_count"] == 3


def test_test_blocks_exist_only_in_java_and_are_counted_elsewhere():
    j = _jtile("test_block", mode=nbt.StringTag("fail"), message=nbt.StringTag("boom"))
    c = tiles.from_java_modern(j)
    assert c["kind"] == "test_block"
    back = tiles.to_java_modern(c, 4400)
    assert back["mode"].py_data == "fail" and back["message"].py_data == "boom" and back["id"].py_data == "minecraft:test_block"
    tally = nc.Tally()
    ti = tiles.from_java_modern(_jtile("test_instance_block", test=nbt.StringTag("a:b")))
    assert tiles.write_list([c, ti], "bedrock", tally, version=BEDROCK_NEW) == []
    assert tiles.write_list([c], "legacy", tally) == []
    assert tiles.write_list([c], "java", tally, data_version=4324) == []                  # 1.21.4 has none either
    assert tally.tile_ids == {"test_block": 3, "test_instance_block": 1} and tally.tiles == 4


def test_unknown_block_entities_are_counted_per_id_and_warned_once():
    mod = nbt.CompoundTag({"id": nbt.StringTag("somemod:machine"), "x": nbt.IntTag(1), "y": nbt.IntTag(2), "z": nbt.IntTag(3)})
    bed = nbt.CompoundTag({"id": nbt.StringTag("FancyThing"), "x": nbt.IntTag(1), "y": nbt.IntTag(2), "z": nbt.IntTag(3)})
    chest = _jtile("chest")
    canon = tiles.read_canon([mod, mod, chest, {"kind": "sign", "pos": (0, 0, 0)}], "java")
    assert [c["kind"] for c in canon] == [tiles.UNKNOWN, tiles.UNKNOWN, "chest", "sign"]
    tally = nc.Tally()
    out = tiles.write_list(canon, "bedrock", tally, version=BEDROCK_NEW)
    assert [t["id"].py_data for t in out] == ["Chest", "Sign"] and tally.tile_ids == {"somemod:machine": 2}
    tiles.write_list(tiles.read_canon([bed], "bedrock"), "java", tally, data_version=JAVA_NEW)
    tiles.write_list(tiles.read_canon([bed, mod], "bedrock"), "legacy", tally)
    logs = Progress(None, lambda m: None)
    tally.warn(logs, "Java 1.21.5")
    assert len(logs.warnings) == 2
    assert logs.warnings[0].startswith("Content that does not exist in Java 1.21.5: removed 0 items, 0 entities and 5 block entities")
    assert logs.warnings[1] == "Block entities left out of Java 1.21.5: somemod:machine ×3, FancyThing ×2."


def test_lce_target_counts_the_block_entities_it_has_no_id_for():
    from collections import Counter

    from worldbridge.lce.world import sanitize_tiles

    blocks = np.zeros((256, 16, 16), np.uint16)
    blocks[70, 0, 0] = 54
    tl = [nbt.CompoundTag({"id": nbt.StringTag("Chest"), "x": nbt.IntTag(0), "y": nbt.IntTag(70), "z": nbt.IntTag(0)}),
          nbt.CompoundTag({"id": nbt.StringTag("somemod:box"), "x": nbt.IntTag(1), "y": nbt.IntTag(70), "z": nbt.IntTag(0)}),
          nbt.CompoundTag({"id": nbt.StringTag("minecraft:cauldron"), "x": nbt.IntTag(2), "y": nbt.IntTag(70), "z": nbt.IntTag(0),
                           "PotionId": nbt.StringTag("")})]
    lost = Counter()
    assert len(sanitize_tiles(tl, blocks, 0, 0, lce=True, lost=lost)) == 1 and lost == {"somemod:box": 1}


def test_a_command_block_whose_last_output_has_arrays_is_still_read():
    last = nbt.CompoundTag({"text": nbt.StringTag("x"), "color": nbt.IntArrayTag(np.array([1, 2, 3, 4], np.int32))})
    c = tiles.from_java_modern(_jtile("command_block", Command=nbt.StringTag("say hi"), LastOutput=last))
    assert c["kind"] == "command_block" and c["command"] == "say hi"
