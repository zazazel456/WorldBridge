"""Chests for the games that pair every chest with any chest beside it (LCE, Java up to 1.12)."""
import numpy as np

from worldbridge import nbt
from worldbridge.chestfix import CHEST, TRAPPED, ChestRows
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.model import NumericChunk, Progress

from .helpers import SyntheticWorld


def _chest(c, x, y, z, facing, n):
    c.blocks[y, z & 15, x & 15] = CHEST
    c.data[y, z & 15, x & 15] = facing
    items = nbt.ListTag([nbt.CompoundTag({"id": nbt.ShortTag(1), "Count": nbt.ByteTag(n), "Damage": nbt.ShortTag(0),
                                          "Slot": nbt.ByteTag(0)})], 10)
    c.tile_entities.append(nbt.CompoundTag({"id": nbt.StringTag("Chest"), "x": nbt.IntTag(x), "y": nbt.IntTag(y),
                                            "z": nbt.IntTag(z), "Items": items}))


def _world():
    """Two chunks: a row of 8 chests facing north across their border, the row behind facing south,
    a lone chest and a proper double chest."""
    a, b = NumericChunk(0, 0, 256), NumericChunk(1, 0, 256)
    n = 1
    for x in range(10, 18):
        _chest(a if x < 16 else b, x, 70, 4, 2, n)
        _chest(a if x < 16 else b, x, 70, 5, 3, n + 8)
        n += 1
    _chest(a, 2, 70, 12, 2, 20)
    _chest(a, 5, 70, 12, 2, 21)
    _chest(a, 6, 70, 12, 2, 22)
    return {(0, 0): a, (1, 0): b}


def _kinds(chunks, z):
    return "".join({CHEST: "C", TRAPPED: "T"}[int(chunks[(x >> 4, 0)].blocks[70, z, x & 15])]
                   for x in range(10, 18))


def test_rows_of_double_chests_are_paired_again():
    chunks = _world()
    rows = ChestRows(lambda dim, cx, cz: chunks.get((cx, cz)))
    for c in chunks.values():                     # each chunk on its own, as the conversion does
        rows.fix(0, c)
    front, back = _kinds(chunks, 4), _kinds(chunks, 5)
    assert front in ("CCTTCCTT", "TTCCTTCC")      # every pair drawn: no chest beside a foreign pair
    assert back == front.translate(str.maketrans("CT", "TC"))    # the row behind does not join it
    a = chunks[(0, 0)]
    assert a.blocks[70, 12, 2] == CHEST and a.blocks[70, 12, 5] == CHEST and a.blocks[70, 12, 6] == CHEST


def test_a_trapped_chest_keeps_its_contents_in_lce(tmp_path):
    src = SyntheticWorld(radius=1)
    chunks = _world()
    ChestRows(lambda dim, cx, cz: chunks.get((cx, cz))).fix(0, chunks[(0, 0)])
    wr = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64", world_size=54, offset_x=0, offset_z=0),
                   Progress())
    wr.add_chunk(0, chunks[(0, 0)])
    path = wr.finish(src.info)
    c = LCEWorld(path).read_chunk(0, 0, 0)
    tiles = {(int(nbt.get(t, "x")), int(nbt.get(t, "z"))): t for t in c.tile_entities}
    for x in range(10, 16):
        assert c.blocks[70, 4, x] in (CHEST, TRAPPED)
        t = tiles[(x, 4)]
        assert int(nbt.get(nbt.get_tag(t, "Items")[0], "Count")) == x - 9
    assert int(np.isin(c.blocks, [TRAPPED]).sum()) > 0


def test_any_group_of_touching_chests_is_drawn_whole():
    """Random groups (rows, 2x2 blocks, columns, L shapes...): afterwards every chest touches at most
    one chest of its own kind, and then the two make a proper double chest, which the game draws."""
    rng = np.random.default_rng(7)
    for trial in range(2000):
        c = NumericChunk(0, 0, 256)
        facing = int(rng.choice([2, 3, 4, 5]))
        cells = {(8, 8)}
        for _ in range(int(rng.integers(1, 12))):
            x, z = list(cells)[int(rng.integers(len(cells)))]
            dx, dz = [(1, 0), (-1, 0), (0, 1), (0, -1)][int(rng.integers(4))]
            if 0 <= x + dx < 16 and 0 <= z + dz < 16:
                cells.add((x + dx, z + dz))
        for x, z in cells:
            c.blocks[64, z, x] = CHEST
            c.data[64, z, x] = facing
        ChestRows(lambda dim, cx, cz: c if (cx, cz) == (0, 0) else None).fix(0, c)
        for x, z in cells:
            kind = c.blocks[64, z, x]
            same = [(x + dx, z + dz) for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1))
                    if 0 <= x + dx < 16 and 0 <= z + dz < 16 and c.blocks[64, z + dz, x + dx] == kind]
            assert len(same) <= 1, (trial, sorted(cells), (x, z))
            if same:
                px, pz = same[0]
                along_x = pz == z
                assert along_x == (facing in (2, 3)), (trial, sorted(cells), (x, z))
