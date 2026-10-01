"""The border of converted worlds: the remedy for every target, the ring's width, finite worlds filled."""
import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.model import NumericChunk, Progress
from worldbridge.terrain import policy
from worldbridge.terrain.filler import FillGenerator
from worldbridge.terrain.ring import Ring

from .helpers import SyntheticWorld


def test_every_target_gets_a_remedy_or_a_warning():
    T = TargetSpec
    cases = [
        (T(family="java"), "game"), (T(family="java", java_mode="amulet", version=(1, 20, 1)), "game"),
        (T(family="java", java_mode="mcregion", java_version_limit="b1.7"), "ring"),
        (T(family="java", java_mode="mcregion", java_version_limit="1.1"), "ring"),
        (T(family="java", java_mode="alpha", java_version_limit="b1.2"), "ring"),
        (T(family="java", java_mode="numeric", java_version_limit="1.12"), "ring"),
        (T(family="java", java_mode="numeric", java_version_limit="1.4"), "ring"),
        (T(family="java", java_mode="amulet", version=(1, 16, 5)), "ring"),
        (T(family="bedrock", version=(1, 21, 50)), "game"), (T(family="bedrock", version=(1, 16, 0)), "missing"),
        (T(family="lce", lce_platform="xbox360", lce_world_size=54), "fill"),
        (T(family="lce", lce_platform="xboxone", lce_world_size=320), "missing"),
        (T(family="lce", lce_world_size=320), "ring"),                                   # PC: neoLegacy
        (T(family="pe_old"), "fill"), (T(family="lce", ring=False), "off"),
        (T(family="java", java_mode="numeric", java_version_limit="1.12", ring=False), "off"),
        (T(family="java", java_mode="numeric", java_version_limit="1.12", blend=False), "ring"),
        (T(family="java", blend=False), "off"), (T(family="java", ring=False), "game"),
    ]
    for t, kind in cases:
        assert policy.decide(t, old_source=True).kind == kind, (t, kind)


class _Flat:
    """A generator whose terrain is flat at y 64."""
    def chunk(self, cx, cz):
        b = np.zeros((16, 16, 128), np.uint8)
        b[:, :, 0] = 7
        b[:, :, 1:64] = 1
        b[:, :, 64] = 2
        return b, np.ones((16, 16), np.int64)


def _edge(cx, cz, h):
    c = NumericChunk(cx, cz, 256)
    c.blocks[1:h] = 1
    c.blocks[h] = 2
    return c


def test_the_ring_widens_where_the_height_difference_is_large():
    low = Ring(_Flat(), 62, [(0, 0)])
    low.observe(0, _edge(0, 0, 70))
    high = Ring(_Flat(), 62, [(0, 0)])
    high.observe(0, _edge(0, 0, 150))
    assert len(high.targets()) > len(low.targets()) and high.ring > low.ring == 3
    # and the ground goes down gently: never more than a few blocks between neighbouring columns
    tops = {}
    for c in high.chunks():
        b = np.asarray(c.blocks)
        tops[(c.cx, c.cz)] = 255 - np.argmax((b != 0)[::-1], axis=0)
    row = np.concatenate([tops[(x, 0)][8] for x in range(1, high.ring + 1)])
    assert np.abs(np.diff(row)).max() <= 4 and row[-1] == 64


def test_filler_terrain_is_natural_and_fast():
    import time

    g = FillGenerator(42)
    t = time.time()
    hs = [g.heights(cx, cz) for cx in range(16) for cz in range(16)]
    assert (time.time() - t) / 256 < 0.05
    h = np.concatenate([x.ravel() for x in hs])
    assert 30 <= h.min() and h.max() <= 120 and np.abs(np.diff(hs[0], axis=0)).max() <= 4


def test_pocket_edition_worlds_are_written_whole(tmp_path):
    src = SyntheticWorld(radius=1)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    out = str(tmp_path / "pe")
    res = convert(hub, out, TargetSpec(family="pe_old"))
    from worldbridge.bedrock.pe_old import PEOldWorld

    pe = PEOldWorld(out)
    assert len(pe.chunk_coords(0)) == 256                                     # all of the 16 x 16 chunks


def test_lce_worlds_are_written_whole(tmp_path):
    src = SyntheticWorld(radius=1)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    out = str(tmp_path / "lce")
    convert(hub, out, TargetSpec(family="lce", lce_platform="xbox360", lce_profile="tu54", lce_world_size=54))
    from worldbridge import detect as det
    from worldbridge.lce.world import LCEWorld

    d = det.detect(out)
    w = LCEWorld(d.path)
    assert len(w.chunk_coords(0)) == 54 * 54


def test_lce_to_lce_needs_nothing():
    assert policy.decide(TargetSpec(family="lce", lce_world_size=54), True, "lce").kind == "game"


def test_the_sea_levels_of_old_and_new_games():
    from worldbridge import detect as det
    from worldbridge.convert import source_sea, target_sea
    from worldbridge.model import WorldInfo

    info = WorldInfo()
    assert source_sea(det.Detected("pe_old", "", ""), info) == 63
    assert source_sea(det.Detected("java_numeric", "", "", "mcregion"), info) == 63          # Beta 1.3 - 1.7.3
    info.level["GameType"] = nbt.IntTag(0)
    assert source_sea(det.Detected("java_numeric", "", "", "mcregion"), info) == 62          # Beta 1.8 - 1.1
    assert target_sea(TargetSpec(family="pe_old")) == 63 and target_sea(TargetSpec(family="java")) == 62


def test_pocket_edition_worlds_come_down_one_block_in_java(tmp_path):
    from worldbridge.bedrock.pe_old import PEOldWriter
    from worldbridge.java.numeric import JavaNumericWorld
    from worldbridge.model import WorldInfo

    pe = str(tmp_path / "pe")
    w = PEOldWriter(pe, Progress())
    for cx in range(16):
        for cz in range(16):
            c = NumericChunk(cx, cz, 128)
            c.blocks[0] = 7
            c.blocks[1:60] = 1
            c.blocks[60:64] = 9                     # PE sea: water up to y 63
            w.add_chunk(0, c)
    info = WorldInfo()
    info.level["SpawnY"] = nbt.IntTag(70)
    w.finish(info)
    out = str(tmp_path / "java")
    convert(pe, out, TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    b = np.asarray(JavaNumericWorld(out).read_chunk(0, 5, 5).blocks)
    col = b[:, 8, 8]
    assert int(np.nonzero(col == 9)[0].max()) == 62 and col[0] == 7            # sea at y 62, floor kept


def test_chunks_the_game_has_not_finished_are_left_out(tmp_path):
    from worldbridge.incomplete import java_incomplete
    from worldbridge.java.region import RegionWriter
    from worldbridge.selection import Selection

    region = tmp_path / "w" / "region"
    region.mkdir(parents=True)
    rw = RegionWriter()
    for (x, z), status in (((0, 0), "minecraft:full"), ((1, 0), "minecraft:structure_starts"),
                           ((2, 0), "minecraft:terrain"), ((3, 0), "minecraft:full")):
        root = nbt.CompoundTag({"xPos": nbt.IntTag(x), "zPos": nbt.IntTag(z), "Status": nbt.StringTag(status)})
        rw.put(x, z, nbt.dump(root, ""))
    rw.write(str(region / "r.0.0.mca"))
    excl = java_incomplete(str(tmp_path / "w"))
    assert excl == {0: {(1, 0), (2, 0)}}
    sel = Selection(exclude=excl)
    assert sel.filter(0, [(0, 0), (1, 0), (2, 0), (3, 0)]) == [(0, 0), (3, 0)] and sel.filters


def test_compression_starts_only_where_needed():
    from worldbridge.heightfit import KNEE, HeightFit

    def fit_for(top):
        f = HeightFit(128)
        c = NumericChunk(0, 0, 256)
        c.blocks[1:top] = 1
        f.observe(c)
        return f

    assert fit_for(140).knee > 90                  # a little too high: only the top is squeezed
    assert fit_for(250).knee == KNEE               # Amplified: from y 80
    assert not fit_for(110).needed                 # fits: nothing moves


def test_the_ring_is_the_generators_own_terrain_lifted():
    gen = FillGenerator(42)
    edge = _edge(0, 0, 95)
    for x, z in ((3, 3), (8, 10), (12, 4)):          # a few trees on the converted border
        edge.blocks[96:101, z, x] = 17
    ring = Ring(gen, 62, [(0, 0)])
    ring.observe(0, edge)
    out = {(c.cx, c.cz): c for c in ring.chunks()}
    assert len(out) == len(ring.targets()) and ring.planted > 0
    top = lambda b: b.shape[0] - 1 - np.argmax(np.isin(b, (1, 2, 3, 12, 13, 24))[::-1], axis=0)  # noqa: E731  [z, x]
    for (cx, cz), c in out.items():
        lift = ring.lift(cx, cz)
        g, _ = gen.chunk(cx, cz)
        h_gen = top(np.transpose(g, (2, 1, 0)))
        want = h_gen + (lift.T if lift is not None else 0)
        # the generator's relief, moved up or down: not a height map made anew
        assert (np.abs(top(np.asarray(c.blocks)) - np.clip(want, 2, 125)) <= 1).mean() > 0.99
    # the outer border is the game's own terrain, the inner one meets the converted ground
    far = max(x for x, z in out if z == 0)
    g, _ = gen.chunk(far, 0)
    assert (top(np.transpose(g, (2, 1, 0)))[:, 15] == top(np.asarray(out[(far, 0)].blocks))[:, 15]).all()
    assert np.abs(top(np.asarray(out[(1, 0)].blocks))[:, 0] - 95).max() <= 3


def test_the_ring_never_leaves_water_walls():
    # the converted world has a dry canyon below the sea next to the ring (x = 16 of chunk (0, 0) is
    # air from y 40 up), the ring's lifted ground there is under the sea: its water would stand as
    # a wall.  The ring's column facing the canyon becomes ground; the converted chunk is untouched.
    import numpy as np

    from worldbridge.model import NumericChunk
    from worldbridge.terrain.ring import Ring

    r = Ring(None, 63, [(1, 0)])
    conv = np.zeros((256, 16, 16), np.uint16)
    conv[:40] = 1
    r.faces[(1, 0)] = (conv[:, :, 0], conv[:, :, 15], conv[:, 0, :], conv[:, 15, :])
    c = NumericChunk(0, 0, 256)
    c.blocks[:50] = 1
    c.blocks[50:63] = 9                                          # the sea over the ring's ground
    c.blocks[50:63, :, 3] = 0                                    # and a dry pit inside the ring
    assert r._seal(c) > 0
    b = np.asarray(c.blocks)
    assert (b[50:63, :, 15] != 9).all() and (b[50:63, :, 15] != 0).all()    # the wall facing the canyon
    assert (b[50:63, :, 3] == 1).all()                                       # the pit is filled
    assert (b[50:63, :, 5:14] == 9).all()                                    # the sea itself stays
    assert b[62, 0, 15] == 1 and (b[63:, :, :] == 0).all()


def test_ring_cover_never_asks_for_a_negative_amount():
    """The relaxation may overshoot below 0 (or leave NaN) on big, unconverged pieces: the planned
    trees, grass and flowers stay >= 0 (numpy's poisson refuses anything else)."""
    import numpy as np

    from worldbridge.terrain import ring as ring_mod

    r = ring_mod.Ring.__new__(ring_mod.Ring)
    r._piece_of = {(0, 0): 0}
    psi = np.full((6, 2, 2), -0.3, np.float32)
    psi[5] = np.nan
    r._pieces = {0: (0, 0, 8, psi, np.ones((2, 2), np.float32))}
    out = r._plan(0, 0)
    assert all(np.isfinite(v) and v >= 0 for v in out)


def test_ring_sea_takes_a_sea_biome():
    """Ring ground lowered under the sea keeps no land biome (the game would dress the water as a
    swamp / forest); the game's own terrain (no lift) and the seas' biomes stay as they are."""
    import numpy as np

    from worldbridge.model import NumericChunk
    from worldbridge.terrain.ring import sea_biomes

    c = NumericChunk(0, 0, 256)
    c.blocks[:50] = 1
    c.blocks[50:63] = 9                      # water up to y 62
    c.biomes = np.full((16, 16), 6, np.uint8)             # swamp
    c.biomes[:, 8:] = 12                                  # ice plains
    c.biomes[0, 0] = 7                                    # river
    lift = np.full((16, 16), -10.0)                       # [x, z]
    lift[0, :] = 0.0                                      # x = 0: the game's terrain
    n = sea_biomes(c, lift, 62)
    assert c.biomes[5, 3] == 0 and c.biomes[5, 10] == 10  # ocean, frozen ocean
    assert c.biomes[0, 0] == 7 and c.biomes[3, 0] == 6    # river kept, unlifted column kept
    assert n == 16 * 15                                   # all but the unlifted column x = 0
    dry = NumericChunk(0, 0, 256)
    dry.blocks[:70] = 1
    dry.biomes = np.full((16, 16), 6, np.uint8)
    assert sea_biomes(dry, lift, 62) == 0 and (dry.biomes == 6).all()
