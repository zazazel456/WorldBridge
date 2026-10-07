"""Broken input, untouched sources, Pocket Edition player (found by tools/matrix.py)."""
import gzip
import hashlib
import os
import zlib

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import Progress

from .helpers import SyntheticWorld


def _anvil(path):
    src = SyntheticWorld(radius=2)
    w = JavaNumericWriter(str(path), JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    return str(path)


def _digest(folder):
    h = {}
    for root, _d, files in os.walk(folder):
        for f in files:
            p = os.path.join(root, f)
            h[os.path.relpath(p, folder)] = hashlib.md5(open(p, "rb").read()).hexdigest()
    return h


def test_corrupted_chunk_is_skipped_with_a_warning(tmp_path):
    world = _anvil(tmp_path / "w")
    p = os.path.join(world, "region", "r.0.0.mca")
    data = bytearray(open(p, "rb").read())
    off = (int.from_bytes(data[0:4], "big") >> 8) * 4096
    data[off + 5:off + 100] = b"\xAB" * 95
    open(p, "wb").write(data)
    res = convert(world, str(tmp_path / "out"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    assert res.chunks == 15
    assert any("unreadable" in w for w in res.warnings)


def test_chunks_compressed_twice_are_read(tmp_path):
    """MCEdit 2 wrote zlib payloads that hold a gzip stream."""
    world = _anvil(tmp_path / "w")
    p = os.path.join(world, "region", "r.0.0.mca")
    reg = JavaRegion(p)
    raws = {c: reg.read(*c) for c in reg.chunks()}
    wr = RegionWriter()
    for c, raw in raws.items():
        wr.put_compressed(c[0], c[1], zlib.compress(gzip.compress(raw)))
    wr.write(p)
    reg = JavaRegion(p)
    assert {c: reg.read(*c) for c in reg.chunks()} == raws
    res = convert(world, str(tmp_path / "out"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    assert res.chunks == 16 and not any("unreadable" in w for w in res.warnings)


def test_modern_sources_are_never_touched(tmp_path):
    base = _anvil(tmp_path / "w")
    modern = str(tmp_path / "modern")
    convert(base, modern, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 1)))
    for f in ("session.lock",):
        if os.path.exists(os.path.join(modern, f)):
            os.remove(os.path.join(modern, f))
    before = _digest(modern)
    convert(modern, str(tmp_path / "lce"), TargetSpec(family="lce", ring=False))
    assert _digest(modern) == before  # no session.lock, no rewritten file
    bedrock = str(tmp_path / "bedrock")
    convert(base, bedrock, TargetSpec(family="bedrock"))
    before = _digest(bedrock)
    convert(bedrock, str(tmp_path / "back"), TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    assert _digest(bedrock) == before  # LevelDB never opened in place


def test_pocket_edition_player_is_written(tmp_path):
    base = _anvil(tmp_path / "w")
    pe = str(tmp_path / "pe")
    res = convert(base, pe, TargetSpec(family="pe_old"))
    raw = open(os.path.join(pe, "level.dat"), "rb").read()
    lvl = nbt.load(raw[8:], little_endian=True, compressed=False).tag
    p = lvl["Player"]
    assert len(p["Pos"]) == 3 and 0 <= float(p["Pos"][0].py_data) < 256
    assert any("inventory" in w for w in res.warnings)
    back = str(tmp_path / "back")
    convert(pe, back, TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    player = nbt.load(open(os.path.join(back, "level.dat"), "rb").read()).tag["Data"]["Player"]
    assert isinstance(player["Pos"][0], nbt.DoubleTag)
