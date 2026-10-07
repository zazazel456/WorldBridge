"""Format detection: single-file worlds inside folders, unsupported / broken worlds reported with a
message, version labels, and a CLI that never answers with a traceback."""
import gzip
import os
import struct

import numpy as np
import pytest

from worldbridge import nbt
from worldbridge.cli import main
from worldbridge.detect import UnsupportedWorld, detect, numeric_label
from worldbridge.lce.container import PLATFORMS, SaveContainer, find_main_file

from .test_old_formats import _indev

LFS = (b"version https://git-lfs.github.com/spec/v1\n"
       b"oid sha256:4d7a214614ab2935c943f9e0ff69d22eadbb8f32b1258daaa5e2ca24d17e2393\nsize 1234\n")


def _classic_v1(w=32, l=32, h=16) -> bytes:
    blocks = np.zeros((h, l, w), np.uint8)
    blocks[:4] = 1
    name = b"Classic"
    raw = struct.pack(">IB", 0x271BB788, 1) + struct.pack(">H", len(name)) + name + struct.pack(">H", 1) + b"n"
    return raw + struct.pack(">q", 0) + struct.pack(">hhh", w, l, h) + blocks.tobytes()


def _bedrock_level_dat(path, storage: int, **extra):
    data = nbt.CompoundTag({"LevelName": nbt.StringTag("t"), "StorageVersion": nbt.IntTag(storage), **extra})
    body = nbt.dump(data, little_endian=True)
    with open(path, "wb") as f:
        f.write(struct.pack("<II", storage, len(body)) + body)


def _java_level_dat(path, **data):
    root = nbt.CompoundTag({"Data": nbt.CompoundTag({"LevelName": nbt.StringTag("t"), **data})})
    with open(path, "wb") as f:
        f.write(nbt.dump(root, compressed=True))


def _lce_save(platform: str) -> bytes:
    c = SaveContainer(PLATFORMS[platform], files={"level.dat": nbt.dump(nbt.CompoundTag({"Data": nbt.CompoundTag()}))})
    return c.encode()


# ------------------------------------------------------------------ the CLI reports, never crashes


@pytest.mark.parametrize("cmd", ["info", "players", "trim", "convert"])
def test_cli_reports_unrecognised_worlds_without_a_traceback(tmp_path, capsys, cmd):
    junk = tmp_path / "junk"
    junk.mkdir()
    (junk / "notes.txt").write_text("hello")
    argv = [cmd, str(junk)] + ([str(tmp_path / "out"), "--to", "java"] if cmd == "convert" else [])
    assert main(["--lang", "en"] + argv) == 1
    out = capsys.readouterr().out
    assert "not recognised" in out and "Traceback" not in out
    assert main(["--lang", "it"] + argv[:1] + [str(junk)] + argv[2:]) == 1
    assert "riconosciuto" in capsys.readouterr().out


def test_cli_reports_unreadable_lce_saves(tmp_path, capsys):
    bad = tmp_path / "saveData.ms"
    bad.write_bytes(b"\0" * 8 + b"\x78\x9c" + b"\xff" * 40)        # a compressed container that is not one
    assert main(["--lang", "en", "players", str(bad)]) == 1
    assert capsys.readouterr().out.startswith("Error: ")


# ------------------------------------------------------------------ broken / unsupported worlds


def test_git_lfs_pointer_instead_of_level_dat(tmp_path, capsys):
    w = tmp_path / "w"
    (w / "region").mkdir(parents=True)
    (w / "level.dat").write_bytes(LFS)
    with pytest.raises(UnsupportedWorld, match="Git LFS pointer"):
        detect(str(w))
    with pytest.raises(UnsupportedWorld, match="Git LFS pointer"):
        detect(str(w / "level.dat"))
    for cmd in ("info", "players"):
        assert main(["--lang", "en", cmd, str(w)]) == 1
        out = capsys.readouterr().out
        assert "level.dat is a Git LFS pointer" in out and "DataVersion" not in out
    assert main(["--lang", "it", "info", str(w)]) == 1
    assert "puntatore Git LFS" in capsys.readouterr().out


def test_level_dat_that_is_not_nbt(tmp_path):
    w = tmp_path / "w"
    (w / "region").mkdir(parents=True)
    (w / "level.dat").write_bytes(gzip.compress(b"\x07garbage that is not NBT"))
    with pytest.raises(UnsupportedWorld, match="level.dat is not a valid NBT file"):
        detect(str(w))


def test_new_nintendo_3ds_world_is_not_supported(tmp_path, capsys):
    w = tmp_path / "3ds"
    for sub in ("db/cdb", "db/vdb"):
        (w / sub).mkdir(parents=True)
    (w / "db" / "cdb" / "slt0.cdb").write_bytes(b"\x01\x00\x01\x00" + bytes(60))
    (w / "db" / "savemarker").write_bytes(b"\xfe\xfe\x04\x0c")
    _bedrock_level_dat(w / "level.dat", 5)
    with pytest.raises(UnsupportedWorld, match="New Nintendo 3DS Edition worlds are not supported"):
        detect(str(w))
    assert main(["--lang", "en", "players", str(w)]) == 1
    assert "3DS" in capsys.readouterr().out


def test_bedrock_world_without_terrain(tmp_path):
    w = tmp_path / "template"
    (w / "behavior_packs" / "pack").mkdir(parents=True)
    _bedrock_level_dat(w / "level.dat", 10)
    (w / "levelname.txt").write_text("simple World")
    with pytest.raises(UnsupportedWorld, match="has no terrain"):
        detect(str(w))


def test_bedrock_db_without_leveldb(tmp_path):
    w = tmp_path / "w"
    (w / "db").mkdir(parents=True)
    _bedrock_level_dat(w / "level.dat", 10)
    with pytest.raises(UnsupportedWorld, match="no LevelDB database"):
        detect(str(w))


# ------------------------------------------------------------------ labels


def test_pocket_edition_leveldb_label(tmp_path):
    w = tmp_path / "pe"
    (w / "db").mkdir(parents=True)
    (w / "db" / "CURRENT").write_text("MANIFEST-000002\n")
    _bedrock_level_dat(w / "level.dat", 4)
    d = detect(str(w))
    assert d.kind == "bedrock" and d.description == "Pocket Edition 0.9 – 0.16 (LevelDB)"
    _bedrock_level_dat(w / "level.dat", 5, lastOpenedWithVersion=nbt.ListTag([nbt.IntTag(0), nbt.IntTag(16)]))
    assert detect(str(w)).description == "Pocket Edition 0.9 – 0.16 (LevelDB)"
    _bedrock_level_dat(w / "level.dat", 8, lastOpenedWithVersion=nbt.ListTag([nbt.IntTag(1), nbt.IntTag(11)]))
    assert detect(str(w)).description == "Bedrock Edition (LevelDB)"


def test_java_labels():
    data = nbt.CompoundTag
    named = data({"DataVersion": nbt.IntTag(1343), "Version": data({"Name": nbt.StringTag("1.12.2")})})
    assert numeric_label("anvil", named) == "Java Edition 1.12.2 (Anvil)"
    assert numeric_label("anvil", data({"DataVersion": nbt.IntTag(512)})) == "Java Edition 1.10.2 (Anvil)"
    assert numeric_label("anvil", data({"DataVersion": nbt.IntTag(500)})) == \
        "Java Edition 1.9 – 1.12.2 (Anvil, DataVersion 500)"
    assert numeric_label("anvil", data()) == "Java Edition 1.2 – 1.12.2 (Anvil)"
    assert numeric_label("mcregion", data()) == "Java Edition Beta 1.3 – Java 1.1 (McRegion)"


def test_modern_label_shows_the_version_name(tmp_path):
    w = tmp_path / "w"
    (w / "region").mkdir(parents=True)
    _java_level_dat(w / "level.dat", DataVersion=nbt.IntTag(3465),
                    Version=nbt.CompoundTag({"Name": nbt.StringTag("1.20.1"), "Id": nbt.IntTag(3465)}))
    d = detect(str(w))
    assert d.kind == "java_modern" and d.description == "Java Edition 1.20.1 (DataVersion 3465)"


# ------------------------------------------------------------------ single-file worlds in a folder


def test_classic_level_dat_in_a_folder(tmp_path):
    w = tmp_path / "classic"
    w.mkdir()
    (w / "level.dat").write_bytes(gzip.compress(_classic_v1()))
    for p in (w, w / "level.dat"):
        d = detect(str(p))
        assert d.kind == "classic" and d.path == str(w / "level.dat")


@pytest.mark.parametrize("name", ["city.mine", "server_level.dat", "Dojo_64_64_128.dat"])
def test_classic_file_in_a_folder(tmp_path, name):
    (tmp_path / "w").mkdir()
    (tmp_path / "w" / name).write_bytes(gzip.compress(_classic_v1()))
    d = detect(str(tmp_path / "w"))
    assert d.kind == "classic" and d.path.endswith(name)


def test_uncompressed_classic_without_extension(tmp_path):
    from worldbridge.java.classic import ClassicWorld

    (tmp_path / "w").mkdir()
    src = tmp_path / "w" / "creative512_256_32"
    src.write_bytes(_classic_v1())
    for p in (src, tmp_path / "w"):
        d = detect(str(p))
        assert d.kind == "classic" and d.path == str(src)
    c = ClassicWorld(str(src)).read_chunk(0, 0, 0)
    assert c.blocks[3, 0, 0] == 1 and c.blocks[4, 0, 0] == 0


def test_indev_file_in_a_folder(tmp_path):
    (tmp_path / "w").mkdir()
    _indev(str(tmp_path / "w" / "hell.mclevel"))
    d = detect(str(tmp_path / "w"))
    assert d.kind == "indev" and d.path.endswith("hell.mclevel")


def test_two_single_file_worlds_are_ambiguous(tmp_path):
    (tmp_path / "w").mkdir()
    for n in ("a.mine", "b.mine"):
        (tmp_path / "w" / n).write_bytes(gzip.compress(_classic_v1()))
    assert detect(str(tmp_path / "w")) is None


@pytest.mark.parametrize("platform,files", [
    ("wiiu", {"250703210031": None, "250703210031.ext": b"\0N\0e\0w\0 \0W\0o\0r\0l\0d\0\0",
              "options_72e5c982752611ebb2da010145153336": b"\0\x12\0ddd2"}),
    ("wiiu", {"savegame.wii": None}),
    ("vita", {"GAMEDATA-2.bin": None}),
])
def test_console_save_names_in_a_folder(tmp_path, platform, files):
    w = tmp_path / "save"
    w.mkdir()
    for name, data in files.items():
        (w / name).write_bytes(_lce_save(platform) if data is None else data)
    main_name = next(n for n, d in files.items() if d is None)
    assert find_main_file(str(w)) == str(w / main_name)
    d = detect(str(w))
    assert d is not None and d.kind == "lce"
    assert SaveContainer.load(str(w)).platform.key == platform


def test_several_wiiu_saves_in_one_folder_are_ambiguous(tmp_path):
    for stamp in ("250703210031", "250703220028"):
        (tmp_path / stamp).write_bytes(_lce_save("wiiu"))
        (tmp_path / (stamp + ".ext")).write_bytes(b"\0x\0\0")
    assert find_main_file(str(tmp_path)) is None


def test_one_world_among_several_subfolders(tmp_path):
    (tmp_path / "Save2025.bin").mkdir()
    (tmp_path / "Save2025.bin" / "savegame.dat").write_bytes(_lce_save("xbox360"))
    (tmp_path / "chunk").mkdir()
    (tmp_path / "chunk" / "test.chunk").write_bytes(b"\x0a\0\0\0")
    d = detect(str(tmp_path))
    assert d is not None and d.kind == "lce" and d.path == str(tmp_path / "Save2025.bin")
