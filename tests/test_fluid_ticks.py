"""Bedrock -> Java: flowing liquids get their ticks (worldbridge.java.fluids, #190).

Bedrock saves water / lava mid-flow together with its pending ticks; the translated Java chunks had the flowing cells
and no tick, so they stayed frozen as partial blocks.  The chunks of 26.3, 1.20, 1.16 and 1.12 are built by hand."""
import numpy as np

from worldbridge import nbt
from worldbridge.java import fluids
from worldbridge.java.modern import _encode
from worldbridge.java.region import JavaRegion, RegionWriter


def _state(name, **props):
    t = nbt.CompoundTag({"Name": nbt.StringTag(name)})
    if props:
        t["Properties"] = nbt.CompoundTag({k: nbt.StringTag(str(v)) for k, v in props.items()})
    return t


# a lava column: a source at (1, 10, 1), flowing cells under it (levels 1, 8, 8) and a floor of netherrack
CELLS = {(1, 10, 1): ("lava", 0), (1, 9, 1): ("lava", 8), (1, 8, 1): ("lava", 8), (2, 10, 1): ("lava", 3)}


def _states_section(sy, spanning):
    pal = [_state("minecraft:air")]
    idx = np.zeros(4096, np.int64)
    for (x, y, z), (kind, lev) in CELLS.items():
        st = _state("minecraft:" + kind, level=lev)
        if st not in pal:
            pal.append(st)
        idx[(y & 15) << 8 | z << 4 | x] = pal.index(st)
    pal.append(_state("minecraft:netherrack"))
    idx[(7 & 15) << 8 | 1 << 4 | 1] = len(pal) - 1
    return pal, _encode(idx, len(pal), spanning)


def _chunk(dv, flat=True, legacy=False):
    if legacy:                                           # 1.12: ids
        blocks = np.zeros(4096, np.uint8)
        data = np.zeros(4096, np.uint8)
        for (x, y, z), (kind, lev) in CELLS.items():
            i = (y & 15) << 8 | z << 4 | x
            blocks[i] = (10 if lev or kind == "lava" and (x, y, z) != (1, 10, 1) else 11)
            data[i] = lev
        blocks[7 << 8 | 1 << 4 | 1] = 87
        packed = (data[0::2] | (data[1::2] << 4)).astype(np.uint8)
        sec = nbt.CompoundTag({"Y": nbt.ByteTag(0), "Blocks": nbt.ByteArrayTag(blocks.astype(np.int8)),
                               "Data": nbt.ByteArrayTag(packed.astype(np.int8))})
        lvl = nbt.CompoundTag({"xPos": nbt.IntTag(0), "zPos": nbt.IntTag(0), "Sections": nbt.compound_list([sec])})
        return nbt.CompoundTag({"DataVersion": nbt.IntTag(dv), "Level": lvl})
    pal, data = _states_section(0, dv < 2527)
    if flat:
        sec = nbt.CompoundTag({"Y": nbt.ByteTag(0), "block_states": nbt.CompoundTag(
            {"palette": nbt.compound_list(pal), "data": data})})
        return nbt.CompoundTag({"DataVersion": nbt.IntTag(dv), "xPos": nbt.IntTag(0), "zPos": nbt.IntTag(0),
                                "sections": nbt.compound_list([sec])})
    sec = nbt.CompoundTag({"Y": nbt.ByteTag(0), "Palette": nbt.compound_list(pal), "BlockStates": data})
    lvl = nbt.CompoundTag({"xPos": nbt.IntTag(0), "zPos": nbt.IntTag(0), "Sections": nbt.compound_list([sec])})
    return nbt.CompoundTag({"DataVersion": nbt.IntTag(dv), "Level": lvl})


def _ticks(root, key):
    holder = nbt.get_tag(root, "Level") or root
    return {(str(nbt.get(t, "i")), int(nbt.get(t, "x")), int(nbt.get(t, "y")), int(nbt.get(t, "z"))): int(nbt.get(t, "t"))
            for t in nbt.get_tag(holder, key) or []}


def test_flat_chunks_get_fluid_ticks():
    for dv in (4700, 3465):                              # 26.x, 1.20.x: top level fluid_ticks
        root = _chunk(dv)
        nf, nb = fluids.add_ticks(root, 0, 0, -1)
        t = _ticks(root, "fluid_ticks")
        assert t[("minecraft:flowing_lava", 1, 9, 1)] == 10          # Nether delay
        assert t[("minecraft:flowing_lava", 1, 8, 1)] == 10
        assert t[("minecraft:flowing_lava", 2, 10, 1)] == 10
        assert t[("minecraft:lava", 1, 10, 1)] == 10                  # the source has air beside it
    root = _chunk(3465)
    fluids.add_ticks(root, 0, 0, 0)
    t = _ticks(root, "fluid_ticks")
    assert t[("minecraft:flowing_lava", 1, 9, 1)] == 30              # Overworld delay
    assert t[("minecraft:lava", 1, 10, 1)] == 30


def test_pre_118_chunks_use_liquid_ticks():
    root = _chunk(2584, flat=False)                      # 1.16.5: Level.LiquidTicks, spanning-free palette
    nf, nb = fluids.add_ticks(root, 0, 0, 0, [("minecraft:lava", 1, 9, 1, 7), ("minecraft:fire", 5, 5, 5, 3)])
    t = _ticks(root, "LiquidTicks")
    assert t[("minecraft:flowing_lava", 1, 9, 1)] == 7                # Bedrock's own delay wins
    assert t[("minecraft:flowing_lava", 1, 8, 1)] == 30
    assert nf == len(t) and nb == 0                                    # no fire there: not translated
    assert "TileTicks" not in nbt.get_tag(root, "Level")


def test_bedrock_block_tick_needs_the_block():
    root = _chunk(3465)
    # netherrack at (1, 7, 1): a "gravel" tick on it is not translated, a netherrack one is
    fluids.add_ticks(root, 0, 0, 0, [("minecraft:gravel", 1, 7, 1, 4), ("minecraft:netherrack", 1, 7, 1, 4)])
    assert _ticks(root, "block_ticks") == {("minecraft:netherrack", 1, 7, 1): 4}


def test_1_12_chunk_ticks_the_flowing_blocks():
    root = _chunk(1343, legacy=True)
    nf, nb = fluids.add_ticks(root, 0, 0, 0, [("minecraft:lava", 1, 9, 1, 9)])
    t = _ticks(root, "TileTicks")
    assert t[("minecraft:flowing_lava", 1, 9, 1)] == 9
    assert t[("minecraft:flowing_lava", 2, 10, 1)] == 30
    assert all(i.startswith("minecraft:") for i, *_ in t)
    assert "LiquidTicks" not in nbt.get_tag(root, "Level")            # 1.12 has one list


def test_no_liquid_no_ticks_and_older_formats_untouched():
    root = _chunk(3465)
    sec = nbt.get_tag(root, "sections")[0]
    sec["block_states"] = nbt.CompoundTag({"palette": nbt.compound_list([_state("minecraft:stone")])})
    assert fluids.add_ticks(root, 0, 0, 0) == (0, 0)
    old = nbt.CompoundTag({"Level": nbt.CompoundTag({"Blocks": nbt.ByteArrayTag(np.zeros(32768, np.int8))})})
    assert fluids.add_ticks(old, 0, 0, 0) == (0, 0)


def test_second_run_adds_nothing():
    root = _chunk(3465)
    fluids.add_ticks(root, 0, 0, 0)
    assert fluids.add_ticks(root, 0, 0, 0) == (0, 0)


def test_world_pass_and_bedrock_ticks(tmp_path, monkeypatch):
    folder = tmp_path / "world" / "DIM-1" / "region"
    folder.mkdir(parents=True)
    rw = RegionWriter()
    rw.put(0, 0, nbt.dump(_chunk(3465), ""))
    rw.write(str(folder / "r.0.0.mca"))

    class FakeDb:
        def iterate(self):
            import struct
            tick = nbt.CompoundTag({"blockState": nbt.CompoundTag({"name": nbt.StringTag("minecraft:lava")}),
                                    "time": nbt.IntTag(120), "x": nbt.IntTag(1), "y": nbt.IntTag(8), "z": nbt.IntTag(1)})
            root = nbt.CompoundTag({"currentTick": nbt.IntTag(100), "tickList": nbt.compound_list([tick])})
            yield struct.pack("<iii", 0, 0, 1) + b"\x33", nbt.dump(root, "", little_endian=True)

        def close(self):
            pass

    from worldbridge.bedrock import extra
    monkeypatch.setattr(extra, "_db", lambda src: FakeDb())
    ticks = fluids.read_bedrock_ticks("x")
    assert ticks == {(-1, 0, 0): [("minecraft:lava", 1, 8, 1, 20)]}
    stats = fluids.schedule_world(str(tmp_path / "world"), None, "x")
    assert stats["chunks"] == 1 and stats["fluid"] >= 4
    raw = JavaRegion(str(folder / "r.0.0.mca")).read(0, 0)
    root = nbt.load(raw, compressed=False).tag
    assert _ticks(root, "fluid_ticks")[("minecraft:flowing_lava", 1, 8, 1)] == 20


def test_1_12_static_liquid_with_a_level_becomes_flowing_and_unversioned_chunks_need_the_hint():
    root = _chunk(1343, legacy=True)
    sec = nbt.get_tag(nbt.get_tag(root, "Level"), "Sections")[0]
    blocks = np.asarray(sec["Blocks"].np_array).copy()
    blocks[blocks == 10] = 11                              # the writer's static lava with a level in its data
    sec["Blocks"] = nbt.ByteArrayTag(blocks)
    del root["DataVersion"]
    assert fluids.add_ticks(root, 0, 0, 0) == (0, 0)       # no version, no hint: left alone
    nf, nb = fluids.add_ticks(root, 0, 0, 0, assume_dv=1343)
    t = _ticks(root, "TileTicks")
    assert t[("minecraft:flowing_lava", 1, 9, 1)] == 30 and nf == 3
    assert (np.asarray(sec["Blocks"].np_array) == 10).sum() == 3     # the three cells with a level are flowing blocks
