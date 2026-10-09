"""The "Giocatori" tab: which players of the source world are carried over, which one becomes
the main (single-player) player and to which nickname each one is linked in the target."""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QRadioButton, QTableWidget, QVBoxLayout, QWidget,
)

from ..selection import PlayerLink, offline_uuid
from ..i18n import N_, tr
from . import theme
from .widgets import HintLabel

HINTS = {
    "java": N_("Java: the nickname decides the player's <i>playerdata/&lt;UUID&gt;.dat</i> file. With “Premium” the UUID "
               "is looked up online on Mojang's servers (original account); without it, the offline UUID is used "
               "(non-premium servers / LAN). The main player is the one who finds the inventory when the world is "
               "opened in single player."),
    "bedrock": N_("Bedrock: only the main player (the world's local player) is transferred; no nickname is needed."),
    "lce": N_("Legacy Console Edition: this takes the <b>XUID</b>, not the nickname: the number that names the "
              "player's file in <i>players/</i> (on PC neoLegacy gives it to your installation: take it from one of "
              "your worlds with “From my world…” in the Conversion tab). With a nickname the game does not find the "
              "player, who starts again at the spawn without an inventory."),
    "pe_old": N_("Pocket Edition 0.x: only the main player is transferred."),
}


PET_HINT = N_("<b>Tamed animals</b> (wolves, cats, parrots, horses…) must know their owner's UUID. <i>Java account "
              "name</i>: the main player's nickname above (with “Premium” for an original account, without it for an "
              "offline one) gives the animals the account's UUID: exact, but the name has to be right. <i>First player "
              "who opens the world</i>: no name needed, a small data pack (Java 1.16+) hands each animal to the nearest "
              "player when its chunk loads; on a multiplayer server that may not be the main player. "
              "<i>Automatic</i> uses the nickname when there is one, else the first player.")


class PlayersTab(QWidget):
    center_requested = Signal(object)  # PlayerEntry
    changed = Signal()                 # the choices changed (see summary())

    def __init__(self, parent=None):
        super().__init__(parent)
        self.entries = []
        self._family = "java"
        self._pending = None
        v = QVBoxLayout(self)
        self.enable = QCheckBox(tr("Choose the players to transfer and link them to a nickname"))
        self.enable.setToolTip(tr("When off, the world's main player is transferred as usual"))
        self.enable.toggled.connect(self._on_enable)
        v.addWidget(self.enable)
        self.hint = HintLabel()
        self.hint.setTextFormat(Qt.RichText)
        v.addWidget(self.hint)
        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels([tr("Transfer"), tr("Main"), tr("Player in the source world"),
                                              tr("Position"), tr("Target nickname"), tr("Premium")])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.Stretch)
        hh.setSectionResizeMode(4, QHeaderView.Stretch)
        for c in (0, 1, 3, 5):
            hh.setSectionResizeMode(c, QHeaderView.ResizeToContents)
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.NoSelection)
        self.table.cellDoubleClicked.connect(self._on_double)
        v.addWidget(self.table, 1)
        self.empty = HintLabel(tr("No players found in the source world: open a world at the top."))
        self.empty.setAlignment(Qt.AlignCenter)
        v.addWidget(self.empty)
        foot = HintLabel(tr("Double-click a player to see them on the map."))
        v.addWidget(foot)
        self.pet_row = QWidget()
        pr = QHBoxLayout(self.pet_row)
        pr.setContentsMargins(0, 0, 0, 0)
        pr.addWidget(QLabel(tr("Tamed animals belong to:")))
        self.pet_owner_box = QComboBox()
        for label, key in ((tr("Automatic"), "auto"), (tr("The Java account of the nickname"), "account"),
                           (tr("The first player who opens the world"), "first-player")):
            self.pet_owner_box.addItem(label, key)
        self.pet_owner_box.currentIndexChanged.connect(lambda _i: self.changed.emit())
        pr.addWidget(self.pet_owner_box, 1)
        v.addWidget(self.pet_row)
        self.pet_hint = HintLabel()
        self.pet_hint.setTextFormat(Qt.RichText)
        self.pet_hint.setText(tr(PET_HINT))
        v.addWidget(self.pet_hint)
        self.host_group = QButtonGroup(self)
        self.host_group.setExclusive(True)
        self._rows = []
        self.set_family("java")
        self._on_enable(False)

    # ---------------------------------------------------------- data
    def set_players(self, entries):
        self.entries = list(entries or [])
        self.table.setRowCount(0)
        for b in list(self.host_group.buttons()):
            self.host_group.removeButton(b)
        self._rows = []
        for i, e in enumerate(self.entries):
            self.table.insertRow(i)
            inc = QCheckBox()
            inc.setChecked(True)
            host = QRadioButton()
            self.host_group.addButton(host, i)
            if i == 0:
                host.setChecked(True)
            nick = QLineEdit(e.name or "")
            nick.setPlaceholderText(tr("nickname (optional)"))
            nick.textChanged.connect(lambda _t, r=i: self._on_nick(r))
            nick.textChanged.connect(lambda _t: self.changed.emit())
            inc.toggled.connect(lambda _on: self.changed.emit())
            host.toggled.connect(lambda _on: self.changed.emit())
            prem = QCheckBox()
            prem.setChecked(True)
            self.table.setCellWidget(i, 0, _centered(inc))
            self.table.setCellWidget(i, 1, _centered(host))
            label = QLabel(f"  {e.label}   " + theme.span("· " + tr("{n} items", n=e.items), "secondary"))
            label.setToolTip(e.key)
            self.table.setCellWidget(i, 2, label)
            pos = ", ".join(f"{v:.0f}" for v in e.pos) if e.pos else "?"
            dim = {0: "", -1: " (Nether)", 1: " (End)"}.get(e.dim, "")
            self.table.setCellWidget(i, 3, QLabel(f"  {pos}{dim}  "))
            self.table.setCellWidget(i, 4, nick)
            self.table.setCellWidget(i, 5, _centered(prem))
            self._rows.append((inc, host, nick, prem))
        self.empty.setVisible(not self.entries)
        self.table.setVisible(bool(self.entries))
        self.enable.setEnabled(bool(self.entries))
        self.enable.setChecked(False)
        self._on_enable(False)
        self.set_family(self._family)
        if self._pending is not None:
            self.import_state(self._pending)
        self.changed.emit()

    def export_state(self) -> dict:
        """The choices, by player (the window is rebuilt when the language changes)."""
        rows = {e.key: (inc.isChecked(), host.isChecked(), nick.text(), prem.isChecked())
                for e, (inc, host, nick, prem) in zip(self.entries, self._rows)}
        return {"enable": self.enable.isChecked(), "rows": rows, "pet_owner": self.pet_owner()}

    def import_state(self, st: dict) -> None:
        """export_state()'s choices; kept until the same players are loaded."""
        if not self.entries:
            self._pending = st
            return
        self._pending = None
        for e, (inc, host, nick, prem) in zip(self.entries, self._rows):
            if e.key in st["rows"]:
                on, is_host, name, premium = st["rows"][e.key]
                inc.setChecked(on)
                if is_host:
                    host.setChecked(True)
                nick.setText(name)
                prem.setChecked(premium)
        self.enable.setChecked(st["enable"])
        self._on_enable(st["enable"])
        i = self.pet_owner_box.findData(st.get("pet_owner", "auto"))
        self.pet_owner_box.setCurrentIndex(max(0, i))

    def set_family(self, family: str):
        self._family = family
        self.hint.setText(tr(HINTS[family]) if family in HINTS else "")
        for inc, host, nick, prem in self._rows:
            nick.setEnabled(self.enable.isChecked() and family in ("java", "lce"))
            prem.setEnabled(self.enable.isChecked() and family == "java")
        self.table.setColumnHidden(5, family != "java")
        for w in (self.pet_row, self.pet_hint):
            w.setVisible(family == "java")

    def _on_enable(self, on: bool):
        self.table.setEnabled(on)
        self.set_family(self._family)
        self.changed.emit()

    def _on_nick(self, row: int):
        inc, host, nick, prem = self._rows[row]
        if nick.text().strip() and self._family == "java":
            nick.setToolTip(tr("Offline UUID: {uuid}", uuid=offline_uuid(nick.text().strip())))
        if not self.enable.isChecked() and nick.hasFocus():
            self.enable.setChecked(True)

    def _on_double(self, row: int, _col: int):
        if 0 <= row < len(self.entries):
            self.center_requested.emit(self.entries[row])

    # ---------------------------------------------------------- result
    def summary(self) -> str:
        """The choice in a few words (shown on the conversion tab)."""
        if not self.entries:
            return tr("No players in the source world") if hasattr(self, "_rows") else ""
        if not self.enable.isChecked():
            return tr("The main player, as in the source world")
        host = self.host_group.checkedId()
        n = sum(1 for i, (inc, *_r) in enumerate(self._rows) if inc.isChecked() or i == host)
        main = self.entries[host].label if 0 <= host < len(self.entries) else "?"
        return tr("{n} of {total} transferred · main: {main}", n=n, total=len(self.entries), main=main)

    def pet_owner(self) -> str:
        """Who the tamed animals of a Java target belong to: auto | account | first-player (worldbridge.pets)."""
        return self.pet_owner_box.currentData() or "auto"

    def links(self) -> Optional[List[PlayerLink]]:
        if not self.enable.isChecked() or not self.entries:
            return None
        out = []
        host_row = self.host_group.checkedId()
        for i, (e, (inc, host, nick, prem)) in enumerate(zip(self.entries, self._rows)):
            out.append(PlayerLink(key=e.key, include=inc.isChecked() or i == host_row, host=i == host_row,
                                  nickname=nick.text().strip() or None, online=prem.isChecked()))
        return out


def _centered(w: QWidget) -> QWidget:
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setAlignment(Qt.AlignCenter)
    lay.addWidget(w)
    return box
