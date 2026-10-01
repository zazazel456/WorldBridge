"""World trim in the GUI: the settings popup next to the trim button and the background workers."""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)

from ..model import ConversionCancelled, Progress
from ..trim import DEFAULTS, TICKS_PER_SECOND, TrimOptions
from ..i18n import N_, tr
from .widgets import HintLabel

_UNITS = ((N_("seconds"), TICKS_PER_SECOND), (N_("minutes"), 60 * TICKS_PER_SECOND), (N_("hours"), 3600 * TICKS_PER_SECOND))


def _settings() -> QSettings:
    return QSettings("WorldBridge", "WorldBridge")


class TrimSettings(QWidget):
    """The settings popup: InhabitedTime threshold and the protections."""

    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(430)
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 10, 12, 10)
        title = QLabel("<b>" + tr("World trim settings") + "</b>")
        v.addWidget(title)
        f = QFormLayout()
        row = QHBoxLayout()
        self.amount = QSpinBox()
        self.amount.setRange(0, 100000)
        self.unit = QComboBox()
        for label, ticks in _UNITS:
            self.unit.addItem(tr(label), ticks)
        row.addWidget(QLabel(tr("less than")))
        row.addWidget(self.amount)
        row.addWidget(self.unit)
        row.addStretch(1)
        f.addRow(tr("Remove chunks used"), row)
        self.ring = QSpinBox()
        self.ring.setRange(0, 16)
        self.ring.setSuffix(" " + tr("chunks"))
        self.ring.setToolTip(tr("Also keeps the chunks around every used chunk: it avoids trees and builds cut in "
                                "half at the edge (the known problem of trims)."))
        f.addRow(tr("Protective ring"), self.ring)
        row = QHBoxLayout()
        self.spawn_on = QCheckBox(tr("radius"))
        self.spawn = QSpinBox()
        self.spawn.setRange(0, 32)
        self.spawn.setSuffix(" " + tr("chunks"))
        self.spawn_on.toggled.connect(self.spawn.setEnabled)
        row.addWidget(self.spawn_on)
        row.addWidget(self.spawn)
        row.addStretch(1)
        f.addRow(tr("Protect the spawn"), row)
        self.forced = QCheckBox(tr("chunks loaded with /forceload"))
        f.addRow(tr("Always keep"), self.forced)
        self.unknown = QCheckBox(tr("chunks with unreadable InhabitedTime"))
        f.addRow("", self.unknown)
        self.heat = QCheckBox(tr("colour the chunks by time spent"))
        self.heat.setToolTip(tr("Red: below the threshold (would be removed) · yellow → green: more and more used · "
                                "grey: no data"))
        f.addRow(tr("Map"), self.heat)
        v.addLayout(f)
        note = HintLabel(tr("Values recommended by the community: MCA Selector's guides suggest "
                            "<i>InhabitedTime &lt; 1 minute</i> (beyond that it becomes destructive for little extra "
                            "space); Aternos' Thanos never touches force-loaded chunks nor those without data. The "
                            "original world is never modified."))
        v.addWidget(note)
        b = QPushButton(tr("Restore the recommended values"))
        b.clicked.connect(lambda: self.set_options(DEFAULTS))
        v.addWidget(b, 0, Qt.AlignRight)
        self._loading = False
        for w in (self.amount, self.ring, self.spawn):
            w.valueChanged.connect(self._emit)
        for w in (self.spawn_on, self.forced, self.unknown, self.heat):
            w.toggled.connect(self._emit)
        self.unit.currentIndexChanged.connect(self._emit)
        self._load()

    # ---------------------------------------------------------- values
    def set_options(self, opt: TrimOptions):
        self._loading = True
        ticks = opt.min_ticks
        for i in range(len(_UNITS) - 1, -1, -1):
            if ticks % _UNITS[i][1] == 0 and (ticks or i == 1):
                self.unit.setCurrentIndex(i)
                self.amount.setValue(ticks // _UNITS[i][1])
                break
        else:
            self.unit.setCurrentIndex(0)
            self.amount.setValue(max(0, round(ticks / TICKS_PER_SECOND)))
        self.ring.setValue(opt.ring)
        self.spawn_on.setChecked(opt.spawn_radius >= 0)
        self.spawn.setValue(max(0, opt.spawn_radius))
        self.spawn.setEnabled(opt.spawn_radius >= 0)
        self.forced.setChecked(opt.keep_forced)
        self.unknown.setChecked(opt.keep_unknown)
        self._loading = False
        self._emit()

    def options(self) -> TrimOptions:
        return TrimOptions(min_ticks=self.amount.value() * int(self.unit.currentData()), ring=self.ring.value(),
                           spawn_radius=self.spawn.value() if self.spawn_on.isChecked() else -1,
                           keep_forced=self.forced.isChecked(), keep_unknown=self.unknown.isChecked())

    def show_heat(self) -> bool:
        return self.heat.isChecked()

    def _load(self):
        s = _settings()
        opt = TrimOptions(
            min_ticks=int(s.value("trim/min_ticks", DEFAULTS.min_ticks)), ring=int(s.value("trim/ring", DEFAULTS.ring)),
            spawn_radius=int(s.value("trim/spawn_radius", DEFAULTS.spawn_radius)),
            keep_forced=str(s.value("trim/keep_forced", DEFAULTS.keep_forced)).lower() == "true",
            keep_unknown=str(s.value("trim/keep_unknown", DEFAULTS.keep_unknown)).lower() == "true")
        self._loading = True
        self.heat.setChecked(str(s.value("trim/heat", "false")).lower() == "true")
        self.set_options(opt)

    def _emit(self, *_a):
        if self._loading:
            return
        o = self.options()
        s = _settings()
        s.setValue("trim/min_ticks", o.min_ticks)
        s.setValue("trim/ring", o.ring)
        s.setValue("trim/spawn_radius", o.spawn_radius)
        s.setValue("trim/keep_forced", o.keep_forced)
        s.setValue("trim/keep_unknown", o.keep_unknown)
        s.setValue("trim/heat", self.heat.isChecked())
        self.changed.emit()


class ScanWorker(QObject):
    progress = Signal(float, str)
    done = Signal(object)      # TrimScan
    failed = Signal(str)

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.prog = Progress(lambda f, m: self.progress.emit(f, m))

    def run(self):
        from ..trim import scan

        try:
            self.done.emit(scan(self.path, self.prog))
        except ConversionCancelled:
            self.failed.emit(tr("cancelled"))
        except Exception as ex:  # noqa: BLE001
            self.failed.emit(str(ex))


class CopyWorker(QObject):
    progress = Signal(float, str)
    done = Signal(int, int, int)   # removed chunks, size before, size after
    failed = Signal(str)

    def __init__(self, src: str, out: str, keep):
        super().__init__()
        self.src, self.out, self.keep = src, out, keep
        self.prog = Progress(lambda f, m: self.progress.emit(f, m))

    def run(self):
        from ..trim import folder_size, trimmed_copy

        try:
            before = folder_size(self.src)
            n = trimmed_copy(self.src, self.out, self.keep, self.prog)
            self.done.emit(n, before, folder_size(self.out))
        except Exception as ex:  # noqa: BLE001
            self.failed.emit(str(ex))


class EditWorker(QObject):
    """Chunk edits on the world itself (worldbridge.chunkedit): removed chunks, painted biomes."""

    progress = Signal(float, str)
    done = Signal(object)          # chunkedit.EditResult
    failed = Signal(str)

    def __init__(self, path: str, remove=None, paint=None, keep=None, dims=()):
        super().__init__()
        self.path, self.remove, self.paint, self.keep, self.dims = path, remove, paint, keep, tuple(dims)
        self.prog = Progress(lambda f, m: self.progress.emit(f, m))

    def run(self):
        from ..chunkedit import edit_world, keep_only

        try:
            if self.keep is not None:
                res = keep_only(self.path, self.keep, self.dims, self.prog)
            else:
                res = edit_world(self.path, self.remove, self.paint, self.prog)
            self.done.emit(res)
        except Exception as ex:  # noqa: BLE001
            self.failed.emit(str(ex))
