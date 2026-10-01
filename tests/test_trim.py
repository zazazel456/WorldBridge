"""World trim (InhabitedTime)."""
import os

import numpy as np
import pytest

from worldbridge import nbt, trim
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.java.region import JavaRegion
from worldbridge.model import OVERWORLD, Progress
from worldbridge.selection import Selection

from .helpers import SyntheticWorld

MIN = 60 * 20


def _java_world(path, kind="anvil", forced=()):
    """8x8 chunks around the origin; only the 2x2 chunks at (2..3, 2..3) were really used, and
    (-4, -4) was visited for 30 s.  Spawn at chunk (0, 0)."""
    src = SyntheticWorld(radius=4)
    read = src.read_chunk

    def read_chunk(dim, cx, cz):
        c = read(dim, cx, cz)
        c.inhabited_time = 10 * MIN if 2 <= cx <= 3 and 2 <= cz <= 3 else 600 if (cx, cz) == (-4, -4) else 0
        return c

    src.read_chunk = read_chunk
    w = JavaNumericWriter(str(path), JavaWriteOptions(kind=kind), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    if forced:
        longs = np.array([(x & 0xFFFFFFFF) | ((z & 0xFFFFFFFF) << 32) for x, z in forced], np.uint64).view(np.int64)
        os.makedirs(os.path.join(str(path), "data"), exist_ok=True)
        root = nbt.CompoundTag({"data": nbt.CompoundTag({"Forced": nbt.LongArrayTag(longs)})})
        with open(os.path.join(str(path), "data", "chunks.dat"), "wb") as f:
            f.write(nbt.dump(root, "", compressed=True))
    return str(path)


def test_durations():
    assert trim.parse_duration("1m") == MIN and trim.parse_duration("30s") == 600
    assert trim.parse_duration("2h") == 2 * 3600 * 20 and trim.parse_duration("1200") == 1200
    assert trim.format_ticks(MIN) == "1 min" and trim.format_ticks(600) == "30 s"
    with pytest.raises(ValueError):
        trim.parse_duration("tanto")


def test_scan_and_plan(tmp_path):
    world = _java_world(tmp_path / "w", forced=[(-3, 3)])
    sc = trim.scan(world)
    assert sc.can_copy and len(sc.inhabited[OVERWORLD]) == 64
    assert sc.inhabited[OVERWORLD][(2, 2)] == 10 * MIN and sc.inhabited[OVERWORLD][(-4, -4)] == 600
    assert sc.forced[OVERWORLD] == {(-3, 3)}
    bare = trim.keep_set(sc, OVERWORLD, trim.TrimOptions(ring=0, spawn_radius=-1, keep_forced=False))
    assert bare == {(2, 2), (2, 3), (3, 2), (3, 3)}
    # defaults: 1 chunk ring (clipped to existing chunks), spawn ±2 around chunk (0, 0), forced chunk
    keep = trim.keep_set(sc, OVERWORLD)
    ring = {(x, z) for x in range(1, 4) for z in range(1, 4)}
    spawn = {(x, z) for x in range(-3, 4) for z in range(-3, 4)}  # spawn ±2 grown by the ring
    forced = {(x, z) for x in range(-4, -1) for z in range(2, 4)}
    assert keep == ring | spawn | forced
    assert (-4, -4) not in keep  # only 30 seconds
    assert (-4, -4) in trim.keep_set(sc, OVERWORLD, trim.TrimOptions(min_ticks=600, ring=0, spawn_radius=-1))


def test_trimmed_copy_keeps_chunks_byte_for_byte(tmp_path):
    world = _java_world(tmp_path / "w")
    sc = trim.scan(world)
    keep = trim.plan(sc, trim.TrimOptions(ring=0, spawn_radius=-1))
    out = str(tmp_path / "trimmed")
    removed = trim.trimmed_copy(world, out, keep)
    assert removed == 60
    a = JavaRegion(os.path.join(world, "region", "r.0.0.mca"))
    b = JavaRegion(os.path.join(out, "region", "r.0.0.mca"))
    assert sorted(b.chunks()) == [(2, 2), (2, 3), (3, 2), (3, 3)]
    assert all(a.read(x, z) == b.read(x, z) for x, z in b.chunks())
    assert not os.path.exists(os.path.join(out, "region", "r.-1.-1.mca"))  # emptied region file removed
    assert os.path.isfile(os.path.join(out, "level.dat")) and os.path.isfile(os.path.join(world, "region", "r.-1.-1.mca"))


def test_convert_with_trim_and_selection(tmp_path):
    world = _java_world(tmp_path / "w")
    out = str(tmp_path / "conv")
    t = TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12",
                   trim=trim.TrimOptions(ring=0, spawn_radius=-1), ring=False,
                   selection=Selection(chunks={OVERWORLD: {(2, 2), (3, 3), (0, 0)}}))
    convert(world, out, t)
    got = sorted(JavaRegion(os.path.join(out, "region", "r.0.0.mca")).chunks())
    assert got == [(2, 2), (3, 3)]  # trim inside the chunks chosen on the map


def test_formats_without_inhabited_time(tmp_path):
    world = _java_world(tmp_path / "old", kind="mcregion")
    with pytest.raises(trim.TrimUnavailable):
        trim.scan(world)
