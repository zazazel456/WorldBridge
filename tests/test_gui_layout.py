"""The "New world" view of the map tab: pasting the selected chunks as groups, moving them around the grid, the live check
that blocks Convert, undo / redo, the layout file, and a real conversion of two groups from the window (offscreen)."""
import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets", exc_type=ImportError)

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QMessageBox  # noqa: E402

from worldbridge import i18n  # noqa: E402
from worldbridge.java.numeric import JavaNumericWorld, JavaNumericWriter, JavaWriteOptions  # noqa: E402
from worldbridge.layout import Group, Layout  # noqa: E402
from worldbridge.model import OVERWORLD, Progress  # noqa: E402

from .helpers import SyntheticWorld  # noqa: E402
from .test_gui import _pick, _wait  # noqa: E402


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


def _world(tmp_path, radius=4):
    src = SyntheticWorld(radius=radius)
    out = str(tmp_path / "src")
    wr = JavaNumericWriter(out, JavaWriteOptions(kind="anvil"), Progress())
    for cx, cz in src.chunk_coords(0):
        wr.add_chunk(0, src.read_chunk(0, cx, cz))
    wr.finish(src.info)
    return out


@pytest.fixture
def gw(win, app, tmp_path):
    """The window with a small Java world (chunks -4..3) opened and drawn, on the map tab."""
    win.src_edit.setText(_world(tmp_path))
    win._on_source_changed(force=True)
    t = win.map_tab
    assert _wait(app, lambda: win._src_kind != "" and t._meta is not None)
    t.ensure_rendered()
    assert _wait(app, lambda: 0 in t._loaded_dims)
    win.tabs.setCurrentWidget(t)
    app.processEvents()
    return win


def _sq(x0, z0, w, h):
    return {(x, z) for x in range(x0, x0 + w) for z in range(z0, z0 + h)}


def _paste(win, chunks):
    t = win.map_tab
    t.canvas.selection[OVERWORLD] = set()
    t.canvas.set_chunks(chunks, True)
    return t.layout_ctl.paste_selection()


def _view(win, app):
    """The new-world canvas, shown, with a known camera: chunk (cx, cz) is the 32 px square at (cx * 32, cz * 32) from the
    centre of the widget."""
    win.map_tab.show_view(1)
    app.processEvents()
    c = win.map_tab.layout_ctl.canvas
    c.center = type(c.center)(0, 0)
    c.scale = 2.0
    c._fitted = True
    c.update()
    return c


def _at(c, cx, cz):
    return c.to_screen(cx * 16 + 8, cz * 16 + 8).toPoint()


def _drag(c, a, b, mods=Qt.NoModifier):
    QTest.mousePress(c, Qt.LeftButton, mods, a)
    QTest.mouseMove(c, QPoint((a.x() + b.x()) // 2, (a.y() + b.y()) // 2))
    QTest.mouseMove(c, b)
    QTest.mouseRelease(c, Qt.LeftButton, mods, b)


def _offsets(win):
    return [g.offset for g in win.map_tab.layout_ctl.model.groups]


# ---------------------------------------------------------------- paste


def test_paste_creates_a_group_with_the_selected_chunks(gw, app):
    t = gw.map_tab
    ctl = t.layout_ctl
    assert t.layout() is None and not t.view_stack.currentIndex()
    gid = _paste(gw, _sq(0, 0, 3, 2))
    g = ctl.model.group(gid)
    assert g.chunks == frozenset(_sq(0, 0, 3, 2)) and g.offset == (0, 0) and g.name == "Group 1" and g.dim == OVERWORLD
    assert t._view_buttons[1].text() == "New world (1)"
    assert [it.text() for it in ctl.list.findItems("", Qt.MatchContains)] == ["Group 1 · 6 chunks · offset 0, 0"]
    # the same chunks again: nothing new (they are in a group already); some new ones: a second group
    assert _paste(gw, _sq(0, 0, 3, 2)) is None and len(ctl.model.groups) == 1
    gid2 = _paste(gw, _sq(0, 0, 4, 3))                       # 12 chunks, 6 of them already in "Group 1"
    assert ctl.model.group(gid2).chunks == frozenset(_sq(0, 0, 4, 3)) - g.chunks
    assert ctl.model.group(gid2).name == "Group 2"
    # nothing selected: said, no group
    t.canvas.selection[OVERWORLD] = set()
    n = len(ctl.model.groups)
    ctl.act_paste.trigger()                                     # Ctrl+V
    assert len(ctl.model.groups) == n and "Select some chunks" in t.status.text()


def test_paste_goes_to_the_nearest_free_place(gw, app):
    ctl = gw.map_tab.layout_ctl
    a = _paste(gw, _sq(0, 0, 2, 1))
    ctl.model.set_offsets({a: (3, 0)})                       # "Group 1" now covers x 3..4
    b = _paste(gw, _sq(3, 0, 2, 1))                          # its own place (x 3..4) is taken
    off = ctl.model.group(b).offset
    assert off != (0, 0) and ctl.model.problems() == []
    near = max(abs(off[0]), abs(off[1]))
    assert near <= 4                                         # right next to it, not far away


def test_a_paste_that_would_leave_the_finite_map_goes_inside_it(app):
    from worldbridge.gui.layoutview import LayoutModel

    m = LayoutModel()
    m.bounds_fn = lambda lay, spawn: {OVERWORLD: (0, 10, 0, 10)}
    m.paste(OVERWORLD, _sq(50, 50, 2, 2))
    assert m.groups[0].offset == (-42, -42) and m.problems() == []        # pushed back inside, at the nearest edge
    m.paste(OVERWORLD, _sq(0, 0, 2, 2))                                   # its own place is free: it stays there
    assert m.groups[1].offset == (0, 0)
    big = _sq(-3, -3, 3, 3)
    m.paste(OVERWORLD, big)
    assert m.problems() == []


# ---------------------------------------------------------------- moving


def test_drag_moves_a_group_by_whole_chunks(gw, app):
    _paste(gw, _sq(0, 0, 2, 2))
    c = _view(gw, app)
    _drag(c, _at(c, 0, 0) + QPoint(3, -4), _at(c, 3, 2) + QPoint(-5, 6))    # 3 chunks right, 2 down (+ a few pixels)
    assert _offsets(gw) == [(3, 2)]
    _drag(c, _at(c, 3, 2), _at(c, 3, 2) + QPoint(10, 10))                    # less than half a chunk: nowhere
    assert _offsets(gw) == [(3, 2)]
    gw.map_tab.layout_ctl.model.undo()                                       # one drag = one undo step
    assert _offsets(gw) == [(0, 0)]


def test_arrow_keys_move_by_one_chunk_and_shift_by_eight(gw, app):
    gid = _paste(gw, _sq(0, 0, 2, 2))
    c = _view(gw, app)
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _at(c, 0, 0))
    assert gw.map_tab.layout_ctl.model.selected == {gid}
    QTest.keyClick(c, Qt.Key_Right)
    QTest.keyClick(c, Qt.Key_Right)
    QTest.keyClick(c, Qt.Key_Up)
    assert _offsets(gw) == [(2, -1)]
    QTest.keyClick(c, Qt.Key_Down, Qt.ShiftModifier)
    QTest.keyClick(c, Qt.Key_Left, Qt.ShiftModifier)
    assert _offsets(gw) == [(-6, 7)]
    QTest.keyClick(c, Qt.Key_Delete)
    assert gw.map_tab.layout_ctl.model.groups == []


def test_several_groups_move_together(gw, app):
    a = _paste(gw, _sq(-4, -4, 2, 2))
    b = _paste(gw, _sq(1, 1, 2, 2))
    c = _view(gw, app)
    QTest.mouseClick(c, Qt.LeftButton, Qt.NoModifier, _at(c, -4, -4))
    QTest.mouseClick(c, Qt.LeftButton, Qt.ControlModifier, _at(c, 1, 1))
    assert gw.map_tab.layout_ctl.model.selected == {a, b}
    _drag(c, _at(c, 1, 1), _at(c, 1, 1) + QPoint(2 * 32, -32))
    assert _offsets(gw) == [(2, -1), (2, -1)]
    QTest.keyClick(c, Qt.Key_Left)
    assert _offsets(gw) == [(1, -1), (1, -1)]
    QTest.mouseClick(c, Qt.LeftButton, Qt.ControlModifier, _at(c, 2, 0))        # Ctrl + click on a selected group: out
    assert gw.map_tab.layout_ctl.model.selected == {a}


def test_back_to_its_place_and_centre_on_the_spawn(gw, app):
    ctl = gw.map_tab.layout_ctl
    a = _paste(gw, _sq(-4, -4, 2, 2))
    b = _paste(gw, _sq(1, 1, 2, 2))
    ctl.model.set_offsets({a: (7, 7), b: (-3, 2)})
    ctl.model.select([a])
    ctl.back_to_place()
    assert ctl.model.group(a).offset == (0, 0) and ctl.model.group(b).offset == (-3, 2)
    # the source's spawn (block 8, 8) is in no group: the new world's spawn is inside the first group, at the chunk
    # nearest to the centre of its place
    spawn = ctl.model.new_spawn_block()
    ctl.model.select([b])
    ctl.centre_on_spawn()
    x0, x1, z0, z1 = ctl.model.placed_bbox(ctl.model.group(b))
    assert ((x0 + x1) // 2, (z0 + z1) // 2) == (spawn[0] >> 4, spawn[1] >> 4)


def test_rename_and_offset_edits_in_the_panel(gw, app):
    ctl = gw.map_tab.layout_ctl
    a = _paste(gw, _sq(0, 0, 2, 2))
    ctl.name_edit.setText("Castle")
    ctl.name_edit.editingFinished.emit()
    assert ctl.model.group(a).name == "Castle"
    ctl.off_x.setValue(5)
    ctl.off_z.setValue(-2)
    assert ctl.model.group(a).offset == (5, -2)
    assert ctl.list.item(0).text() == "Castle · 4 chunks · offset 5, -2"
    ctl.list.clearSelection()
    assert ctl.model.selected == set()
    ctl.list.item(0).setSelected(True)
    assert ctl.model.selected == {a}


# ---------------------------------------------------------------- the check


def test_overlap_blocks_convert_with_the_message(gw, app):
    t = gw.map_tab
    ctl = t.layout_ctl
    a = _paste(gw, _sq(0, 0, 2, 2))
    b = _paste(gw, _sq(2, 0, 2, 2))
    assert ctl.problems() == [] and gw.btn_convert.isEnabled()
    ctl.model.set_offsets({b: (-2, 0)})                       # onto "Group 1"
    probs = ctl.problems()
    assert probs and "overlap" in probs[0] and "Group 1" in probs[0]
    assert not gw.btn_convert.isEnabled() and "cannot be converted yet" in gw.run_hint.text()
    assert probs[0] in gw.btn_convert.toolTip()
    assert "overlap" in ctl.check_label.text()
    bad = ctl.model.derived()[2][OVERWORLD]
    assert bad == _sq(0, 0, 2, 2)                              # these are painted red
    c = _view(gw, app)
    c.grab()                                                   # painting with red chunks does not fail
    gw._start()                                                # not even by Ctrl+Enter / the programme: nothing starts
    assert gw._worker is None and "cannot be converted yet" in gw.message.text.text()
    ctl.model.undo()
    assert ctl.problems() == [] and gw.btn_convert.isEnabled()
    assert a in ctl.model.ids


def test_chunks_outside_the_finite_map_block_convert(gw, app):
    _pick(gw.edition, "lce")
    small = min(i for i in (gw.lce_size.itemData(k) for k in range(gw.lce_size.count())) if i)
    gw.lce_size.setCurrentIndex(gw.lce_size.findData(small))
    ctl = gw.map_tab.layout_ctl
    home = _paste(gw, _sq(0, 0, 2, 2))                         # holds the source's spawn: the LCE map is centred on it
    far = _paste(gw, _sq(-4, -4, 2, 2))
    assert ctl.problems() == [] and gw.btn_convert.isEnabled()
    ctl.model.set_offsets({far: (5000, 0)})
    probs = ctl.problems()
    assert any("outside the map" in p for p in probs)
    assert not gw.btn_convert.isEnabled()
    assert ctl.model.derived()[2][OVERWORLD] == {(x + 5000, z) for x, z in _sq(-4, -4, 2, 2)}      # drawn red
    _view(gw, app).grab()
    _pick(gw.edition, "java")                                  # a world without a limit: fine
    assert ctl.problems() == [] and gw.btn_convert.isEnabled()
    _pick(gw.edition, "lce")
    assert not gw.btn_convert.isEnabled()
    ctl.model.select([far])
    ctl.back_to_place()
    assert ctl.problems() == [] and gw.btn_convert.isEnabled() and home in ctl.model.ids


# ---------------------------------------------------------------- undo / redo


def test_undo_redo_of_paste_move_and_delete(gw, app):
    ctl = gw.map_tab.layout_ctl
    m = ctl.model
    a = _paste(gw, _sq(0, 0, 2, 2))
    m.move([a], 4, 1)
    m.delete([a])
    assert m.groups == [] and ctl.act_undo.isEnabled() and not ctl.act_redo.isEnabled()
    ctl.act_undo.trigger()                                     # Ctrl+Z
    assert _offsets(gw) == [(4, 1)] and m.selected <= set(m.ids)
    ctl.act_undo.trigger()
    assert _offsets(gw) == [(0, 0)]
    ctl.act_undo.trigger()
    assert m.groups == [] and not ctl.act_undo.isEnabled() and ctl.act_redo.isEnabled()
    ctl.act_redo.trigger()                                     # Ctrl+Y
    ctl.act_redo.trigger()
    assert _offsets(gw) == [(4, 1)]
    ctl.act_redo.trigger()
    assert m.groups == []
    assert m.undo() and len(m.groups) == 1


# ---------------------------------------------------------------- the file


def test_save_and_load_round_trip(gw, app, tmp_path, monkeypatch):
    ctl = gw.map_tab.layout_ctl
    a = _paste(gw, _sq(-4, -4, 2, 2))
    b = _paste(gw, _sq(1, 1, 3, 1))
    ctl.model.set_offsets({a: (10, 5), b: (-2, -9)})
    ctl.model.rename(b, "Tower")
    f = str(tmp_path / "comp.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (f, "")))
    ctl.save_layout()
    saved = Layout.load(f)
    assert [(g.chunks, g.offset, g.name) for g in saved.groups] == [(g.chunks, g.offset, g.name) for g in ctl.model.groups]
    ctl.model.delete(list(ctl.model.ids))
    assert gw.map_tab.layout() is None
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (f, "")))
    ctl.load_layout()
    assert [(g.chunks, g.offset, g.name) for g in ctl.model.groups] == [(g.chunks, g.offset, g.name) for g in saved.groups]
    ctl.model.undo()                                           # loading is undoable
    assert ctl.model.groups == []
    # a broken file: said, nothing changes
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    boxes = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: boxes.append(a[2])))
    ctl.load_layout(str(bad))
    assert boxes and ctl.model.groups == []


# ---------------------------------------------------------------- the conversion carries the layout


def test_the_selection_of_the_conversion_carries_the_layout(gw, app):
    t = gw.map_tab
    t.scope_sel.setChecked(True)
    t.move_sel.setChecked(True)
    t.canvas.selection[OVERWORLD] = {(0, 0)}
    assert t.move_target() == (0, 0) and t.move_sel_row.isVisibleTo(t) and gw._target().selection.move_to == (0, 0)
    a = _paste(gw, _sq(-4, -4, 2, 2))
    b = _paste(gw, _sq(1, 1, 2, 2))
    t.layout_ctl.model.set_offsets({a: (4, 4), b: (-1, -1)})
    sel = gw._target().selection
    assert sel.layout is not None and sel.move_to is None and sel.moves
    assert [(g.chunks, g.offset) for g in sel.layout.groups] == [(frozenset(_sq(-4, -4, 2, 2)), (4, 4)),
                                                                 (frozenset(_sq(1, 1, 2, 2)), (-1, -1))]
    assert sel.chunks == {OVERWORLD: _sq(-4, -4, 2, 2) | _sq(1, 1, 2, 2)}
    # the one-group "move" controls give way while groups exist
    assert t.move_target() is None and t.moves_chunks() and t.chunk_selection() is None
    assert not t.move_sel_row.isVisibleTo(t) and not t.move_box.isVisibleTo(t) and t.composed_hint.isVisibleTo(t)
    assert "Composed world (2 groups, 8 chunks)" in gw.scope_label.text()
    # the border check of Bedrock counts a layout as moved
    from types import SimpleNamespace

    from worldbridge.bedrock import edge

    assert edge.applies(SimpleNamespace(family="bedrock", version=(1, 21, 0)), "java_legacy", True, t.moves_chunks()) \
        == edge.applies(SimpleNamespace(family="bedrock", version=(1, 21, 0)), "java_legacy", True, True)
    # without groups they work as before
    t.layout_ctl.model.delete(list(t.layout_ctl.model.ids))
    assert t.layout() is None and t.move_sel_row.isVisibleTo(t) and t.move_target() == (0, 0)
    assert gw._target().selection.layout is None and gw._target().selection.move_to == (0, 0)


def test_a_real_conversion_of_two_groups_from_the_window(gw, app, tmp_path):
    t = gw.map_tab
    a = _paste(gw, _sq(-4, -4, 2, 2))
    b = _paste(gw, _sq(1, 1, 2, 2))
    t.layout_ctl.model.set_offsets({a: (4, 4), b: (-3, -3)})          # (0,0)-(1,1) and (-2,-2)-(-1,-1)
    assert t.layout_problems() == []
    _pick(gw.edition, "java")
    _pick(gw.java_ver, ("numeric", None, "1.12"))
    gw.ring.setChecked(False)
    gw.out_edit.setText(str(tmp_path / "out"))
    gw._start()
    assert _wait(app, lambda: gw._worker is None, 240)
    assert gw.message.isVisible() and "Conversion completed" in gw.message.text.text()
    out = gw._result_path
    assert os.path.isfile(os.path.join(out, "level.dat"))
    got = set(JavaNumericWorld(out).chunk_coords(0))
    assert got == _sq(0, 0, 2, 2) | _sq(-2, -2, 2, 2)
    assert gw.btn_convert.isEnabled()


# ---------------------------------------------------------------- the world and the language


def test_the_layout_follows_the_language_and_is_cleared_with_another_world(gw, app, tmp_path, monkeypatch):
    t = gw.map_tab
    a = _paste(gw, _sq(-4, -4, 2, 2))
    t.layout_ctl.model.set_offsets({a: (6, 1)})
    t.layout_ctl.model.rename(a, "Mine")
    path = gw.src_edit.text()
    it = gw.switch_language("it")
    try:
        assert it is not None
        assert _wait(app, lambda: it.map_tab._meta is not None and it._pending_state is None)
        lay = it.map_tab.layout()
        assert lay is not None and [(g.offset, g.name) for g in lay.groups] == [((6, 1), "Mine")]
        assert it.map_tab._view_buttons[1].text() == "Nuovo mondo (1)"
        # another world: asked first; "No" keeps the world and the groups
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.No))
        elsewhere = tmp_path / "else"
        elsewhere.mkdir()
        it.src_edit.setText(str(elsewhere))
        it._on_source_changed(force=True)
        assert it.src_edit.text() == path and it.map_tab.layout() is not None
        monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.Yes))
        it.src_edit.setText(str(elsewhere))
        it._on_source_changed(force=True)
        assert _wait(app, lambda: it.map_tab.path == "" or it.map_tab.layout() is None, 30)
        it.map_tab.set_source("")
        assert it.map_tab.layout() is None
    finally:
        i18n.set_language("en")
        it.close()
        app.processEvents()


def test_the_state_of_the_view_is_exported_and_restored(gw, app):
    t = gw.map_tab
    a = _paste(gw, _sq(-4, -4, 2, 2))
    t.layout_ctl.model.set_offsets({a: (6, 1)})
    st = t.export_state()
    t.layout_ctl.model.clear()
    assert t.layout() is None
    t.import_state(st)
    assert [g.offset for g in t.layout().groups] == [(6, 1)]
    assert t.views.checkedId() == 0
