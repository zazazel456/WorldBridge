"""The Caves & Cliffs depth (worldbridge.depthfit): block entities and entities end where their blocks
went, ``auto`` keeps the underground of flat worlds and cuts that of normal ones, the chunks the cut
empties are counted apart from the unreadable ones."""
import numpy as np
import pytest

from worldbridge import depthfit, nbt
from worldbridge import detect as det
from worldbridge.convert import TargetSpec, convert
from worldbridge.depthfit import DEEP_BOTTOM, DepthFit
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.model import OVERWORLD, NumericChunk, Progress, WorldInfo

from .helpers import make_chunk


def _tile(x, y, z, name="Chest"):
    return nbt.CompoundTag({"id": nbt.StringTag(name), "x": nbt.IntTag(x), "y": nbt.IntTag(y), "z": nbt.IntTag(z)})


def _mob(x, y, z, name="Pig", **extra):
    return nbt.CompoundTag({"id": nbt.StringTag(name), "Pos": nbt.pos_list(x, y, z), **extra})


def _hub_chunk(tiles=(), mobs=()):
    c = NumericChunk(0, 0, 256)
    c.tile_entities = list(tiles)
    c.entities = list(mobs)
    return c


def _pos_y(e):
    return float(e["Pos"][1].py_data)


# ------------------------------------------------------------------ block entities and entities follow their blocks


def test_keep_moves_block_entities_and_entities_up_with_the_world():
    fit = DepthFit(DEEP_BOTTOM, compress=True)                  # --depth keep: the world rises by 64 blocks
    fit.used = True
    frame = _mob(5.5, -59.5, 6.5, "ItemFrame", TileX=nbt.IntTag(5), TileY=nbt.IntTag(-60), TileZ=nbt.IntTag(6))
    c = _hub_chunk([_tile(3, -60, 4), _tile(3, -64, 5), _tile(3, 70, 6)],
                   [_mob(2.5, -60.0, 2.5), frame, _mob(2.5, 70.0, 2.5), _mob(2.5, 200.0, 2.5)])
    lost = fit.move_numeric(c)
    assert [int(nbt.get(t, "y")) for t in c.tile_entities] == [4, 0, 134]
    assert [_pos_y(e) for e in c.entities] == [4.0, 4.5, 134.0]
    assert int(nbt.get(c.entities[1], "TileY")) == 4                       # the frame hangs on the moved block
    assert lost == (0, 1)                                                  # y 200 + 64 does not fit the 256 blocks


def test_cut_drops_what_stood_under_y_0_and_counts_it():
    fit = DepthFit(0, compress=True)                            # the default cut: nothing moves, the rest is dropped
    fit.used = True
    c = _hub_chunk([_tile(3, -60, 4), _tile(3, 12, 5)], [_mob(2.5, -60.0, 2.5), _mob(2.5, 12.0, 2.5), _mob(2.5, 300.0, 2.5)])
    lost = fit.move_numeric(c)
    assert [int(nbt.get(t, "y")) for t in c.tile_entities] == [12]
    assert [_pos_y(e) for e in c.entities] == [12.0]
    assert lost == (1, 2)


def _marked_mountain(markers):
    """A universal chunk whose columns rise with x (to y 295 at x = 15); an obsidian block at every
    marker (x, y, z) of the source."""
    from amulet.api.block import Block
    from amulet.api.chunk import Chunk

    ch = Chunk(0, 0)
    air = ch.block_palette.get_add_block(Block("universal_minecraft", "air"))
    stone = ch.block_palette.get_add_block(Block("universal_minecraft", "stone"))
    grass = ch.block_palette.get_add_block(Block("universal_minecraft", "grass_block"))
    mark = ch.block_palette.get_add_block(Block("universal_minecraft", "obsidian"))
    col = np.full((16, 384, 16), air, np.uint32)
    for x in range(16):
        top = 40 + 17 * x
        col[x, :top + 64, :] = stone
        col[x, top + 64, :] = grass
    for x, y, z in markers:
        col[x, y + 64, z] = mark
    ch.blocks = {cy: col[:, (cy + 4) * 16:(cy + 5) * 16, :].copy() for cy in range(-4, 20)}
    return ch, mark


def test_block_y_is_where_apply_puts_the_block_in_a_compressed_mountain():
    ys = [150, 200, 230, 250, 270, 280, 285, 288, 290, 292, 293, 294]       # the ground of x = 15 is at y 295
    markers = [(15, y, z) for z, y in enumerate(ys)] + [(0, 20, 0), (0, -30, 1)]
    ch, mark = _marked_mountain(markers)
    fit = DepthFit(DEEP_BOTTOM, compress=True)
    fit.observe(ch)
    assert fit.fit.needed
    fit.apply(ch)
    col = np.concatenate([ch.blocks.get_sub_chunk(cy) for cy in range(16)], axis=1)       # x, y, z
    moved = cut = 0
    for x, y, z in markers:
        ny = fit.block_y(x, y, z)
        found = np.nonzero(col[x, :, z] == mark)[0]
        assert list(found) == ([] if ny is None else [ny]), (x, y, z)
        moved += ny is not None and ny != y + 64
        cut += ny is None
    assert moved and cut                                                   # some come down, some were in the removed rock
    assert fit.block_y(0, -30, 1) == 34 and fit.block_y(0, 20, 0) == 84     # under the knee: only moved up


def test_the_reader_moves_extras_with_their_blocks_and_counts_the_cut_ones():
    from worldbridge.extra import _wrap_reader

    class Extras:
        def chunk_extras(self, dim, cx, cz):
            return ([_mob(2.5, -60.0, 2.5), _mob(2.5, 10.0, 2.5)], [_tile(3, -60, 3), _tile(3, 20, 3), _tile(3, 400, 3)])

    class Hub:
        extras = Extras()

        def read_chunk(self, dim, cx, cz):
            return NumericChunk(cx, cz, 256)

    for bottom, tiles, mobs in ((DEEP_BOTTOM, [4, 84], [4.0, 74.0]), (0, [20], [10.0])):
        fit = DepthFit(bottom, compress=True)
        fit.used = True
        world = Hub()
        _wrap_reader(world, fit)
        c = world.read_chunk(OVERWORLD, 0, 0)
        assert [int(nbt.get(t, "y")) for t in c.tile_entities] == tiles
        assert [_pos_y(e) for e in c.entities] == mobs
        assert c.cut_extras == ((1, 0) if bottom == DEEP_BOTTOM else (2, 1))      # y 400 (and y -60 when cut)
        assert world.emptied_extras(OVERWORLD, 0, 0) == (3, 2)             # a chunk left without blocks: all lost


def test_the_source_readers_no_longer_cut_at_the_source_height():
    from worldbridge.java.modern import JavaModernExtras

    ex = JavaModernExtras.__new__(JavaModernExtras)
    chest = nbt.CompoundTag({"id": nbt.StringTag("minecraft:chest"), "x": nbt.IntTag(3), "y": nbt.IntTag(-60),
                             "z": nbt.IntTag(3), "Items": nbt.ListTag([], 10)})
    pig = nbt.CompoundTag({"id": nbt.StringTag("minecraft:pig"), "Pos": nbt.pos_list(5.5, -60.0, 5.5)})
    ex.data = {(0, 0, 0): ([chest], [pig])}
    ents, tiles = ex.chunk_extras(0, 0, 0)
    assert [int(nbt.get(t, "y")) for t in tiles] == [-60]
    assert [_pos_y(e) for e in ents] == [-60.0]


# ------------------------------------------------------------------ auto


def test_auto_keeps_flat_or_low_worlds_and_cuts_normal_ones():
    flat = np.full(4096, -61, np.int32)                                     # superflat 1.18+
    assert depthfit.decide(flat)[0] == DEEP_BOTTOM
    assert depthfit.decide(np.concatenate([flat, np.full(1000, 70)]))[0] == DEEP_BOTTOM      # mostly flat, a build
    bottom, why = depthfit.decide(np.full(4096, 63, np.int32))                # sea level
    assert bottom == 0 and "63" in why
    assert depthfit.decide(np.zeros(0, np.int32))[0] == 0                   # nothing to look at: the default cut


def test_the_surface_is_the_top_block_of_the_columns():
    ch, _mark = _marked_mountain([(0, 100, 0)])                           # a block floating over the ground of x = 0
    tops = DepthFit(DEEP_BOTTOM, compress=False).surface(ch).reshape(16, 16)       # [z, x]
    assert tops[0, 0] == 100 and tops[1, 0] == 40
    assert (tops[:, 5] == 40 + 17 * 5).all()


def test_plan_asks_the_world_only_for_auto(monkeypatch):
    calls = []
    monkeypatch.setattr(depthfit, "choose", lambda path: calls.append(path) or (DEEP_BOTTOM, "flat"))
    logs = []
    p = Progress(None, logs.append)
    fit = depthfit.plan(TargetSpec(family="lce"), True, "/w", p)             # the default is auto
    assert calls == ["/w"] and fit.bottom == DEEP_BOTTOM and logs == ["flat"]
    for depth, bottom in (("cut", 0), ("keep", DEEP_BOTTOM), (-20, -20)):
        fit = depthfit.plan(TargetSpec(family="lce", depth=depth), True, "/w", p)
        assert fit.bottom == bottom
    assert calls == ["/w"]                                                  # explicit choices never look at the world
    assert depthfit.plan(TargetSpec(family="lce"), False, "/w", p) is None  # not a Caves & Cliffs source


# ------------------------------------------------------------------ whole conversions


def _modern_world(path, top, chests=(), pig_y=None):
    """A Java 1.20.4 world of 2 x 2 chunks: stone up to y ``top``, grass on it; a chest holding 3 sticks at every
    y of ``chests`` (x = 3 + i, z = 3), a pig at ``pig_y``."""
    import amulet_nbt as an
    from amulet.api.block import Block
    from amulet.api.block_entity import BlockEntity
    from amulet.api.chunk import Chunk

    from worldbridge import amulet_bridge as ab
    from worldbridge.java.region import JavaRegion, RegionWriter

    ab.make_wrapper(path, "java", (1, 20, 4)).close()
    level = ab.load_level(path)
    try:
        for cx in range(2):
            for cz in range(2):
                ch = Chunk(cx, cz)
                air = ch.block_palette.get_add_block(Block("universal_minecraft", "air"))
                stone = ch.block_palette.get_add_block(Block("universal_minecraft", "stone"))
                grass = ch.block_palette.get_add_block(Block("universal_minecraft", "grass_block"))
                chest = ch.block_palette.get_add_block(Block("universal_minecraft", "chest", {
                    "facing": an.StringTag("north"), "type": an.StringTag("single"), "waterlogged": an.StringTag("false")}))
                col = np.full((16, 384, 16), air, np.uint32)
                col[:, :top + 64, :] = stone
                col[:, top + 64, :] = grass
                if (cx, cz) == (0, 0):
                    for i, y in enumerate(chests):
                        col[3 + i, y + 64, 3] = chest
                        items = an.ListTag([an.CompoundTag({"Slot": an.ByteTag(0), "id": an.StringTag("minecraft:stick"),
                                                            "Count": an.ByteTag(3)})])
                        ch.block_entities.insert(BlockEntity("minecraft", "chest", 3 + i, y, 3,
                                                             an.NamedTag(an.CompoundTag({"Items": items}))))
                ch.blocks = {cy: col[:, (cy + 4) * 16:(cy + 5) * 16, :].copy() for cy in range(-4, 20)}
                level.put_chunk(ch, "minecraft:overworld")
        level.save()
    finally:
        level.close()
    if pig_y is not None:                           # the entities of 1.17+ worlds have their own region files
        epath = f"{path}/entities/r.0.0.mca"
        rw = RegionWriter()
        pig = nbt.CompoundTag({"id": nbt.StringTag("minecraft:pig"), "Pos": nbt.pos_list(5.5, pig_y, 5.5),
                               "Motion": nbt.pos_list(0, 0, 0), "Rotation": nbt.ListTag([nbt.FloatTag(0)] * 2, 5),
                               "UUID": nbt.IntArrayTag(np.array([1, 2, 3, 4], np.int32)), "Health": nbt.FloatTag(10),
                               "Air": nbt.ShortTag(300), "OnGround": nbt.ByteTag(1)})
        old = JavaRegion(epath)
        for lx, lz in old.chunks():
            if (lx, lz) != (0, 0):
                rw.put(lx, lz, old.read(lx, lz))
        rw.put(0, 0, nbt.dump(nbt.CompoundTag({"DataVersion": nbt.IntTag(3700), "Position": nbt.IntArrayTag(
            np.array([0, 0], np.int32)), "Entities": nbt.compound_list([pig])}), ""))
        rw.write(epath)
    return path


def _to_numeric(src, out, **target):
    logs = []
    res = convert(src, out, TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12", ring=False,
                                       **target), Progress(None, logs.append))
    return res, logs


def _chunk00(out):
    w = JavaNumericWorld(out)
    return w, w.read_chunk(0, 0, 0)


@pytest.fixture(scope="module")
def flat_world(tmp_path_factory):
    return _modern_world(str(tmp_path_factory.mktemp("flat") / "w"), -61, chests=[-60], pig_y=-60.0)


@pytest.mark.parametrize("depth", ["auto", "keep"])
def test_flat_world_keeps_its_chunks_chests_and_mobs_where_its_blocks_went(tmp_path, flat_world, depth):
    kw = {} if depth == "auto" else {"depth": depth}
    res, logs = _to_numeric(flat_world, str(tmp_path / "out"), **kw)
    w, c = _chunk00(str(tmp_path / "out"))
    assert len(w.chunk_coords(0)) == 4
    assert int(c.blocks[3, 0, 0]) == 2 and int(c.blocks[4, 0, 0]) == 0       # the grass came up from y -61 to y 3
    chest = c.tile_entities[0]
    assert int(nbt.get(chest, "y")) == 4 and int(c.blocks[4, 3, 3]) == 54
    assert int(chest["Items"][0]["Count"].py_data) == 3                      # its contents are still there
    assert [_pos_y(e) for e in c.entities] == [4.0]
    assert not [m for m in res.warnings if "left empty" in m or "unreadable" in m or "Height limit" in m]
    assert any("Underground (automatic)" in m and "mostly below y 0" in m for m in logs) == (depth == "auto")


def test_cut_of_a_flat_world_reports_the_emptied_chunks_apart_from_the_unreadable_ones(tmp_path, flat_world):
    res, _logs = _to_numeric(flat_world, str(tmp_path / "out"), depth="cut")
    text = "\n".join(res.warnings)
    assert "4 chunks were left empty by the height limit" in text and "--depth keep" in text
    assert "unreadable" not in text
    assert "1 block entities" in text and "1 entities" in text               # the chest and the pig under y 0
    assert JavaNumericWorld(str(tmp_path / "out")).chunk_coords(0) == []


def test_auto_cuts_a_normal_world_and_counts_the_underground_chest_it_loses(tmp_path):
    src = _modern_world(str(tmp_path / "w"), 62, chests=[-10, 63], pig_y=63.0)
    res, logs = _to_numeric(src, str(tmp_path / "out"))
    w, c = _chunk00(str(tmp_path / "out"))
    assert any("above y 0 (median y 62)" in m for m in logs)
    assert len(w.chunk_coords(0)) == 4 and int(c.blocks[62, 0, 0]) == 2     # nothing moved
    assert [int(nbt.get(t, "y")) for t in c.tile_entities] == [63]
    assert [_pos_y(e) for e in c.entities] == [63.0]
    text = "\n".join(res.warnings)
    assert "Height limit: 1 block entities" in text and "0 entities" in text
    assert "left empty" not in text and "unreadable" not in text


# ------------------------------------------------------------------ a numeric world without an Overworld


@pytest.mark.parametrize("kind", ["anvil", "mcregion"])
def test_a_numeric_world_with_only_a_nether_or_an_end_is_recognised(tmp_path, kind):
    for dim, name in ((-1, "nether"), (1, "end")):
        out = str(tmp_path / name)
        w = JavaNumericWriter(out, JavaWriteOptions(kind=kind), Progress())
        w.add_chunk(dim, make_chunk(0, 0))
        w.finish(WorldInfo())
        d = det.detect(out)
        assert d is not None and d.kind == "java_numeric" and d.subkind == kind
        assert JavaNumericWorld(out).dimensions() == [dim]


# ------------------------------------------------------------------ Amulet to Amulet: the extras are copied from the source


def test_java_to_java_1_16_moves_the_chest_and_the_mob_with_the_blocks(tmp_path, flat_world):
    from worldbridge.java.region import JavaRegion

    out = str(tmp_path / "out")
    convert(flat_world, out, TargetSpec(family="java", java_mode="amulet", version=(1, 16, 5), ring=False))
    reg = JavaRegion(f"{out}/region/r.0.0.mca")
    lvl = nbt.load(reg.read(0, 0), compressed=False).tag["Level"]
    assert [int(nbt.get(t, "y")) for t in lvl["TileEntities"]] == [4]
    assert [_pos_y(e) for e in lvl["Entities"]] == [4.0]


def test_bedrock_to_old_bedrock_moves_the_chest_and_the_mob_with_the_blocks(tmp_path, flat_world):
    from worldbridge.bedrock.extra import ENTITY_TAG, BE_TAG, _db, _get, chunk_prefix, read_nbt_list

    new = str(tmp_path / "bedrock")
    convert(flat_world, new, TargetSpec(family="bedrock", version=(1, 20, 0), ring=False))
    out = str(tmp_path / "old")
    res = convert(new, out, TargetSpec(family="bedrock", version=(1, 16, 220), ring=False))
    assert not [m for m in res.warnings if "left empty" in m or "Height limit" in m]
    db = _db(out)
    try:
        prefix = chunk_prefix(0, 0, OVERWORLD)
        chests = read_nbt_list(_get(db, prefix + bytes([BE_TAG])) or b"")
        assert [int(nbt.get(t, "y")) for t in chests] == [4]
        ys = [float(a["Pos"][1].py_data) for key, v in db.iterate(b"actorprefix", b"actorprefix\xff")
              for a in read_nbt_list(bytes(v))]
        ys += [float(a["Pos"][1].py_data) for a in read_nbt_list(_get(db, prefix + bytes([ENTITY_TAG])) or b"")]
        assert ys and set(ys) == {4.0}                        # Amulet's own copy and the one copied from the source
    finally:
        db.close()
