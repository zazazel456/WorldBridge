import gzip
import struct

import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.detect import detect
from worldbridge.lce.world import LCEWorld


def _indev(path, mobs=False):
    w, l, h = 40, 36, 64
    blocks = np.zeros((h, l, w), np.uint8)
    blocks[:30] = 1
    blocks[30] = 2
    blocks[31, 5, 7] = 54
    root = nbt.CompoundTag({
        "About": nbt.CompoundTag({"Name": nbt.StringTag("Indev Test"), "Author": nbt.StringTag("x")}),
        "Environment": nbt.CompoundTag({"TimeOfDay": nbt.ShortTag(0)}),
        "Map": nbt.CompoundTag({"Width": nbt.ShortTag(w), "Length": nbt.ShortTag(l), "Height": nbt.ShortTag(h),
                                "Spawn": nbt.ListTag([nbt.ShortTag(5), nbt.ShortTag(32), nbt.ShortTag(5)], 2),
                                "Blocks": nbt.ByteArrayTag(blocks.reshape(-1).view(np.int8)),
                                "Data": nbt.ByteArrayTag(np.zeros(blocks.size, np.int8))}),
        "Entities": nbt.ListTag([], 10),
        "TileEntities": nbt.ListTag([nbt.CompoundTag({
            "id": nbt.StringTag("Chest"), "Pos": nbt.IntTag(7 + (31 << 10) + (5 << 20)),
            "Items": nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(264), "Count": nbt.ByteTag(2),
                                                   "Damage": nbt.ShortTag(0), "Slot": nbt.ByteTag(0)})], 10)})], 10),
    })
    if mobs:  # Indev keeps Pos / Motion as floats
        fl = lambda *v: nbt.ListTag([nbt.FloatTag(x) for x in v], 5)
        for eid, pos in (("Pig", (10.5, 33.0, 12.5)), ("LocalPlayer", (5.5, 33.0, 5.5))):
            root["Entities"].append(nbt.CompoundTag({"id": nbt.StringTag(eid), "Pos": fl(*pos), "Motion": fl(0, 0, 0),
                                                     "Rotation": fl(0, 0)}))
    open(path, "wb").write(nbt.dump(root, "MinecraftLevel", compressed=True))


def test_indev_to_lce(tmp_path):
    src = tmp_path / "world.mclevel"
    _indev(str(src))
    assert detect(str(src)).kind == "indev"
    out = tmp_path / "out"
    convert(str(src), str(out), TargetSpec(family="lce", ring=False))
    w = LCEWorld(str(out))
    assert w.info.name == "Indev Test"
    c = w.read_chunk(0, 0, 0)
    assert c.blocks[29, 0, 0] == 1 and c.blocks[30, 0, 0] == 2 and c.blocks[31, 5, 7] == 54
    assert nbt.get(c.tile_entities[0], "x") == 7


def test_indev_float_positions_become_doubles(tmp_path):
    from worldbridge.java.finite import load_indev
    src = tmp_path / "world.mclevel"
    _indev(str(src), mobs=True)
    w = load_indev(str(src))
    for e in list(w.ents) + list(w.info.players.values()):
        for k in ("Pos", "Motion"):
            assert all(isinstance(v, nbt.DoubleTag) for v in e[k])
    assert nbt.pos_list(nbt.FloatTag(1.5), 2, nbt.DoubleTag(3.0)).list_data_type == 6


def test_indev_mobs_and_player_convert(tmp_path):
    src = tmp_path / "world.mclevel"
    _indev(str(src), mobs=True)
    convert(str(src), str(tmp_path / "lce"), TargetSpec(family="lce", ring=False))
    out = tmp_path / "java"
    res = convert(str(src), str(out), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.2"))
    assert res.chunks and not any("unreadable" in w for w in res.warnings)


def test_classic_v1(tmp_path):
    w, l, h = 32, 32, 16
    blocks = np.zeros((h, l, w), np.uint8)
    blocks[:4] = 1
    blocks[4, 3, 3] = 21  # red cloth
    name = b"Classic"
    raw = struct.pack(">IB", 0x271BB788, 1) + struct.pack(">H", len(name)) + name + struct.pack(">H", 1) + b"n"
    raw += struct.pack(">q", 0) + struct.pack(">hhh", w, l, h) + blocks.tobytes()
    src = tmp_path / "level.mine"
    src.write_bytes(gzip.compress(raw))
    out = tmp_path / "out"
    convert(str(src), str(out), TargetSpec(family="java", java_mode="dfu"))
    from worldbridge.java.numeric import JavaNumericWorld

    jw = JavaNumericWorld(str(out))
    c = jw.read_chunk(0, 0, 0)
    assert c.blocks[3, 0, 0] == 1 and c.blocks[4, 3, 3] == 35 and c.data[4, 3, 3] == 14
