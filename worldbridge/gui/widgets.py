"""Small building blocks shared by the tabs, following the KDE Human Interface Guidelines
(develop.kde.org/hig): secondary text in the palette's inactive colour, long explanations behind a
contextual help button instead of only in a tooltip, in-window messages instead of message boxes,
section headings instead of framed group boxes."""

from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from PySide6.QtCore import QEvent, QPoint, Qt, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QStyle, QToolButton, QVBoxLayout, QWhatsThis, QWidget,
)

from . import theme
from ..i18n import tr


def spacing(widget: Optional[QWidget] = None, large: bool = False) -> int:
    """The style's spacing between related controls (``large``: between groups)."""
    st = widget.style() if widget is not None else None
    if st is None:
        from PySide6.QtWidgets import QApplication

        st = QApplication.style()
    s = st.pixelMetric(QStyle.PM_LayoutVerticalSpacing)
    s = s if s > 0 else 6
    return s * 3 if large else s


class HintLabel(QLabel):
    """Secondary, word-wrapped text (explanations under a control or on top of a page)."""

    def __init__(self, text: str = "", parent=None, wrap: bool = True):
        super().__init__(text, parent)
        self.setWordWrap(wrap)
        self.setTextFormat(Qt.RichText if "<" in text else Qt.AutoText)
        self.setTextInteractionFlags(Qt.LinksAccessibleByMouse)     # no keyboard stop on every hint
        self.setOpenExternalLinks(True)
        self._recolor()

    def setText(self, text: str) -> None:  # noqa: N802 (Qt API)
        if "<" in text:
            self.setTextFormat(Qt.RichText)
        super().setText(text)

    def _recolor(self):
        pal = self.palette()
        col = theme.secondary_color(self.parentWidget()) if self.parentWidget() is not None \
            else theme.secondary_color()
        if pal.color(QPalette.WindowText) != col:
            pal.setColor(QPalette.WindowText, col)
            pal.setColor(QPalette.Text, col)
            self.setPalette(pal)

    def changeEvent(self, e):  # noqa: N802
        super().changeEvent(e)
        if e.type() in (QEvent.PaletteChange, QEvent.StyleChange, QEvent.ParentChange):
            self._recolor()


def heading(text: str, space_above: bool = False) -> QLabel:
    """A section heading: the normal font in bold, like KDE's form sections; ``space_above``
    separates it from the group before (the HIG's large spacing between groups)."""
    lab = QLabel(text)
    f = lab.font()
    f.setBold(True)
    lab.setFont(f)
    lab.setAccessibleName(text)
    if space_above:
        lab.setContentsMargins(0, spacing(None, large=True), 0, 0)
    return lab


class HelpButton(QToolButton):
    """KDE's contextual help button: a small "?" that shows a longer explanation on click."""

    def __init__(self, text: str, parent=None):
        super().__init__(parent)
        self._text = text
        self.setIcon(theme.icon("help-contextual", "help-about", fallback=QStyle.SP_MessageBoxQuestion))
        if self.icon().isNull():
            self.setText("?")
        self.setAutoRaise(True)
        self.setCursor(Qt.WhatsThisCursor)
        self.setToolTip(tr("Show the explanation"))
        self.setAccessibleName(tr("Help"))
        self.setAccessibleDescription(text)
        self.setFocusPolicy(Qt.TabFocus)
        self.clicked.connect(self._show)

    def _show(self):
        html = "<p style='white-space:pre-wrap'>" + _esc(self._text).replace("\n", "<br>") + "</p>"
        QWhatsThis.showText(self.mapToGlobal(QPoint(self.width() // 2, self.height())), html, self)


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def with_help(widget: QWidget, text: str) -> QWidget:
    """``widget`` followed by its help button, in one row."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.addWidget(widget)
    lay.addWidget(HelpButton(text))
    lay.addStretch(1)
    return box


def row(*items, stretch: bool = True, margins: bool = False) -> QWidget:
    """Widgets side by side (an int adds that much space)."""
    box = QWidget()
    lay = QHBoxLayout(box)
    if not margins:
        lay.setContentsMargins(0, 0, 0, 0)
    for it in items:
        if isinstance(it, int):
            lay.addSpacing(it)
        else:
            lay.addWidget(it)
    if stretch:
        lay.addStretch(1)
    return box


class InlineMessage(QFrame):
    """KDE's in-window message (KMessageWidget): a tinted box with text, actions and a close
    button; for results and problems that should not interrupt with a dialog."""

    closed = Signal()
    ICONS = {"positive": ("dialog-positive", QStyle.SP_DialogApplyButton),
             "neutral": ("dialog-warning", QStyle.SP_MessageBoxWarning),
             "negative": ("dialog-error", QStyle.SP_MessageBoxCritical),
             "information": ("dialog-information", QStyle.SP_MessageBoxInformation)}

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setAutoFillBackground(True)
        self._kind = "information"
        lay = QHBoxLayout(self)
        self.icon = QLabel()
        self.icon.setAlignment(Qt.AlignTop)
        lay.addWidget(self.icon)
        self.text = QLabel()
        self.text.setWordWrap(True)
        self.text.setTextInteractionFlags(Qt.TextSelectableByMouse | Qt.LinksAccessibleByMouse)
        self.text.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        lay.addWidget(self.text, 1)
        self.actions_box = QHBoxLayout()
        lay.addLayout(self.actions_box)
        self.close_btn = QToolButton()
        self.close_btn.setAutoRaise(True)
        self.close_btn.setIcon(theme.icon("dialog-close", "window-close", fallback=QStyle.SP_TitleBarCloseButton))
        self.close_btn.setToolTip(tr("Close the message"))
        self.close_btn.setAccessibleName(tr("Close the message"))
        self.close_btn.clicked.connect(self.dismiss)
        lay.addWidget(self.close_btn, 0, Qt.AlignTop)
        self._buttons: List[QPushButton] = []
        self.hide()

    def show_message(self, kind: str, text: str, actions: Tuple[Tuple[str, Callable], ...] = ()) -> None:
        self._kind = kind
        self.text.setText(text)
        name, sp = self.ICONS.get(kind, self.ICONS["information"])
        ic = theme.icon(name, fallback=sp)
        size = self.style().pixelMetric(QStyle.PM_SmallIconSize) * 2
        self.icon.setPixmap(ic.pixmap(size, size))
        for b in self._buttons:
            b.deleteLater()
        self._buttons = []
        for label, slot in actions:
            b = QPushButton(label)
            b.clicked.connect(slot)
            self.actions_box.addWidget(b, 0, Qt.AlignTop)
            self._buttons.append(b)
        self._tint()
        self.show()

    def dismiss(self):
        self.hide()
        self.closed.emit()

    def _tint(self):
        base = self.parentWidget().palette() if self.parentWidget() is not None else self.palette()
        if self._kind == "information":
            col = base.color(QPalette.Highlight)
        else:
            col = theme.state_color(self._kind)
        win = base.color(QPalette.Window)
        mix = QColor(round(win.red() * 0.8 + col.red() * 0.2), round(win.green() * 0.8 + col.green() * 0.2),
                     round(win.blue() * 0.8 + col.blue() * 0.2))
        pal = self.palette()
        pal.setColor(QPalette.Window, mix)
        pal.setColor(QPalette.Base, mix)
        pal.setColor(QPalette.Mid, col)
        pal.setColor(QPalette.Dark, col)
        pal.setColor(QPalette.Light, col)
        self.setPalette(pal)

    def changeEvent(self, e):  # noqa: N802
        super().changeEvent(e)
        if e.type() in (QEvent.StyleChange, QEvent.ParentChange):
            self._tint()


class Disclosure(QWidget):
    """A collapsed section: an arrow button that shows or hides ``content``."""

    toggled = Signal(bool)

    def __init__(self, title: str, content: QWidget, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.button = QToolButton()
        self.button.setText(title)
        self.button.setCheckable(True)
        self.button.setAutoRaise(True)
        self.button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.button.setArrowType(Qt.RightArrow)
        self.button.toggled.connect(self.set_open)
        v.addWidget(self.button)
        self.content = content
        v.addWidget(content, 1)
        content.hide()

    def set_open(self, on: bool) -> None:
        if self.button.isChecked() != on:
            self.button.setChecked(on)
            return
        self.button.setArrowType(Qt.DownArrow if on else Qt.RightArrow)
        self.content.setVisible(on)
        self.toggled.emit(on)
