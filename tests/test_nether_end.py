"""The Nether and the End: generators checked against the games' own code, the 3D ring, regenerating
a dimension.  The fingerprints below are of chunks / density columns the games generated (with the
seeds and coordinates given), compared block by block and bit by bit before being written here."""

import hashlib

import numpy as np

from worldbridge import nbt
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.model import NETHER, THE_END, NumericChunk, Progress
from worldbridge.terrain import dims16
from worldbridge.terrain.end import EndGenerator
from worldbridge.terrain.nether import Nether13Generator, NetherGenerator
from worldbridge.terrain.ring3d import Ring3D, _NETHER_ROCK

from .helpers import SyntheticWorld

S = -3878429724685138167


def _md5(a) -> str:
    return hashlib.md5(np.ascontiguousarray(a).tobytes()).hexdigest()


def test_nether_chunks_as_the_games_generate_them():
    assert _md5(NetherGenerator(123).chunk(1, 1)[0]) == "a7870fe5022a5ebed6bf5c83d921ec0f"               # 1.12.2
    assert _md5(NetherGenerator(S).chunk(4, -5)[0]) == "b1101e7f74131247ddd4c336f1d999a7"                 # 1.6.4
    assert _md5(NetherGenerator(S, "mid").chunk(-2, 3)[0]) == "3bf016e4010be6c5e28a0a14446d74fb"          # 1.2.5
    assert _md5(Nether13Generator(987654321).chunk(55, -45)[0]) == "e742e08dec7612bee68e6e8a6d566397"      # 1.13.2


def test_end_chunks_as_the_games_generate_them():
    assert _md5(EndGenerator(S).chunk(115, 2)[0]) == "73c164dd327f9e27f2c84ccc7d9c65b3"                   # 1.12.2, outer island
    assert _md5(EndGenerator(S, islands=False).chunk(3, -2)[0]) == "b9eee2ba9eba90d3970b4e61bd4f6c0a"     # 1.6.4
    blocks, biomes = EndGenerator(S, version="1.13").chunk(119, 3)                                         # 1.13.2
    assert _md5(blocks) == "d1a101c69f968080b4238810ac83ef92"
    assert EndGenerator(S, version="1.13").biome(0, 0) == 9


def test_noise_columns_as_the_games_compute_them():
    for gen, x, z, want in ((dims16.Nether16Generator(12345, "1.16"), -250, -250, "a845be90ab56d88aa310d9df8d59c39a"),
                            (dims16.Nether16Generator(12345, "1.15"), 7, -3, "4090cb88710e47be6a43a817369c28aa"),
                            (dims16.End16Generator(S, "1.16"), 210, -5, "f56c49b0674c26d44be59c19874eb0e0"),
                            (dims16.End16Generator(S, "1.15"), 210, -5, "a3bbc0e3d70c445f50c411cdfdfb4b33")):
        assert _md5(gen.grid([x], [z])[0, 0].astype(np.float64)) == want


def test_the_nether_ring_goes_smoothly_from_the_converted_border_to_the_game():
    # a converted Nether from another world (seed 111) in a world whose seed is 222
    src, gen = NetherGenerator(111), NetherGenerator(222)
    conv = [(x, z) for x in (-1, 0) for z in (-1, 0)]
    ring = Ring3D(gen, NETHER, conv, seed=222, width=2)
    for cx, cz in conv:
        c = NumericChunk(cx, cz, 128)
        c.blocks[:] = np.transpose(src.chunk(cx, cz)[0], (2, 1, 0))
        ring.observe(NETHER, c)
    out = {(c.cx, c.cz): np.transpose(np.asarray(c.blocks)[:128], (2, 1, 0)) for c in ring.chunks()}
    assert len(out) == 6 * 6 - 4
    rock = _NETHER_ROCK
    # right outside the converted chunk (0, 0), the ring's first column is almost the converted one
    a = rock[src.chunk(0, 0)[0][15, :, :].astype(np.int64)]
    b = rock[out[(1, 0)][0, :, :].astype(np.int64)]
    assert (a != b).mean() < 0.02
    # at the ring's outer edge, the game's own terrain
    far = out[(2, 2)]
    assert (far[15, 15] == gen.chunk(2, 2)[0][15, 15]).all()


def test_a_dimension_can_be_left_to_the_game(tmp_path):
    from worldbridge.convert import TargetSpec, convert

    src = SyntheticWorld(radius=1)
    src.info.players["host"]["Dimension"] = nbt.IntTag(-1)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
        c = NumericChunk(cx, cz, 256)
        c.blocks[:128] = 87
        w.add_chunk(NETHER, c)
    w.finish(src.info)
    out = str(tmp_path / "out")
    convert(hub, out, TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12", regen=(NETHER,)))
    world = JavaNumericWorld(out)
    assert not world.chunk_coords(NETHER) and world.chunk_coords(0)
    p = next(iter(world.info.players.values())) if world.info.players else world.info.level.get("Player")
    assert int(nbt.get(p, "Dimension", 0)) == 0
