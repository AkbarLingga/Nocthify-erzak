"""Small popups opened from the dock's status area: volume and calendar."""
from __future__ import annotations

import time

from PyQt5.QtCore import QDate, QLocale, QRectF, Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout

from .. import icons
from ..theme import font
from .common import BigSlider, GlassPopup, RoundButton


class VolumePopup(GlassPopup):
    WIDTH = 300

    def __init__(self, hub):
        super().__init__(hub)
        m = self.margin
        self._apply_timer = QTimer(self, singleShot=True, interval=40, timeout=self._apply)
        root = QVBoxLayout(self)
        root.setContentsMargins(m + 14, m + 12, m + 14, m + 12)
        root.setSpacing(8)
        top = QHBoxLayout()
        self.title = QLabel("Sound")
        self.value = QLabel("")
        top.addWidget(self.title, 1)
        top.addWidget(self.value)
        root.addLayout(top)
        self.slider = BigSlider("volume")
        root.addWidget(self.slider)
        foot = QHBoxLayout()
        self.link = QLabel("Sound Settings…")
        self.link.setCursor(Qt.PointingHandCursor)
        self.link.mousePressEvent = lambda _e: self._settings()
        foot.addWidget(self.link, 1)
        b_mute = RoundButton("volume_mute", 28, flat=True, tooltip="Mute")
        b_mute.clicked.connect(self._toggle_mute)
        foot.addWidget(b_mute)
        root.addLayout(foot)
        self.slider.valueChanged.connect(lambda _v: (self._apply_timer.start(), self._label()))
        self.slider.iconClicked.connect(self._toggle_mute)
        hub.volume_changed.connect(self._on_volume)
        self.setFixedWidth(self.WIDTH + 2 * m)
        self.on_theme()

    def on_theme(self):
        pal = self.pal
        self.title.setFont(font(13, QFont.DemiBold))
        self.title.setStyleSheet(f"color: {pal.fg.name()}; background: transparent;")
        self.value.setFont(font(12.5, QFont.Medium))
        c2 = pal.fg2
        self.value.setStyleSheet(f"color: rgba({c2.red()},{c2.green()},{c2.blue()},{c2.alpha()});"
                                 f" background: transparent;")
        self.link.setFont(font(12))
        self.link.setStyleSheet(f"color: {pal.accent.name()}; background: transparent;")
        self.update()

    def _label(self):
        v = self.hub.volume
        muted = bool(v and v[1])
        self.value.setText("Muted" if muted else f"{self.slider.value}%")

    def _on_volume(self, level, muted):
        if not self.slider._drag:
            self.slider.setValue(0 if muted else level)
        self.slider.set_glyph("volume_mute" if muted or level == 0 else "volume")
        self._label()

    def _apply(self):
        self.hub.backend.set_volume(self.slider.value)
        self.hub.volume = (self.slider.value, False)
        self.slider.set_glyph("volume" if self.slider.value else "volume_mute")
        self.hub.volume_changed.emit(self.slider.value, False)

    def _toggle_mute(self):
        v = self.hub.volume or (self.slider.value, False)
        self.hub.backend.set_mute(not v[1])
        self.hub.volume = (v[0], not v[1])
        self.hub.volume_changed.emit(v[0], not v[1])

    def _settings(self):
        self.hide()
        QTimer.singleShot(60, lambda: self.hub.do("sound"))

    def open_at(self, pos, rise=None):
        v = self.hub.volume or self.hub.backend.get_volume()
        self.slider.enabled_state = v is not None or self.hub.backend.name == "linux"
        if v:
            self.hub.volume = v
            self._on_volume(*v)
        self.adjustSize()
        self.hub.cc_open = True          # no volume HUD on the island while this is open
        self.popup_at(pos, rise)

    def hideEvent(self, ev):
        self.hub.cc_open = False
        super().hideEvent(ev)


class TrayPopup(GlassPopup):
    """The notification-area icons (Steam, WhatsApp, Spotify, ...) in a glass grid.
    Left click / double click / right click are forwarded to the real tray icon."""

    COLS, CELL, PAD = 5, 46, 12

    def __init__(self, hub):
        super().__init__(hub)
        self.icons_ = []
        self._hover = -1
        self.setMouseTracking(True)

    def load(self):
        self.icons_ = self.hub.backend.tray_icons() or []
        dpr = self.devicePixelRatioF() or 1.0
        target = int(round(24 * dpr))
        for ic in self.icons_:
            pm = ic.get("pixmap")
            if pm is not None and pm.width() > target:      # big icons: high-quality downscale
                pm = pm.scaled(target, target, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                pm.setDevicePixelRatio(dpr)
                ic["pixmap"] = pm
        m = self.margin
        n = max(1, len(self.icons_))
        cols = min(self.COLS, n)
        rows = (n + self.COLS - 1) // self.COLS
        w = max(cols * self.CELL + 2 * self.PAD, 200)
        h = rows * self.CELL + 2 * self.PAD + 30
        self.setFixedSize(int(w + 2 * m), int(h + 2 * m))
        self._hover = -1

    def _cell(self, i):
        c = self.panel_rect()
        cols = min(self.COLS, max(1, len(self.icons_)))
        x0 = c.left() + (c.width() - cols * self.CELL) / 2
        return QRectF(x0 + (i % self.COLS) * self.CELL, c.top() + self.PAD + (i // self.COLS) * self.CELL,
                      self.CELL, self.CELL)

    def _index_at(self, pos):
        for i in range(len(self.icons_)):
            if self._cell(i).contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, e):
        i = self._index_at(e.pos())
        if i != self._hover:
            self._hover = i
            self.setCursor(Qt.PointingHandCursor if i >= 0 else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self._hover = -1
        self.update()

    def _fire(self, e, button):
        i = self._index_at(e.pos())
        if i < 0:
            return
        icon = self.icons_[i]
        self.hide()
        # let our popup's mouse grab end first, then hand the click to the app
        QTimer.singleShot(40, lambda: self.hub.backend.tray_click(icon, button))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.RightButton:
            self._fire(e, "right")
        elif e.button() == Qt.LeftButton:
            self._fire(e, "left")

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._fire(e, "double")

    def paint_content(self, p):
        pal = self.pal
        c = self.panel_rect()
        if not self.icons_:
            p.setPen(pal.fg2)
            p.setFont(font(12.5))
            p.drawText(c, Qt.AlignCenter, "No tray icons")
            return
        for i, ic in enumerate(self.icons_):
            r = self._cell(i).adjusted(4, 4, -4, -4)
            if i == self._hover:
                p.setPen(Qt.NoPen)
                p.setBrush(pal.tile_hover)
                p.drawRoundedRect(r, 10, 10)
            pm = ic.get("pixmap")
            if pm is not None:
                # draw at the icon's real pixel size (crisp), capped to the cell
                dpr = pm.devicePixelRatio() or 1.0
                s = min(24.0, pm.width() / dpr)
                if s < 16:
                    s = 16.0
                p.drawPixmap(QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), pm,
                             QRectF(pm.rect()))
            else:
                icons.draw(p, "app", r.adjusted(10, 10, -10, -10), pal.fg2)
        tip = self.icons_[self._hover]["tip"] if self._hover >= 0 else "Click: open   ·   Right-click: menu"
        p.setPen(pal.fg if self._hover >= 0 else pal.fg3)
        p.setFont(font(11.5, QFont.Medium if self._hover >= 0 else QFont.Normal))
        tr = QRectF(c.left() + 10, c.bottom() - self.PAD - 22, c.width() - 20, 22)
        p.drawText(tr, Qt.AlignCenter, p.fontMetrics().elidedText(tip.split("\n")[0], Qt.ElideRight,
                                                                  int(tr.width())))


class CalendarPopup(GlassPopup):
    W, H = 316, 368

    def __init__(self, hub):
        super().__init__(hub)
        m = self.margin
        self.setFixedSize(self.W + 2 * m, self.H + 2 * m)
        self.locale = QLocale.system()
        self.month = QDate.currentDate()
        self._hover = None
        self.setMouseTracking(True)
        self._tick = QTimer(self, interval=1000, timeout=self.update)

    def open_at(self, pos, rise=None):
        today = QDate.currentDate()
        self.month = QDate(today.year(), today.month(), 1)
        self._tick.start()
        self.popup_at(pos, rise)

    def hideEvent(self, ev):
        self._tick.stop()
        super().hideEvent(ev)

    # -------------------------------------------------------------- geometry
    def _content(self):
        return self.panel_rect().adjusted(18, 16, -18, -16)

    def _nav_rects(self):
        c = self._content()
        y = c.top() + 84
        return QRectF(c.right() - 64, y, 28, 28), QRectF(c.right() - 30, y, 28, 28)

    def _grid_origin(self):
        c = self._content()
        return c.left(), c.top() + 150, c.width() / 7.0, 30.0

    # ----------------------------------------------------------------- input
    def mouseMoveEvent(self, e):
        prev_r, next_r = self._nav_rects()
        hov = "prev" if prev_r.contains(e.pos()) else "next" if next_r.contains(e.pos()) else None
        if hov != self._hover:
            self._hover = hov
            self.setCursor(Qt.PointingHandCursor if hov else Qt.ArrowCursor)
            self.update()

    def mousePressEvent(self, e):
        prev_r, next_r = self._nav_rects()
        if prev_r.contains(e.pos()):
            self.month = self.month.addMonths(-1)
        elif next_r.contains(e.pos()):
            self.month = self.month.addMonths(1)
        else:
            c = self._content()
            if QRectF(c.left(), c.top() + 84, c.width() - 70, 28).contains(e.pos()):
                t = QDate.currentDate()
                self.month = QDate(t.year(), t.month(), 1)
        self.update()

    def wheelEvent(self, e):
        self.month = self.month.addMonths(-1 if e.angleDelta().y() > 0 else 1)
        self.update()

    # --------------------------------------------------------------- drawing
    def paint_content(self, p):
        pal = self.pal
        c = self._content()
        loc = self.locale
        now = time.localtime()
        h24 = bool(self.hub.config.get("general", "clock_24h"))
        if h24:
            clock = time.strftime("%H:%M:%S", now)
        else:
            clock = time.strftime("%I:%M:%S %p", now).lstrip("0")
        p.setPen(pal.fg)
        p.setFont(font(30, QFont.DemiBold))
        p.drawText(QRectF(c.left(), c.top(), c.width(), 40), Qt.AlignLeft | Qt.AlignVCenter, clock)
        today = QDate.currentDate()
        p.setPen(pal.accent)
        p.setFont(font(12.5, QFont.Medium))
        p.drawText(QRectF(c.left(), c.top() + 42, c.width(), 20), Qt.AlignLeft | Qt.AlignVCenter,
                   loc.toString(today, "dddd, d MMMM yyyy"))
        # divider
        p.fillRect(QRectF(c.left(), c.top() + 72, c.width(), 1), pal.with_alpha(pal.fg, 26))
        # month header + arrows
        p.setPen(pal.fg)
        p.setFont(font(14, QFont.DemiBold))
        p.drawText(QRectF(c.left(), c.top() + 84, c.width() - 70, 28), Qt.AlignLeft | Qt.AlignVCenter,
                   loc.toString(self.month, "MMMM yyyy"))
        for key, r, glyph in (("prev", self._nav_rects()[0], "chevron_left"),
                              ("next", self._nav_rects()[1], "chevron_right")):
            if self._hover == key:
                p.setPen(Qt.NoPen)
                p.setBrush(pal.tile_hover)
                p.drawEllipse(r)
            icons.draw(p, glyph, r.adjusted(6, 6, -6, -6), pal.fg)
        # weekday names
        first = int(loc.firstDayOfWeek())        # 1 = Monday .. 7 = Sunday
        x0, y0, cw, ch = self._grid_origin()
        p.setFont(font(11, QFont.Medium))
        p.setPen(pal.fg2)
        for i in range(7):
            dow = (first - 1 + i) % 7 + 1
            p.drawText(QRectF(x0 + i * cw, y0 - 30, cw, 24), Qt.AlignCenter,
                       loc.dayName(dow, QLocale.ShortFormat)[:2])
        # days
        start = QDate(self.month.year(), self.month.month(), 1)
        offset = (start.dayOfWeek() - first) % 7
        day = start.addDays(-offset)
        p.setFont(font(12.5))
        for row in range(6):
            for col in range(7):
                r = QRectF(x0 + col * cw, y0 + row * ch, cw, ch)
                in_month = day.month() == self.month.month()
                if day == today:
                    d = min(cw, ch) - 2
                    p.setPen(Qt.NoPen)
                    p.setBrush(pal.accent)
                    p.drawEllipse(QRectF(r.center().x() - d / 2, r.center().y() - d / 2, d, d))
                    p.setPen(Qt.white)
                    p.setFont(font(12.5, QFont.DemiBold))
                else:
                    p.setPen(pal.fg if in_month else pal.fg3)
                    p.setFont(font(12.5))
                p.drawText(r, Qt.AlignCenter, str(day.day()))
                day = day.addDays(1)
