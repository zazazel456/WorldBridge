"""Work on every core gives exactly what one core gives (parallel.py and the steps that use it)."""
import os

import numpy as np
import pytest

from worldbridge import nbt, parallel
from worldbridge.chestfix import CHEST, TRAPPED, ChestRows
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.lce.world import LCEWorld
from worldbridge.mapview import _tile_core, is_air, is_watery, tile_from_sections
from worldbridge.model import NumericChunk, Progress
from worldbridge.selection import Selection

from .helpers import SyntheticWorld, make_chunk


def _square(state, x):
    return (state, x * x)


def test_ordered_map_keeps_the_order_on_every_core(monkeypatch):
    items = list(range(300))
    want = [("s", x * x) for x in items]
    for n in ("1", "4"):
        monkeypatch.setenv("WORLDBRIDGE_WORKERS", n)
        assert list(parallel.ordered_map(_square, "s", items, batch=7)) == want
        assert list(parallel.ordered_map(_square, "s", iter(items), batch=3)) == want     # a lazy source


def _worker_flag(_state, _x):
    return parallel.in_worker()


def test_workers_know_they_are_workers(monkeypatch):
    monkeypatch.setenv("WORLDBRIDGE_WORKERS", "3")
    assert all(parallel.ordered_map(_worker_flag, None, range(64)))
    assert not parallel.in_worker()
    monkeypatch.setenv("WORLDBRIDGE_WORKERS", "1")
    assert not any(parallel.ordered_map(_worker_flag, None, range(64)))


def _boom(_state, x):
    if x == 50:
        raise ValueError("chunk 50")
    return x


def test_an_error_in_a_worker_reaches_the_caller(monkeypatch):
    monkeypatch.setenv("WORLDBRIDGE_WORKERS", "4")
    with pytest.raises(ValueError, match="chunk 50"):
        list(parallel.ordered_map(_boom, None, range(200)))


# ---------------------------------------------------------------- chests


def _chest_world():
    """Rows of chests across the borders of four chunks, as the source world keeps them."""
    chunks = {}
    for cx in (0, 1):
        for cz in (0, 1):
            chunks[(cx, cz)] = NumericChunk(cx, cz, 256)
    rng = np.random.default_rng(3)
    for x in range(8, 24):
        for z in range(10, 22):
            if rng.random() < 0.55:
                c = chunks[(x >> 4, z >> 4)]
                c.blocks[70, z & 15, x & 15] = CHEST if rng.random() < 0.8 else TRAPPED
                c.data[70, z & 15, x & 15] = 2 if rng.random() < 0.5 else 5
    return chunks


def _copy(c):
    return NumericChunk(c.cx, c.cz, c.height, blocks=c.blocks.copy(), data=c.data.copy())


def test_chest_rows_do_not_depend_on_the_order_of_the_chunks():
    world = _chest_world()

    def fixed(order):
        rows = ChestRows(lambda dim, cx, cz: _copy(world[(cx, cz)]) if (cx, cz) in world else None)
        out = {}
        for key in order:
            c = _copy(world[key])
            rows.fix(0, c)
            out[key] = c.blocks[70].copy()
        return out

    keys = sorted(world)
    a, b = fixed(keys), fixed(keys[::-1])
    assert all((a[k] == b[k]).all() for k in keys)
    assert any((a[k] != world[k].blocks[70]).any() for k in keys)          # something was changed


# ---------------------------------------------------------------- conversion


def _java_world(tmp_path):
    src = SyntheticWorld(radius=4)
    out = str(tmp_path / "src")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        c = make_chunk(cx, cz)
        for x in range(16):                     # a row of chests along every chunk, across its borders
            c.blocks[66, 3, x] = CHEST
            c.data[66, 3, x] = 2
        wr.add_chunk(0, c)
    wr.finish(src.info)
    return out, set(src.chunk_coords(0))


def _lce_chunks(path):
    w = LCEWorld(path)
    out = {}
    for cx, cz in w.chunk_coords(0):
        c = w.read_raw_chunk(0, cx, cz)
        tiles = sorted(nbt.dump(t).hex() for t in c.tile_entities)
        out[(cx, cz)] = (c.blocks.tobytes(), c.data.tobytes(), c.sky.tobytes(), tuple(tiles))
    return out


@pytest.mark.parametrize("move", [None, (0, 0)])
def test_a_conversion_on_every_core_is_the_one_on_one_core(tmp_path, monkeypatch, move):
    src, chunks = _java_world(tmp_path)
    results = []
    for n in ("1", "4"):
        monkeypatch.setenv("WORLDBRIDGE_WORKERS", n)
        sel = Selection(chunks={0: chunks}, move_to=move) if move else None
        t = TargetSpec(family="lce", lce_platform="win64", ring=False, selection=sel)
        out = tmp_path / f"lce{n}"
        convert(src, str(out), t)
        results.append(_lce_chunks(next(p for p in out.rglob("saveData.ms"))))
    assert results[0] == results[1]
    assert len(results[0]) == 64


def test_the_ring_on_every_core_is_the_one_on_one_core(monkeypatch):
    from worldbridge.terrain.filler import FillGenerator
    from worldbridge.terrain.ring import Ring

    def ring_chunks():
        converted = [(x, z) for x in range(3) for z in range(3)]
        fill = [(x, z) for x in range(-4, 7) for z in range(-4, 7)]
        r = Ring(FillGenerator(99), 62, converted, fill=fill, seed=99)
        for cx, cz in converted:
            r.observe(0, make_chunk(cx, cz))
        return [(c.cx, c.cz, c.blocks.tobytes(), c.data.tobytes(), c.biomes.tobytes()) for c in r.chunks()]

    monkeypatch.setenv("WORLDBRIDGE_WORKERS", "1")
    one = ring_chunks()
    monkeypatch.setenv("WORLDBRIDGE_WORKERS", "4")
    assert ring_chunks() == one
    assert len(one) == 121 - 9


# ---------------------------------------------------------------- map and biomes


def test_the_map_reads_only_the_top_sections_and_gets_the_same_tile():
    rng = np.random.default_rng(11)
    names = ["air", "stone", "water", "grass_block", "cave_air", "oak_leaves", "sand", "light"]
    for trial in range(300):
        secs = []
        for sy in sorted(rng.choice(np.arange(-4, 20), size=int(rng.integers(1, 8)), replace=False)):
            pal = list(rng.choice(names, size=int(rng.integers(1, 5)), replace=False))
            idx = rng.integers(0, len(pal), (16, 16, 16))
            if rng.random() < 0.5:                     # mostly open or mostly full sections
                idx[rng.random((16, 16, 16)) < 0.8] = 0
            secs.append((int(sy), idx, pal))
        new = tile_from_sections(secs)
        # the reference: every section unpacked, the whole column looked at
        pos = {"air": 0}
        luts = [np.array([pos.setdefault(n, len(pos)) for n in p], np.int32) for _s, _i, p in secs]
        ymin, ymax = min(s[0] for s in secs), max(s[0] for s in secs)
        keys = np.zeros(((ymax - ymin + 1) * 16, 16, 16), np.int32)
        for (sy, idx, _p), lut in zip(secs, luts):
            keys[(sy - ymin) * 16:(sy - ymin) * 16 + 16] = lut[idx]
        order = sorted(pos, key=pos.get)
        a = np.array([is_air(n) for n in order], bool)
        w = np.array([is_watery(n) for n in order], bool)
        ref = _tile_core(keys, a, w, lambda k: order[k], ymin * 16)
        assert (new is None) == (ref is None), trial
        if ref is not None:
            for f in ("color", "height", "depth", "index"):
                assert (getattr(new, f) == getattr(ref, f)).all(), (trial, f)
            assert new.names == ref.names


def test_biome_blocks_are_the_areas_the_layers_give():
    from worldbridge.terrain.genlayers import Stack
    from worldbridge.terrain.layers17 import Stack17
    from worldbridge.terrain.neolayers import NeoStack

    rng = np.random.default_rng(5)
    for stack in (Stack("1.6", 42), Stack17("1.12", 42), Stack17("1.16", 7), NeoStack(-31)):
        for _ in range(12):
            x, z = (int(v) for v in rng.integers(-500, 500, 2))
            w, h = (int(v) for v in rng.integers(1, 40, 2))
            assert (stack.biomes(x, z, w, h) == stack.voronoi.area(x, z, w, h)).all()
            assert (stack.biomes4(x, z, w, h) == stack.mix.area(x, z, w, h)).all()


def test_amulet_on_every_core_is_amulet_on_one_core(tmp_path, monkeypatch):
    """Java 1.13+ read through Amulet by several processes, each writing its own regions."""
    from worldbridge import amulet_bridge as ab
    from worldbridge.lce.world import LCEWriteOptions, LCEWriter

    src = SyntheticWorld(radius=3, dims=(0, -1))
    w = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64"), Progress())
    for d in src.dimensions():
        for cx, cz in src.chunk_coords(d):
            w.add_chunk(d, src.read_chunk(d, cx, cz))
    w.finish(src.info)
    convert(str(tmp_path / "lce"), str(tmp_path / "modern"), TargetSpec(family="java", java_mode="amulet"))
    monkeypatch.setattr(ab, "PARALLEL_MIN_CHUNKS", 1)
    chunks = {(x, z) for x in range(-3, 3) for z in range(-3, 3)}
    results = []
    for n in ("1", "3"):
        monkeypatch.setenv("WORLDBRIDGE_WORKERS", n)
        sel = Selection(chunks={0: chunks, -1: chunks}, move_to=(40, -24))
        out = tmp_path / f"back{n}"
        convert(str(tmp_path / "modern"), str(out), TargetSpec(family="lce", ring=False, selection=sel))
        results.append(_lce_chunks(next(p for p in out.rglob("saveData.ms"))))
    assert results[0] == results[1]
    assert len(results[0]) == 36


def _bedrock_records(world):
    from leveldb import LevelDB

    db = LevelDB(os.path.join(str(world), "db"))
    try:
        # the chunks' records (the player's, "~local_player", has an id drawn anew by every conversion)
        return {bytes(k): bytes(v) for k, v in db.iterate() if len(k) in (9, 10, 13, 14) and not k.startswith(b"~")}
    finally:
        db.close()


def test_amulet_into_and_from_bedrock_on_every_core_is_one_core(tmp_path, monkeypatch):
    """Bedrock written by several processes (a LevelDB each, merged) and read by several processes (a
    copy of the LevelDB each): the same chunks as in one process."""
    from worldbridge import amulet_bridge as ab
    from worldbridge.lce.world import LCEWriteOptions, LCEWriter

    src = SyntheticWorld(radius=3, dims=(0, -1))
    w = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64"), Progress())
    for d in src.dimensions():
        for cx, cz in src.chunk_coords(d):
            w.add_chunk(d, src.read_chunk(d, cx, cz))
    w.finish(src.info)
    monkeypatch.setattr(ab, "PARALLEL_MIN_CHUNKS", 1)
    bedrock, back = [], []
    for n in ("1", "3"):
        monkeypatch.setenv("WORLDBRIDGE_WORKERS", n)
        out = tmp_path / f"bedrock{n}"
        convert(str(tmp_path / "lce"), str(out), TargetSpec(family="bedrock", blend=False))
        bedrock.append(_bedrock_records(out))
        lce = tmp_path / f"back{n}"
        convert(str(out), str(lce), TargetSpec(family="lce", ring=False))
        back.append(_lce_chunks(next(p for p in lce.rglob("saveData.ms"))))
    assert bedrock[0] == bedrock[1]
    assert sum(1 for k in bedrock[0] if len(k) in (10, 14)) >= 72      # the sub chunks of 72 chunks
    assert back[0] == back[1]
    assert len(back[0]) == 36


def _fill_leveldb(path):
    from leveldb import LevelDB

    db = LevelDB(path, True)
    for i in range(2000):                           # more than LevelDB's write buffer: a compaction
        db.put(b"k%06d" % i, os.urandom(4096))
    db.close()
    return path


def test_workers_that_open_leveldb_do_not_wait_for_the_parents_thread(tmp_path):
    """A process that used LevelDB has its background thread; workers that open a LevelDB of their own
    start from the fork server and close it (a forked copy would wait for that thread forever)."""
    import concurrent.futures as cf

    _fill_leveldb(str(tmp_path / "parent"))
    pool = cf.ProcessPoolExecutor(max_workers=2, mp_context=parallel.process_context(leveldb=True))
    try:
        futures = [pool.submit(_fill_leveldb, str(tmp_path / f"w{k}")) for k in range(2)]
        assert [f.result(timeout=120) for f in futures] == [str(tmp_path / f"w{k}") for k in range(2)]
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _tag_square(state, x):
    return ("map", state, x * x)


def _tag_negate(state, x):
    return ("convert", state, -x)


def test_ordered_map_is_safe_for_concurrent_callers(monkeypatch):
    """The GUI's map loader and a conversion run ordered_map at the same time: each gets its own function and state."""
    import threading

    monkeypatch.setenv("WORLDBRIDGE_WORKERS", "3")
    bad = []

    def run(fn, tag, expect):
        for _ in range(8):
            try:
                got = list(parallel.ordered_map(fn, tag, list(range(120)), batch=8))
                if got != [expect(tag, x) for x in range(120)]:
                    bad.append(tag)
            except Exception as ex:  # noqa: BLE001
                bad.append(repr(ex))

    ts = [threading.Thread(target=run, args=(_tag_square, "MAP", lambda s, x: ("map", s, x * x))),
          threading.Thread(target=run, args=(_tag_negate, "CONV", lambda s, x: ("convert", s, -x)))]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    assert not bad, bad[:3]
