"""Java 1.13 chunks with status "fullchunk" hold complete terrain: Amulet (which writes only chunks
scoring 2.0) must not drop them."""
import os
import shutil

from worldbridge import nbt
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.region import JavaRegion, RegionWriter
from worldbridge.model import Progress
from tests.test_biome_ids import _bedrock_ids, _java_ids, _source


def _set_status(world, status):
    n = 0
    for fn in os.listdir(os.path.join(world, "region")):
        path = os.path.join(world, "region", fn)
        reg = JavaRegion(path)
        rw = RegionWriter()
        for lx, lz in reg.chunks():
            root = nbt.load(reg.read(lx, lz), compressed=False).tag
            lvl = root["Level"] if "Level" in root else root
            lvl["Status"] = nbt.StringTag(status)
            rw.put(lx, lz, nbt.dump(root, ""))
            n += 1
        rw.write(path)
    return n


def test_fullchunk_chunks_reach_the_output(tmp_path):
    hub = str(tmp_path / "hub")
    coords = _source(hub, [1])
    j13 = str(tmp_path / "j13")
    convert(hub, j13, TargetSpec(family="java", java_mode="amulet", version=(1, 13, 2), ring=False), progress=Progress())
    for status in ("fullchunk", "finalized", "mobs_spawned", "lighted"):
        src = str(tmp_path / ("src_" + status))
        shutil.copytree(j13, src)
        assert _set_status(src, status) >= len(coords)
        for label, target, read in (
            ("j17", TargetSpec(family="java", java_mode="amulet", version=(1, 17, 1), ring=False), _java_ids),
            ("bed", TargetSpec(family="bedrock", version=(1, 16, 0), ring=False), _bedrock_ids),
        ):
            out = str(tmp_path / f"{label}_{status}")
            convert(src, out, target, progress=Progress())
            for c in coords:
                assert read(out, *c), (status, label, c)
