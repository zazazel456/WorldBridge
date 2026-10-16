"""The Nether of Java 1.18+ targets: its biome source against the biomes a 26.3 Nether wrote (seed
7769476965016494779), the climate noises against the game's own values, which targets get a 3D ring, and a
small ring written and marked the way the game carries it on."""

import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import NETHER, THE_END, NumericChunk
from worldbridge.terrain import dims16, nethercarver, netherbiomes, nethersurface, policy, ring3d
from worldbridge.terrain.nether import NetherGenerator

SEED = 7769476965016494779

# 4 x 4 cells [qx][qz] of chunks of the 26.3 Nether, taken from the chunks the game saved (0 nether_wastes,
# 1 soul_sand_valley, 2 crimson_forest, 3 warped_forest, 4 basalt_deltas)
GAME = {
    (-3, -22): [[2, 2, 2, 2], [3, 2, 2, 0], [3, 3, 3, 0], [3, 3, 3, 3]],
    (-2, -21): [[3, 0, 0, 0], [3, 3, 0, 0], [3, 3, 3, 0], [3, 3, 3, 3]],
    (-5, -12): [[2, 2, 2, 2], [2, 2, 2, 2], [2, 2, 2, 2], [2, 1, 1, 1]],
    (-4, -11): [[1, 1, 1, 2], [1, 1, 1, 1], [0, 0, 0, 0], [0, 0, 0, 0]],
    (-1, 3): [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0], [0, 4, 4, 4]],
    (12, -23): [[4, 3, 3, 3], [0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
    (-23, 1): [[4, 4, 4, 4]] * 4,
    (-23, -25): [[2, 2, 2, 2]] * 4,
}


def test_the_climate_noises_are_the_games_legacy_nether_noises():
    nb = netherbiomes.NetherBiomes(SEED)
    # NormalNoise.createForLegacyNetherBiome(LegacyRandomSource(seed)) of the 26.3 jar, (x, 0, z)
    want = [(0.0, 0.0, -0.20131783, 0.10925851), (13.7, -7.3, -0.23307565, 0.13695082),
            (27.4, -14.6, -0.18670052, 0.17831013), (68.5, -36.5, 0.09409829, 0.05631645)]
    for x, z, t, h in want:
        assert abs(float(nb.temperature.value(x, 0.0, z)) - t) < 1e-6
        assert abs(float(nb.vegetation.value(x, 0.0, z)) - h) < 1e-6


def test_the_biome_source_matches_the_game_cell_by_cell():
    nb = netherbiomes.NetherBiomes(SEED)
    for (cx, cz), want in GAME.items():
        assert nb.chunk(cx, cz).tolist() == want, (cx, cz)


def test_names_and_points():
    assert netherbiomes.NAMES[netherbiomes.BASALT_DELTAS] == "minecraft:basalt_deltas"
    assert len(netherbiomes.POINTS) == len(netherbiomes.NAMES) == 5


def _target(**kw):
    return TargetSpec(family="java", **kw)


def test_java_118_plus_targets_get_a_nether_ring():
    for version in (None, (1, 18, 0), (1, 21, 4), (26, 3, 0)):
        t = _target(java_mode="auto" if version is None else "amulet", version=version)
        assert ring3d.modern_target(t)
        assert ring3d.dimensions(t) == (NETHER, THE_END)
        gen, noise_only = ring3d.generator(t, SEED, NETHER)
        assert isinstance(gen, dims16.Nether16Generator) and not gen.legacy and noise_only
    # the policy still says the game blends the overworld
    assert policy.decide(_target(java_mode="auto"), False).kind == "game"


def test_older_and_other_targets_keep_their_rings():
    t17 = _target(java_mode="amulet", version=(1, 17, 1))
    assert not ring3d.modern_target(t17)
    gen, noise_only = ring3d.generator(t17, SEED, NETHER)
    assert isinstance(gen, dims16.Nether16Generator) and noise_only
    t12 = _target(java_mode="numeric", java_version_limit="1.12")
    assert not ring3d.modern_target(t12)
    assert isinstance(ring3d.generator(t12, SEED, NETHER)[0], NetherGenerator)
    assert not ring3d.modern_target(TargetSpec(family="bedrock", version=(1, 21, 0)))
    assert ring3d.dimensions(TargetSpec(family="bedrock", version=(1, 21, 0))) == ()


def _chunk_nbt(cx, cz, block="minecraft:netherrack"):
    sections = nbt.ListTag([nbt.CompoundTag({
        "Y": nbt.ByteTag(y),
        "block_states": nbt.CompoundTag({"palette": nbt.ListTag([nbt.StringTag(block)])}),
        "biomes": nbt.CompoundTag({"palette": nbt.ListTag([nbt.StringTag("minecraft:nether_wastes")])}),
    }) for y in range(8)])
    return nbt.CompoundTag({"DataVersion": nbt.IntTag(5020), "xPos": nbt.IntTag(cx), "zPos": nbt.IntTag(cz),
                            "Status": nbt.StringTag("minecraft:full"), "sections": sections,
                            "Heightmaps": nbt.CompoundTag({"WORLD_SURFACE": nbt.LongArrayTag(np.zeros(37, np.int64))}),
                            "isLightOn": nbt.ByteTag(1)})


def test_a_ring_chunk_is_marked_for_the_game_with_its_biomes(tmp_path):
    ring = ring3d.Ring3D(dims16.Nether16Generator(SEED, "1.16"), NETHER, [(0, 0)], seed=SEED, noise_only=True,
                         modern=True)
    ring.written = [(2, 1)]
    out = RegionWriter()
    out.put(2, 1, nbt.dump(_chunk_nbt(2, 1), ""))
    out.put(5, 5, nbt.dump(_chunk_nbt(5, 5), ""))                 # a converted chunk: untouched
    reg = tmp_path / "DIM-1" / "region"
    reg.mkdir(parents=True)
    out.write(str(reg / "r.0.0.mca"))
    assert ring3d.mark_modern(str(tmp_path), ring, "DIM-1/region") == 1
    r = JavaRegion(str(reg / "r.0.0.mca"))
    marked = nbt.load(r.read(2, 1), compressed=False).tag
    assert marked["Status"].py_str == "minecraft:terrain"
    assert int(marked["isLightOn"]) == 0 and len(marked["Heightmaps"]) == 0
    want = netherbiomes.NetherBiomes(SEED).chunk(2, 1)
    for sec in marked["sections"]:
        pal = [p.py_str for p in sec["biomes"]["palette"]]
        if len(pal) == 1:
            assert (want == netherbiomes.NAMES.index(pal[0])).all()
            continue
        bits = max(1, (len(pal) - 1).bit_length())
        data = [int(v) & (2 ** 64 - 1) for v in sec["biomes"]["data"]]
        per = 64 // bits
        for i in range(64):
            idx = (data[i // per] >> ((i % per) * bits)) & ((1 << bits) - 1)
            x, z = i & 3, (i >> 2) & 3
            assert pal[idx] == netherbiomes.NAMES[int(want[x, z])]
    other = nbt.load(r.read(5, 5), compressed=False).tag
    assert other["Status"].py_str == "minecraft:full"


def test_a_small_modern_ring_meets_the_converted_border():
    gen = dims16.Nether16Generator(SEED, "1.16")
    other = dims16.Nether16Generator(SEED + 1, "1.16")                      # a converted Nether of another world
    conv = [(x, z) for x in (0, 1) for z in (0, 1)]
    ring = ring3d.Ring3D(gen, NETHER, conv, seed=SEED, width=1, noise_only=True, modern=True)
    for cx, cz in conv:
        c = NumericChunk(cx, cz, 128)
        c.blocks[:] = np.transpose(other.chunk(cx, cz)[0], (2, 1, 0))
        ring.observe(NETHER, c)
    out = {(c.cx, c.cz): np.transpose(np.asarray(c.blocks)[:128], (2, 1, 0)) for c in ring.chunks()}
    assert len(out) == 4 * 4 - 4
    # no bedrock of its own (the game adds it), rock is netherrack, open space below y 32 is lava
    for b in out.values():
        assert not (b == 7).any()
        assert set(np.unique(b)) <= {0, 11, 87}


def test_the_ring_never_hangs_lava_in_the_air():
    """#192: the converted side's cave lava above the sea (or a sheet over air) must not be carried into the
    ring: lava is only the open space under y 32, nothing is a liquid without a block (or lava) below."""
    gen = dims16.Nether16Generator(SEED, "1.16")
    conv = [(x, z) for x in (0, 1) for z in (0, 1)]
    ring = ring3d.Ring3D(gen, NETHER, conv, seed=SEED, width=2, noise_only=True, modern=True)
    for cx, cz in conv:
        c = NumericChunk(cx, cz, 128)
        b = np.zeros((16, 16, 128), np.uint8)                              # [x, z, y]
        b[:, :, :40] = 87
        b[:, :, 40:46] = 0
        b[:, :, 46] = 11                                                   # a lava sheet over air at y 46 (and one at 70)
        b[:, :, 47:52] = 87
        b[:, :, 70] = 11
        b[:, :, 100:] = 87
        c.blocks[:] = np.transpose(b, (2, 1, 0))
        ring.observe(NETHER, c)
    out = [np.transpose(np.asarray(c.blocks)[:128], (2, 1, 0)) for c in ring.chunks()]
    assert out
    for b in out:
        lava = b == 11
        assert not lava[:, :, 32:].any()
        assert not (b[:, :, :32] == 0).any()                               # the sea fills every open cell under y 32
        assert not (lava[:, :, 1:] & (b[:, :, :-1] == 0)).any()


def test_the_games_caves_do_not_open_against_the_converted_border():
    """#192: a cavern of the game's carver (up to 65 blocks high) opened flush against the converted rock was a wall."""
    gen = dims16.Nether16Generator(SEED, "1.16")
    conv = [(x, z) for x in (0, 1) for z in (0, 1)]
    ring = ring3d.Ring3D(gen, NETHER, conv, seed=SEED, width=4, noise_only=True, modern=True)
    for cx, cz in conv:
        c = NumericChunk(cx, cz, 128)
        c.blocks[:] = np.transpose(gen.chunk(cx, cz)[0], (2, 1, 0))
        ring.observe(NETHER, c)
    near = ring3d._carve_gate(ring, 2, 0)                                  # next to the converted chunks
    far = ring3d._carve_gate(ring, 5, 0)                                   # the ring's outer edge
    assert near.shape == far.shape == (16, 16)
    assert not near[:, :4].any()
    assert far.all()


def test_the_cave_carver_digs_the_games_tunnels():
    caves = nethercarver.NetherCaves(SEED)
    gen = dims16.Nether16Generator(SEED, "1.16")
    # cells of netherrack (y 5..120) the carver opens in two chunks of the 26.3 Nether; the game's own chunks had
    # 1,909 and 6,831 open cells there (lakes and decoration make up the difference)
    for (cx, cz), ours, game in (((12, -12), 1896, 1909), ((0, -8), 6828, 6831)):
        rock = np.transpose(gen.chunk(cx, cz)[0], (2, 1, 0)) == 87
        rock[:5] = False
        rock[121:] = False
        n = int((caves.mask(cx, cz) & rock).sum())
        assert n == ours and abs(n - game) <= 0.01 * game
    assert len(caves.source(5, 1)) == 103
    assert caves.source(5, 1)[0].round(3).tolist() == [85.794, 108.995, 27.392, 1.5, 7.5]


def test_bedrock_follows_the_games_gradients():
    b = nethersurface.NetherSurface(SEED).bedrock(3, -4)
    assert b[0].all() and b[127].all() and not b[5:123].any()
    for y, p in ((1, 0.8), (2, 0.6), (3, 0.4), (4, 0.2)):
        assert abs(b[y].mean() - p) < 0.12                           # the floor thins out layer by layer
        assert abs(b[127 - y].mean() - p) < 0.12                     # and so does the roof


def test_the_surface_follows_the_biome():
    surf = nethersurface.NetherSurface(SEED)
    cat = np.zeros((128, 16, 16), np.int8)
    cat[:61] = 2                                                     # netherrack up to y 60, air above
    for biome, want in ((netherbiomes.CRIMSON_FOREST, {nethersurface.CRIMSON_NYLIUM, nethersurface.WART_BLOCK}),
                        (netherbiomes.WARPED_FOREST, {nethersurface.WARPED_NYLIUM, nethersurface.WARPED_WART}),
                        (netherbiomes.BASALT_DELTAS, {nethersurface.BLACKSTONE, nethersurface.BASALT, nethersurface.GRAVEL}),
                        (netherbiomes.SOUL_SAND_VALLEY, {nethersurface.SOUL_SAND, nethersurface.SOUL_SOIL, nethersurface.GRAVEL})):
        codes = surf.apply(10, 10, cat, np.full((4, 4), biome))
        top = set(np.unique(codes[60]).tolist()) - {0}
        assert top and top <= want, (biome, top)
    # under the roof every biome is netherrack (the rules stop at y 122), and the bedrock is the same everywhere
    roof = np.zeros((128, 16, 16), np.int8)
    roof[101:] = 2
    codes = surf.apply(10, 10, roof, np.full((4, 4), netherbiomes.CRIMSON_FOREST))
    assert set(np.unique(codes[122:127]).tolist()) <= {0, nethersurface.BEDROCK}


def test_end_biomes_follow_the_island_height():
    gen = dims16.End16Generator(SEED, "1.16")
    # chunks of a 26.3 End and the biome the game wrote for each
    for (cx, cz), want in (((-11, -14), "the_end"), ((-2, 77), "end_midlands"), ((-74, -13), "end_barrens"),
                           ((-1, 70), "small_end_islands"), ((-2, 80), "end_highlands")):
        assert gen.biome_name(cx, cz) == "minecraft:" + want


def test_the_end_gets_a_ring_too():
    t = _target(java_mode="auto")
    gen, noise_only = ring3d.generator(t, SEED, THE_END)
    assert isinstance(gen, dims16.End16Generator) and noise_only


def test_an_end_ring_chunk_gets_its_biome_and_no_nether_surface(tmp_path):
    ring = ring3d.Ring3D(dims16.End16Generator(SEED, "1.16"), THE_END, [(0, 0)], seed=SEED, noise_only=True, modern=True)
    ring.written = [(-2, 80)]
    out = RegionWriter()
    out.put(30, 16, nbt.dump(_chunk_nbt(-2, 80, "minecraft:end_stone"), ""))
    reg = tmp_path / "DIM1" / "region"
    reg.mkdir(parents=True)
    out.write(str(reg / "r.-1.2.mca"))
    assert ring3d.mark_modern(str(tmp_path), ring, "DIM1/region") == 1
    chunk = nbt.load(JavaRegion(str(reg / "r.-1.2.mca")).read(30, 16), compressed=False).tag
    assert chunk["Status"].py_str == "minecraft:terrain"
    for sec in chunk["sections"]:
        assert [p.py_str for p in sec["biomes"]["palette"]] == ["minecraft:end_highlands"]
        assert [p.py_str for p in sec["block_states"]["palette"]] == ["minecraft:end_stone"]


def test_the_ring_is_only_made_for_chunks_written_in_the_1_18_format():
    from worldbridge import convert

    t = _target(java_mode="auto")
    plan = policy.Plan("game", "")
    # a pre-1.18 source written in the 1.17 format for the game to upgrade: no ring (the game blends)
    assert convert._make_rings3d(t, SEED, {NETHER: [(0, 0)]}, plan) == {}
    rings = convert._make_rings3d(t, SEED, {NETHER: [(0, 0)], THE_END: [(0, 0)]}, plan, modern_ok=True)
    assert set(rings) == {NETHER, THE_END} and all(r.modern and r.noise_only for r in rings.values())
    assert convert._make_rings3d(_target(java_mode="auto", ring=False), SEED, {NETHER: [(0, 0)]}, plan, modern_ok=True) == {}
    assert list(convert._make_rings3d(_target(java_mode="numeric", java_version_limit="1.12"), SEED,
                                      {NETHER: [(0, 0)]}, plan)) == [NETHER]
