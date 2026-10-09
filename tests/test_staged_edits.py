"""World management, "Apply only to the converted world": the edits of a world's documents are written into a
working copy that the conversion reads instead of the source, so the source stays byte for byte as it was (no
*.wb-backup either) and the converted world, whatever its format, carries the edits; the working folder is gone
when the conversion ends, whatever way it ends."""
import hashlib
import os
import struct

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from worldbridge import nbt  # noqa: E402
from worldbridge.convert import TargetSpec, convert  # noqa: E402
from worldbridge.gui import app as gui_app  # noqa: E402
from worldbridge.java.numeric import JavaNumericWriter, JavaWriteOptions  # noqa: E402
from worldbridge.lce.world import LCEWriteOptions, LCEWriter  # noqa: E402
from worldbridge.manage import build_staged_copy, capture_edits, open_world  # noqa: E402
from worldbridge.model import ConversionCancelled, Progress  # noqa: E402

from .helpers import SyntheticWorld  # noqa: E402


# ------------------------------------------------------------------ worlds and helpers

def _java(tmp_path):
    src = SyntheticWorld(radius=1)
    out = str(tmp_path / "src" / "Java World")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    return out


def _lce(tmp_path):
    src = SyntheticWorld(radius=1)
    out = str(tmp_path / "src" / "LCE World")
    wr = LCEWriter(out, LCEWriteOptions(platform="win64", world_size=54), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    return out


def _bedrock(tmp_path):
    out = str(tmp_path / "src" / "Bedrock World")
    convert(_lce(tmp_path), out, TargetSpec(family="bedrock", ring=False))
    return out


def _tree(path):
    """Every file under ``path`` (or the file itself): bytes, size and modification time."""
    if os.path.isfile(path):
        files = [(os.path.basename(path), path)]
        base = os.path.dirname(path)
    else:
        base = path
        files = [(os.path.relpath(os.path.join(r, n), base), os.path.join(r, n))
                 for r, _d, names in os.walk(path) for n in names]
    out = {}
    for rel, p in files:
        with open(p, "rb") as f:
            out[rel] = (hashlib.sha1(f.read()).hexdigest(), os.stat(p).st_size, os.stat(p).st_mtime_ns)
    return out


def _field(w, label, doc=None):
    fields = w.player_fields(doc) if doc is not None else w.quick_fields()
    return next(f for f in fields if f.label == label)


def _edit(w, name):
    """A quick setting (name, game mode) and a player field (X position) changed."""
    w.set(_field(w, "Name"), name)
    w.set(_field(w, "Game mode"), 2)
    player = next(d for d in w.docs if d.kind == "player")
    w.set(_field(w, "Position X", player), 101.5)


def _carries(path, name):
    w = open_world(path)
    assert w.get(_field(w, "Name")) == name
    return w


def _run_worker(src, out, target, edits):
    got = []
    worker = gui_app.ConvertWorker(src, out, target, edits)
    worker.finished.connect(lambda ok, msg, warns: got.append((ok, msg, warns)))
    worker.run()
    return got[0]


def _convert_staged(src_path, edits, tmp_path, targets):
    """Converts the staged source to each target; the source world and the folders around it are checked."""
    parent = os.path.dirname(src_path)
    listing = sorted(os.listdir(parent))
    before = _tree(src_path)
    outs = []
    for i, (family, kw) in enumerate(targets):
        out = str(tmp_path / f"out{i}")
        ok, msg, _w = _run_worker(src_path, out, TargetSpec(family=family, ring=False, **kw), edits)
        assert ok, msg
        assert _tree(src_path) == before                           # a) the source: same bytes, sizes and mtimes
        assert sorted(os.listdir(parent)) == listing               # d) no working folder left, no *.wb-backup
        outs.append(out)
    assert not [n for r, _d, fs in os.walk(src_path) for n in fs if n.endswith(".wb-backup")]    # b)
    return outs


# ------------------------------------------------------------------ the three families

def test_java_world(tmp_path):
    src = _java(tmp_path)
    w = open_world(src)
    before = _tree(src)
    _edit(w, "Edited Java")
    edits = capture_edits(w, src)
    assert edits.count == 1 and list(edits.roots) == ["level.dat"]           # the single player is inside level.dat
    outs = _convert_staged(src, edits, tmp_path, [("java", dict(java_mode="numeric", java_version_limit="1.12")),
                                                  ("lce", {})])
    w1 = _carries(outs[0], "Edited Java")                                    # the same format
    assert w1.get(_field(w1, "Game mode")) == 2
    assert w1.get(_field(w1, "Position X", next(d for d in w1.docs if d.kind == "player"))) == 101.5
    w2 = _carries(outs[1], "Edited Java")                                    # another format
    assert w2.get(_field(w2, "Game mode")) == 2
    assert w2.get(_field(w2, "Position X", next(d for d in w2.docs if d.kind == "player"))) == 101.5
    assert _tree(src) == before


def test_bedrock_world(tmp_path):
    src = _bedrock(tmp_path)
    before = _tree(src)
    w = open_world(src)
    assert _tree(src) == before                                              # reading the players changes nothing
    assert w.kind == "bedrock"
    _edit(w, "Edited Bedrock")
    edits = capture_edits(w, src)
    assert sorted(edits.roots) == ["level.dat", "~local_player"]            # the player lives in the database
    outs = _convert_staged(src, edits, tmp_path, [("bedrock", {}), ("lce", {})])
    w1 = _carries(outs[0], "Edited Bedrock")
    assert w1.get(_field(w1, "Game mode")) == 2
    assert w1.get(_field(w1, "Position X", next(d for d in w1.docs if d.kind == "player"))) == 101.5
    w2 = _carries(outs[1], "Edited Bedrock")
    assert w2.get(_field(w2, "Position X", next(d for d in w2.docs if d.kind == "player"))) == 101.5
    assert _tree(src) == before


@pytest.mark.parametrize("as_file", [False, True])
def test_lce_world(tmp_path, as_file):
    folder = _lce(tmp_path)
    src = os.path.join(folder, "saveData.ms") if as_file else folder
    before = _tree(folder)
    w = open_world(src)
    assert w.kind == "lce"
    _edit(w, "Edited LCE")
    edits = capture_edits(w, src)
    assert sorted(edits.roots) == ["level.dat", "players/host.dat"]
    outs = _convert_staged(src, edits, tmp_path, [("lce", {}), ("bedrock", {})])
    for out in outs:
        w1 = _carries(out, "Edited LCE")
        assert w1.get(_field(w1, "Game mode")) == 2
        assert w1.get(_field(w1, "Position X", next(d for d in w1.docs if d.kind == "player"))) == 101.5
    assert _tree(folder) == before


# ------------------------------------------------------------------ the working copy

def test_the_working_copy_shares_the_big_files_and_copies_the_documents(tmp_path):
    src = _java(tmp_path)
    w = open_world(src)
    _edit(w, "Edited")
    copy = build_staged_copy(capture_edits(w, src))
    try:
        assert os.path.basename(copy.path) == "Java World"                  # the name every derived name comes from
        assert os.path.dirname(copy.root) == os.path.dirname(src) and os.path.basename(copy.root).startswith(
            ".worldbridge_edit_")
        region = os.path.join("region", "r.0.0.mca")
        assert os.path.samefile(os.path.join(src, region), os.path.join(copy.path, region))       # hard link
        assert not os.path.samefile(os.path.join(src, "level.dat"), os.path.join(copy.path, "level.dat"))
        assert _carries(copy.path, "Edited")
        assert _carries(src, "Test World")
    finally:
        copy.cleanup()
    assert not os.path.exists(copy.root)


def test_a_player_file_is_staged_too(tmp_path):
    src = _java(tmp_path)
    os.makedirs(os.path.join(src, "playerdata"))
    pf = os.path.join(src, "playerdata", "abc.dat")
    root = nbt.CompoundTag({"Health": nbt.FloatTag(20.0), "XpLevel": nbt.IntTag(1)})
    with open(pf, "wb") as f:
        f.write(nbt.dump(root, "", compressed=True))
    before = _tree(src)
    w = open_world(src)
    doc = w.doc(os.path.join("playerdata", "abc.dat"))
    w.set(_field(w, "Experience level", doc), 30)
    edits = capture_edits(w, src)
    copy = build_staged_copy(edits)
    try:
        staged = open_world(copy.path).doc(os.path.join("playerdata", "abc.dat"))
        assert int(nbt.get(staged.root, "XpLevel")) == 30
    finally:
        copy.cleanup()
    assert _tree(src) == before


def test_edits_accumulate_and_do_not_follow_later_changes(tmp_path):
    src = _java(tmp_path)
    w = open_world(src)
    w.set(_field(w, "Name"), "First")
    edits = capture_edits(w, src)
    for d in w.docs:
        d.dirty = False
    w.set(_field(w, "Name"), "Second")                                       # later, not applied yet
    copy = build_staged_copy(edits)
    try:
        assert _carries(copy.path, "First")
    finally:
        copy.cleanup()
    more = capture_edits(w, src, edits)
    assert more.count == 1 and edits.count == 1                              # same document, not twice


def test_without_write_access_next_to_the_world_the_temporary_folder_is_used(tmp_path, monkeypatch):
    import tempfile as tf

    from worldbridge import manage

    src = _java(tmp_path)
    w = open_world(src)
    w.set(_field(w, "Name"), "Elsewhere")
    real = tf.mkdtemp
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tf, "tempdir", str(tmp_path))

    def mkdtemp(prefix=None, dir=None, **kw):
        if dir is not None:
            raise PermissionError("read-only")
        return real(prefix=prefix, **kw)

    monkeypatch.setattr(manage.tempfile, "mkdtemp", mkdtemp)
    before = _tree(src)
    copy = build_staged_copy(capture_edits(w, src))
    try:
        assert os.path.dirname(copy.root) == str(tmp_path) and _carries(copy.path, "Elsewhere")
    finally:
        copy.cleanup()
    assert _tree(src) == before and not os.path.exists(copy.root)


def test_cancelling_while_the_copy_is_prepared_leaves_nothing(tmp_path):
    src = _java(tmp_path)
    w = open_world(src)
    w.set(_field(w, "Name"), "x")
    edits = capture_edits(w, src)
    listing = sorted(os.listdir(os.path.dirname(src)))
    progress = Progress()
    progress.cancel()
    with pytest.raises(ConversionCancelled):
        build_staged_copy(edits, progress)
    assert sorted(os.listdir(os.path.dirname(src))) == listing


def test_the_working_folder_is_removed_when_the_conversion_fails(tmp_path, monkeypatch):
    src = _java(tmp_path)
    w = open_world(src)
    w.set(_field(w, "Name"), "x")
    edits = capture_edits(w, src)
    listing = sorted(os.listdir(os.path.dirname(src)))
    before = _tree(src)
    seen = []

    def boom(path, out, target, progress):
        seen.append(path)
        assert os.path.isdir(path) and os.path.dirname(os.path.dirname(path)) == os.path.dirname(src)
        raise RuntimeError("boom")

    monkeypatch.setattr(gui_app, "convert", boom)
    ok, msg, _w = _run_worker(src, str(tmp_path / "out"), TargetSpec(family="lce"), edits)
    assert not ok and "boom" in msg and seen
    assert not os.path.exists(seen[0])
    assert sorted(os.listdir(os.path.dirname(src))) == listing and _tree(src) == before

    def cancelled(path, out, target, progress):
        raise ConversionCancelled()

    monkeypatch.setattr(gui_app, "convert", cancelled)
    ok, msg, _w = _run_worker(src, str(tmp_path / "out2"), TargetSpec(family="lce"), edits)
    assert not ok and sorted(os.listdir(os.path.dirname(src))) == listing


def test_nothing_is_staged_for_a_read_only_world(tmp_path):
    w = open_world(_java(tmp_path))
    w.read_only = True
    with pytest.raises(PermissionError):
        capture_edits(w, "x")


# ------------------------------------------------------------------ the window

@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def _click_by_text(answer):
    def fake_exec(self):
        next(b for b in self.buttons() if b.text().replace("&", "") == answer).click()
        return 0
    return fake_exec


def test_the_button_and_the_staged_state(app, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from worldbridge.gui.manageui import ManageTab

    a, b = _java(tmp_path), str(tmp_path / "other")
    os.rename(_java(tmp_path / "x"), b)
    tab = ManageTab()
    tab.show()
    source = [a]
    tab.source_getter = lambda: source[0]
    tab.open(a)
    try:
        assert not tab.btn_stage.isEnabled() and tab.btn_stage.text() == "Apply only to the converted world"
        assert "not changed" in tab.btn_stage.toolTip()
        tab._quick_changed(_field(tab.world, "Name"), "Staged")
        assert tab.has_changes() and tab.btn_stage.isEnabled()
        source[0] = b                                                        # not the world to convert any more
        tab._update_buttons()
        assert not tab.btn_stage.isEnabled()
        source[0] = a
        tab._update_buttons()
        before = _tree(a)
        tab.btn_stage.click()
        assert not tab.has_changes() and tab.staged_edits().count == 1       # nothing left unsaved
        assert tab.staged_box.isVisibleTo(tab) and "1" in tab.staged_label.text()
        assert not tab.btn_stage.isEnabled()
        assert _tree(a) == before                                            # the source is not touched by the button
        # another world: asked; Cancel stays, Keep opens it and keeps the edits
        monkeypatch.setattr(QMessageBox, "exec", _click_by_text("Cancel"))
        assert tab.open(b) is False and tab.world.path == a and tab.staged_edits() is not None
        monkeypatch.setattr(QMessageBox, "exec", _click_by_text("Keep them"))
        assert tab.open(b) and tab.world.path == b and tab.staged_edits() is not None
        assert tab.staged_box.isVisibleTo(tab)
        monkeypatch.setattr(QMessageBox, "exec", _click_by_text("Discard them"))
        tab._reload()
        assert tab.staged_edits() is None and not tab.staged_box.isVisibleTo(tab)
        # the Discard button
        tab.open(a)
        tab._quick_changed(_field(tab.world, "Name"), "Again")
        tab.btn_stage.click()
        assert tab.staged_edits() is not None
        tab.btn_discard_staged.click()
        assert tab.staged_edits() is None
    finally:
        tab.discard_staged()
        tab.close()


def test_the_window_converts_from_the_staged_edits_and_drops_them_with_another_source(app, tmp_path, monkeypatch):
    from worldbridge.gui.app import MainWindow

    a = _java(tmp_path)
    other = _lce(tmp_path)
    win = MainWindow(remember=False)
    win.show()
    try:
        win.src_edit.setText(a)
        win.manage_tab.open(a)
        assert not win.manage_tab.btn_stage.isEnabled()
        win.manage_tab._quick_changed(_field(win.manage_tab.world, "Name"), "From the window")
        assert win.manage_tab.btn_stage.isEnabled()
        win.manage_tab.btn_stage.click()
        assert win.staged_hint.isVisibleTo(win) and "1" in win.staged_hint.text()
        started = []

        class Spy(gui_app.ConvertWorker):
            def __init__(self, *args):
                started.append(args)
                super().__init__(*args)

        monkeypatch.setattr(gui_app, "ConvertWorker", Spy)
        monkeypatch.setattr(win, "_run_thread", lambda *a, **k: None)
        win._target = lambda: TargetSpec(family="lce")
        win.out_edit.setText(str(tmp_path / "gui_out"))
        win._start()
        assert started and started[0][3] is win.manage_tab.staged_edits()     # the worker gets the staged edits
        win._on_finished(False, "stopped", [])
        # a different world at the top: the edits are dropped, with a notice
        win.src_edit.setText(other)
        win._on_source_changed(force=True)
        assert win.manage_tab.staged_edits() is None
        assert not win.staged_hint.isVisibleTo(win) and not win.manage_tab.staged_box.isVisibleTo(win.manage_tab)
        assert _wait_idle(app, win)
    finally:
        win.manage_tab.discard_staged()
        win.close()
        app.processEvents()


def _wait_idle(app, win, sec=30):
    import time

    end = time.time() + sec
    while time.time() < end and win._threads:
        app.processEvents()
        time.sleep(0.02)
    return not win._threads
