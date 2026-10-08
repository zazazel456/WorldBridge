"""What real servers (Java 1.8 / 1.12 / 1.16) complained about in converted worlds: ids a pre-DataVersion chunk
needs, attributes older games do not know, entities in the wrong chunk or sharing a UUID, the world icon."""
import struct

import numpy as np
import pytest

from worldbridge import icon, nbt, placement
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions, entity_uuids
from worldbridge.java.oldcontent import OldContent, attributes_known
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import NumericChunk, Progress

from .helpers import SyntheticWorld

S, I, B = nbt.StringTag, nbt.IntTag, nbt.ByteTag


def _mob(eid, x=1.5, z=2.5, **fields):
    e = nbt.CompoundTag({"id": S(eid), "Pos": nbt.pos_list(x, 64.0, z), "Motion": nbt.pos_list(0, 0, 0),
                         "Rotation": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(0)], 5)})
    for k, v in fields.items():
        e[k] = v
    return e


def _attr(name, base=1.0):
    return nbt.CompoundTag({"Name": S(name), "Base": nbt.DoubleTag(base)})


# ------------------------------------------------------------------ ids of a chunk without DataVersion
@pytest.mark.parametrize("old,new", [
    ("EvocationIllager", "minecraft:evocation_illager"), ("VindicationIllager", "minecraft:vindication_illager"),
    ("IllusionIllager", "minecraft:illusion_illager"), ("Vex", "minecraft:vex"),
    ("EvocationFangs", "minecraft:evocation_fangs"), ("Llama", "minecraft:llama"),
    ("LlamaSpit", "minecraft:llama_spit"), ("Parrot", "minecraft:parrot"),
])
def test_mobs_of_1_11_and_1_12_get_their_registry_names(old, new):
    # the game's fixer renames the ids of its table (Trap, MinecartRideable ...) but never heard of these
    assert str(OldContent("1.12").entity(_mob(old))["id"].py_data) == new


def test_mobs_of_1_12_do_not_reach_1_11_and_the_old_names_stay_before_it():
    assert OldContent("1.11").entity(_mob("Parrot")) is None
    assert str(OldContent("1.11").entity(_mob("Llama"))["id"].py_data) == "minecraft:llama"
    assert OldContent("1.10").entity(_mob("Llama")) is None
    assert str(OldContent("1.12").entity(_mob("Pig"))["id"].py_data) == "Pig"           # the fixer's table renames it
    assert str(OldContent("1.10").entity(_mob("PolarBear"))["id"].py_data) == "PolarBear"


def test_block_entities_of_1_11_and_1_12():
    box = nbt.CompoundTag({"id": S("ShulkerBox"), "x": I(1), "y": I(2), "z": I(3)})
    bed = nbt.CompoundTag({"id": S("Bed"), "x": I(1), "y": I(2), "z": I(3), "color": I(14)})
    assert str(OldContent("1.12").tile(box)["id"].py_data) == "minecraft:shulker_box"
    assert str(OldContent("1.12").tile(bed)["id"].py_data) == "minecraft:bed"
    assert OldContent("1.11").tile(bed) is None and OldContent("1.10").tile(box) is None
    chest = nbt.CompoundTag({"id": S("Chest"), "x": I(1), "y": I(2), "z": I(3)})
    assert str(OldContent("1.12").tile(chest)["id"].py_data) == "Chest"                 # the fixer renames it


def test_species_split_of_1_11_is_written_whole_and_deterministic():
    r12 = OldContent("1.12")
    assert str(r12.entity(_mob("EntityHorse", Type=I(1)))["id"].py_data) == "minecraft:donkey"
    h = r12.entity(_mob("EntityHorse", Type=I(0)))
    assert str(h["id"].py_data) == "EntityHorse"                                       # the fixer makes it a horse
    assert str(r12.entity(_mob("Skeleton", SkeletonType=B(1)))["id"].py_data) == "minecraft:wither_skeleton"
    assert str(r12.entity(_mob("Skeleton", SkeletonType=B(2)))["id"].py_data) == "minecraft:stray"
    sk = r12.entity(_mob("Skeleton", SkeletonType=B(0)))
    assert str(sk["id"].py_data) == "Skeleton" and "SkeletonType" not in sk
    assert str(r12.entity(_mob("Zombie", ZombieType=I(6)))["id"].py_data) == "minecraft:husk"
    zv = r12.entity(_mob("Zombie", IsVillager=B(1)))             # the fixer would roll a profession (0: no villager)
    assert str(zv["id"].py_data) == "minecraft:zombie_villager" and int(zv["Profession"].py_data) == 0
    assert str(r12.entity(_mob("Guardian", Elder=B(1)))["id"].py_data) == "minecraft:elder_guardian"


def test_zombie_and_skeleton_discriminators_follow_the_version():
    z = OldContent("1.10").entity(_mob("Zombie", IsVillager=B(1), VillagerProfession=I(2)))
    assert str(z["id"].py_data) == "Zombie" and int(z["ZombieType"].py_data) == 3 and "IsVillager" not in z
    z8 = OldContent("1.8").entity(_mob("Zombie", ZombieType=I(6)))
    assert "ZombieType" not in z8                                                       # no husks before 1.10
    s8 = OldContent("1.8").entity(_mob("Skeleton", SkeletonType=B(2)))
    assert int(s8["SkeletonType"].py_data) == 0                                         # no strays
    assert int(OldContent("1.8").entity(_mob("Skeleton", SkeletonType=B(1)))["SkeletonType"].py_data) == 1


def test_attributes_are_limited_to_the_ones_the_game_registers():
    names = ["generic.maxHealth", "generic.armor", "generic.armorToughness", "generic.attackSpeed", "generic.luck",
             "generic.flyingSpeed", "horse.jumpStrength"]
    e = _mob("Zombie", Attributes=nbt.ListTag([_attr(n) for n in names], 10))
    got = lambda v: [str(a["Name"].py_data) for a in OldContent(v).entity(nbt.copy(e)).get("Attributes", [])]  # noqa: E731
    assert got("1.8") == ["generic.maxHealth", "horse.jumpStrength"]
    assert got("1.9")[1:4] == ["generic.armor", "generic.armorToughness", "generic.attackSpeed"]
    assert "generic.flyingSpeed" not in got("1.11") and "generic.flyingSpeed" in got("1.12")
    assert got("1.5") == [] and "Attributes" not in OldContent("1.5").entity(nbt.copy(e))
    assert attributes_known(OldContent("1.8").r) == attributes_known(OldContent("1.6").r)


# ------------------------------------------------------------------ the writer
def _chunk(cx, cz, *ents):
    c = NumericChunk(cx, cz, 256)
    c.blocks[0] = 7
    c.blocks[1:60] = 1
    c.biomes = np.full((16, 16), 4, np.uint8)
    c.entities = list(ents)
    return c


def _write(tmp_path, chunks, limit=None, name="w"):
    src = SyntheticWorld(radius=0)
    out = str(tmp_path / name)
    w = JavaNumericWriter(out, JavaWriteOptions(kind="anvil", version_limit=limit), Progress())
    for c in chunks:
        w.add_chunk(0, c)
    w.finish(src.info)
    return out, w


def _entities(world, cx, cz):
    c = JavaNumericWorld(world).read_chunk(0, cx, cz)
    return [] if c is None else c.entities


def test_entity_stored_in_the_neighbour_chunk_goes_to_the_chunk_of_its_position(tmp_path):
    # Bedrock keeps the Wandering Trader with chunk (-1, -2) although it stands at x = 0.11
    trader = _mob("Pig", x=0.11, z=-27.53)
    stay = _mob("Cow", x=-3.0, z=-27.0)
    out, w = _write(tmp_path, [_chunk(-1, -2, trader, stay), _chunk(0, -2)])
    assert [str(e["id"].py_data) for e in _entities(out, -1, -2)] == ["Cow"]
    moved = _entities(out, 0, -2)
    assert [str(e["id"].py_data) for e in moved] == ["Pig"] and w.moved_entities == 1


def test_stray_entity_finds_a_chunk_written_before_or_after(tmp_path):
    e = _mob("Pig", x=16.5, z=1.0)
    out, _ = _write(tmp_path, [_chunk(1, 0), _chunk(0, 0, e)], name="before")
    assert len(_entities(out, 1, 0)) == 1 and not _entities(out, 0, 0)
    out, _ = _write(tmp_path, [_chunk(0, 0, nbt.copy(e)), _chunk(1, 0)], name="after")
    assert len(_entities(out, 1, 0)) == 1 and not _entities(out, 0, 0)


def test_stray_entity_without_a_chunk_there_stays_at_the_edge_of_its_own(tmp_path):
    out, w = _write(tmp_path, [_chunk(0, 0, _mob("Pig", x=40.0, z=5.0))])
    (e,) = _entities(out, 0, 0)
    x = float(e["Pos"][0].py_data)
    assert 0 <= x < 16 and w.clamped_entities == 1


def test_hanging_entity_is_placed_by_its_wall_block(tmp_path):
    frame = _mob("ItemFrame", x=15.99, z=3.0, TileX=I(16), TileY=I(64), TileZ=I(3))
    out, _ = _write(tmp_path, [_chunk(0, 0, frame), _chunk(1, 0)])
    assert len(_entities(out, 1, 0)) == 1


def _uuid(e, hi, lo):
    e["UUIDMost"], e["UUIDLeast"] = nbt.LongTag(hi), nbt.LongTag(lo)
    return e


def test_entities_sharing_a_uuid_get_a_new_one(tmp_path):
    # two rabbits of an old server world with the same UUID: the game keeps one and drops the other
    a = _uuid(_mob("Rabbit", x=1.0, z=1.0), 5, 7)
    b = _uuid(_mob("Rabbit", x=40.0, z=1.0), 5, 7)
    c = _uuid(_mob("Rabbit", x=2.0, z=2.0), 5, 7)                    # a third, in the chunk of the first
    out, w = _write(tmp_path, [_chunk(0, 0, a, c), _chunk(2, 0, b)])
    keys = [k for cx in (0, 2) for k in entity_uuids(_entities(out, cx, 0))]
    assert len(keys) == 3 and len(set(keys)) == 3 and (5, 7) in keys and w.new_uuids == 2


def test_a_stray_with_a_known_uuid_is_renewed_too(tmp_path):
    a = _uuid(_mob("Pig", x=1.0, z=1.0), 9, 9)
    b = _uuid(_mob("Pig", x=17.0, z=1.0), 9, 9)                      # stored in chunk 0, stands in chunk 1
    out, _ = _write(tmp_path, [_chunk(0, 0, a, b), _chunk(1, 0)])
    keys = entity_uuids(_entities(out, 0, 0)) + entity_uuids(_entities(out, 1, 0))
    assert len(keys) == 2 and len(set(keys)) == 2


def test_unique_entities_keep_their_uuid(tmp_path):
    a = _uuid(_mob("Pig", x=1.0, z=1.0), 1, 2)
    b = _uuid(_mob("Cow", x=17.0, z=1.0), 3, 4)
    out, w = _write(tmp_path, [_chunk(0, 0, a), _chunk(1, 0, b)])
    assert entity_uuids(_entities(out, 0, 0)) == [(1, 2)] and entity_uuids(_entities(out, 1, 0)) == [(3, 4)]
    assert w.new_uuids == 0


def test_numeric_1_12_world_carries_the_ids_the_game_loads(tmp_path):
    ev = _mob("EvocationIllager", x=1.0, z=1.0)
    c = _chunk(0, 0, ev, _mob("Zombie", x=2.0, z=2.0, Attributes=nbt.ListTag([_attr("generic.armor")], 10)))
    c.blocks[70, 3, 3] = 219                                         # (a tile without its block is dropped)
    c.tile_entities.append(nbt.CompoundTag({"id": S("ShulkerBox"), "x": I(3), "y": I(70), "z": I(3),
                                            "Items": nbt.ListTag([], 10)}))
    out, _ = _write(tmp_path, [c], limit="1.12")
    ents = JavaNumericWorld(out).read_chunk(0, 0, 0)
    assert sorted(str(e["id"].py_data) for e in ents.entities) == ["Zombie", "minecraft:evocation_illager"]
    assert [str(t["id"].py_data) for t in ents.tile_entities] == ["minecraft:shulker_box"]
    old = _write(tmp_path, [c], limit="1.8", name="w18")[0]
    zombie = [e for e in JavaNumericWorld(old).read_chunk(0, 0, 0).entities if str(e["id"].py_data) == "Zombie"][0]
    assert "Attributes" not in zombie


# ------------------------------------------------------------------ Java modern + Bedrock injectors
def test_rehome_canon_moves_entities_to_the_chunk_of_their_position():
    pig = {"name": "pig", "pos": (0.11, 4.0, -27.53)}
    cow = {"name": "cow", "pos": (-3.0, 4.0, -27.0)}
    far = {"name": "sheep", "pos": (200.0, 4.0, -27.0)}
    canon = {(0, -1, -2): ([{"kind": "x"}], [pig, cow, far])}
    out, n = placement.rehome_canon(canon, lambda d, x, z: (x, z) == (0, -2) or (x, z) == (-1, -2))
    assert n == 1
    assert out[(0, 0, -2)][1] == [pig] and cow in out[(0, -1, -2)][1] and out[(0, -1, -2)][0] == [{"kind": "x"}]
    assert far in out[(0, -1, -2)][1] and -16 <= far["pos"][0] < 0                  # no chunk there: at the edge
    assert placement.chunk_of((-0.5, 0, -0.5)) == (-1, -1) and placement.chunk_of(None) is None


def test_java_modern_injection_writes_each_entity_in_its_chunk(tmp_path):
    from worldbridge import entities
    from worldbridge.java.modern import inject_canon

    reg = RegionWriter(external=True)
    for lx, lz in ((31, 30), (0, 30)):                                       # chunks (-1, -2) and (0, -2)
        root = nbt.CompoundTag({"DataVersion": I(2586), "Level": nbt.CompoundTag({
            "xPos": I(lx if lx < 31 else -1), "zPos": I(-2), "Entities": nbt.ListTag([], 10),
            "TileEntities": nbt.ListTag([], 10), "Sections": nbt.ListTag([], 10)})})
        reg.put(lx, lz, nbt.dump(root, ""))
    region = tmp_path / "region"
    region.mkdir()
    reg.write(str(region / "r.-1.-1.mca"))
    # (-1, -2) is in r.-1.-1 (lx 31), (0, -2) in r.0.-1: write the second region separately
    reg2 = RegionWriter(external=True)
    root0 = nbt.CompoundTag({"DataVersion": I(2586), "Level": nbt.CompoundTag({
        "xPos": I(0), "zPos": I(-2), "Entities": nbt.ListTag([], 10), "TileEntities": nbt.ListTag([], 10),
        "Sections": nbt.ListTag([], 10)})})
    reg2.put(0, 30, nbt.dump(root0, ""))
    reg2.write(str(region / "r.0.-1.mca"))
    trader = entities.from_java_modern(nbt.CompoundTag({
        "id": S("minecraft:wandering_trader"), "Pos": nbt.pos_list(0.11, 4.0, -27.53),
        "Motion": nbt.pos_list(0, 0, 0), "Rotation": nbt.ListTag([nbt.FloatTag(0)] * 2, 5)}))
    inject_canon(str(tmp_path), {(0, -1, -2): ([], [trader])}, Progress())
    chunks = {}
    for fn in ("r.-1.-1.mca", "r.0.-1.mca"):
        r = JavaRegion(str(region / fn))
        for lx, lz in r.chunks():
            root = nbt.load(r.read(lx, lz), compressed=False).tag
            chunks[(int(root["Level"]["xPos"].py_data), int(root["Level"]["zPos"].py_data))] = \
                [str(e["id"].py_data) for e in root["Level"]["Entities"]]
    assert chunks[(0, -2)] == ["minecraft:wandering_trader"] and chunks[(-1, -2)] == []


def test_bedrock_injection_stores_each_actor_with_the_chunk_of_its_position(tmp_path):
    from worldbridge import entities
    from worldbridge.bedrock.extra import BedrockInjector, _db, _get, chunk_prefix, read_nbt_list

    db = _db(str(tmp_path), True)
    for cx in (-1, 0):
        db.put(chunk_prefix(cx, -2, 0) + b"\x2c", b"\x28")                   # the chunks exist
    db.close()
    inj = BedrockInjector(str(tmp_path), (1, 16, 0), Progress())
    try:
        pig = entities.from_java_modern(nbt.CompoundTag({
            "id": S("minecraft:pig"), "Pos": nbt.pos_list(0.11, 4.0, -27.53), "Motion": nbt.pos_list(0, 0, 0),
            "Rotation": nbt.ListTag([nbt.FloatTag(0)] * 2, 5)}))
        inj.put_chunk(0, -1, -2, [], [pig])
    finally:
        inj.close()
    db = _db(str(tmp_path))
    try:
        here = read_nbt_list(_get(db, chunk_prefix(-1, -2, 0) + b"\x32") or b"")
        there = read_nbt_list(_get(db, chunk_prefix(0, -2, 0) + b"\x32") or b"")
    finally:
        db.close()
    assert len(here) == 0 and len(there) == 1


# ------------------------------------------------------------------ the world icon
def _png(w, h, color=(10, 200, 30, 255)):
    return icon.encode_png(np.full((h, w, 4), color, np.uint8))


def test_java_icon_is_always_64_by_64():
    big = icon.java_icon(_png(128, 64))
    assert icon.png_size(big) == (64, 64)
    px = icon.decode_png(big)
    assert tuple(px[10, 10]) == (10, 200, 30, 255)
    ok = _png(64, 64)
    assert icon.java_icon(ok) is ok                                          # right already: untouched
    assert icon.png_size(icon.java_icon(_png(20, 20))) == (64, 64)
    assert icon.java_icon(b"not an image") is None and icon.java_icon(None) is None


def test_jpeg_icon_of_a_bedrock_world_becomes_a_png():
    pytest.importorskip("PySide6")
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PySide6.QtGui import QColor, QImage

    img = QImage(640, 360, QImage.Format.Format_RGB32)
    img.fill(QColor(200, 30, 30))
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    img.save(buf, "JPEG")
    out = icon.java_icon(bytes(ba))
    assert out is not None and icon.png_size(out) == (64, 64)
    r, g, b, _ = icon.decode_png(out)[32, 32]
    assert r > 150 and g < 90 and b < 90


def test_writer_converts_the_icon(tmp_path):
    src = SyntheticWorld(radius=0)
    src.info.thumbnail_png = _png(300, 200)
    out = str(tmp_path / "w")
    w = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    w.add_chunk(0, _chunk(0, 0))
    w.finish(src.info)
    data = open(out + "/icon.png", "rb").read()
    assert struct.unpack(">II", data[16:24]) == (64, 64)
    src.info.thumbnail_png = b"\xff\xd8\xff garbage"
    out2 = str(tmp_path / "w2")
    w = JavaNumericWriter(out2, JavaWriteOptions(kind="anvil"), Progress())
    w.add_chunk(0, _chunk(0, 0))
    w.finish(src.info)
    import os

    assert not os.path.exists(out2 + "/icon.png")
