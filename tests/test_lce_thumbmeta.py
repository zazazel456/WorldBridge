"""The host options of an LCE world live in a text chunk of the thumbnail PNG, not in level.dat: a thumbnail without
them starts the world Peaceful, with no PvP / TNT / fire spread (seen in game on neoLegacy: every hostile mob of a
converted Wii U / Vita / Java world vanished)."""
import struct
import zlib

import pytest

from worldbridge import nbt
from worldbridge.lce import thumbmeta as tm
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter, _default_thumbnail
from worldbridge.model import Progress

from .helpers import SyntheticWorld


def _level(**kw):
    d = {"Difficulty": nbt.ByteTag(2), "GameType": nbt.IntTag(0), "MapFeatures": nbt.ByteTag(1),
         "RandomSeed": nbt.LongTag(5)}
    d.update(kw)
    return nbt.CompoundTag(d)


def _png_with(text: bytes) -> bytes:
    base = _default_thumbnail()
    ihdr_end = 8 + 12 + 13
    c = struct.pack(">I", len(text)) + b"tEXt" + text + struct.pack(">I", zlib.crc32(b"tEXt" + text) & 0xFFFFFFFF)
    return base[:ihdr_end] + c + base[ihdr_end:]


def _chunks(png):
    i, out = 8, []
    while i < len(png):
        n, typ = struct.unpack(">I4s", png[i:i + 8])
        body = png[i + 8:i + 8 + n]
        assert struct.unpack(">I", png[i + 8 + n:i + 12 + n])[0] == zlib.crc32(typ + body) & 0xFFFFFFFF
        out.append((typ, body))
        i += 12 + n
    return out


def test_the_options_of_the_real_saves_are_reproduced():
    # PS3 (Normal, old generation: no world size) and PS4 (Easy, classic world), as the games wrote them
    assert tm.host_options(_level(), 0) == 0x3C8A
    assert tm.host_options(_level(Difficulty=nbt.ByteTag(1)), 54) == 0x103C89


def test_the_fields_of_the_level_are_set():
    v = tm.host_options(_level(Difficulty=nbt.ByteTag(3), GameType=nbt.IntTag(1), spawnBonusChest=nbt.ByteTag(1),
                               hasBeenInCreative=nbt.ByteTag(1), generatorName=nbt.StringTag("flat"),
                               MapFeatures=nbt.ByteTag(0)), 320)
    assert v & tm.DIFFICULTY == 3 and (v >> 4) & 3 == 1 and v & tm.BONUS_CHEST and v & tm.HAS_BEEN_IN_CREATIVE
    assert v & tm.FLAT and not v & tm.STRUCTURES and (v >> 20) & 7 == 4
    assert v & tm.PVP and v & tm.TNT and v & tm.FIRE_SPREADS          # the switches of a new world are on
    # a level without a difficulty: Easy, the game's default, never Peaceful
    assert tm.host_options(nbt.CompoundTag(), 54) & tm.DIFFICULTY == 1


def test_the_switches_of_the_source_are_kept_and_the_difficulty_follows_the_level():
    base = 0x3C8A & ~tm.PVP & ~tm.TNT
    v = tm.host_options(_level(Difficulty=nbt.ByteTag(0)), 54, base)
    assert not v & tm.PVP and not v & tm.TNT and v & tm.DIFFICULTY == 0


def test_the_text_chunk_is_written_and_replaced():
    png = tm.with_metadata(_default_thumbnail(), _level(), 54, 2340570047136252143)
    texts = tm.read_texts(png)
    assert texts["4J_SEED"] == "2340570047136252143" and texts["4J_HOSTOPTIONS"] == "103c8a"
    assert texts["4J_TEXTUREPACK"] == "0"
    assert [t for t, _ in _chunks(png)].count(b"tEXt") == 1 and _chunks(png)[-1][0] == b"IEND"
    # the pairs of a real thumbnail: the extra data and the load count stay, seed / options are the world's
    src = _png_with(b"4J_SEED\x001\x004J_HOSTOPTIONS\x003c8a\x004J_TEXTUREPACK\x000\x004J_EXTRADATA\x0088100b8\x004J_#LOADS\x004")
    out = tm.with_metadata(src, _level(Difficulty=nbt.ByteTag(1)), 54, 77)
    t = tm.read_texts(out)
    assert t["4J_SEED"] == "77" and t["4J_EXTRADATA"] == "88100b8" and t["4J_#LOADS"] == "4"
    assert int(t["4J_HOSTOPTIONS"], 16) & 3 == 1 and [x for x, _ in _chunks(out)].count(b"tEXt") == 1
    # not a PNG: left alone
    assert tm.with_metadata(b"nope", _level(), 54, 1) == b"nope"


@pytest.mark.parametrize("platform, name", [("win64", "thumbnails/thumbData.png"), ("ps4", "THUMB"),
                                            ("xboxone", "THUMB"), ("switch", "THUMB"), ("ps3", "THUMB")])
def test_every_png_target_writes_the_options(tmp_path, platform, name):
    src = SyntheticWorld(radius=1)
    src.info.level["Difficulty"] = nbt.ByteTag(3)
    w = LCEWriter(str(tmp_path / platform), LCEWriteOptions(platform=platform, world_size=54), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    t = tm.read_texts(open(str(tmp_path / platform / name), "rb").read())
    assert int(t["4J_HOSTOPTIONS"], 16) & 3 == 3 and t["4J_SEED"] == "12345"
    # and the thumbnail is found again by the reader, still a valid PNG
    world = LCEWorld(str(tmp_path / platform), "xboxone" if platform == "xboxone" else None)
    assert world.info.thumbnail_png and tm.read_texts(world.info.thumbnail_png)["4J_SEED"] == "12345"
