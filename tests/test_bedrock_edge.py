"""Blending the border of a Bedrock 1.18+ world made from a 1.18+ source (worldbridge/bedrock/edge.py)."""
import os
import struct
import numpy as np
import pytest
from leveldb import LevelDB

from worldbridge import convert
from worldbridge.bedrock import edge
from worldbridge.convert import ConversionError, TargetSpec
from worldbridge.model import Progress

import amulet_nbt as an


def _t(version=(1, 21, 50), family="bedrock", **kw):
    return TargetSpec(family=family, version=version, **kw)


# ------------------------------------------------------------------ the condition
@pytest.mark.parametrize("target,kind,old,moved,expect", [
    (_t(), "java_modern", False, False, True),               # Java 1.18+ -> Bedrock 1.18+
    (_t((1, 18, 30)), "java_modern", False, False, True),
    (_t(), "bedrock", False, True, True),                    # Bedrock 1.18+ moved elsewhere
    (_t(), "bedrock", False, False, False),                  # Bedrock -> Bedrock where it was: continues by itself
    (_t(), "java_modern", True, False, False),               # pre-1.18 sources are written in the old format already
    (_t(), "bedrock", True, True, False),
    (_t(), "lce", True, False, False),
    (_t(), "java_numeric", True, False, False),
    (_t((1, 17, 40)), "java_modern", False, False, False),   # Bedrock before 1.18 has no such terrain
    (_t(family="java", java_mode="auto", version=None), "java_modern", False, False, False),
])
def test_when_the_option_applies(target, kind, old, moved, expect):
    assert edge.applies(target, kind, old, moved) is expect


def test_a_move_or_a_y_offset_counts_as_moved():
    from worldbridge.selection import Selection

    assert not edge.is_moved(_t(), Selection())
    assert edge.is_moved(_t(), Selection(move_to=(0, 0)))
    assert edge.is_moved(_t(y_offset=64), Selection())


def _run(target, kind="java_modern", old=False, moved=False, tmp=None):
    prog = Progress(on_log=lambda m: logs.append(m))
    logs = []
    convert._bedrock_edge(str(tmp), target, kind, old, moved, prog)
    return prog.warnings, logs


def test_warning_when_it_applies_and_the_option_is_off(tmp_path):
    warnings, logs = _run(_t(), tmp=tmp_path)
    assert len(warnings) == 1 and "stay cut" in warnings[0] and "below y 0" in warnings[0]


def test_no_warning_where_the_option_does_not_apply(tmp_path):
    for kw in ({"kind": "bedrock"}, {"old": True}, {"kind": "lce", "old": True}):
        warnings, logs = _run(_t(), tmp=tmp_path, **kw)
        assert not warnings and not logs
    warnings, logs = _run(_t(bedrock_edge_blend=True), kind="bedrock", tmp=tmp_path)     # asked for, but nothing to do
    assert not warnings and len(logs) == 1 and "ignored" in logs[0]


def test_width_must_be_positive():
    with pytest.raises(ConversionError):
        convert.validate_target(_t(bedrock_edge_width=0))
    convert.validate_target(_t(bedrock_edge_width=2))


# ------------------------------------------------------------------ which chunks
def _square(n, ox=0, oz=0):
    return {(ox + i, oz + j) for i in range(n) for j in range(n)}


def test_border_is_the_outer_ring_only():
    ring = edge.border_chunks(_square(5), 1)
    assert ring == _square(5) - _square(3, 1, 1) and len(ring) == 16


def test_border_width():
    assert edge.border_chunks(_square(7), 2) == _square(7) - _square(3, 2, 2)
    assert edge.border_chunks(_square(4), 2) == _square(4)          # nothing left inside
    assert edge.border_chunks(_square(5), 0) == edge.border_chunks(_square(5), 1)


def test_a_hole_makes_a_border_of_its_own():
    have = _square(5) - {(2, 2)}
    ring = edge.border_chunks(have, 1)
    assert {(1, 1), (1, 2), (2, 1), (3, 3)} <= ring           # the chunks around the hole
    assert (2, 2) not in ring


# ------------------------------------------------------------------ the world
def _stone_subchunk(y):
    from worldbridge.bedrock.terrain import Storage, SubChunk

    def block(name):
        return an.CompoundTag({"name": an.StringTag(name), "states": an.CompoundTag({}), "version": an.IntTag(1)})

    idx = np.zeros(4096, np.int64)
    idx[:1000] = 1                                                      # 1000 stone, the rest air
    return SubChunk(9, y, [Storage(idx, [block("minecraft:air"), block("minecraft:stone")])]).encode()


def _world(tmp_path, chunks, with_nether=True):
    os.makedirs(tmp_path / "db")
    db = LevelDB(str(tmp_path / "db"))
    for cx, cz in chunks:
        pre = struct.pack("<ii", cx, cz)
        db.put(pre + b"\x2c", bytes([40]))
        db.put(pre + b"\x3d", b"\x01")
        db.put(pre + b"\x2b", b"\0" * 8)
        for y in (-2, -1, 0, 1):
            db.put(pre + b"\x2f" + struct.pack("b", y), _stone_subchunk(y))
    if with_nether:
        for cx in range(-3, 0):                                         # another dimension: never counted
            db.put(struct.pack("<iii", cx, 0, 1) + b"\x2c", bytes([40]))
    db.close()


def _read(tmp_path, chunks):
    db = LevelDB(str(tmp_path / "db"))
    try:
        out = {}
        for cx, cz in chunks:
            pre = struct.pack("<ii", cx, cz)
            ver = db.get(pre + b"\x2c")
            subs = []
            for y in (-2, -1, 0, 1):
                try:
                    db.get(pre + b"\x2f" + struct.pack("b", y))
                    subs.append(y)
                except KeyError:
                    pass
            try:
                flag = bytes(db.get(pre + b"\x3d"))
            except KeyError:
                flag = None
            out[(cx, cz)] = (bytes(ver)[0], flag, subs)
        return out
    finally:
        db.close()


def test_only_the_border_chunks_are_marked_and_the_interior_keeps_its_underground(tmp_path):
    chunks = _square(5)
    _world(tmp_path, chunks)
    r = edge.mark_border(str(tmp_path), 1)
    assert r == {"chunks": 25, "marked": 16, "below0": 16 * 2 * 1000}
    got = _read(tmp_path, chunks)
    ring = edge.border_chunks(chunks, 1)
    for c, (ver, flag, subs) in got.items():
        if c in ring:
            assert (ver, flag) == (22, None)                            # pre-1.18, no blending flag
        else:
            assert (ver, flag) == (40, b"\x01")                         # untouched
        assert subs == [-2, -1, 0, 1]                                   # no sub chunk is removed or changed
    db = LevelDB(str(tmp_path / "db"))
    try:
        assert bytes(db.get(struct.pack("<iii", -3, 0, 1) + b"\x2c"))[0] == 40
    finally:
        db.close()


def test_width_two_marks_two_rings(tmp_path):
    chunks = _square(7)
    _world(tmp_path, chunks, with_nether=False)
    r = edge.mark_border(str(tmp_path), 2)
    assert r["marked"] == 40 and r["chunks"] == 49
    got = _read(tmp_path, chunks)
    assert {c for c, v in got.items() if v[0] == 22} == chunks - _square(3, 2, 2)
    assert got[(3, 3)][0] == 40


def test_other_blending_records_go_too(tmp_path):
    _world(tmp_path, {(0, 0)}, with_nether=False)
    db = LevelDB(str(tmp_path / "db"))
    for tag in (0x3F, 0x40, 0x41):
        db.put(struct.pack("<ii", 0, 0) + bytes([tag]), b"\x01")
    db.close()
    edge.mark_border(str(tmp_path), 1)
    db = LevelDB(str(tmp_path / "db"))
    try:
        for tag in (0x3D, 0x3F, 0x40, 0x41):
            with pytest.raises(KeyError):
                db.get(struct.pack("<ii", 0, 0) + bytes([tag]))
    finally:
        db.close()


def test_the_log_reports_what_will_be_regenerated(tmp_path):
    _world(tmp_path, _square(4), with_nether=False)
    warnings, logs = _run(_t(bedrock_edge_blend=True, bedrock_edge_width=1), tmp=tmp_path)
    assert not warnings
    assert len(logs) == 1 and "12 border chunks" in logs[0] and "24000 blocks below y 0" in logs[0]
