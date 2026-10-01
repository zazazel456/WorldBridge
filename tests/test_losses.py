"""Data that tools/matrix.py found lost on some routes: pet owners, the ender chest through
Bedrock, flower pot plants and note block pitches through Java 1.13+."""
import numpy as np

from worldbridge import entities as ent
from worldbridge import nbt, tiles
from worldbridge.bedrock.extra import bedrock_player_to_legacy, legacy_player_to_bedrock
from worldbridge.java import modern

OWNER = "0f0e0d0c-0b0a-4908-8706-050403020100"


def _wolf():
    return nbt.CompoundTag({
        "id": nbt.StringTag("Wolf"), "OwnerUUID": nbt.StringTag(OWNER), "Sitting": nbt.ByteTag(1),
        "CollarColor": nbt.ByteTag(11), "Health": nbt.FloatTag(20.0),
        "Pos": nbt.ListTag([nbt.DoubleTag(1.5), nbt.DoubleTag(65.0), nbt.DoubleTag(1.5)], 6)})


def test_tamed_wolf_keeps_its_owner_everywhere():
    c = ent.from_legacy(_wolf())
    assert c["tamed"] and ent.uuid_string(c["owner"]) == OWNER
    new = ent.to_java_modern(c, 3465)  # 1.20.1: int array
    assert isinstance(new["Owner"], nbt.IntArrayTag) and int(new["Sitting"].py_data) == 1
    back = ent.from_java_modern(new)
    assert back["owner"] == c["owner"] and back["tamed"]
    old = ent.to_java_modern(c, 2230)  # 1.15: string
    assert nbt.get(old, "OwnerUUID") == OWNER
    assert nbt.get(ent.to_legacy(back), "OwnerUUID") == OWNER
    be = ent.to_bedrock(c, 5, owner_uid=-77)
    assert int(be["IsTamed"].py_data) == 1 and int(be["OwnerNew"].py_data) == -77
    assert int(be["Sitting"].py_data) == 1 and int(be["Color"].py_data) == 11
    assert "+minecraft:wolf_tame" in [str(d.py_data) for d in be["definitions"]]
    from_be = ent.from_bedrock(be)
    assert from_be["tamed"] and from_be["owner"] == ent.bedrock_uuid(-77)
    assert int(from_be["extra"]["CollarColor"].py_data) == 11


def test_bedrock_owner_matches_the_converted_player():
    be_player = nbt.CompoundTag({"UniqueID": nbt.LongTag(-77)})
    p = bedrock_player_to_legacy(be_player)
    uid = ((int(p["UUIDMost"].py_data) & (2**64 - 1)) << 64) | (int(p["UUIDLeast"].py_data) & (2**64 - 1))
    assert uid == ent.bedrock_uuid(-77)


def test_wild_wolf_stays_wild():
    w = _wolf()
    del w["OwnerUUID"]
    c = ent.from_legacy(w)
    assert not c["tamed"]
    assert "IsTamed" not in ent.to_bedrock(c, 5, owner_uid=-77)


def test_ender_chest_food_and_xp_reach_bedrock():
    p = nbt.CompoundTag({
        "Inventory": nbt.ListTag([], 10), "Health": nbt.FloatTag(15.0), "foodLevel": nbt.IntTag(9), "XpLevel": nbt.IntTag(30),
        "EnderItems": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(264), "Count": nbt.ByteTag(32),
                                                    "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(4)})], 10)})
    be = legacy_player_to_bedrock(p, (1, 21, 50), 1)
    ender = be["EnderChestInventory"]
    assert len(ender) == 27 and str(ender[4]["Name"].py_data) == "minecraft:diamond"
    back = bedrock_player_to_legacy(be)
    assert [int(i["Count"].py_data) for i in back["EnderItems"]] == [32]
    assert int(back["foodLevel"].py_data) == 9 and int(back["XpLevel"].py_data) == 30
    assert float(back["Health"].py_data) == 15.0


def _chunk(dv, palette_names, fill):
    """One 1.13+ chunk section at Y=4 whose blocks are palette indices ``fill`` (4096)."""
    pal = nbt.ListTag([nbt.CompoundTag({"Name": nbt.StringTag(n), **({"Properties": nbt.CompoundTag(p)} if p else {})})
                       for n, p in palette_names], 10)
    spanning = dv < modern.SPANNING_DV
    data = modern._encode(np.asarray(fill), len(pal), spanning)
    if dv >= 2860:  # 1.18
        sec = nbt.CompoundTag({"Y": nbt.ByteTag(4), "block_states": nbt.CompoundTag({"palette": pal, "data": data})})
        return nbt.CompoundTag({"DataVersion": nbt.IntTag(dv), "sections": nbt.ListTag([sec], 10)})
    sec = nbt.CompoundTag({"Y": nbt.ByteTag(4), "Palette": pal, "BlockStates": data})
    return nbt.CompoundTag({"DataVersion": nbt.IntTag(dv), "Level": nbt.CompoundTag({"Sections": nbt.ListTag([sec], 10)})})


def _at(x, y, z):
    return (y & 15) << 8 | z << 4 | x


def test_pots_and_note_blocks_survive_java_1_13_plus():
    for dv in (1976, 2230, 2586, 3465):  # 1.14 and 1.15 (spanning longs), 1.16, 1.20
        names = [("minecraft:air", None), ("minecraft:stone", None), ("minecraft:potted_blue_orchid", None),
                 ("minecraft:note_block", {"note": nbt.StringTag("12"), "instrument": nbt.StringTag("harp"),
                                           "powered": nbt.StringTag("false")})]
        fill = np.ones(4096, np.int64)
        fill[_at(3, 70, 5)] = 2
        fill[_at(9, 71, 2)] = 3
        root = _chunk(dv, names, fill)
        got = {t["pos"]: t for t in modern.state_tiles(root, 2, -1)}
        assert got[(35, 70, -11)]["plant"] == ("minecraft:red_flower", 1)
        assert got[(41, 71, -14)]["note"] == 12
        # reverse: an empty pot and a note block at 0 get their plant / pitch back
        root = _chunk(dv, [("minecraft:stone", None), ("minecraft:flower_pot", None),
                           ("minecraft:note_block", {"note": nbt.StringTag("0")})], np.where(
            np.arange(4096) == _at(3, 70, 5), 1, np.where(np.arange(4096) == _at(9, 71, 2), 2, 0)))
        canon = [{"kind": "flower_pot", "pos": (35, 70, -11), "plant": (38, 1)},
                 {"kind": "noteblock", "pos": (41, 71, -14), "note": 12},
                 {"kind": "flower_pot", "pos": (36, 70, -11), "plant": (38, 1)}]  # stone there: untouched
        assert modern.apply_state_tiles(root, canon) == 2
        got = {t["pos"]: t for t in modern.state_tiles(root, 2, -1)}
        assert got[(35, 70, -11)]["plant"] == ("minecraft:red_flower", 1) and got[(41, 71, -14)]["note"] == 12
        assert (36, 70, -11) not in got


def test_flower_pot_plant_through_bedrock_and_old_ids():
    c = {"kind": "flower_pot", "pos": (1, 2, 3), "plant": ("minecraft:red_flower", 1)}
    for version in ((1, 16, 220), (1, 21, 50), (26, 50, 0)):
        assert tiles.from_bedrock(tiles.to_bedrock(c, version))["plant"] == ("minecraft:red_flower", 1)
    legacy = tiles.to_legacy(c)
    assert isinstance(legacy["Item"], nbt.IntTag) and int(legacy["Item"].py_data) == 38


def test_raw_bedrock_actors_are_dropped_from_java_chunks():
    wolf_be = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:wolf"), "id": nbt.StringTag("minecraft:wolf"),
                               "definitions": nbt.ListTag([nbt.StringTag("+minecraft:wolf")], 8)})
    wolf_java = nbt.CompoundTag({"id": nbt.StringTag("minecraft:wolf")})
    root = nbt.CompoundTag({"Level": nbt.CompoundTag({"Entities": nbt.ListTag([wolf_be, wolf_java], 10)})})
    modern._drop_bedrock_entities(root)
    assert [dict(e) for e in root["Level"]["Entities"]] == [dict(wolf_java)]


def test_bedrock_player_speed_permissions_and_game_mode():
    p = nbt.CompoundTag({"Inventory": nbt.ListTag([], 10), "playerGameType": nbt.IntTag(0)})
    be = legacy_player_to_bedrock(p, (1, 21, 50), 1, world_game_type=0)
    attrs = {str(a["Name"].py_data): float(a["Current"].py_data) for a in be["Attributes"]}
    assert abs(attrs["minecraft:movement"] - 0.1) < 1e-6  # absent = 0.7, seven times too fast
    assert int(be["PlayerGameMode"].py_data) == 5  # follows the world's mode
    assert int(be["playerPermissionsLevel"].py_data) == 2 and int(be["abilities"]["op"].py_data) == 1
    creative = legacy_player_to_bedrock(nbt.CompoundTag({"playerGameType": nbt.IntTag(1)}), (1, 21, 50), 1, world_game_type=0)
    assert int(creative["PlayerGameMode"].py_data) == 1 and int(creative["abilities"]["mayfly"].py_data) == 1


def test_map_colours_round_trip_and_old_palettes():
    from worldbridge import maps

    cols = np.arange(4, 4 + 128 * 128) % (62 * 4 - 4) + 4
    cols = cols.astype(np.uint8)
    rgba = maps.java_to_rgba(cols.tobytes())
    back = np.frombuffer(maps.rgba_to_java(rgba, 62), np.uint8)
    assert (maps.PALETTE[back][:, :3] == maps.PALETTE[cols][:, :3]).all()  # same colour on screen
    data = nbt.CompoundTag({"dimension": nbt.StringTag("minecraft:the_nether"),
                            "colors": nbt.ByteArrayTag(cols.view(np.int8))})
    old = maps.legacy_map_data(data, 36)
    assert int(old["dimension"].py_data) == -1
    assert (np.asarray(old["colors"], np.uint8) >> 2).max() < 36


def _hub_with_frame(path):
    from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
    from worldbridge.model import Progress

    from .helpers import SyntheticWorld

    src = SyntheticWorld(radius=1)
    read = src.read_chunk

    def read_chunk(dim, cx, cz):
        c = read(dim, cx, cz)
        if (cx, cz) == (0, 0):
            c.blocks[66:70, 2, 3] = 1  # wall at x = 3, frame in front of it (x = 2, facing west)
            c.entities.append(nbt.CompoundTag({
                "id": nbt.StringTag("ItemFrame"), "TileX": nbt.IntTag(2), "TileY": nbt.IntTag(67), "TileZ": nbt.IntTag(2),
                "Facing": nbt.ByteTag(1), "ItemRotation": nbt.ByteTag(2),
                "Pos": nbt.ListTag([nbt.DoubleTag(2.96875), nbt.DoubleTag(67.5), nbt.DoubleTag(2.5)], 6),
                "Item": nbt.CompoundTag({"id": nbt.ShortTag(358), "Count": nbt.ByteTag(1), "Damage": nbt.ShortTag(3)})}))
        return c

    src.read_chunk = read_chunk
    cols = np.full(128 * 128, 12 * 4 + 1, np.uint8)
    src.info.extra_files["data/map_3.dat"] = nbt.dump(nbt.CompoundTag({"data": nbt.CompoundTag({
        "scale": nbt.ByteTag(0), "dimension": nbt.ByteTag(0), "xCenter": nbt.IntTag(0), "zCenter": nbt.IntTag(0),
        "colors": nbt.ByteArrayTag(cols.view(np.int8))})}), "", compressed=True)
    w = JavaNumericWriter(str(path), JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    return str(path)


def test_item_frames_maps_and_height_maps_through_bedrock(tmp_path):
    import os
    import struct

    from worldbridge.bedrock.extra import _db
    from worldbridge.convert import TargetSpec, convert
    from worldbridge.java.numeric import JavaNumericWorld

    hub = _hub_with_frame(tmp_path / "hub")
    be = str(tmp_path / "be")
    convert(hub, be, TargetSpec(family="bedrock"))
    db = _db(be)
    try:
        hm = np.frombuffer(bytes(db.get(struct.pack("<ii", 0, 0) + b"\x2d"))[:512], "<i2")
        assert hm.min() >= 64  # was 0 everywhere: no blending with the terrain Bedrock generates
        assert any(bytes(k).startswith(b"map_") for k, _v in db.iterate())
    finally:
        db.close()
    back = str(tmp_path / "back")
    convert(be, back, TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    w = JavaNumericWorld(back)
    frames = [e for e in w.read_chunk(0, 0, 0).entities if nbt.get(e, "id") == "ItemFrame"]
    assert len(frames) == 1
    f = frames[0]
    assert (int(f["TileX"].py_data), int(f["TileY"].py_data), int(f["TileZ"].py_data), int(f["Facing"].py_data)) == (2, 67, 2, 1)
    assert int(f["Item"]["id"].py_data) == 358 and int(f["Item"]["Damage"].py_data) == 3 and int(f["ItemRotation"].py_data) == 2
    data = nbt.load(open(os.path.join(back, "data", "map_3.dat"), "rb").read()).tag["data"]
    assert int(np.asarray(data["colors"], np.uint8)[0]) == 12 * 4 + 1


def test_game_written_bedrock_player_with_binary_strings_is_read(tmp_path):
    import amulet_nbt as an

    from worldbridge.bedrock.extra import _db, read_bedrock_players

    path = str(tmp_path / "be")
    import os

    os.makedirs(os.path.join(path, "db"))
    db = _db(path, create=True)
    p = an.CompoundTag({"identifier": an.StringTag("minecraft:player"), "UniqueID": an.LongTag(-5),
                        "Pos": an.ListTag([an.FloatTag(1.0), an.FloatTag(70.0), an.FloatTag(2.0)]),
                        "internalComponents": an.CompoundTag({"EntityStorageKeyComponent": an.CompoundTag(
                            {"StorageKey": an.StringTag("F\u241bx96\u241bx82   ")})}),
                        "Inventory": an.ListTag([an.CompoundTag({"Name": an.StringTag("minecraft:stick"),
                                                                 "Count": an.ByteTag(9), "Damage": an.ShortTag(0),
                                                                 "Slot": an.ByteTag(0)})])})
    raw = an.NamedTag(p, "").save_to(compressed=False, little_endian=True, string_encoder=an.utf8_escape_encoder)
    db.put(b"~local_player", raw)
    db.close()
    players = read_bedrock_players(path)
    assert "host" in players and len(players["host"]["Inventory"]) == 1
