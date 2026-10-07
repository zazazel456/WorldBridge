"""Xbox 360 savegame.dat headers.

Every real Xbox 360 save (TU0 to TU75, loose or inside a CON package) starts with
``[BE u32 size][BE u64 decompressed size]``, then the XMemCompress LZX frames and one zero byte (the
u32 counts all of that, header included), then a few bytes of slack (zeros or leftovers) up to the end
of the file.  WorldBridge up to 0.2.x wrote ``[u32 0][BE u32 size]`` instead.  The files are built here with
the real layout (no real save is shipped).  Written layouts above ``X360_REAL_LZX_MAX`` use LZX
uncompressed blocks (the pure-Python compressor takes minutes on tens of MB)."""
import random
import struct

import pytest

from worldbridge.detect import detect
from worldbridge.lce import compression as comp
from worldbridge.lce import container as cont_mod
from worldbridge.lce.container import PLATFORMS, SaveContainer, find_main_file, looks_like_lce, x360_header
from worldbridge.lce.vendor import lzx_codec

from .test_stfs import _package


def _listing():
    rnd = random.Random(360)
    files = {
        "level.dat": b"\x0a\x00\x00" + bytes(rnd.getrandbits(8) for _ in range(300)) + b"\x00",
        "r.0.0.mcr": bytes(rnd.choice(b"\x00\x00\x00\x01\x02\x07\x09") for _ in range(70_000)),  # > 2 LZX frames
        "players/2535405650000001.dat": b"player" * 50,
    }
    cont = SaveContainer(PLATFORMS["xbox360"], 11, 11, dict(files), timestamps=dict.fromkeys(files, 1))
    return cont.build_listing(), files


def _real_x360(listing, slack=b"\x5a\x00\x13" * 40):
    body = comp.xmem_compress(listing) + b"\x00"
    return struct.pack(">IQ", 12 + len(body), len(listing)) + body + slack


def _check(cont, files):
    assert cont.platform.key == "xbox360"
    assert (cont.original_version, cont.version) == (11, 11)
    assert cont.files == files


def test_reads_the_header_of_real_saves(tmp_path):
    listing, files = _listing()
    raw = _real_x360(listing)
    assert raw[4:8] == b"\0\0\0\0" and raw[:4] != b"\0\0\0\0"
    assert x360_header(raw) == (len(raw) - 120, len(listing))
    folder = tmp_path / "Save20250429062129.bin"
    folder.mkdir()
    (folder / "savegame.dat").write_bytes(raw)
    assert looks_like_lce(str(folder))
    d = detect(str(folder / "savegame.dat"))
    assert d is not None and d.kind == "lce"
    _check(SaveContainer.load(str(folder)), files)


def test_reads_a_real_header_inside_a_con_package(tmp_path):
    listing, files = _listing()
    pkg = tmp_path / "Save20231016154131.bin"
    pkg.write_bytes(_package([("savegame.dat", _real_x360(listing))], 1, False))
    assert detect(str(pkg)).kind == "lce"
    cont = SaveContainer.load(str(pkg))
    _check(cont, files)
    assert cont.display_name == "Mondo àè"


def test_still_reads_the_old_worldbridge_header(tmp_path):
    listing, files = _listing()
    old = struct.pack(">II", 0, len(listing)) + comp.xmem_compress(listing)
    (tmp_path / "savegame.dat").write_bytes(old)
    assert looks_like_lce(str(tmp_path))
    _check(SaveContainer.load(str(tmp_path)), files)


def test_writes_the_layout_of_real_saves(tmp_path):
    listing, files = _listing()
    cont = SaveContainer(PLATFORMS["xbox360"], 11, 11, dict(files), timestamps=dict.fromkeys(files, 1))
    raw = cont.encode()
    size, dsize = struct.unpack_from(">IQ", raw, 0)
    assert dsize == len(listing)
    assert size == len(raw) - 4 and raw[size - 1:] == bytes(5)   # frames, a zero byte, 4 bytes of slack
    assert comp.xmem_decompress(raw[12:size], dsize) == listing
    out = cont.save(str(tmp_path))
    _check(SaveContainer.load(out), files)


def test_other_headers_are_not_taken_for_xbox360():
    listing, _ = _listing()
    zlib_be = struct.pack(">II", 0, len(listing)) + comp.zlib_compress(listing)       # Wii U
    assert x360_header(zlib_be) is None
    ps3 = SaveContainer(PLATFORMS["ps3"], 11, 11, {"level.dat": b"x" * 100}).build_listing()
    assert x360_header(ps3) is None                                                       # file count -> huge u64
    real = _real_x360(listing, b"")
    assert x360_header(real) is not None
    assert x360_header(real[:-1]) is None                                                 # truncated file
    assert x360_header(real[:12] + b"\x00\x00" + real[14:]) is None                       # empty first frame
    bad = bytearray(real)
    struct.pack_into(">Q", bad, 4, 1 << 40)
    assert x360_header(bytes(bad)) is None                                                # absurd size


@pytest.mark.parametrize("platform", ["wiiu", "ps3", "vita", "win64", "ps4"])
def test_other_platforms_keep_their_detection(tmp_path, platform):
    listing, files = _listing()
    cont = SaveContainer(PLATFORMS[platform], 11, 11, dict(files))
    out = cont.save(str(tmp_path))
    if platform == "ps4":
        (tmp_path / "sce_sys").mkdir()                       # what tells a PS4 save from Windows64
    assert looks_like_lce(str(tmp_path))
    back = SaveContainer.load(out)
    assert back.files == files
    assert back.platform.key == platform


def test_players_of_the_oldest_saves(tmp_path):
    """Save version 1 (before TU1) keeps the player as players_<XUID>.dat at the top of the listing."""
    from worldbridge import nbt
    from worldbridge.lce.world import LCEWorld, save_players

    level = nbt.CompoundTag({"Data": nbt.CompoundTag({"LevelName": nbt.StringTag("world"), "SpawnY": nbt.IntTag(64)})})
    player = nbt.CompoundTag({"Pos": nbt.ListTag([nbt.DoubleTag(-141.0), nbt.DoubleTag(67.0), nbt.DoubleTag(-108.0)])})
    pdat = nbt.dump(player, "") + bytes(64)                  # the game pads the file
    cont = SaveContainer(PLATFORMS["xbox360"], 0, 2,  # (build_listing writes the v2+ table)
                         {"level.dat": nbt.dump(level, ""), "players_12771850921608919742.dat": pdat})
    (tmp_path / "savegame.dat").write_bytes(_real_x360(cont.build_listing()))
    world = LCEWorld(str(tmp_path))
    assert list(world.info.players) == ["12771850921608919742"]
    assert save_players(str(tmp_path)) == {"12771850921608919742": "12771850921608919742"}


def _big_files(total):
    rnd = random.Random(7)
    chunk = bytes(rnd.getrandbits(8) for _ in range(4096))
    return {"level.dat": b"\x0a\x00\x00" + chunk[:200] + b"\x00", "r.0.0.mcr": (chunk * (total // 4096 + 1))[:total]}


def test_big_container_is_stored_in_uncompressed_blocks_and_round_trips(tmp_path, monkeypatch):
    files = _big_files(cont_mod.X360_REAL_LZX_MAX + 100_000)
    cont = SaveContainer(PLATFORMS["xbox360"], 11, 11, dict(files), timestamps=dict.fromkeys(files, 1))
    calls = []
    real = lzx_codec._lzx_real_frames
    monkeypatch.setattr(lzx_codec, "_lzx_real_frames", lambda d: calls.append(len(d)) or real(d))
    raw = cont.encode()
    assert calls == []                                   # the pure-Python compressor was not run
    listing = cont.build_listing()
    size, dsize = struct.unpack_from(">IQ", raw, 0)
    assert dsize == len(listing) and len(raw) > len(listing)          # stored: a bit larger than the listing
    assert x360_header(raw) == (size, dsize)
    assert comp.xmem_decompress(raw[12:size], dsize) == listing
    _check(SaveContainer.load(cont.save(str(tmp_path))), files)


def test_small_container_still_gets_the_real_compressor(monkeypatch):
    listing, files = _listing()
    assert len(listing) < cont_mod.X360_REAL_LZX_MAX
    calls = []
    real = lzx_codec._lzx_real_frames
    monkeypatch.setattr(lzx_codec, "_lzx_real_frames", lambda d: calls.append(len(d)) or real(d))
    cont = SaveContainer(PLATFORMS["xbox360"], 11, 11, dict(files), timestamps=dict.fromkeys(files, 1))
    raw = cont.encode()
    assert calls == [len(listing)]
    assert len(raw) < len(listing)                       # really compressed
    _check(SaveContainer._decode(raw, "savegame.dat", None), files)


def test_xmem_never_runs_the_real_encoder_above_16_mib(monkeypatch):
    """The real encoder writes one verbatim block with a 24 bit size: it can never verify above 16 MiB."""
    def boom(_d):
        raise AssertionError("real encoder used")
    monkeypatch.setattr(lzx_codec, "_lzx_real_frames", boom)
    blob = bytes(range(251)) * 70_000                    # 17.6 MB
    assert len(blob) >= 1 << 24
    body = comp.xmem_compress(blob, max_real=1 << 40)
    assert comp.xmem_decompress(body, len(blob)) == blob


@pytest.mark.parametrize("n", [0, 1, 32767, 32768, 32769, 3 * 32768, 1_100_001])
def test_xmem_uncompressed_framing_round_trips(n):
    blob = bytes((i * 7 + (i >> 8)) & 0xFF for i in range(n))
    body = comp.xmem_compress(blob, max_real=0)          # always stored
    assert comp.xmem_decompress(body, n) == blob
    assert comp.xmem_decompress(comp.xmem_compress(blob), n) == blob


def test_finds_the_save_of_folders_as_found_on_disk(tmp_path):
    listing, files = _listing()
    raw = _real_x360(listing)
    gdp = tmp_path / "gdp"
    gdp.mkdir()
    (gdp / "savegame-first.dat").write_bytes(raw)                     # a renamed copy
    assert looks_like_lce(str(gdp))
    _check(SaveContainer.load(str(gdp)), files)
    root = tmp_path / "root"                                          # <root>/Save<date>.bin/savegame.dat
    (root / "Save20250429062129.bin").mkdir(parents=True)
    (root / "chunk").mkdir()
    (root / "Save20250429062129.bin" / "savegame.dat").write_bytes(raw)
    d = detect(str(root))                                             # detect picks the one save below
    assert d.kind == "lce" and d.path == str(root / "Save20250429062129.bin")
    _check(SaveContainer.load(d.path), files)
    two = tmp_path / "two"                                            # ambiguous: no guess
    for n in ("A.bin", "B.bin"):
        (two / n).mkdir(parents=True)
        (two / n / "savegame.dat").write_bytes(raw)
    assert find_main_file(str(two)) is None
