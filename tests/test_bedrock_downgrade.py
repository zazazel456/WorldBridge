"""Bedrock -> older Bedrock keeps one copy of every actor, in the format of the target, with the block entities, items and
player rewritten for it; Bedrock -> Bedrock keeps the chunks the game has not finished; --move-to moves the player."""
import struct

import pytest

from worldbridge import nbt
from worldbridge.bedrock import extra as bx
from worldbridge.bedrock.extra import BE_TAG, ENTITY_TAG, _db, _get, chunk_prefix, read_nbt_list
from worldbridge.convert import TargetSpec, convert
from worldbridge.model import OVERWORLD, Progress
from worldbridge.relocate import Relocation
from worldbridge.selection import Selection

from .test_depth import _modern_world


@pytest.fixture(scope="module")
def bedrock_120(tmp_path_factory):
    """A Bedrock 1.20.0 world (made from a Java one): a chest and a pig in chunk 0, 0; to it are added by hand a 1.20
    sign (FrontText), a crafter (1.21), an armadillo (1.20.5+), a player with a 1.21 item."""
    base = tmp_path_factory.mktemp("b120")
    java = _modern_world(str(base / "java"), 4, chests=[5], pig_y=5.0)
    out = str(base / "bedrock")
    convert(java, out, TargetSpec(family="bedrock", version=(1, 20, 0), ring=False))
    db = _db(out)
    try:
        key = chunk_prefix(0, 0, OVERWORLD) + bytes([BE_TAG])
        tags = read_nbt_list(_get(db, key) or b"")

        def side(text):
            return nbt.CompoundTag({"Text": nbt.StringTag(text), "SignTextColor": nbt.IntTag(-16777216)})

        tags.append(nbt.CompoundTag({"id": nbt.StringTag("Sign"), "x": nbt.IntTag(1), "y": nbt.IntTag(5), "z": nbt.IntTag(1),
                                     "FrontText": side("hello"), "BackText": side(""), "IsWaxed": nbt.ByteTag(0)}))
        tags.append(nbt.CompoundTag({"id": nbt.StringTag("Crafter"), "x": nbt.IntTag(2), "y": nbt.IntTag(5), "z": nbt.IntTag(2)}))
        db.put(key, bx._dump_list(tags))
        prefix = chunk_prefix(0, 0, OVERWORLD)
        arm = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:armadillo"),
                               "Pos": nbt.ListTag([nbt.FloatTag(3.5), nbt.FloatTag(5.0), nbt.FloatTag(3.5)], 5),
                               "UniqueID": nbt.LongTag(-4294967295), "definitions": nbt.ListTag([], 8)})
        akey = struct.pack(">ii", 7, 7)
        arm["internalComponents"] = nbt.CompoundTag({"EntityStorageKeyComponent": nbt.CompoundTag(
            {"StorageKey": nbt.escape_string(akey)})})
        db.put(b"actorprefix" + akey, nbt.dump(arm, "", little_endian=True, escape=True))
        db.put(b"digp" + prefix, (_get(db, b"digp" + prefix) or b"") + akey)
        pig = nbt.CompoundTag({"identifier": nbt.StringTag("minecraft:pig"),
                               "Pos": nbt.ListTag([nbt.FloatTag(-3.5), nbt.FloatTag(5.0), nbt.FloatTag(3.5)], 5),
                               "UniqueID": nbt.LongTag(-4294967294), "definitions": nbt.ListTag([], 8)})
        pkey = struct.pack(">ii", 8, 8)
        db.put(b"actorprefix" + pkey, nbt.dump(pig, "", little_endian=True, escape=True))
        db.put(b"digp" + struct.pack("<ii", -1, 0), pkey)       # cx = -1: its key goes on with 0xff
        db.put(b"actorprefix" + b"orphan!!!", nbt.dump(arm, "", little_endian=True, escape=True))
        java_player = nbt.CompoundTag({
            "DataVersion": nbt.IntTag(3700), "Pos": nbt.pos_list(5.5, 5.0, 5.5),
            "Inventory": nbt.ListTag([nbt.CompoundTag({"Slot": nbt.ByteTag(0), "id": nbt.StringTag("minecraft:oak_fence"),
                                                       "Count": nbt.ByteTag(2)})], 10)})
        db.put(b"~local_player", nbt.dump(bx.legacy_player_to_bedrock(java_player, (1, 20, 0), 1), "", little_endian=True))
    finally:
        db.close()
    return out


def _records(path):
    """(block entities, actors from 0x32 lists, actors from digp, orphan actorprefix, player) of chunk 0, 0."""
    db = _db(path)
    try:
        prefix = chunk_prefix(0, 0, OVERWORLD)
        tiles = read_nbt_list(_get(db, prefix + bytes([BE_TAG])) or b"")
        old = read_nbt_list(_get(db, prefix + bytes([ENTITY_TAG])) or b"")
        keys = _get(db, b"digp" + prefix) or b""
        new = [a for i in range(0, len(keys), 8) for a in read_nbt_list(_get(db, b"actorprefix" + keys[i:i + 8]) or b"")]
        used = {b"actorprefix" + bytes(v)[i:i + 8] for _k, v in db.iterate(b"digp", b"digq") for i in range(0, len(v), 8)}
        orphans = [bytes(k) for k, _v in db.iterate(b"actorprefix", b"actorprefiy") if bytes(k) not in used]
        player = nbt.load(_get(db, b"~local_player"), little_endian=True, compressed=False).tag
        return tiles, old, new, orphans, player
    finally:
        db.close()


def _ids(actors):
    return sorted(str(nbt.get(a, "identifier")) for a in actors)


def _digp_minus_one(path):
    db = _db(path)
    try:
        keys = _get(db, b"digp" + struct.pack("<ii", -1, 0)) or b""
        return [a for i in range(0, len(keys), 8) for a in read_nbt_list(_get(db, b"actorprefix" + keys[i:i + 8]) or b"")]
    finally:
        db.close()


def test_the_source_has_its_actors_in_digp_and_an_orphan(bedrock_120):
    tiles, old, new, orphans, _p = _records(bedrock_120)
    assert not old and _ids(new) == ["minecraft:armadillo", "minecraft:pig"] and len(orphans) == 1


@pytest.mark.parametrize("version,sign_text", [((1, 16, 220), True), ((1, 12, 0), True)])
def test_older_bedrock_gets_one_copy_of_its_actors_in_the_old_format(tmp_path, bedrock_120, version, sign_text):
    out = str(tmp_path / "old")
    res = convert(bedrock_120, out, TargetSpec(family="bedrock", version=version, ring=False))
    tiles, old, new, orphans, player = _records(out)
    assert _ids(old) == ["minecraft:pig"]                 # the pig once, in the 0x32 list; the armadillo does not exist yet
    assert not new and not orphans                        # nothing for 1.18.30+ in a world that does not read it
    ids = sorted(str(nbt.get(t, "id")) for t in tiles)
    assert "Crafter" not in ids and "Chest" in ids and "Sign" in ids
    sign = next(t for t in tiles if nbt.get(t, "id") == "Sign")
    assert nbt.get(sign, "Text") == "hello" and "FrontText" not in sign       # the layout of before 1.19.80
    assert [str(nbt.get(i, "Name")) for i in player["Inventory"] if nbt.get(i, "Name")][0] == "minecraft:fence"
    assert any("Content that does not exist in Bedrock" in m and "1 entities and 1 block entities" in m
               for m in res.warnings)


def test_newer_or_equal_bedrock_copies_the_source_once_without_orphans(tmp_path, bedrock_120):
    out = str(tmp_path / "same")
    convert(bedrock_120, out, TargetSpec(family="bedrock", version=(1, 21, 0), ring=False))
    tiles, old, new, orphans, player = _records(out)
    assert _ids(new) == ["minecraft:armadillo", "minecraft:pig"] and not old     # as in the source: no second copy
    assert not orphans                                                           # neither Amulet's nor the source's
    assert "Crafter" in [str(nbt.get(t, "id")) for t in tiles]
    assert [str(nbt.get(i, "Name")) for i in player["Inventory"] if nbt.get(i, "Name")][0] == "minecraft:oak_fence"


def test_move_to_moves_the_player_with_the_chunks(tmp_path, bedrock_120):
    db = _db(bedrock_120)                                  # the player stands in chunk 0, 0
    try:
        p = nbt.load(_get(db, b"~local_player"), little_endian=True, compressed=False).tag
        pos = [float(v.py_data) for v in p["Pos"]]
    finally:
        db.close()
    assert 0 <= pos[0] < 16 and 0 <= pos[2] < 16
    cx, cz = int(pos[0] // 16), int(pos[2] // 16)
    sel = Selection(chunks={0: {(cx, cz)}}, move_to=(160, 320))
    out = str(tmp_path / "moved")
    convert(bedrock_120, out, TargetSpec(family="bedrock", version=(1, 21, 0), ring=False, selection=sel))
    db = _db(out)
    try:
        p2 = nbt.load(_get(db, b"~local_player"), little_endian=True, compressed=False).tag
        pos2 = [float(v.py_data) for v in p2["Pos"]]
    finally:
        db.close()
    dx, dz = (160 >> 4) - cx, (320 >> 4) - cz
    assert pos2[0] == pytest.approx(pos[0] + dx * 16) and pos2[2] == pytest.approx(pos[2] + dz * 16)


def test_player_outside_the_moved_chunks_goes_to_the_new_spawn():
    sel = Selection(chunks={0: {(5, 5)}}, move_to=(0, 0))
    mv = Relocation(sel)
    mv.new_spawn = (3, 70, 4)
    root = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.FloatTag(-0.7), nbt.FloatTag(65.0), nbt.FloatTag(-16.6)], 5),
                            "DimensionId": nbt.IntTag(1)})
    assert mv.move_bedrock_player(root)
    assert [round(float(v.py_data), 2) for v in root["Pos"]] == [3.5, 71.62, 4.5] and int(root["DimensionId"].py_data) == 0


# ------------------------------------------------------------------ chunks the game has not finished


def _finalized(path):
    db = _db(path)
    try:
        return {struct.unpack_from("<ii", bytes(k), 0): struct.unpack_from("<i", bytes(v), 0)[0]
                for k, v in db.iterate() if len(k) == 9 and bytes(k)[-1] == 0x36}
    finally:
        db.close()


@pytest.fixture(scope="module")
def unfinished(tmp_path_factory, bedrock_120):
    import shutil

    p = str(tmp_path_factory.mktemp("unf") / "w")
    shutil.copytree(bedrock_120, p)
    db = _db(p)
    try:
        db.put(chunk_prefix(0, 0, OVERWORLD) + b"\x36", struct.pack("<i", 0))
    finally:
        db.close()
    return p


def test_bedrock_to_bedrock_keeps_the_chunks_the_game_has_not_finished(tmp_path, unfinished):
    assert _finalized(unfinished)[(0, 0)] == 0
    out = str(tmp_path / "bed")
    res = convert(unfinished, out, TargetSpec(family="bedrock", version=(1, 21, 0), ring=False))
    fin = _finalized(out)
    assert len(fin) == len(_finalized(unfinished)) and fin[(0, 0)] == 0       # the chunk is there, still unfinished
    assert not [m for m in res.warnings if "had not finished" in m]


def test_other_targets_leave_them_out_and_say_what_they_held(tmp_path, unfinished):
    from worldbridge.java.region import JavaRegion

    out = str(tmp_path / "java")
    res = convert(unfinished, out, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4), ring=False))
    reg = JavaRegion(f"{out}/region/r.0.0.mca")
    assert (0, 0) not in set(reg.chunks()) and len(list(reg.chunks())) == len(_finalized(unfinished)) - 1
    warn = [m for m in res.warnings if "had not finished" in m]
    assert warn and "block entities" in warn[0]


def test_actors_of_a_chunk_with_a_negative_x_are_not_taken_for_orphans(tmp_path, bedrock_120):
    assert len(_digp_minus_one(bedrock_120)) == 1
    out = str(tmp_path / "same")
    convert(bedrock_120, out, TargetSpec(family="bedrock", version=(1, 21, 0), ring=False))
    assert _ids(_digp_minus_one(out)) == ["minecraft:pig"] and not _records(out)[3]
    old = str(tmp_path / "old")
    convert(bedrock_120, old, TargetSpec(family="bedrock", version=(1, 16, 220), ring=False))
    db = _db(old)
    try:
        assert len(read_nbt_list(_get(db, struct.pack("<ii", -1, 0) + bytes([ENTITY_TAG])) or b"")) == 1
    finally:
        db.close()
