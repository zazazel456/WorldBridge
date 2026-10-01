"""WorldBridge graphical interface (PySide6).

The window follows the KDE Human Interface Guidelines (develop.kde.org/hig) and the desktop's own
look (see ``theme``): the world being worked on is chosen once at the top and every tab works on
it; each tab shows the controls that matter for the current choice (the others are hidden, not just
greyed out); long explanations sit behind "?" help buttons; results and problems appear inside the
window; the final action, "Converti", is at the bottom right."""

from __future__ import annotations

import os
import re
import sys
import traceback
from typing import List, Optional, Tuple

from PySide6.QtCore import QObject, QSettings, Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFontDatabase, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QStyle,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from .. import APP_NAME, __version__, i18n
from .. import amulet_bridge as ab
from ..convert import TargetSpec, convert
from ..detect import detect
from ..model import ConversionCancelled, Progress
from ..selection import Selection
from ..i18n import N_, tr
from . import theme
from .mapwidget import MapTab
from .players import PlayersTab
from .widgets import Disclosure, HelpButton, HintLabel, InlineMessage, heading, row, spacing, with_help

EDITIONS = [
    ("java", "Java Edition"),
    ("bedrock", "Bedrock Edition"),
    ("lce", N_("Legacy Console Edition (consoles + PC port)")),
    ("pe_old", N_("Pocket Edition 0.1 – 0.8 (old format)")),
]

HELP_BLEND = N_("For worlds born before 1.18 (LCE, old Java / Bedrock, Pocket Edition) converted to Java or "
                "Bedrock 1.18+: the chunks are written as pre-1.18 chunks, so when the world is opened Minecraft "
                "blends them with the new terrain (heights and biomes) and generates the part below y 0.\n"
                "Unticked, the chunks are written in the new format: no blending, no terrain below y 0.")
HELP_RING = N_("For the games that do not blend (Java Alpha 1.2 – 1.17, LCE neoLegacy): WorldBridge writes around "
               "the converted world a ring of terrain made by the game's generator (same seed), which passes "
               "smoothly from the converted edge to that version's terrain; in the Nether and the End too.\n"
               "Pocket Edition 0.x and LCE with a 54 / 64-chunk map: the world is finite and is written whole, "
               "with natural terrain joining the converted world around it.")
HELP_DEPTH = N_("1.18+ worlds (y −64 to 319) to games whose world starts at y 0 (Java 1.2 – 1.17, LCE, Bedrock up "
                "to 1.17, and older versions).\n"
                "Cut: what lies below y 0 disappears, the rest stays at its height.\n"
                "Keep everything: nothing disappears below, the world rises by 64 blocks (useful if you built "
                "below y 0); the mountains that no longer fit are compressed or cut as you choose below.\n"
                "From a chosen y: below that y it disappears, the rest rises to start from y 0.")
HELP_TALL = N_("When the terrain does not fit the target game's height: the mountains of 1.18+ worlds (up to y 319, "
               "and even more if you keep the underground) to the games 256 blocks high, and to those 128 blocks "
               "high (Alpha, Beta, Java 1.0 – 1.1, Pocket Edition 0.x).\n"
               "Compress: nothing changes at the bottom; higher up every column loses a band of rock under the "
               "surface, so mountains stay mountains (lower) with grass, snow, trees and buildings intact. Bases "
               "dug into the mountain come down whole.\n"
               "Cut: everything above the limit disappears and flat stone plateaus remain.")
HELP_XUID = N_("The game loads the main player from players/<XUID>.dat: the XUID is a number the game gives your "
               "user, not the nickname. With “From my world…” you take it from a world you have already played.")


# ============================================================ workers


class DetectWorker(QObject):
    done = Signal(object, str, str)  # ([(kind, html line)], kind, world name)

    def __init__(self, path: str):
        super().__init__()
        self.path = path

    def run(self):
        try:
            d = detect(self.path)
            if d is None:
                self.done.emit([("error", tr("Format not recognised.")),
                                ("text", tr("Choose the world folder or the save file (saveData.ms, savegame.dat, "
                                            "GAMEDATA, .bin, level.dat, .mclevel, .mcworld…)."))], "", "")
                return
            lines: List[Tuple[str, str]] = [("title", _esc(d.description))]
            name = ""
            try:
                if d.kind in ("lce", "java_numeric", "pe_old", "indev", "classic"):
                    from ..convert import open_source

                    src = open_source(d, Progress(), "")
                    name = src.info.name
                    lines.append(("text", tr("Name: {name}", name=f"<b>{_esc(src.info.name)}</b>")))
                    dims = src.dimensions()
                    counts = ", ".join(f"{_dim(dm)}: {len(src.chunk_coords(dm))}" for dm in dims)
                    lines.append(("text", tr("Chunks – {counts}", counts=counts)))
                    sx, sy, sz = src.info.spawn
                    lines.append(("text", tr("Spawn: {x}, {y}, {z} · Players: {n}", x=sx, y=sy, z=sz, n=len(src.info.players))))
                    cont = getattr(src, "container", None)
                    if cont is not None:
                        lines.append(("text", tr("Platform: {platform} · save version {version}", platform=cont.platform.label, version=cont.version)))
                elif d.kind == "bta":
                    from ..bta.world import BtaWorld, DIMENSION_NAMES, auto_shift, ocean_y

                    w = BtaWorld(d.path)
                    name = w.name
                    wt = w.world_type()
                    lines.append(("text", tr("Name: {name} · save version {version}", name=f"<b>{_esc(w.name)}</b>", version=w.save_version)))
                    regs = ", ".join(tr("{dim}: {n} regions", dim=DIMENSION_NAMES[dm], n=len(w.regions(dm))) for dm in w.dimensions())
                    lines.append(("text", regs))
                    oy = ocean_y(wt)
                    lines.append(("text", tr("World type: {type} (sea at y {sea}) → Overworld lowered by {shift} "
                                             "blocks · Players: {n}", type=_esc(wt or "?"), sea=oy if oy > 0 else "?",
                                             shift=auto_shift(wt), n=len(w.players()))))
                    lines.append(("ok", tr("Target: Minecraft Java 26.3 (the only conversion available for Better "
                                           "than Adventure).")))
                elif d.kind in ("java_modern", "bedrock"):
                    desc = ab.describe(d.path)
                    from ..extra import read_amulet_info

                    info = read_amulet_info(d)
                    name = info.name
                    lines.append(("text", tr("Name: {name}", name=f"<b>{_esc(info.name)}</b>")))
                    if desc:
                        lines.append(("text", tr("Version: {version}", version=desc)))
            except Exception as ex:  # noqa: BLE001
                lines.append(("warn", tr("Partial analysis: {error}", error=_esc(str(ex)))))
            self.done.emit(lines, d.kind, name)
        except Exception as ex:  # noqa: BLE001
            self.done.emit([("error", tr("Error: {error}", error=_esc(str(ex))))], "", "")


class ConvertWorker(QObject):
    progress = Signal(float, str)
    log = Signal(str)
    finished = Signal(bool, str, list)

    def __init__(self, src: str, out: str, target: TargetSpec):
        super().__init__()
        self.src, self.out, self.target = src, out, target
        self.prog = Progress(lambda f, m: self.progress.emit(f, m), lambda m: self.log.emit(m))

    def run(self):
        try:
            res = convert(self.src, self.out, self.target, self.prog)
            self.finished.emit(True, res.output, res.warnings)
        except ConversionCancelled:
            self.finished.emit(False, tr("Conversion cancelled."), [])
        except Exception as ex:  # noqa: BLE001
            self.log.emit(traceback.format_exc())
            self.finished.emit(False, str(ex), [])

    def cancel(self):
        self.prog.cancel()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _dim(d: int) -> str:
    return {0: "Overworld", -1: "Nether", 1: "End"}.get(d, str(d))


def format_summary(lines) -> str:
    """The analysis of the source world as rich text in the palette's colours."""
    if isinstance(lines, str):
        return lines
    out = []
    for kind, text in lines:
        if kind == "title":
            out.append(f"<b>{text}</b>")
        elif kind == "error":
            out.append(f"<b>{theme.span(text, 'negative')}</b>")
        elif kind == "warn":
            out.append(theme.span(text, "neutral"))
        elif kind == "ok":
            out.append(theme.span(text, "positive"))
        else:
            out.append(text)
    if len(out) > 2:                     # title, then the details on one or two lines
        return out[0] + "<br>" + " · ".join(out[1:])
    return "<br>".join(out)


# ============================================================ main window

# the conversion tab's controls carried over when the window is rebuilt in another language (in order)
_STATE_WIDGETS = ("edition", "java_ver", "bed_ver", "lce_plat", "lce_prof", "lce_size", "lce_center", "lce_ox",
                  "lce_oz", "lce_xuid", "blend", "ring", "depth", "depth_y", "tall", "name_edit", "out_edit",
                  "bta_palette", "bta_auto_y", "bta_y")


def _install_qt_translations() -> None:
    """Qt's own texts (the buttons of standard dialogs) in the interface's language."""
    from PySide6.QtCore import QLibraryInfo, QTranslator

    app = QApplication.instance()
    if app is None:
        return
    for t in getattr(app, "_wb_translators", []):
        app.removeTranslator(t)
    app._wb_translators = []
    if i18n.language() == "en":
        return
    folder = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    for name in ("qtbase", "qt"):
        t = QTranslator(app)
        if t.load(f"{name}_{i18n.language()}", folder):
            app.installTranslator(t)
            app._wb_translators.append(t)


class MainWindow(QMainWindow):
    def __init__(self, remember: Optional[bool] = None):
        super().__init__()
        # window size, output folder... are remembered in the real application (not in tests)
        if remember is None:
            remember = QApplication.organizationName() == APP_NAME
        self._remember = remember
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 860)
        self._threads = []
        self._worker: Optional[ConvertWorker] = None
        self._src_kind = ""
        self._src_name = ""
        self._result_path = ""
        self._pending_state = None
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)

        root.addWidget(self._source_bar())

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._conversion_page(), theme.icon("document-export", "document-save-as"), tr("Conversion"))
        self.map_tab = MapTab()
        self.tabs.addTab(self.map_tab, theme.icon("map-flat", "globe", "applications-education-geography"),
                         tr("Map and chunks"))
        self.players_tab = PlayersTab()
        self.tabs.addTab(self.players_tab, theme.icon("user-identity", "system-users"), tr("Players"))
        from .manageui import ManageTab

        self.manage_tab = ManageTab()
        self.tabs.addTab(self.manage_tab, theme.icon("document-edit", "document-properties"), tr("World management"))
        self.tabs.currentChanged.connect(self._on_tab)
        self.manage_tab.source_requested.connect(lambda: self.manage_tab.open(self.src_edit.text().strip()))
        self.map_tab.players_loaded.connect(self.players_tab.set_players)
        self.map_tab.summary_changed.connect(self._update_scope)
        self.players_tab.changed.connect(self._update_scope)
        self.players_tab.center_requested.connect(self._show_player)

        root.addWidget(self._run_bar())
        self.setAcceptDrops(True)
        self._on_edition()
        self._update_scope()
        QShortcut(QKeySequence("Ctrl+O"), self, self._pick_src_dir)
        QShortcut(QKeySequence("Ctrl+Shift+O"), self, self._pick_src_file)
        QShortcut(QKeySequence("Ctrl+Return"), self, lambda: self.btn_convert.isEnabled() and self._start())
        if remember:
            self._restore()

    # ---------------------------------------------------------- the world being worked on
    def _source_bar(self) -> QWidget:
        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(spacing(box))
        top = QHBoxLayout()
        lab = QLabel(tr("&World:"))
        f = lab.font()
        f.setBold(True)
        lab.setFont(f)
        top.addWidget(lab)
        self.src_edit = QLineEdit()
        self.src_edit.setPlaceholderText(tr("Drop the world folder or the save file here"))
        self.src_edit.setClearButtonEnabled(True)
        self.src_edit.editingFinished.connect(self._on_source_changed)
        lab.setBuddy(self.src_edit)
        top.addWidget(self.src_edit, 1)
        b_dir = QPushButton(theme.icon("folder-open", fallback=QStyle.SP_DirOpenIcon), tr("Open folder…"))
        b_dir.setToolTip(tr("Open a world's folder (Ctrl+O)"))
        b_dir.clicked.connect(self._pick_src_dir)
        b_file = QPushButton(theme.icon("document-open", fallback=QStyle.SP_FileIcon), tr("Open file…"))
        b_file.setToolTip(tr("Open a save file: saveData.ms, savegame.dat, GAMEDATA, .mcworld… (Ctrl+Shift+O)"))
        b_file.clicked.connect(self._pick_src_file)
        top.addWidget(b_dir)
        top.addWidget(b_file)
        top.addSpacing(spacing(box, True))
        top.addWidget(self._language_switch())
        about = QToolButton()
        about.setIcon(theme.icon("help-about", fallback=QStyle.SP_MessageBoxInformation))
        about.setAutoRaise(True)
        about.setToolTip(tr("About {app}", app=APP_NAME))
        about.setAccessibleName(tr("About {app}", app=APP_NAME))
        about.clicked.connect(self._about)
        top.addWidget(about)
        v.addLayout(top)
        self.src_info = HintLabel(tr("No world open. Java, Bedrock, Legacy Console Edition, Pocket Edition, Classic / "
                                     "Indev and Better than Adventure are recognised automatically."))
        self.src_info.setTextFormat(Qt.RichText)
        v.addWidget(self.src_info)
        return box

    def _language_switch(self) -> QWidget:
        """EN | IT, at the top right: the window is rebuilt in the other language, keeping every choice."""
        box = QWidget()
        box.setToolTip(tr("Language of the interface"))
        box.setAccessibleName(tr("Language of the interface"))
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.lang_group = QButtonGroup(box)
        self.lang_group.setExclusive(True)
        for code in i18n.LANGUAGES:
            b = QToolButton()
            b.setText(code.upper())
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setChecked(code == i18n.language())
            b.setToolTip(i18n.LANGUAGES[code])
            b.setAccessibleName(i18n.LANGUAGES[code])
            b.setProperty("lang", code)
            self.lang_group.addButton(b)
            h.addWidget(b)
        self.lang_group.buttonClicked.connect(lambda b: self.switch_language(b.property("lang")))
        return box

    def switch_language(self, code: str) -> Optional["MainWindow"]:
        """Rebuild the window in ``code``'s language with the same world and choices (None: not now)."""
        if code == i18n.language():
            return None
        if self._worker is not None or self.manage_tab.has_changes():
            for b in self.lang_group.buttons():
                b.setChecked(b.property("lang") == i18n.language())
            self.tabs.setCurrentIndex(0)
            self.message.show_message("neutral", tr("The language can be changed when no conversion is running and "
                                                    "the world management tab has no unsaved changes."))
            return None
        state = self.export_state()
        i18n.set_language(code)
        _install_qt_translations()
        if self._remember:
            QSettings().setValue("ui/language", code)
            self._save_state()
        new = MainWindow(remember=self._remember)
        new.restoreGeometry(self.saveGeometry())
        new.import_state(state)
        if self.isMaximized():
            new.showMaximized()
        elif self.isVisible():
            new.show()
        app = QApplication.instance()
        if app is not None:
            app._wb_window = new                   # the application keeps the window alive
        self._remember = False                    # the new window saves the state from now on
        self.close()
        return new

    def export_state(self) -> dict:
        """Every choice of the window (the world, the conversion, the map and the players)."""
        st = {"src": self.src_edit.text(), "tab": self.tabs.currentIndex(), "log": self.logview.toPlainText(),
              "log_open": self.log_box.button.isChecked(),
              "map": self.map_tab.export_state(), "players": self.players_tab.export_state(),
              "manage": self.manage_tab.path_edit.text() if getattr(self.manage_tab, "_manual", False) else None}
        for name in _STATE_WIDGETS:
            w = getattr(self, name)
            if isinstance(w, QComboBox):
                st[name] = w.currentIndex()
            elif isinstance(w, QCheckBox):
                st[name] = w.isChecked()
            elif isinstance(w, QSpinBox):
                st[name] = w.value()
            else:
                st[name] = w.text()
        return st

    def import_state(self, st: dict) -> None:
        for name in _STATE_WIDGETS:           # in order: the platform before its versions and sizes
            w = getattr(self, name)
            if isinstance(w, QComboBox):
                if 0 <= st[name] < w.count():
                    w.setCurrentIndex(st[name])
            elif isinstance(w, QCheckBox):
                w.setChecked(st[name])
            elif isinstance(w, QSpinBox):
                w.setValue(st[name])
            else:
                w.setText(st[name])
        if st["log"]:
            self.logview.setPlainText(st["log"])
        self.log_box.set_open(st["log_open"])
        self._pending_state = st
        if st["src"].strip():
            self.src_edit.setText(st["src"])
            self._on_source_changed()
        if st["manage"]:
            self.manage_tab.path_edit.setText(st["manage"])
            self.manage_tab._manual = True
            self.manage_tab._open_path()
        self.tabs.setCurrentIndex(st["tab"])

    def _about(self):
        QMessageBox.about(
            self, tr("About {app}", app=APP_NAME),
            f"<h3>{APP_NAME} {__version__}</h3><p>" + tr("Universal Minecraft world converter.") + "</p>"
            "<p>Java · Bedrock · Legacy Console Edition · Pocket Edition · Classic / Indev · "
            "Better than Adventure</p>")

    # ---------------------------------------------------------- conversion tab
    def _conversion_page(self) -> QWidget:
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.setContentsMargins(0, spacing(page), 0, 0)
        self.message = InlineMessage()
        outer.addWidget(self.message)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        body = QWidget()
        col = QVBoxLayout(body)
        wrap = QHBoxLayout()
        wrap.addStretch(1)
        form_box = QWidget()
        form_box.setMaximumWidth(920)
        form_box.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        wrap.addWidget(form_box, 12)
        wrap.addStretch(1)
        col.addLayout(wrap)
        f = self.form = QFormLayout(form_box)
        f.setRowWrapPolicy(QFormLayout.DontWrapRows)
        f.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)

        # ---- target
        f.addRow(heading(tr("Target")))
        self.edition = QComboBox()
        for key, label in EDITIONS:
            self.edition.addItem(tr(label), key)
        self.edition.currentIndexChanged.connect(self._on_edition)
        f.addRow(tr("&Game:"), self.edition)
        self._java_rows(f)
        self.bed_ver = QComboBox()
        for i, v in enumerate(reversed(ab.versions("bedrock"))):
            self.bed_ver.addItem(ab.version_str(v) + ("  " + tr("(latest)") if i == 0 else ""), v)
        self.bed_ver.currentIndexChanged.connect(self._update_tall)
        f.addRow(tr("&Version:"), self.bed_ver)
        self._lce_rows(f)
        self.pe_hint = HintLabel(tr("Pocket Edition 0.1 – 0.8 <b>chunks.dat</b> format: a 256 × 256-block world, 128 "
                                    "high, Overworld only. The area is centred on the spawn."))
        f.addRow(self.pe_hint)
        self._bta_rows(f)

        # ---- terrain
        self.terrain_heading = heading(tr("Terrain"), space_above=True)
        f.addRow(self.terrain_heading)
        self.blend = QCheckBox(tr("Game &blending"))
        self.blend.setChecked(True)
        self.blend.setToolTip(tr("Minecraft Java / Bedrock 1.18+ blends the converted chunks with the new terrain"))
        self.blend_row = with_help(self.blend, tr(HELP_BLEND))
        self.ring = QCheckBox(tr("Transition &ring"))
        self.ring.setChecked(True)
        self.ring.setToolTip(tr("Around the converted world, terrain generated as in the target game"))
        self.ring_row = with_help(self.ring, tr(HELP_RING))
        borders = QWidget()
        bl = QVBoxLayout(borders)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)
        bl.addWidget(self.blend_row)
        bl.addWidget(self.ring_row)
        self.borders = borders
        f.addRow(tr("Terrain border:"), borders)
        self.depth = QComboBox()
        self.depth.addItem(tr("Cut below y 0 (default)"), "cut")
        self.depth.addItem(tr("Keep everything (the world rises by 64 blocks)"), "keep")
        self.depth.addItem(tr("Keep from a chosen y"), "custom")
        self.depth.setToolTip(tr("What happens to what lies below y 0 in 1.18+ worlds"))
        self.depth_y = QSpinBox()
        self.depth_y.setRange(-64, -1)
        self.depth_y.setValue(-32)
        self.depth_y.setPrefix("y ")
        self.depth_y.setEnabled(False)
        self.depth.currentIndexChanged.connect(self._on_depth)
        self.depth_box = row(self.depth, self.depth_y, HelpButton(tr(HELP_DEPTH)), stretch=False)
        self.depth_box.layout().setStretch(0, 1)
        f.addRow(tr("&Underground of 1.18+ worlds:"), self.depth_box)
        self.tall = QComboBox()
        self.tall.addItem(tr("Compress (the surface comes down whole) – recommended"), "compress")
        self.tall.addItem(tr("Cut at the world's limit"), "cut")
        self.tall.setToolTip(tr("The terrain that does not fit the target game's height"))
        self.tall_box = row(self.tall, HelpButton(tr(HELP_TALL)), stretch=False)
        self.tall_box.layout().setStretch(0, 1)
        f.addRow(tr("&Tall mountains:"), self.tall_box)

        # ---- what is converted (chosen in the other tabs)
        f.addRow(heading(tr("What is converted"), space_above=True))
        self.scope_label = QLabel()
        self.scope_label.setWordWrap(True)
        b_map = QPushButton(tr("Choose on the map…"))
        b_map.setToolTip(tr("Chunks to convert, moving, spawn, biomes, Nether and End (Map and chunks tab)"))
        b_map.clicked.connect(lambda: self.tabs.setCurrentWidget(self.map_tab))
        self.scope_row = row(self.scope_label, b_map, stretch=False)
        self.scope_row.layout().setStretch(0, 1)
        f.addRow(tr("World:"), self.scope_row)
        self.players_label = QLabel()
        self.players_label.setWordWrap(True)
        b_pl = QPushButton(tr("Choose the players…"))
        b_pl.clicked.connect(lambda: self.tabs.setCurrentWidget(self.players_tab))
        pr = row(self.players_label, b_pl, stretch=False)
        pr.layout().setStretch(0, 1)
        f.addRow(tr("Players:"), pr)

        # ---- result
        f.addRow(heading(tr("Result"), space_above=True))
        self.name_edit = QLineEdit()
        self.name_edit.setPlaceholderText(tr("Same as the source world"))
        f.addRow(tr("World &name:"), self.name_edit)
        self.out_edit = QLineEdit(os.path.join(os.path.expanduser("~"), "WorldBridge"))
        b_out = QPushButton(theme.icon("folder-open", fallback=QStyle.SP_DirOpenIcon), tr("Browse…"))
        b_out.clicked.connect(self._pick_out)
        out_row = row(self.out_edit, b_out, stretch=False)
        out_row.layout().setStretch(0, 1)
        f.addRow(tr("Output &folder:"), out_row)
        f.addRow(HintLabel(tr("The converted world goes into a new folder in here; the source world is never "
                              "modified.")))

        self.logview = QPlainTextEdit()
        self.logview.setReadOnly(True)
        self.logview.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.logview.setMinimumHeight(220)
        self.log_box = Disclosure(tr("Conversion log"), self.logview)
        col.addSpacing(spacing(page))
        col.addWidget(self.log_box)
        col.addStretch(1)
        # the log takes the free height when it is open
        self.log_box.toggled.connect(lambda on: (col.setStretchFactor(self.log_box, 1 if on else 0),
                                                col.setStretch(col.count() - 1, 0 if on else 1)))
        scroll.setWidget(body)
        outer.addWidget(scroll, 1)
        return page

    def _java_rows(self, f: QFormLayout):
        self.java_ver = QComboBox()
        latest = ab.version_str(ab.latest("java"))
        self.java_ver.addItem(tr("{version} (latest) – best route automatically  [recommended]", version=latest),
                              ("auto", None, None))
        for v in reversed([v for v in ab.versions("java") if v >= (1, 13, 0)]):
            self.java_ver.addItem(tr("{version} – pre-converted blocks", version=ab.version_str(v)), ("amulet", v, None))
        self.java_ver.addItem(tr("1.9 → latest – upgraded by Minecraft when opened (DataFixer)"), ("dfu", None, None))
        for lim in ("1.12", "1.11", "1.10", "1.9", "1.8", "1.7", "1.6", "1.5", "1.4", "1.3", "1.2"):
            self.java_ver.addItem(tr("{version} – numeric Anvil format", version=lim + ".x"), ("numeric", None, lim))
        self.java_ver.addItem(tr("{version} – McRegion format", version="1.1"), ("mcregion", None, "1.1"))
        self.java_ver.addItem(tr("{version} – McRegion format", version="1.0"), ("mcregion", None, "1.0"))
        for lim, label in (("b1.8", "Beta 1.8"), ("b1.7", "Beta 1.7"), ("b1.6", "Beta 1.6"), ("b1.5", "Beta 1.5"),
                           ("b1.4", "Beta 1.4"), ("b1.3", "Beta 1.3")):
            self.java_ver.addItem(tr("{version} – McRegion format", version=label), ("mcregion", None, lim))
        self.java_ver.addItem(tr("{version} – Alpha format (World1…World5 folder)", version="Beta 1.0 – 1.2_02"),
                              ("alpha", None, "b1.2"))
        self.java_ver.addItem(tr("{version} – Alpha format (World1…World5 folder)", version="Alpha 1.0 – 1.2.6 / Infdev"),
                              ("alpha", None, "alpha"))
        f.addRow(tr("&Version:"), self.java_ver)
        self.java_ver.currentIndexChanged.connect(self._update_tall)
        self.java_hint = HintLabel(tr("Java 26.1+ worlds are written in the classic layout: on first start Minecraft "
                                      "migrates them to the new format by itself (dimensions/, players/)."))
        f.addRow(self.java_hint)
        self.alpha_hint = HintLabel(tr("Alpha and Beta up to 1.2_02 only see the worlds in the World1 … World5 folders "
                                       "of .minecraft/saves: the world is written into the first free one."))
        f.addRow(self.alpha_hint)

    def _bta_rows(self, f: QFormLayout):
        self.bta_heading = heading("Better than Adventure", space_above=True)
        f.addRow(self.bta_heading)
        self.bta_palette = QLineEdit()
        self.bta_palette.setPlaceholderText(tr("Default: woods chosen by the average colour of the textures"))
        self.bta_palette.setToolTip(tr(".properties file that chooses which vanilla wood each colour of BTA's painted "
                                       "wood becomes (example: worldbridge/bta/data/palette.example.properties)"))
        b_pal = QPushButton(tr("Browse…"))
        b_pal.clicked.connect(self._pick_bta_palette)
        self.bta_pal_row = row(self.bta_palette, b_pal, stretch=False)
        self.bta_pal_row.layout().setStretch(0, 1)
        f.addRow(tr("Wood palette:"), self.bta_pal_row)
        self.bta_auto_y = QCheckBox(tr("Automatic"))
        self.bta_auto_y.setChecked(True)
        self.bta_auto_y.setToolTip(tr("Lowers the Overworld so that BTA's sea matches the vanilla one (y 63): 65 blocks "
                                      "for “extended” worlds, 1 for the classic ones. BTA's underground ends up below "
                                      "y 0, so nothing is lost."))
        self.bta_y = QSpinBox()
        self.bta_y.setRange(0, 128)
        self.bta_y.setSuffix(" " + tr("blocks"))
        self.bta_y.setEnabled(False)
        self.bta_auto_y.toggled.connect(lambda on: self.bta_y.setEnabled(not on))
        self.bta_y_row = row(self.bta_auto_y, self.bta_y)
        f.addRow(tr("Lower the Overworld:"), self.bta_y_row)
        self.bta_note = HintLabel(tr("The world is written in the 1.18.2 format and upgraded by Minecraft 26.3 when "
                                     "opened (official DataFixer), which blends the new terrain with the converted "
                                     "one. The Drift becomes The End."))
        f.addRow(self.bta_note)
        self._bta_on = False

    def _lce_rows(self, f: QFormLayout):
        from ..lce.container import PLATFORMS

        self.lce_form = f
        self.lce_plat = QComboBox()
        for k, p in PLATFORMS.items():
            self.lce_plat.addItem(p.label, k)
        f.addRow(tr("&Platform:"), self.lce_plat)
        self.lce_prof = QComboBox()
        f.addRow(tr("Game version:"), self.lce_prof)
        self.lce_size = QComboBox()
        f.addRow(tr("World &size:"), self.lce_size)
        self.lce_center = QCheckBox(tr("Centre on the spawn"))
        self.lce_center.setChecked(True)
        self.lce_ox = QSpinBox()
        self.lce_oz = QSpinBox()
        for sb, lab in ((self.lce_ox, "X "), (self.lce_oz, "Z ")):
            sb.setRange(-1875000, 1875000)
            sb.setPrefix(lab)
            sb.setToolTip(tr("Chunk at the centre of the converted area"))
        self.lce_center.toggled.connect(lambda on: (self.lce_ox.setEnabled(not on), self.lce_oz.setEnabled(not on)))
        self.lce_ox.setEnabled(False)
        self.lce_oz.setEnabled(False)
        self.lce_area_row = row(self.lce_center, spacing(None, True), QLabel(tr("otherwise centre at chunk")),
                                self.lce_ox, self.lce_oz)
        f.addRow(tr("Area:"), self.lce_area_row)
        self.lce_xuid = QLineEdit()
        self.lce_xuid.setPlaceholderText("15885783760619110653")
        self.lce_xuid.setToolTip(tr(HELP_XUID))
        self.lce_xuid_row = QWidget()
        xr = QHBoxLayout(self.lce_xuid_row)
        xr.setContentsMargins(0, 0, 0, 0)
        xr.addWidget(self.lce_xuid, 1)
        b_xuid = QPushButton(tr("From my world…"))
        b_xuid.setToolTip(tr("Take the XUID from a world you have already played"))
        b_xuid.clicked.connect(self._xuid_from_save)
        xr.addWidget(b_xuid)
        xr.addWidget(HelpButton(tr(HELP_XUID)))
        f.addRow(tr("Player ID (optional):"), self.lce_xuid_row)
        self.lce_hint = HintLabel()
        f.addRow(self.lce_hint)
        self.lce_plat.currentIndexChanged.connect(self._on_lce_platform)
        self._on_lce_platform()

    def _pick_bta_palette(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Choose the BTA palette"), self.bta_palette.text() or os.path.expanduser("~"),
                                           tr("Palette") + " (*.properties);;" + tr("All files") + " (*)")
        if f:
            self.bta_palette.setText(f)

    def _set_bta_source(self, on: bool, auto_y: int = 0):
        """A Better than Adventure source converts only to Java 26.3."""
        model = self.edition.model()
        for i in range(self.edition.count()):
            item = model.item(i)
            if item is not None:
                item.setEnabled(not on or self.edition.itemData(i) == "java")
        if on:
            self.edition.setCurrentIndex(self.edition.findData("java"))
            self.java_ver.setCurrentIndex(0)
            if self.bta_auto_y.isChecked():
                self.bta_y.setValue(auto_y)
        self.java_ver.setEnabled(not on)
        self.blend.setEnabled(not on)
        if on:
            self.blend.setChecked(True)
        self._bta_on = on
        self._update_tall()

    def _on_edition(self):
        self._update_tall()
        if hasattr(self, "players_tab"):
            self.players_tab.set_family(self.edition.currentData())

    def _on_depth(self, _i=None):
        self.depth_y.setEnabled(self.depth.currentData() == "custom")
        self._refresh_rows()

    def _update_tall(self):
        if not all(hasattr(self, a) for a in ("tall", "ring", "bed_ver")):
            return
        fam = self.edition.currentData()
        low = fam == "pe_old" or (fam == "java" and self.java_ver.currentData()[0] in ("mcregion", "alpha"))
        # which of the two borders the target has: the game's blending (1.18+) or WorldBridge's ring
        new = False
        if fam == "java":
            mode, ver, _lim = self.java_ver.currentData()
            new = mode in ("auto", "dfu") or (mode == "amulet" and tuple(ver or (99,)) >= (1, 18))
        elif fam == "bedrock":
            new = tuple(self.bed_ver.currentData()) >= (1, 18)
        self.blend.setEnabled(new and self.java_ver.isEnabled())
        self.ring.setEnabled(not new and fam != "bedrock")
        # games whose world starts at y 0: the underground and the mountains of a 1.18+ world
        self.depth.setEnabled(not new)
        self.depth_y.setEnabled(not new and self.depth.currentData() == "custom")
        self.tall.setEnabled(low or not new)
        self._new_target = new
        self._refresh_rows()
        if hasattr(self, "map_tab"):
            self.map_tab.set_target_game(*self._target_game())

    def _refresh_rows(self):
        """Only the rows that matter for the chosen target (and source) are shown."""
        if not hasattr(self, "tall_box"):
            return
        f = self.form
        fam = self.edition.currentData()
        new = getattr(self, "_new_target", False)
        vis = {
            self.java_ver: fam == "java", self.java_hint: fam == "java" and self.java_ver.currentData()[0] in ("auto", "dfu")
            or (fam == "java" and self.java_ver.currentData()[0] == "amulet"
                and tuple(self.java_ver.currentData()[1] or ()) >= (26, 1)),
            self.alpha_hint: fam == "java" and self.java_ver.currentData()[0] == "alpha",
            self.bed_ver: fam == "bedrock",
            self.lce_plat: fam == "lce", self.lce_prof: fam == "lce", self.lce_size: fam == "lce",
            self.lce_area_row: fam == "lce", self.lce_hint: fam == "lce",
            self.lce_xuid_row: fam == "lce" and self.lce_plat.currentData() in ("win64", "xbox360", "xboxone"),
            self.pe_hint: fam == "pe_old",
            self.bta_heading: self._bta_on, self.bta_pal_row: self._bta_on, self.bta_y_row: self._bta_on,
            self.bta_note: self._bta_on,
        }
        blend_on = new
        ring_on = not new and fam != "bedrock"
        self.blend_row.setVisible(blend_on)
        self.ring_row.setVisible(ring_on)
        vis[self.borders] = blend_on or ring_on
        vis[self.depth_box] = self.depth.isEnabled()
        vis[self.tall_box] = self.tall.isEnabled()
        vis[self.terrain_heading] = blend_on or ring_on or self.depth.isEnabled() or self.tall.isEnabled()
        self.depth_y.setVisible(self.depth.currentData() == "custom")
        for w, on in vis.items():
            f.setRowVisible(w, bool(on))

    def _target_game(self):
        """(family, version) of the conversion's target, for the biomes it has."""
        fam = self.edition.currentData()
        if fam == "java":
            mode, ver, lim = self.java_ver.currentData()
            if mode == "amulet":
                return "java", tuple(ver)
            if mode in ("auto", "dfu"):
                # numeric sources go through a 1.12 hub (the game upgrades it), modern ones straight to the latest
                modern = getattr(self, "_src_kind", "") in ("java_modern", "bedrock")
                return "java", None if modern else (1, 12)
            if mode == "numeric":
                return "java", tuple(int(x) for x in lim.split("."))
            return "java", (1, 1)                               # McRegion / Alpha: no biomes stored
        if fam == "bedrock":
            return "bedrock", tuple(self.bed_ver.currentData())
        return fam, None

    def _on_lce_platform(self):
        """What the chosen platform offers: its versions (on PC only neoLegacy TU31), its world sizes
        (the old consoles only the Classic one), the player id where the game uses it, where the save goes."""
        from ..lce.container import PLATFORMS
        from ..lce.world import PROFILES, WORLD_SIZES, platform_profiles, platform_sizes

        key = self.lce_plat.currentData()
        keep_prof = self.lce_prof.currentData()
        self.lce_prof.clear()
        for k in platform_profiles(key):
            self.lce_prof.addItem(tr(PROFILES[k].label), k)
        self.lce_prof.setCurrentIndex(max(0, self.lce_prof.findData(keep_prof)))
        self.lce_prof.setEnabled(self.lce_prof.count() > 1)
        sizes = platform_sizes(key)
        keep = self.lce_size.currentData()
        self.lce_size.clear()
        if len(sizes) > 1:
            # automatic: an LCE world keeps its own size, any other world gets the biggest one
            auto = (tr("same as the source LCE world") if getattr(self, "_src_kind", "") == "lce"
                    else WORLD_SIZES[max(sizes)][0])
            self.lce_size.addItem(tr("Automatic ({size})", size=auto), 0)
        for size in sizes:
            self.lce_size.addItem(WORLD_SIZES[size][0], size)
        self.lce_size.setCurrentIndex(max(0, self.lce_size.findData(keep)))
        self.lce_size.setEnabled(len(sizes) > 1)
        p = PLATFORMS[key]
        files = f"<i>{p.default_file}</i>" + (" " + tr("and the <i>GAMEDATA_*</i> files") if p.split else "")
        where = (tr("copy the generated folder into <i>Windows64/GameHDD/</i>.") if key == "win64" else
                 tr("put {files} in place of those of an existing save of the console.", files=files))
        self.lce_hint.setText(tr("LCE worlds have a finite size: the chunks outside the chosen area are left out. "
                                 "Then {where}", where=where))
        self._refresh_rows()

    def _xuid_from_save(self):
        """The XUID of the user, from a world already played with it (players/<XUID>.dat, named inside)."""
        from ..lce.world import save_players

        f, _ = QFileDialog.getOpenFileName(self, tr("Choose one of your played worlds (saveData.ms, savegame.dat…)"),
                                           self.out_edit.text() or os.path.expanduser("~"),
                                           tr("LCE saves") + " (saveData.ms savegame.dat GAMEDATA*);;" + tr("All files") + " (*)")
        if not f:
            return
        try:
            players = {n: x for n, x in save_players(f).items() if x.isdigit()}
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, tr("Player ID"), tr("Cannot read the save:") + f"\n{e}")
            return
        if not players:
            QMessageBox.information(self, tr("Player ID"), tr("There is no player with an XUID in this world."))
            return
        items = [f"{n}  ({x})" for n, x in players.items()]
        choice, ok = (items[0], True) if len(items) == 1 else QInputDialog.getItem(
            self, tr("Player ID"), tr("Which one are you?"), items, 0, False)
        if ok:
            self.lce_xuid.setText(players[choice.rsplit("  (", 1)[0]])

    def _update_scope(self, *_a):
        """The conversion tab's summary of what the map and players tabs chose."""
        if not hasattr(self, "scope_label"):
            return
        self.scope_label.setText(self.map_tab.summary())
        self.players_label.setText(self.players_tab.summary())

    # ---------------------------------------------------------- source
    def _pick_src_dir(self):
        d = QFileDialog.getExistingDirectory(self, tr("Open the world folder"), self.src_edit.text() or os.path.expanduser("~"))
        if d:
            self.src_edit.setText(d)
            self._on_source_changed()

    def _pick_src_file(self):
        f, _ = QFileDialog.getOpenFileName(self, tr("Open the save file"), self.src_edit.text() or os.path.expanduser("~"),
                                           tr("Minecraft saves") + " (*.ms *.dat *.bin *.mclevel *.mine *.mcworld *.zip "
                                           "GAMEDATA*);;" + tr("All files") + " (*)")
        if f:
            self.src_edit.setText(f)
            self._on_source_changed()

    def _on_source_changed(self):
        path = self.src_edit.text().strip()
        if not path:
            return
        self.src_info.setText(tr("Analysing…"))
        self._run_thread(DetectWorker(path), "done", self._on_detected)

    def _on_detected(self, lines, kind: str, name: str):
        self.src_info.setText(format_summary(lines))
        self._src_kind = kind
        self._src_name = name
        self.setWindowTitle(f"{name} — {APP_NAME}" if kind and name else APP_NAME)
        self._on_lce_platform()                         # the automatic world size depends on the source
        self._update_tall()                             # and the biomes of an "auto" Java target
        auto_y = 0
        if kind == "bta":
            try:
                from ..bta.world import BtaWorld, auto_shift

                auto_y = auto_shift(BtaWorld(self.src_edit.text().strip()).world_type())
            except Exception:  # noqa: BLE001
                pass
        self._set_bta_source(kind == "bta", auto_y)
        self.map_tab.set_source(self.src_edit.text().strip() if kind else "")
        st, self._pending_state = self._pending_state, None
        if st is not None and kind:
            # the window was rebuilt in another language: the same choices on the same world
            self.players_tab.import_state(st["players"])
            self.map_tab.import_state(st["map"])
            for name in ("blend", "ring", "bta_auto_y", "bta_y"):
                w = getattr(self, name)
                w.setChecked(st[name]) if isinstance(w, QCheckBox) else w.setValue(st[name])
        if kind:
            self.manage_tab.follow_source(self.src_edit.text().strip())
        if not kind:
            self.players_tab.set_players([])
        self._update_scope()

    def _show_player(self, entry):
        self.tabs.setCurrentWidget(self.map_tab)
        self.map_tab.center_on_player(entry)

    def dragEnterEvent(self, e):  # noqa: N802
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dropEvent(self, e):  # noqa: N802
        urls = e.mimeData().urls()
        if urls:
            self.src_edit.setText(urls[0].toLocalFile())
            self._on_source_changed()

    def _pick_out(self):
        d = QFileDialog.getExistingDirectory(self, tr("Choose the output folder"), self.out_edit.text())
        if d:
            self.out_edit.setText(d)

    # ---------------------------------------------------------- run bar
    def _run_bar(self) -> QWidget:
        self.run_box = QWidget()
        h = QHBoxLayout(self.run_box)
        h.setContentsMargins(0, 0, 0, 0)
        self.bar = QProgressBar()
        self.bar.setRange(0, 1000)
        self.bar.setFormat(tr("Ready"))
        self.bar.setTextVisible(True)
        self.bar.hide()
        h.addWidget(self.bar, 1)
        self.run_hint = HintLabel(tr("Every tab except “World management” prepares this conversion."), wrap=False)
        h.addWidget(self.run_hint, 1)
        self.btn_open = QPushButton(theme.icon("folder-open", fallback=QStyle.SP_DirOpenIcon), tr("Open the result folder"))
        self.btn_open.setEnabled(False)
        self.btn_open.hide()
        self.btn_open.clicked.connect(self._open_result)
        h.addWidget(self.btn_open)
        self.btn_cancel = QPushButton(theme.icon("process-stop", "dialog-cancel", fallback=QStyle.SP_DialogCancelButton),
                                      tr("&Cancel"))
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.hide()
        self.btn_cancel.clicked.connect(self._cancel)
        h.addWidget(self.btn_cancel)
        self.btn_convert = QPushButton(theme.icon("media-playback-start", "system-run", fallback=QStyle.SP_MediaPlay),
                                       tr("C&onvert"))
        self.btn_convert.setDefault(True)
        self.btn_convert.setToolTip(tr("Convert the world with the choices of these tabs (Ctrl+Enter)"))
        self.btn_convert.clicked.connect(self._start)
        h.addWidget(self.btn_convert)
        return self.run_box

    def _on_tab(self, i: int):
        """The conversion's buttons belong to the conversion tabs, not to the world's management."""
        self.run_box.setVisible(self.tabs.widget(i) is not self.manage_tab)

    # ---------------------------------------------------------- run
    def _target(self) -> TargetSpec:
        fam = self.edition.currentData()
        t = TargetSpec(family=fam, world_name=self.name_edit.text().strip() or None, blend=self.blend.isChecked(), ring=self.ring.isChecked(),
                       tall_terrain=self.tall.currentData(),
                       regen=self.map_tab.regen_dims(),
                       depth=self.depth_y.value() if self.depth.currentData() == "custom" else self.depth.currentData())
        if fam == "java":
            mode, ver, lim = self.java_ver.currentData()
            t.java_mode, t.version, t.java_version_limit = mode, ver, lim
        elif fam == "bedrock":
            t.version = tuple(self.bed_ver.currentData())
        elif fam == "lce":
            t.lce_platform = self.lce_plat.currentData()
            t.lce_profile = self.lce_prof.currentData()
            t.lce_world_size = self.lce_size.currentData()
            t.lce_center_on_spawn = self.lce_center.isChecked()
            t.lce_offset = (self.lce_ox.value(), self.lce_oz.value())
            t.lce_player_id = self.lce_xuid.text().strip() or None
        if self._src_kind == "bta":
            t.bta_palette = self.bta_palette.text().strip() or None
            t.bta_y_offset = None if self.bta_auto_y.isChecked() else self.bta_y.value()
        sel = Selection(chunks=self.map_tab.chunk_selection(), spawn=self.map_tab.spawn(), players=self.players_tab.links(),
                        biomes=self.map_tab.biome_overrides(), move_to=self.map_tab.move_target())
        t.selection = sel if sel.active else None
        return t

    def _output_dir(self, target: TargetSpec) -> str:
        src = self.src_edit.text().strip().rstrip("/\\")
        base = target.world_name or self._src_name or os.path.splitext(os.path.basename(src))[0] or "world"
        if base.lower() in ("savedata", "savegame", "gamedata", "level", "db"):
            base = os.path.basename(os.path.dirname(src)) or base
        base = re.sub(r"[^\w\- ]+", "_", base).strip() or "world"
        if target.family == "java" and target.java_mode == "alpha":
            # Alpha - Beta 1.2 only list the folders World1 ... World5 of the saves folder
            for i in range(1, 6):
                final = os.path.join(self.out_edit.text().strip(), f"World{i}")
                if not (os.path.exists(final) and os.listdir(final)):
                    return final
        suffix = {"java": "Java", "bedrock": "Bedrock", "lce": "LCE_" + target.lce_platform, "pe_old": "PE"}[target.family]
        out = os.path.join(self.out_edit.text().strip(), f"{base}_{suffix}")
        n = 2
        final = out
        while os.path.exists(final) and os.listdir(final):
            final = f"{out}_{n}"
            n += 1
        return final

    def _start(self):
        src = self.src_edit.text().strip()
        if not src or not os.path.exists(src):
            self.tabs.setCurrentIndex(0)
            self.message.show_message("negative", tr("Open the world to convert first: drop it into the window or use "
                                                     "“Open folder…” / “Open file…” at the top."),
                                      ((tr("Open folder…"), self._pick_src_dir),))
            return
        target = self._target()
        sel = target.selection
        if sel is not None and sel.chunks is not None and not sel.count():
            self.tabs.setCurrentIndex(0)
            self.message.show_message("negative", tr("You chose “Selected chunks only” but no chunk is selected on the "
                                                     "map."),
                                      ((tr("Go to the map"), lambda: self.tabs.setCurrentWidget(self.map_tab)),
                                       (tr("Convert the whole world"), self._convert_all)))
            return
        out = self._output_dir(target)
        self.tabs.setCurrentIndex(0)
        self.message.dismiss()
        self.logview.clear()
        self.log_box.set_open(True)
        self._log(f"→ Output: {out}")
        if target.family == "java" and target.java_mode == "alpha":
            self._log("   " + tr("Alpha and Beta up to 1.2_02 only see the worlds in the World1 … World5 folders of "
                                 ".minecraft/saves: copy the folder as it is (the folder's name is the world slot)."))
        self.btn_convert.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.btn_cancel.show()
        self.btn_open.setEnabled(False)
        self.btn_open.hide()
        self.run_hint.hide()
        self.bar.show()
        self.bar.setValue(0)
        self.bar.setFormat(tr("Starting…"))
        self.map_tab.pause_preview(True)          # the conversion reads the world at full speed
        self._worker = ConvertWorker(src, out, target)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._log)
        self._run_thread(self._worker, "finished", self._on_finished)

    def _convert_all(self):
        self.map_tab.scope_all.setChecked(True)
        self._start()

    def _cancel(self):
        if self._worker:
            self._worker.cancel()
            self.btn_cancel.setEnabled(False)
            self._log(tr("Cancelling…"))

    def _on_progress(self, frac: float, msg: str):
        self.bar.setValue(int(frac * 1000))
        self.bar.setFormat(f"{frac * 100:.0f}%  –  {msg}")

    def _log(self, msg: str):
        self.logview.appendPlainText(msg)

    def _on_finished(self, ok: bool, msg: str, warnings: list):
        self.map_tab.pause_preview(False)
        self.btn_convert.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self.btn_cancel.hide()
        self._worker = None
        if ok:
            self._result_path = msg if os.path.isdir(msg) else os.path.dirname(msg)
            self.btn_open.setEnabled(True)
            self.btn_open.show()
            self.bar.setValue(1000)
            self.bar.setFormat(tr("Completed"))
            text = "<b>" + tr("Conversion completed.") + f"</b><br>{_esc(msg)}"
            if warnings:
                text += "<br><br>" + tr("Warnings:") + "<ul style='margin:0'>" + "".join(
                    f"<li>{_esc(w)}</li>" for w in warnings[:12]) + "</ul>"
                if len(warnings) > 12:
                    text += tr("… and {n} more (in the log).", n=len(warnings) - 12)
                for w in warnings:
                    self._log("⚠ " + w)
            self.message.show_message("neutral" if warnings else "positive", text,
                                      ((tr("Open the folder"), self._open_result),))
        else:
            self.bar.setFormat(tr("Stopped"))
            self._log("✖ " + msg)
            self.message.show_message("negative", "<b>" + tr("Conversion failed.") + f"</b><br>{_esc(msg)}<br>"
                                      + tr("The details are in the log below."))
        self.tabs.setCurrentIndex(0)
        QApplication.alert(self)                 # the window asks for attention if it is in the background

    def _open_result(self):
        if self._result_path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._result_path))

    def _run_thread(self, worker: QObject, signal: str, slot):
        th = QThread(self)
        worker.moveToThread(th)
        th.started.connect(worker.run)
        getattr(worker, signal).connect(slot)
        getattr(worker, signal).connect(th.quit)
        th.finished.connect(lambda: self._threads.remove((th, worker)) if (th, worker) in self._threads else None)
        self._threads.append((th, worker))
        th.start()

    # ---------------------------------------------------------- remembered between sessions
    def _restore(self):
        s = QSettings()
        geo = s.value("window/geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        out = s.value("convert/output")
        if out:
            self.out_edit.setText(str(out))
        ed = s.value("convert/edition")
        if ed and self.edition.findData(ed) >= 0:
            self.edition.setCurrentIndex(self.edition.findData(ed))
        self.map_tab.restore_state(s)

    def _save_state(self):
        s = QSettings()
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("convert/output", self.out_edit.text().strip())
        s.setValue("convert/edition", self.edition.currentData())
        self.map_tab.save_state(s)

    def closeEvent(self, e):  # noqa: N802
        if self._remember:
            self._save_state()
        self.map_tab.shutdown()
        if self._worker:
            self._worker.cancel()
        for th, _w in list(self._threads):
            th.quit()
            th.wait(3000)
        super().closeEvent(e)


def main() -> int:
    app = theme.setup_application(sys.argv)
    saved = QSettings().value("ui/language")
    i18n.set_language(str(saved) if saved else None)
    _install_qt_translations()
    w = MainWindow()
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        w.src_edit.setText(sys.argv[1])
        w._on_source_changed()
    w.show()
    app._wb_window = w
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
