"""App launcher: Launchpad grid + Spotlight-like search (replaces the Start menu)."""
from __future__ import annotations

from PyQt5.QtCore import QFileInfo, QPoint, QSize, Qt, QTimer
from PyQt5.QtGui import QIcon
from PyQt5.QtWidgets import (QApplication, QFileIconProvider, QHBoxLayout, QLabel, QLineEdit,
                             QListView, QListWidget, QListWidgetItem, QVBoxLayout)

from .. import icons
from ..theme import font_family
from .common import GlassPopup, RoundButton


class Launcher(GlassPopup):
    W, H = 700, 560

    def __init__(self, hub):
        super().__init__(hub)
        self.apps = None
        self._pending = []
        self._provider = QFileIconProvider()
        self._icon_timer = QTimer(self, interval=0, timeout=self._load_some_icons)
        m = self.margin
        self.setFixedSize(self.W + 2 * m, self.H + 2 * m)
        root = QVBoxLayout(self)
        root.setContentsMargins(m + 18, m + 18, m + 18, m + 14)
        root.setSpacing(12)
        top = QHBoxLayout()
        self.search_icon = QLabel()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search apps…")
        self.search.textChanged.connect(self._filter)
        self.search.returnPressed.connect(self._launch_first)
        top.addWidget(self.search_icon)
        top.addWidget(self.search, 1)
        b_set = RoundButton("settings", 34, flat=True, tooltip="Nocthify Settings")
        b_set.clicked.connect(lambda: self._do("settings"))
        b_pow = RoundButton("power", 34, flat=True, tooltip="Lock")
        b_pow.clicked.connect(lambda: self._do("lock"))
        top.addWidget(b_set)
        top.addWidget(b_pow)
        root.addLayout(top)
        self.grid = QListWidget()
        self.grid.setViewMode(QListView.IconMode)
        self.grid.setResizeMode(QListView.Adjust)
        self.grid.setMovement(QListView.Static)
        self.grid.setIconSize(QSize(48, 48))
        self.grid.setGridSize(QSize(120, 96))
        self.grid.setWordWrap(False)
        self.grid.setTextElideMode(Qt.ElideRight)
        self.grid.setSpacing(4)
        self.grid.setUniformItemSizes(True)
        self.grid.setFrameShape(QListWidget.NoFrame)
        self.grid.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.grid.itemActivated.connect(self._launch_item)
        self.grid.itemClicked.connect(self._launch_item)
        root.addWidget(self.grid, 1)
        self.on_theme()

    def on_theme(self):
        pal = self.pal
        fg = pal.fg.name()
        fg2 = f"rgba({pal.fg.red()},{pal.fg.green()},{pal.fg.blue()},150)"
        tile = pal.tile
        hov = pal.tile_hover
        fam = font_family()
        self.search_icon.setPixmap(icons.pixmap("search", pal.fg2, 18))
        self.search.setStyleSheet(
            f"QLineEdit {{ background: rgba({tile.red()},{tile.green()},{tile.blue()},{tile.alpha()});"
            f" color: {fg}; border: none; border-radius: 12px; padding: 9px 14px; font-family: '{fam}';"
            f" font-size: 15px; selection-background-color: {pal.accent.name()}; }}")
        self.grid.setStyleSheet(
            f"QListWidget {{ background: transparent; color: {fg}; font-family: '{fam}'; font-size: 12px;"
            f" outline: none; }}"
            f"QListWidget::item {{ border-radius: 14px; padding: 6px; color: {fg}; }}"
            f"QListWidget::item:hover {{ background: rgba({hov.red()},{hov.green()},{hov.blue()},{hov.alpha()}); }}"
            f"QListWidget::item:selected {{ background: {pal.accent.name()}; color: white; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}"
            f"QScrollBar::handle:vertical {{ background: {fg2}; border-radius: 4px; min-height: 30px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page"
            f" {{ background: none; height: 0; }}")
        self.update()

    def _do(self, action):
        self.hide()
        QTimer.singleShot(60, lambda: self.hub.do(action))

    def _populate(self):
        self.apps = self.hub.backend.list_apps()
        self.grid.clear()
        placeholder = icons.icon("app", self.pal.fg2.name(), 52)
        self._pending = []
        for app in self.apps:
            it = QListWidgetItem(placeholder, app.name)
            it.setData(Qt.UserRole, app.path)
            it.setData(Qt.UserRole + 1, (app.name + " " + (app.keywords or "")).lower())
            it.setToolTip(app.name)
            it.setTextAlignment(Qt.AlignHCenter | Qt.AlignTop)
            self.grid.addItem(it)
            self._pending.append((it, app))
        self._icon_timer.start()

    def _load_some_icons(self):
        for _ in range(12):
            if not self._pending:
                self._icon_timer.stop()
                return
            it, app = self._pending.pop(0)
            hint = app.icon_hint or ""
            if hint.startswith("glyph:"):
                ic = icons.icon(hint[6:], self.pal.fg.name(), 52)
            elif self.hub.backend.name == "linux":
                pm = self.hub.backend.app_icon(app.path, 52)
                ic = QIcon(pm) if pm is not None else None
            else:
                pm = self.hub.backend.file_icon(app.path, 48)
                ic = QIcon(pm) if pm is not None else self._provider.icon(QFileInfo(app.path))
            if ic is not None and not ic.isNull():
                it.setIcon(ic)

    def _filter(self, text):
        q = text.strip().lower()
        first = None
        for i in range(self.grid.count()):
            it = self.grid.item(i)
            hit = not q or all(part in it.data(Qt.UserRole + 1) for part in q.split())
            it.setHidden(not hit)
            if hit and first is None:
                first = it
        if first is not None:
            self.grid.setCurrentItem(first)

    def _launch_first(self):
        it = self.grid.currentItem()
        if it is not None and not it.isHidden():
            self._launch_item(it)

    def _launch_item(self, it):
        path = it.data(Qt.UserRole)
        self.hide()
        self.hub.backend.launch(path)

    def toggle(self):
        if self.isVisible():
            self.hide()
            return
        if self.apps is None:
            self._populate()
        self.search.clear()
        self._filter("")
        dock = self.hub.dock
        if dock is not None and dock.isVisible():
            # rise out of the dock, like Launchpad / the Windows 11 start menu
            pos, rise = dock.popup_pos(self.width(), self.height(), margin=self.margin)
        else:
            g = QApplication.primaryScreen().availableGeometry()
            pos = QPoint(g.center().x() - self.width() // 2, g.center().y() - self.height() // 2 - 20)
            rise = QPoint(0, 30)
        self.popup_at(pos, rise)
        self.search.setFocus()

    def refresh(self):
        self.apps = None
