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


# ------------------------------------------------------------------ the End of the LCE games


class EndWorld(SyntheticWorld):
    """A world whose End has chunks where the test says."""

    def __init__(self, end, radius=1):
        super().__init__(radius=radius, dims=(0, 1))
        self.end = list(end)

    def chunk_coords(self, dim):
        return list(self.end) if dim == 1 else super().chunk_coords(dim)


# the End of the TU46+ saves has two blocks of 12 x 12 chunks: the island and the one at z 19..30
_END_FAR = [(0, 0), (-9, 8), (3, 27), (-6, 30), (5, 19)]
_END_OUT = [(-20, 5), (40, 0), (0, 32), (-33, 0)]      # the first is outside 18 x 18, the rest outside 64 x 64


def _end_chunks(path):
    return set(LCEWorld(path).chunk_coords(1))


@pytest.mark.parametrize("profile, size", [("tu31", 18), ("tu46", 64), ("tu54", 64)])
def test_the_end_is_the_size_of_the_profile(profile, size):
    from worldbridge.lce.world import map_area
    from worldbridge.model import THE_END

    w = LCEWriter("unused", LCEWriteOptions(platform="ps4", profile=profile, world_size=54, offset_x=100, offset_z=-7),
                  Progress())
    lo, hi = w.bounds(THE_END)
    assert (lo, hi) == (-(size // 2), size - size // 2)
    # the area the selection reads and the one the writer keeps are the same (and do not move with the offset)
    assert w.area(THE_END) == map_area(THE_END, 54, 100, -7, size) == (lo, hi, lo, hi)
    assert map_area(THE_END, 54, 100, -7) == (-9, 9, -9, 9)                  # 18 x 18 unless told otherwise
    assert w.target_coords(THE_END, 3, 4) == (3, 4)


@pytest.mark.parametrize("profile, kept", [("tu31", [(0, 0), (-9, 8)]), ("tu54", _END_FAR + [(-20, 5)])])
def test_another_source_keeps_the_end_the_game_has(tmp_path, profile, kept):
    from worldbridge import detect as det
    from worldbridge.convert import TargetSpec, convert
    from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions

    src = EndWorld(_END_FAR + _END_OUT)
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    for d in src.dimensions():
        for cx, cz in src.chunk_coords(d):
            w.add_chunk(d, src.read_chunk(d, cx, cz))
    w.finish(src.info)
    out = str(tmp_path / "lce")
    convert(hub, out, TargetSpec(family="lce", lce_platform="ps4", lce_profile=profile, lce_world_size=54))
    assert _end_chunks(det.detect(out).path) == set(kept)


def test_lce_to_lce_keeps_every_end_chunk(tmp_path):
    """An LCE save is what the game wrote: its End has chunks outside the 18 x 18 of the older games."""
    from worldbridge import detect as det
    from worldbridge.convert import TargetSpec, convert

    src = EndWorld(_END_FAR)
    first = str(tmp_path / "first")
    w = LCEWriter(first, LCEWriteOptions(platform="ps4", profile="tu54", world_size=54), Progress())
    for d in src.dimensions():
        for cx, cz in src.chunk_coords(d):
            w.add_chunk(d, src.read_chunk(d, cx, cz))
    w.finish(src.info)
    assert _end_chunks(first) == set(_END_FAR)
    for platform, profile in (("ps4", "tu54"), ("ps4", "tu46"), ("ps4", "tu31"), ("win64", "tu31")):
        out = str(tmp_path / f"{platform}_{profile}")
        convert(det.detect(first).path, out, TargetSpec(family="lce", lce_platform=platform, lce_profile=profile,
                                                        lce_world_size=54))
        assert _end_chunks(det.detect(out).path) == set(_END_FAR), (platform, profile)


def test_a_mob_the_profile_does_not_have_is_reported(tmp_path):
    """TU54 has no fish nor drowned (they came with the Aquatic update): they are removed, and said so."""
    from worldbridge.model import OVERWORLD

    prog = Progress()
    src = SyntheticWorld(radius=1)
    w = LCEWriter(str(tmp_path / "out"), LCEWriteOptions(platform="ps4", profile="tu54", world_size=54), prog)
    for cx, cz in src.chunk_coords(0):
        c = src.read_chunk(0, cx, cz)
        c.entities.append(nbt.CompoundTag({"id": nbt.StringTag("minecraft:salmon")}))
        c.entities.append(nbt.CompoundTag({"id": nbt.StringTag("minecraft:drowned")}))
        w.add_chunk(OVERWORLD, c)
    w.finish(src.info)
    assert any("salmon" in m and "drowned" in m for m in prog.warnings), prog.warnings
    world = LCEWorld(str(tmp_path / "out"))
    for cx, cz in world.chunk_coords(0):
        assert [nbt.get(e, "id") for e in world.read_chunk(0, cx, cz).entities] == ["Pig"]


def test_the_ender_chests_of_a_tu69_save_are_kept():
    """Those saves write the block entity id as "minecraft:ender_Chest" (a capital C)."""
    from worldbridge import ids
    from worldbridge.lce.world import sanitize_tiles

    assert ids.tile_to_old("minecraft:ender_Chest") == "EnderChest"
    assert ids.tile_to_old("minecraft:ender_chest") == "EnderChest"
    blocks = np.zeros((256, 16, 16), np.uint16)
    blocks[64, 3, 4] = 130
    tile = nbt.CompoundTag({"id": nbt.StringTag("minecraft:ender_Chest"), "x": nbt.IntTag(4), "y": nbt.IntTag(64),
                            "z": nbt.IntTag(3)})
    assert [nbt.get(t, "id") for t in sanitize_tiles([tile], blocks, 0, 0)] == ["EnderChest"]
