"""Which chunk Status values count as finished (see worldbridge.incomplete): proven on a Java 1.13.2 server, where
chunks saved as empty/carved/liquid_carved/decorated still changed (ores, trees, lakes from the neighbours) once the
chunks around them generated, and lighted and later ones did not."""
import pytest

from worldbridge import nbt
from worldbridge.incomplete import java_incomplete
from worldbridge.java.region import RegionWriter

KEPT_113 = ["lighted", "mobs_spawned", "finalized", "fullchunk", "postprocessed"]
SKIPPED_113 = ["empty", "base", "carved", "liquid_carved", "decorated"]
KEPT_114 = ["light", "spawn", "heightmaps", "full", "minecraft:light", "minecraft:spawn", "minecraft:full"]
SKIPPED_114 = ["structure_starts", "structure_references", "biomes", "noise", "surface", "carvers", "liquid_carvers",
               "features", "minecraft:initialize_light", "minecraft:features", "minecraft:carvers", "minecraft:terrain"]


def _world(tmp_path, statuses, level_wrapped):
    region = tmp_path / "w" / "region"
    region.mkdir(parents=True)
    rw = RegionWriter()
    for i, status in enumerate(statuses):
        body = {"xPos": nbt.IntTag(i), "zPos": nbt.IntTag(0), "Status": nbt.StringTag(status)}
        root = nbt.CompoundTag({"Level": nbt.CompoundTag(body)}) if level_wrapped else nbt.CompoundTag(body)
        rw.put(i, 0, nbt.dump(root, ""))
    rw.write(str(region / "r.0.0.mca"))
    return str(tmp_path / "w")


@pytest.mark.parametrize("wrapped", [True, False])
def test_status_kept_or_skipped(tmp_path, wrapped):
    kept = KEPT_113 + KEPT_114
    skipped = SKIPPED_113 + SKIPPED_114
    statuses = kept + skipped
    excl = java_incomplete(_world(tmp_path, statuses, wrapped))
    assert excl == {0: {(i, 0) for i in range(len(kept), len(statuses))}}


def test_amulet_hook_marks_the_finished_scores_full():
    from amulet.api.chunk.status import Status, StatusFormats  # noqa: F401
    from amulet.api.chunk import Chunk
    c = Chunk(0, 0)
    got = {}
    for name in KEPT_113[:-1]:
        c.status = name
        got[name] = c.status.value
    assert all(v >= 1.1 or v == -0.1 for v in got.values()), got
    for name in ("empty", "base", "carved", "liquid_carved", "decorated"):
        c.status = name
        assert not (c.status.value >= 1.1 or c.status.value == -0.1), name
