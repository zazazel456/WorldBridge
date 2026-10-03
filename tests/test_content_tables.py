"""What each game version registers: status effects, map colours, biomes, blocks, and the item ids of
Bedrock before and after its 1.16.100 item flattening."""

import os

import numpy as np

from worldbridge import biomes, items, maps, nbt
from worldbridge import blocks as blk
from worldbridge.convert import TargetSpec
from worldbridge.items import Item
from worldbridge.java.oldcontent import OldContent
from worldbridge.model import Progress

from .helpers import SyntheticWorld


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
