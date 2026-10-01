"""Chunks removed and biomes changed on a world itself, without converting it."""
import os

import numpy as np
import pytest

from worldbridge import amulet_bridge as ab
from worldbridge import biomes as bio
from worldbridge.chunkedit import edit_world, keep_only, world_game
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.model import Progress

from .helpers import SyntheticWorld


def _java(tmp_path, name="java"):
    src = SyntheticWorld(radius=2)
    out = str(tmp_path / name)
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    return out, src


def _backups(tmp_path):
    return [p for p in os.listdir(tmp_path) if ".wb-backup-" in p]


def test_old_java_world_edited_in_place(tmp_path):
    world, src = _java(tmp_path)
    assert world_game(world) == ("java", (1, 12))
    res = edit_world(world, remove={0: {(0, 0), (1, 1)}}, paint={0: {(-1, -1): 6, (0, 0): 2}})
    assert res.removed == 2 and res.painted == 1                     # a removed chunk is not painted
    w = JavaNumericWorld(world)
    assert set(w.chunk_coords(0)) == set(src.chunk_coords(0)) - {(0, 0), (1, 1)}
    assert (np.asarray(w.read_chunk(0, -1, -1).biomes) == 6).all()
    assert not (np.asarray(w.read_chunk(0, -2, -2).biomes) == 6).all()
    assert (w.read_chunk(0, -1, -1).blocks == src.read_chunk(0, -1, -1).blocks).all()   # nothing else changes
    assert len(_backups(tmp_path)) == 1


def test_keep_only_the_selection(tmp_path):
    world, _src = _java(tmp_path)
    keep_only(world, {0: {(0, 0), (-1, 0)}}, [0])
    assert set(JavaNumericWorld(world).chunk_coords(0)) == {(0, 0), (-1, 0)}


def test_modern_java_world_gets_a_modern_biome(tmp_path):
    hub, _src = _java(tmp_path, "hub")
    world = str(tmp_path / "modern")
    convert(hub, world, TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4), ring=False, blend=False))
    fam, ver = world_game(world)
    assert fam == "java" and ver >= (1, 20)
    res = edit_world(world, paint={0: {(0, 0): bio.parse("cherry_grove")}})
    assert res.painted == 1
    level = ab.load_level(world)
    try:
        ch = level.get_chunk(0, 0, "minecraft:overworld")
        ids = np.unique(np.concatenate([a.ravel() for a in ch.biomes.to_raw()[2].values()]))
        assert {str(ch.biome_palette[int(i)]) for i in ids} == {"universal_minecraft:cherry_grove"}
    finally:
        level.close()


@pytest.mark.parametrize("platform", ["win64", "ps3", "xbox360", "ps4"])
def test_lce_world_edited_in_place(tmp_path, platform):
    src = SyntheticWorld(radius=2)
    world = tmp_path / platform
    wr = LCEWriter(str(world), LCEWriteOptions(platform=platform, world_size=54), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    path = wr.finish(src.info)
    hint = "ps4" if platform == "ps4" else None
    before = LCEWorld(path, hint)
    coords = before.chunk_coords(0)
    gone, painted = coords[0], coords[-1]
    res = edit_world(path, remove={0: {gone}}, paint={0: {painted: bio.parse("Swampland")}})
    assert res.removed == 1 and res.painted == 1 and res.backup
    after = LCEWorld(path, hint)
    assert set(after.chunk_coords(0)) == set(coords) - {gone}
    c = after.read_chunk(0, *painted)
    assert (np.asarray(c.biomes) == 6).all()
    assert (c.blocks == before.read_chunk(0, *painted).blocks).all()
    assert (after.read_chunk(0, *coords[1]).blocks == before.read_chunk(0, *coords[1]).blocks).all()


def test_lce_refuses_a_biome_it_does_not_have(tmp_path):
    src = SyntheticWorld(radius=1)
    wr = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64", world_size=54), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    path = wr.finish(src.info)
    with pytest.raises(Exception):
        edit_world(path, paint={0: {(0, 0): bio.parse("cherry_grove")}})


def test_bedrock_world_edited_in_place(tmp_path):
    hub, src = _java(tmp_path, "hub")
    world = str(tmp_path / "bedrock")
    convert(hub, world, TargetSpec(family="bedrock", version=(1, 20, 0), ring=False, blend=False))
    res = edit_world(world, remove={0: {(0, 0)}}, paint={0: {(1, 1): 35}})
    assert res.removed == 1 and res.painted == 1
    level = ab.load_level(world)
    try:
        assert (0, 0) not in set(level.all_chunk_coords("minecraft:overworld"))
    finally:
        level.close()
