"""Mountains taller than a 128 high target are compressed, not cut."""
import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.heightfit import KNEE, HeightFit
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.model import NumericChunk, Progress, WorldInfo


def _column_world(heights):
    """{(cx, cz): ground y}: stone up to y - 3, dirt, grass on top."""
    chunks = {}
    for (cx, cz), h in heights.items():
        c = NumericChunk(cx, cz, 256)
        c.blocks[0] = 7
        c.blocks[1:h - 3] = 1
        c.blocks[h - 3:h] = 3
        c.blocks[h] = 2
        chunks[(cx, cz)] = c
    return chunks


def _fit(chunks, ceiling=128):
    fit = HeightFit(ceiling)
    for c in chunks.values():
        fit.observe(c)
    return fit


def test_mountains_come_down_with_their_surface_and_low_land_stays():
    chunks = _column_world({(0, 0): 200, (1, 0): 200, (2, 0): 200, (5, 0): 70})
    fit = _fit(chunks)
    assert fit.needed
    peak = fit.apply(chunks[(1, 0)])
    col = np.asarray(peak.blocks[:, 8, 8])
    top = int(np.nonzero(col)[0].max())
    assert top <= 127 - 10 and col[top] == 2 and (col[top - 3:top] == 3).all()   # grass + dirt intact
    assert col[0] == 7 and (col[1:top - 3] == 1).all()                           # rock below, no holes
    low = fit.apply(chunks[(5, 0)])
    assert int(np.nonzero(np.asarray(low.blocks[:, 8, 8]))[0].max()) == 70          # under the knee: untouched


def test_nothing_changes_when_everything_fits():
    chunks = _column_world({(0, 0): 100, (1, 0): 110})
    fit = _fit(chunks)
    assert not fit.needed


def test_a_base_inside_the_mountain_comes_down_whole():
    chunks = _column_world({(x, z): 200 for x in range(-1, 2) for z in range(-1, 2)})
    c = chunks[(0, 0)]
    c.blocks[150:155, 4:9, 4:9] = 5          # plank room, air inside, a chest on the floor
    c.blocks[151:154, 5:8, 5:8] = 0
    c.blocks[151, 6, 6] = 54
    c.tile_entities.append(nbt.CompoundTag({"id": nbt.StringTag("minecraft:chest"), "x": nbt.IntTag(6),
                                            "y": nbt.IntTag(151), "z": nbt.IntTag(6)}))
    before = np.asarray(c.blocks[150:155, 4:9, 4:9]).copy()
    fit = _fit(chunks)
    c = fit.apply(c)
    assert fit.lost_tiles == 0
    (t,) = c.tile_entities
    y = int(nbt.get(t, "y"))
    assert y < 128 and c.blocks[y, 6, 6] == 54
    assert (np.asarray(c.blocks[y - 1:y + 4, 4:9, 4:9]) == before).all()           # room not sheared


def test_players_and_mobs_follow_their_ground():
    chunks = _column_world({(0, 0): 200, (1, 0): 200})
    fit = _fit(chunks)
    c = chunks[(0, 0)]
    c.entities.append(nbt.CompoundTag({"id": nbt.StringTag("minecraft:cow"),
                                       "Pos": nbt.ListTag([nbt.DoubleTag(8.5), nbt.DoubleTag(201.0), nbt.DoubleTag(8.5)], 6)}))
    c = fit.apply(c)
    ground = int(np.nonzero(np.asarray(c.blocks[:, 8, 8]))[0].max())
    assert float(nbt.get_tag(c.entities[0], "Pos")[1].py_data) == ground + 1
    assert fit.shift_at(8.5, 201.0, 8.5) == ground + 1


def test_float_positions_move_with_the_ground():
    from worldbridge.heightfit import _move_entity
    chunks = _column_world({(0, 0): 200, (1, 0): 200})
    fit = _fit(chunks)
    e = nbt.CompoundTag({"id": nbt.StringTag("Pig"), "Pos": nbt.ListTag([nbt.FloatTag(8.5), nbt.FloatTag(201.0), nbt.FloatTag(8.5)], 5)})
    _move_entity(e, fit)
    assert e["Pos"].list_data_type == 6 and float(e["Pos"][1].py_data) < 201.0


def test_a_column_at_the_very_bottom_is_left_alone():
    chunks = _column_world({(x, z): 200 for x in range(-1, 2) for z in range(-1, 2)})
    chunks[(0, 0)].blocks[255, 0, 0] = 5               # something built in the column
    fit = _fit(chunks)
    fit.heights[(0, 0)][0, 0] = 2                      # sky-island maps: a surface under the band's start
    fit.shifts(0, 0)[0, 0] = 5
    c = fit.apply(chunks[(0, 0)])                      # (used to raise: argmin of an empty sequence)
    assert int(np.nonzero(np.asarray(c.blocks[:, 8, 8]))[0].max()) < 200


def _hub(tmp_path, heights):
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for c in _column_world(heights).values():
        w.add_chunk(0, c)
    info = WorldInfo()
    info.level["LevelName"] = nbt.StringTag("alti")
    info.level["SpawnX"], info.level["SpawnY"], info.level["SpawnZ"] = nbt.IntTag(8), nbt.IntTag(201), nbt.IntTag(8)
    w.finish(info)
    return hub


def test_convert_to_java_1_1_compresses_or_cuts(tmp_path):
    hub = _hub(tmp_path, {(x, z): 200 for x in range(2) for z in range(2)})
    for mode in ("compress", "cut"):
        out = str(tmp_path / mode)
        convert(hub, out, TargetSpec(family="java", java_mode="mcregion", java_version_limit="1.1", tall_terrain=mode))
        w = JavaNumericWorld(out)
        col = np.asarray(w.read_chunk(0, 0, 0).blocks[:, 8, 8])
        top = int(np.nonzero(col)[0].max())
        spawn_y = int(nbt.get(w.info.level, "SpawnY"))
        if mode == "compress":
            assert top < 127 - 5 and col[top] == 2 and spawn_y == top + 1
        else:
            assert top == 127 and col[top] == 1                                    # the old flat stone table
    assert KNEE < 100


def test_new_java_1_18_to_1_21_worlds_keep_y_below_0_and_above_255(tmp_path):
    # Amulet read the heights of the world it writes from a level.dat that had none: 0 - 255
    from worldbridge import amulet_bridge as ab

    for v in ((1, 18, 2), (1, 21, 4), (26, 3, 0)):
        w = ab.make_wrapper(str(tmp_path / f"w{v}"), "java", v)
        try:
            ow = w.bounds("minecraft:overworld").bounds
            nether = w.bounds("minecraft:the_nether").bounds
        finally:
            w.close()
        assert (ow[0][1], ow[1][1]) == (-64, 320) and (nether[0][1], nether[1][1]) == (0, 256)


def test_amplified_preset_survives_into_the_level_dat():
    from worldbridge.java.numeric import JavaWriteOptions, build_java_level

    info = WorldInfo()
    info.level["WorldGenSettings"] = nbt.CompoundTag({"seed": nbt.LongTag(5), "dimensions": nbt.CompoundTag({
        "minecraft:overworld": nbt.CompoundTag({"generator": nbt.CompoundTag({
            "type": nbt.StringTag("minecraft:noise"), "settings": nbt.StringTag("minecraft:amplified")})})})})
    out = build_java_level(info, JavaWriteOptions(kind="anvil"))
    assert nbt.get(out, "generatorName") == "amplified" and nbt.get(out, "RandomSeed") == 5


def _slope(cx_range=range(-1, 3), z_range=range(-1, 2)):
    """Ground rising 1 block per column eastwards, from y 150 at x = 0."""
    chunks = {}
    for cx in cx_range:
        for cz in z_range:
            c = NumericChunk(cx, cz, 256)
            c.blocks[0] = 7
            for x in range(16):
                h = 150 + cx * 16 + x
                c.blocks[1:h, :, x] = 1
                c.blocks[h, :, x] = 2
            chunks[(cx, cz)] = c
    return chunks


def test_a_tree_on_a_slope_keeps_its_leaves_on_its_trunk():
    chunks = _slope()
    c = chunks[(0, 0)]
    tx, tz, base = 8, 8, 150 + 8 + 1
    c.blocks[base:base + 5, tz, tx] = 17                                       # trunk
    for dx in range(-2, 3):
        for dz in range(-2, 3):
            if dx or dz:
                c.blocks[base + 3:base + 5, tz + dz, tx + dx] = 18             # a crown of leaves
    fit = _fit(chunks)
    c = fit.apply(c)
    b = np.asarray(c.blocks)
    trunk_top = int(np.nonzero(b[:, tz, tx] == 17)[0].max())
    for dx in (-2, 2):
        leaves = np.nonzero(b[:, tz, tx + dx] == 18)[0]
        assert list(leaves) == [trunk_top - 1, trunk_top]                      # same height as at the trunk


def test_a_house_on_a_slope_comes_down_rigid():
    chunks = _slope()
    c = chunks[(0, 0)]
    for x in range(4, 10):                                                     # cobble foundation + plank walls
        h = 150 + x
        c.blocks[h + 1:170, 4:9, x] = 4
        c.blocks[170:175, 4:9, x] = 5
    before = np.asarray(c.blocks[170:175, 4:9, 4:10]).copy()
    fit = _fit(chunks)
    s = fit.shifts(0, 0)
    assert len(set(s[4:9, 4:10].ravel().tolist())) == 1                        # one shift for the whole house
    sh = int(s[4, 4])
    c = fit.apply(c)
    assert (np.asarray(c.blocks[170 - sh:175 - sh, 4:9, 4:10]) == before).all()


def _universal_chunk(tops):
    """An Amulet universal chunk of stone from y -64 up to tops[x] (plus grass on top)."""
    from amulet.api.block import Block
    from amulet.api.chunk import Chunk

    ch = Chunk(0, 0)
    air = ch.block_palette.get_add_block(Block("universal_minecraft", "air"))
    stone = ch.block_palette.get_add_block(Block("universal_minecraft", "stone"))
    grass = ch.block_palette.get_add_block(Block("universal_minecraft", "grass_block"))
    col = np.full((16, 384, 16), air, np.uint32)
    for x in range(16):
        col[x, :tops[x] + 64, :] = stone
        col[x, tops[x] + 64, :] = grass
    ch.blocks = {cy: col[:, (cy + 4) * 16:(cy + 5) * 16, :].copy() for cy in range(-4, 20)}
    return ch, grass, stone


def test_a_caves_and_cliffs_world_keeps_its_underground_and_its_mountains():
    from worldbridge.depthfit import DepthFit

    tops = [40 + 17 * x for x in range(16)]                  # from y 40 (under the knee) up to y 295
    ch, grass, stone = _universal_chunk(tops)
    fit = DepthFit(bottom=-64, compress=True)
    fit.observe(ch)
    fit.apply(ch)
    assert set(ch.blocks.sub_chunks) <= set(range(16))
    col = np.concatenate([ch.blocks.get_sub_chunk(cy) for cy in range(16)], axis=1)   # x, y, z
    new_tops = [int(np.nonzero(col[x, :, 0] == grass)[0].max()) for x in range(16)]
    assert new_tops[0] == tops[0] + 64                       # below the knee: only moved up
    assert max(new_tops) < 256 and all(b >= a for a, b in zip(new_tops, new_tops[1:]))   # still a slope
    assert (col[:, 0, :] == stone).all()                     # the deepest rock is kept, at y 0


def test_the_underground_can_be_cut_at_a_chosen_depth():
    from worldbridge.depthfit import DepthFit

    ch, grass, stone = _universal_chunk([100] * 16)
    fit = DepthFit(bottom=-20, compress=False)
    fit.apply(ch)
    col = np.concatenate([ch.blocks.get_sub_chunk(cy) for cy in range(16)], axis=1)
    assert int(np.nonzero(col[0, :, 0] == grass)[0].max()) == 120
