"""The sea level adjustment (Java 62 -> Alpha / Beta 63) moves the overworld only: the Nether and the End have no sea
level, and a raised Nether would push its bedrock roof (y 127) out of the 128 high target."""
import numpy as np

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.model import NETHER, OVERWORLD, THE_END, NumericChunk, Progress, WorldInfo, y_shifts


def _hub(tmp_path, player_dim, y=70.0):
    hub = str(tmp_path / "hub")
    w = JavaNumericWriter(hub, JavaWriteOptions(kind="anvil"), Progress())
    ow = NumericChunk(0, 0, 256)
    ow.blocks[0] = 7
    ow.blocks[1:50] = 1
    w.add_chunk(OVERWORLD, ow)
    ne = NumericChunk(0, 0, 256)
    ne.blocks[0] = 7
    ne.blocks[1:127] = 87
    ne.blocks[127] = 7                                       # the bedrock roof
    w.add_chunk(NETHER, ne)
    info = WorldInfo()
    info.level = nbt.CompoundTag({"LevelName": nbt.StringTag("sea"), "SpawnX": nbt.IntTag(8), "SpawnY": nbt.IntTag(64),
                                  "SpawnZ": nbt.IntTag(8), "RandomSeed": nbt.LongTag(1)})
    info.players["host"] = nbt.CompoundTag({
        "Pos": nbt.ListTag([nbt.DoubleTag(8.5), nbt.DoubleTag(y), nbt.DoubleTag(8.5)], 6), "Dimension": nbt.IntTag(player_dim)})
    w.finish(info)
    return hub


def _convert(tmp_path, hub, name, **kw):
    msgs = []
    prog = Progress(on_log=msgs.append)
    out = str(tmp_path / name)
    spec = TargetSpec(family="java", java_mode="alpha", java_version_limit="b1.2", ring=False, **kw)
    convert(hub, out, spec, progress=prog)
    return JavaNumericWorld(out), msgs, prog.warnings


def _player_y(world):
    p = next(iter(world.info.players.values())) if world.info.players else world.info.level["Player"]
    return float(nbt.get_tag(p, "Pos")[1].py_data)


def test_y_shifts_gives_the_sea_to_the_overworld_only():
    assert y_shifts(0, 1) == {OVERWORLD: 1, NETHER: 0, THE_END: 0}
    assert y_shifts(-2, 1) == {OVERWORLD: -1, NETHER: -2, THE_END: -2}          # --y-offset moves everything
    assert TargetSpec(family="java", sea_offset=1, y_offset=0).dy(NETHER) == 0


def test_the_overworld_rises_by_one_and_the_nether_keeps_its_roof(tmp_path):
    world, msgs, warns = _convert(tmp_path, _hub(tmp_path, NETHER), "alpha")
    assert any("Sea level" in m for m in msgs)
    ow = np.asarray(world.read_chunk(OVERWORLD, 0, 0).blocks[:, 8, 8])
    assert int(np.nonzero(ow)[0].max()) == 50 and ow[50] == 1 and ow[0] == 7        # raised by one: rock 1..49 -> 2..50
    ne = np.asarray(world.read_chunk(NETHER, 0, 0).blocks[:, 8, 8])
    assert ne[127] == 7 and ne[0] == 7 and ne[126] == 87 and ne[1] == 87           # not moved: roof and floor stay
    assert not any("did not fit" in w for w in warns)
    assert abs(_player_y(world) - 70.0) < 1e-6                                     # a Nether player keeps y
    assert int(nbt.get(world.info.level, "SpawnY")) == 65                           # the spawn is in the overworld


def test_an_overworld_player_rises_with_its_world(tmp_path):
    world, _, _ = _convert(tmp_path, _hub(tmp_path, OVERWORLD, 65.0), "alpha_ow")
    assert abs(_player_y(world) - 66.0) < 1e-6


def test_the_user_y_offset_moves_every_dimension(tmp_path):
    world, msgs, _ = _convert(tmp_path, _hub(tmp_path, NETHER), "alpha_user", y_offset=-1)
    assert not any("Sea level" in m for m in msgs)                                 # chosen by the user: no automatic one
    ne = np.asarray(world.read_chunk(NETHER, 0, 0).blocks[:, 8, 8])
    assert ne[126] == 7 and ne[127] == 0
    assert abs(_player_y(world) - 69.0) < 1e-6


def test_lce_pipeline_shifts_the_overworld_only(tmp_path):
    """The writers without their own shift (LCE, PE): the pipeline moves the chunks, per dimension."""
    from worldbridge.convert import shift_info_y

    info = WorldInfo()
    info.level = nbt.CompoundTag({"SpawnY": nbt.IntTag(64)})
    for name, dim, y in (("a", OVERWORLD, 65.0), ("b", NETHER, 70.0), ("c", THE_END, 80.0)):
        info.players[name] = nbt.CompoundTag({
            "Pos": nbt.ListTag([nbt.DoubleTag(0.0), nbt.DoubleTag(y), nbt.DoubleTag(0.0)], 6), "Dimension": nbt.IntTag(dim)})
    shift_info_y(info, y_shifts(0, 1))
    ys = {k: float(p["Pos"][1].py_data) for k, p in info.players.items()}
    assert ys == {"a": 66.0, "b": 70.0, "c": 80.0}
    assert int(nbt.get(info.level, "SpawnY")) == 65
