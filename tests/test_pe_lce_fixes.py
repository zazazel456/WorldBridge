"""Pocket Edition 0.x and LCE split saves: entities of every id form, plain sign text, chunk length, the
PE 0.1 – 0.2 level and player, pe-old to pe-old, entities.dat of PS4 / Xbox One, player ids, dropped players."""
import struct

import numpy as np
import pytest

from worldbridge import nbt
from worldbridge.bedrock import pe_old
from worldbridge.convert import TargetSpec, convert
from worldbridge.lce.world import (ENTITY_FILES, LCEWorld, LCEWriteOptions, LCEWriter, read_entity_file,
                                   write_entity_file)
from worldbridge.model import NumericChunk, Progress, WorldInfo

from .helpers import SyntheticWorld, make_chunk


def _mob(eid, x=8.5, z=8.5, **extra):
    e = nbt.CompoundTag({
        "id": nbt.StringTag(eid),
        "Pos": nbt.ListTag([nbt.DoubleTag(x), nbt.DoubleTag(65.0), nbt.DoubleTag(z)], 6),
        "Motion": nbt.ListTag([nbt.DoubleTag(0), nbt.DoubleTag(0), nbt.DoubleTag(0)], 6),
        "Rotation": nbt.ListTag([nbt.FloatTag(0), nbt.FloatTag(0)], 5)})
    for k, v in extra.items():
        e[k] = v
    return e


def _sign(tid, *lines):
    t = nbt.CompoundTag({"id": nbt.StringTag(tid), "x": nbt.IntTag(3), "y": nbt.IntTag(64), "z": nbt.IntTag(3)})
    for i, line in enumerate(lines, 1):
        t[f"Text{i}"] = nbt.StringTag(line)
    return t


def _write_pe(path, chunks, prog=None, info=None, origin=(0, 0)):
    w = pe_old.PEOldWriter(str(path), prog or Progress(), origin=origin)
    for c in chunks:
        w.add_chunk(0, c)
    w.finish(info or WorldInfo())
    return w


# ------------------------------------------------------------------ Java / LCE -> PE 0.8


def test_pe_keeps_the_entities_of_every_id_form_and_reports_the_others(tmp_path):
    c = make_chunk(0, 0)
    c.entities = [_mob("Chicken"), _mob("minecraft:pig"), _mob("minecraft:chicken"), _mob("minecraft:wolf"),
                  _mob("Wolf"), _mob("minecraft:squid")]
    c.tile_entities = [_sign("minecraft:sign", "a"), _sign("Chest"),
                       _sign("minecraft:chest"), _sign("NetherReactor"), _sign("MobSpawner"), _sign("minecraft:beacon")]
    prog = Progress()
    _write_pe(tmp_path / "pe", [c], prog)
    w = pe_old.PEOldWorld(str(tmp_path / "pe"))
    assert sorted(nbt.get(e, "id") for e in w._ents) == ["Chicken", "Chicken", "Pig"]
    assert sorted(nbt.get(t, "id") for t in w._tiles) == ["Chest", "Chest", "NetherReactor", "Sign"]
    msg = [m for m in prog.warnings if "does not exist in Pocket Edition 0.8" in m]
    assert msg and "3 entities and 2 block entities" in msg[0], prog.warnings


def test_pe_signs_are_plain_text_and_health_is_a_short(tmp_path):
    c = make_chunk(0, 0)
    c.tile_entities = [_sign("Sign", '{"text":"WorldBridge àèé €"}', '"quoted"', "§cred and a very long line", "")]
    c.entities = [_mob("minecraft:pig", Health=nbt.FloatTag(7.6)),
                  _mob("Cow", Health=nbt.ShortTag(10), HealF=nbt.FloatTag(9.0))]
    _write_pe(tmp_path / "pe", [c])
    w = pe_old.PEOldWorld(str(tmp_path / "pe"))
    sign = w._tiles[0]
    assert [str(nbt.get(sign, f"Text{i}")) for i in range(1, 5)] == ["WorldBridge àèé", "quoted",
                                                                    "red and a very ", ""]
    hp = {nbt.get(e, "id"): e for e in w._ents}
    assert isinstance(hp["Pig"]["Health"], nbt.ShortTag) and hp["Pig"]["Health"].py_data == 8
    assert hp["Cow"]["Health"].py_data == 9 and "HealF" not in hp["Cow"]


def test_pe_chunk_length_counts_its_own_four_bytes(tmp_path):
    _write_pe(tmp_path / "pe", [make_chunk(0, 0)])
    raw = (tmp_path / "pe" / "chunks.dat").read_bytes()
    off = int.from_bytes(raw[1:4], "little") * pe_old.SECTOR
    assert struct.unpack_from("<I", raw, off)[0] == 82180 == pe_old.CHUNK_BYTES + 4
    assert pe_old.PEOldWorld(str(tmp_path / "pe")).read_chunk(0, 0, 0) is not None


# ------------------------------------------------------------------ PE 0.1 - 0.2 sources


def _v1_level(name="PE Test"):
    body = struct.pack(">7i", 1324843077, 128, 64, 130, 55, 0, 1325516198) + struct.pack(">H", len(name)) + name.encode()
    return struct.pack("<ii", 1, len(body)) + body


def _v1_player():
    body = struct.pack("<9f2hB3x9i", 160.5, 71.6, 226.25, 0, -0.0784, 0, 19.5, 180.0, 0, -20, 300, 1,
                       5, 4, 3, 102, -1, -1, -1, -1, -1)
    return struct.pack("<ii", 1, 80) + body


def test_pe_0_1_level_and_player_are_read(tmp_path):
    pe = tmp_path / "pe01"
    _write_pe(pe, [make_chunk(0, 0)])
    (pe / "level.dat").write_bytes(_v1_level())
    (pe / "player.dat").write_bytes(_v1_player())
    w = pe_old.PEOldWorld(str(pe))
    assert w.info.name == "PE Test" and w.info.spawn == (128, 64, 130)
    assert nbt.get(w.info.level, "RandomSeed") == 1324843077 and nbt.get(w.info.level, "Time") == 55
    p = w.info.players["host"]
    assert [float(v.py_data) for v in p["Pos"]] == pytest.approx([160.5, 71.6, 226.25], abs=1e-4)
    assert [(nbt.get(i, "id"), nbt.get(i, "Slot")) for i in p["Inventory"]] == [(5, 0), (4, 1), (3, 2), (102, 3)]
    assert float(p["Rotation"][0].py_data) == 180.0 and float(p["Rotation"][1].py_data) == 19.5


def test_a_truncated_pe_0_1_file_is_not_a_level():
    assert pe_old.read_v1_level(_v1_level()[:20]) is None
    assert pe_old.read_v1_player(_v1_player()[:50]) is None
    assert pe_old.read_v1_level(struct.pack("<ii", 3, 10) + bytes(10)) is None      # a 0.3+ (NBT) level.dat


# ------------------------------------------------------------------ pe-old -> pe-old


def test_pe_to_pe_keeps_the_map_in_place_whatever_the_spawn(tmp_path):
    src = tmp_path / "src"
    chunks = []
    for cx in range(16):
        for cz in range(16):
            c = NumericChunk(cx, cz, 128)
            c.blocks[0] = 7
            c.blocks[1:40] = 1
            chunks.append(c)
    chunks[0].tile_entities = [_sign("Sign", "far corner")]
    chunks[0].tile_entities[0]["x"], chunks[0].tile_entities[0]["z"] = nbt.IntTag(2), nbt.IntTag(2)
    chunks[0].entities = [_mob("Pig", 3.5, 3.5, Health=nbt.ShortTag(10))]
    info = WorldInfo()
    info.level["SpawnX"], info.level["SpawnY"], info.level["SpawnZ"] = nbt.IntTag(10), nbt.IntTag(64), nbt.IntTag(230)
    _write_pe(src, chunks, info=info)
    out = tmp_path / "out"
    res = convert(str(src), str(out), TargetSpec(family="pe_old"))
    a, b = pe_old.PEOldWorld(str(src)), pe_old.PEOldWorld(str(out))
    assert len(b.index) == 256 and sorted(b.index) == sorted(a.index)
    assert b.info.spawn == a.info.spawn
    assert [nbt.get(t, "Text1") for t in b._tiles] == ["far corner"]
    assert [nbt.get(e, "id") for e in b._ents] == ["Pig"]
    assert not [m for m in res.warnings if "left out" in m]


# ------------------------------------------------------------------ LCE split saves: entities.dat


def _ps4_save(tmp_path, platform="ps4", name="out"):
    src = SyntheticWorld(radius=1)
    w = LCEWriter(str(tmp_path / name), LCEWriteOptions(platform=platform, world_size=54), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    return w.finish(src.info)


@pytest.mark.parametrize("platform", ["ps4", "xboxone"])
def test_split_saves_keep_their_entities_in_entities_dat(tmp_path, platform):
    from worldbridge.lce.container import SaveContainer

    path = _ps4_save(tmp_path, platform)
    cont = SaveContainer.load(path)
    assert set(ENTITY_FILES.values()) <= set(cont.files)
    per_chunk = read_entity_file(cont.files["entities.dat"])
    assert len(per_chunk) == 4 and all(len(v) == 1 and nbt.get(v[0], "id") == "Pig" for v in per_chunk.values())
    assert read_entity_file(cont.files["DIM-1entities.dat"]) == {}
    world = LCEWorld(path)
    for cx, cz in world.chunk_coords(0):
        assert world.read_raw_chunk(0, cx, cz).entities and len(world.read_chunk(0, cx, cz).entities) == 1


def test_entities_of_the_dat_file_join_the_chunks_and_nothing_else_does(tmp_path):
    from worldbridge.lce.container import SaveContainer

    path = _ps4_save(tmp_path)
    cont = SaveContainer.load(path)
    zombie = nbt.dump(nbt.CompoundTag({"Entities": nbt.compound_list([_mob("minecraft:zombie")])}), "")
    cont.files["entities.dat"] = write_entity_file({(-1, -1): zombie})
    cont.save(str(tmp_path / "edited"))
    world = LCEWorld(str(tmp_path / "edited" / "GAMEDATA") if (tmp_path / "edited" / "GAMEDATA").exists()
                     else str(tmp_path / "edited"))
    got = {k: [nbt.get(e, "id") for e in world.read_chunk(0, *k).entities] for k in world.chunk_coords(0)}
    assert got[(-1, -1)] == ["minecraft:zombie"] and sum(len(v) for v in got.values()) == 1


def test_an_unreadable_entities_dat_is_reported(tmp_path):
    from worldbridge.lce.container import SaveContainer

    path = _ps4_save(tmp_path)
    cont = SaveContainer.load(path)
    cont.files["DIM1/entities.dat"] = struct.pack(">I", 3) + b"\x00\x01"
    cont.save(str(tmp_path / "bad"))
    prog = Progress()
    p = str(tmp_path / "bad" / "GAMEDATA") if (tmp_path / "bad" / "GAMEDATA").exists() else str(tmp_path / "bad")
    LCEWorld(p, progress=prog)
    assert any("DIM1/entities.dat" in m for m in prog.warnings), prog.warnings


def test_entity_file_roundtrip():
    blob = nbt.dump(nbt.CompoundTag({"Entities": nbt.compound_list([_mob("minecraft:cow")])}), "")
    data = write_entity_file({(3, -2): blob, (-1, 0): blob})
    assert struct.unpack_from(">I", data, 0)[0] == 2
    got = read_entity_file(data)
    assert sorted(got) == [(-1, 0), (3, -2)] and nbt.get(got[(3, -2)][0], "id") == "minecraft:cow"


# ------------------------------------------------------------------ LCE player ids


@pytest.mark.parametrize("platform, pid, warned", [
    ("xbox360", None, True), ("xboxone", None, True), ("wiiu", None, True), ("switch", None, True),
    ("win64", None, True), ("ps3", None, False), ("ps4", None, False), ("vita", None, False),
    ("xbox360", "15885783760619110653", False), ("wiiu", "72e5c982752611ebb2da010145153336", False),
    ("wiiu", "15885783760619110653", True), ("switch", "whatever", False), ("xbox360", "nick", True)])
def test_the_host_player_file_must_be_one_the_console_loads(tmp_path, platform, pid, warned):
    prog = Progress()
    src = SyntheticWorld(radius=1)
    w = LCEWriter(str(tmp_path / "o"), LCEWriteOptions(platform=platform, world_size=54, host_player_id=pid), prog)
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    assert any("player id" in m or "XUID" in m for m in prog.warnings) == warned, prog.warnings


# ------------------------------------------------------------------ Java targets and the other players


def test_java_targets_say_how_many_players_they_drop():
    from worldbridge.convert import _warn_single_player
    from worldbridge.selection import PlayerLink, Selection

    info = WorldInfo()
    for k in ("a", "b", "c", "d"):
        info.players[k] = nbt.CompoundTag()
    prog = Progress()
    _warn_single_player(info, TargetSpec(family="java"), Selection(), prog)
    assert any(m.startswith("3 players were not written") for m in prog.warnings), prog.warnings
    info.player_links = {"c": PlayerLink("c", uuid="1234")}
    prog = Progress()
    _warn_single_player(info, TargetSpec(family="java"), Selection(), prog)
    assert any(m.startswith("2 players were not written") for m in prog.warnings), prog.warnings
    prog = Progress()
    _warn_single_player(info, TargetSpec(family="lce"), Selection(), prog)
    assert not prog.warnings
