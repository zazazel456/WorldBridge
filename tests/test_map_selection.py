"""Map renderer, chunk selection, spawn override and player linking."""
import numpy as np

from worldbridge import mapview as mv
from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.lce.world import LCEWriteOptions, LCEWriter
from worldbridge.model import NETHER, Progress
from worldbridge.selection import PlayerLink, Selection, load_csv, offline_uuid, save_csv

from .helpers import SyntheticWorld


def test_mca_selector_csv_roundtrip(tmp_path):
    chunks = {(x, z) for x in range(32) for z in range(32)} | {(40, -3), (-1, -1)}
    f = tmp_path / "sel.csv"
    save_csv(str(f), chunks)
    lines = f.read_text().split()
    assert "0;0" in lines and "1;-1;40;-3" in lines and "-1;-1;-1;-1" in lines
    assert load_csv(str(f)) == chunks


def test_offline_uuid_matches_minecraft():
    assert offline_uuid("Notch") == "b50ad385-829d-3141-a216-7e7d7539ba7f"


def test_tile_top_block_and_water_depth():
    idx = np.zeros((16, 16, 16), np.int64)          # [y, z, x]
    idx[:5] = 1                                        # stone y 0..4
    idx[5:9] = 2                                       # water y 5..8
    idx[:12, 3, 3] = 3                                 # oak_log pillar up to y 11
    tile = mv.tile_from_sections([(0, idx, ["minecraft:air", "minecraft:stone", "minecraft:water", "minecraft:oak_log"])])
    assert tile.height[0, 0] == 8 and tile.name_at(0, 0) == "minecraft:water" and tile.depth[0, 0] == 4
    assert tile.height[3, 3] == 11 and tile.name_at(3, 3) == "minecraft:oak_log" and tile.depth[3, 3] == 0
    img = mv.shade(tile)
    assert img.shape == (16, 16, 3) and img[0, 0, 2] > img[0, 0, 0]  # water is blue


def test_nether_roof_is_skipped():
    c = type("C", (), {})()
    c.blocks = np.zeros((128, 16, 16), np.int32)
    c.data = np.zeros_like(c.blocks)
    c.blocks[:40] = 87      # netherrack floor up to y 39
    c.blocks[120:128] = 7   # bedrock roof
    top = mv.tile_from_numeric(c)
    below = mv.tile_from_numeric(c, roof=127)
    assert top.height[0, 0] == 127
    assert below.height[0, 0] == 39 and below.name_at(0, 0) == "netherrack"


def test_java_packed_block_states_both_layouts():
    rng = np.random.default_rng(1)
    vals = rng.integers(0, 20, 4096)          # 20 palette entries -> 5 bits
    bits = 5
    # 1.16+ layout: values do not span longs (12 per long)
    per = 64 // bits
    longs = []
    for i in range(0, 4096, per):
        v = 0
        for j, x in enumerate(vals[i:i + per]):
            v |= int(x) << (j * bits)
        longs.append(v - (1 << 64) if v >= 1 << 63 else v)
    assert np.array_equal(mv._unpack(np.array(longs, np.int64), bits, 4096, False), vals)
    # 1.13-1.15 layout: one continuous bit stream
    total = 0
    for i, x in enumerate(vals):
        total |= int(x) << (i * bits)
    words = [(total >> (64 * k)) & ((1 << 64) - 1) for k in range(4096 * bits // 64)]
    words = [w - (1 << 64) if w >= 1 << 63 else w for w in words]
    assert np.array_equal(mv._unpack(np.array(words, np.int64), bits, 4096, True), vals)


def _lce_world(path):
    src = SyntheticWorld(radius=3, dims=(0,))
    src.info.players["second"] = nbt.copy(src.info.players["host"])
    w = LCEWriter(str(path), LCEWriteOptions(platform="win64"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    return path


def test_map_and_selection_through_conversion(tmp_path):
    src = _lce_world(tmp_path / "lce")
    m = mv.open_map(str(src))
    try:
        assert len(m.chunk_coords(0)) == 36
        t = m.tile(0, 0, 0)
        assert t.height[5, 5] == 64 and t.name_at(5, 5) == "red_wool"
        keys = [p.key for p in m.players]
    finally:
        m.close()
    sel = Selection(chunks={0: {(0, 0), (1, 0), (-1, -1)}}, spawn=(20, 70, 5),
                    players=[PlayerLink(key=keys[1], host=True, nickname="Steve", online=False),
                             PlayerLink(key=keys[0], include=False)])
    out = tmp_path / "java"
    convert(str(src), str(out), TargetSpec(family="java", selection=sel))
    m = mv.open_map(str(out))
    try:
        assert sorted(m.chunk_coords(0)) == [(-1, -1), (0, 0), (1, 0)]
        assert m.spawn == (20, 70, 5)
    finally:
        m.close()
    pd = out / "playerdata"
    assert [f.name for f in pd.iterdir()] == [offline_uuid("Steve") + ".dat"]
    lvl = nbt.load((out / "level.dat").read_bytes()).tag["Data"]
    assert "UUIDMost" in lvl["Player"]  # singleplayer data linked to the same UUID


def test_selection_excludes_unselected_dimensions():
    sel = Selection(chunks={0: {(1, 1)}})
    assert sel.filter(0, [(0, 0), (1, 1)]) == [(1, 1)]
    assert sel.filter(NETHER, [(0, 0)]) == []
    assert Selection().filter(NETHER, [(0, 0)]) == [(0, 0)]


def test_map_of_java_26_chunks_reads_every_palette_form():
    # Java 26.x palettes: plain strings, {"id", "properties"}, and strings wrapped as {"": name} in
    # a list that mixes both kinds; read as air, the ground vanished and the map showed the caves
    import numpy as np

    from worldbridge import nbt
    from worldbridge.mapview import java_chunk_tile

    def section(y, palette, fill):
        idx = np.full(4096, fill, np.int64)
        bits = 4
        per = 64 // bits
        longs = np.zeros(4096 // per, np.uint64)
        for i, v in enumerate(idx):
            longs[i // per] |= np.uint64(v) << np.uint64((i % per) * bits)
        bs = nbt.CompoundTag({"palette": palette, "data": nbt.LongArrayTag(longs.view(np.int64))})
        return nbt.CompoundTag({"Y": nbt.ByteTag(y), "block_states": bs})

    mixed = nbt.ListTag([nbt.CompoundTag({"": nbt.StringTag("minecraft:air")}),
                         nbt.CompoundTag({"": nbt.StringTag("minecraft:grass_block")}),
                         nbt.CompoundTag({"id": nbt.StringTag("minecraft:oak_log"),
                                          "properties": nbt.CompoundTag({"axis": nbt.StringTag("y")})})], 10)
    root = nbt.CompoundTag({"DataVersion": nbt.IntTag(5023), "sections": nbt.ListTag([
        section(0, nbt.ListTag([nbt.StringTag("minecraft:stone"), nbt.StringTag("minecraft:air")], 8), 0),
        section(4, mixed, 1)], 10)})
    tile = java_chunk_tile(root)
    assert (tile.height == 79).all() and tile.name_at(3, 3) == "minecraft:grass_block"
    assert nbt.state_name(mixed[2]) == "minecraft:oak_log" and str(nbt.state_props(mixed[2])["axis"].py_data) == "y"


def test_a_biome_painted_on_selected_chunks(tmp_path):
    from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions

    src = SyntheticWorld(radius=1)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    out = str(tmp_path / "out")
    t = TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12", ring=False)
    t.selection = Selection(biomes={0: {(0, 0): 35}})                                  # savanna
    convert(hub, out, t)
    world = JavaNumericWorld(out)
    assert (np.asarray(world.read_chunk(0, 0, 0).biomes) == 35).all()
    assert not (np.asarray(world.read_chunk(0, -1, 0).biomes) == 35).all()


def test_a_biome_only_newer_games_have(tmp_path):
    """A 1.18+ biome (cherry grove) painted through the numeric route: after Amulet's translation."""
    from worldbridge import amulet_bridge as ab
    from worldbridge import biomes
    from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions

    src = SyntheticWorld(radius=1)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    out = str(tmp_path / "out")
    t = TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4), ring=False, blend=False)
    t.selection = Selection(biomes={0: {(0, 0): biomes.parse("cherry_grove")}})
    convert(hub, out, t)
    level = ab.load_level(out)
    try:
        chunk = level.get_chunk(0, 0, "minecraft:overworld")
        names = {str(chunk.biome_palette[int(i)]) for i in np.unique(np.concatenate(
            [a.ravel() for a in chunk.biomes.to_raw()[2].values()]))}
    finally:
        level.close()
    assert names == {"universal_minecraft:cherry_grove"}


def test_biomes_offered_follow_the_game():
    from worldbridge import biomes

    assert biomes.available("lce") == biomes.LCE and 131 not in biomes.LCE
    assert biomes.game_name(6, "lce") == "Swampland" and biomes.game_name(6, "java", (1, 16, 5)) == "swamp"
    assert biomes.game_name(3, "java", (1, 20)) == "windswept_hills"
    assert 1008 in biomes.available("java", (1, 20, 4)) and 1008 not in biomes.available("java", (1, 19, 2))
    assert 17 not in biomes.available("java", (1, 18))              # desert hills: gone in 1.18
    assert biomes.available("java", (1, 6, 4)) == biomes.JAVA_12 and biomes.available("pe_old") == ()
    assert biomes.parse("Mega Spruce Taiga") == 160 and biomes.parse("windswept_hills") == 3
