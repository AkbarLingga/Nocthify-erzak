"""Control Center panel (macOS / iOS style)."""
from __future__ import annotations

from PyQt5.QtCore import QPoint, QRectF, Qt, QTimer
from PyQt5.QtGui import QFont, QPainter
from PyQt5.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QMenu, QMessageBox,
                             QVBoxLayout, QWidget)

from .. import icons
from ..theme import elide, font, menu_stylesheet
from .common import BigSlider, GlassPopup, RoundButton, Tile


class MediaCard(QWidget):
    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setFixedHeight(64)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(64, 0, 10, 0)
        lay.addStretch(1)
        for glyph, cmd in (("prev", "prev"), ("play", "play"), ("next", "next")):
            b = RoundButton(glyph, 32, flat=True)
            b.clicked.connect(lambda c=cmd: hub.media_command(c))
            lay.addWidget(b)
            if cmd == "play":
                self.play_btn = b
        hub.media_changed.connect(self._on_media)

    def _on_media(self, media):
        self.play_btn.set_glyph("pause" if media and media.get("playing", True) else "play")
        self.update()

    def paintEvent(self, _e):
        pal = self.hub.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(Qt.NoPen)
        p.setBrush(pal.tile)
        p.drawRoundedRect(r, 16, 16)
        art = QRectF(r.left() + 10, r.top() + 10, 44, 44)
        p.setBrush(pal.with_alpha(pal.fg, 26))
        p.drawRoundedRect(art, 10, 10)
        media = self.hub.media
        pm = None
        if media:
            try:
                pm = self.hub.backend.app_icon(media.get("app_id", ""), 64)
            except Exception:
                pm = None
        if pm is not None:
            p.drawPixmap(art.adjusted(8, 8, -8, -8), pm, QRectF(pm.rect()))
        else:
            icons.draw(p, "music", art.adjusted(12, 12, -12, -12), pal.fg2)
        tx = art.right() + 10
        tw = r.width() - tx - 124
        p.setPen(pal.fg)
        p.setFont(font(12.5, QFont.DemiBold))
        p.drawText(QRectF(tx, r.top() + 13, tw, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   elide(p, media.get("title") if media else "Not Playing", tw))
        p.setPen(pal.fg2)
        p.setFont(font(11))
        sub = (media.get("artist") or media.get("source", "")) if media else "—"
        p.drawText(QRectF(tx, r.top() + 32, tw, 16), Qt.AlignLeft | Qt.AlignVCenter, elide(p, sub, tw))


class StatsLine(QWidget):
    def __init__(self, hub, parent=None):
        super().__init__(parent)
        self.hub = hub
        self.setFixedHeight(34)
        hub.stats_changed.connect(lambda *_: self.update())
        hub.battery_changed.connect(lambda *_: self.update())

    def paintEvent(self, _e):
        pal = self.hub.palette
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        x = 4.0
        parts = []
        b = self.hub.battery
        if b:
            parts.append(("bolt" if b[1] else "battery", f"{b[0]}%",
                          pal.green if b[1] else (pal.red if b[0] <= 20 else pal.fg)))
        if self.hub.config.get("control_center", "show_stats"):
            cpu, ram = self.hub.stats
            parts.append(("cpu", f"{int(cpu)}%", pal.fg))
            parts.append(("tasks", f"{int(ram)}%", pal.fg))
        p.setFont(font(12, QFont.DemiBold))
        for glyph, text, col in parts:
            icons.draw(p, glyph, QRectF(x, 9, 16, 16), col)
            x += 20
            w = p.fontMetrics().horizontalAdvance(text) + 2
            p.setPen(pal.fg)
            p.drawText(QRectF(x, 0, w, 34), Qt.AlignLeft | Qt.AlignVCenter, text)
            x += w + 14


class ControlCenter(GlassPopup):
    WIDTH = 372

    def __init__(self, hub):
        super().__init__(hub)
        self._bright_timer = QTimer(self, singleShot=True, interval=16, timeout=self._apply_brightness)
        self._vol_timer = QTimer(self, singleShot=True, interval=16, timeout=self._apply_volume)
        self._build()
        hub.volume_changed.connect(self._on_volume)
        hub.config.changed.connect(lambda _s: self._sync_toggles())

    def _build(self):
        m = self.margin
        root = QVBoxLayout(self)
        root.setContentsMargins(m + 14, m + 14, m + 14, m + 12)
        root.setSpacing(10)
        grid = QGridLayout()
        grid.setSpacing(10)
        self.t_wifi = Tile("wifi", "Wi-Fi", "…")
        self.t_bt = Tile("bluetooth", "Bluetooth", "Settings")
        self.t_dnd = Tile("moon", "Focus", "Do Not Disturb", toggle=True)
        self.t_dark = Tile("contrast", "Appearance", "Dark", toggle=True)
        for t in (self.t_wifi, self.t_bt, self.t_dnd, self.t_dark):
            t.setFixedHeight(54)
        grid.addWidget(self.t_wifi, 0, 0)
        grid.addWidget(self.t_dnd, 0, 1)
        grid.addWidget(self.t_bt, 1, 0)
        grid.addWidget(self.t_dark, 1, 1)
        root.addLayout(grid)

        row = QHBoxLayout()
        row.setSpacing(10)
        self.squares = []
        for glyph, label, action in (("nightlight", "Night Light", "nightlight"),
                                     ("cast", "Project", "project"),
                                     ("camera", "Screenshot", "screenshot"),
                                     ("lock", "Lock", "lock")):
            t = Tile(glyph, label, layout="square")
            t.setFixedHeight(76)
            t.clicked.connect(lambda a=action: self._run(a))
            row.addWidget(t)
            self.squares.append(t)
        root.addLayout(row)

        self.s_bright = BigSlider("sun", "Display")
        self.s_vol = BigSlider("volume", "Sound")
        root.addWidget(self.s_bright)
        root.addWidget(self.s_vol)
        self.media = MediaCard(self.hub)
        root.addWidget(self.media)

        foot = QHBoxLayout()
        foot.setSpacing(6)
        self.stats = StatsLine(self.hub)
        foot.addWidget(self.stats, 1)
        b_apps = RoundButton("grid", 32, tooltip="Apps")
        b_set = RoundButton("settings", 32, tooltip="Nocthify Settings")
        b_pow = RoundButton("power", 32, tooltip="Power")
        b_apps.clicked.connect(lambda: self._run("launcher"))
        b_set.clicked.connect(lambda: self._run("settings"))
        b_pow.clicked.connect(self._power_menu)
        for b in (b_apps, b_set, b_pow):
            foot.addWidget(b)
        root.addLayout(foot)

        self.t_wifi.clicked.connect(lambda: self._run("wifi"))
        self.t_bt.clicked.connect(lambda: self._run("bluetooth"))
        self.t_dnd.clicked.connect(lambda: self.hub.do("dnd"))
        self.t_dark.clicked.connect(self._toggle_dark)
        # throttle, not debounce: apply while dragging (every ~16 ms), and the last value always lands
        self.s_bright.valueChanged.connect(lambda _v: self._bright_timer.isActive() or self._bright_timer.start())
        self.s_vol.valueChanged.connect(lambda _v: self._vol_timer.isActive() or self._vol_timer.start())
        self.s_vol.iconClicked.connect(self._toggle_mute)
        self.setFixedWidth(self.WIDTH + 2 * m)

    # ------------------------------------------------------------- behaviour
    def _run(self, action):
        self.hide()
        QTimer.singleShot(80, lambda: self.hub.do(action))

    def _toggle_dark(self):
        dark = not self.t_dark.active
        self.t_dark.set_state(active=dark, subtitle="Dark" if dark else "Light")
        self.hub.set_dark_mode(dark)

    def _toggle_mute(self):
        v = self.hub.volume or (self.s_vol.value, False)
        self.hub.backend.set_mute(not v[1])
        self.hub.volume = (v[0], not v[1])
        self._on_volume(v[0], not v[1])

    def _apply_volume(self):
        self.hub.backend.set_volume(self.s_vol.value)
        self.hub.volume = (self.s_vol.value, False)
        self.s_vol.set_glyph("volume" if self.s_vol.value else "volume_mute")

    def _apply_brightness(self):
        self.hub.backend.set_brightness_async(self.s_bright.value)

    def _on_volume(self, level, muted):
        if not self.s_vol._drag:
            self.s_vol.setValue(0 if muted else level)
        self.s_vol.set_glyph("volume_mute" if muted or level == 0 else "volume")

    def _sync_toggles(self):
        dnd = bool(self.hub.config.get("general", "do_not_disturb"))
        self.t_dnd.set_state(active=dnd, subtitle="On" if dnd else "Off")

    def _power_menu(self):
        m = QMenu(self)
        m.setAttribute(Qt.WA_TranslucentBackground)
        m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        m.setStyleSheet(menu_stylesheet(self.pal))
        m.addAction(icons.icon("sleep", self.pal.fg.name()), "Sleep", lambda: self._run("sleep"))
        m.addAction(icons.icon("restart", self.pal.fg.name()), "Restart…", lambda: self._confirm("restart"))
        m.addAction(icons.icon("power", self.pal.fg.name()), "Shut Down…", lambda: self._confirm("shutdown"))
        m.addAction(icons.icon("logout", self.pal.fg.name()), "Log Out…", lambda: self._confirm("logout"))
        m.exec_(self.cursor().pos())

    def _confirm(self, action):
        self.hide()
        label = {"restart": "restart", "shutdown": "shut down", "logout": "log out"}[action]
        box = QMessageBox(QMessageBox.Question, "Nocthify",
                          f"Are you sure you want to {label} now?\nUnsaved work may be lost.",
                          QMessageBox.Yes | QMessageBox.Cancel)
        box.setWindowFlags(box.windowFlags() | Qt.WindowStaysOnTopHint)
        if box.exec_() == QMessageBox.Yes:
            self.hub.backend.restore_taskbar()
            self.hub.do(action)

    # ------------------------------------------------------------- showing
    def toggle(self):
        if self.isVisible():
            self.hide()
            return
        self.media.setVisible(bool(self.hub.config.get("control_center", "show_media")))
        self.media._on_media(self.hub.media)
        self.adjustSize()
        self._sync_toggles()
        dark = self.hub.backend.is_dark_mode()
        self.t_dark.set_state(active=dark, subtitle="Dark" if dark else "Light")
        v = self.hub.volume or self.hub.backend.get_volume()
        if v:
            self._on_volume(*v)
            self.s_vol.enabled_state = True
        else:
            self.s_vol.enabled_state = self.hub.backend.name == "linux"
        self.s_bright.enabled_state = True
        self.hub.run_async(self.hub.backend.get_brightness, self._got_brightness)
        self.t_wifi.set_state(subtitle="…")
        self.hub.run_async(self.hub.backend.wifi_name, self._got_wifi)
        self.hub.want_stats(True)
        self.hub.cc_open = True
        g = QApplication.primaryScreen().availableGeometry()
        full = QApplication.primaryScreen().geometry()
        top = full.top() + 44
        if self.hub.config.get("control_center", "position") == "center":
            x = full.center().x() - self.width() // 2
        else:
            x = g.right() - self.width() - 4
        self.popup_at(QPoint(x, top))

    def _got_brightness(self, val):
        if val is None:
            self.s_bright.enabled_state = False
            self.s_bright.update()
        else:
            self.s_bright.enabled_state = True
            self.s_bright.setValue(val)

    def _got_wifi(self, name):
        self.t_wifi.set_state(subtitle=name or "Not connected", active=bool(name))

    def hideEvent(self, ev):
        if self.hub.cc_open:
            self.hub.cc_open = False
            self.hub.want_stats(False)
        super().hideEvent(ev)
