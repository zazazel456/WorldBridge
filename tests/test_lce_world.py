import os

import numpy as np
import pytest

from worldbridge import nbt
from worldbridge.lce.world import LCEWorld, LCEWriteOptions, LCEWriter
from worldbridge.model import Progress

from .helpers import SyntheticWorld, make_chunk


@pytest.mark.parametrize("platform", ["win64", "ps3", "wiiu", "vita", "ps4", "xboxone", "switch", "xbox360"])
def test_lce_roundtrip(tmp_path, platform):
    src = SyntheticWorld(radius=2 if platform != "xbox360" else 1, dims=(0, -1))
    out = tmp_path / platform
    w = LCEWriter(str(out), LCEWriteOptions(platform=platform), Progress())
    for d in src.dimensions():
        for cx, cz in src.chunk_coords(d):
            w.add_chunk(d, src.read_chunk(d, cx, cz))
    w.finish(src.info)
    # an Xbox One split save is told from a PS4 one only by the files of the console's storage
    world = LCEWorld(str(out), "xboxone" if platform == "xboxone" else None)
    # Switch and Windows64 containers are byte-identical formats
    assert world.container.platform.key == {"switch": "win64"}.get(platform, platform)
    assert world.info.name == "Test World"
    assert set(world.dimensions()) == {0, -1}
    coords = world.chunk_coords(0)
    assert len(coords) == len(src.chunk_coords(0))
    for cx, cz in coords:
        c = world.read_chunk(0, cx, cz)
        ref = make_chunk(cx, cz, 0)
        assert np.array_equal(c.blocks, ref.blocks)
        assert np.array_equal(c.data, ref.data)
        assert np.array_equal(c.biomes, ref.biomes)
        assert nbt.get(c.tile_entities[0], "id") == "Chest"
        assert nbt.get(c.entities[0], "id") == "Pig"
    assert len(world.info.players) == 1


@pytest.mark.parametrize("platform, asked, written", [("xbox360", 320, 54), ("vita", 0, 54), ("ps3", 64, 54),
                                                      ("wiiu", 0, 320), ("ps4", 192, 192), ("win64", 0, 320)])
def test_the_world_size_fits_the_console(tmp_path, platform, asked, written):
    from worldbridge.convert import TargetSpec, _make_writer

    src = SyntheticWorld(radius=1)
    t = TargetSpec(family="lce", lce_platform=platform, lce_world_size=asked)
    assert _make_writer(t, str(tmp_path / platform), Progress(), src).opt.world_size == written


def test_a_nickname_is_not_an_xuid(tmp_path):
    """Windows64 loads the main player from players/<XUID>.dat: a nickname there is never read."""
    from worldbridge.lce.world import save_players

    for pid, warned in (("alexanderdip2012", True), ("15885783760619110653", False)):
        prog = Progress()
        src = SyntheticWorld(radius=1)
        w = LCEWriter(str(tmp_path / pid), LCEWriteOptions(platform="win64", world_size=54, host_player_id=pid), prog)
        for cx, cz in src.chunk_coords(0):
            w.add_chunk(0, src.read_chunk(0, cx, cz))
        path = w.finish(src.info)
        assert any("XUID" in m for m in prog.warnings) == warned
        assert list(save_players(path).values()) == [pid]
