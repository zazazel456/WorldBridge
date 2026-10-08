"""Java 26.x has no bed block entity (found with a real 26.3 server: its block entity registry lists 49 types and no
``minecraft:bed``, schema 4885 removes it, and the data fixer silently drops the old ones): the colour was always in
the block.  WorldBridge must not write it for such a target (chunks written in the older blending format included, the
game upgrades them), must not count it as lost, and must still give the older games / Bedrock the colour from the block."""
from __future__ import annotations

import os

from worldbridge import nbt, newcontent, tiles
from worldbridge.java import modern
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import OVERWORLD, Progress

DV_1_21_5 = 4325
DV_26_3 = 5023


def _bed(pos=(1, 70, 2), color=14):
    return {"kind": "bed", "pos": pos, "color": color}


def test_bed_block_entity_is_gone_from_data_version_4885():
    assert tiles.exists_in_java("bed", 4884) and not tiles.exists_in_java("bed", 4885)
    assert tiles.exists_in_java("bed", 1343) and tiles.exists_in_java("bed", DV_1_21_5)
    assert not tiles.exists_in_java("bed", DV_26_3)
    # chunks written in the blending format (1.17) that the 26.3 game upgrades
    assert not tiles.exists_in_java("bed", 2724, DV_26_3) and tiles.exists_in_java("bed", 2724, DV_1_21_5)
    assert tiles.exists_in_bedrock("bed", (1, 21, 0)) and tiles.exists_in_bedrock("bed", (26, 50, 0))


def test_other_block_entities_are_not_removed():
    for kind in ("chest", "sign", "banner", "skull", "mob_spawner", "piston"):
        assert not tiles.removed_in_java(kind, DV_26_3), kind


def test_bed_is_written_up_to_1_21_5_and_not_after():
    for dv, target in ((DV_1_21_5, None), (2724, DV_1_21_5), (1343, None)):
        t = tiles.to_java_modern(_bed(), dv, target)
        assert t is not None and nbt.get(t, "id") == "minecraft:bed", (dv, target)
    for dv, target in ((DV_26_3, None), (2724, DV_26_3), (4885, None)):
        assert tiles.to_java_modern(_bed(), dv, target) is None, (dv, target)


def test_a_removed_block_entity_is_not_a_loss():
    tally = newcontent.Tally()
    assert tiles.write_list([_bed()], "java", tally, data_version=2724, target_dv=DV_26_3) == []
    assert tiles.write_list([_bed()], "java", tally, data_version=DV_26_3) == []
    assert not tally and not tally.tile_ids
    out = tiles.write_list([_bed()], "java", tally, data_version=2724, target_dv=DV_1_21_5)
    assert len(out) == 1
    # a block entity the target lacks without being removed is still counted
    assert tiles.write_list([{"kind": "campfire", "pos": (0, 70, 0)}], "java", tally, data_version=1343) == []
    assert tally.tile_ids == {"campfire": 1}


def test_the_colour_comes_from_the_bed_block():
    red = modern._state_tile("minecraft:red_bed", nbt.CompoundTag({"part": nbt.StringTag("head")}))
    assert red == {"kind": "bed", "color": 14, "merge": True}
    assert modern._state_tile("minecraft:white_bed", None)["color"] == 0
    assert modern._state_tile("minecraft:black_bed", None)["color"] == 15
    assert modern._state_tile("minecraft:bed_rock", None) is None


def test_state_tile_completes_or_replaces_the_block_entity():
    te = nbt.CompoundTag({"id": nbt.StringTag("minecraft:bed"), "x": nbt.IntTag(1), "y": nbt.IntTag(70), "z": nbt.IntTag(2)})
    state = {"kind": "bed", "color": 11, "merge": True, "pos": (1, 70, 2)}
    merged = modern.merge_state_tiles([te], [state])
    assert len(merged) == 1 and merged[0]["kind"] == "bed" and merged[0]["color"] == 11
    only = modern.merge_state_tiles([], [state])                      # a 26.x chunk: no block entity at all
    assert len(only) == 1 and only[0]["color"] == 11 and "merge" not in only[0]


def _world(tmp_path):
    region = tmp_path / "w" / "region"
    region.mkdir(parents=True)
    root = nbt.CompoundTag({"DataVersion": nbt.IntTag(2724),
                            "Level": nbt.CompoundTag({"xPos": nbt.IntTag(0), "zPos": nbt.IntTag(0),
                                                      "TileEntities": nbt.ListTag([], 10)})})
    rw = RegionWriter(external=True)
    rw.put(0, 0, nbt.dump(root, ""))
    rw.write(str(region / "r.0.0.mca"))
    return str(tmp_path / "w")


def _ids(world):
    reg = JavaRegion(os.path.join(world, "region", "r.0.0.mca"))
    root = nbt.load(reg.read(0, 0), compressed=False).tag
    return sorted(nbt.get(t, "id") for t in nbt.get_tag(nbt.get_tag(root, "Level"), "TileEntities"))


def test_inject_canon_leaves_the_bed_out_of_a_26_target(tmp_path):
    canon = {(OVERWORLD, 0, 0): ([_bed(), {"kind": "chest", "pos": (3, 70, 3), "items": []}], [])}
    for target_dv, expect in ((DV_26_3, ["minecraft:chest"]), (DV_1_21_5, ["minecraft:bed", "minecraft:chest"])):
        sub = tmp_path / str(target_dv)
        sub.mkdir()
        w = _world(sub)
        progress = Progress()
        modern.inject_canon(w, canon, progress, target_dv)
        assert _ids(w) == expect, target_dv
        assert not newcontent.tally_of(progress).tile_ids, target_dv


def test_amulets_own_bed_copies_go_too(tmp_path):
    """The conversion from an old Java world: Amulet translates the bed block entities itself, the canonical list
    may not hold them (found with a real 26.3 server: 12 beds written, 0 left after the data fixer)."""
    w = _world(tmp_path)
    p = os.path.join(w, "region", "r.0.0.mca")
    reg = JavaRegion(p)
    root = nbt.load(reg.read(0, 0), compressed=False).tag
    lvl = nbt.get_tag(root, "Level")
    lvl["TileEntities"] = nbt.compound_list([nbt.CompoundTag({"id": nbt.StringTag("minecraft:bed"), "x": nbt.IntTag(9),
                                                              "y": nbt.IntTag(70), "z": nbt.IntTag(9)})])
    rw = RegionWriter(external=True)
    rw.put(0, 0, nbt.dump(root, ""))
    rw.write(p)
    canon = {(OVERWORLD, 0, 0): ([{"kind": "chest", "pos": (3, 70, 3), "items": []}], [])}
    modern.inject_canon(w, canon, Progress(), DV_26_3)
    assert _ids(w) == ["minecraft:chest"]


# minecraft:block_entity_type of a 26.3 server (``java -DbundlerMainClass=net.minecraft.data.Main -jar server.jar
# --reports``, reports/registries.json): 49 types.  1.21.5 has the same minus copper_golem_statue / potent_sulfur / shelf
# and plus bed.
REGISTRY_26_3 = frozenset("""banner barrel beacon beehive bell blast_furnace brewing_stand brushable_block
calibrated_sculk_sensor campfire chest chiseled_bookshelf command_block comparator conduit copper_golem_statue crafter
creaking_heart daylight_detector decorated_pot dispenser dropper enchanting_table end_gateway end_portal ender_chest
furnace hanging_sign hopper jigsaw jukebox lectern mob_spawner piston potent_sulfur sculk_catalyst sculk_sensor
sculk_shrieker shelf shulker_box sign skull smoker structure_block test_block test_instance_block trapped_chest
trial_spawner vault""".split())


def test_every_block_entity_id_written_exists_in_the_26_3_registry():
    assert len(REGISTRY_26_3) == 49 and "bed" not in REGISTRY_26_3
    for kind, (_legacy, jid, _bedrock) in tiles.KINDS.items():
        jid = tiles.JAVA_ID_OF_KIND.get(kind, jid)
        if jid and tiles.exists_in_java(kind, DV_26_3):
            assert jid in REGISTRY_26_3, (kind, jid)


def test_soul_campfire_bee_nest_and_spawner_use_the_registry_ids():
    for dv in (2724, DV_1_21_5, DV_26_3):
        for kind, want in (("soul_campfire", "campfire"), ("bee_nest", "beehive"), ("mob_spawner", "mob_spawner")):
            t = tiles.to_java_modern({"kind": kind, "pos": (0, 70, 0), "entity": "zombie"}, dv)
            assert t is not None and nbt.get(t, "id") == "minecraft:" + want, (dv, kind)
    # the kinds stay apart: the block says which one it is
    assert tiles.JAVA_TO_KIND["soul_campfire"] == "soul_campfire" and tiles.JAVA_TO_KIND["bee_nest"] == "bee_nest"
