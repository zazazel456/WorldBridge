"""The "New world" view of the Map tab: the converted world as a grid of white chunks onto which the chunks selected on the
source map are pasted as GROUPS, and moved around the grid (worldbridge.layout: composition).

* ``LayoutModel``: the groups, the selection of groups, undo / redo, the live check (overlaps, finite map);
* ``LayoutCanvas``: the grid (same zoom / pan as the source map), the groups drawn with the source map's own tiles, with a
  coloured outline and name; red where the check fails; drag = move by whole chunks, arrows = 1 chunk (Shift: 8);
* ``LayoutController``: the side panel (list of groups, rename, offset, back to place, centre on the spawn, save / load),
  the shortcuts and the glue to the map tab.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional, Set, Tuple

import numpy as np
from PySide6.QtCore import QLineF, QObject, QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QAction, QColor, QImage, QKeySequence, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QFileDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)

from ..i18n import tr
from ..layout import Group, Layout
from ..model import NETHER, OVERWORLD, THE_END
from . import theme
from .mapwidget import DIM_NAMES, MapCanvas, _label
from .widgets import HintLabel, heading, row

Chunk = Tuple[int, int]
Box = Tuple[int, int, int, int]                     # chunks, inclusive: x0, x1, z0, z1

PALETTE = [(30, 110, 230), (240, 140, 20), (40, 160, 80), (150, 80, 200), (0, 160, 170), (210, 60, 150),
           (150, 150, 30), (140, 90, 50)]
RED = QColor(220, 30, 30)
MOVE_STEP, BIG_STEP = 1, 8
TINT_LIMIT = 60000                                  # a group with more chunks gets only a rectangular outline


def _moved(g: Group, off: Chunk) -> Group:
    """``g`` at another offset (the chunks are shared: no copy of a big group on every step of a drag)."""
    n = object.__new__(Group)
    for k, v in (("dim", g.dim), ("chunks", g.chunks), ("offset", (int(off[0]), int(off[1]))), ("name", g.name)):
        object.__setattr__(n, k, v)
    return n


def _named(g: Group, name: str) -> Group:
    n = _moved(g, g.offset)
    object.__setattr__(n, "name", name)
    return n


def _overlap(a: Box, b: Box) -> bool:
    return a[0] <= b[1] and b[0] <= a[1] and a[2] <= b[3] and b[2] <= a[3]


# ============================================================ model


class LayoutModel(QObject):
    """The groups of the new world.  Groups are immutable: every change replaces one, so a snapshot (for undo) is a tuple."""

    changed = Signal()                  # the groups (or the bounds) changed
    selection_changed = Signal()

    UNDO_LIMIT = 200

    def __init__(self):
        super().__init__()
        self.groups: List[Group] = []
        self.ids: List[int] = []         # one per group: stable through undo (the colour and the selection follow it)
        self.selected: Set[int] = set()
        self._serial = 0
        self._undo: list = []
        self._redo: list = []
        self._drag = None
        self.bounds_fn: Optional[Callable] = None     # (Layout, spawn (x, y, z) | None) -> {dim: (x0, x1, z0, z1)} | None
        self.spawn_fn: Optional[Callable] = None      # () -> (x, z) block of the source world's (chosen) spawn | None
        self._ver = 0
        self._derived = None
        self._bbox: Dict[int, tuple] = {}

    # ------------------------------------------------------------------ reading
    def layout(self) -> Layout:
        return Layout(list(self.groups))

    def __len__(self) -> int:
        return len(self.groups)

    def index(self, gid: int) -> int:
        return self.ids.index(gid)

    def group(self, gid: int) -> Group:
        return self.groups[self.ids.index(gid)]

    def source_bbox(self, g: Group) -> Box:
        e = self._bbox.get(id(g.chunks))
        if e is None or e[0] is not g.chunks:
            if len(self._bbox) > 400:
                self._bbox.clear()
            xs = [c[0] for c in g.chunks]
            zs = [c[1] for c in g.chunks]
            e = self._bbox[id(g.chunks)] = (g.chunks, (min(xs), max(xs), min(zs), max(zs)))
        return e[1]

    def placed_bbox(self, g: Group) -> Box:
        x0, x1, z0, z1 = self.source_bbox(g)
        dx, dz = g.offset
        return x0 + dx, x1 + dx, z0 + dz, z1 + dz

    def new_spawn_block(self) -> Optional[Tuple[int, int]]:
        """Where the spawn of the new world is: the source's (chosen) spawn moved with its chunk, else inside the first
        Overworld group (what the conversion does)."""
        lay = self.layout()
        src = self.spawn_fn() if self.spawn_fn else None
        if src is not None:
            o = lay.offset(OVERWORLD, math.floor(src[0]) >> 4, math.floor(src[1]) >> 4)
            if o is not None:
                return src[0] + o[0] * 16, src[1] + o[1] * 16
        return lay.default_spawn()

    def derived(self):
        """(version, bounds, bad, problems): the finite map's chunks per dimension, the destination chunks to paint red
        per dimension, and the engine's readable problems.  Cached until the layout (or the target) changes."""
        if self._derived is None or self._derived[0] != self._ver:
            lay = self.layout()
            bounds = None
            if self.bounds_fn is not None:
                sp = self.new_spawn_block()
                try:
                    bounds = self.bounds_fn(lay, (sp[0], 0, sp[1]) if sp else None)
                except Exception:  # noqa: BLE001 (a target whose options are not complete)
                    bounds = None
            self._derived = (self._ver, bounds, self._bad(lay, bounds), lay.problems(bounds) if lay.groups else [])
        return self._derived

    def problems(self) -> List[str]:
        return self.derived()[3]

    def _bad(self, lay: Layout, bounds) -> Dict[int, Set[Chunk]]:
        out: Dict[int, Set[Chunk]] = {}
        for dim in lay.dimensions():
            bad: Set[Chunk] = set()
            gs = [g for g in lay.groups if g.dim == dim and g.chunks]
            for i, a in enumerate(gs):
                for b in gs[i + 1:]:
                    common = a.chunks & b.chunks                          # the same source chunk in two groups
                    if common:
                        bad.update(a.dest(*c) for c in common)
                        bad.update(b.dest(*c) for c in common)
                    if _overlap(self.placed_bbox(a), self.placed_bbox(b)):
                        bad.update(a.placed() & b.placed())               # two groups on the same destination chunk
            box = (bounds or {}).get(dim)
            if box is not None:
                x0, x1, z0, z1 = box
                for g in gs:
                    bx0, bx1, bz0, bz1 = self.placed_bbox(g)
                    if not (x0 <= bx0 and bx1 < x1 and z0 <= bz0 and bz1 < z1):
                        bad.update(d for d in g.placed() if not (x0 <= d[0] < x1 and z0 <= d[1] < z1))
            out[dim] = bad
        return out

    # ------------------------------------------------------------------ undo
    def _snap(self):
        return tuple(self.groups), tuple(self.ids)

    def _push(self):
        self._undo.append(self._snap())
        del self._undo[:-self.UNDO_LIMIT]
        self._redo.clear()

    def _restore(self, snap):
        self.groups, self.ids = list(snap[0]), list(snap[1])
        self.selected &= set(self.ids)

    def can_undo(self) -> bool:
        return bool(self._undo)

    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self._snap())
        self._restore(self._undo.pop())
        self._touch(True)
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self._snap())
        self._restore(self._redo.pop())
        self._touch(True)
        return True

    def _touch(self, selection: bool = False):
        self._ver += 1
        self.changed.emit()
        if selection:
            self.selection_changed.emit()

    def refresh(self):
        """The target's options changed (the finite map): check again."""
        self._touch()

    # ------------------------------------------------------------------ selection
    def select(self, ids) -> None:
        ids = set(ids) & set(self.ids)
        if ids != self.selected:
            self.selected = ids
            self.selection_changed.emit()

    # ------------------------------------------------------------------ changes
    def next_name(self) -> str:
        used = {g.name for g in self.groups}
        n = 1
        while tr("Group {n}", n=n) in used:
            n += 1
        return tr("Group {n}", n=n)

    def paste(self, dim: int, chunks) -> int:
        """A new group with ``chunks`` at the same coordinates (offset 0, 0) or, when that overlaps or leaves the map,
        at the nearest free place.  Returns its id."""
        chunks = frozenset(chunks)
        off = self.free_offset(dim, chunks)
        self._push()
        self._serial += 1
        self.groups.append(Group(dim, chunks, off, self.next_name()))
        self.ids.append(self._serial)
        self.selected = {self._serial}
        self._touch(True)
        return self._serial

    def free_offset(self, dim: int, chunks) -> Chunk:
        chunks = frozenset(chunks)
        probe = Group(dim, chunks, (0, 0))
        xs = [c[0] for c in chunks]
        zs = [c[1] for c in chunks]
        bx0, bx1, bz0, bz1 = min(xs), max(xs), min(zs), max(zs)
        w, h = bx1 - bx0 + 1, bz1 - bz0 + 1
        others = [(self.placed_bbox(g), g.placed()) for g in self.groups if g.dim == dim and g.chunks]
        box = None
        if self.bounds_fn is not None:
            sp = self.new_spawn_block()
            try:
                box = (self.bounds_fn(Layout(self.groups + [probe]), (sp[0], 0, sp[1]) if sp else None) or {}).get(dim)
            except Exception:  # noqa: BLE001
                box = None

        def fits(o: Chunk) -> bool:
            x0, x1, z0, z1 = bx0 + o[0], bx1 + o[0], bz0 + o[1], bz1 + o[1]
            if box is not None and not (box[0] <= x0 and x1 < box[1] and box[2] <= z0 and z1 < box[3]):
                return False
            mine = None
            for bb, placed in others:
                if _overlap((x0, x1, z0, z1), bb):
                    if mine is None:
                        mine = {(x + o[0], z + o[1]) for x, z in chunks}
                    if not mine.isdisjoint(placed):
                        return False
            return True

        if fits((0, 0)):
            return 0, 0
        base = [(0, 0)]
        if box is not None:                       # pushed back inside the map
            dx = max(box[0] - bx0, min(box[1] - 1 - bx1, 0)) if w <= box[1] - box[0] else box[0] - bx0
            dz = max(box[2] - bz0, min(box[3] - 1 - bz1, 0)) if h <= box[3] - box[2] else box[2] - bz0
            base.append((dx, dz))
        cands: List[Chunk] = []
        for bdx, bdz in base:
            cands.append((bdx, bdz))
            for (gx0, gx1, gz0, gz1), _p in others:           # touching a group on each side, aligned with it or not
                for dx in (gx1 + 1 - bx0, gx0 - 1 - bx1):
                    cands += [(dx, bdz), (dx, gz0 - bz0)]
                for dz in (gz1 + 1 - bz0, gz0 - 1 - bz1):
                    cands += [(bdx, dz), (gx0 - bx0, dz)]
        cands.sort(key=lambda o: (o[0] * o[0] + o[1] * o[1], o))
        for o in cands:
            if fits(o):
                return o
        steps = sorted(((i * (w + 1), j * (h + 1)) for i in range(-12, 13) for j in range(-12, 13)),
                       key=lambda o: (o[0] * o[0] + o[1] * o[1], o))
        for o in steps:
            if fits(o):
                return o
        return 0, 0

    def _replace(self, gid: int, g: Group):
        self.groups[self.ids.index(gid)] = g

    def move(self, ids, dx: int, dz: int) -> None:
        ids = [i for i in ids if i in self.ids]
        if not ids or not (dx or dz):
            return
        self._push()
        for i in ids:
            g = self.group(i)
            self._replace(i, _moved(g, (g.offset[0] + dx, g.offset[1] + dz)))
        self._touch()

    def set_offsets(self, offsets: Dict[int, Chunk]) -> None:
        offsets = {i: o for i, o in offsets.items() if i in self.ids and tuple(self.group(i).offset) != tuple(o)}
        if not offsets:
            return
        self._push()
        for i, o in offsets.items():
            self._replace(i, _moved(self.group(i), o))
        self._touch()

    def rename(self, gid: int, name: str) -> None:
        if gid in self.ids and self.group(gid).name != name:
            self._push()
            self._replace(gid, _named(self.group(gid), name))
            self._touch()

    def delete(self, ids) -> None:
        ids = {i for i in ids if i in self.ids}
        if not ids:
            return
        self._push()
        keep = [k for k, i in enumerate(self.ids) if i not in ids]
        self.groups = [self.groups[k] for k in keep]
        self.ids = [self.ids[k] for k in keep]
        self.selected -= ids
        self._touch(True)

    def begin_drag(self, ids) -> None:
        ids = [i for i in ids if i in self.ids]
        self._drag = (self._snap(), {i: tuple(self.group(i).offset) for i in ids})

    def drag_to(self, dx: int, dz: int) -> None:
        """Every group of the drag at its starting offset plus (dx, dz) chunks."""
        if self._drag is None:
            return
        moved = False
        for i, o in self._drag[1].items():
            new = (o[0] + dx, o[1] + dz)
            if tuple(self.group(i).offset) != new:
                self._replace(i, _moved(self.group(i), new))
                moved = True
        if moved:
            self._touch()

    def end_drag(self) -> None:
        if self._drag is None:
            return
        snap, start = self._drag
        self._drag = None
        if any(tuple(self.group(i).offset) != o for i, o in start.items() if i in self.ids):
            self._undo.append(snap)
            del self._undo[:-self.UNDO_LIMIT]
            self._redo.clear()

    def load(self, layout: Layout) -> None:
        """Replaces every group by those of ``layout`` (undoable)."""
        self._push()
        self.groups, self.ids = [], []
        for g in layout.groups:
            self._serial += 1
            self.groups.append(g if g.name else _named(g, tr("Group {n}", n=len(self.groups) + 1)))
            self.ids.append(self._serial)
        self.selected = set()
        self._touch(True)

    def clear(self) -> None:
        """No group, no history (another source world)."""
        self.groups, self.ids, self.selected = [], [], set()
        self._undo.clear()
        self._redo.clear()
        self._drag = None
        self._touch(True)

    def export(self) -> dict:
        return {"groups": list(self.groups), "ids": list(self.ids), "serial": self._serial}

    def restore(self, st: dict) -> None:
        self.groups, self.ids, self._serial = list(st["groups"]), list(st["ids"]), st["serial"]
        self.selected = set()
        self._undo.clear()
        self._redo.clear()
        self._touch(True)


# ============================================================ canvas


def _qimage_array(img: QImage) -> np.ndarray:
    n = img.height() * img.bytesPerLine()
    arr = np.frombuffer(img.constBits(), np.uint8, count=n).reshape(img.height(), img.bytesPerLine())
    return arr[:, : img.width() * 4].reshape(img.height(), img.width(), 4)


def _to_qimage(arr: np.ndarray, fmt) -> QImage:
    arr = np.ascontiguousarray(arr)
    return QImage(arr.data, arr.shape[1], arr.shape[0], arr.shape[1] * 4, fmt).copy()


class LayoutCanvas(MapCanvas):
    """The new world: a white grid of chunks; the groups are drawn with the source map's tiles."""

    def __init__(self, model: LayoutModel, source: MapCanvas, parent=None):
        super().__init__(parent)
        self.model = model
        self.source = source
        self.scale = 2.0
        self._tiles: Dict[int, tuple] = {}          # id -> (chunks, source tile version, QImage, px per chunk)
        self._tints: Dict[int, tuple] = {}          # id -> (chunks, QImage)
        self._edges: Dict[int, tuple] = {}          # id -> (chunks, [QLineF])
        self._at: Optional[tuple] = None            # (version, dim, {destination chunk: id})
        self._move = None                           # (start block, ids)
        self._fitted = False
        model.changed.connect(self.update)
        model.selection_changed.connect(self.update)
        source.tiles_changed.connect(self._tiles_changed)

    def _tiles_changed(self):
        if self.isVisible():
            self.update()

    # ---------------------------------------------------------- the view
    def fit_layout(self):
        """Shows the finite map, or the groups (both when both)."""
        _v, bounds, _bad, _p = self.model.derived()
        boxes: List[Box] = []
        box = (bounds or {}).get(self.dim)
        if box is not None:
            boxes.append((box[0], box[1] - 1, box[2], box[3] - 1))
        boxes += [self.model.placed_bbox(g) for g in self.model.groups if g.dim == self.dim and g.chunks]
        self._fitted = True
        if not boxes:
            self.center = QPointF(0, 0)
            self.scale = 2.0
            self.update()
            return
        x0, x1 = min(b[0] for b in boxes), max(b[1] for b in boxes)
        z0, z1 = min(b[2] for b in boxes), max(b[3] for b in boxes)
        w, h = (x1 - x0 + 1) * 16, (z1 - z0 + 1) * 16
        self.center = QPointF(x0 * 16 + w / 2, z0 * 16 + h / 2)
        self.scale = max(1 / 32, min(8.0, 0.92 * min(self.width() / max(w, 1), self.height() / max(h, 1))))
        self.update()

    def reveal(self, gids):
        """Brings the groups into view when none of them is."""
        gs = [self.model.group(i) for i in gids if i in self.model.ids]
        if not gs:
            return
        box = [self.model.placed_bbox(g) for g in gs]
        x0, x1 = min(b[0] for b in box), max(b[1] for b in box)
        z0, z1 = min(b[2] for b in box), max(b[3] for b in box)
        a = self.to_screen(x0 * 16, z0 * 16)
        b = self.to_screen((x1 + 1) * 16, (z1 + 1) * 16)
        if QRectF(a, b).intersects(QRectF(0, 0, self.width(), self.height())):
            return
        self.center = QPointF((x0 + x1 + 1) * 8, (z0 + z1 + 1) * 8)
        self.update()

    # ---------------------------------------------------------- hit test
    def _index(self) -> Dict[Chunk, int]:
        if self._at is None or self._at[0] != self.model._ver or self._at[1] != self.dim:
            m: Dict[Chunk, int] = {}
            for gid, g in zip(self.model.ids, self.model.groups):
                if g.dim == self.dim:
                    dx, dz = g.offset
                    for x, z in g.chunks:
                        m[(x + dx, z + dz)] = gid                    # the last one drawn is the one on top
            self._at = (self.model._ver, self.dim, m)
        return self._at[2]

    def group_at(self, pos) -> Optional[int]:
        return self._index().get(self._chunk_at(pos))

    # ---------------------------------------------------------- images
    def _color(self, gid: int) -> QColor:
        return QColor(*PALETTE[(gid - 1) % len(PALETTE)])

    def _tile_image(self, gid: int, g: Group):
        e = self._tiles.get(gid)
        ver = self.source.tile_version
        if e is not None and e[0] is g.chunks and e[1] == ver:
            return e[2], e[3]
        regs = self.source.regions.get(g.dim, {})
        x0, x1, z0, z1 = self.model.source_bbox(g)
        w, h = x1 - x0 + 1, z1 - z0 + 1
        n = w * h
        ppc = 16 if n <= 65536 else 4 if n <= 1 << 20 else 1       # pixels per chunk: a huge group is drawn smaller
        out = np.zeros((h * ppc, w * ppc, 4), np.uint8)
        by_reg: Dict[Chunk, list] = {}
        for cx, cz in g.chunks:
            by_reg.setdefault((cx >> 5, cz >> 5), []).append((cx & 31, cz & 31))
        st = 16 // ppc
        for (rx, rz), cs in by_reg.items():
            img = regs.get((rx, rz))
            if img is None:
                continue
            arr = _qimage_array(img)
            if st > 1:
                arr = arr[::st, ::st]
            m = np.zeros((32, 32), bool)
            a = np.array(cs)
            m[a[:, 1], a[:, 0]] = True
            tile = arr * np.kron(m, np.ones((ppc, ppc), bool))[..., None]
            ox, oz = (rx * 32 - x0) * ppc, (rz * 32 - z0) * ppc
            sx0, sz0 = max(0, -ox), max(0, -oz)
            sx1, sz1 = min(32 * ppc, w * ppc - ox), min(32 * ppc, h * ppc - oz)
            if sx1 > sx0 and sz1 > sz0:
                out[oz + sz0:oz + sz1, ox + sx0:ox + sx1] = tile[sz0:sz1, sx0:sx1]
        img = _to_qimage(out, QImage.Format_ARGB32_Premultiplied)
        self._tiles[gid] = (g.chunks, ver, img, ppc)
        return img, ppc

    def _tint_image(self, gid: int, g: Group) -> QImage:
        e = self._tints.get(gid)
        if e is not None and e[0] is g.chunks:
            return e[1]
        x0, x1, z0, z1 = self.model.source_bbox(g)
        arr = np.zeros((z1 - z0 + 1, x1 - x0 + 1, 4), np.uint8)
        a = np.array(list(g.chunks))
        c = self._color(gid)
        arr[a[:, 1] - z0, a[:, 0] - x0] = (c.blue(), c.green(), c.red(), 255)
        img = _to_qimage(arr, QImage.Format_ARGB32)
        self._tints[gid] = (g.chunks, img)
        return img

    def _edge_lines(self, gid: int, g: Group) -> List[QLineF]:
        e = self._edges.get(gid)
        if e is not None and e[0] is g.chunks:
            return e[1]
        x0, x1, z0, z1 = self.model.source_bbox(g)
        cs = g.chunks
        lines: List[QLineF] = []
        if len(cs) > TINT_LIMIT:
            lines = [QLineF(0, 0, x1 - x0 + 1, 0), QLineF(0, z1 - z0 + 1, x1 - x0 + 1, z1 - z0 + 1),
                     QLineF(0, 0, 0, z1 - z0 + 1), QLineF(x1 - x0 + 1, 0, x1 - x0 + 1, z1 - z0 + 1)]
        else:
            for x, z in cs:
                u, v = x - x0, z - z0
                if (x, z - 1) not in cs:
                    lines.append(QLineF(u, v, u + 1, v))
                if (x, z + 1) not in cs:
                    lines.append(QLineF(u, v + 1, u + 1, v + 1))
                if (x - 1, z) not in cs:
                    lines.append(QLineF(u, v, u, v + 1))
                if (x + 1, z) not in cs:
                    lines.append(QLineF(u + 1, v, u + 1, v + 1))
        self._edges[gid] = (g.chunks, lines)
        return lines

    def _forget(self):
        live = set(self.model.ids)
        for cache in (self._tiles, self._tints, self._edges):
            for k in [k for k in cache if k not in live]:
                del cache[k]

    # ---------------------------------------------------------- painting
    def paintEvent(self, _e):
        m = self.model
        _v, bounds, bad_by_dim, problems = m.derived()
        bad = bad_by_dim.get(self.dim, set())
        box = (bounds or {}).get(self.dim)
        self._forget()
        p = QPainter(self)
        W, H = self.width(), self.height()
        p.fillRect(self.rect(), QColor(168, 171, 178) if box else QColor(255, 255, 255))
        tl = self.to_block(QPoint(0, 0))
        br = self.to_block(QPoint(W, H))
        white = QRectF(0, 0, W, H)
        if box is not None:
            a = self.to_screen(box[0] * 16, box[2] * 16)
            b = self.to_screen(box[1] * 16, box[3] * 16)
            white = QRectF(a, b).normalized()
            p.fillRect(white, QColor(255, 255, 255))
        # the grid: chunks (zoomed in), regions
        p.save()
        p.setClipRect(white)
        if self.scale >= 1.5:
            p.setPen(QPen(QColor(0, 0, 0, 34), 1))
            x = math.floor(tl.x() / 16) * 16
            while x <= br.x():
                sx = int(self.to_screen(x, 0).x())
                p.drawLine(sx, 0, sx, H)
                x += 16
            z = math.floor(tl.y() / 16) * 16
            while z <= br.y():
                sz = int(self.to_screen(0, z).y())
                p.drawLine(0, sz, W, sz)
                z += 16
        p.setPen(QPen(QColor(0, 0, 0, 80), 1))
        for rx in range(math.floor(tl.x() / 512), math.floor(br.x() / 512) + 2):
            sx = int(self.to_screen(rx * 512, 0).x())
            p.drawLine(sx, 0, sx, H)
        for rz in range(math.floor(tl.y() / 512), math.floor(br.y() / 512) + 2):
            sz = int(self.to_screen(0, rz * 512).y())
            p.drawLine(0, sz, W, sz)
        p.restore()
        if box is not None:
            p.setPen(QPen(QColor(90, 94, 104), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(white)
        # the groups: tiles, tint, red where the check fails
        shown = []
        for gid, g in zip(m.ids, m.groups):
            if g.dim != self.dim or not g.chunks:
                continue
            x0, x1, z0, z1 = m.placed_bbox(g)
            a = self.to_screen(x0 * 16, z0 * 16)
            b = self.to_screen((x1 + 1) * 16, (z1 + 1) * 16)
            r = QRectF(a, b)
            if not r.intersects(QRectF(0, 0, W, H)):
                continue
            shown.append((gid, g, r, (x0, z0)))
            sel = gid in m.selected
            img, _ppc = self._tile_image(gid, g)
            p.setRenderHint(QPainter.SmoothPixmapTransform, self.scale < 1)
            p.drawImage(r, img)
            p.setRenderHint(QPainter.SmoothPixmapTransform, False)
            if len(g.chunks) <= TINT_LIMIT:
                p.setOpacity(0.32 if sel else 0.14)
                p.drawImage(r, self._tint_image(gid, g))
                p.setOpacity(1.0)
            else:
                c = self._color(gid)
                c.setAlpha(80 if sel else 36)
                p.fillRect(r, c)
            dx, dz = g.offset
            mine = [d for d in bad if (d[0] - dx, d[1] - dz) in g.chunks]
            if mine and len(mine) <= 40000:
                col = QColor(RED.red(), RED.green(), RED.blue(), 150)
                for cx, cz in mine:
                    if tl.x() / 16 - 1 <= cx <= br.x() / 16 + 1 and tl.y() / 16 - 1 <= cz <= br.y() / 16 + 1:
                        s = self.to_screen(cx * 16, cz * 16)
                        p.fillRect(QRectF(s.x(), s.y(), 16 * self.scale, 16 * self.scale), col)
            elif mine:
                p.fillRect(r, QColor(RED.red(), RED.green(), RED.blue(), 90))
            shown[-1] += (bool(mine),)
        # outlines, then names
        for gid, g, r, (x0, z0), is_bad in shown:
            sel = gid in m.selected
            pen = QPen(RED if is_bad else self._color(gid), 4 if sel else 2)
            pen.setCosmetic(True)
            pen.setJoinStyle(Qt.MiterJoin)
            p.save()
            p.translate(r.topLeft())
            p.scale(16 * self.scale, 16 * self.scale)
            p.setPen(pen)
            p.drawLines(self._edge_lines(gid, g))
            p.restore()
        f = self.font()
        f.setPointSize(max(8, f.pointSize() - 1))
        p.setFont(f)
        for gid, g, r, _o, is_bad in shown:
            if r.width() < 28 and gid not in m.selected:
                continue
            pos = QPointF(min(max(r.left() + 4, 4), max(4, W - 60)), min(max(r.top() + 16, 16), H - 6))
            _label(p, pos, g.label(), RED if is_bad else self._color(gid).lighter(150))
        # the spawn of the new world
        sp = m.new_spawn_block() if self.dim == OVERWORLD else None
        if sp is not None:
            s = self.to_screen(sp[0] + 0.5, sp[1] + 0.5)
            p.setPen(QPen(QColor(20, 20, 20), 3))
            p.drawLine(s + QPointF(-9, 0), s + QPointF(9, 0))
            p.drawLine(s + QPointF(0, -9), s + QPointF(0, 9))
            p.setPen(QPen(QColor(255, 70, 70), 2))
            p.drawLine(s + QPointF(-8, 0), s + QPointF(8, 0))
            p.drawLine(s + QPointF(0, -8), s + QPointF(0, 8))
            _label(p, s + QPointF(11, -7), f"Spawn {sp[0]}, {sp[1]}", QColor(255, 120, 120))
        if not shown and not m.groups:
            p.setPen(QColor(120, 125, 135))
            p.drawText(self.rect().adjusted(24, 0, -24, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       tr("The new world is empty. Select chunks on the source map and paste them here (Ctrl+V)."))
        p.end()

    # ---------------------------------------------------------- mouse and keys
    def mousePressEvent(self, e):
        self.setFocus()
        m = self.model
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and self._space):
            self._drag = ("pan", e.position(), QPointF(self.center), False)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if e.button() != Qt.LeftButton:
            return
        gid = self.group_at(e.position())
        ctrl = bool(e.modifiers() & Qt.ControlModifier)
        if gid is None:
            if not ctrl:
                m.select([])
            self._drag = ("pan", e.position(), QPointF(self.center), False)
            self.setCursor(Qt.ClosedHandCursor)
            return
        if ctrl:
            m.select(m.selected ^ {gid})
            if gid not in m.selected:
                return
        elif gid not in m.selected:
            m.select([gid])
        ids = sorted(m.selected)
        m.begin_drag(ids)
        self._move = (self.to_block(e.position()), ids)
        self._drag = ("move", e.position(), None, False)
        self.setCursor(Qt.SizeAllCursor)

    def mouseMoveEvent(self, e):
        if self._drag and self._drag[0] == "pan":
            d = e.position() - self._drag[1]
            self.center = self._drag[2] - QPointF(d.x() / self.scale, d.y() / self.scale)
            self.update()
        elif self._drag and self._drag[0] == "move" and self._move is not None:
            start, _ids = self._move
            now = self.to_block(e.position())
            self.model.drag_to(math.floor((now.x() - start.x()) / 16 + 0.5), math.floor((now.y() - start.y()) / 16 + 0.5))
        else:
            self.setCursor(Qt.SizeAllCursor if self.group_at(e.position()) is not None else Qt.ArrowCursor)
        self._emit_hover(e.position())

    def mouseReleaseEvent(self, e):
        if self._drag and self._drag[0] == "move":
            self.model.end_drag()
        self._drag = None
        self._move = None
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def keyPressEvent(self, e):
        step = BIG_STEP if e.modifiers() & Qt.ShiftModifier else MOVE_STEP
        d = {Qt.Key_Left: (-step, 0), Qt.Key_Right: (step, 0), Qt.Key_Up: (0, -step), Qt.Key_Down: (0, step)}.get(e.key())
        m = self.model
        if d is not None and m.selected:
            m.move(sorted(m.selected), *d)
            self.reveal(m.selected)
        elif e.key() in (Qt.Key_Delete, Qt.Key_Backspace) and m.selected:
            m.delete(sorted(m.selected))
        elif e.key() == Qt.Key_Escape:
            m.select([])
        else:
            super().keyPressEvent(e)
            return
        e.accept()

    def _emit_hover(self, pos):
        b = self.to_block(pos)
        x, z = math.floor(b.x()), math.floor(b.y())
        cx, cz = x >> 4, z >> 4
        text = tr("New world  ·  X {x}  Z {z}   ·   chunk {cx}, {cz}", x=x, z=z, cx=cx, cz=cz)
        gid = self._index().get((cx, cz))
        if gid is not None:
            g = self.model.group(gid)
            text += "   ·   " + tr("{group} (from the source chunk {sx}, {sz})", group=g.name, sx=cx - g.offset[0],
                                   sz=cz - g.offset[1])
        self.hover.emit(text)


# ============================================================ controller (side panel + glue)


class LayoutController(QObject):
    """Builds the "New world" view for a ``MapTab`` and drives it: ``canvas`` and ``panel`` go into the tab's two stacks."""

    changed = Signal()                  # the groups (or their check) changed

    def __init__(self, tab):
        super().__init__(tab)
        self.tab = tab
        self.model = LayoutModel()
        self.model.spawn_fn = self._source_spawn
        self.canvas = LayoutCanvas(self.model, tab.canvas)
        self.canvas.hover.connect(lambda t: tab.hover_label.setText(t))
        self._syncing = False
        self.panel = self._build_panel()
        self.actions: List[QAction] = []
        for text, icons, keys, slot in (
                (tr("Paste selection"), ("edit-paste",), ["Ctrl+V"], self.paste_selection),
                (tr("Undo"), ("edit-undo",), ["Ctrl+Z"], self.model.undo),
                (tr("Redo"), ("edit-redo",), ["Ctrl+Y", "Ctrl+Shift+Z"], self.model.redo)):
            a = QAction(theme.icon(*icons), text, tab)
            a.setShortcuts([QKeySequence(k) for k in keys])
            a.setShortcutContext(Qt.WidgetWithChildrenShortcut)
            a.triggered.connect(slot)
            tab.addAction(a)
            self.actions.append(a)
        self.act_paste, self.act_undo, self.act_redo = self.actions
        self.act_undo.setEnabled(False)
        self.act_redo.setEnabled(False)
        self.model.changed.connect(self._on_changed)
        self.model.selection_changed.connect(self._on_selection)
        self._on_changed()

    # ---------------------------------------------------------- reading
    def _source_spawn(self):
        t = self.tab
        if t.use_spawn.isChecked():
            return t.sx.value(), t.sz.value()
        s = t.canvas.orig_spawn
        return None if s is None else (s[0], s[2])

    def has_groups(self) -> bool:
        return bool(self.model.groups)

    def layout(self) -> Optional[Layout]:
        return self.model.layout() if self.model.groups else None

    def problems(self) -> List[str]:
        return list(self.model.problems())

    # ---------------------------------------------------------- panel
    def _build_panel(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(280)
        body = QWidget()
        v = QVBoxLayout(body)
        self.list_heading = heading(tr("Groups of the new world"))
        v.addWidget(self.list_heading)
        v.addWidget(HintLabel(tr("Select chunks on the source map and paste them here: every paste is a group that you "
                                 "move around the grid. Drag a group to place it; the arrow keys move it by 1 chunk "
                                 "(Shift: 8); Ctrl + click selects several.")))
        self.btn_paste = QPushButton(theme.icon("edit-paste"), tr("Paste selection"))
        self.btn_paste.setToolTip(tr("Add the chunks selected on the source map to the new world as a group (Ctrl+V)"))
        self.btn_paste.clicked.connect(lambda: self.paste_selection())
        self.btn_undo = QPushButton(theme.icon("edit-undo"), tr("Undo"))
        self.btn_undo.setToolTip(tr("Undo the last change of the new world (Ctrl+Z)"))
        self.btn_undo.clicked.connect(lambda: self.model.undo())
        self.btn_redo = QPushButton(theme.icon("edit-redo"), tr("Redo"))
        self.btn_redo.setToolTip(tr("Redo the change undone (Ctrl+Y)"))
        self.btn_redo.clicked.connect(lambda: self.model.redo())
        v.addWidget(row(self.btn_paste, self.btn_undo, self.btn_redo))
        self.list = QListWidget()
        self.list.setSelectionMode(QListWidget.ExtendedSelection)
        self.list.setMinimumHeight(110)
        self.list.setAccessibleName(tr("Groups of the new world"))
        self.list.itemSelectionChanged.connect(self._list_selected)
        v.addWidget(self.list, 1)

        v.addWidget(heading(tr("Selected group"), space_above=True))
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.name_edit = QLineEdit()
        self.name_edit.setAccessibleName(tr("Group name"))
        self.name_edit.editingFinished.connect(self._renamed)
        form.addRow(tr("Name:"), self.name_edit)
        self.off_x, self.off_z = QSpinBox(), QSpinBox()
        for sb, lab in ((self.off_x, "X"), (self.off_z, "Z")):
            sb.setRange(-2000000, 2000000)
            sb.setAccessibleName(tr("Offset {axis} (chunks)", axis=lab))
            sb.valueChanged.connect(self._offset_edited)
            form.addRow(tr("Offset {axis} (chunks):", axis=lab), sb)
        v.addLayout(form)
        self.btn_back = QPushButton(theme.icon("go-previous", "edit-undo"), tr("Back to its place"))
        self.btn_back.setToolTip(tr("Put the group at the coordinates it has in the source world (offset 0, 0)"))
        self.btn_back.clicked.connect(self.back_to_place)
        self.btn_spawn = QPushButton(theme.icon("mark-location", "go-home"), tr("Centre on the spawn"))
        self.btn_spawn.setToolTip(tr("Move the selected groups so that their centre is on the spawn of the new world"))
        self.btn_spawn.clicked.connect(self.centre_on_spawn)
        self.btn_delete = QPushButton(theme.icon("edit-delete", "delete"), tr("Delete"))
        self.btn_delete.setToolTip(tr("Remove the selected groups from the new world (the source world is not "
                                      "changed) (Del)"))
        self.btn_delete.clicked.connect(lambda: self.model.delete(sorted(self.model.selected)))
        v.addWidget(row(self.btn_back, self.btn_spawn))
        v.addWidget(row(self.btn_delete))

        v.addWidget(heading(tr("Check"), space_above=True))
        self.check_label = HintLabel("")
        v.addWidget(self.check_label)

        v.addWidget(heading(tr("Layout file"), space_above=True))
        self.btn_save = QPushButton(theme.icon("document-save", "document-save-as"), tr("Save layout…"))
        self.btn_save.setToolTip(tr("Save the groups and their places to a file (JSON), to use again or with the "
                                    "command line (--layout)"))
        self.btn_save.clicked.connect(self.save_layout)
        self.btn_load = QPushButton(theme.icon("document-open"), tr("Load layout…"))
        self.btn_load.setToolTip(tr("Replace the groups with those of a layout file"))
        self.btn_load.clicked.connect(self.load_layout)
        self.btn_clear = QPushButton(theme.icon("edit-clear", "edit-delete"), tr("Remove all groups"))
        self.btn_clear.setToolTip(tr("Empty the new world: the “Move the selected chunks” choice of the map is "
                                     "available again"))
        self.btn_clear.clicked.connect(lambda: self.model.delete(list(self.model.ids)))
        v.addWidget(row(self.btn_save, self.btn_load))
        v.addWidget(row(self.btn_clear))
        v.addStretch(1)
        scroll.setWidget(body)
        return scroll

    # ---------------------------------------------------------- refreshing
    def set_dim(self, dim: int) -> None:
        self.canvas.dim = dim
        m = self.model
        m.select([i for i in m.selected if m.group(i).dim == dim])
        self.canvas.update()
        self._on_changed()

    def _gids(self) -> List[int]:
        m = self.model
        return [i for i, g in zip(m.ids, m.groups) if g.dim == self.canvas.dim]

    def _on_changed(self):
        m = self.model
        self._syncing = True
        try:
            sel = set(m.selected)
            self.list.blockSignals(True)
            self.list.clear()
            for gid in self._gids():
                g = m.group(gid)
                it = QListWidgetItem(tr("{name} · {n} chunks · offset {dx}, {dz}", name=g.name, n=len(g.chunks),
                                        dx=g.offset[0], dz=g.offset[1]))
                it.setData(Qt.UserRole, gid)
                pm = QPixmap(12, 12)
                pm.fill(self.canvas._color(gid))
                it.setIcon(pm)
                self.list.addItem(it)
                it.setSelected(gid in sel)
            self.list.blockSignals(False)
            self.list_heading.setText(tr("Groups of the new world") + f" – {DIM_NAMES.get(self.canvas.dim, '')}")
            self._fill_selected()
            self.btn_undo.setEnabled(m.can_undo())
            self.btn_redo.setEnabled(m.can_redo())
            self.act_undo.setEnabled(m.can_undo())
            self.act_redo.setEnabled(m.can_redo())
            self.btn_clear.setEnabled(bool(m.groups))
            self.btn_save.setEnabled(bool(m.groups))
            probs = m.problems()
            if probs:
                lines = [theme.span(_esc(t), "negative") for t in probs[:5]]
                if len(probs) > 5:
                    lines.append(theme.span(tr("… and {n} more problems.", n=len(probs) - 5), "negative"))
                self.check_label.setText("<br>".join(lines))
            elif m.groups:
                self.check_label.setText(theme.span(tr("The new world is valid: {groups} groups, {n} chunks.",
                                                       groups=len(m.groups), n=sum(len(g.chunks) for g in m.groups)),
                                                    "positive"))
            else:
                self.check_label.setText(tr("No group yet: the conversion uses the choices of the map as usual."))
        finally:
            self._syncing = False
        self.changed.emit()

    def _on_selection(self):
        self._syncing = True
        try:
            self.list.blockSignals(True)
            for k in range(self.list.count()):
                it = self.list.item(k)
                it.setSelected(it.data(Qt.UserRole) in self.model.selected)
            self.list.blockSignals(False)
            self._fill_selected()
        finally:
            self._syncing = False
        self.canvas.update()

    def _fill_selected(self):
        m = self.model
        sel = sorted(m.selected)
        one = len(sel) == 1
        self.name_edit.setEnabled(one)
        self.off_x.setEnabled(one)
        self.off_z.setEnabled(one)
        for w in (self.btn_back, self.btn_spawn, self.btn_delete):
            w.setEnabled(bool(sel))
        for sb in (self.off_x, self.off_z, self.name_edit):
            sb.blockSignals(True)
        if one:
            g = m.group(sel[0])
            self.name_edit.setText(g.name)
            self.off_x.setValue(g.offset[0])
            self.off_z.setValue(g.offset[1])
        else:
            self.name_edit.setText(tr("{n} groups selected", n=len(sel)) if sel else "")
            self.off_x.setValue(0)
            self.off_z.setValue(0)
        for sb in (self.off_x, self.off_z, self.name_edit):
            sb.blockSignals(False)

    def _list_selected(self):
        if not self._syncing:
            self.model.select([it.data(Qt.UserRole) for it in self.list.selectedItems()])

    def _renamed(self):
        sel = sorted(self.model.selected)
        if len(sel) == 1 and not self._syncing:
            name = self.name_edit.text().strip()
            if name:
                self.model.rename(sel[0], name)
            else:
                self._fill_selected()

    def _offset_edited(self):
        sel = sorted(self.model.selected)
        if len(sel) == 1 and not self._syncing:
            self.model.set_offsets({sel[0]: (self.off_x.value(), self.off_z.value())})

    # ---------------------------------------------------------- actions
    def paste_selection(self) -> Optional[int]:
        """The chunks selected on the source map (current dimension) become a group of the new world."""
        t = self.tab
        dim = t.canvas.dim
        sel = set(t.canvas.selected(dim)) if dim is not None else set()
        if not sel:
            self._say(tr("Select some chunks on the source map first."))
            return None
        taken = set()
        for g in self.model.groups:
            if g.dim == dim:
                taken |= g.chunks
        new = sel - taken
        if not new:
            self._say(tr("These chunks are already in a group of the new world."))
            return None
        gid = self.model.paste(dim, new)
        msg = tr("{group} pasted: {n} chunks.", group=self.model.group(gid).name, n=len(new))
        if len(new) < len(sel):
            msg += " " + tr("{n} chunks left out (already in another group).", n=len(sel) - len(new))
        self._say(msg)
        self.canvas.reveal([gid])
        return gid

    def _say(self, text: str) -> None:
        self.tab.status.setText(text)

    def back_to_place(self):
        self.model.set_offsets({i: (0, 0) for i in self.model.selected})

    def centre_on_spawn(self):
        """The selected groups, together, centred on the spawn of the new world (the groups not selected decide where it
        is; without any, the centre of the finite map or the block 0, 0)."""
        m = self.model
        sel = sorted(m.selected)
        if not sel:
            return
        rest = Layout([g for i, g in zip(m.ids, m.groups) if i not in m.selected])
        src = self._source_spawn()
        target = None
        if src is not None:
            o = rest.offset(OVERWORLD, math.floor(src[0]) >> 4, math.floor(src[1]) >> 4)
            target = (src[0] + o[0] * 16, src[1] + o[1] * 16) if o is not None else None
        if target is None:
            target = rest.default_spawn()
        if target is None:
            box = (m.derived()[1] or {}).get(m.group(sel[0]).dim)
            target = ((box[0] + box[1]) * 8, (box[2] + box[3]) * 8) if box else (0, 0)
        boxes = [m.placed_bbox(m.group(i)) for i in sel]
        cx = (min(b[0] for b in boxes) + max(b[1] for b in boxes)) >> 1
        cz = (min(b[2] for b in boxes) + max(b[3] for b in boxes)) >> 1
        m.move(sel, (math.floor(target[0]) >> 4) - cx, (math.floor(target[1]) >> 4) - cz)
        self.canvas.reveal(sel)

    def save_layout(self):
        if not self.model.groups:
            return
        f, _ = QFileDialog.getSaveFileName(self.tab, tr("Save layout"), tr("layout") + ".json", tr("Layout") + " (*.json)")
        if f:
            try:
                self.model.layout().save(f)
                self._say(tr("Layout saved to {path}", path=f))
            except OSError as ex:
                self._say(tr("Saving failed: {error}", error=ex))

    def load_layout(self, path: str = ""):
        if not path:
            path, _ = QFileDialog.getOpenFileName(self.tab, tr("Load layout"), "", tr("Layout") + " (*.json);;" + tr("All files") + " (*)")
        if not path:
            return
        try:
            lay = Layout.load(path)
        except (OSError, ValueError) as ex:
            QMessageBox.warning(self.tab, tr("Load layout"), tr("The layout cannot be loaded:") + f"\n\n{ex}")
            return
        self.model.load(lay)
        msg = tr("Layout loaded: {n} groups.", n=len(lay.groups))
        missing = sum(1 for g in lay.groups if g.dim in self.tab._loaded_dims for c in g.chunks
                      if c not in self.tab.canvas.present.get(g.dim, ()))
        if missing:
            msg += " " + tr("{n} chunks of the file do not exist in this world.", n=missing)
        self._say(msg)
        self.canvas.fit_layout()

    # ---------------------------------------------------------- state
    def clear(self) -> None:
        self.model.clear()

    def export_state(self) -> dict:
        return {"model": self.model.export(), "view": (self.canvas.center.x(), self.canvas.center.y(), self.canvas.scale),
                "fitted": self.canvas._fitted}

    def import_state(self, st: dict) -> None:
        self.model.restore(st["model"])
        x, z, scale = st["view"]
        self.canvas.center, self.canvas.scale = QPointF(x, z), scale
        self.canvas._fitted = st["fitted"]
        self.canvas.update()


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
