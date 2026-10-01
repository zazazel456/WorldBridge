"""The "Mappa" tab: an MCA Selector-like top-down view of the source world.

* mouse wheel = zoom around the cursor, middle button (or Space / "Sposta" mode) = move;
* "Seleziona" mode: drag = select the chunks in the rectangle, Ctrl + drag or right button =
  deselect, Shift + click = a whole region (32 × 32 chunks), click = toggle one chunk;
* "Spawn" mode: click = new world spawn (Y = top block + 1);
* selections are saved / loaded as MCA Selector CSV files.
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Set, Tuple

import numpy as np
from PySide6.QtCore import QObject, QPoint, QPointF, QRect, QRectF, Qt, QThread, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QFont, QImage, QKeySequence, QPainter, QPen
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QFileDialog, QFormLayout, QGridLayout, QHBoxLayout, QLabel, QMenu, QMessageBox,
    QPushButton, QRadioButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStyle, QToolBar, QToolButton,
    QVBoxLayout, QWidget, QWidgetAction,
)

from ..model import NETHER, OVERWORLD, THE_END, Progress
from ..i18n import N_, tr
from . import theme
from .trimui import CopyWorker, EditWorker, ScanWorker, TrimSettings
from .widgets import GuiThread, HelpButton, HintLabel, heading, row, spacing, with_help

DIM_NAMES = {OVERWORLD: "Overworld", NETHER: "Nether", THE_END: "End"}
Chunk = Tuple[int, int]

HELP_MOVE = N_("In the converted world the selected chunks do not stay at their coordinates: the centre of the "
               "selection goes to the centre of the world (0, 0) or to the chosen coordinates. Useful for finite "
               "worlds (LCE, Pocket Edition) or to bring a build near the spawn.")
HELP_REGEN = N_("A regenerated dimension is not converted: the game generates it anew, with its generator and the "
                "world's seed, the first time you enter it; the players who were there go back to the spawn.\n"
                "If you convert it instead, WorldBridge writes a ring of the game's terrain (Java Alpha 1.2 – 1.17) "
                "around the converted part that joins it smoothly.")
HELP_BIOME = N_("The biome the selected chunks will have in the converted world (colour of grass and water, weather, "
                "creatures): the list is the target game's and version's, with its names. Java Alpha / Beta and "
                "Pocket Edition 0.x do not store biomes: there they cannot be changed.")


# ============================================================ background loader


class MapLoader(QObject):
    """Opens the world once and renders the chunks of one dimension at a time (worker thread)."""

    meta = Signal(object)             # dict(dims, spawn, players, counts, description)
    batch = Signal(int, object)       # dim, [(cx, cz, rgb[16,16,3], height, index, names)]
    progress = Signal(int, int, int)  # dim, done, total
    failed = Signal(str)
    dim_done = Signal(int)

    def __init__(self, path: str):
        super().__init__()
        self.path = path
        self.src = None
        self._stop = False
        self._queue: List[int] = []
        # where the user looks (dim -> chunk): the tiles load from there outwards; set from the GUI thread
        self.focus: Dict[int, Chunk] = {}
        self.paused = False             # a conversion is running: the preview waits

    def stop(self):
        self._stop = True

    def _order(self, arr: np.ndarray, focus: Chunk) -> np.ndarray:
        """Concentric circles around ``focus``: region by region (each region file is read once), and
        inside a region from the nearest chunk."""
        fx, fz = focus
        rd = ((arr[:, 0] >> 5) * 32 + 16 - fx) ** 2 + ((arr[:, 1] >> 5) * 32 + 16 - fz) ** 2
        cd = (arr[:, 0] - fx) ** 2 + (arr[:, 1] - fz) ** 2
        return np.lexsort((cd, rd))

    def _default_focus(self, dim: int) -> Chunk:
        sx, _sy, sz = (int(v) for v in (self.src.spawn or (0, 0, 0)))
        if dim == NETHER:
            return (sx // 8) >> 4, (sz // 8) >> 4
        if dim == THE_END:
            return 0, 0
        return sx >> 4, sz >> 4

    def open(self):
        try:
            from ..mapview import open_map

            self.src = open_map(self.path, Progress())
            dims = self.src.dimensions()
            counts = {d: len(self.src.chunk_coords(d)) for d in dims}
            self.meta.emit({"dims": dims, "spawn": self.src.spawn, "players": self.src.players, "counts": counts,
                            "description": self.src.description, "kind": self.src.kind})
        except Exception as ex:  # noqa: BLE001
            self.failed.emit(str(ex))

    def render(self, dim: int):
        if self.src is None:
            return
        from ..mapview import shade

        self._stop = False
        try:
            coords = self.src.chunk_coords(dim)
        except Exception as ex:  # noqa: BLE001
            self.failed.emit(str(ex))
            return
        total = len(coords)
        last_rows: Dict[Chunk, np.ndarray] = {}
        out = []
        t = time.time()
        arr = np.array(coords, dtype=np.int64).reshape(-1, 2)
        focus = self.focus.get(dim) or self._default_focus(dim)
        todo = arr[self._order(arr, focus)] if len(arr) else arr

        def feed():
            """The chunks in the order they are drawn, re-sorted when the user looks elsewhere (read
            a little ahead of the drawing by the worker processes)."""
            nonlocal todo, focus
            pos = 0
            sorted_at = time.time()
            while pos < len(todo):
                now_focus = self.focus.get(dim)
                if (now_focus is not None and max(abs(now_focus[0] - focus[0]), abs(now_focus[1] - focus[1])) > 4
                        and time.time() - sorted_at > 0.5):
                    focus = now_focus                       # the user moved: what is on screen first
                    sorted_at = time.time()
                    rest = todo[pos:]
                    todo = np.concatenate([todo[:pos], rest[self._order(rest, focus)]])
                yield int(todo[pos][0]), int(todo[pos][1])
                pos += 1

        from ..mapview import map_tile, parallel_safe
        from ..parallel import ordered_map

        # the tiles are made on every core; the shading, which looks at the chunk to the north, here in order
        tiles = ordered_map(map_tile, (self.src, dim), feed(), batch=16,
                            n_workers=None if parallel_safe(self.src) else 1)
        try:
            for i, (cx, cz, tile) in enumerate(tiles):
                if self._stop:
                    return
                while self.paused and not self._stop:
                    time.sleep(0.2)
                if tile is not None:
                    north = last_rows.get((cx, cz - 1))
                    rgb = shade(tile, north)
                    last_rows[(cx, cz)] = tile.height[15].astype(np.int32)
                    out.append((cx, cz, rgb, tile.height, tile.index, tile.names))
                if out and (len(out) >= 96 or time.time() - t > 0.15):
                    self.batch.emit(dim, out)
                    self.progress.emit(dim, i + 1, total)
                    out = []
                    t = time.time()
        finally:
            tiles.close()                                   # stops the worker processes
        if out:
            self.batch.emit(dim, out)
        self.progress.emit(dim, total, total)
        self.dim_done.emit(dim)

    def close(self):
        if self.src is not None:
            try:
                self.src.close()
            except Exception:  # noqa: BLE001
                pass
            self.src = None


class _Bridge(QObject):
    """Queued calls into the loader's thread."""

    open = Signal()
    render = Signal(int)
    close = Signal()


# ============================================================ canvas


def _label(p: QPainter, pos: QPointF, text: str, color: QColor):
    """Text with a dark rounded background, readable over any terrain."""
    fm = p.fontMetrics()
    r = QRectF(pos.x(), pos.y() - fm.ascent() - 2, fm.horizontalAdvance(text) + 8, fm.height() + 3)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(15, 17, 20, 190))
    p.drawRoundedRect(r, 3, 3)
    p.setPen(color)
    p.drawText(QPointF(pos.x() + 4, pos.y()), text)


class MapCanvas(QWidget):
    hover = Signal(str)
    spawn_picked = Signal(int, int, int)
    selection_changed = Signal()

    MODE_PAN, MODE_SELECT, MODE_SPAWN = range(3)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(360)
        self.mode = self.MODE_SELECT
        self.dim = OVERWORLD
        self.scale = 1.0                 # screen pixels per block
        self.center = QPointF(0, 0)      # block coordinates at the centre of the widget
        self.regions: Dict[int, Dict[Chunk, QImage]] = {}
        self.info: Dict[int, Dict[Chunk, Tuple[np.ndarray, np.ndarray, List[str]]]] = {}
        self.present: Dict[int, Set[Chunk]] = {}
        self.selection: Dict[int, Set[Chunk]] = {}
        self._sel_img: Dict[Tuple[int, int, int], QImage] = {}
        self.spawn: Optional[Tuple[int, int, int]] = None
        self.orig_spawn: Optional[Tuple[int, int, int]] = None
        self.players = []
        self.heat: Dict[int, Dict[Chunk, Optional[int]]] = {}   # InhabitedTime (world trim)
        self.heat_min = 1200
        self.show_heat = False
        self._heat_img: Dict[Tuple[int, int, int], QImage] = {}
        self._drag = None                # (kind, start_pos, start_center / start_block, remove)
        self._rubber: Optional[QRect] = None
        self._space = False

    # ---------------------------------------------------------- data
    def reset(self):
        self.regions.clear()
        self.info.clear()
        self.present.clear()
        self.selection.clear()
        self._sel_img.clear()
        self.spawn = self.orig_spawn = None
        self.players = []
        self.heat.clear()
        self._heat_img.clear()
        self.update()

    def set_heat(self, heat, min_ticks: int, show: bool):
        """InhabitedTime of the chunks (from a world trim scan) and whether to draw it."""
        if heat is not None:
            self.heat = heat
        self.heat_min = min_ticks
        self.show_heat = show
        self._heat_img.clear()
        self.update()

    def set_selection(self, selection: Dict[int, Set[Chunk]]):
        """Replaces the selection of every dimension in ``selection``."""
        for d, chunks in selection.items():
            self.selection[d] = set(chunks)
        self._sel_img.clear()
        self.selection_changed.emit()
        self.update()

    def _heat_image(self, rx: int, rz: int) -> Optional[QImage]:
        key = (self.dim, rx, rz)
        img = self._heat_img.get(key)
        if img is None:
            arr = np.zeros((32, 32, 4), np.uint8)
            lo = max(1, self.heat_min)
            span = math.log(max(lo * 2, 72000 * 10) / lo)  # threshold .. 10 hours
            for (cx, cz), t in self.heat.get(self.dim, {}).items():
                if cx >> 5 != rx or cz >> 5 != rz:
                    continue
                if t is None:
                    col = (140, 140, 160, 120)
                elif t < self.heat_min:
                    col = (230, 40, 40, 150)
                else:
                    f = min(1.0, math.log(max(t, lo) / lo) / span)
                    col = (int(250 - 200 * f), int(210 + 20 * f), int(40 + 20 * f), 120)
                arr[cz - rz * 32, cx - rx * 32] = col
            if not arr[..., 3].any():
                self._heat_img[key] = QImage()
                return None
            img = self._heat_img[key] = QImage(arr.data, 32, 32, 128, QImage.Format_RGBA8888).copy()
        return None if img.isNull() else img

    def add_tiles(self, dim: int, tiles):
        regs = self.regions.setdefault(dim, {})
        info = self.info.setdefault(dim, {})
        pres = self.present.setdefault(dim, set())
        painters = {}
        for cx, cz, rgb, height, index, names in tiles:
            key = (cx >> 5, cz >> 5)
            img = regs.get(key)
            if img is None:
                img = regs[key] = QImage(512, 512, QImage.Format_ARGB32_Premultiplied)
                img.fill(Qt.transparent)
            p = painters.get(key)
            if p is None:
                p = painters[key] = QPainter(img)
            chunk = QImage(np.ascontiguousarray(rgb).data, 16, 16, 48, QImage.Format_RGB888).copy()
            p.drawImage((cx & 31) * 16, (cz & 31) * 16, chunk)
            info[(cx, cz)] = (height, index.astype(np.uint16), names)
            pres.add((cx, cz))
        for p in painters.values():
            p.end()
        self.update()

    def center_on(self, x: float, z: float):
        self.center = QPointF(x, z)
        self.update()

    def fit(self, dim: int):
        pres = self.present.get(dim)
        if not pres:
            return
        xs = [c[0] for c in pres]
        zs = [c[1] for c in pres]
        w = (max(xs) - min(xs) + 1) * 16
        h = (max(zs) - min(zs) + 1) * 16
        self.center = QPointF((min(xs) * 16 + w / 2), (min(zs) * 16 + h / 2))
        self.scale = max(1 / 32, min(8.0, 0.92 * min(self.width() / max(w, 1), self.height() / max(h, 1))))
        self.update()

    # ---------------------------------------------------------- coordinates
    def to_block(self, pos) -> QPointF:
        return QPointF(self.center.x() + (pos.x() - self.width() / 2) / self.scale,
                       self.center.y() + (pos.y() - self.height() / 2) / self.scale)

    def to_screen(self, x: float, z: float) -> QPointF:
        return QPointF((x - self.center.x()) * self.scale + self.width() / 2,
                       (z - self.center.y()) * self.scale + self.height() / 2)

    # ---------------------------------------------------------- selection
    def selected(self, dim: Optional[int] = None) -> Set[Chunk]:
        return self.selection.setdefault(self.dim if dim is None else dim, set())

    def _mark_dirty(self, chunks):
        for cx, cz in chunks:
            self._sel_img.pop((self.dim, cx >> 5, cz >> 5), None)

    def set_chunks(self, chunks, on: bool, dim: Optional[int] = None):
        s = self.selected(dim)
        chunks = list(chunks)
        if on:
            s.update(chunks)
        else:
            s.difference_update(chunks)
        self._mark_dirty(chunks)
        self.selection_changed.emit()
        self.update()

    def select_all(self):
        self.set_chunks(self.present.get(self.dim, set()), True)

    def clear_selection(self):
        s = self.selected()
        old = list(s)
        s.clear()
        self._mark_dirty(old)
        self.selection_changed.emit()
        self.update()

    def invert(self):
        pres = self.present.get(self.dim, set())
        s = self.selected()
        new = pres - s
        self._mark_dirty(pres | s)
        self.selection[self.dim] = set(new)
        self.selection_changed.emit()
        self.update()

    def _selection_image(self, rx: int, rz: int) -> Optional[QImage]:
        key = (self.dim, rx, rz)
        img = self._sel_img.get(key)
        if img is None:
            s = self.selection.get(self.dim, set())
            arr = np.zeros((32, 32, 4), np.uint8)
            base_x, base_z = rx * 32, rz * 32
            for cx, cz in s:
                if cx >> 5 == rx and cz >> 5 == rz:
                    arr[cz - base_z, cx - base_x] = (60, 150, 255, 110)
            if not arr[..., 3].any():
                self._sel_img[key] = QImage()
                return None
            img = QImage(arr.data, 32, 32, 128, QImage.Format_RGBA8888).copy()
            self._sel_img[key] = img
        return None if img.isNull() else img

    # ---------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(24, 26, 30))
        tl = self.to_block(QPoint(0, 0))
        br = self.to_block(QPoint(self.width(), self.height()))
        rx0, rz0 = math.floor(tl.x() / 512), math.floor(tl.y() / 512)
        rx1, rz1 = math.floor(br.x() / 512), math.floor(br.y() / 512)
        p.setRenderHint(QPainter.SmoothPixmapTransform, self.scale < 1)
        regs = self.regions.get(self.dim, {})
        sel_regions = {(cx >> 5, cz >> 5) for cx, cz in self.selection.get(self.dim, ())}
        for (rx, rz), img in regs.items():
            if rx0 <= rx <= rx1 and rz0 <= rz <= rz1:
                a = self.to_screen(rx * 512, rz * 512)
                p.drawImage(QRectF(a.x(), a.y(), 512 * self.scale, 512 * self.scale), img)
        p.setRenderHint(QPainter.SmoothPixmapTransform, False)
        if self.show_heat and self.heat.get(self.dim):
            for rx, rz in {(cx >> 5, cz >> 5) for cx, cz in self.heat[self.dim]}:
                if rx0 <= rx <= rx1 and rz0 <= rz <= rz1:
                    img = self._heat_image(rx, rz)
                    if img is not None:
                        a = self.to_screen(rx * 512, rz * 512)
                        p.drawImage(QRectF(a.x(), a.y(), 512 * self.scale, 512 * self.scale), img)
        for rx, rz in sel_regions:
            if rx0 <= rx <= rx1 and rz0 <= rz <= rz1:
                img = self._selection_image(rx, rz)
                if img is not None:
                    a = self.to_screen(rx * 512, rz * 512)
                    p.drawImage(QRectF(a.x(), a.y(), 512 * self.scale, 512 * self.scale), img)
        # chunk grid (zoomed in) and region grid
        if self.scale >= 1.5:
            p.setPen(QPen(QColor(255, 255, 255, 28), 1))
            x = math.floor(tl.x() / 16) * 16
            while x <= br.x():
                sx = self.to_screen(x, 0).x()
                p.drawLine(int(sx), 0, int(sx), self.height())
                x += 16
            z = math.floor(tl.y() / 16) * 16
            while z <= br.y():
                sz = self.to_screen(0, z).y()
                p.drawLine(0, int(sz), self.width(), int(sz))
                z += 16
        p.setPen(QPen(QColor(255, 255, 255, 70), 1))
        for rx in range(rx0, rx1 + 2):
            sx = self.to_screen(rx * 512, 0).x()
            p.drawLine(int(sx), 0, int(sx), self.height())
        for rz in range(rz0, rz1 + 2):
            sz = self.to_screen(0, rz * 512).y()
            p.drawLine(0, int(sz), self.width(), int(sz))
        # markers
        f = QFont(self.font())
        f.setPointSize(max(8, f.pointSize() - 1))
        p.setFont(f)
        for pl in self.players:
            if pl.pos is None or pl.dim != self.dim:
                continue
            s = self.to_screen(pl.pos[0], pl.pos[2])
            p.setPen(QPen(QColor(20, 20, 20), 2))
            p.setBrush(QBrush(QColor(255, 210, 60)))
            p.drawEllipse(s, 5, 5)
            _label(p, s + QPointF(8, 4), pl.name or (tr("Main player") if pl.key == "host" else pl.key[:20]),
                   QColor(255, 230, 140))
        if self.dim == OVERWORLD:
            if self.orig_spawn and self.spawn != self.orig_spawn:
                s = self.to_screen(self.orig_spawn[0] + 0.5, self.orig_spawn[2] + 0.5)
                p.setPen(QPen(QColor(200, 200, 200, 160), 2, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(s, 7, 7)
            if self.spawn:
                s = self.to_screen(self.spawn[0] + 0.5, self.spawn[2] + 0.5)
                p.setPen(QPen(QColor(20, 20, 20), 3))
                p.drawLine(s + QPointF(-9, 0), s + QPointF(9, 0))
                p.drawLine(s + QPointF(0, -9), s + QPointF(0, 9))
                p.setPen(QPen(QColor(255, 70, 70), 2))
                p.drawLine(s + QPointF(-8, 0), s + QPointF(8, 0))
                p.drawLine(s + QPointF(0, -8), s + QPointF(0, 8))
                _label(p, s + QPointF(11, -7), f"Spawn {self.spawn[0]}, {self.spawn[1]}, {self.spawn[2]}", QColor(255, 120, 120))
        if self._rubber is not None:
            remove = self._drag and self._drag[3]
            col = QColor(255, 90, 90) if remove else QColor(90, 170, 255)
            p.setPen(QPen(col, 1, Qt.DashLine))
            col.setAlpha(40)
            p.setBrush(col)
            p.drawRect(self._rubber)
        if not regs:
            p.setPen(QColor(140, 145, 155))
            p.drawText(self.rect(), Qt.AlignCenter, tr("Choose a source world: the map is drawn here."))
        p.end()

    # ---------------------------------------------------------- mouse
    def _chunk_at(self, pos) -> Chunk:
        b = self.to_block(pos)
        return math.floor(b.x()) >> 4, math.floor(b.y()) >> 4

    def wheelEvent(self, e):
        before = self.to_block(e.position())
        factor = 1.25 if e.angleDelta().y() > 0 else 0.8
        self.scale = max(1 / 32, min(32.0, self.scale * factor))
        after = self.to_block(e.position())
        self.center += before - after
        self.update()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space:
            self._space = True
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space:
            self._space = False
        super().keyReleaseEvent(e)

    def mousePressEvent(self, e):
        pan = (e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and (self.mode == self.MODE_PAN or self._space)))
        if pan:
            self._drag = ("pan", e.position(), QPointF(self.center), False)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if self.mode == self.MODE_SPAWN and e.button() == Qt.LeftButton:
            b = self.to_block(e.position())
            x, z = math.floor(b.x()), math.floor(b.y())
            y = self._height(x, z)
            self.spawn = (x, (y + 1) if y is not None else 64, z)
            self.spawn_picked.emit(*self.spawn)
            self.update()
            return
        if self.mode == self.MODE_SELECT and e.button() in (Qt.LeftButton, Qt.RightButton):
            remove = e.button() == Qt.RightButton or bool(e.modifiers() & Qt.ControlModifier)
            self._drag = ("sel", e.position(), None, remove, bool(e.modifiers() & Qt.ShiftModifier))
            self._rubber = None

    def mouseMoveEvent(self, e):
        self._emit_hover(e.position())
        if not self._drag:
            return
        if self._drag[0] == "pan":
            d = e.position() - self._drag[1]
            self.center = self._drag[2] - QPointF(d.x() / self.scale, d.y() / self.scale)
            self.update()
        elif self._drag[0] == "sel":
            a = self._drag[1].toPoint()
            b = e.position().toPoint()
            if (a - b).manhattanLength() > 4:
                self._rubber = QRect(a, b).normalized()
                self.update()

    def mouseReleaseEvent(self, e):
        if not self._drag:
            return
        kind = self._drag[0]
        if kind == "sel":
            remove, whole_region = self._drag[3], self._drag[4]
            if self._rubber is not None:
                c0 = self._chunk_at(self._rubber.topLeft())
                c1 = self._chunk_at(self._rubber.bottomRight())
                chunks = [(x, z) for x in range(c0[0], c1[0] + 1) for z in range(c0[1], c1[1] + 1)]
                pres = self.present.get(self.dim, set())
                self.set_chunks([c for c in chunks if c in pres] if pres else chunks, not remove)
            else:
                cx, cz = self._chunk_at(e.position())
                if whole_region:
                    rx, rz = cx >> 5, cz >> 5
                    pres = self.present.get(self.dim, set())
                    region = [(rx * 32 + x, rz * 32 + z) for x in range(32) for z in range(32)]
                    self.set_chunks([c for c in region if c in pres] if pres else region, not remove)
                else:
                    on = not remove and (cx, cz) not in self.selected()
                    self.set_chunks([(cx, cz)], on)
        self._drag = None
        self._rubber = None
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def _height(self, x: int, z: int) -> Optional[int]:
        info = self.info.get(self.dim, {}).get((x >> 4, z >> 4))
        if info is None:
            return None
        h = int(info[0][z & 15, x & 15])
        return None if h == -32768 else h

    def _emit_hover(self, pos):
        b = self.to_block(pos)
        x, z = math.floor(b.x()), math.floor(b.y())
        cx, cz = x >> 4, z >> 4
        text = tr("X {x}  Z {z}   ·   chunk {cx}, {cz}   ·   region r.{rx}.{rz}", x=x, z=z, cx=cx, cz=cz, rx=cx >> 5, rz=cz >> 5)
        info = self.info.get(self.dim, {}).get((cx, cz))
        if info is not None:
            h, idx, names = info
            y = int(h[z & 15, x & 15])
            if y != -32768:
                text += f"   ·   {names[int(idx[z & 15, x & 15])].split(':', 1)[-1]}  (Y {y})"
        heat = self.heat.get(self.dim)
        if heat is not None and (cx, cz) in heat:
            from ..trim import format_ticks

            t = heat[(cx, cz)]
            text += "   ·   InhabitedTime " + ("?" if t is None else format_ticks(t))
        if (cx, cz) in self.selection.get(self.dim, ()):
            text += "   ·   " + tr("selected")
        self.hover.emit(text)


# ============================================================ tab


class MapTab(QWidget):
    """Map + tools; owns the loader thread for the current source world.

    Layout (KDE HIG "Layout and navigation"): a toolbar above the map (dimension, what a click
    does, the selection's menu, zoom to fit, world trim), the map as the main content, and on its
    trailing side a panel with what the selection is used for: first the choices of the conversion,
    then, apart, the changes made straight on the source world."""

    players_loaded = Signal(object)   # list of PlayerEntry
    meta_loaded = Signal(object)
    summary_changed = Signal()        # what will be converted changed (see summary())

    def __init__(self, parent=None):
        super().__init__(parent)
        self._gui = GuiThread(self)
        self._path = ""
        self._thread: Optional[QThread] = None
        self._loader: Optional[MapLoader] = None
        self._focus_timer = None
        self._bridge: Optional[_Bridge] = None
        self._meta = None
        self._loaded_dims: Set[int] = set()
        self._requested: Set[int] = set()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(self._toolbar())

        self.canvas = MapCanvas()
        self.canvas.hover.connect(lambda t: self.hover_label.setText(t))
        self.canvas.spawn_picked.connect(self._on_spawn_picked)
        self.canvas.selection_changed.connect(self._on_selection_changed)
        self.split = QSplitter(Qt.Horizontal)
        self.split.setChildrenCollapsible(True)
        self.split.addWidget(self.canvas)
        self.split.addWidget(self._side_panel())
        self.split.setStretchFactor(0, 1)
        self.split.setStretchFactor(1, 0)
        self.split.setCollapsible(0, False)
        self.split.setSizes([900, 360])
        v.addWidget(self.split, 1)

        foot = QHBoxLayout()
        self.hover_label = HintLabel(" ", wrap=False)
        self.hover_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self.status = QLabel(tr("No world open."))
        foot.addWidget(self.hover_label, 1)
        foot.addWidget(self.status)
        v.addLayout(foot)
        self._world_game = ("", None)
        self.painted: Dict[int, Dict[Chunk, int]] = {}
        self.set_target_game("java", None)
        self._trim_scan = None
        self._trim_active = False
        self._trim_thread = None
        self._syncing = False
        self._pending = None
        self._keep_view = False
        self._update_move()

    # ---------------------------------------------------------- building
    def _toolbar(self) -> QToolBar:
        bar = QToolBar()
        bar.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        lab = QLabel(tr("Dimension:") + " ")
        bar.addWidget(lab)
        self.dim_box = QComboBox()
        self.dim_box.setToolTip(tr("The dimension shown on the map"))
        self.dim_box.currentIndexChanged.connect(self._on_dim)
        lab.setBuddy(self.dim_box)
        bar.addWidget(self.dim_box)
        bar.addSeparator()
        self.modes = QButtonGroup(self)
        for i, (label, icons, tip) in enumerate((
                (tr("Pan"), ("transform-browse", "tool-pointer", "input-mouse"),
                 tr("Drag to move the map (also with the middle button or holding Space)")),
                (tr("Select"), ("edit-select", "select-rectangular", "edit-select-all"),
                 tr("Drag: select · Ctrl + drag or right button: deselect · Shift + click: whole region · click: one "
                    "chunk")),
                (tr("Spawn"), ("mark-location", "flag", "go-home"), tr("Click on the map: new spawn point")))):
            b = QToolButton()
            b.setText(label)
            b.setIcon(theme.icon(*icons))
            b.setToolTip(tip)
            b.setCheckable(True)
            b.setAutoRaise(True)
            b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            b.setAccessibleName(tr("{mode} mode", mode=label))
            self.modes.addButton(b, i)
            bar.addWidget(b)
        self.modes.button(1).setChecked(True)
        self.modes.idClicked.connect(self._on_mode)
        bar.addSeparator()

        sel = QToolButton()
        sel.setText(tr("Selection"))
        sel.setIcon(theme.icon("edit-select-all", "edit-select"))
        sel.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        sel.setPopupMode(QToolButton.InstantPopup)
        sel.setAutoRaise(True)
        menu = QMenu(sel)
        self.sel_actions = []
        for entry in (
                (tr("Select all"), ("edit-select-all",), self._select_all, "Ctrl+A",
                 tr("Select every chunk of the dimension")),
                (tr("Deselect all"), ("edit-select-none",), self._clear, "Ctrl+Shift+A", tr("Deselect all")),
                (tr("Invert selection"), ("edit-select-invert",), self._invert, "Ctrl+I", tr("Invert the selection")),
                None,
                (tr("Import selection…"), ("document-import", "document-open"), self._import, "",
                 tr("Load a selection (MCA Selector CSV)")),
                (tr("Export selection…"), ("document-export", "document-save-as"), self._export, "",
                 tr("Save the selection (MCA Selector CSV)"))):
            if entry is None:
                menu.addSeparator()
                continue
            label, icons, slot, keys, tip = entry
            a = QAction(theme.icon(*icons), label, self)
            a.setToolTip(tip)
            a.triggered.connect(slot)
            if keys:
                a.setShortcut(QKeySequence(keys))
                a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
                self.addAction(a)
            menu.addAction(a)
            self.sel_actions.append(a)
        sel.setMenu(menu)
        bar.addWidget(sel)
        fit = QAction(theme.icon("zoom-fit-best", "zoom-original"), tr("Fit"), self)
        fit.setToolTip(tr("Show the whole world (Ctrl+0)"))
        fit.setShortcut(QKeySequence("Ctrl+0"))
        fit.setShortcutContext(Qt.WidgetWithChildrenShortcut)
        fit.triggered.connect(self._fit)
        self.addAction(fit)
        bar.addAction(fit)

        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        bar.addWidget(spacer)
        self.trim_btn = QToolButton()
        self.trim_btn.setText(tr("World trim"))
        self.trim_btn.setIcon(theme.icon("edit-cut"))
        self.trim_btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.trim_btn.setAutoRaise(True)
        self.trim_btn.setToolTip(tr("Select only the chunks really used (InhabitedTime ≥ 1 minute, with a protective "
                                    "ring and the spawn): chunks never visited stay out of the conversion, or you save "
                                    "a trimmed copy of the world."))
        self.trim_btn.clicked.connect(self.run_trim)
        self.trim_btn.setEnabled(False)
        bar.addWidget(self.trim_btn)
        self.trim_gear = QToolButton()
        self.trim_gear.setIcon(theme.icon("configure", "preferences-system"))
        self.trim_gear.setText(tr("Trim settings"))
        self.trim_gear.setToolButtonStyle(Qt.ToolButtonIconOnly if not self.trim_gear.icon().isNull()
                                          else Qt.ToolButtonTextOnly)
        self.trim_gear.setToolTip(tr("Trim settings (InhabitedTime threshold, protections, heat map)"))
        self.trim_gear.setAccessibleName(tr("Trim settings"))
        self.trim_gear.setPopupMode(QToolButton.InstantPopup)
        self.trim_gear.setAutoRaise(True)
        menu = QMenu(self.trim_gear)
        self.trim_settings = TrimSettings()
        wa = QWidgetAction(menu)
        wa.setDefaultWidget(self.trim_settings)
        menu.addAction(wa)
        self.trim_gear.setMenu(menu)
        self.trim_settings.changed.connect(self._trim_settings_changed)
        bar.addWidget(self.trim_gear)
        return bar

    def _side_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(280)
        body = QWidget()
        v = QVBoxLayout(body)

        # ---- the conversion
        v.addWidget(heading(tr("What to convert")))
        self.scope_all = QRadioButton(tr("The whole world"))
        self.scope_sel = QRadioButton(tr("Selected chunks only"))
        self.scope_all.setChecked(True)
        self.scope_all.toggled.connect(self._update_status)
        self.scope_all.toggled.connect(self._update_move)
        v.addWidget(self.scope_all)
        v.addWidget(self.scope_sel)
        self.move_sel = QCheckBox(tr("Move the selected chunks"))
        self.move_sel.setToolTip(tr("In the converted world the selected chunks do not stay at their coordinates"))
        self.move_sel.toggled.connect(self._update_status)
        self.move_sel.toggled.connect(self._update_move)
        v.addWidget(with_help(self.move_sel, tr(HELP_MOVE)))
        self.move_box = QWidget()
        mb = QGridLayout(self.move_box)
        mb.setContentsMargins(self.style().pixelMetric(QStyle.PM_IndicatorWidth) + spacing(body), 0, 0, 0)
        self.move_center = QRadioButton(tr("To the world centre (0, 0)"))
        self.move_at = QRadioButton(tr("To the coordinates (blocks):"))
        self.move_center.setChecked(True)
        mb.addWidget(self.move_center, 0, 0, 1, 2)
        mb.addWidget(self.move_at, 1, 0, 1, 2)
        self.move_x, self.move_z = QSpinBox(), QSpinBox()
        coords = QFormLayout()
        coords.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        for sb, lab in ((self.move_x, "X"), (self.move_z, "Z")):
            sb.setRange(-30000000, 30000000)
            sb.setAccessibleName(tr("Target {axis} coordinate", axis=lab))
            sb.valueChanged.connect(lambda _v: self.move_at.setChecked(True))
            coords.addRow(f"{lab}:", sb)
        mb.addLayout(coords, 2, 0, 1, 2)
        mb.addWidget(HintLabel(tr("The centre of the selection goes there; spawn and players that were on the moved "
                                  "chunks follow them, the others start at the new spawn.")), 3, 0, 1, 2)
        v.addWidget(self.move_box)

        v.addWidget(heading(tr("Spawn"), space_above=True))
        self.use_spawn = QCheckBox(tr("New spawn in the converted world"))
        self.use_spawn.setToolTip(tr("Use the point chosen with the “Spawn” mode (or typed here) as the spawn of the "
                                     "converted world"))
        self.use_spawn.toggled.connect(self._spawn_toggled)
        v.addWidget(self.use_spawn)
        sp = QFormLayout()
        sp.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.sx, self.sy, self.sz = QSpinBox(), QSpinBox(), QSpinBox()
        for sb, lab in ((self.sx, "X"), (self.sy, "Y"), (self.sz, "Z")):
            sb.setRange(-30000000, 30000000) if lab != "Y" else sb.setRange(-64, 320)
            sb.setAccessibleName(f"Spawn {lab}")
            sb.valueChanged.connect(self._spawn_edited)
            sp.addRow(f"{lab}:", sb)
        v.addLayout(sp)
        b = QPushButton(theme.icon("edit-undo", "document-revert"), tr("Restore the original"))
        b.setToolTip(tr("Restore the spawn of the source world"))
        b.clicked.connect(self._reset_spawn)
        v.addWidget(b, 0, Qt.AlignLeft)
        v.addWidget(HintLabel(tr("Or choose the “Spawn” mode and click on the map.")))

        v.addWidget(heading(tr("Nether and End"), space_above=True))
        self.regen_nether = QCheckBox(tr("Regenerate the Nether from scratch"))
        self.regen_end = QCheckBox(tr("Regenerate the End from scratch"))
        for cb in (self.regen_nether, self.regen_end):
            cb.setToolTip(tr("The dimension is not converted: the game generates it anew"))
            cb.toggled.connect(lambda _on: self.summary_changed.emit())
            v.addWidget(cb)
        v.addWidget(with_help(HintLabel(tr("The other dimensions are converted."), wrap=False), tr(HELP_REGEN)))

        v.addWidget(heading(tr("Biome of the selected chunks"), space_above=True))
        self.biome_box = QComboBox()
        self.biome_box.setToolTip(tr(HELP_BIOME))
        self.biome_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.biome_box.setMinimumContentsLength(16)
        v.addWidget(self.biome_box)
        b1 = QPushButton(tr("Apply"))
        b1.setToolTip(tr("Give the chosen biome to every selected chunk of the dimension shown"))
        b1.clicked.connect(self._paint_biome)
        b2 = QPushButton(tr("Remove"))
        b2.setToolTip(tr("The selected chunks go back to their original biome"))
        b2.clicked.connect(self._unpaint_biome)
        v.addWidget(row(b1, b2, HelpButton(tr(HELP_BIOME))))
        self.biome_status = HintLabel("")
        self.biome_status.hide()
        v.addWidget(self.biome_status)

        # ---- the source world itself
        v.addWidget(heading(tr("Edit the source world"), space_above=True))
        v.addWidget(HintLabel(tr("Changes the open world right away, without converting. The changed files are "
                                 "copied first; close the game.")))
        edit = QGridLayout()
        for i, (label, slot, tip) in enumerate((
                (tr("Delete the selected chunks…"), self._edit_remove,
                 tr("Removes the selected chunks from the world: the game generates them again")),
                (tr("Keep only the selected chunks…"), self._edit_keep,
                 tr("Removes every unselected chunk of the dimension shown from the world")))):
            b = QPushButton(theme.icon("edit-delete", "delete"), label)
            b.setToolTip(tip + " " + tr("(the changed files are copied first)."))
            b.clicked.connect(slot)
            edit.addWidget(b, i, 0)
        v.addLayout(edit)
        self.world_biome_box = QComboBox()
        self.world_biome_box.setToolTip(tr("The biomes of the source world's game and version"))
        self.world_biome_box.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.world_biome_box.setMinimumContentsLength(16)
        v.addWidget(self.world_biome_box)
        b = QPushButton(tr("Give the biome to the selected chunks…"))
        b.setToolTip(tr("The selected chunks of the source world take this biome right away (the changed files are "
                        "copied first)."))
        b.clicked.connect(self._edit_paint)
        v.addWidget(b, 0, Qt.AlignLeft)
        self.world_game_label = HintLabel("")
        v.addWidget(self.world_game_label)
        v.addStretch(1)
        scroll.setWidget(body)
        return scroll

    def _update_move(self, *_a):
        """The destination of the moved chunks only matters when they are moved."""
        on = self.move_sel.isChecked()
        self.move_box.setEnabled(on)
        self.move_box.setVisible(on)
        self.summary_changed.emit()

    def summary(self) -> str:
        """What will be converted, in a few words (shown on the conversion tab)."""
        parts = []
        if self.scope_sel.isChecked():
            n = sum(len(v) for v in self.canvas.selection.values())
            parts.append(tr("selected chunks only ({n})", n=n))
            if self.move_sel.isChecked():
                parts.append(tr("moved to the centre") if self.move_center.isChecked()
                             else tr("moved to X {x}, Z {z}", x=self.move_x.value(), z=self.move_z.value()))
        else:
            parts.append(tr("the whole world"))
        if self.use_spawn.isChecked():
            parts.append(tr("new spawn {x}, {y}, {z}", x=self.sx.value(), y=self.sy.value(), z=self.sz.value()))
        n = sum(len(v) for v in self.painted.values())
        if n:
            parts.append(tr("{n} chunks with a new biome", n=n))
        nether, end = self.regen_nether.isChecked(), self.regen_end.isChecked()
        if nether and end:
            parts.append(tr("Nether and End regenerated from scratch"))
        elif nether or end:
            parts.append(tr("{dim} regenerated from scratch", dim="Nether" if nether else "End"))
        text = ", ".join(parts)
        return text[0].upper() + text[1:]

    def save_state(self, s) -> None:
        s.setValue("map/splitter", self.split.saveState())

    def export_state(self) -> dict:
        """Everything chosen on this tab, to rebuild it (the window is rebuilt when the language changes)."""
        c = self.canvas
        return {"selection": {d: set(v) for d, v in c.selection.items()}, "scope_sel": self.scope_sel.isChecked(),
                "move_sel": self.move_sel.isChecked(), "move_center": self.move_center.isChecked(),
                "move_xz": (self.move_x.value(), self.move_z.value()), "use_spawn": self.use_spawn.isChecked(),
                "spawn": (self.sx.value(), self.sy.value(), self.sz.value()),
                "regen": (self.regen_nether.isChecked(), self.regen_end.isChecked()),
                "painted": {d: dict(v) for d, v in self.painted.items()}, "biome": self.biome_box.currentData(),
                "view": (c.dim, c.center.x(), c.center.y(), c.scale), "mode": self.modes.checkedId(),
                "trim": (self._trim_scan, self._trim_active), "split": self.split.saveState()}

    def import_state(self, st: dict) -> None:
        """The choices of export_state(), on the same source world (after set_source)."""
        c = self.canvas
        c.selection = {d: set(v) for d, v in st["selection"].items()}
        c._sel_img.clear()
        self.painted = {d: dict(v) for d, v in st["painted"].items()}
        i = self.biome_box.findData(st["biome"])
        if i >= 0:
            self.biome_box.setCurrentIndex(i)
        self._update_biome_status()
        self.regen_nether.setChecked(st["regen"][0])
        self.regen_end.setChecked(st["regen"][1])
        self.move_x.setValue(st["move_xz"][0])
        self.move_z.setValue(st["move_xz"][1])
        (self.move_center if st["move_center"] else self.move_at).setChecked(True)
        self.move_sel.setChecked(st["move_sel"])
        (self.scope_sel if st["scope_sel"] else self.scope_all).setChecked(True)
        self.modes.button(st["mode"]).setChecked(True)
        self._on_mode(st["mode"])
        self._trim_scan, self._trim_active = st["trim"]
        if self._trim_scan is not None:
            opt = self.trim_settings.options()
            c.set_heat(self._trim_scan.inhabited, opt.min_ticks, self.trim_settings.show_heat())
        self.split.restoreState(st["split"])
        self._pending = st                       # spawn and view: once the world's data has arrived
        if self._meta is not None:
            self._apply_pending()
        c.update()
        self.summary_changed.emit()

    def _apply_pending(self) -> None:
        st, self._pending = self._pending, None
        if st is None:
            return
        if st["use_spawn"]:
            self._set_spawn_boxes(st["spawn"])
            self.canvas.spawn = tuple(st["spawn"])
            self.use_spawn.setChecked(True)
        dim, x, z, scale = st["view"]
        i = self.dim_box.findData(dim)
        if i >= 0:
            self.dim_box.setCurrentIndex(i)
        self.canvas.scale = scale
        self.canvas.center_on(x, z)
        self._keep_view = True
        self._update_status()

    def restore_state(self, s) -> None:
        st = s.value("map/splitter")
        if st is not None:
            self.split.restoreState(st)


    # ---------------------------------------------------------- loading
    def set_source(self, path: str):
        if path == self._path:
            return
        self._shutdown()
        self._path = path
        self._meta = None
        self._keep_view = False
        self._loaded_dims.clear()
        self._requested.clear()
        self.canvas.reset()
        self.dim_box.blockSignals(True)
        self.dim_box.clear()
        self.dim_box.blockSignals(False)
        self.scope_all.setChecked(True)
        self.use_spawn.setChecked(False)
        self._trim_scan = None
        self._trim_active = False
        self.trim_btn.setEnabled(bool(path))
        self._set_world_game(path)
        if not path:
            self.status.setText(tr("No world loaded."))
            return
        self.status.setText(tr("Opening the world…"))
        self._thread = QThread(self)
        self._loader = MapLoader(path)
        self._bridge = _Bridge()
        self._loader.moveToThread(self._thread)
        self._bridge.open.connect(self._loader.open)
        self._bridge.render.connect(self._loader.render)
        self._bridge.close.connect(self._loader.close)
        self._loader.meta.connect(self._on_meta)
        self._loader.batch.connect(self._on_batch)
        self._loader.progress.connect(self._on_progress)
        self._loader.failed.connect(self._gui.wrap(lambda m: self.status.setText(tr("Map not available: {error}", error=m))))
        self._loader.dim_done.connect(self._on_dim_done)
        self._thread.start()
        self._bridge.open.emit()
        if self._focus_timer is None:
            from PySide6.QtCore import QTimer

            self._focus_timer = QTimer(self)
            self._focus_timer.timeout.connect(self._push_focus)
            self._focus_timer.start(300)

    def _push_focus(self):
        """The loader draws first what is on screen (it reads this from its thread)."""
        if self._loader is not None and self.canvas.dim is not None:
            c = self.canvas.center
            self._loader.focus[self.canvas.dim] = (int(math.floor(c.x())) >> 4, int(math.floor(c.y())) >> 4)

    def pause_preview(self, on: bool) -> None:
        """A conversion is running: the preview stops reading the world, and goes on afterwards."""
        if self._loader is not None:
            self._loader.paused = on
        if on and self._loader is not None and self._meta is not None:
            self.status.setText(tr("Preview paused during the conversion"))

    def ensure_rendered(self):
        """Render the selected dimension (called when the tab becomes visible)."""
        if self._meta is None or self._bridge is None:
            return
        dim = self.dim_box.currentData()
        if dim is not None and dim not in self._requested:
            self._requested.add(dim)
            self._bridge.render.emit(dim)

    def _on_meta(self, meta):
        self._meta = meta
        self.dim_box.blockSignals(True)
        self.dim_box.clear()
        for d in meta["dims"]:
            self.dim_box.addItem(tr("{dim}  ({n} chunks)", dim=DIM_NAMES.get(d, d), n=meta['counts'].get(d, 0)), d)
        self.dim_box.blockSignals(False)
        sp = tuple(int(v) for v in meta["spawn"])
        self.canvas.orig_spawn = sp
        self.canvas.spawn = sp
        self.canvas.players = meta["players"]
        self._set_spawn_boxes(sp)
        self.canvas.center_on(sp[0], sp[2])
        self.status.setText(meta["description"])
        self.players_loaded.emit(meta["players"])
        self.meta_loaded.emit(meta)
        self._apply_pending()
        if self.isVisible():
            self.ensure_rendered()

    def _on_batch(self, dim, tiles):
        self.canvas.add_tiles(dim, tiles)

    def _on_progress(self, dim, done, total):
        if dim == self.dim_box.currentData():
            self.status.setText(tr("{dim}: {done}/{total} chunks", dim=DIM_NAMES.get(dim, dim), done=done, total=total))

    def _on_dim_done(self, dim):
        self._loaded_dims.add(dim)
        # big worlds: the view stays where the user is looking
        small = (self._meta or {}).get("counts", {}).get(dim, 0) <= 20000
        if dim == self.dim_box.currentData() and len(self._loaded_dims) == 1 and small and not self._keep_view:
            self.canvas.fit(dim)
        self._update_status()

    def _on_dim(self):
        dim = self.dim_box.currentData()
        if dim is None:
            return
        self.canvas.dim = dim
        if dim not in self._loaded_dims and self._meta is not None:
            sx, _sy, sz = self.canvas.orig_spawn or (0, 0, 0)
            f = {NETHER: 1 / 8, THE_END: 0}.get(dim, 1)
            self.canvas.center_on(sx * f, sz * f)          # where that dimension starts loading
        self.canvas.update()
        self.ensure_rendered()
        if dim in self._loaded_dims:
            self.canvas.fit(dim)
        self._update_status()

    def _shutdown(self):
        if self._loader is not None:
            self._loader.stop()
        if self._bridge is not None:
            self._bridge.close.emit()
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait(5000)
        self._thread = self._loader = self._bridge = None

    def shutdown(self):
        self._shutdown()
        if self._trim_thread is not None:
            th, worker = self._trim_thread
            worker.prog.cancel()
            th.quit()
            th.wait(10000)
            self._trim_thread = None

    def showEvent(self, e):
        super().showEvent(e)
        self.ensure_rendered()

    # ---------------------------------------------------------- tools
    def _on_mode(self, i):
        self.canvas.mode = i
        self.canvas.setCursor(Qt.OpenHandCursor if i == 0 else Qt.CrossCursor if i == 2 else Qt.ArrowCursor)

    def _select_all(self):
        self.canvas.select_all()

    def _clear(self):
        self.canvas.clear_selection()

    def _invert(self):
        self.canvas.invert()

    def _fit(self):
        self.canvas.fit(self.canvas.dim)

    def _import(self):
        from ..selection import load_csv

        f, _ = QFileDialog.getOpenFileName(self, tr("Import selection"), "", tr("MCA Selector selection") + " (*.csv);;" + tr("All files") + " (*)")
        if f:
            try:
                self.canvas.set_chunks(load_csv(f), True)
                self.scope_sel.setChecked(True)
            except Exception as ex:  # noqa: BLE001
                self.status.setText(tr("Import failed: {error}", error=ex))

    def _export(self):
        from ..selection import save_csv

        f, _ = QFileDialog.getSaveFileName(self, tr("Export selection"), tr("selection") + ".csv", tr("MCA Selector selection") + " (*.csv)")
        if f:
            save_csv(f, self.canvas.selected())

    def _on_selection_changed(self):
        if self.canvas.selection.get(self.canvas.dim):
            self.scope_sel.setChecked(True)
        self._update_status()

    def _update_status(self):
        if self._meta is None:
            return
        parts = []
        for d in self._meta["dims"]:
            n = len(self.canvas.selection.get(d, ()))
            parts.append(f"{DIM_NAMES.get(d, d)}: {n}" + ("" if n or self.scope_all.isChecked() else " " + tr("(left out)")))
        if self.scope_sel.isChecked():
            self.status.setText(tr("Selected – {parts}", parts=" · ".join(parts)))
        else:
            self.status.setText(tr("{world} – the whole world will be converted", world=self._meta['description']))
        self.summary_changed.emit()

    # ---------------------------------------------------------- world trim
    def _run_worker(self, worker, on_done, on_failed):
        th = QThread(self)
        worker.moveToThread(th)
        th.started.connect(worker.run)
        worker.done.connect(self._gui.wrap(on_done))         # the callbacks show message boxes: interface thread
        worker.failed.connect(self._gui.wrap(on_failed))
        worker.done.connect(th.quit)
        worker.failed.connect(th.quit)
        worker.progress.connect(self._gui.wrap(lambda f, m: self.status.setText(f"{m}  ({f * 100:.0f}%)")))
        self._trim_thread = (th, worker)
        th.start()

    def run_trim(self):
        """✂: reads InhabitedTime (once per world) and selects the chunks that stay."""
        if not self._path:
            return
        if self._trim_scan is not None:
            self._apply_trim(ask=True)
            return
        self.trim_btn.setEnabled(False)
        self.status.setText(tr("Reading the time spent in the chunks (InhabitedTime)…"))
        self._run_worker(ScanWorker(self._path), self._on_trim_scanned, self._on_trim_failed)

    def _on_trim_failed(self, msg: str):
        self.trim_btn.setEnabled(bool(self._path))
        self.status.setText(tr("Trim not available: {error}", error=msg))
        QMessageBox.information(self, tr("World trim"), tr("Trim not available for this world.") + f"\n\n{msg}")

    def _on_trim_scanned(self, sc):
        self.trim_btn.setEnabled(True)
        self._trim_scan = sc
        self._apply_trim(ask=True)

    def _trim_settings_changed(self):
        opt = self.trim_settings.options()
        self.canvas.set_heat(self._trim_scan.inhabited if self._trim_scan else None, opt.min_ticks,
                             self.trim_settings.show_heat())
        if self._trim_active and self._trim_scan is not None:
            self._apply_trim(ask=False)  # live update of the selection

    def _apply_trim(self, ask: bool):
        from .. import trim

        sc = self._trim_scan
        opt = self.trim_settings.options()
        keep = trim.plan(sc, opt)
        before = ({d: set(v) for d, v in self.canvas.selection.items()}, self.scope_sel.isChecked())
        self.canvas.set_heat(sc.inhabited, opt.min_ticks, self.trim_settings.show_heat())
        self.canvas.set_selection(keep)
        self.scope_sel.setChecked(True)
        self._trim_active = True
        summ = trim.summary(sc, keep)
        self._update_status()
        self.status.setText(tr("Trim: {summary}", summary=summ))
        if not ask:
            return
        esc = opt.describe().replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        lines = ["<b>" + tr("World trim") + f"</b>: {summ}", theme.span(esc, "secondary"), ""]
        for d in trim.trim_dims(sc):
            tot = len(sc.inhabited[d])
            k = len(keep.get(d, ()))
            warn = " — <b>" + theme.span(tr("it would be regenerated entirely"), "neutral") + "</b>" if tot and not k else ""
            lines.append(tr("{dim}: {kept} of {total} kept", dim=DIM_NAMES.get(d, d), kept=k, total=tot) + warn)
        lines += ["", tr("The kept chunks are highlighted on the map; with the trim settings (next to the button) "
                         "you change threshold and protections and the selection updates at once."),
                  tr("The conversion will use only the kept chunks.") + (
                      " " + tr("You can also save a trimmed copy of the world right away, in the same format.")
                      if sc.can_copy else "")]
        box = QMessageBox(self)
        box.setWindowTitle(tr("World trim"))
        box.setTextFormat(Qt.RichText)
        box.setText("<br>".join(lines))
        use = box.addButton(tr("Use for the conversion"), QMessageBox.AcceptRole)
        save = box.addButton(tr("Save trimmed world…"), QMessageBox.ActionRole) if sc.can_copy else None
        here = box.addButton(tr("Apply to the world"), QMessageBox.ActionRole)
        here.setToolTip(tr("Deletes the chunks not kept from the source world right away (the changed files are "
                           "copied first)"))
        undo = box.addButton(tr("Undo trim"), QMessageBox.RejectRole)
        box.setDefaultButton(use)
        box.exec()
        if box.clickedButton() is undo:
            self._trim_active = False
            self.canvas.selection = before[0]
            self.canvas._sel_img.clear()
            self.canvas.set_heat(None, opt.min_ticks, False)
            (self.scope_sel if before[1] else self.scope_all).setChecked(True)
            self.canvas.update()
            self._update_status()
        elif save is not None and box.clickedButton() is save:
            self._save_trimmed(keep)
        elif box.clickedButton() is here:
            dims = trim.trim_dims(sc)
            n = sum(len(sc.inhabited[d]) - len(keep.get(d, ())) for d in dims)
            if self._confirm_edit(tr("Delete {n} unused chunks from the world?", n=n)):
                self._run_edit(EditWorker(self._path, keep=keep, dims=dims))

    def _save_trimmed(self, keep):
        import os

        parent = QFileDialog.getExistingDirectory(self, tr("Where to save the trimmed world"), os.path.dirname(self._path))
        if not parent:
            return
        base = os.path.basename(os.path.normpath(self._path)) + "_trim"
        out = os.path.join(parent, base)
        n = 2
        while os.path.exists(out):
            out = os.path.join(parent, f"{base}_{n}")
            n += 1
        self.trim_btn.setEnabled(False)

        def done(removed, before, after):
            from ..trim import human_size

            self.trim_btn.setEnabled(True)
            self.status.setText(tr("Trimmed world saved: {path}", path=out))
            QMessageBox.information(self, tr("World trim"), tr(
                "Trimmed world saved in:\n{path}\n\n{n} chunks removed · {before} → {after}\n\nThe original world was "
                "not modified.", path=out, n=removed, before=human_size(before), after=human_size(after)))

        def failed(msg):
            self.trim_btn.setEnabled(True)
            self.status.setText(tr("Saving the trimmed world failed: {error}", error=msg))
            QMessageBox.critical(self, tr("World trim"), tr("Saving failed:") + f"\n\n{msg}")

        self._run_worker(CopyWorker(self._path, out, keep), done, failed)

    # ---------------------------------------------------------- spawn
    def _set_spawn_boxes(self, sp):
        self._syncing = True
        self.sx.setValue(sp[0])
        self.sy.setValue(sp[1])
        self.sz.setValue(sp[2])
        self._syncing = False

    def _on_spawn_picked(self, x, y, z):
        self._set_spawn_boxes((x, y, z))
        self.use_spawn.setChecked(True)

    def _spawn_edited(self):
        if self._syncing:
            return
        self.canvas.spawn = (self.sx.value(), self.sy.value(), self.sz.value())
        self.use_spawn.setChecked(True)
        self.canvas.update()
        self.summary_changed.emit()

    def _spawn_toggled(self, on):
        if not on and self.canvas.orig_spawn:
            self.canvas.spawn = self.canvas.orig_spawn
            self._set_spawn_boxes(self.canvas.orig_spawn)
        elif on:
            self.canvas.spawn = (self.sx.value(), self.sy.value(), self.sz.value())
        self.canvas.update()
        self.summary_changed.emit()

    def _reset_spawn(self):
        self.use_spawn.setChecked(False)

    def center_on_player(self, entry):
        if entry.pos is None:
            return
        i = self.dim_box.findData(entry.dim)
        if i >= 0:
            self.dim_box.setCurrentIndex(i)
        self.canvas.scale = max(self.canvas.scale, 2.0)
        self.canvas.center_on(entry.pos[0], entry.pos[2])

    # ---------------------------------------------------------- biomes
    def _paint_biome(self):
        dim = self.dim_box.currentData()
        sel = self.canvas.selected(dim) if dim is not None else set()
        if not sel:
            self.biome_status.setText(tr("Select some chunks on the map first."))
            self.biome_status.show()
            return
        bid = self.biome_box.currentData()
        self.painted.setdefault(dim, {}).update({c: bid for c in sel})
        self._update_biome_status()

    def _unpaint_biome(self):
        dim = self.dim_box.currentData()
        for c in self.canvas.selected(dim) if dim is not None else ():
            self.painted.get(dim, {}).pop(c, None)
        self._update_biome_status()

    def _update_biome_status(self):
        n = sum(len(v) for v in self.painted.values())
        self.biome_status.setText(tr("{n} chunks with a new biome", n=n) if n else "")
        self.biome_status.setVisible(bool(n))
        self.summary_changed.emit()

    def biome_overrides(self) -> Dict[int, Dict[Chunk, int]]:
        return {d: dict(v) for d, v in self.painted.items() if v}

    def regen_dims(self) -> Tuple[int, ...]:
        return tuple(d for d, cb in ((NETHER, self.regen_nether), (THE_END, self.regen_end)) if cb.isChecked())

    def set_target_game(self, family: str, version) -> None:
        """The conversion's target: which biomes can be painted for it, with the names it uses."""
        _fill_biomes(self.biome_box, family, version)
        dropped = 0
        from ..biomes import available

        ok = set(available(family, version))
        for d in list(self.painted):
            before = len(self.painted[d])
            self.painted[d] = {c: b for c, b in self.painted[d].items() if b in ok}
            dropped += before - len(self.painted[d])
        self._update_biome_status()
        if dropped:
            self.biome_status.setText(self.biome_status.text() + " · " + tr("{n} removed (a biome the target does not have)", n=dropped))
            self.biome_status.show()

    def _set_world_game(self, path: str) -> None:
        from .. import biomes as bio
        from ..chunkedit import world_game
        from ..gameversion import bedrock_label

        fam, ver = world_game(path) if path else ("", None)
        self._world_game = (fam, ver)
        _fill_biomes(self.world_biome_box, fam, ver)
        name = {"lce": "LCE", "java": "Java", "bedrock": "Bedrock", "pe_old": "Pocket Edition"}.get(fam, "")
        if fam == "java" and ver:
            name += " " + ".".join(str(x) for x in ver) + "+"
        elif fam == "bedrock" and ver:
            name += " " + bedrock_label(ver)
        self.world_game_label.setText(tr("biomes of {game}", game=name) if bio.available(fam, ver) else "")

    # ---------------------------------------------------------- edits on the world itself
    def _confirm_edit(self, question: str) -> bool:
        r = QMessageBox.question(
            self, tr("Edit the source world"),
            question + "\n\n" + tr("The world itself is modified (not a copy): close the game first. A copy of the "
                                    "changed files goes to a “.wb-backup-…” folder next to the world."))
        return r == QMessageBox.Yes

    def _edit_selected(self):
        dim = self.dim_box.currentData()
        sel = self.canvas.selected(dim) if dim is not None else set()
        if not sel:
            QMessageBox.information(self, tr("Edit the world"), tr("Select some chunks on the map first."))
        return dim, sel

    def _edit_remove(self):
        dim, sel = self._edit_selected()
        if sel and self._confirm_edit(tr("Delete the {n} selected chunks from the world?", n=len(sel))):
            self._run_edit(EditWorker(self._path, remove={dim: sel}))

    def _edit_keep(self):
        dim, sel = self._edit_selected()
        if sel and self._confirm_edit(tr("Keep only the {n} selected chunks in the dimension shown and delete all the "
                                         "others?", n=len(sel))):
            self._run_edit(EditWorker(self._path, keep={dim: sel}, dims=(dim,)))

    def _edit_paint(self):
        dim, sel = self._edit_selected()
        bid = self.world_biome_box.currentData()
        if not sel:
            return
        if bid is None:
            QMessageBox.information(self, tr("Edit the world"), tr("This world does not store biomes."))
            return
        if self._confirm_edit(tr("Give the biome “{biome}” to the {n} selected chunks?", biome=self.world_biome_box.currentText(), n=len(sel))):
            self._run_edit(EditWorker(self._path, paint={dim: {c: bid for c in sel}}))

    def _run_edit(self, worker):
        def done(res):
            self.status.setText(tr("World edited: {summary}", summary=res.summary()))
            QMessageBox.information(self, tr("Edit the world"), tr("Done: {summary}.", summary=res.summary()))
            self.reload()

        def failed(msg):
            self.status.setText(tr("Edit failed: {error}", error=msg))
            QMessageBox.critical(self, tr("Edit the world"), tr("Edit failed:") + f"\n\n{msg}")

        self.status.setText(tr("Editing the world…"))
        self._run_worker(worker, done, failed)

    def reload(self) -> None:
        """Reads the world again (after it was changed on disk)."""
        path, self._path = self._path, ""
        self.set_source(path)

    def move_target(self) -> Optional[Tuple[int, int]]:
        """Where the selected chunks go in the converted world (None: they stay where they are)."""
        if not (self.move_sel.isChecked() and self.scope_sel.isChecked()):
            return None
        return (0, 0) if self.move_center.isChecked() else (self.move_x.value(), self.move_z.value())

    # ---------------------------------------------------------- result
    def chunk_selection(self) -> Optional[Dict[int, Set[Chunk]]]:
        if not self.scope_sel.isChecked():
            return None
        return {d: set(v) for d, v in self.canvas.selection.items() if v}

    def spawn(self) -> Optional[Tuple[int, int, int]]:
        if not self.use_spawn.isChecked():
            return None
        return (self.sx.value(), self.sy.value(), self.sz.value())


def _fill_biomes(box: QComboBox, family: str, version) -> None:
    """The biomes of a game, with its names (the Italian name alongside)."""
    from .. import biomes as bio

    keep = box.currentData()
    box.clear()
    ids = bio.available(family, version)
    for bid in sorted(ids, key=lambda b: bio.game_name(b, family, version).lower()):
        box.addItem(bio.label(bid, family, version), bid)
    if not ids:
        box.addItem(tr("(this game does not store biomes)"), None)
    i = box.findData(keep)
    box.setCurrentIndex(max(0, i))
    box.setEnabled(bool(ids))
