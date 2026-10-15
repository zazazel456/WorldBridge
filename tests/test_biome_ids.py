"""Biome ids >= 40 and the signed ones (129 - 167) survive a world that goes through Amulet from a Java <= 1.12 Anvil chunk."""
import os

import numpy as np
import pytest

from worldbridge import nbt
from worldbridge.bedrock.extra import _db, _get, chunk_prefix
from worldbridge.biomes import JAVA_19, java12_lut
from worldbridge.convert import TargetSpec, convert
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions
from worldbridge.java.region import JavaRegion
from worldbridge.model import Progress
from tests.helpers import SyntheticWorld, make_chunk

HUB_IDS = [0, 3, 21, 39, 40, 44, 48, 129, 131, 149, 168]
REAL_IDS = [127, 129, 131, 149, 160, 165]


def _grid(ids):
    """[z, x] ids, constant per 4 x 4 cell (Java 1.15+ keeps one biome per cell) and all of them present."""
    cells = np.array([ids[i % len(ids)] for i in range(16)], np.uint8).reshape(4, 4)
    return np.kron(cells, np.ones((4, 4), np.uint8))


def _source(path, ids, **opt):
    src = SyntheticWorld(radius=1)
    w = JavaNumericWriter(path, JavaWriteOptions(kind="anvil", **opt), Progress())
    for cx, cz in src.chunk_coords(0):
        c = make_chunk(cx, cz)
        c.biomes = _grid(ids)
        w.add_chunk(0, c)
    w.finish(src.info)
    return src.chunk_coords(0)


def _java_ids(world, cx, cz):
    reg = JavaRegion(os.path.join(world, "region", f"r.{cx >> 5}.{cz >> 5}.mca"))
    root = nbt.load(reg.read(cx & 31, cz & 31), compressed=False).tag
    lvl = root["Level"] if "Level" in root else root
    return set(np.unique(np.asarray(lvl["Biomes"].np_array).astype(np.int64) & 0xFF).tolist())


def _bedrock_ids(world, cx, cz):
    db = _db(world)
    try:
        d2 = _get(db, chunk_prefix(cx, cz, 0) + b"\x2d")
    finally:
        db.close()
    return set(np.frombuffer(d2[512:768], np.uint8).tolist())


def _convert(src, out, target):
    convert(src, out, target, progress=Progress())


@pytest.fixture(scope="module")
def hub(tmp_path_factory):
    path = str(tmp_path_factory.mktemp("hub") / "hub")
    return path, _source(path, HUB_IDS)


def test_hub_ids_reach_bedrock_1_16(hub, tmp_path):
    path, coords = hub
    out = str(tmp_path / "bed")
    _convert(path, out, TargetSpec(family="bedrock", version=(1, 16, 0)))
    # Bedrock's own numbers: small_end_islands 9, warm_ocean 40, deep_lukewarm_ocean 43, bamboo_jungle 48
    assert _bedrock_ids(out, *coords[0]) == {0, 3, 9, 21, 39, 40, 43, 48, 129, 131, 149}


def test_hub_ids_reach_java_1_17(hub, tmp_path):
    path, coords = hub
    out = str(tmp_path / "j17")
    _convert(path, out, TargetSpec(family="java", java_mode="amulet", version=(1, 17, 1)))
    assert _java_ids(out, *coords[0]) == set(HUB_IDS)


def test_hub_ids_degrade_to_valid_java_1_12_ids(hub, tmp_path):
    path, coords = hub
    expect = {0, 3, 9, 21, 24, 39, 129, 131, 149}      # warm_ocean -> ocean, deep_lukewarm -> deep_ocean, bamboo -> jungle
    amu = str(tmp_path / "j12a")
    _convert(path, amu, TargetSpec(family="java", java_mode="amulet", version=(1, 12, 2)))
    assert _java_ids(amu, *coords[0]) == expect
    num = str(tmp_path / "j12n")
    _convert(path, num, TargetSpec(family="java", java_mode="numeric", java_version_limit="1.12"))
    got = set(np.unique(JavaNumericWorld(num).read_chunk(0, *coords[0]).biomes).tolist())
    assert got == expect and got <= set(JAVA_19)


def test_signed_byte_java_1_12_source(tmp_path):
    src = str(tmp_path / "src")
    coords = _source(src, REAL_IDS, version_limit="1.12")           # what a real 1.12 world stores: signed bytes
    raw = nbt.load(JavaRegion(os.path.join(src, "region", "r.-1.-1.mca")).read(31, 31), compressed=False).tag
    assert (np.asarray((raw["Level"] if "Level" in raw else raw)["Biomes"].np_array) < 0).any()
    for label, target, read in (
        ("bed", TargetSpec(family="bedrock", version=(1, 16, 0)), _bedrock_ids),
        ("j17", TargetSpec(family="java", java_mode="amulet", version=(1, 17, 1)), _java_ids),
    ):
        out = str(tmp_path / label)
        _convert(src, out, target)
        assert read(out, *coords[0]) == set(REAL_IDS), label


def test_java_12_lut_keeps_valid_ids_and_degrades_the_rest():
    lut = java12_lut()
    assert all(lut[b] == b for b in JAVA_19) and lut[255] == 255
    assert (lut[44], lut[48], lut[168], lut[40], lut[174], lut[200]) == (0, 24, 21, 9, 1, 1)


def test_ring_biomes_above_39_survive(tmp_path):
    """The generator's ring of a Java 1.17 / Bedrock target keeps its ocean / mutated biomes (not plains)."""
    src = str(tmp_path / "src")
    coords = _source(src, [1])
    seen = {}
    for label, target, read in (
        ("j17", TargetSpec(family="java", java_mode="amulet", version=(1, 17, 1)), _java_ids),
        ("bed", TargetSpec(family="bedrock", version=(1, 16, 0)), _bedrock_ids),
    ):
        out = str(tmp_path / label)
        _convert(src, out, target)
        ring = set()
        for cx in range(-6, 6):
            for cz in range(-6, 6):
                if (cx, cz) in coords:
                    continue
                try:
                    ring |= read(out, cx, cz)
                except Exception:  # noqa: BLE001 - no such chunk
                    pass
        seen[label] = ring
    assert any(b >= 40 for b in seen["j17"]), seen
    assert any(b >= 40 for b in seen["bed"]), seen
