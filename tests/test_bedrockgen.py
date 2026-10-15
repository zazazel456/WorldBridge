"""The Bedrock overworld generator before 1.18 (bedrockgen.py and friends) and the ring made with it for Bedrock
1.6 - 1.17 targets.  The golden values (tests/data/bedrock_old_golden.json) are what Bedrock Dedicated Server made:
the BlockVolume after its surface pass (1.16.220, seeds 12345, 1001 and 22: plains, oceans, frozen oceans, badlands...)
and the untouched columns of saved worlds of 1.10 - 1.17 with seeds above 2^31."""
import json
import os

import numpy as np
import pytest

from worldbridge import nbt
from worldbridge.convert import TargetSpec, ensure_seed
from worldbridge.model import NumericChunk, Progress
from worldbridge.terrain import bedrockgen, bedrocksurface, policy
from worldbridge.terrain import ring as ring_mod
from worldbridge.terrain.bedrockgen import BedrockGenerator
from worldbridge.terrain.bedrocknoise import Random

GOLDEN = os.path.join(os.path.dirname(__file__), "data", "bedrock_old_golden.json")


def T(version, **kw):
    return TargetSpec(family="bedrock", version=version, **kw)


# ---------------------------------------------------------------------------------------------- random numbers
def test_mt19937_matches_the_reference_stream():
    r = Random(5489)                                  # the reference seed of MT19937
    assert [r.u32() for _ in range(3)] == [3499211612, 581869302, 3890346734]
    for _ in range(9996):
        r.u32()
    assert r.u32() == 4123659995                      # the 10000th output (crosses 16 re-twists)


def test_seeds_are_unsigned_32_bit():
    a, b, c = Random(-5), Random(2 ** 32 - 5), Random(2 ** 32 * 7 + 2 ** 32 - 5)
    assert a.u32() == b.u32() == c.u32()


def test_next_int_and_next_float():
    r, ref = Random(12345), Random(12345)
    u = [ref.u32() for _ in range(4)]
    assert r.next_int(10) == u[0] % 10 and r.next_int(256) == u[1] % 256
    assert r.next_int(0) == 0 and r.u32() == u[2]                     # nextInt(0) is 0 and draws nothing
    f = Random(99)
    first = Random(99).u32()
    v = f.next_float()
    assert v.dtype == np.float32 and v == np.float32(first * 2.0 ** -32)
    vals = [f.next_float() for _ in range(1000)]
    assert all(0.0 <= x <= 1.0 for x in vals)


# ---------------------------------------------------------------------------------------------- versions and dispatch
def test_supported_versions():
    assert bedrockgen.supports((1, 6, 0)) and bedrockgen.supports((1, 16, 40)) and bedrockgen.supports((1, 17, 41, 1))
    assert bedrockgen.supports((1, 11)) and not bedrockgen.supports((1, 5, 9)) and not bedrockgen.supports((1, 18, 0))
    assert not bedrockgen.supports(None) and not bedrockgen.supports(()) and not bedrockgen.supports((26, 3))
    for v in bedrockgen.VERIFIED:
        assert bedrockgen.supports(v)
    assert bedrockgen.version_params((1, 17, 10))["volume_height"] == 320
    assert bedrockgen.version_params((1, 16, 0))["volume_height"] == 128
    with pytest.raises(ValueError):
        BedrockGenerator(1, (1, 18, 0))


def test_policy_for_bedrock_targets():
    for v in ((1, 6, 0), (1, 12, 0), (1, 16, 0), (1, 17, 41)):
        p = policy.decide(T(v), True)
        assert p.kind == "ring" and p.text, v
    assert policy.decide(T((1, 17, 41), ring=False), True).kind == "off"
    for v in ((1, 2, 0), (1, 5, 3)):
        p = policy.decide(T(v), True)
        assert p.kind == "missing" and "Bedrock 1.6" in p.text
    assert policy.decide(T((1, 18, 0)), True).kind == "game"
    assert policy.decide(T((1, 21, 50)), False).kind == "game"
    # an old Bedrock world that stays where it is continues by itself
    assert policy.decide(T((1, 16, 0)), True, "bedrock", None, True).kind == "game"
    assert policy.decide(T((1, 16, 0)), True, "bedrock", None, False).kind == "ring"


def test_ring_dispatch():
    t = T((1, 16, 40))
    assert ring_mod.supported(t) and ring_mod.supported(t, "default")
    assert not ring_mod.supported(T((1, 5, 0)))
    gen, sea = ring_mod.generator(t, 12345)
    assert isinstance(gen, BedrockGenerator) and sea == 62 and gen.version == (1, 16, 40)
    # the java targets still get their own
    assert not isinstance(ring_mod.generator(TargetSpec(family="java", java_mode="amulet", version=(1, 16, 5)), 1)[0],
                          BedrockGenerator)


def test_seed_is_the_unsigned_low_32_bits():
    a = BedrockGenerator(-3878429724685138167)
    b = BedrockGenerator(-3878429724685138167 & 0xFFFFFFFF)
    assert a.seed == b.seed < 2 ** 32
    assert np.array_equal(a.chunk(2, -3)[0], b.chunk(2, -3)[0])


def test_derived_seed_for_bedrock_is_32_bit():
    lvl = nbt.CompoundTag({"LevelName": nbt.StringTag("Some World")})
    s = ensure_seed(lvl, Progress(), "Some World", bedrock=True)
    assert 0 < s < 2 ** 32 and int(nbt.get(lvl, "RandomSeed")) == s
    lvl2 = nbt.CompoundTag({"LevelName": nbt.StringTag("Some World")})
    assert ensure_seed(lvl2, Progress(), "Some World", bedrock=False) > 2 ** 32       # the other targets keep 63 bits
    lvl3 = nbt.CompoundTag({"RandomSeed": nbt.LongTag(4171510507)})
    assert ensure_seed(lvl3, Progress(), "x", bedrock=True) == 4171510507         # a seed the world has is kept


# ---------------------------------------------------------------------------------------------- the generator
def test_chunk_interface():
    gen = BedrockGenerator(12345)
    blocks, biomes, data = gen.chunk(0, 0)
    assert blocks.shape == (16, 16, 128) and blocks.dtype == np.uint8 and data.shape == blocks.shape
    assert biomes.shape == (16, 16) and biomes.max() < 256
    assert (blocks[:, :, 0] == 7).all()                                # the bedrock floor
    assert set(np.unique(blocks)) <= {0, 1, 2, 3, 7, 9, 12, 13, 24}
    top = 127 - np.argmax((blocks != 0)[:, :, ::-1] & (blocks != 9)[:, :, ::-1], axis=2)
    assert 55 < top.mean() < 100


def test_lift_moves_the_ground_and_zero_lift_changes_nothing():
    gen = BedrockGenerator(12345)
    base = gen.chunk(3, 4)[0]
    same = gen.chunk(3, 4, lift=np.zeros((16, 16)))[0]
    assert np.array_equal(base, same)
    up = gen.chunk(3, 4, lift=np.full((16, 16), 6.0))[0]

    def top(b):
        solid = (b != 0) & (b != 9)
        return b.shape[2] - 1 - np.argmax(solid[:, :, ::-1], axis=2)
    d = top(up)[:, :] - top(base)
    assert 5 <= d.mean() <= 7
    high = gen.chunk(3, 4, lift=np.full((16, 16), 90.0))[0]            # raised above the generator's 128
    assert high.shape[2] == 256 and top(high).max() > 128


def test_biomes_come_back_exact_after_the_hub():
    gen = BedrockGenerator(1221576862)
    exact = gen.biomes(0, 0)
    ids = set()
    for cx in range(-6, 6, 2):
        for cz in range(-6, 6, 2):
            ids.update(np.unique(gen.biomes(cx, cz)).tolist())
            assert gen.chunk(cx, cz)[1].max() <= 39                    # what Java 1.12 numeric chunks can hold
    assert {40, 42, 44, 45} & ids                                      # warm / lukewarm / cold oceans occur
    hub = gen.chunk(0, 0)[1]
    stored = np.where(hub == 10, 46, hub)                              # the translation of the hub's frozen ocean
    assert np.array_equal(bedrockgen.restore_biomes(stored, exact), exact)
    changed = stored.copy()
    changed[0, 0] = 1                                                  # a column the ring made something else of
    assert bedrockgen.restore_biomes(changed, exact)[0, 0] == 1


# ---------------------------------------------------------------------------------------------- golden values
def _skin(column):
    """(bedrock layers, top y, [[name, run]]) from the highest non-air block down to the first stone."""
    bed = 0
    while bed < len(column) and column[bed] == "bedrock":
        bed += 1
    top = len(column) - 1
    while top > 0 and column[top] == "air":
        top -= 1
    runs, y = [], top
    while y >= bed:
        if runs and runs[-1][0] == column[y]:
            runs[-1][1] += 1
        else:
            runs.append([column[y], 1])
        if column[y] == "stone":
            break
        y -= 1
    return bed, top, runs


def _sets():
    with open(GOLDEN) as f:
        data = json.load(f)
    return data["sets"]


@pytest.mark.parametrize("entry", _sets(), ids=lambda s: "%s-%s" % (s["seed"], s["version"]))
def test_golden_chunks_from_bedrock_dedicated_server(entry):
    version = tuple(int(x) for x in entry["version"].split(".")[:2])
    gen = BedrockGenerator(entry["seed"], version)
    pal = entry["palette"]
    assert entry["chunks"]
    for rec in entry["chunks"]:
        codes, biomes = gen.chunk_bedrock(rec["cx"], rec["cz"])
        names = bedrocksurface.names(codes)
        # the biomes of the whole chunk (Data2D, index z * 16 + x)
        assert biomes.T.ravel().tolist() == rec["biomes"], rec["cx"]
        cols = rec.get("columns", list(range(256)))
        for i, col in enumerate(cols):
            x, z = col % 16, col // 16
            bed, top, runs = _skin(list(names[x, z]))
            want = [[pal[rec["skin"][i][k]], rec["skin"][i][k + 1]] for k in range(0, len(rec["skin"][i]), 2)]
            assert (bed, top, runs) == (rec["bedrock"][i], rec["top"][i], want), (entry["seed"], rec["cx"], rec["cz"], x, z)


def test_golden_covers_the_special_surfaces():
    seen = {}
    for s in _sets():
        for rec in s["chunks"]:
            seen.setdefault(s["seed"], set()).update(rec["biomes"])
    assert {37, 38, 39} <= seen[22]                                    # badlands bands (seed 22)
    assert {46, 47} & seen[22] and {44, 45} & seen[1001]                # frozen and cold oceans
    assert 24 in seen[12345] and {42, 44} & seen[1221576862]
    assert any(seed > 2 ** 31 for seed in seen)


# ---------------------------------------------------------------------------------------------- the ring
def _flat_edge(cx, cz, h=70):
    c = NumericChunk(cx, cz, 256)
    c.blocks[0] = 7
    c.blocks[1:h] = 1
    c.blocks[h] = 2
    return c


def test_the_ring_ends_exactly_with_the_generators_terrain():
    gen, sea = ring_mod.generator(T((1, 16, 0)), 12345)
    ring = ring_mod.Ring(gen, sea, [(0, 0)], seed=12345)
    ring.observe(0, _flat_edge(0, 0))
    targets = ring.targets()
    assert targets
    far = max(targets, key=lambda c: max(abs(c[0]), abs(c[1])))
    assert ring.lift(*far) is None or not np.any(ring.lift(*far))      # the lift is gone at the outer edge
    c, _planted, _sealed = ring._ring_chunk(*far)
    want = gen.chunk(*far)[0]
    assert np.array_equal(np.transpose(c.blocks[:128], (2, 1, 0)), want)
    assert not c.terrain_populated


# ---------------------------------------------------------------------------------------------- conversions
def _bedrock_chunks(world):
    import struct

    from leveldb import LevelDB

    db = LevelDB(os.path.join(world, "db"))
    fin, bio = {}, {}
    try:
        for k, v in db.iterate():
            k, v = bytes(k), bytes(v)
            if len(k) == 9 and k[8] == 0x36:
                fin[struct.unpack_from("<ii", k)] = struct.unpack("<i", v[:4])[0]
            elif len(k) == 9 and k[8] == 0x2D:
                bio[struct.unpack_from("<ii", k)] = np.frombuffer(v[512:768], np.uint8).reshape(16, 16).T.copy()
    finally:
        db.close()
    return fin, bio


def test_conversion_to_bedrock_1_16_gets_a_ring_for_both_routes(tmp_path):
    from worldbridge.convert import convert
    from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions

    from .helpers import SyntheticWorld

    seed = 4171510507
    src = SyntheticWorld(radius=1)
    src.info.level["RandomSeed"] = nbt.LongTag(seed)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    gen = BedrockGenerator(seed, (1, 16, 0))
    # through the numeric hub
    out = str(tmp_path / "bedrock")
    convert(hub, out, TargetSpec(family="bedrock", version=(1, 16, 0)))
    fin, bio = _bedrock_chunks(out)
    ring = [c for c, s in fin.items() if s == 1]
    assert sum(1 for s in fin.values() if s == 2) == 4 and len(ring) > 40       # the game finishes the ring's chunks
    far = max(ring, key=lambda c: max(abs(c[0] - 0.5), abs(c[1] - 0.5)))
    assert np.array_equal(bio[far], gen.biomes(*far))                           # exact Bedrock biomes, not the hub's
    # straight through Amulet (a Bedrock world to Bedrock): the ring is added afterwards, never over a converted chunk
    base = str(tmp_path / "base")
    convert(hub, base, TargetSpec(family="bedrock", version=(1, 16, 0), ring=False))
    assert set(_bedrock_chunks(base)[0].values()) == {2}
    # an old Bedrock world that stays where it is needs no ring (the game generates the same terrain)
    same = str(tmp_path / "same")
    convert(base, same, TargetSpec(family="bedrock", version=(1, 16, 0)), Progress())
    assert set(_bedrock_chunks(same)[0].values()) == {2}
    # moved, it does
    out2 = str(tmp_path / "direct")
    convert(base, out2, TargetSpec(family="bedrock", version=(1, 16, 0), y_offset=1), Progress())
    fin2, _bio2 = _bedrock_chunks(out2)
    assert sum(1 for s in fin2.values() if s == 2) == 4 and sum(1 for s in fin2.values() if s == 1) > 40
