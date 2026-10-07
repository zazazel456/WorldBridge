"""The ids an LCE save is written with: the TU54+ games (and PS3 / PS4 / Vita / Wii U v384+) name entities and
block entities the Java 1.11 way ("minecraft:donkey", "minecraft:chest"), every console from TU31 names its
items ("minecraft:egg"), neoLegacy (Windows64) and the older profiles keep the old entity ids."""
import numpy as np
import pytest

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.detect import detect
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter, read_entity_file
from worldbridge.model import OVERWORLD, NumericChunk, Progress

from .helpers import SyntheticWorld

T = nbt.CompoundTag


def _item(iid, slot=0, count=1, dmg=0):
    return T({"id": nbt.ShortTag(iid), "Count": nbt.ByteTag(count), "Damage": nbt.ShortTag(dmg),
              "Slot": nbt.ByteTag(slot)})


def _ent(eid, x=8.5, **extra):
    e = T({"id": nbt.StringTag(eid),
           "Pos": nbt.ListTag([nbt.DoubleTag(x), nbt.DoubleTag(65.0), nbt.DoubleTag(8.5)], 6),
           "Motion": nbt.ListTag([nbt.DoubleTag(0)] * 3, 6),
           "Rotation": nbt.ListTag([nbt.FloatTag(0)] * 2, 5)})
    for k, v in extra.items():
        e[k] = v
    return e


def _tile(tid, x, **extra):
    t = T({"id": nbt.StringTag(tid), "x": nbt.IntTag(x), "y": nbt.IntTag(64), "z": nbt.IntTag(2)})
    for k, v in extra.items():
        t[k] = v
    return t


def _chunk():
    c = NumericChunk(0, 0, 256)
    c.blocks[0] = 7
    c.blocks[1:63] = 1
    c.blocks[63] = 2
    for x, b in ((1, 54), (2, 130), (3, 52), (4, 140), (5, 84), (6, 117)):
        c.blocks[64, 2, x] = b
    c.biomes = np.full((16, 16), 1, np.uint8)
    c.tile_entities = [
        _tile("Chest", 1, Items=nbt.ListTag([_item(344, 0, 3), _item(264, 1)], 10)),
        _tile("EnderChest", 2),
        _tile("MobSpawner", 3, EntityId=nbt.StringTag("PigZombie"), Delay=nbt.ShortTag(20)),
        _tile("FlowerPot", 4, Item=nbt.IntTag(40), Data=nbt.IntTag(0)),
        _tile("RecordPlayer", 5, Record=nbt.IntTag(2256), RecordItem=_item(2256)),
        _tile("Cauldron", 6, Items=nbt.ListTag([_item(373, 0, 1, 8261)], 10)),
    ]
    trade = T({"sell": _item(264), "buy": _item(388, 0, 2), "maxUses": nbt.IntTag(7), "uses": nbt.IntTag(0)})
    c.entities = [
        _ent("Pig", 1.5),
        _ent("PigZombie", 2.5),
        _ent("EntityHorse", 3.5, Type=nbt.IntTag(1), ChestedHorse=nbt.ByteTag(1), SaddleItem=_item(329, 0, 1)),
        _ent("EntityHorse", 4.5, Type=nbt.IntTag(0), ArmorItem=_item(417, 0, 1)),
        _ent("EntityHorse", 5.5, Type=nbt.IntTag(4)),
        _ent("Skeleton", 6.5, SkeletonType=nbt.ByteTag(1), Equipment=nbt.ListTag([_item(261, 0)], 10)),
        _ent("Skeleton", 7.5, SkeletonType=nbt.ByteTag(0)),
        _ent("Zombie", 8.5, IsVillager=nbt.ByteTag(1), VillagerProfession=nbt.IntTag(2)),
        _ent("Guardian", 9.5, Elder=nbt.ByteTag(1)),
        _ent("Villager", 10.5, Profession=nbt.IntTag(1), Offers=T({"Recipes": nbt.ListTag([trade], 10)})),
        _ent("Item", 11.5, Item=_item(344, 0, 2)),
        _ent("Creeper", 12.5, Riding=_ent("Zombie", 12.5, Riding=_ent("EntityHorse", 12.5, Type=nbt.IntTag(2)))),
        _ent("MinecartChest", 13.5, Items=nbt.ListTag([_item(263, 3, 4)], 10)),
    ]
    return c


def _write(tmp_path, platform, profile, name=None, size=54):
    src = SyntheticWorld(radius=1)
    out = tmp_path / (name or f"{platform}_{profile}")
    w = LCEWriter(str(out), LCEWriteOptions(platform=platform, profile=profile, world_size=size), Progress())
    w.add_chunk(OVERWORLD, _chunk())
    w.finish(src.info)
    world = LCEWorld(str(out), None)
    return world, world.read_raw_chunk(OVERWORLD, 0, 0)


def _by_id(lst):
    out = {}
    for t in lst:
        out.setdefault(nbt.get(t, "id"), []).append(t)
    return out


def _item_ids(tag, found):
    """Every "id" of an item (a compound that has a Count) below ``tag``."""
    if isinstance(tag, nbt.CompoundTag):
        if "Count" in tag and "id" in tag:
            found.append(tag["id"])
        for v in tag.values():
            _item_ids(v, found)
    elif isinstance(tag, nbt.ListTag):
        for v in tag:
            _item_ids(v, found)
    return found


def _all_item_ids(ch):
    found = []
    for t in list(ch.entities) + list(ch.tile_entities):
        _item_ids(t, found)
    return found


def test_tu54_names_the_entities_and_block_entities(tmp_path):
    _world, ch = _write(tmp_path, "ps3", "tu54")
    ents = _by_id(ch.entities)
    for name in ("minecraft:pig", "minecraft:zombie_pigman", "minecraft:donkey", "minecraft:horse",
                 "minecraft:skeleton_horse", "minecraft:wither_skeleton", "minecraft:skeleton",
                 "minecraft:zombie_villager", "minecraft:elder_guardian", "minecraft:villager", "minecraft:item",
                 "minecraft:creeper", "minecraft:chest_minecart"):
        assert name in ents, (name, sorted(ents))
    assert not {"EntityHorse", "PigZombie", "Pig", "Item"} & set(ents)
    donkey = ents["minecraft:donkey"][0]
    assert "Type" not in donkey and nbt.get(donkey, "ChestedHorse") == 1
    assert nbt.get(donkey["SaddleItem"], "id") == "minecraft:saddle"
    assert "Type" not in ents["minecraft:horse"][0] and "Type" not in ents["minecraft:skeleton_horse"][0]
    assert "SkeletonType" not in ents["minecraft:wither_skeleton"][0]
    assert "SkeletonType" not in ents["minecraft:skeleton"][0]
    zv = ents["minecraft:zombie_villager"][0]                  # the profession stays (EntityZombieSplitFix)
    assert nbt.get(zv, "Profession") == 2 and "IsVillager" not in zv and "VillagerProfession" not in zv
    assert "Elder" not in ents["minecraft:elder_guardian"][0]
    tiles = _by_id(ch.tile_entities)
    assert set(tiles) == {"minecraft:chest", "minecraft:ender_Chest", "minecraft:mob_spawner",
                          "minecraft:flower_pot", "minecraft:jukebox", "minecraft:brewing_stand"}
    # the spawner as the game writes it: the mob in SpawnData / SpawnPotentials
    sp = tiles["minecraft:mob_spawner"][0]
    assert nbt.get(sp["SpawnData"], "id") == "minecraft:zombie_pigman" and "EntityId" not in sp
    assert nbt.get(sp["SpawnPotentials"][0]["Entity"], "id") == "minecraft:zombie_pigman"
    # the flower pot keeps the plant as a number, like the real saves
    assert isinstance(tiles["minecraft:flower_pot"][0]["Item"], nbt.IntTag)


def test_tu54_names_what_rides_an_entity(tmp_path):
    _world, ch = _write(tmp_path, "xbox360", "tu54")
    stack = _by_id(ch.entities)["minecraft:creeper"]
    assert len(stack) == 1
    rider = stack[0]["Riding"]
    assert nbt.get(rider, "id") == "minecraft:zombie"
    mount = rider["Riding"]
    assert nbt.get(mount, "id") == "minecraft:mule" and "Type" not in mount


def test_modern_entity_follows_passengers_and_spawner_minecarts():
    from worldbridge.lce.compat import modern_entity

    e = _ent("Boat", Passengers=nbt.ListTag([_ent("PigZombie"), _ent("Skeleton", SkeletonType=nbt.ByteTag(2))], 10))
    modern_entity(e)
    assert nbt.get(e, "id") == "minecraft:boat"
    assert [nbt.get(p, "id") for p in e["Passengers"]] == ["minecraft:zombie_pigman", "minecraft:stray"]
    cart = modern_entity(_ent("MinecartSpawner", EntityId=nbt.StringTag("Zombie")))
    assert nbt.get(cart, "id") == "minecraft:spawner_minecart"
    assert nbt.get(cart["SpawnData"], "id") == "minecraft:zombie"
    husk = modern_entity(_ent("Zombie", ZombieType=nbt.IntTag(6)))
    assert nbt.get(husk, "id") == "minecraft:husk" and "ZombieType" not in husk


@pytest.mark.parametrize("platform, profile", [("ps3", "tu54"), ("xbox360", "tu54"), ("xbox360", "tu46"),
                                               ("wiiu", "tu31"), ("ps4", "tu46")])
def test_every_console_profile_names_its_items(tmp_path, platform, profile):
    world, ch = _write(tmp_path, platform, profile)
    found = _all_item_ids(ch)
    assert len(found) >= 10
    assert all(isinstance(i, nbt.StringTag) and i.py_data.startswith("minecraft:") for i in found), found
    chest = _by_id(ch.tile_entities)["minecraft:chest" if profile == "tu54" else "Chest"][0]
    first = chest["Items"][0]
    assert nbt.get(first, "id") == "minecraft:egg" and nbt.get(first, "Count") == 3 and "Damage" in first
    player = next(iter(world.info.players.values()))
    assert [nbt.get(i, "id") for i in player["Inventory"]] == ["minecraft:diamond_sword"]


@pytest.mark.parametrize("profile, platform", [("tu46", "xbox360"), ("tu31", "wiiu")])
def test_the_older_profiles_keep_the_old_names(tmp_path, profile, platform):
    _world, ch = _write(tmp_path, platform, profile)
    ents = _by_id(ch.entities)
    assert {"EntityHorse", "PigZombie", "Pig", "Zombie", "Skeleton", "Guardian"} <= set(ents)
    assert not any(k.startswith("minecraft:") for k in ents)
    assert sorted(nbt.get(e, "Type") for e in ents["EntityHorse"]) == [0, 1, 4]
    tiles = _by_id(ch.tile_entities)
    assert {"Chest", "EnderChest", "MobSpawner", "FlowerPot", "RecordPlayer", "Cauldron"} <= set(tiles)
    assert nbt.get(tiles["MobSpawner"][0], "EntityId") == "PigZombie"


def test_neolegacy_keeps_numbers_and_old_names(tmp_path):
    world, ch = _write(tmp_path, "win64", "tu31")
    found = _all_item_ids(ch)
    assert found and all(isinstance(i, nbt.ShortTag) for i in found)
    assert "Chest" in _by_id(ch.tile_entities) and "Pig" in _by_id(ch.entities)
    player = next(iter(world.info.players.values()))
    assert all(isinstance(nbt.get_tag(i, "id"), nbt.ShortTag) for i in player["Inventory"])


def test_a_split_save_names_the_entities_of_entities_dat(tmp_path):
    world, ch = _write(tmp_path, "ps4", "tu54")
    assert world.container.platform.split
    raw = read_entity_file(world.container.files["entities.dat"])
    names = {nbt.get(e, "id") for lst in raw.values() for e in lst}
    assert {"minecraft:donkey", "minecraft:zombie_pigman", "minecraft:wither_skeleton"} <= names
    assert not any(n in ("EntityHorse", "PigZombie") for n in names)
    _w2, ch2 = _write(tmp_path, "ps4", "tu46", name="ps4_46")
    assert {"EntityHorse", "PigZombie"} <= {nbt.get(e, "id") for e in ch2.entities}


def test_the_profile_decides_not_the_platform():
    from worldbridge.lce.world import PROFILES

    assert [k for k, p in PROFILES.items() if p.modern_ids] == ["tu54"]


def test_tu54_round_trips_to_java_with_its_entities_tiles_and_items(tmp_path):
    from worldbridge.java.numeric import JavaNumericWorld

    src = tmp_path / "lce"
    w = LCEWriter(str(src), LCEWriteOptions(platform="ps3", profile="tu54", world_size=54), Progress())
    w.add_chunk(OVERWORLD, _chunk())
    w.finish(SyntheticWorld(radius=1).info)
    out = tmp_path / "java"
    convert(str(src), str(out), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12", ring=False))
    ch = JavaNumericWorld(str(out)).read_chunk(OVERWORLD, 0, 0)
    assert ch is not None
    assert len(ch.entities) == len(_chunk().entities)
    ents = [str(nbt.get(e, "id")).replace("minecraft:", "").lower() for e in ch.entities]
    assert "donkey" in ents or "entityhorse" in ents
    assert sum(1 for t in ch.tile_entities if "Items" in t) >= 2
    tiles = {str(nbt.get(t, "id")).lower().replace("minecraft:", "") for t in ch.tile_entities}
    assert {"chest", "enderchest", "mobspawner", "flowerpot"} <= {t.replace("_", "") for t in tiles}
    chest = next(t for t in ch.tile_entities if str(nbt.get(t, "id")).lower().endswith("chest") and len(t.get("Items") or []))
    assert sorted(int(nbt.get(i, "Count")) for i in chest["Items"]) == [1, 3]


def _level_only(path, **fields):
    path.mkdir()
    data = T({"LevelName": nbt.StringTag("t"), "RandomSeed": nbt.LongTag(1), **fields})
    (path / "level.dat").write_bytes(nbt.dump(T({"Data": data}), ""))
    (path / "session.lock").write_bytes(b"\x00" * 8)
    return str(path)


@pytest.mark.parametrize("fields, kind", [({"version": nbt.IntTag(19132)}, "mcregion"),
                                          ({"version": nbt.IntTag(19133)}, "anvil"),
                                          ({}, "alpha")])
def test_a_folder_with_only_a_level_dat_is_a_java_world(tmp_path, fields, kind):
    d = detect(_level_only(tmp_path / "w", **fields))
    assert d is not None and d.kind == "java_numeric" and d.subkind == kind


def test_a_level_dat_only_folder_of_1_13_plus_stays_modern(tmp_path):
    d = detect(_level_only(tmp_path / "w", version=nbt.IntTag(19133), DataVersion=nbt.IntTag(3700)))
    assert d is not None and d.kind == "java_modern"


def test_a_conversion_without_chunks_can_be_reopened(tmp_path):
    from worldbridge.cli import main

    assert main(["--lang", "en", "players", _level_only(tmp_path / "x", version=nbt.IntTag(19132))]) == 0
