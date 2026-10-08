"""The map tab and the world: switching world while a copy or an edit runs, signals of an old world's loader,
phantom chunk selection, CSV import (offscreen, synthetic worlds)."""
import os
import threading
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QEvent, QObject, QPoint, QPointF, Qt, Signal  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from worldbridge.model import Progress  # noqa: E402

from .test_gui import _close_map_tab, _java_world, _map_tab, _wait  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _pump(app, sec=0.5):
    end = time.time() + sec
    while time.time() < end:
        app.processEvents()
        time.sleep(0.02)


def _loaded(app, t, dim=0):
    t.ensure_rendered()
    assert _wait(app, lambda: dim in t._loaded_dims)


class _SlowEdit(QObject):
    """An edit that takes its time (and, like the real one, is not interrupted by a world switch)."""

    progress = Signal(float, str)
    done = Signal(object)
    failed = Signal(str)
    interruptible = False

    def __init__(self, release):
        super().__init__()
        self.prog = Progress()
        self.release = release
        self.started = threading.Event()

    def run(self):
        self.started.set()
        while not self.release.is_set() and not self.prog.cancelled:
            time.sleep(0.01)
        self.done.emit(None)


# ---------------------------------------------------------------- 1. workers and the world switch


def test_switching_world_cancels_the_copy_and_removes_the_partial_folder(app, tmp_path, monkeypatch):
    from worldbridge import trim

    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(dest)))
    boxes = []
    for name in ("information", "critical", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: boxes.append(a[2])))
    started = threading.Event()

    def slow_copy(src, dst, progress, ignore=None):
        os.makedirs(dst, exist_ok=True)
        with open(os.path.join(dst, "partial.bin"), "wb") as f:
            f.write(b"x")
        started.set()
        for _ in range(3000):
            progress.check()                                   # raises ConversionCancelled
            time.sleep(0.01)

    monkeypatch.setattr(trim, "copy_tree", slow_copy)
    a, b = _java_world(tmp_path, "a"), _java_world(tmp_path, "b")
    t = _map_tab(app)
    try:
        t.set_source(a)
        assert _wait(app, lambda: t._meta is not None)
        t._save_trimmed({0: {(0, 0)}})
        assert _wait(app, lambda: started.is_set())
        assert t.busy() and t.cancel_btn.isVisibleTo(t) and not t.trim_btn.isEnabled()
        assert (dest / "a_trim" / "partial.bin").exists()
        assert t.set_source(b) is True
        assert not (dest / "a_trim").exists() and os.listdir(dest) == []    # the partial folder is gone
        assert not t.busy() and t.trim_btn.isEnabled() and not t.cancel_btn.isVisible()
        _pump(app)
        assert boxes == []                                     # no "Saving failed" for a cancel
        assert t._path == b
    finally:
        _close_map_tab(app, t)


def test_the_cancel_button_stops_the_copy_without_an_error_box(app, tmp_path, monkeypatch):
    from worldbridge import trim

    dest = tmp_path / "dest"
    dest.mkdir()
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: str(dest)))
    boxes = []
    for name in ("information", "critical", "warning"):
        monkeypatch.setattr(QMessageBox, name, staticmethod(lambda *a, **k: boxes.append(a[2])))
    started = threading.Event()

    def slow_copy(src, dst, progress, ignore=None):
        os.makedirs(dst, exist_ok=True)
        started.set()
        for _ in range(3000):
            progress.check()
            time.sleep(0.01)

    monkeypatch.setattr(trim, "copy_tree", slow_copy)
    t = _map_tab(app)
    try:
        t.set_source(_java_world(tmp_path, "a"))
        assert _wait(app, lambda: t._meta is not None)
        t._save_trimmed({0: {(0, 0)}})
        assert _wait(app, lambda: started.is_set())
        t.cancel_btn.click()
        assert _wait(app, lambda: not t.busy())
        assert os.listdir(dest) == [] and boxes == []
        assert t.status.text() == "Operation cancelled."
        assert t.trim_btn.isEnabled()
    finally:
        _close_map_tab(app, t)


def test_a_second_edit_is_refused_and_the_world_is_not_switched_during_an_edit(app, tmp_path, monkeypatch):
    from worldbridge.gui import mapwidget

    release = threading.Event()
    a, b = _java_world(tmp_path, "a"), _java_world(tmp_path, "b")
    t = _map_tab(app)
    try:
        t.set_source(a)
        assert _wait(app, lambda: t._meta is not None)
        shown = []
        monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a_, **k: shown.append(a_[2])))
        first, second = _SlowEdit(release), _SlowEdit(release)
        assert t._run_worker(first, lambda r: None, lambda m: None) is True
        assert _wait(app, lambda: first.started.is_set())
        assert t._run_worker(second, lambda r: None, lambda m: None) is False      # no second edit / scan / copy
        t.run_trim()
        assert t._active == [first] and not second.started.is_set()
        assert all(not b_.isEnabled() for b_ in t._edit_buttons) and not t.trim_btn.isEnabled()
        assert not t.cancel_btn.isVisible()                                         # an edit has no cancel
        assert t.can_switch(b) is False and t.set_source(b) is False                # the map stays on world A
        assert t._path == a and not first.prog.cancelled
        release.set()
        assert _wait(app, lambda: not t.busy())
        assert t.set_source(b) is True and t._path == b
        assert mapwidget.EditWorker.interruptible is False
    finally:
        release.set()
        _close_map_tab(app, t)


def test_closing_cancels_the_edit_and_waits_for_it(app, tmp_path):
    release = threading.Event()
    t = _map_tab(app)
    try:
        t.set_source(_java_world(tmp_path, "a"))
        assert _wait(app, lambda: t._meta is not None)
        ed = _SlowEdit(release)
        shown = []
        assert t._run_worker(ed, lambda r: shown.append(r), lambda m: shown.append(m))
        assert _wait(app, lambda: ed.started.is_set())
        t.shutdown()                                           # cancels (between two regions) and waits
        assert ed.prog.cancelled and not t._workers and not t.busy()
        _pump(app, 0.3)
        assert shown == []                                     # no answer, no box, once the window closes
    finally:
        release.set()
        t.close()


def test_the_map_edits_are_disabled_during_a_conversion(app, tmp_path):
    t = _map_tab(app)
    try:
        t.set_source(_java_world(tmp_path, "a"))
        assert _wait(app, lambda: t._meta is not None)
        assert t.trim_btn.isEnabled() and all(b.isEnabled() for b in t._edit_buttons)
        t.set_conversion_running(True)
        assert not t.trim_btn.isEnabled() and all(not b.isEnabled() for b in t._edit_buttons)
        t.run_trim()
        assert not t._active                                   # nothing started
        assert t._run_worker(_SlowEdit(threading.Event()), None, None) is False
        t.set_conversion_running(False)
        assert t.trim_btn.isEnabled() and all(b.isEnabled() for b in t._edit_buttons)
    finally:
        _close_map_tab(app, t)


def test_the_window_refuses_a_world_change_during_a_conversion_or_an_edit(app, tmp_path):
    from worldbridge.gui.app import MainWindow

    release = threading.Event()
    a, b = _java_world(tmp_path, "a"), _java_world(tmp_path, "b")
    w = MainWindow(remember=False)
    w.show()
    try:
        w.src_edit.setText(a)
        w._on_source_changed(force=True)
        assert _wait(app, lambda: w.map_tab._meta is not None and w.map_tab.path == a)
        # an edit runs: the box goes back to the world being edited, the map keeps it
        ed = _SlowEdit(release)
        assert w.map_tab._run_worker(ed, lambda r: None, lambda m: None)
        assert _wait(app, lambda: ed.started.is_set())
        w.src_edit.setText(b)
        w._on_source_changed(force=True)
        assert w.src_edit.text() == a and w.map_tab.path == a
        w._start()                                             # no conversion over a world being edited
        assert w._worker is None
        release.set()
        assert _wait(app, lambda: not w.map_tab.busy())
        # a conversion runs: same
        w._worker = object()
        w.src_edit.setText(b)
        w._on_source_changed(force=True)
        assert w.src_edit.text() == a and w.map_tab.path == a
        w._worker = None
        w.src_edit.setText(b)
        w._on_source_changed(force=True)
        assert _wait(app, lambda: w.map_tab.path == b)
    finally:
        release.set()
        w._worker = None
        w.close()
        app.processEvents()


# ---------------------------------------------------------------- 2. signals of an old loader


def test_the_signals_of_the_previous_worlds_loader_are_ignored(app, tmp_path):
    a, b = _java_world(tmp_path, "a"), _java_world(tmp_path, "b")
    t = _map_tab(app)
    try:
        t.set_source(a)
        old = t._loader
        assert _wait(app, lambda: t._meta is not None)
        t.set_source(b)
        assert t._loader is not old
        assert _wait(app, lambda: t._meta is not None)
        meta = t._meta
        old.meta.emit({"dims": [7], "spawn": (0, 0, 0), "players": [], "counts": {7: 1}, "description": "STALE",
                       "kind": "x"})
        old.batch.emit(7, [])
        old.progress.emit(7, 1, 1)
        old.dim_done.emit(7)
        _pump(app)
        assert t._meta is meta and t._meta["description"] != "STALE"
        assert t.dim_box.findData(7) < 0 and 7 not in t._loaded_dims and 7 not in t.canvas.present
        assert t.status.text() != "STALE"
    finally:
        _close_map_tab(app, t)


def test_a_loader_created_during_a_conversion_starts_paused(app, tmp_path):
    t = _map_tab(app)
    try:
        t.set_conversion_running(True)
        t.set_source(_java_world(tmp_path, "a"))
        assert t._loader.paused is True
        t.set_conversion_running(False)
        assert t._loader.paused is False
    finally:
        _close_map_tab(app, t)


# ---------------------------------------------------------------- 3. phantom chunks


def _canvas():
    from worldbridge.gui.mapwidget import MapCanvas

    c = MapCanvas()
    c.resize(600, 400)
    c.show()
    QtWidgets.QApplication.processEvents()
    return c


def _click(c, chunk, shift=False, right=False):
    """A click in the middle of ``chunk`` (the view is centred on the origin, 4 px per block)."""
    p = c.to_screen(chunk[0] * 16 + 8, chunk[1] * 16 + 8).toPoint()
    button = Qt.RightButton if right else Qt.LeftButton
    mods = Qt.ShiftModifier if shift else Qt.NoModifier

    def ev(t):
        return QMouseEvent(t, QPointF(p), QPointF(p), button, button if t != QEvent.MouseButtonRelease else Qt.NoButton,
                           mods)

    c.mousePressEvent(ev(QEvent.MouseButtonPress))
    c.mouseReleaseEvent(ev(QEvent.MouseButtonRelease))


def test_clicks_on_a_dimension_without_chunks_select_nothing(app):
    c = _canvas()
    try:
        c.scale = 4.0
        c.center_on(0, 0)
        _click(c, (3, 3))
        _click(c, (3, 3), shift=True)                           # used to select the whole 32 x 32 region
        assert not c.selected()
        c.present[0] = set()                                    # a dimension that is empty
        _click(c, (3, 3), shift=True)
        assert not c.selected()
    finally:
        c.close()


def test_clicks_on_a_loaded_dimension_select_only_the_chunks_that_exist(app):
    c = _canvas()
    try:
        c.scale = 4.0
        c.center_on(0, 0)
        c.present[0] = {(x, z) for x in range(0, 4) for z in range(0, 4)}
        _click(c, (1, 1))
        assert c.selected() == {(1, 1)}
        _click(c, (9, 9))                                       # nothing there
        assert c.selected() == {(1, 1)}
        _click(c, (2, 2), shift=True)                           # the region: only its 16 chunks
        assert c.selected() == c.present[0]
        _click(c, (2, 2), shift=True, right=True)
        assert not c.selected()
        assert c.set_chunks([(0, 0), (50, 50)], True) == 1      # the API refuses them too
        assert c.selected() == {(0, 0)}
    finally:
        c.close()


def test_csv_import_selects_only_existing_chunks_and_reports_the_rest(app, tmp_path, monkeypatch):
    t = _map_tab(app)
    try:
        t.set_source(_java_world(tmp_path, "a"))
        assert _wait(app, lambda: t._meta is not None)
        csv = tmp_path / "sel.csv"
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(csv), "")))
        _loaded(app, t)
        have = sorted(t.canvas.present[0])
        assert have
        loaded = set(t._loaded_dims)
        t._loaded_dims.clear()                                  # the dimension still loading: nothing is imported
        csv.write_text(f"0;0;{have[0][0]};{have[0][1]}\n")
        t._import()
        assert not t.canvas.selected(0) and "still loading" in t.status.text()
        t._loaded_dims.update(loaded)
        c0 = have[0]
        csv.write_text(f"{c0[0] >> 5};{c0[1] >> 5};{c0[0]};{c0[1]}\n0;0;500;500\n0;0;-400;300\nnot a line\n")
        t._import()
        assert t.canvas.selected(0) == {c0}
        assert "1 chunks selected" in t.status.text() and "2 left out" in t.status.text()
        assert t.scope_sel.isChecked()
        # a region line (1024 chunks): the existing ones are taken, the others counted
        csv.write_text("0;0\n")
        t.canvas.clear_selection()
        n_in_region = len([c for c in t.canvas.present[0] if c[0] >> 5 == 0 and c[1] >> 5 == 0])
        t._import()
        assert len(t.canvas.selected(0)) == n_in_region
        assert f"{1024 - n_in_region} left out" in t.status.text()
    finally:
        _close_map_tab(app, t)
