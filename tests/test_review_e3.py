"""Review fixes (batch E3): level.dat versions of Bedrock targets and the spawn / players of a moved selection."""
import struct

from worldbridge import amulet_bridge as ab
from worldbridge import gameversion as gv
from worldbridge import nbt
from worldbridge.model import WorldInfo
from worldbridge.relocate import Relocation
from worldbridge.selection import Selection


# ------------------------------------------------------------------ M7: level.dat versions


def test_bedrock_storage_version_follows_the_target():
    for v, want in (((1, 2, 13), 8), ((1, 12, 0), 8), ((1, 16, 220), 8), ((1, 18, 2), 8), ((1, 19, 20), 9),
                    ((1, 19, 22), 9), ((1, 19, 50), 10), ((1, 20, 0), 10), ((1, 21, 50), 10), ((26, 50), 10)):
        assert gv.bedrock_storage_version(v) == want, v


def test_bedrock_protocol_numbers_of_known_worlds():
    for v, want in (((1, 16, 220), 431), ((1, 17, 40), 471), ((1, 18, 0), 475), ((1, 18, 2), 475), ((1, 19, 50), 560),
                    ((1, 20, 51), 630), ((1, 20, 72), 662), ((26, 40), 2168)):
        assert gv.bedrock_protocol(v) == want, v
    assert gv.bedrock_protocol((1, 12, 0)) == 361 and gv.bedrock_protocol((1, 16, 5)) == 407     # the one before


def _level_dat(tmp_path, version):
    info = WorldInfo()
    info.level = nbt.CompoundTag({"LevelName": nbt.StringTag("w"), "SpawnX": nbt.IntTag(1), "SpawnY": nbt.IntTag(2),
                                  "SpawnZ": nbt.IntTag(3)})
    # Amulet's template: a header of 9 whatever the version
    root = nbt.CompoundTag({"StorageVersion": nbt.IntTag(9)})
    payload = nbt.dump(root, "", little_endian=True)
    (tmp_path / "level.dat").write_bytes(struct.pack("<ii", 9, len(payload)) + payload)
    ab.write_bedrock_level_dat(str(tmp_path), info, version)
    raw = (tmp_path / "level.dat").read_bytes()
    return struct.unpack_from("<i", raw, 0)[0], nbt.load(raw[8:], little_endian=True, compressed=False).tag


def test_level_dat_header_and_tag_agree_and_follow_the_target(tmp_path):
    for i, (version, storage, proto) in enumerate((((1, 12, 0), 8, 361), ((1, 16, 220), 8, 431), ((1, 19, 22), 9, 545),
                                                    ((1, 20, 50), 10, 630), ((26, 50, 0), 10, 2168))):
        d = tmp_path / str(i)
        d.mkdir()
        header, root = _level_dat(d, version)
        assert header == int(nbt.get(root, "StorageVersion")) == storage, version
        assert int(nbt.get(root, "NetworkVersion")) == proto, version
        assert nbt.get(root, "InventoryVersion") == ".".join(str(i) for i in gv.bedrock_stored(version, 3))


# ------------------------------------------------------------------ L12 / L18: spawn and players of a moved selection


def test_a_player_just_west_of_the_origin_is_in_chunk_minus_one():
    sel = Selection(chunks={0: {(-1, -2), (-1, -1)}}, move_to=(1000, 2000))
    mv = Relocation(sel)
    assert mv._moved(0, -0.7, -16.6) == (-0.7 + mv.delta(0)[0] * 16, -16.6 + mv.delta(0)[1] * 16)
    assert mv._moved(0, 0.3, -16.6) is None          # chunk (0, -2) is not selected


def test_an_explicit_spawn_outside_the_moved_chunks_is_kept_as_given():
    sel = Selection(chunks={0: {(-1, -2)}}, move_to=(1000, 2000), spawn=(1000, -59, 2000))
    info = WorldInfo()
    info.level = nbt.CompoundTag({"SpawnX": nbt.IntTag(1000), "SpawnY": nbt.IntTag(-59), "SpawnZ": nbt.IntTag(2000)})
    mv = Relocation(sel)
    mv.top = -60                                      # the ground found at the destination
    assert mv.spawn(info) == (1000, -59, 2000)
    sel.spawn = None
    assert Relocation(sel).spawn(info) == (1000, -59, 2000)       # no top known: the same
    mv = Relocation(sel)
    mv.top = -60
    assert mv.spawn(info) == (1000, -60, 2000)        # without --spawn it goes on the ground at the destination


def test_bedrock_spawn_never_set_and_negative_spawn_y():
    int_min = -(1 << 31)
    unset = nbt.CompoundTag({"SpawnX": nbt.IntTag(int_min), "SpawnY": nbt.IntTag(int_min), "SpawnZ": nbt.IntTag(int_min)})
    assert ab.bedrock_spawn_unset(unset)
    lv = ab.bedrock_info_to_java(unset)
    assert (int(lv["SpawnX"].py_data), int(lv["SpawnY"].py_data), int(lv["SpawnZ"].py_data)) == (0, 64, 0)
    flat = nbt.CompoundTag({"SpawnX": nbt.IntTag(25), "SpawnY": nbt.IntTag(-60), "SpawnZ": nbt.IntTag(59)})
    assert not ab.bedrock_spawn_unset(flat)
    lv = ab.bedrock_info_to_java(flat)
    assert int(lv["SpawnY"].py_data) == -60                     # a real Y of a 1.18+ world
    ground = nbt.CompoundTag({"SpawnX": nbt.IntTag(0), "SpawnY": nbt.IntTag(32767), "SpawnZ": nbt.IntTag(0)})
    assert int(ab.bedrock_info_to_java(ground)["SpawnY"].py_data) == 64      # "on the ground"
