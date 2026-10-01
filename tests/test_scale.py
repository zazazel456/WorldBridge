"""Big worlds: what keeps the memory and the work of a conversion independent of the world's size."""
import os
import struct

import numpy as np
import pytest

from worldbridge import convert as convert_mod
from worldbridge import detect, nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.java.region import ChunkIndex, region_chunks
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter, WORLD_SIZES, map_area
from worldbridge.model import NETHER, OVERWORLD, THE_END, UNKNOWN_BIOME, BiomeFiller, NumericChunk, Progress

from .helpers import SyntheticWorld, make_chunk


def _java_world(path, radius, dims=(OVERWORLD,)):
    src = SyntheticWorld(radius=radius, dims=dims)
    wr = JavaNumericWriter(str(path), JavaWriteOptions(kind="anvil"), Progress())
    for dim in dims:
        for cx, cz in src.chunk_coords(dim):
            wr.add_chunk(dim, make_chunk(cx, cz, seed=dim))
    wr.finish(src.info)
    return str(path)


# ---------------------------------------------------------------- the index of a Java world


def test_the_chunk_index_is_the_region_headers(tmp_path):
    path = _java_world(tmp_path / "w", radius=20)
    idx = JavaNumericWorld(path)._scan(OVERWORLD)
    assert isinstance(idx, ChunkIndex)
    expected = {}
    region = os.path.join(path, "region")
    for fn in os.listdir(region):
        _r, rx, rz, _ext = fn.split(".")
        for lx, lz in region_chunks(os.path.join(region, fn)):
            expected[(int(rx) * 32 + lx, int(rz) * 32 + lz)] = (os.path.join(region, fn), lx, lz)
    assert len(idx) == len(expected) == 40 * 40
    assert set(idx) == set(expected) and set(idx.keys()) == set(expected)
    for key, value in expected.items():
        assert idx.get(key) == value and key in idx
    assert idx.get((1000, 1000)) is None and (1000, 1000) not in idx
    # one entry per region (-1 and 0 on each axis), not per chunk
    assert len(idx.regions) == 4


# ---------------------------------------------------------------- finite maps


@pytest.mark.parametrize("size", sorted(WORLD_SIZES))
@pytest.mark.parametrize("dim", [OVERWORLD, NETHER, THE_END])
@pytest.mark.parametrize("offset", [(0, 0), (37, -85), (-500, 3)])
def test_the_map_area_is_what_the_lce_writer_keeps(tmp_path, size, dim, offset):
    w = LCEWriter(str(tmp_path), LCEWriteOptions(platform="win64", world_size=size, offset_x=offset[0],
                                                 offset_z=offset[1]), Progress())
    x0, x1, z0, z1 = map_area(dim, size, *offset)
    for cx in range(x0 - 3, x1 + 3):
        for cz in (z0 - 1, z0, (z0 + z1) // 2, z1 - 1, z1):
            assert (w.target_coords(dim, cx, cz) is not None) == (x0 <= cx < x1 and z0 <= cz < z1)


def _lce_chunks(path):
    w = LCEWorld(path)
    out = {}
    for dim in (OVERWORLD, NETHER):
        for cx, cz in w.chunk_coords(dim):
            c = w.read_raw_chunk(dim, cx, cz)
            out[(dim, cx, cz)] = (c.blocks.tobytes(), c.data.tobytes(), c.sky.tobytes(), c.biomes.tobytes())
    return out


def test_a_world_bigger_than_the_lce_map_is_read_only_where_it_reaches_it(tmp_path, monkeypatch):
    """The chunks that cannot land in the map are not read, and the map is the same as when every
    chunk was read and the writer left them out."""
    monkeypatch.setattr(convert_mod, "_AREA_MARGIN", 3)             # a smaller world does
    src = _java_world(tmp_path / "w", radius=32, dims=(OVERWORLD, NETHER))
    reads = []
    original = JavaNumericWorld.read_chunk

    def counted(self, dim, cx, cz):
        reads.append((dim, cx, cz))
        return original(self, dim, cx, cz)

    monkeypatch.setattr(JavaNumericWorld, "read_chunk", counted)
    results, logs = [], []
    for cut in (True, False):
        # reads counted in this process; the run without the cut only gives the map to compare with
        monkeypatch.setenv("WORLDBRIDGE_WORKERS", "1" if cut else "4")
        if not cut:
            monkeypatch.setattr(convert_mod, "_finite_area", lambda *a: None)
        reads.clear()
        p = Progress()
        seen = []
        p._on_log = seen.append
        out = tmp_path / f"lce_{cut}"
        convert(src, str(out), TargetSpec(family="lce", lce_platform="win64", lce_world_size=54, ring=False), p)
        results.append(_lce_chunks(next(q for q in out.rglob("saveData.ms"))))
        logs.append([m for m in seen if "outside the LCE world" in m])
        if cut:
            m = convert_mod._AREA_MARGIN
            assert len(reads) == (54 + 2 * m) ** 2 + (18 + 2 * m) ** 2      # of 2 * 64 * 64
    assert results[0] == results[1]
    assert len([k for k in results[0] if k[0] == OVERWORLD]) == 54 * 54
    assert logs[0] == logs[1] and logs[0]             # the same count of chunks left out


# ---------------------------------------------------------------- biomes not computed yet


def _chunks_with_holes():
    rng = np.random.default_rng(7)
    out = []
    for cx in range(-3, 3):
        for cz in range(-3, 3):
            c = NumericChunk(cx, cz, 256)
            c.biomes = rng.integers(0, 40, (16, 16)).astype(np.uint8)
            if (cx * 5 + cz) % 7 == 0:
                c.biomes[:] = UNKNOWN_BIOME                        # held back, filled at the end
            elif (cx + cz) % 5 == 0:
                c.biomes[:8] = UNKNOWN_BIOME                       # filled from itself
            out.append(c)
    return out


def test_the_biome_filler_reading_back_is_the_one_keeping_everything():
    def run(lookup_mode):
        written = {}
        f = BiomeFiller((lambda dim, cx, cz: written.get((dim, cx, cz))) if lookup_mode else None)
        result = {}
        for c in _chunks_with_holes():
            got = f.process(OVERWORLD, c)
            if got is not None:
                written[(OVERWORLD, got.cx, got.cz)] = got.biomes.copy()
                result[(got.cx, got.cz)] = got.biomes.copy()
        for _dim, c in f.flush():
            written[(OVERWORLD, c.cx, c.cz)] = c.biomes.copy()    # written as they come, like convert
            result[(c.cx, c.cz)] = c.biomes.copy()
        assert not f.known or not lookup_mode
        return result

    kept, read_back = run(False), run(True)
    assert kept.keys() == read_back.keys()
    for k in kept:
        assert np.array_equal(kept[k], read_back[k])


def test_the_hub_writer_gives_back_the_biomes_it_stored(tmp_path):
    w = JavaNumericWriter(str(tmp_path), JavaWriteOptions(kind="anvil"), Progress())
    rng = np.random.default_rng(3)
    stored = {}
    for cx in range(-40, 40, 7):
        for cz in range(-3, 3):
            c = make_chunk(cx, cz)
            c.biomes = rng.integers(0, 40, (16, 16)).astype(np.uint8)
            stored[(cx, cz)] = c.biomes.copy()
            w.add_chunk(OVERWORLD, c)
    w._flush_regions(keep=0)                          # some regions on disk, the last ones in memory
    for (cx, cz), b in stored.items():
        assert np.array_equal(w.stored_biomes(OVERWORLD, cx, cz), b)
    assert w.stored_biomes(OVERWORLD, 5000, 5000) is None
    assert w.stored_biomes(NETHER, 0, 0) is None


# ---------------------------------------------------------------- Bedrock height maps


def test_bedrock_height_maps_are_fixed_one_column_at_a_time(tmp_path, monkeypatch):
    from leveldb import LevelDB
    from worldbridge.bedrock import terrain

    air = nbt.CompoundTag({"name": nbt.StringTag("minecraft:air"), "states": nbt.CompoundTag(), "version": nbt.IntTag(1)})
    stone = nbt.CompoundTag({"name": nbt.StringTag("minecraft:stone"), "states": nbt.CompoundTag(), "version": nbt.IntTag(1)})
    db = LevelDB(str(tmp_path / "db"), True)
    expected_keys = []
    for x in (-2, 0, 3):
        for z in (-1, 4):
            for d in (0, 1, 2):
                prefix = struct.pack("<ii", x, z) + (struct.pack("<i", d) if d else b"")
                top = 5 + (x * 3 + z * 5 + d * 7) % 11
                idx = np.zeros(4096, np.int64)
                xs, zs, ys = np.meshgrid(np.arange(16), np.arange(16), np.arange(16), indexing="ij")
                idx[((xs << 8) | (zs << 4) | ys).reshape(-1)] = (ys < top).reshape(-1)
                sub = terrain.SubChunk(9, 0, [terrain.Storage(idx, [air, stone])]).encode()
                db.put(prefix + bytes([terrain.SUBCHUNK, 0]), sub)
                tag = terrain.DATA3D if d == 0 else terrain.DATA2D
                db.put(prefix + bytes([tag]), bytes(512) + b"biomes")
                expected_keys.append((prefix, tag, top))
    db.put(b"~local_player", b"x")
    expect = {}
    for prefix, tag, _top in expected_keys:
        expect[prefix] = terrain._height_map(prefix, tag, bytes(512) + b"biomes",
                                             {0: db.get(prefix + bytes([terrain.SUBCHUNK, 0]))}, None)
    monkeypatch.setenv("WORLDBRIDGE_WORKERS", "3")              # the sub chunks decoded by workers
    fixed = terrain.fix_height_maps(db)
    assert fixed == len(expected_keys)
    for prefix, tag, _top in expected_keys:
        assert db.get(prefix + bytes([tag])) == expect[prefix]
    db.close()


# ---------------------------------------------------------------- working copies


def test_the_working_copy_of_a_bedrock_world_links_its_tables(tmp_path):
    world = tmp_path / "world"
    (world / "db").mkdir(parents=True)
    (world / "db" / "000005.ldb").write_bytes(b"table")
    (world / "db" / "000006.log").write_bytes(b"log")
    (world / "db" / "MANIFEST-000004").write_bytes(b"manifest")
    (world / "db" / "LOCK").write_bytes(b"")
    (world / "level.dat").write_bytes(b"level")
    snap = detect.snapshot(str(world), str(tmp_path / "tmp"))
    same = lambda a, b: os.stat(a).st_ino == os.stat(b).st_ino
    assert same(world / "db" / "000005.ldb", os.path.join(snap, "db", "000005.ldb"))
    for name in ("db/000006.log", "db/MANIFEST-000004", "level.dat"):
        assert not same(world / name, os.path.join(snap, name))
        assert open(os.path.join(snap, name), "rb").read() == (world / name).read_bytes()
    assert not os.path.exists(os.path.join(snap, "db", "LOCK"))
    # the same disk: no folder next to the world
    assert detect.snapshot_parent(str(world), str(tmp_path)) is None
