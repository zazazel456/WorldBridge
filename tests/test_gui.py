"""The graphical interface (offscreen): every function still reachable after the reorganisation,
rows shown for the chosen target, messages inside the window, a conversion started from it, and
the desktop theme integration (gui/theme.py)."""
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)   # pytest >= 8.2: a broken libEGL skips

from PySide6.QtGui import QColor, QPalette  # noqa: E402

from worldbridge.gui import theme  # noqa: E402
from worldbridge.lce.world import LCEWriteOptions, LCEWriter  # noqa: E402
from worldbridge.model import Progress  # noqa: E402

from .helpers import SyntheticWorld  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def win(app):
    from worldbridge.gui.app import MainWindow

    w = MainWindow(remember=False)
    w.resize(1200, 850)
    w.show()
    app.processEvents()
    yield w
    w.close()
    app.processEvents()


def _wait(app, cond, sec=60):
    end = time.time() + sec
    while time.time() < end and not cond():
        app.processEvents()
        time.sleep(0.02)
    return cond()


def _shown(w, widget):
    return w.form.isRowVisible(widget)


def _pick(box, data):
    items = [box.itemData(i) for i in range(box.count())]
    items = [tuple(v) if isinstance(v, list) else v for v in items]
    assert data in items, data
    box.setCurrentIndex(items.index(data))


def test_every_tab_and_control_is_there(win, app):
    assert [win.tabs.tabText(i) for i in range(win.tabs.count())] == ["Conversion", "Map and chunks", "Players",
                                                                      "World management"]
    for i in range(win.tabs.count()):
        win.tabs.setCurrentIndex(i)
        app.processEvents()
        win.grab()
    m = win.map_tab
    # the map's selection menu and the view actions (they were buttons in a row before)
    assert [a.text() for a in m.sel_actions] == ["Select all", "Deselect all", "Invert selection",
                                                 "Import selection…", "Export selection…"]
    assert [a.shortcut().toString() for a in m.sel_actions[:3]] == ["Ctrl+A", "Ctrl+Shift+A", "Ctrl+I"]
    assert [m.modes.button(i).text() for i in range(3)] == ["Pan", "Select", "Spawn"]
    assert m.modes.checkedId() == 1
    # everything else of the old rows: scope, move, spawn, regeneration, biomes, trim, edits on the world
    for name in ("scope_all", "scope_sel", "move_sel", "move_center", "move_at", "move_x", "move_z", "use_spawn",
                 "sx", "sy", "sz", "regen_nether", "regen_end", "biome_box", "world_biome_box", "trim_btn",
                 "trim_gear", "trim_settings", "dim_box"):
        assert getattr(m, name) is not None
    labels = {b.text() for b in m.findChildren(QtWidgets.QPushButton)}
    assert {"Apply", "Remove", "Restore the original", "Delete the selected chunks…", "Keep only the selected chunks…",
            "Give the biome to the selected chunks…"} <= labels
    # the manage tab keeps its buttons
    labels = {b.text() for b in win.manage_tab.findChildren(QtWidgets.QPushButton)}
    assert {"Open folder…", "Open file…", "Use the world opened at the top", "Reload", "&Save changes"} <= labels
    # the conversion's buttons are hidden on the world's management
    win.tabs.setCurrentWidget(win.manage_tab)
    assert not win.run_box.isVisible()
    win.tabs.setCurrentIndex(0)
    assert win.run_box.isVisible() and win.btn_convert.isVisible() and not win.btn_cancel.isVisible()


def test_rows_follow_the_target(win):
    _pick(win.edition, "java")
    win.java_ver.setCurrentIndex(0)                                   # latest: the game blends
    assert _shown(win, win.java_ver) and not _shown(win, win.lce_plat) and not _shown(win, win.bed_ver)
    assert win.blend_row.isVisibleTo(win) and not win.ring_row.isVisibleTo(win)
    assert not _shown(win, win.depth_box)
    _pick(win.java_ver, ("numeric", None, "1.12"))                    # 1.12: WorldBridge's ring
    assert not win.blend_row.isVisibleTo(win) and win.ring_row.isVisibleTo(win)
    assert _shown(win, win.depth_box) and _shown(win, win.tall_box)
    _pick(win.java_ver, ("alpha", None, "alpha"))
    assert _shown(win, win.alpha_hint)
    _pick(win.edition, "lce")
    _pick(win.lce_plat, "win64")
    assert _shown(win, win.lce_plat) and _shown(win, win.lce_xuid_row) and not _shown(win, win.java_ver)
    _pick(win.lce_plat, "ps3")
    assert not _shown(win, win.lce_xuid_row)
    _pick(win.edition, "bedrock")
    old = [win.bed_ver.itemData(i) for i in range(win.bed_ver.count()) if tuple(win.bed_ver.itemData(i)) < (1, 18)]
    _pick(win.bed_ver, old[0])
    assert not _shown(win, win.borders)                              # old Bedrock: no border at all
    assert _shown(win, win.depth_box)
    _pick(win.edition, "pe_old")
    assert _shown(win, win.pe_hint) and not _shown(win, win.bed_ver)
    # the chosen underground y only when asked for
    _pick(win.depth, "custom")
    assert win.depth_y.isVisibleTo(win) and win.depth_y.isEnabled()
    _pick(win.depth, "cut")
    assert not win.depth_y.isVisibleTo(win)
    # Better than Adventure: its rows, Java only
    assert not _shown(win, win.bta_pal_row)
    win._on_detected([("title", "BTA")], "bta", "Mondo")
    assert _shown(win, win.bta_pal_row) and win.edition.currentData() == "java"
    assert not win.edition.model().item(win.edition.findData("lce")).isEnabled()
    win._on_detected([("title", "x")], "lce", "Mondo")
    assert not _shown(win, win.bta_pal_row)


def test_the_underground_choice_starts_on_automatic(win):
    assert win.depth.itemData(0) == "auto" and win.depth.currentData() == "auto"
    assert win.depth.itemText(0).startswith("Automatic")
    assert win._target().depth == "auto"


def test_target_spec(win):
    win._on_detected([("title", "x")], "java_numeric", "Mio")
    _pick(win.edition, "lce")
    _pick(win.lce_plat, "win64")
    win.lce_xuid.setText(" 123 ")
    win.ring.setChecked(False)
    _pick(win.depth, "custom")
    win.depth_y.setValue(-20)
    win.name_edit.setText("Nuovo")
    t = win._target()
    assert (t.family, t.lce_platform, t.lce_player_id, t.ring, t.depth, t.world_name) == \
        ("lce", "win64", "123", False, -20, "Nuovo")
    assert t.selection is None
    m = win.map_tab
    m.canvas.selection = {0: {(0, 0), (1, 0)}}
    m.scope_sel.setChecked(True)
    m.move_sel.setChecked(True)
    m.move_x.setValue(100)
    m.use_spawn.setChecked(True)
    m.sx.setValue(5)
    m.regen_end.setChecked(True)
    t = win._target()
    assert t.selection.chunks == {0: {(0, 0), (1, 0)}} and t.selection.move_to == (100, 0)
    assert t.selection.spawn == (5, m.sy.value(), m.sz.value()) and t.regen == (1,)
    # the conversion tab says it
    text = win.scope_label.text()
    assert "Selected chunks only (2)" in text and "X 100" in text and "End regenerated" in text
    assert "new spawn 5" in text
    assert win._output_dir(t).endswith("Nuovo_LCE_win64")


def test_messages_inside_the_window(win, app):
    win.src_edit.setText("")
    win._start()                                   # no world: said in the window, no dialog to close
    assert win.message.isVisible() and "Open the world to convert first" in win.message.text.text()
    win.message.dismiss()
    assert not win.message.isVisible()


def test_players_summary(win):
    class E:
        def __init__(self, i):
            self.key, self.name, self.label, self.items, self.pos, self.dim = f"k{i}", "", f"P{i}", 1, None, 0

    t = win.players_tab
    t.set_players([E(0), E(1), E(2)])
    assert "as in the source world" in win.players_label.text()
    t.enable.setChecked(True)
    t._rows[2][0].setChecked(False)
    assert win.players_label.text() == "2 of 3 transferred · main: P0"
    t.set_players([])
    assert not t.table.isVisible() and not t.enable.isEnabled()


def test_convert_from_the_window(win, app, tmp_path):
    src = SyntheticWorld(radius=1, dims=(0,))
    w = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    win.src_edit.setText(str(tmp_path / "lce"))
    win._on_source_changed()
    assert _wait(app, lambda: win._src_kind == "lce")
    assert "Test World" in win.src_info.text() and win.windowTitle().startswith("Test World")
    _pick(win.edition, "java")
    _pick(win.java_ver, ("numeric", None, "1.12"))
    win.ring.setChecked(False)
    win.out_edit.setText(str(tmp_path / "out"))
    win._start()
    assert win.btn_cancel.isVisible() and win.bar.isVisible() and win.log_box.content.isVisible()
    assert _wait(app, lambda: win._worker is None, 180)
    assert win.message.isVisible() and "Conversion completed" in win.message.text.text()
    assert win.btn_open.isVisible() and os.path.isfile(os.path.join(win._result_path, "level.dat"))


# ============================================================ theme


def test_desktop_styles(monkeypatch, tmp_path):
    cfg = tmp_path / "cfg"
    (cfg / "qt6ct").mkdir(parents=True)
    (cfg / "kdeglobals").write_text("[General]\nColorScheme=BreezeDark\n\n[Colors:Window]\n"
                                    "ForegroundNegative=1,2,3\n\n[KDE]\nwidgetStyle=kvantum\n")
    (cfg / "qt6ct" / "qt6ct.conf").write_text("[Appearance]\nstyle=Oxygen\n")
    for k in ("QT_STYLE_OVERRIDE", "QT_QPA_PLATFORMTHEME", "KDE_FULL_SESSION"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("WORLDBRIDGE_USER_CONFIG", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "none"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    assert theme.wanted_styles() == ["kvantum"]
    monkeypatch.setenv("QT_STYLE_OVERRIDE", "Breeze")
    monkeypatch.setenv("QT_QPA_PLATFORMTHEME", "qt6ct")
    assert theme.wanted_styles() == ["Breeze", "Oxygen", "kvantum"]
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "GNOME")
    monkeypatch.delenv("QT_STYLE_OVERRIDE")
    monkeypatch.delenv("QT_QPA_PLATFORMTHEME")
    assert theme.wanted_styles() == []                                   # Fusion with GNOME's colours
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    (cfg / "kdeglobals").write_text("[General]\nColorScheme=BreezeLight\n")
    assert theme.wanted_styles() == ["breeze"]                           # Plasma's default


def test_state_colours(monkeypatch, tmp_path, app):
    cfg = tmp_path / "cfg"
    cfg.mkdir()
    (cfg / "kdeglobals").write_text("[Colors:Window]\nForegroundNegative=1,2,3\n")
    monkeypatch.setenv("WORLDBRIDGE_USER_CONFIG", str(cfg))
    monkeypatch.setenv("XDG_CONFIG_DIRS", str(tmp_path / "none"))
    monkeypatch.setenv("XDG_CURRENT_DESKTOP", "KDE")
    monkeypatch.delattr(theme.state_color, "cache", raising=False)
    assert theme.state_color("negative") == QColor(1, 2, 3)
    assert theme.state_color("positive") == QColor(39, 174, 96)          # Breeze's, not in the scheme
    monkeypatch.delattr(theme.state_color, "cache", raising=False)
    # secondary text is opaque (Qt's placeholder colour is half transparent)
    assert theme.secondary_color().alpha() == 255
    assert "color:#" in theme.span("x", "secondary")


def test_hint_label_follows_the_palette(app):
    from worldbridge.gui.widgets import HintLabel

    box = QtWidgets.QWidget()
    lab = HintLabel("ciao", box)
    pal = box.palette()
    pal.setColor(QPalette.PlaceholderText, QColor(10, 200, 30))
    box.setPalette(pal)
    app.processEvents()
    assert lab.palette().color(QPalette.WindowText) == QColor(10, 200, 30)


def test_environment_for_the_desktop(monkeypatch, tmp_path):
    from PySide6.QtCore import QSettings

    real = tmp_path / "real"
    data = tmp_path / "data"
    real.mkdir()
    data.mkdir()
    monkeypatch.setenv("WORLDBRIDGE_USER_CONFIG", str(real))
    monkeypatch.setenv("WORLDBRIDGE_USER_DATA", str(data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "runtime-config"))
    monkeypatch.setenv("XDG_DATA_DIRS", "/usr/share")
    monkeypatch.setattr(theme, "settings_dir", lambda: str(tmp_path / "settings"))
    theme.prepare_environment()
    assert os.environ["XDG_CONFIG_HOME"] == str(real)                    # the desktop's settings are read
    assert os.environ["XDG_DATA_DIRS"] == f"{data}:/usr/share"
    s = QSettings(QSettings.IniFormat, QSettings.UserScope, "WorldBridge", "Prova")
    assert s.fileName().startswith(str(tmp_path / "settings"))          # Qt's writes stay in .runtime


def test_style_plugins(monkeypatch, tmp_path):
    import PySide6

    lib = os.path.join(os.path.dirname(PySide6.__file__), "Qt", "lib", "libQt6Widgets.so.6")
    assert "libQt6Gui.so.6" in theme.elf_needed(lib)
    assert theme.elf_needed(str(tmp_path / "missing.so")) == []
    monkeypatch.setattr(theme, "SYSTEM_PLUGIN_DIRS", ())
    (tmp_path / "plugins" / "styles").mkdir(parents=True)
    (tmp_path / "plugins" / "styles" / "libbroken.so").write_bytes(b"not a plugin")
    monkeypatch.setenv("WORLDBRIDGE_QT_PLUGIN_DIRS", str(tmp_path / "plugins"))
    assert theme.find_style_plugin("kvantum") is None


def test_broken_style_is_refused(monkeypatch, tmp_path):
    """A plugin that cannot work is tried in another process, refused, and the answer remembered."""
    import shutil

    import PySide6

    fake = tmp_path / "libfake.so"
    shutil.copy(os.path.join(os.path.dirname(PySide6.__file__), "Qt", "lib", "libQt6Svg.so.6"), fake)
    monkeypatch.setattr(theme, "settings_dir", lambda: str(tmp_path / "settings"))
    monkeypatch.setattr(theme, "RUNTIME_DIR", str(tmp_path))
    monkeypatch.setenv("WORLDBRIDGE_HOME", str(tmp_path))
    assert theme.style_works(str(fake), "fake", timeout=120) is False
    cache = (tmp_path / "settings" / "WorldBridge" / "styles.json").read_text()
    assert "libfake.so" in cache and "false" in cache


def test_language_switch_keeps_every_choice(win, app, tmp_path):
    """EN | IT at the top right: the window comes back in the other language with the same world,
    the same conversion choices, the same map selection, spawn and players."""
    from worldbridge import i18n

    src = SyntheticWorld(radius=1, dims=(0,))
    w = LCEWriter(str(tmp_path / "lce"), LCEWriteOptions(platform="win64"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    win.src_edit.setText(str(tmp_path / "lce"))
    win._on_source_changed()
    assert _wait(app, lambda: win._src_kind == "lce" and win.map_tab._meta is not None)
    _pick(win.edition, "java")
    _pick(win.java_ver, ("numeric", None, "1.12"))
    win.ring.setChecked(False)
    win.name_edit.setText("Renamed")
    m = win.map_tab
    m.canvas.set_chunks([(0, 0), (1, 0)], True, 0)
    m.scope_sel.setChecked(True)
    m.use_spawn.setChecked(True)
    m.sx.setValue(7)
    m.regen_end.setChecked(True)
    win.tabs.setCurrentWidget(m)
    before = win._target()

    it = win.switch_language("it")
    try:
        assert it is not None and i18n.language() == "it" and not win.isVisible()
        assert [it.tabs.tabText(i) for i in range(it.tabs.count())] == ["Conversione", "Mappa e chunk", "Giocatori",
                                                                        "Gestione mondo"]
        assert _wait(app, lambda: it._src_kind == "lce" and it.map_tab._meta is not None and it._pending_state is None)
        app.processEvents()
        after = it._target()
        assert (after.family, after.java_mode, after.java_version_limit, after.ring, after.world_name, after.regen) == \
            (before.family, before.java_mode, before.java_version_limit, before.ring, before.world_name, before.regen)
        assert after.selection.chunks == before.selection.chunks == {0: {(0, 0), (1, 0)}}
        assert after.selection.spawn[0] == 7
        assert it.tabs.currentWidget() is it.map_tab
        assert "Solo i chunk selezionati (2)" in it.scope_label.text()
        assert [b.text() for b in it.lang_group.buttons() if b.isChecked()] == ["IT"]
        en = it.switch_language("en")
        assert en is not None and i18n.language() == "en" and en.tabs.tabText(0) == "Conversion"
        assert _wait(app, lambda: en._src_kind == "lce" and en._pending_state is None)
        en.close()
    finally:
        i18n.set_language("en")
        it.close()
        app.processEvents()


def test_inventory_table_shows_the_items_of_a_native_bedrock_player(app, tmp_path):
    from worldbridge.gui.manageui import ManageTab

    from .test_manage import _bedrock_world, _native_bedrock_player

    tab = ManageTab()
    tab.open(_bedrock_world(tmp_path, _native_bedrock_player()))
    tab.docs.setCurrentRow(next(i for i, d in enumerate(tab.world.docs) if d.kind == "player"))
    table = tab.quick_holder.findChildren(QtWidgets.QTableWidget)[-1]
    rows = [tuple(table.item(r, c).text() for c in range(4)) for r in range(table.rowCount())]
    assert [r[2] for r in rows] == ["minecraft:cooked_mutton", "minecraft:oak_planks", "minecraft:netherite_helmet",
                                    "minecraft:shield", "minecraft:elytra"]           # not 68 rows, most empty
    box = next(cb for cb in tab.quick_holder.findChildren(QtWidgets.QCheckBox) if "empty" in cb.text())
    box.setChecked(True)
    table = tab.quick_holder.findChildren(QtWidgets.QTableWidget)[-1]
    assert table.rowCount() == 5 + 63
    tab.close()


def test_source_world_edit_answers_in_the_interface_thread(app, tmp_path, monkeypatch):
    """The dappled forest painted on a Bedrock 26.50 world from "Edit the source world": the message
    and the map's reload ran in the worker's thread and crashed the program."""
    from PySide6.QtCore import QThread
    from PySide6.QtWidgets import QMessageBox

    from worldbridge import biomes as bio
    from worldbridge.convert import TargetSpec, convert
    from worldbridge.gui.mapwidget import MapTab

    from .test_chunkedit import _java

    hub, _src = _java(tmp_path, "hub")
    world = str(tmp_path / "bedrock")
    convert(hub, world, TargetSpec(family="bedrock", version=(26, 50, 0), ring=False, blend=False))
    shown = []
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: shown.append(QThread.currentThread() is app.thread())))
    t = MapTab()
    t.show()
    try:
        t._confirm_edit = lambda q: True
        t.set_source(world)
        assert _wait(app, lambda: t._meta is not None)
        dim = t.dim_box.currentData()
        t.canvas.selection.setdefault(dim, set()).update({(0, 0), (1, 1)})
        _pick(t.world_biome_box, bio.parse("dappled_forest"))
        t._edit_paint()
        assert _wait(app, lambda: shown, 120)
        assert shown == [True]
        assert _wait(app, lambda: t._meta is not None and t._path == world)     # the map read again
    finally:
        t.shutdown()
        t.close()
        app.processEvents()


# ============================================================ review fixes (stale answers, closing, unsaved changes)


def _java_world(tmp_path, name):
    from .test_chunkedit import _java

    return _java(tmp_path, name)[0]


def _lce_world(tmp_path, name="lce"):
    src = SyntheticWorld(radius=1, dims=(0,))
    w = LCEWriter(str(tmp_path / name), LCEWriteOptions(platform="win64"), Progress())
    for cx, cz in src.chunk_coords(0):
        w.add_chunk(0, src.read_chunk(0, cx, cz))
    w.finish(src.info)
    return str(tmp_path / name)


def _map_tab(app):
    from worldbridge.gui.mapwidget import MapTab

    t = MapTab()
    t.show()
    return t


def _close_map_tab(app, t):
    t.shutdown()
    t.close()
    app.processEvents()


def test_a_trim_scan_of_another_world_is_dropped(app, tmp_path, monkeypatch):
    """The scan of world A finishing after world B was opened was applied to B (and "Apply to the world"
    then deleted B's chunks): the scan is cancelled when the world changes and its answer ignored."""
    import threading

    from PySide6.QtCore import QObject, Signal

    from worldbridge.gui import mapwidget

    release = threading.Event()
    made = []

    class SlowScan(QObject):
        progress = Signal(float, str)
        done = Signal(object)
        failed = Signal(str)

        def __init__(self, path):
            super().__init__()
            self.path = path
            self.prog = Progress()
            made.append(self)

        def run(self):
            release.wait(30)
            self.done.emit(object())             # ignores the cancel: the worst case

    monkeypatch.setattr(mapwidget, "ScanWorker", SlowScan)
    applied = []
    a, b = _java_world(tmp_path, "a"), _java_world(tmp_path, "b")
    t = _map_tab(app)
    try:
        monkeypatch.setattr(t, "_apply_trim", lambda ask: applied.append(ask))
        t.set_source(a)
        assert _wait(app, lambda: t._meta is not None)
        t.run_trim()
        assert not t.trim_btn.isEnabled()                        # no second scan, no trim while one runs
        assert all(not b_.isEnabled() for b_ in t._edit_buttons)
        t.set_source(b)
        assert made[0].prog.cancelled                            # the scan of A was told to stop
        assert t.trim_btn.isEnabled()                            # B can be scanned at once
        release.set()
        end = time.time() + 1.5
        while time.time() < end:
            app.processEvents()
            time.sleep(0.02)
        assert t._trim_scan is None and applied == []            # nothing of A reached B
        assert t.trim_btn.isEnabled() and all(b_.isEnabled() for b_ in t._edit_buttons)
    finally:
        release.set()
        _close_map_tab(app, t)


def test_a_new_world_starts_without_the_choices_of_the_previous_one(app, tmp_path):
    a, b = _java_world(tmp_path, "a"), _java_world(tmp_path, "b")
    t = _map_tab(app)
    try:
        t.set_source(a)
        assert _wait(app, lambda: t._meta is not None)
        t.painted = {0: {(1, 1): 37, (0, 0): 37}}
        t._update_biome_status()
        t.regen_nether.setChecked(True)
        t.regen_end.setChecked(True)
        t.move_sel.setChecked(True)
        t.set_source(b)
        assert t.painted == {} and t.biome_overrides() == {} and not t.biome_status.isVisible()
        assert t.regen_dims() == () and not t.move_sel.isChecked() and t.move_target() is None
        assert t.summary() == "The whole world"
    finally:
        _close_map_tab(app, t)


def test_the_source_is_analysed_once_and_never_after_closing(win, app, tmp_path):
    """Closing the window made the box lose the focus (editingFinished) and started an analysis whose thread
    outlived the window (abort of the whole program); the same signal re-analysed a world at every focus-out."""
    world = _java_world(tmp_path, "w")
    win.src_edit.setText(world)
    win._on_source_changed(force=True)
    assert _wait(app, lambda: win._src_kind == "java_numeric")
    seq = win._detect_seq
    win._on_source_changed()                                     # focus-out: the same path
    assert win._detect_seq == seq
    win._on_source_changed(force=True)                           # picked again on purpose
    assert win._detect_seq == seq + 1
    assert _wait(app, lambda: not win._threads)
    win.src_edit.setText(str(tmp_path / "other"))
    win.close()
    seq = win._detect_seq
    win._on_source_changed()                                     # the focus-out caused by the close
    win._on_source_changed(force=True)
    assert win._detect_seq == seq and not win._threads


def test_a_slower_older_analysis_does_not_overwrite_a_newer_one(win, app, tmp_path, monkeypatch):
    import threading

    from worldbridge.gui import app as gui_app

    slow_path = _lce_world(tmp_path)
    fast_path = _java_world(tmp_path, "java")
    gate = threading.Event()

    class Gated(gui_app.DetectWorker):
        def run(self):
            if self.path == slow_path:
                gate.wait(30)
            super().run()

    monkeypatch.setattr(gui_app, "DetectWorker", Gated)
    try:
        win.src_edit.setText(slow_path)
        win._on_source_changed(force=True)
        win.src_edit.setText(fast_path)
        win._on_source_changed(force=True)
        assert _wait(app, lambda: win._src_kind == "java_numeric")
        gate.set()
        assert _wait(app, lambda: not win._threads)
        assert win._src_kind == "java_numeric" and win.map_tab._path == fast_path     # not the LCE world's answer
    finally:
        gate.set()


def test_closing_during_a_conversion_waits_for_the_cancel(win, app):
    """Closing at once left Amulet's processes and the .worldbridge_* folders behind: the window stays until
    the conversion has stopped (it is cancelled), then closes."""
    cancelled = []

    class Fake:
        def cancel(self):
            cancelled.append(True)

    win._worker = Fake()
    win.close()
    app.processEvents()
    assert win.isVisible() and cancelled == [True]
    win.close()                                                  # asked again: still one cancel
    assert win.isVisible() and cancelled == [True]
    win._on_finished(False, "Conversion cancelled.", [])
    app.processEvents()
    assert not win.isVisible() and win._worker is None


def test_world_management_asks_before_discarding_changes(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from worldbridge.gui.manageui import ManageTab

    a, b = _java_world(tmp_path, "a"), _java_world(tmp_path, "b")
    answers = []
    asked = []

    def fake_exec(self):
        asked.append(self.text())
        return answers.pop(0)

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    tab = ManageTab()
    try:
        tab.open(a)
        assert tab.world is not None and tab.maybe_discard() and asked == []      # nothing to lose
        tab.world.docs[0].dirty = True
        answers[:] = [QMessageBox.Cancel]
        assert tab.open(b) is False
        assert os.path.abspath(tab.world.path) == os.path.abspath(a) and tab.has_changes()
        tab.path_edit.setText(b)
        answers[:] = [QMessageBox.Cancel]
        tab._typed_path()                                        # Enter in the box
        assert os.path.abspath(tab.world.path) == os.path.abspath(a) and tab.path_edit.text() == tab.world.path
        answers[:] = [QMessageBox.Cancel]
        tab._reload()
        assert tab.has_changes()
        answers[:] = [QMessageBox.Save]
        assert tab.open(b) and not tab.has_changes()             # saved first, then the other world
        assert os.path.exists(os.path.join(a, "level.dat.wb-backup"))
        assert os.path.abspath(tab.world.path) == os.path.abspath(b)
        tab.world.docs[0].dirty = True
        answers[:] = [QMessageBox.Discard]
        tab._reload()
        assert not tab.has_changes() and len(asked) == 5 and answers == []
    finally:
        tab.close()


def test_closing_the_window_asks_about_unsaved_world_changes(win, app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    win.manage_tab.open(_java_world(tmp_path, "w"))
    win.manage_tab.world.docs[0].dirty = True
    answers = [QMessageBox.Cancel, QMessageBox.Discard]
    monkeypatch.setattr(QMessageBox, "exec", lambda self: answers.pop(0))
    win.close()
    assert win.isVisible() and win.manage_tab.has_changes()
    win.close()
    assert not win.isVisible() and answers == []


def test_the_failure_banner_is_short_and_names_the_error(monkeypatch):
    from worldbridge.gui import app as gui_app
    from worldbridge.model import ConversionError

    assert gui_app._failure_text(KeyError("foo")) == "KeyError: 'foo'"
    assert gui_app._failure_text(ConversionError("Nothing to convert.")) == "Nothing to convert."
    long = gui_app._failure_text(ConversionError("x" * 60000))
    assert len(long) < 330 and long.endswith("… (see the log)")
    monkeypatch.setattr(gui_app, "convert", lambda *a, **k: (_ for _ in ()).throw(ValueError("bad " * 500)))
    w = gui_app.ConvertWorker("s", "o", None)
    got = []
    w.finished.connect(lambda ok, msg, warns: got.append((ok, msg)))
    w.run()
    assert got and got[0][0] is False and got[0][1].startswith("ValueError: bad") and len(got[0][1]) < 330


def test_trimmed_copy_of_a_world_opened_as_a_file(app, tmp_path, monkeypatch):
    """"Save trimmed world" on a world opened through its level.dat copied the file's path: Not a directory."""
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    world = _java_world(tmp_path, "w")
    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(dest)))
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a[2])))
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: shown.append("FAILED " + a[2])))
    t = _map_tab(app)
    try:
        t.set_source(os.path.join(world, "level.dat"))
        assert _wait(app, lambda: t._meta is not None)
        t._save_trimmed({0: {(0, 0)}})
        assert _wait(app, lambda: shown, 60)
        assert not shown[0].startswith("FAILED"), shown
        assert sorted(os.listdir(dest)) == ["w_trim"] and os.path.isfile(dest / "w_trim" / "level.dat")
    finally:
        _close_map_tab(app, t)


def test_trim_settings_do_not_touch_the_user_settings_when_not_remembered(app, monkeypatch):
    from worldbridge.gui import trimui
    from worldbridge.gui.app import MainWindow

    def forbidden():
        raise AssertionError("the real user settings were used")

    monkeypatch.setattr(trimui, "_settings", forbidden)
    w = MainWindow(remember=False)
    try:
        ts = w.map_tab.trim_settings
        ts.amount.setValue(ts.amount.value() + 5)               # would be written
        ts.heat.setChecked(True)
        assert ts.show_heat() and not ts._remember
    finally:
        w.close()
    s = trimui.TrimSettings(remember=False)
    s.ring.setValue(9)
    assert s.options().ring == 9
    s.close()
