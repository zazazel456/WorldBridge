"""Java Alpha / Beta / McRegion output: readable by the old game (NBT types, fields, content)."""
import os

import numpy as np

from worldbridge import entities as ent
from worldbridge import nbt
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.java.oldcontent import OldContent
from worldbridge.model import Progress
from worldbridge.java.region import JavaRegion

from .helpers import SyntheticWorld
from .strict_old_nbt import load as strict_load

TYPE = {"byte": 1, "short": 2, "int": 3, "long": 4, "float": 5, "double": 6, "string": 8, "list": 9, "compound": 10}


def _modern_source():
    """A synthetic world carrying what a Java 26.x / LCE source brings along."""
    src = SyntheticWorld(radius=2)
    uuid = nbt.IntArrayTag(np.array([1, 2, 3, 4], np.int32))
    src.info.level.pop("SpawnX"), src.info.level.pop("SpawnY"), src.info.level.pop("SpawnZ")
    src.info.level["spawn"] = nbt.CompoundTag({"pos": nbt.IntArrayTag(np.array([100, 70, -50], np.int32)),
                                               "dimension": nbt.StringTag("minecraft:overworld")})
    src.info.players["host"] = nbt.CompoundTag({
        "DataVersion": nbt.IntTag(5023), "UUID": uuid, "Health": nbt.FloatTag(9.5),
        "fall_distance": nbt.DoubleTag(0.0), "Dimension": nbt.StringTag("minecraft:overworld"),
        "Pos": nbt.ListTag([nbt.DoubleTag(8.5), nbt.DoubleTag(65.0), nbt.DoubleTag(8.5)], 6),
        "Rotation": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(0)], 5),
        "recipeBook": nbt.CompoundTag({"recipes": nbt.ListTag([nbt.StringTag("minecraft:oak_boat")], 8)}),
        "warden_spawn_tracker": nbt.CompoundTag({"warning_level": nbt.IntTag(0)}),
        "Inventory": nbt.ListTag([
            nbt.CompoundTag({"id": nbt.StringTag("minecraft:diamond_sword"), "count": nbt.IntTag(1), "Slot": nbt.ByteTag(0)}),
            nbt.CompoundTag({"id": nbt.StringTag("minecraft:cooked_beef"), "count": nbt.IntTag(3), "Slot": nbt.ByteTag(1)}),
            nbt.CompoundTag({"id": nbt.StringTag("minecraft:cake"), "count": nbt.IntTag(1), "Slot": nbt.ByteTag(2)}),
            nbt.CompoundTag({"id": nbt.StringTag("minecraft:shield"), "count": nbt.IntTag(1), "Slot": nbt.ByteTag(-106)}),
        ], 10),
    })
    chunk = src.read_chunk

    def read_chunk(dim, cx, cz):
        c = chunk(dim, cx, cz)
        if (cx, cz) == (0, 0):
            c.entities.append(nbt.CompoundTag({"id": nbt.StringTag("Wolf"), "UUID": uuid,
                                               "Pos": nbt.ListTag([nbt.DoubleTag(3.5), nbt.DoubleTag(65), nbt.DoubleTag(3.5)], 6),
                                               "Health": nbt.FloatTag(8.0)}))
            c.entities.append(nbt.CompoundTag({"id": nbt.StringTag("MinecartChest"), "Items": nbt.ListTag([], 10),
                                               "Pos": nbt.ListTag([nbt.DoubleTag(4.5), nbt.DoubleTag(65), nbt.DoubleTag(4.5)], 6)}))
            c.entities.append(nbt.CompoundTag({"id": nbt.StringTag("Item"), "Health": nbt.ShortTag(5),
                                               "Pos": nbt.ListTag([nbt.DoubleTag(5.5), nbt.DoubleTag(65), nbt.DoubleTag(5.5)], 6),
                                               "Item": nbt.CompoundTag({"id": nbt.ShortTag(395), "Count": nbt.ByteTag(1),
                                                                        "Damage": nbt.ShortTag(0)})}))
            c.blocks[70, 1, 1] = 138  # beacon (1.4)
            c.tile_entities.append(nbt.CompoundTag({"id": nbt.StringTag("Beacon"), "x": nbt.IntTag(1),
                                                    "y": nbt.IntTag(70), "z": nbt.IntTag(1)}))
            c.tile_entities[0]["Items"].append(nbt.CompoundTag({"id": nbt.ShortTag(364), "Count": nbt.ByteTag(2),
                                                               "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(1)}))
        return c

    src.read_chunk = read_chunk
    return src


def _run(tmp_path, src, name, kind, limit):
    out = tmp_path / name
    w = JavaNumericWriter(str(out), JavaWriteOptions(kind=kind, version_limit=limit), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    return out


def _alpha_chunks(world):
    for root, _dirs, files in os.walk(world):
        for f in files:
            if f.startswith("c.") and f.endswith(".dat"):
                yield strict_load(open(os.path.join(root, f), "rb").read())


def test_beta12_level_dat_is_readable_by_the_old_game(tmp_path):
    out = _run(tmp_path, _modern_source(), "World1", "alpha", "b1.2")
    data = strict_load((out / "level.dat").read_bytes())["Data"][1]  # raises on TAG_Int_Array & co.
    assert data["RandomSeed"] == (TYPE["long"], 12345)
    assert [data[k][1] for k in ("SpawnX", "SpawnY", "SpawnZ")] == [100, 70, -50]  # Java 1.21.9+ spawn: {pos}
    assert data["SizeOnDisk"][0] == TYPE["long"] and data["SizeOnDisk"][1] > 0
    assert "version" not in data and "LevelName" not in data  # Beta 1.3 fields
    p = data["Player"][1]
    assert p["Health"] == (TYPE["short"], 10) and p["FallDistance"][0] == TYPE["float"]
    assert p["Dimension"] == (TYPE["int"], 0)
    assert not {"UUID", "recipeBook", "warden_spawn_tracker", "DataVersion", "fall_distance", "foodLevel"} & set(p)
    inv = {it["id"][1]: it for _t, it in p["Inventory"][1]}
    assert set(inv) == {276, 354}  # beef (Beta 1.8) and the off-hand shield are gone, cake exists since Beta 1.2
    assert inv[276]["Count"][0] == TYPE["byte"] and inv[276]["Damage"][0] == TYPE["short"]


def test_old_chunks_only_hold_content_of_the_version(tmp_path):
    out = _run(tmp_path, _modern_source(), "World2", "alpha", "alpha")
    ents, tiles, items = set(), set(), set()
    for d in _alpha_chunks(out):
        lvl = d["Level"][1]
        assert "TileTicks" not in lvl
        for _t, e in lvl["Entities"][1]:
            ents.add(e["id"][1])
            if e["id"][1] == "Minecart":
                assert e["Type"] == (TYPE["int"], 1)
            assert e["Pos"][0] == TYPE["list"] and e["Rotation"][1][0][0] == TYPE["float"]
        for _t, te in lvl["TileEntities"][1]:
            tiles.add(te["id"][1])
            items |= {it["id"][1] for _t2, it in te.get("Items", (9, []))[1]}
    assert "Wolf" not in ents and "Item" not in ents  # wolves: Beta 1.4; the dropped item is a map (1.4)
    assert {"Pig", "Minecart"} <= ents
    assert tiles == {"Chest"} and items == {264}  # Beacon (1.4) and steak (Beta 1.8) removed


def test_mcregion_beta13(tmp_path):
    out = _run(tmp_path, _modern_source(), "b13", "mcregion", "b1.3")
    data = strict_load((out / "level.dat").read_bytes())["Data"][1]
    assert data["version"] == (TYPE["int"], 19132) and data["LevelName"][0] == TYPE["string"]
    assert data["Player"][1]["Sleeping"] == (TYPE["byte"], 0)
    region = JavaRegion(str(out / "region" / "r.0.0.mcr"))
    for lx, lz in region.chunks():
        strict_load(region.read(lx, lz), gz=False)


def test_old_content_player_fields_per_version():
    p = _modern_source().info.players["host"]
    from worldbridge.lce.world import legacy_items

    p["Inventory"] = legacy_items(p["Inventory"])
    b18 = OldContent("b1.8").player(p)
    assert b18["foodLevel"].py_data == 20 and "abilities" not in b18
    j16 = OldContent("1.6").player(p)
    assert isinstance(j16["HealF"], nbt.FloatTag) and "EnderItems" in j16 and "abilities" in j16
    assert 364 in {int(it["id"].py_data) for it in j16["Inventory"]}


def test_painting_layouts():
    # Java 1.8+ (hub): the block in front of the wall; Java <= 1.7 / LCE: the wall block
    modern = nbt.CompoundTag({"id": nbt.StringTag("Painting"), "Motive": nbt.StringTag("Skeleton"),
                              "Pos": nbt.ListTag([nbt.DoubleTag(-68.96875), nbt.DoubleTag(101.5), nbt.DoubleTag(-285.0)], 6),
                              "Rotation": nbt.ListTag([nbt.FloatTag(270.0), nbt.FloatTag(0)], 5),
                              "TileX": nbt.IntTag(-69), "TileY": nbt.IntTag(101), "TileZ": nbt.IntTag(-285),
                              "Facing": nbt.ByteTag(3)})
    old = ent.hanging_to_old(nbt.copy(modern))
    assert (old["TileX"].py_data, old["Direction"].py_data, old["Dir"].py_data) == (-70, 3, 3) and "Facing" not in old
    back = ent.hanging_to_modern(nbt.copy(old))
    assert (back["TileX"].py_data, back["TileZ"].py_data, back["Facing"].py_data) == (-69, -285, 3)
    # TileX/Y/Z lost (left at 0 0 0): rebuilt from the position and the rotation
    broken = nbt.copy(modern)
    for k in ("TileX", "TileY", "TileZ"):
        broken[k] = nbt.IntTag(0)
    broken["Facing"] = nbt.ByteTag(0)
    fixed = ent.hanging_to_modern(broken)
    assert [fixed[k].py_data for k in ("TileX", "TileY", "TileZ", "Facing")] == [-69, 101, -285, 3]
    # Java 1.21+ source: block_pos + lower-case facing
    j121 = nbt.CompoundTag({"id": nbt.StringTag("minecraft:painting"), "variant": nbt.StringTag("minecraft:sea"),
                            "Pos": modern["Pos"], "Rotation": modern["Rotation"], "facing": nbt.ByteTag(3),
                            "block_pos": nbt.IntArrayTag(np.array([-69, 84, -319], np.int32))})
    c = ent.from_java_modern(j121)
    assert c["tile"] == (-69, 84, -319) and c["facing"] == 3 and c["motive"] == "Sea"
