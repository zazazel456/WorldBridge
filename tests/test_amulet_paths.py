"""Slow end-to-end checks through Amulet (Bedrock 26.x, Java 26.x)."""
import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.model import Progress

from .helpers import SyntheticWorld, make_chunk


def _lce(path):
    src = SyntheticWorld(radius=1, dims=(0, -1))
    w = LCEWriter(str(path), LCEWriteOptions(platform="win64"), Progress())
    for d in src.dimensions():
        for cx, cz in src.chunk_coords(d):
            w.add_chunk(d, src.read_chunk(d, cx, cz))
    w.finish(src.info)


def _check_lce(path):
    w = LCEWorld(str(path))
    assert w.info.name == "Test World"
    for cx, cz in w.chunk_coords(0):
        c = w.read_chunk(0, cx, cz)
        r = make_chunk(cx, cz, 0)
        assert np.array_equal(c.blocks, r.blocks)
        assert np.array_equal(c.data, r.data)
        chest = [t for t in c.tile_entities if nbt.get(t, "id") == "Chest"][0]
        assert int(chest["Items"][0]["id"].py_data) == 264 and int(chest["Items"][0]["Count"].py_data) == 5
        assert any(nbt.get(e, "id") == "Pig" for e in c.entities)
    assert w.info.players


def test_lce_bedrock_roundtrip(tmp_path):
    _lce(tmp_path / "a")
    convert(str(tmp_path / "a"), str(tmp_path / "b"), TargetSpec(family="bedrock"))
    convert(str(tmp_path / "b"), str(tmp_path / "c"), TargetSpec(family="lce", ring=False))
    _check_lce(tmp_path / "c")


def test_lce_java_latest_roundtrip(tmp_path):
    _lce(tmp_path / "a")
    convert(str(tmp_path / "a"), str(tmp_path / "b"), TargetSpec(family="java", java_mode="amulet"))
    convert(str(tmp_path / "b"), str(tmp_path / "c"), TargetSpec(family="lce", ring=False))
    _check_lce(tmp_path / "c")


def test_java_dfu_route(tmp_path):
    _lce(tmp_path / "a")
    convert(str(tmp_path / "a"), str(tmp_path / "b"), TargetSpec(family="java"))
    from worldbridge.java.numeric import JavaNumericWorld

    jw = JavaNumericWorld(str(tmp_path / "b"))
    c = jw.read_chunk(0, 0, 0)
    assert np.array_equal(c.blocks, make_chunk(0, 0, 0).blocks)
    lvl = nbt.load(open(tmp_path / "b" / "level.dat", "rb").read()).tag["Data"]
    assert lvl["version"].py_data == 19133 and "Player" in lvl
