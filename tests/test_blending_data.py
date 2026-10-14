import os

from worldbridge import nbt
from worldbridge.java import blending
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.convert import TargetSpec, convert
from worldbridge.model import Progress
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


def test_every_java_118_target_blends_unless_turned_off():
    t = TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4))
    assert blending.supported(t) and blending.supported(TargetSpec(family="java"))
    assert blending.supported(TargetSpec(family="java", java_mode="amulet", version=(1, 18, 2)))
    assert not blending.supported(TargetSpec(family="java", java_mode="amulet", version=(1, 17, 1)))
    assert not blending.supported(TargetSpec(family="bedrock", version=(1, 21, 50)))
    t.blend = False
    assert not blending.supported(t)


def test_policy_never_says_the_edge_continues_by_itself_for_java_118():
    t = TargetSpec(family="java", java_mode="amulet", version=(1, 20, 4))
    for old in (False, True):
        text = policy.decide(t, old).text
        assert "continues by itself" not in text and "blend" in text
    assert "blending data" in policy.decide(t, False).text
    t.blend = False
    assert policy.decide(t, False).kind == "off" and policy.decide(t, True).kind == "off"


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


def test_mark_world_26x_layout_and_each_chunks_own_data_version(tmp_path):
    folder = tmp_path / "dimensions" / "minecraft" / "overworld" / "region"
    nether = tmp_path / "dimensions" / "minecraft" / "the_nether" / "region"
    os.makedirs(folder)
    os.makedirs(nether)
    rw = RegionWriter()
    rw.put(0, 0, _chunk(4800))
    rw.put(1, 0, _chunk(2975))                       # an older chunk in the same world keeps its own layout
    rw.put(2, 0, _chunk(2730))                       # pre-1.18 format: left to the game's upgrade
    rw.write(str(folder / "r.0.0.mca"))
    rw.write(str(nether / "r.0.0.mca"))
    assert blending.mark_world(str(tmp_path)) == 2
    reg = JavaRegion(str(folder / "r.0.0.mca"))
    got = {lx: nbt.load(reg.read(lx, 0), compressed=False).tag for lx, _ in reg.chunks()}
    assert set(got[0]["blending_data"]) == {"min_section", "max_section"}
    assert set(got[1]["blending_data"]) == {"old_noise"} and "blending_data" not in got[2]
    other = JavaRegion(str(nether / "r.0.0.mca"))
    assert "blending_data" not in nbt.load(other.read(0, 0), compressed=False).tag      # the overworld only


def _dvs_and_tags(world):
    out = []
    reg = JavaRegion(os.path.join(world, "region", "r.0.0.mca"))
    for lx, lz in reg.chunks():
        root = nbt.load(reg.read(lx, lz), compressed=False).tag
        out.append((int(root["DataVersion"].py_data), "blending_data" in root))
    return out


def test_copy_route_marks_a_same_seed_1_18_plus_world(tmp_path):
    from .test_border import _write_small_lce

    hub = str(tmp_path / "hub")
    _write_small_lce(hub)
    plain = str(tmp_path / "plain")                  # a 1.20.4 world without the tag (--no-blend)
    spec = dict(family="java", java_mode="amulet", version=(1, 20, 4), ring=False)
    convert(hub, plain, TargetSpec(**spec, blend=False))
    assert not any(tag for _dv, tag in _dvs_and_tags(plain))
    logs = []
    tagged = str(tmp_path / "tagged")
    convert(plain, tagged, TargetSpec(**spec), progress=Progress(on_log=logs.append))
    assert any("Copying the world" in m for m in logs)           # the copy route
    got = _dvs_and_tags(tagged)
    assert got and all(dv >= 2825 and tag for dv, tag in got)
    untouched = str(tmp_path / "untouched")
    convert(plain, untouched, TargetSpec(**spec, blend=False))
    assert not any(tag for _dv, tag in _dvs_and_tags(untouched))   # --no-blend: copied as it is
