"""Selected chunks moved to the centre of the world (or to chosen coordinates) on every route."""
from worldbridge import amulet_bridge as ab
from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.lce.world import LCEWorld
from worldbridge.model import Progress
from worldbridge.selection import Selection

from .helpers import SyntheticWorld, make_chunk

FAR = (100, 1000)                       # chunk where the far away build starts


class FarWorld(SyntheticWorld):
    def chunk_coords(self, dim):
        return [(FAR[0] + x, FAR[1] + z) for x in range(4) for z in range(4)]

    def read_chunk(self, dim, cx, cz):
        return make_chunk(cx, cz, seed=dim)


def _far_java(tmp_path):
    src = FarWorld(radius=2)
    src.info.level["SpawnX"], src.info.level["SpawnZ"] = nbt.IntTag(FAR[0] * 16 + 20), nbt.IntTag(FAR[1] * 16 + 20)
    src.info.players["host"]["Pos"] = nbt.ListTag([nbt.DoubleTag(FAR[0] * 16 + 20.5), nbt.DoubleTag(65.0),
                                                   nbt.DoubleTag(FAR[1] * 16 + 20.5)], 6)
    out = str(tmp_path / "far")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    return out, set(src.chunk_coords(0))


def test_far_chunks_land_in_the_middle_of_an_lce_world(tmp_path):
    src, chunks = _far_java(tmp_path)
    t = TargetSpec(family="lce", lce_platform="xbox360", lce_world_size=54, ring=False,
                   selection=Selection(chunks={0: chunks}, move_to=(0, 0)))
    convert(src, str(tmp_path / "lce"), t)
    w = LCEWorld(str(tmp_path / "lce"))
    got = w.chunk_coords(0)
    assert len(got) == 16                                     # nothing left outside the 54 x 54 world
    c = w.read_chunk(0, *got[0])
    tile = c.tile_entities[0]
    assert int(nbt.get(tile, "x")) >> 4 == c.cx and int(nbt.get(tile, "z")) >> 4 == c.cz
    pos = nbt.get_tag(c.entities[0], "Pos")
    assert int(float(pos[0].py_data)) >> 4 == c.cx


def test_far_chunks_moved_to_chosen_coordinates(tmp_path):
    src, chunks = _far_java(tmp_path)
    t = TargetSpec(family="java", java_mode="numeric", ring=False,
                   selection=Selection(chunks={0: chunks}, move_to=(1000, -2000)))
    convert(src, str(tmp_path / "moved"), t)
    w = JavaNumericWorld(str(tmp_path / "moved"))
    got = set(w.chunk_coords(0))
    # the centre of the 4 x 4 selection (chunk FAR + 1) lands on chunk (1000 >> 4, -2000 >> 4)
    dx, dz = (1000 >> 4) - (FAR[0] + 1), (-2000 >> 4) - (FAR[1] + 1)
    assert got == {(cx + dx, cz + dz) for cx, cz in chunks}
    c = w.read_chunk(0, FAR[0] + dx, FAR[1] + dz)
    assert int(nbt.get(c.tile_entities[0], "x")) == (FAR[0] + dx) * 16 + 6
    # the spawn and the player were in the moved chunks: they move with them
    lv = w.info.level
    assert (int(nbt.get(lv, "SpawnX")), int(nbt.get(lv, "SpawnZ"))) == (FAR[0] * 16 + 20 + dx * 16, FAR[1] * 16 + 20 + dz * 16)
    p = next(iter(w.info.players.values()))
    assert float(nbt.get_tag(p, "Pos")[0].py_data) == FAR[0] * 16 + 20.5 + dx * 16


def test_the_amulet_route_moves_the_chunks_too(tmp_path):
    src, chunks = _far_java(tmp_path)
    modern = str(tmp_path / "modern")
    convert(src, modern, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4), ring=False))
    t = TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4), ring=False,
                   selection=Selection(chunks={0: chunks}, move_to=(0, 0)))
    convert(modern, str(tmp_path / "back"), t)
    level = ab.load_level(str(tmp_path / "back"))
    try:
        got = set(level.all_chunk_coords("minecraft:overworld"))
    finally:
        level.close()
    dx, dz = -(FAR[0] + 1), -(FAR[1] + 1)
    assert got == {(cx + dx, cz + dz) for cx, cz in chunks}


def test_copper_chests_keep_their_contents_and_every_chest_is_drawn():
    """Java 1.21.9+ copper chests become wooden chests with their block entity; a chest left without
    one gets an empty one (the old games draw chests through it: without it they are invisible)."""
    import numpy as np

    from worldbridge import tiles
    from worldbridge.model import NumericChunk

    for n in ("copper_chest", "waxed_oxidized_copper_chest", "weathered_copper_chest"):
        assert tiles.JAVA_TO_KIND[n] == "chest"
    c = NumericChunk(2, -1, 256)
    c.blocks[64, 3, 5] = 54
    c.blocks[64, 3, 6] = 146
    c.blocks[70, 0, 0] = 130
    c.tile_entities.append(nbt.CompoundTag({"id": nbt.StringTag("Chest"), "x": nbt.IntTag(37),
                                            "y": nbt.IntTag(64), "z": nbt.IntTag(-13)}))
    assert tiles.ensure_drawn_tiles(c) == 2
    ids = sorted((str(nbt.get(t, "id")), int(nbt.get(t, "x")), int(nbt.get(t, "z"))) for t in c.tile_entities)
    assert ids == [("Chest", 37, -13), ("Chest", 38, -13), ("EnderChest", 32, -16)]
    assert tiles.ensure_drawn_tiles(c) == 0 and not np.isin(c.blocks, [54]).sum() == 0
