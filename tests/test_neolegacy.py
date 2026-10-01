"""neoLegacy: its 16 x 16 region files, its biomes and terrain, the ring of LCE targets."""
import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.model import Progress
from worldbridge.terrain import policy
from worldbridge.terrain.neogen import NeoGenerator
from worldbridge.terrain.neolayers import NeoStack

from .helpers import SyntheticWorld

SEED = -3112930505348390392


def _to_neo(tmp_path, size=64):
    src = SyntheticWorld(radius=2)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    src.info.level["RandomSeed"] = nbt.LongTag(SEED)
    w.finish(src.info)
    out = str(tmp_path / "lce")
    convert(hub, out, TargetSpec(family="lce", lce_platform="win64", lce_profile="tu31", lce_world_size=size))
    from worldbridge import detect as det
    from worldbridge.lce.world import LCEWorld

    return LCEWorld(det.detect(out).path)


def test_region_format_16_is_read_where_it_belongs(tmp_path):
    from worldbridge.lce import region as lreg
    from worldbridge.lce.world import LCEWorld

    w = _to_neo(tmp_path)
    before = {c: np.asarray(w.read_chunk(0, *c).blocks) for c in w.chunk_coords(0)}
    cont = w.container
    # the same chunks, stored as neoLegacy stores its new worlds: 16 x 16 chunks per region file
    chunks = {}
    for name in [n for n in cont.files if n.startswith("r.")]:
        rx, rz = (int(v) for v in name[2:-4].split("."))
        for lx, lz, payload, _rle, dlen in lreg.iter_region_chunks(cont.files.pop(name), cont.endian, 32):
            cx, cz = rx * 32 + lx, rz * 32 + lz
            chunks.setdefault((cx >> 4, cz >> 4), {})[(cx & 15, cz & 15)] = (payload, dlen)
    for (rx, rz), c in chunks.items():
        cont.files[f"r.{rx}.{rz}.mcr"] = lreg.build_region(c, cont.endian)
    cont.files["region_format_16"] = b""
    path = cont.save(str(tmp_path / "neo16"))
    w16 = LCEWorld(path)
    assert sorted(w16.chunk_coords(0)) == sorted(before)
    for c, b in before.items():
        assert (np.asarray(w16.read_chunk(0, *c).blocks) == b).all()


def test_neolegacy_biomes_are_its_own_stack():
    s = NeoStack(SEED)
    b = s.biomes(0, 0, 64, 64)
    # the 4J stack: hills spots become "M" biomes, the biomes of the Java 1.7 desert list are missing
    assert b.shape == (64, 64) and set(np.unique(b)) <= set(range(40)) | set(range(129, 168))
    assert (s.biomes4(-8, -8, 16, 16) == s.biomes4(-8, -8, 16, 16)).all()
    assert not np.isin(s.biomes(-2048, -2048, 512, 512), (35, 36)).any()        # no savanna in the warm list


def test_the_edge_of_an_lce_map_sinks_into_the_sea():
    g = NeoGenerator(SEED, xz_size=54, caves=False)
    blocks, _, _ = g.chunk(26, 0)                       # the last chunk of a 54-chunk map
    last = blocks[15]                                   # the column on the very edge: x = 431
    y = np.arange(128)
    assert (last[:, y <= 53] != 0).all() and np.isin(last[:, (y > 53) & (y < 63)], (8, 9)).all()
    assert np.isin(last[:, 63:], (0, 111)).all()                   # air (a swamp may leave a lily pad)


def test_neolegacy_targets_get_a_ring_of_the_games_terrain(tmp_path):
    t = TargetSpec(family="lce", lce_platform="win64", lce_profile="tu31", lce_world_size=320)
    assert policy.decide(t, True).kind == "ring"
    assert policy.decide(TargetSpec(family="lce", lce_world_size=320), True).kind == "ring"      # PC = neoLegacy
    assert policy.decide(TargetSpec(family="lce", lce_platform="xboxone", lce_world_size=320), True).kind == "missing"
    w = _to_neo(tmp_path)
    coords = w.chunk_coords(0)
    assert len(coords) > 16                             # the converted chunks and the ring
    g = NeoGenerator(SEED, xz_size=64)
    xs = sorted({c[0] for c in coords})
    for cz in sorted({c[1] for c in coords}):
        c = np.asarray(w.read_chunk(0, xs[0], cz).blocks)[:128]
        gb = np.transpose(g.chunk(xs[0], cz)[0], (2, 1, 0))
        assert (c[:, :, 0] == gb[:, :, 0]).all()         # the outer edge is the game's own terrain


def test_players_of_java_1_16_and_later_reach_lce_and_pocket_edition():
    from worldbridge.lce.world import LCEWriteOptions, legacy_player
    from worldbridge.model import dimension_of

    p = nbt.CompoundTag({"Dimension": nbt.StringTag("minecraft:overworld"),
                         "Pos": nbt.ListTag([nbt.DoubleTag(8.5), nbt.DoubleTag(70.0), nbt.DoubleTag(8.5)], 6)})
    out = legacy_player(p, LCEWriteOptions(), lambda dim, cx, cz: (cx, cz))
    assert nbt.get(out, "Dimension") == 0
    assert dimension_of(nbt.CompoundTag({"Dimension": nbt.StringTag("minecraft:the_nether")})) == -1
    assert dimension_of(nbt.CompoundTag({})) == 0
