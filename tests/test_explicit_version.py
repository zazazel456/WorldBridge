"""An explicit --version is never ignored; the numeric 1.2 - 1.12 writers stamp no DataVersion with their old ids."""
import glob

import pytest

from worldbridge import nbt, tiles
from worldbridge.convert import ConversionError, TargetSpec, convert, resolve_explicit_version
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions
from worldbridge.java.region import JavaRegion
from worldbridge.model import Progress

from .helpers import SyntheticWorld, make_chunk


def _spec(mode="auto", version=None, limit=None):
    return TargetSpec(family="java", java_mode=mode, version=version, java_version_limit=limit)


def test_auto_with_version_1_13_plus_picks_amulet():
    t = _spec(version=(1, 20, 4))
    note = resolve_explicit_version(t)
    assert t.java_mode == "amulet" and t.version == (1, 20, 4)
    assert "1.20.4" in note and t.describe() == "Java Edition 1.20.4"


def test_dfu_with_version_is_not_ignored_either():
    t = _spec("dfu", (1, 16, 5))
    resolve_explicit_version(t)
    assert t.java_mode == "amulet"


@pytest.mark.parametrize("version,limit", [((1, 12, 2), "1.12"), ((1, 8, 9), "1.8"), ((1, 2, 5), "1.2")])
def test_auto_with_old_version_picks_the_numeric_route(version, limit):
    t = _spec(version=version)
    assert resolve_explicit_version(t)
    assert (t.java_mode, t.java_version_limit) == ("numeric", limit)


def test_auto_without_version_is_unchanged():
    t = _spec()
    assert resolve_explicit_version(t) is None and t.java_mode == "auto"
    assert "latest" in t.describe()


def test_conflicting_or_impossible_combinations_are_refused():
    with pytest.raises(ConversionError):
        resolve_explicit_version(_spec(version=(1, 8, 9), limit="1.12"))
    with pytest.raises(ConversionError):
        resolve_explicit_version(_spec("mcregion", (1, 20, 4), "1.1"))
    with pytest.raises(ConversionError):
        resolve_explicit_version(_spec(version=(0, 9, 0)))     # not a version with an Anvil format


def test_numeric_mode_takes_the_limit_from_the_version():
    t = _spec("numeric", (1, 7, 10))
    resolve_explicit_version(t)
    assert t.java_version_limit == "1.7"


def test_other_families_are_untouched():
    t = TargetSpec(family="bedrock", version=(1, 20, 0))
    assert resolve_explicit_version(t) is None and t.java_mode == "auto"


def test_legacy_kind_first_versions_match_the_block_lists():
    """MIN_VERSION_LEGACY (kinds with a Sign / Chest / Furnace block entity of the hub whose block is newer)."""
    from worldbridge.amulet_bridge import translation_manager

    tm = translation_manager()
    blocks = {"barrel": "barrel", "smoker": "smoker", "blast_furnace": "blast_furnace", "hanging_sign": "oak_hanging_sign"}
    assert set(blocks) == set(tiles.MIN_VERSION_LEGACY)
    for platform, pos in (("java", 0), ("bedrock", 1)):
        versions = sorted(tuple(v) for v in tm.version_numbers(platform))
        for kind, block in blocks.items():
            first = next(v for v in versions if block in tm.get_version(platform, v).block.base_names("minecraft"))
            have = tiles.MIN_VERSION_LEGACY[kind][pos]
            assert have >= (tm.get_version("java", first).data_version if platform == "java" else first), (kind, first)


def test_hanging_signs_and_1_14_containers_are_missing_from_older_targets():
    assert not tiles.exists_in_java("hanging_sign", 3218) and tiles.exists_in_java("hanging_sign", 3463)
    assert not tiles.exists_in_java("barrel", 1519) and tiles.exists_in_java("barrel", 1952)


def _chunk_roots(world):
    out = []
    for f in glob.glob(str(world) + "/region/*.mca"):
        r = JavaRegion(f)
        out += [nbt.load(r.read(lx, lz), compressed=False).tag for lx, lz in r.chunks()]
    return out


def test_convert_with_version_writes_exactly_that_version(tmp_path):
    src = SyntheticWorld(radius=1)
    w = JavaNumericWriter(str(tmp_path / "a"), JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    logs = []
    t = _spec(version=(1, 20, 4))
    t.blend = False                                         # blending would write the pre-1.18 format of an old world
    convert(str(tmp_path / "a"), str(tmp_path / "b"), t, Progress(None, logs.append))
    dvs = {int(nbt.get(r, "DataVersion")) for r in _chunk_roots(tmp_path / "b")}
    assert dvs == {3700}                                    # 1.20.4, not the latest (5020)
    assert any("1.20.4" in m for m in logs) and not any("(latest)" in m for m in logs)


def test_numeric_writer_stamps_no_data_version_and_uses_the_ids_the_fixers_know(tmp_path):
    """1.12 runs its DataFixers (MinecartRideable -> minecart, Trap -> dispenser) on chunks older than 1.11's
    DataVersion; a chunk without any is the oldest of all, so the pre-1.11 ids are the consistent choice (the
    server then renames them itself when it loads the chunk)."""
    for lim in ("1.12", "1.8", "1.2"):
        c = make_chunk(0, 0)
        c.blocks[5, 1, 1] = 23                                 # a dispenser for its block entity
        c.tile_entities.append(nbt.CompoundTag({"id": nbt.StringTag("Trap"), "x": nbt.IntTag(1), "y": nbt.IntTag(5),
                                                "z": nbt.IntTag(1)}))
        out = tmp_path / lim
        w = JavaNumericWriter(str(out), JavaWriteOptions(kind="anvil", version_limit=lim), Progress())
        w.add_chunk(0, c)
        w.finish(SyntheticWorld(radius=0).info)
        root = _chunk_roots(out)[0]
        assert "DataVersion" not in root
        ids = {str(nbt.get(t, "id")) for t in nbt.get_tag(root, "Level")["TileEntities"]}
        assert "Trap" in ids and not any(i.startswith("minecraft:") for i in ids)
        dat = nbt.load(open(out / "level.dat", "rb").read()).tag["Data"]
        assert "DataVersion" not in dat


def test_gui_version_choices_never_pair_auto_with_a_version(tmp_path):
    """Every entry of the GUI's version list is either the automatic route without a version or an explicit
    version on a route that honours it (Amulet 1.13+, numeric/McRegion/Alpha with their limit)."""
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    from worldbridge.gui.app import MainWindow

    w = MainWindow(remember=False)
    try:
        for i in range(w.java_ver.count()):
            mode, ver, lim = w.java_ver.itemData(i)
            if mode in ("auto", "dfu"):
                assert ver is None
            elif mode == "amulet":
                assert ver is not None
            else:
                assert ver is None and lim
            t = TargetSpec(family="java", java_mode=mode, version=ver, java_version_limit=lim)
            assert resolve_explicit_version(t) is None or t.java_mode != "auto"
    finally:
        w.close()
        app.processEvents()
