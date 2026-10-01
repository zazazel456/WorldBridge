"""World management: the documents of every kind of world, read, edited and saved back."""
import os
import struct

from worldbridge import nbt
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.manage import open_world
from worldbridge.model import Progress

from .helpers import SyntheticWorld


def _field(w, label):
    return next(f for f in w.quick_fields() if f.label == label)


def test_java_settings_are_edited_and_saved_with_a_backup(tmp_path):
    src = SyntheticWorld(radius=1)
    out = str(tmp_path / "java")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    wr.add_chunk(0, src.read_chunk(0, 0, 0))
    wr.finish(src.info)
    w = open_world(out)
    assert w.kind == "java" and w.get(_field(w, "Name")) == "Test World"
    w.set(_field(w, "Game mode"), 2)
    w.set(_field(w, "Spawn Y"), 99)
    w.set(_field(w, "Seed"), -42)
    w.save()
    assert os.path.isfile(os.path.join(out, "level.dat.wb-backup"))
    again = open_world(out)
    assert again.get(_field(again, "Game mode")) == 2
    assert again.get(_field(again, "Spawn Y")) == 99 and again.get(_field(again, "Seed")) == -42


def test_old_pocket_edition_level_dat(tmp_path):
    root = nbt.CompoundTag({"LevelName": nbt.StringTag("PE"), "RandomSeed": nbt.LongTag(7), "GameType": nbt.IntTag(0),
                            "SpawnX": nbt.IntTag(1), "SpawnY": nbt.IntTag(64), "SpawnZ": nbt.IntTag(1)})
    body = nbt.dump(root, "", little_endian=True)
    world = tmp_path / "pe"
    world.mkdir()
    (world / "level.dat").write_bytes(struct.pack("<ii", 3, len(body)) + body)
    (world / "chunks.dat").write_bytes(b"\0" * 4096)
    w = open_world(str(world))
    assert w.kind == "pe_old" and w.get(_field(w, "Seed")) == 7
    w.set(_field(w, "Game mode"), 1)
    w.save()
    raw = (world / "level.dat").read_bytes()
    assert struct.unpack_from("<i", raw)[0] == 3                                    # the header is kept
    assert int(nbt.get(nbt.load(raw[8:], little_endian=True).tag, "GameType")) == 1


def test_lce_level_dat_inside_the_save(tmp_path):
    src = SyntheticWorld(radius=1)
    out = tmp_path / "lce"
    wr = LCEWriter(str(out), LCEWriteOptions(platform="win64", world_size=54), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    w = open_world(str(out))
    assert w.kind == "lce" and not w.read_only
    w.set(_field(w, "Name"), "Rinominato")
    w.save()
    assert LCEWorld(str(out)).info.name == "Rinominato"
    assert len(LCEWorld(str(out)).chunk_coords(0)) == len(src.chunk_coords(0))    # the chunks are untouched
