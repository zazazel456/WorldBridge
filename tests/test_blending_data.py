import os

from worldbridge import nbt
from worldbridge.java import blending
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.convert import TargetSpec
from worldbridge.terrain import policy


def test_layout_per_data_version():
    assert blending.layout(2730) is None
    old = blending.layout(2975)                       # 1.18.2
    assert set(old) == {"old_noise"} and int(old["old_noise"].py_data) == 1
    assert set(blending.layout(3440)) == {"old_noise"}
    for dv in (3441, 3463, 3700, 4800):               # 1.20 and later: sections, no heights
        bd = blending.layout(dv)
        assert set(bd) == {"min_section", "max_section"}
        assert (int(bd["min_section"].py_data), int(bd["max_section"].py_data)) == (-4, 20)


def test_when_needed():
    n = blending.needed
    assert n("bedrock", False, False, False)
    assert n("java_modern", False, False, True)       # moved / repainted
    assert n("java_modern", False, True, False)       # downgrade: another generator
    assert not n("java_modern", False, True, True)    # same generator, same place
    assert not n("java_modern", True, True, True)     # pre-1.18 source: written pre-1.18 instead


def test_policy_foreign_and_no_blend():
    t = TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4))
    assert "blending data" in policy.decide(t, False, foreign=True).text
    assert "blending data" not in policy.decide(t, False).text
    t.blend = False
    assert policy.decide(t, False, foreign=True).kind == "off"


def _chunk(dv, status="minecraft:full", **extra):
    c = nbt.CompoundTag({"DataVersion": nbt.IntTag(dv), "Status": nbt.StringTag(status)})
    c.update(extra)
    return nbt.dump(c, "")


def test_mark_world(tmp_path):
    rw = RegionWriter()
    rw.put(0, 0, _chunk(3463))
    rw.put(1, 0, _chunk(3463, "minecraft:empty"))
    rw.put(2, 0, _chunk(3463, blending_data=nbt.CompoundTag({"min_section": nbt.IntTag(-4), "max_section": nbt.IntTag(10)})))
    rw.put(3, 0, _chunk(2975))
    os.makedirs(tmp_path / "region")
    path = str(tmp_path / "region" / "r.0.0.mca")
    rw.write(path)
    assert blending.mark_world(str(tmp_path)) == 2
    reg = JavaRegion(path)
    got = {lx: nbt.load(reg.read(lx, 0), compressed=False).tag for lx, _ in reg.chunks()}
    assert "blending_data" in got[0] and "blending_data" not in got[1]
    assert int(got[2]["blending_data"]["max_section"].py_data) == 10     # untouched
    assert set(got[3]["blending_data"]) == {"old_noise"}
    assert blending.mark_world(str(tmp_path)) == 0                       # idempotent
