"""Biome orientation through Amulet, 'not computed' biomes and pre-1.18 blending output."""
import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.region import JavaRegion
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.model import Progress

from .helpers import SyntheticWorld


def _lce_with_biomes(path, unknown_chunk=None):
    src = SyntheticWorld(radius=1)
    w = LCEWriter(str(path), LCEWriteOptions(platform="win64"), Progress())
    for cx, cz in src.chunk_coords(0):
        c = src.read_chunk(0, cx, cz)
        c.biomes = np.zeros((16, 16), np.uint8)
        c.biomes[:, :8] = 2  # [z][x]: x < 8 desert
        c.biomes[:, 8:] = 5  # x >= 8 taiga
        if (cx, cz) == unknown_chunk:
            c.biomes[:] = 255
        w.add_chunk(0, c)
    w.finish(src.info)


def test_biomes_java_3d_orientation_and_blending(tmp_path):
    _lce_with_biomes(tmp_path / "a")
    convert(str(tmp_path / "a"), str(tmp_path / "b"), TargetSpec(family="java", java_mode="amulet"))
    root = nbt.load(JavaRegion(str(tmp_path / "b" / "region" / "r.0.0.mca")).read(0, 0), compressed=False).tag
    assert int(root["DataVersion"].py_data) < 2825  # pre-1.18 chunk: the game blends it
    b = np.asarray(root["Level"]["Biomes"].np_array)
    layer = b[256:272].reshape(4, 4)  # [z>>2][x>>2]
    assert layer.tolist() == [[2, 2, 5, 5]] * 4


def test_biomes_bedrock_and_unknown_fill(tmp_path):
    from worldbridge.bedrock.extra import _db, _get, chunk_prefix

    _lce_with_biomes(tmp_path / "a", unknown_chunk=(0, 0))
    convert(str(tmp_path / "a"), str(tmp_path / "b"), TargetSpec(family="bedrock"))
    db = _db(str(tmp_path / "b"))
    try:
        for cx, cz in ((-1, 0), (0, 0)):
            d2 = _get(db, chunk_prefix(cx, cz, 0) + b"\x2d")
            bio = np.frombuffer(d2[512:768], np.uint8).reshape(16, 16)  # Bedrock: z-major
            assert set(np.unique(bio)) <= {2, 5}
            if (cx, cz) != (0, 0):
                assert (bio[:, :8] == 2).all() and (bio[:, 8:] == 5).all()
    finally:
        db.close()


def test_lce_to_lce_is_lossless(tmp_path):
    src = SyntheticWorld(radius=1)
    w = LCEWriter(str(tmp_path / "a"), LCEWriteOptions(platform="win64"), Progress())
    for cx, cz in src.chunk_coords(0):
        c = src.read_chunk(0, cx, cz)
        c.biomes = np.full((16, 16), 255, np.uint8)
        c.lce_terrain_flags = 486
        c.lce_heightmap = np.arange(256, dtype=np.uint8)
        c.entities[0]["Equipment"] = nbt.ListTag([nbt.CompoundTag() for _ in range(5)], 10)
        c.tile_ticks.append(nbt.CompoundTag({"i": nbt.IntTag(8), "x": nbt.IntTag(cx * 16), "y": nbt.IntTag(64),
                                             "z": nbt.IntTag(cz * 16), "t": nbt.IntTag(5)}))
        w.add_chunk(0, c)
    w.finish(src.info)
    convert(str(tmp_path / "a"), str(tmp_path / "b"), TargetSpec(family="lce", lce_platform="win64", ring=False))
    a, b = LCEWorld(str(tmp_path / "a")), LCEWorld(str(tmp_path / "b"))
    assert a.info.level == b.info.level
    for cx, cz in a.chunk_coords(0):
        x, y = a.read_raw_chunk(0, cx, cz), b.read_raw_chunk(0, cx, cz)
        for f in ("blocks", "data", "sky", "block_light", "biomes", "heightmap"):
            assert np.array_equal(getattr(x, f), getattr(y, f)), f
        assert x.terrain_populated == y.terrain_populated == 486
        assert [nbt.dump(e) for e in x.entities] == [nbt.dump(e) for e in y.entities]
        assert [nbt.dump(t) for t in x.tile_ticks] == [nbt.dump(t) for t in y.tile_ticks]
