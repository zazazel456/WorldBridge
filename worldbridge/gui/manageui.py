"""The "Gestione mondo" tab: the settings and the players of a world, and every tag of its NBT.

Left: the documents of the world (level.dat, the players, and in Java 26.x the separate files of
the seed, the game rules and the weather) and, above them, the quick settings of this kind of world
(name, seed, game mode, difficulty, spawn, time, weather, game rules).  Right: the tree of every tag
of the chosen document, editable (double click on a value; right click to add, rename or remove a
tag).  "Salva" writes the changed documents back in the world's own format, after copying the files
it replaces (*.wb-backup).  "Applica solo al mondo convertito" keeps the changes apart (``StagedEdits``)
instead: the world stays as it is and the next conversion writes them into the converted world."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QSplitter, QStyle, QTableWidget, QTableWidgetItem, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
    QWidget,
)

from .. import nbt
from . import theme
from .widgets import HintLabel, heading
from ..i18n import tr

TYPES = [("Byte", nbt.ByteTag), ("Short", nbt.ShortTag), ("Int", nbt.IntTag), ("Long", nbt.LongTag),
         ("Float", nbt.FloatTag), ("Double", nbt.DoubleTag), ("String", nbt.StringTag), ("List", nbt.ListTag),
         ("Compound", nbt.CompoundTag), ("Byte array", nbt.ByteArrayTag), ("Int array", nbt.IntArrayTag),
         ("Long array", nbt.LongArrayTag)]
_NAME = {t: n for n, t in TYPES}
_ARRAYS = (nbt.ByteArrayTag, nbt.IntArrayTag, nbt.LongArrayTag)
_INTS = (nbt.ByteTag, nbt.ShortTag, nbt.IntTag, nbt.LongTag)
_FLOATS = (nbt.FloatTag, nbt.DoubleTag)


def _text(tag) -> str:
    if isinstance(tag, nbt.CompoundTag):
        return tr("{n} entries", n=len(tag))
    if isinstance(tag, nbt.ListTag):
        return tr("{n} elements", n=len(tag))
    if isinstance(tag, _ARRAYS):
        vals = [int(v) for v in tag]
        return ", ".join(str(v) for v in vals[:64]) + (" …" if len(vals) > 64 else "")
    return str(tag.py_data)


def _parse(tag_type, text: str):
    if tag_type in _INTS:
        return tag_type(int(text.strip()))
    if tag_type in _FLOATS:
        return tag_type(float(text.strip().replace(",", ".")))
    if tag_type is nbt.StringTag:
        return nbt.StringTag(text)
    if tag_type in _ARRAYS:
        return tag_type([int(v) for v in text.replace(";", ",").split(",") if v.strip()])
    raise ValueError(tr("this tag has no value to write"))


def same_world(a: str, b: str) -> bool:
    """Both paths name the same world (a ``level.dat`` file stands for its folder)."""
    def norm(p: str) -> str:
        p = os.path.realpath(os.path.expanduser(p.strip())) if p.strip() else ""
        return os.path.dirname(p) if os.path.basename(p).lower() == "level.dat" and os.path.isfile(p) else p
    return bool(a.strip()) and norm(a) == norm(b)


class ManageTab(QWidget):
    source_requested = Signal()          # "Usa il mondo sorgente"
    staged_changed = Signal()            # the edits kept for the converted world changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self.world = None
        self._doc = None
        self._filling = False
        self._staged = None              # manage.StagedEdits: edits for the converted world, not in any world
        self.source_getter = lambda: getattr(self, "_source", "")     # the world chosen at the top of the window
        v = QVBoxLayout(self)
        top = QHBoxLayout()
        top.addWidget(QLabel(tr("World to edit:")))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(tr("The world opened at the top, or another one: folder or save file"))
        self.path_edit.setToolTip(tr("Java, Bedrock, Pocket Edition, LCE; Enter opens the path typed"))
        self.path_edit.returnPressed.connect(self._typed_path)
        top.addWidget(self.path_edit, 1)
        for label, icons, slot, tip in (
                (tr("Open folder…"), ("folder-open",), self._pick_dir, tr("Edit another world (folder)")),
                (tr("Open file…"), ("document-open",), self._pick_file, tr("Edit another world (save file)")),
                (tr("Use the world opened at the top"), ("go-up", "view-refresh"), self.use_source,
                 tr("Go back to the world chosen at the top of the window"))):
            b = QPushButton(theme.icon(*icons), label)
            b.setToolTip(tip)
            b.clicked.connect(slot)
            top.addWidget(b)
        v.addLayout(top)
        self.desc = HintLabel(tr("Open a world to see and edit its settings, its players and all its NBT data."))
        v.addWidget(self.desc)

        split = QSplitter(Qt.Horizontal)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(heading(tr("Quick settings")))
        self.quick_area = QScrollArea()
        self.quick_area.setWidgetResizable(True)
        self.quick_holder = QWidget()
        self.quick = QFormLayout(self.quick_holder)
        self.quick_area.setWidget(self.quick_holder)
        lv.addWidget(self.quick_area, 3)
        lv.addWidget(heading(tr("Documents")))
        self.docs = QListWidget()
        self.docs.currentRowChanged.connect(self._show_doc)
        lv.addWidget(self.docs, 1)
        split.addWidget(left)

        right = QWidget()
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Name"), tr("Type"), tr("Value")])
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tree.itemDoubleClicked.connect(self._edit_item)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        rv.addWidget(self.tree, 1)
        hint = HintLabel(tr("Double-click a value to change it · right-click to add, rename or remove a tag"))
        rv.addWidget(hint)
        split.addWidget(right)
        split.setSizes([380, 620])
        v.addWidget(split, 1)

        self.staged_box = QWidget()
        sb = QHBoxLayout(self.staged_box)
        sb.setContentsMargins(0, 0, 0, 0)
        self.staged_label = QLabel("")
        self.staged_label.setWordWrap(True)
        sb.addWidget(self.staged_label, 1)
        self.btn_discard_staged = QPushButton(theme.icon("edit-delete", fallback=QStyle.SP_TrashIcon), tr("Discard"))
        self.btn_discard_staged.setToolTip(tr("Forget these changes: the next conversion will not carry them"))
        self.btn_discard_staged.clicked.connect(self.discard_staged)
        sb.addWidget(self.btn_discard_staged)
        self.staged_box.hide()
        v.addWidget(self.staged_box)

        bottom = QHBoxLayout()
        self.state = QLabel("")
        bottom.addWidget(self.state, 1)
        self.btn_reload = QPushButton(theme.icon("view-refresh", fallback=QStyle.SP_BrowserReload), tr("Reload"))
        self.btn_reload.setToolTip(tr("Read the world from disk again (unsaved changes are lost)"))
        self.btn_reload.clicked.connect(self._reload)
        self.btn_save = QPushButton(theme.icon("document-save", fallback=QStyle.SP_DialogSaveButton), tr("&Save changes"))
        self.btn_save.setToolTip(tr("Write the changes into the world (a *.wb-backup copy first)"))
        self.btn_save.clicked.connect(self._save)
        self.btn_stage = QPushButton(theme.icon("document-export", "go-next", fallback=QStyle.SP_ArrowRight),
                                     tr("Apply only to the converted world"))
        self.btn_stage.clicked.connect(self._stage)
        for b in (self.btn_reload, self.btn_stage, self.btn_save):
            b.setEnabled(False)
            bottom.addWidget(b)
        v.addLayout(bottom)
        self._update_buttons()

    # ------------------------------------------------------------------ opening
    def open(self, path: str, manual=None) -> bool:
        """Opens ``path``, after asking what to do with unsaved changes (False: the user cancelled)."""
        if not self.maybe_discard() or not self.maybe_drop_staged():
            return False
        if manual is not None:
            self._manual = manual
        self.path_edit.setText(path)
        self._open_path()
        return True

    def _reload(self):
        if self.maybe_discard() and self.maybe_drop_staged():
            self._open_path()

    def maybe_discard(self) -> bool:
        """True when the world has no unsaved changes or the user chose to save or discard them."""
        if not self.has_changes():
            return True
        box = QMessageBox(QMessageBox.Question, tr("Unsaved changes"),
                          tr("The world has unsaved changes. Save them before going on?"),
                          QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, self)
        box.setDefaultButton(QMessageBox.Save)
        r = box.exec()
        if r == QMessageBox.Save:
            self._save()
            return not self.has_changes()
        return r == QMessageBox.Discard

    def follow_source(self, path: str) -> None:
        """The world of the conversion tab is the one managed here, unless another one was opened by
        hand or has unsaved changes; it is read when the tab is first shown."""
        self._source = path
        self._update_buttons()
        if getattr(self, "_manual", False) or self.has_changes():
            return
        self._pending = path
        if self.isVisible():
            self._open_pending()

    def use_source(self) -> None:
        """«Usa il mondo di origine»: back to following the conversion's world."""
        self._manual = False
        self.source_requested.emit()

    def _open_pending(self):
        path, self._pending = getattr(self, "_pending", ""), ""
        if path and path != self.path_edit.text().strip():
            self.open(path)

    def showEvent(self, e):
        super().showEvent(e)
        self._open_pending()

    def _pick_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("World folder"), self.path_edit.text())
        if d:
            self.open(d, manual=True)

    def _pick_file(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Save file (LCE: saveData.ms, savegame.dat, GAMEDATA…)"),
                                           self.path_edit.text())
        if f:
            self.open(f, manual=True)

    def _typed_path(self):
        typed = self.path_edit.text().strip()
        if not self.maybe_discard() or not self.maybe_drop_staged():
            self.path_edit.setText(self.world.path)            # stays on the world with the changes
            return
        self._manual = typed != getattr(self, "_source", "")
        self._open_path()

    def _open_path(self):
        from ..manage import open_world

        path = self.path_edit.text().strip()
        if not path:
            return
        try:
            self.world = open_world(path)
        except Exception as e:  # noqa: BLE001
            self.world = None
            self.desc.setText(theme.span(tr("Cannot open the world: {error}", error=e), "negative"))
            self.docs.clear()
            self.tree.clear()
            self._clear_quick()
            self.btn_save.setEnabled(False)
            self.btn_reload.setEnabled(False)
            self._update_buttons()
            return
        w = self.world
        ro = "  ·  " + tr("<b>read-only</b> (Xbox 360 STFS package)") if w.read_only else ""
        warn = "<br>" + theme.span(w.warning, "negative") if w.warning else ""
        self.desc.setText(f"{w.description}  ·  {os.path.abspath(w.path)}{ro}{warn}")
        self.docs.blockSignals(True)
        self.docs.clear()
        for d in w.docs:
            QListWidgetItem(d.label, self.docs)
        self.docs.blockSignals(False)
        self._build_quick(w.docs[0] if w.docs else None)
        self.docs.setCurrentRow(0)
        self.btn_reload.setEnabled(True)
        self.btn_save.setEnabled(not w.read_only)
        self._set_dirty(False)
        self._refresh_staged()

    # ------------------------------------------------------------------ quick settings
    def _clear_quick(self):
        while self.quick.rowCount():
            self.quick.removeRow(0)

    def _build_quick(self, doc=None):
        self._clear_quick()
        w = self.world
        self._quick_doc = doc
        self._filling = True
        player = doc is not None and doc.kind == "player"
        fields = w.player_fields(doc) if player else w.quick_fields()
        for f in fields:
            val = w.get(f)
            if f.kind == "choice":
                box = QComboBox()
                for k, label in f.choices.items():
                    box.addItem(tr(label), k)
                i = box.findData(val)
                if i < 0 and val is not None:
                    box.addItem(str(val), val)
                    i = box.count() - 1
                box.setCurrentIndex(max(i, 0) if val is not None else -1)
                box.currentIndexChanged.connect(lambda _i, f=f, box=box: self._quick_changed(f, box.currentData()))
                widget = box
            elif f.kind == "bool":
                cb = QCheckBox()
                cb.setChecked(bool(val))
                cb.toggled.connect(lambda on, f=f: self._quick_changed(f, 1 if on else 0))
                widget = cb
            elif f.kind == "int":
                sb = QSpinBox()
                sb.setRange(-2 ** 31, 2 ** 31 - 1)
                sb.setValue(int(val or 0))
                sb.valueChanged.connect(lambda x, f=f: self._quick_changed(f, x))
                widget = sb
            elif f.kind == "float":
                sb = QDoubleSpinBox()
                sb.setRange(-1e9, 1e9)
                sb.setDecimals(3)
                sb.setValue(float(val or 0))
                sb.valueChanged.connect(lambda x, f=f: self._quick_changed(f, x))
                widget = sb
            else:                                                     # text, long (a seed)
                le = QLineEdit("" if val is None else str(val))
                le.editingFinished.connect(lambda f=f, le=le: self._quick_changed(f, le.text()))
                widget = le
            if val is None and f.kind != "choice":
                widget.setToolTip(tr("Not in the world: writing a value adds it"))
            self.quick.addRow(f.label + ":", widget)
        if player:
            self._inventory_table(doc)
        self._filling = False

    # ------------------------------------------------------------------ inventory
    def _inventory_table(self, doc):
        from ..manage import inventory, item_count, item_name

        self.quick.addRow(heading(tr("Inventory")))
        stacks = inventory(doc)
        show_empty = getattr(self, "_show_empty", False)
        shown = [st for st in stacks if show_empty or not st.empty]
        if not stacks:
            self.quick.addRow(HintLabel(tr("This player has no inventory.")))
            return
        t = QTableWidget(len(shown), 4)
        t.setHorizontalHeaderLabels([tr("Where"), tr("Slot"), tr("Item"), tr("Count")])
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        t.verticalHeader().setVisible(False)
        t.setMinimumHeight(240)
        for row, st in enumerate(shown):
            for col, val in enumerate((tr(st.section), st.slot, item_name(st.tag), item_count(st.tag))):
                cell = QTableWidgetItem(str(val))
                if col < 2:
                    cell.setFlags(cell.flags() & ~Qt.ItemIsEditable)
                t.setItem(row, col, cell)
        t.itemChanged.connect(lambda cell, shown=shown, doc=doc: self._item_edited(doc, shown, cell))
        self.quick.addRow(t)
        n_empty = sum(1 for st in stacks if st.empty)
        cb = QCheckBox(tr("Show the empty slots ({n})", n=n_empty))
        cb.setChecked(show_empty)
        cb.toggled.connect(lambda on, doc=doc: self._toggle_empty(doc, on))
        self.quick.addRow(cb)
        hint = HintLabel(tr("Double-click to change the item (e.g. minecraft:diamond) or the count; the item's other "
                            "data (enchantments, name) are in the tree on the right."))
        self.quick.addRow(hint)

    def _toggle_empty(self, doc, on: bool):
        self._show_empty = on
        self._build_quick(doc)

    def _item_edited(self, doc, stacks, cell):
        from ..manage import set_item_count, set_item_name

        if self._filling:
            return
        it = stacks[cell.row()].tag
        text = cell.text().strip()
        try:
            if cell.column() == 2:
                set_item_name(it, text)
            elif cell.column() == 3:
                set_item_count(it, int(text))
        except (TypeError, ValueError, OverflowError) as e:
            self.state.setText(theme.span(tr("Invalid value") + f": {e}", "negative"))
            return
        doc.dirty = True
        self._set_dirty(True)
        if self._doc is doc:
            self._fill_tree()

    def _quick_changed(self, f, value):
        if self._filling or self.world is None:
            return
        try:
            if f.kind == "long":
                value = int(str(value).strip())
            self.world.set(f, value)
        except (TypeError, ValueError):
            self.state.setText(theme.span(tr("Invalid value for “{field}”", field=f.label), "negative"))
            return
        self._set_dirty(True)
        if self._doc is not None and self._doc.key == f.doc:
            self._fill_tree()
            if self._doc.kind == "player":
                return

    # ------------------------------------------------------------------ tree
    def _show_doc(self, row: int):
        if self.world is None or row < 0 or row >= len(self.world.docs):
            return
        self._doc = self.world.docs[row]
        prev = getattr(self, "_quick_doc", None)
        if self._doc.kind == "player" or (prev is not None and prev.kind == "player"):
            self._build_quick(self._doc)
        self._fill_tree()

    def _fill_tree(self):
        self.tree.clear()
        root = self._doc.root
        top = QTreeWidgetItem(self.tree, [self._doc.label, "Compound", _text(root)])
        top.setData(0, Qt.UserRole, (None, None))
        self._add_children(top, root)
        top.setExpanded(True)
        if top.childCount() == 1:                          # Java's level.dat: open its "Data" too
            top.child(0).setExpanded(True)

    def _add_children(self, item: QTreeWidgetItem, tag):
        entries = list(tag.items()) if isinstance(tag, nbt.CompoundTag) else list(enumerate(tag))
        for key, child in entries:
            it = QTreeWidgetItem(item, [str(key), _NAME.get(type(child), type(child).__name__), _text(child)])
            it.setData(0, Qt.UserRole, (tag, key))
            if isinstance(child, (nbt.CompoundTag, nbt.ListTag)):
                self._add_children(it, child)

    @staticmethod
    def _tag_of(item: QTreeWidgetItem):
        parent, key = item.data(0, Qt.UserRole)
        if parent is None:
            return None
        return parent[key]

    def _edit_item(self, item: QTreeWidgetItem, _col: int):
        tag = self._tag_of(item)
        if tag is None or isinstance(tag, (nbt.CompoundTag, nbt.ListTag)):
            return
        text, ok = QInputDialog.getText(self, tr("Edit value"), f"{item.text(0)} ({item.text(1)}):", text=_text(tag)
                                        if not isinstance(tag, _ARRAYS) else ", ".join(str(int(v)) for v in tag))
        if not ok:
            return
        parent, key = item.data(0, Qt.UserRole)
        try:
            parent[key] = _parse(type(tag), text)
        except (TypeError, ValueError, OverflowError) as e:
            QMessageBox.warning(self, tr("Invalid value"), str(e))
            return
        item.setText(2, _text(parent[key]))
        self._changed()

    def _menu(self, pos):
        item = self.tree.itemAt(pos)
        if item is None:
            return
        tag = self._tag_of(item)
        container = self._doc.root if tag is None else tag
        m = QMenu(self)
        if isinstance(container, (nbt.CompoundTag, nbt.ListTag)):
            add = m.addMenu(tr("Add tag"))
            for name, t in TYPES:
                if isinstance(container, nbt.ListTag) and len(container) and not isinstance(container[0], t):
                    continue
                add.addAction(name, lambda t=t, c=container: self._add_tag(c, t))
        if tag is not None:
            parent, key = item.data(0, Qt.UserRole)
            if isinstance(parent, nbt.CompoundTag):
                m.addAction(tr("Rename…"), lambda: self._rename(parent, key))
            m.addAction(tr("Remove"), lambda: self._remove(parent, key))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _add_tag(self, container, t):
        if isinstance(container, nbt.CompoundTag):
            name, ok = QInputDialog.getText(self, tr("New tag"), tr("Name:"))
            if not ok or not name:
                return
            if name in container:
                QMessageBox.warning(self, tr("Name already used"), tr("There is already a tag “{name}”.", name=name))
                return
        new = t() if t in (nbt.CompoundTag,) else t([]) if t in _ARRAYS or t is nbt.ListTag else \
            t("") if t is nbt.StringTag else t(0)
        if isinstance(container, nbt.CompoundTag):
            container[name] = new
        else:
            container.append(new)
        self._changed(refill=True)

    def _rename(self, parent, key):
        name, ok = QInputDialog.getText(self, tr("Rename"), tr("New name:"), text=str(key))
        if ok and name and name != key and name not in parent:
            parent[name] = parent.pop(key)
            self._changed(refill=True)

    def _remove(self, parent, key):
        if isinstance(parent, nbt.CompoundTag):
            del parent[key]
        else:
            parent.pop(int(key))
        self._changed(refill=True)

    def _changed(self, refill: bool = False):
        self._doc.dirty = True
        self._set_dirty(True)
        if refill:
            self._fill_tree()
        self._build_quick(self._doc if self._doc.kind == "player" else getattr(self, "_quick_doc", None))

    # ------------------------------------------------------------------ saving
    def _set_dirty(self, dirty: bool):
        self.state.setText(theme.span(tr("Unsaved changes"), "neutral") if dirty else "")
        self.btn_save.setDefault(dirty)
        self._update_buttons()

    def _save(self):
        if self.world is None:
            return
        try:
            self.world.save()
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Saving failed"), str(e))
            return
        self._set_dirty(False)
        self.state.setText(theme.span(tr("Saved (backup copy: *.wb-backup)"), "positive"))

    def has_changes(self) -> bool:
        return self.world is not None and any(d.dirty for d in self.world.docs)

    # ------------------------------------------------------------------ edits for the converted world only
    def is_source_world(self) -> bool:
        """The world opened here is the one the conversion reads (the path at the top of the window)."""
        return self.world is not None and (same_world(self.world.path, self.source_getter())
                                           or same_world(self.path_edit.text(), self.source_getter()))

    def _update_buttons(self) -> None:
        w = self.world
        ok = w is not None and not w.read_only and self.has_changes() and self.is_source_world()
        self.btn_stage.setEnabled(ok)
        tip = tr("The source world is not changed: the next conversion writes these changes into the converted world.")
        if not ok:
            tip += "\n" + tr("Available when the world opened here is the one chosen at the top of the window and "
                              "has changes.")
        self.btn_stage.setToolTip(tip)

    def staged_edits(self):
        """The edits kept for the converted world (``manage.StagedEdits``), None when there are none."""
        return self._staged

    def _stage(self) -> None:
        from ..manage import capture_edits

        if self.world is None or not self.has_changes() or not self.is_source_world():
            return
        previous = self._staged if self._staged is not None and same_world(self._staged.source, self.source_getter()) \
            else None
        try:
            self._staged = capture_edits(self.world, self.source_getter().strip(), previous)
        except Exception as e:  # noqa: BLE001
            QMessageBox.critical(self, tr("Saving failed"), str(e))
            return
        for d in self.world.docs:               # kept apart from the world: nothing is left unsaved
            d.dirty = False
        self._set_dirty(False)
        self._refresh_staged()
        self.staged_changed.emit()

    def _refresh_staged(self) -> None:
        st = self._staged
        self.staged_box.setVisible(st is not None)
        if st is not None:
            where = "" if self.is_source_world() else "  (" + os.path.basename(os.path.normpath(st.source)) + ")"
            self.staged_label.setText(theme.span(
                tr("Changed documents: {n}. They will be written into the converted world; the source world is not "
                   "changed.", n=st.count) + where, "positive"))
        self._update_buttons()

    def discard_staged(self) -> None:
        if self._staged is None:
            return
        self._staged = None
        self._refresh_staged()
        self.staged_changed.emit()

    def maybe_drop_staged(self, closing: bool = False) -> bool:
        """Before the editor leaves the edits kept for the converted world (another world, a reload, closing):
        keep them or discard them (False: the user cancelled)."""
        st = self._staged
        if st is None:
            return True
        if closing:
            r = QMessageBox.question(self, tr("Changes for the converted world"),
                                     tr("The changes kept for the converted world ({n} changed documents) are lost "
                                        "when the window closes. Close anyway?", n=st.count))
            if r != QMessageBox.Yes:
                return False
            self.discard_staged()
            return True
        box = QMessageBox(QMessageBox.Question, tr("Changes for the converted world"),
                          tr("The changes kept for the converted world ({n} changed documents) are in no world yet. "
                             "Keep them for the next conversion?", n=st.count), QMessageBox.NoButton, self)
        keep = box.addButton(tr("Keep them"), QMessageBox.AcceptRole)
        drop = box.addButton(tr("Discard them"), QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.setDefaultButton(keep)
        box.exec()
        if box.clickedButton() is drop:
            self.discard_staged()
            return True
        return box.clickedButton() is keep

    def source_changed(self, path: str) -> bool:
        """The conversion's world is now ``path``: edits kept for another world are dropped (True: they were)."""
        if self._staged is None or same_world(self._staged.source, path):
            self._update_buttons()
            self._refresh_staged()
            return False
        self.discard_staged()
        self._update_buttons()
        return True
