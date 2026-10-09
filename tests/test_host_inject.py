"""The extras of a Bedrock world (villagers, pets) through ``inject_from_bedrock`` into a Java chunk."""
from __future__ import annotations

import os
import struct

from worldbridge import nbt, pets
from worldbridge.bedrock.extra import _db, bedrock_player_to_java
from worldbridge.java import modern
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import Progress

def test_the_players_tab_chooses_who_the_pets_belong_to():
    from PySide6 import QtWidgets

    from worldbridge.gui.players import PlayersTab

    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    tab = PlayersTab()
    assert tab.pet_owner() == "auto"
    tab.pet_owner_box.setCurrentIndex(tab.pet_owner_box.findData("first-player"))
    st = tab.export_state()
    assert st["pet_owner"] == "first-player"
    tab.set_players([])
    assert tab.pet_owner() == "first-player"
    tab.set_family("bedrock")
    assert tab.pet_row.isHidden()
    tab.set_family("java")
    assert not tab.pet_row.isHidden()


from .test_host_villagers import UNIQUE_ID, _bedrock_player, _bedrock_villager, _info


def test_bedrock_extras_reach_the_java_chunks(tmp_path):
    src = str(tmp_path / "be")
    os.makedirs(os.path.join(src, "db"))
    db = _db(src, create=True)
    villager = _bedrock_villager("cleric", tier=0, xp=0, uid=-100)
    villager["Pos"] = nbt.ListTag([nbt.FloatTag(2.5), nbt.FloatTag(70.0), nbt.FloatTag(2.5)], 5)
    wolf = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:wolf"), "IsTamed": nbt.ByteTag(1),
                            "OwnerNew": nbt.LongTag(UNIQUE_ID), "UniqueID": nbt.LongTag(-200),
                            "Pos": nbt.ListTag([nbt.FloatTag(3.5), nbt.FloatTag(70.0), nbt.FloatTag(3.5)], 5)})
    ids = b""
    for i, actor in enumerate((villager, wolf)):
        key = struct.pack(">q", -100 - i * 100)
        db.put(b"actorprefix" + key, nbt.dump(actor, "", little_endian=True, compressed=False))
        ids += key
    db.put(b"digp" + struct.pack("<ii", 0, 0), ids)
    poi = nbt.CompoundTag({"POI": nbt.ListTag([nbt.CompoundTag({"VillagerID": nbt.LongTag(-100), "instances": nbt.ListTag(
        [nbt.CompoundTag({"Type": nbt.IntTag(2), "X": nbt.IntTag(9), "Y": nbt.IntTag(70), "Z": nbt.IntTag(10)})], 10)})], 10)})
    db.put(b"VILLAGE_Overworld_x_POI", nbt.dump(poi, "", little_endian=True, compressed=False))
    db.close()

    out = tmp_path / "out"
    (out / "region").mkdir(parents=True)
    chunk = nbt.CompoundTag({"DataVersion": nbt.IntTag(5020), "xPos": nbt.IntTag(0), "zPos": nbt.IntTag(0),
                             "sections": nbt.ListTag([], 10), "block_entities": nbt.ListTag([], 10)})
    rw = RegionWriter(external=True)
    rw.put(0, 0, nbt.dump(chunk, ""))
    rw.write(str(out / "region" / "r.0.0.mca"))

    info = _info(bedrock_player_to_java(_bedrock_player()))
    prog = Progress()
    info.pet_plan = pets.plan_for("auto", info, 5023, prog)
    modern.inject_from_bedrock(src, str(out), info, prog, target_dv=5023)

    got = nbt.load(JavaRegion(str(out / "entities" / "r.0.0.mca")).read(0, 0), compressed=False).tag
    by_id = {nbt.get(e, "id"): e for e in got["Entities"]}
    v, w = by_id["minecraft:villager"], by_id["minecraft:wolf"]
    assert v["VillagerData"]["profession"] == "minecraft:cleric" and len(v["Offers"]["Recipes"]) == 2
    assert [int(x) for x in v["Brain"]["memories"]["minecraft:job_site"]["value"]["pos"]] == [9, 70, 10]
    assert [str(t) for t in w["Tags"]] == ["worldbridge_host_pet"] and info.pet_plan.tagged == 1
