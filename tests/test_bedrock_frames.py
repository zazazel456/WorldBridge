"""Item frames: blocks with a block entity in Bedrock, entities in Java.

* Java has no block for Bedrock's frame: PyMCTranslate's stand-in is stone, which pops the frame off
  (and keeps a Java -> Bedrock conversion from placing it).  A Java target gets air.
* Bedrock palettes differ by version: block states with ``item_frame_photo_bit`` from 1.17.30, without
  it from 1.13, ``{name, val}`` palettes in 1.2.13 - 1.12 and plain ids and data nibbles before.
"""
import struct

import amulet_nbt as an
import numpy as np

from worldbridge import items, nbt
from worldbridge.bedrock import extra, terrain


class FakeDb(dict):
    def get(self, key):
        return dict.get(self, key)

    def put(self, key, value):
        self[key] = value


def _prefix(cx, cz):
    return struct.pack("<ii", cx, cz)


def _key(cx=0, cz=0, sy=0):
    return _prefix(cx, cz) + bytes([terrain.SUBCHUNK]) + struct.pack("b", sy)


def _states_entry(name, **states):
    return an.CompoundTag({"name": an.StringTag(name), "states": an.CompoundTag(states),
                           "version": an.IntTag(18168865)})


def _sub(palette, version=9):
    return terrain.SubChunk(version, 0, [terrain.Storage(np.zeros(4096, np.int64), palette)]).encode()


def _frame_states(v):
    name, states, _id = extra.frame_block(v, 2, False)
    return name, {k: val.py_int for k, val in states.items()}


def test_frame_states_follow_the_version():
    assert _frame_states((1, 21, 60)) == ("minecraft:frame", {"facing_direction": 2, "item_frame_map_bit": 0,
                                                              "item_frame_photo_bit": 0})
    assert _frame_states((1, 17, 30))[1].keys() == {"facing_direction", "item_frame_map_bit", "item_frame_photo_bit"}
    for v in ((1, 13, 0), (1, 16, 220), (1, 17, 10)):
        assert _frame_states(v) == ("minecraft:frame", {"facing_direction": 2, "item_frame_map_bit": 0}), v
    for v in ((1, 2, 0), (1, 9, 0), (1, 12, 0)):          # block_data: east 0, west 1, south 2, north 3, +8 map
        name, states, nid = extra.frame_block(v, 2, False)
        assert (name, dict(states), nid) == ("minecraft:frame", {"block_data": an.IntTag(3)}, 199), v
        assert extra.frame_block(v, 5, True)[1]["block_data"].py_int == 8
        assert extra.frame_block(v, 4, False)[1]["block_data"].py_int == 1
        assert extra.frame_block(v, 1, False) is None      # floor / ceiling frames: Bedrock 1.13+
    assert extra.frame_block((1, 17, 0), 3, False, True)[0] == "minecraft:glow_frame"


def _prefix_of(cx, cz):
    return _prefix(cx, cz)


def test_a_frame_goes_where_there_is_air_or_the_old_stone():
    stone = _states_entry("minecraft:stone", stone_type=an.StringTag("stone"))
    granite = _states_entry("minecraft:stone", stone_type=an.StringTag("granite"))
    air = _states_entry("minecraft:air")
    blk = extra.frame_block((1, 21, 60), 3, False)
    # index 0 air, 1 stone, 2 granite: blocks x 0 (air), x 1 (stone), x 2 (granite)
    db = FakeDb()
    sc = terrain.SubChunk.decode(_sub([air, stone, granite]))
    sc.storages[0].idx[1 << 8] = 1
    sc.storages[0].idx[2 << 8] = 2
    db[_key()] = sc.encode()
    blocks = {(0, 0, 0): blk, (1, 0, 0): blk, (2, 0, 0): blk}
    assert terrain.set_blocks(db, _prefix_of, blocks) == [(0, 0, 0)]
    assert terrain.set_blocks(db, _prefix_of, blocks, replace_stone=True) == [(1, 0, 0)]   # (0,0,0) has its frame now


def test_set_blocks_writes_each_palette_form():
    # block states, without the photo bit before 1.17.30
    db = FakeDb()
    db[_key()] = _sub([_states_entry("minecraft:air")])
    blk = extra.frame_block((1, 16, 220), 4, True)
    assert terrain.set_blocks(db, _prefix_of, {(1, 2, 3): blk}) == [(1, 2, 3)]
    pal = terrain.SubChunk.decode(db[_key()]).storages[0].palette
    assert pal[-1]["name"].py_str == "minecraft:frame" and set(pal[-1]["states"].keys()) == {
        "facing_direction", "item_frame_map_bit"} and "version" in pal[-1]
    # {name, val} palettes (1.2.13 - 1.12)
    db = FakeDb()
    db[_key()] = _sub([an.CompoundTag({"name": an.StringTag("minecraft:air"), "val": an.ShortTag(0)})], version=8)
    blk = extra.frame_block((1, 12, 0), 5, True)
    assert terrain.set_blocks(db, _prefix_of, {(1, 2, 3): blk}) == [(1, 2, 3)]
    sc = terrain.SubChunk.decode(db[_key()])
    entry = sc.storages[0].palette[int(sc.storages[0].idx[1 << 8 | 3 << 4 | 2])]
    assert entry["name"].py_str == "minecraft:frame" and entry["val"].py_int == 8 and "states" not in entry
    # a block of the wrong form for the palette is not placed
    assert terrain.set_blocks(db, _prefix_of, {(1, 2, 4): extra.frame_block((1, 21, 60), 3, False)}) == []
    # before 1.2.13: ids and data nibbles
    db = FakeDb()
    db[_key()] = bytes(1 + 4096 + 2048 + 4096)
    blk = extra.frame_block((1, 2, 0), 4, False)
    n = 1 << 8 | 3 << 4 | 2
    assert terrain.set_blocks(db, _prefix_of, {(1, 2, 3): blk}) == [(1, 2, 3)]
    raw = db[_key()]
    assert terrain.legacy_block_at(raw, n) == (199, 1) and len(raw) == 1 + 4096 + 2048 + 4096
    assert terrain.set_blocks(db, _prefix_of, {(1, 2, 3): blk}) == []           # not air any more
    db[_key()] = bytes([0, 1]) + bytes(4095) + bytes(2048)
    assert terrain.legacy_block_at(db[_key()], 0) == (1, 0)                       # id 1: stone
    assert terrain.set_blocks(db, _prefix_of, {(0, 0, 0): blk}, replace_stone=True) == [(0, 0, 0)]


def test_old_frames_are_read_back_with_their_facing():
    for data, f3 in ((0, 5), (1, 4), (2, 3), (3, 2), (11, 2)):
        te = nbt.CompoundTag({"id": nbt.StringTag("ItemFrame"), "x": nbt.IntTag(1), "y": nbt.IntTag(2), "z": nbt.IntTag(3)})
        db = FakeDb()
        db[_key()] = _sub([an.CompoundTag({"name": an.StringTag("minecraft:frame"), "val": an.ShortTag(data)})], version=8)
        assert extra.frame_canon(db, _prefix(0, 0), te)["facing"] == f3
        raw = bytearray(1 + 4096 + 2048)
        n = 1 << 8 | 3 << 4 | 2
        raw[1 + n] = 199
        raw[4097 + (n >> 1)] = data << ((n & 1) * 4)
        db[_key()] = bytes(raw)
        assert extra.frame_canon(db, _prefix(0, 0), te)["facing"] == f3
    db[_key()] = _sub([_states_entry("minecraft:frame", facing_direction=an.IntTag(4))])
    assert extra.frame_canon(db, _prefix(0, 0), te)["facing"] == 4


def test_java_targets_get_air_where_bedrock_has_a_frame():
    from amulet.api.block import Block

    from worldbridge import amulet_bridge as ab

    ab._install_legacy_fallback()
    tm = items._tm()
    for ver in ((1, 16, 220), (1, 21, 60)):
        u = tm.get_version("bedrock", ver).block.to_universal(Block("minecraft", "frame", {
            "facing_direction": an.IntTag(2), "item_frame_map_bit": an.ByteTag(0)}))[0]
        for jv in ((1, 12, 2), (1, 13, 2), (1, 20, 4), items._latest("java")):
            assert tm.get_version("java", jv).block.from_universal(u)[0].base_name == "air", (ver, jv)
