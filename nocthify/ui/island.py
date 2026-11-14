"""Dynamic Island / Notch.

States
  compact   - small pill: clock on the left, battery / music bars / timer on the right
  activity  - temporary wider pill: volume HUD, charging, low battery, alerts
  expanded  - big card on hover: clock + date, battery/CPU/RAM rings,
              now-playing with media controls, and a row of shortcuts

The whole island is painted by hand on one translucent window, so it costs
almost nothing while idle (no timers run unless something is animating).
"""
from __future__ import annotations

import math
import random
import sys
import time

from PyQt5.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QRegion
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from .. import icons
from ..theme import (elide, font, menu_stylesheet, notch_path, paint_glass, paint_ring,
                     rounded_path)

IS_LINUX = not sys.platform.startswith("win")
M = 22  # transparent margin around the island for the shadow


class Island(QWidget):
    def __init__(self, hub):
        flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                 Qt.WindowDoesNotAcceptFocus | Qt.NoDropShadowWindowHint)
        if IS_LINUX:
            flags |= Qt.X11BypassWindowManagerHint
        super().__init__(None, flags)
        self.hub = hub
        self.cfg = hub.config
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setMouseTracking(True)

        self.mode = "compact"
        self.activity = None
        self.shape = QRectF()
        self.zones = []          # (rect, id, callback)
        self.hover_zone = None
        self.hover_label = ""
        self.inside = False
        self.bars = [0.4, 0.7, 0.5, 0.8]
        self.bar_targets = [0.5] * 4
        self._minute = None
        self._art = None
        self._art_key = None
        self._stats_on = False
        self.timer_left = None

        self.anim = QVariantAnimation(self)
        self.anim.valueChanged.connect(self._on_shape)
        self.t_hover = QTimer(self, singleShot=True, timeout=self.expand)
        self.t_leave = QTimer(self, singleShot=True, timeout=self.collapse)
        self.t_activity = QTimer(self, singleShot=True, timeout=self._end_activity)
        self.t_clock = QTimer(self, interval=1000, timeout=self._tick)
        self.t_bars = QTimer(self, interval=95, timeout=self._animate_bars)

        hub.battery_changed.connect(lambda _b: self.update())
        hub.media_changed.connect(self._on_media)
        hub.stats_changed.connect(lambda *_: self.update() if self.mode == "expanded" else None)
        hub.activity.connect(self.show_activity)
        hub.theme_changed.connect(self.update)
        hub.timer_tick.connect(self._on_timer)
        hub.fullscreen_changed.connect(self._on_fullscreen)
        self.reload()
        self.t_clock.start()

    # --------------------------------------------------------------- config
    @property
    def c(self):
        return self.cfg.get("island")

    @property
    def pal(self):
        return self.hub.palette

    def black(self):
        return self.c.get("material", "black") == "black"

    def fg(self):
        return QColor(255, 255, 255) if self.black() else self.pal.fg

    def fg2(self):
        return QColor(255, 255, 255, 160) if self.black() else self.pal.fg2

    def tile(self, hover=False):
        if self.black():
            return QColor(255, 255, 255, 34 if hover else 20)
        return self.pal.tile_hover if hover else self.pal.tile

    def reload(self):
        c = self.c
        self.cw = int(c.get("compact_width", 200))
        self.ch = int(c.get("compact_height", 34))
        self.ew = max(360, int(c.get("expanded_width", 460)))
        self.notch = c.get("style") == "notch"
        self.top = 0 if self.notch else int(c.get("top_offset", 6))
        self.eh = self._expanded_height()
        scr = QApplication.primaryScreen()
        # On Linux keep clear of top panels (GNOME top bar etc.)
        screen = scr.availableGeometry() if IS_LINUX else scr.geometry()
        w = self.ew + 2 * M
        h = self.top + self.eh + M
        self.setFixedSize(w, h)
        self.move(screen.x() + (screen.width() - w) // 2, screen.y())
        self.shape = self._target("compact")
        self.mode = "compact"
        self._apply_mask()
        if c.get("enabled", True) and not self.hub.fullscreen:
            self.show()
            self.hub.backend.prepare_own_window(self)
        else:
            self.hide()
        self._sync_bars()
        self.update()

    def _shortcuts(self):
        out = []
        for sid in self.c.get("shortcuts", []):
            meta = self.hub.shortcut_meta(sid)
            if meta:
                out.append((sid, meta[0], meta[1]))
        return out

    def _per_row(self):
        return max(1, int((self.ew - 36 + 8) // (46 + 8)))

    def _expanded_height(self):
        h = 18 + 52 + 14
        if self.c.get("show_media", True):
            h += 60 + 12
        n = len(self._shortcuts())
        if n:
            rows = math.ceil(n / self._per_row())
            h += rows * 46 + (rows - 1) * 8 + 22
        return h + 10

    def _compact_width(self):
        w = self.cw
        if (self.hub.media and self.c.get("show_media", True)) or self.timer_left:
            w += 46
        return w

    def _target(self, mode):
        cx = self.width() / 2
        if mode == "expanded":
            w, h = self.ew, self.eh
        elif mode == "activity":
            w, h = max(self.cw + 150, 340), self.ch + 12
        else:
            w, h = self._compact_width(), self.ch
        return QRectF(cx - w / 2, self.top, w, h)

    # ------------------------------------------------------------ animation
    def _go(self, mode):
        if mode == self.mode and not self.anim.state() == QVariantAnimation.Running:
            target = self._target(mode)
            if target == self.shape:
                return
        prev = self.mode
        self.mode = mode
        target = self._target(mode)
        if not self.cfg.get("general", "animations"):
            self._on_shape(target)
            return
        self.anim.stop()
        self.anim.setStartValue(QRectF(self.shape))
        self.anim.setEndValue(target)
        growing = target.height() * target.width() > self.shape.height() * self.shape.width()
        if growing:
            curve = QEasingCurve(QEasingCurve.OutBack)
            curve.setOvershoot(1.05 if mode == "expanded" else 1.4)
            self.anim.setEasingCurve(curve)
            self.anim.setDuration(430 if mode == "expanded" else 360)
        else:
            self.anim.setEasingCurve(QEasingCurve.OutCubic)
            self.anim.setDuration(300 if prev == "expanded" else 260)
        self.anim.start()
        self._sync_bars()
        want = mode == "expanded"
        if want != self._stats_on and self.c.get("show_stats", True):
            self._stats_on = want
            self.hub.want_stats(want)

    def _on_shape(self, rect):
        self.shape = QRectF(rect)
        self._apply_mask()
        self.update()

    def _apply_mask(self):
        if IS_LINUX:  # X11 doesn't let clicks through transparent pixels
            self.setMask(QRegion(self.shape.adjusted(-2, -2, 2, 2).toAlignedRect()))

    def expand(self):
        if self.mode != "expanded":
            self._go("expanded")

    def collapse(self):
        if self.activity and self.t_activity.isActive():
            self._go("activity")
        else:
            self.activity = None
            self._go("compact")

    def show_activity(self, info: dict):
        if not self.isVisible():
            return
        self.activity = info
        dur = 1700 if info.get("kind") == "volume" else 2600
        self.t_activity.start(dur)
        if self.mode != "expanded":
            self._go("activity")
        self.update()

    def _end_activity(self):
        self.activity = None
        if self.mode == "activity":
            self._go("compact")

    # --------------------------------------------------------------- events
    def _on_media(self, info):
        self._sync_bars()
        if self.mode == "compact":
            self._go("compact")
        self.update()

    def _on_timer(self, remaining):
        had = self.timer_left
        self.timer_left = remaining
        if (had is None) != (remaining is None) and self.mode == "compact":
            self._go("compact")
        self.update()

    def _on_fullscreen(self, fs):
        if not self.c.get("enabled", True):
            return
        if fs:
            self.hide()
        else:
            self.show()
            self.hub.backend.prepare_own_window(self)

    def _tick(self):
        minute = time.strftime("%H%M")
        if minute != self._minute:
            self._minute = minute
            self.update()

    def _sync_bars(self):
        need = (self.hub.media is not None and self.mode == "compact" and self.isVisible()
                and self.c.get("show_media", True) and self.cfg.get("general", "animations"))
        if need and not self.t_bars.isActive():
            self.t_bars.start()
        elif not need and self.t_bars.isActive():
            self.t_bars.stop()

    def _animate_bars(self):
        for i in range(4):
            if abs(self.bars[i] - self.bar_targets[i]) < 0.08:
                self.bar_targets[i] = random.uniform(0.25, 1.0)
            self.bars[i] += (self.bar_targets[i] - self.bars[i]) * 0.45
        r = self.shape
        self.update(QRectF(r.right() - 60, r.top(), 60, r.height()).toAlignedRect())

    def enterEvent(self, e):
        pass

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())
        inside = self.shape.adjusted(-4, -4, 4, 6).contains(pos)
        if inside and not self.inside:
            self.inside = True
            self.t_leave.stop()
            if self.c.get("expand_on_hover", True) and self.mode != "expanded":
                self.t_hover.start(int(self.c.get("hover_delay_ms", 160)))
        elif not inside and self.inside:
            self._left()
        zone = None
        for rect, zid, _cb, label in self.zones:
            if rect.contains(pos):
                zone = zid
                self.hover_label = label
                break
        if zone != self.hover_zone:
            self.hover_zone = zone
            self.setCursor(Qt.PointingHandCursor if zone else Qt.ArrowCursor)
            self.update()

    def _left(self):
        self.inside = False
        self.t_hover.stop()
        if self.mode == "expanded":
            self.t_leave.start(380)
        if self.hover_zone:
            self.hover_zone = None
            self.update()

    def leaveEvent(self, e):
        self._left()

    def mousePressEvent(self, e):
        pos = QPointF(e.pos())
        if e.button() == Qt.RightButton:
            self._menu(e.globalPos())
            return
        if e.button() != Qt.LeftButton:
            return
        if self.mode == "expanded":
            for rect, _zid, cb, _label in self.zones:
                if rect.contains(pos):
                    cb()
                    return
        elif self.shape.contains(pos):
            self.t_hover.stop()
            self.expand()

    def wheelEvent(self, e):
        v = self.hub.volume
        if v is None:
            v = self.hub.backend.get_volume()
        if v is None:
            return
        step = 4 if e.angleDelta().y() > 0 else -4
        level = max(0, min(100, v[0] + step))
        self.hub.backend.set_volume(level)
        self.hub.volume = (level, False)
        self.hub.volume_changed.emit(level, False)
        if self.mode != "expanded":
            self.show_activity({"kind": "volume", "value": level, "muted": False})

    def _menu(self, gpos):
        m = QMenu(self)
        m.setAttribute(Qt.WA_TranslucentBackground)
        m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        m.setStyleSheet(menu_stylesheet(self.pal))
        m.addAction("Control Center", lambda: self.hub.do("control_center"))
        m.addAction("Apps", lambda: self.hub.do("launcher"))
        m.addAction("Start / Cancel Timer", lambda: self.hub.do("timer"))
        m.addSeparator()
        style = m.addMenu("Style")
        style.setStyleSheet(menu_stylesheet(self.pal))
        style.addAction("Floating Island", lambda: self.cfg.set("island", "style", "island"))
        style.addAction("Notch", lambda: self.cfg.set("island", "style", "notch"))
        style.addAction("Black", lambda: self.cfg.set("island", "material", "black"))
        style.addAction("Glass", lambda: self.cfg.set("island", "material", "glass"))
        m.addAction("Settings…", lambda: self.hub.do("settings"))
        m.addAction("Hide Island", lambda: self.cfg.set("island", "enabled", False))
        m.addSeparator()
        m.addAction("Quit Nocthify", lambda: self.hub.do("quit"))
        m.exec_(gpos)

    # ------------------------------------------------------------- painting
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = self.shape
        radius = min(r.height() / 2, 32)
        path = notch_path(r, radius) if self.notch else rounded_path(r, radius)
        paint_glass(p, path, self.pal, solid_black=self.black(), shadow=True)
        p.save()
        p.setClipPath(path)
        span = max(1.0, self.eh - self.ch)
        grow = max(0.0, min(1.0, (r.height() - self.ch) / span))
        self.zones = []
        if self.mode == "expanded" or grow > 0.35:
            p.setOpacity(max(0.0, min(1.0, (grow - 0.35) / 0.5)))
            self._paint_expanded(p, r)
        elif self.mode == "activity" and self.activity:
            p.setOpacity(max(0.0, min(1.0, (r.width() - self.cw) / 120.0)))
            self._paint_activity(p, r)
        else:
            p.setOpacity(max(0.0, 1.0 - grow * 4))
            self._paint_compact(p, r)
        p.restore()

    def _time_text(self, fmt24="%H:%M", fmt12="%I:%M"):
        t = time.strftime(fmt24 if self.cfg.get("general", "clock_24h") else fmt12)
        return t.lstrip("0") if not self.cfg.get("general", "clock_24h") else t

    def _battery_glyph(self, p, rect: QRectF, pct, plugged, color):
        p.save()
        body = QRectF(rect.left(), rect.top(), rect.width() - 2.5, rect.height())
        p.setPen(QColor(color.red(), color.green(), color.blue(), 120))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(body, 3, 3)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 120))
        p.drawRoundedRect(QRectF(body.right() + 0.8, rect.center().y() - 2, 1.7, 4), 1, 1)
        if plugged:
            fill = self.pal.green
        elif pct <= 20:
            fill = self.pal.red
        else:
            fill = color
        inner = body.adjusted(1.8, 1.8, -1.8, -1.8)
        inner.setWidth(max(1.5, inner.width() * pct / 100.0))
        p.setBrush(fill)
        p.drawRoundedRect(inner, 1.6, 1.6)
        p.restore()

    def _paint_compact(self, p, r):
        fg = self.fg()
        pad = 15 if not self.notch else 18
        cy = r.center().y()
        if self.c.get("show_clock", True):
            p.setPen(fg)
            p.setFont(font(13.5, QFont.DemiBold))
            p.drawText(QRectF(r.left() + pad, r.top(), 80, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       self._time_text())
        right = r.right() - pad
        if self.timer_left:
            m, s = divmod(self.timer_left, 60)
            p.setPen(self.pal.orange)
            p.setFont(font(13, QFont.DemiBold))
            p.drawText(QRectF(right - 60, r.top(), 60, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                       f"{m}:{s:02d}")
            icons.draw(p, "timer", QRectF(right - 82, cy - 8, 16, 16), self.pal.orange)
            return
        if self.hub.media and self.c.get("show_media", True):
            col = self.pal.accent if not self.black() else QColor("#7CF29A")
            bw, gap, h = 3.0, 2.6, r.height() * 0.5
            x = right - (4 * bw + 3 * gap)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            for i, v in enumerate(self.bars):
                bh = max(3.0, h * v)
                p.drawRoundedRect(QRectF(x + i * (bw + gap), cy - bh / 2, bw, bh), 1.5, 1.5)
            art = self._media_art(18)
            if art is not None:
                p.drawPixmap(QRectF(x - 28, cy - 9, 18, 18), art, QRectF(art.rect()))
            return
        b = self.hub.battery
        if b and self.c.get("show_battery", True):
            pct, plugged = b
            self._battery_glyph(p, QRectF(right - 25, cy - 6, 25, 12), pct, plugged, fg)
            p.setPen(fg)
            p.setFont(font(12.5, QFont.DemiBold))
            p.drawText(QRectF(right - 75, r.top(), 44, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                       f"{pct}%")
            if plugged:
                icons.draw(p, "bolt", QRectF(right - 21, cy - 5, 10, 10), QColor(0, 0, 0, 200)
                           if pct > 45 else fg)

    def _paint_activity(self, p, r):
        a = self.activity
        kind = a.get("kind")
        fg = self.fg()
        pad = 16
        cy = r.center().y()
        if kind in ("volume", "brightness"):
            muted = a.get("muted")
            val = 0 if muted else int(a.get("value", 0))
            glyph = "sun" if kind == "brightness" else ("volume_mute" if muted or val == 0 else "volume")
            icons.draw(p, glyph, QRectF(r.left() + pad, cy - 9, 18, 18), fg)
            track = QRectF(r.left() + pad + 30, cy - 3, r.width() - 2 * pad - 80, 6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(fg.red(), fg.green(), fg.blue(), 50))
            p.drawRoundedRect(track, 3, 3)
            p.setBrush(fg)
            p.drawRoundedRect(QRectF(track.left(), track.top(), max(6.0, track.width() * val / 100), 6), 3, 3)
            p.setPen(fg)
            p.setFont(font(12.5, QFont.DemiBold))
            p.drawText(QRectF(track.right() + 8, r.top(), 42, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                       f"{val}%")
            return
        color = a.get("color")
        if kind == "charging":
            color, glyph, text = self.pal.green, "bolt", "Charging"
            right_text = f"{a.get('value', 0)}%"
        elif kind == "lowbattery":
            color, glyph, text = self.pal.red, "battery", "Low Battery"
            right_text = f"{a.get('value', 0)}%"
        else:
            glyph = a.get("glyph", "bell_off")
            text = a.get("text", "")
            right_text = ""
            color = QColor(color) if color else (self.pal.orange if kind == "timer_done" else fg)
        circ = QRectF(r.left() + 10, cy - 13, 26, 26)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color.red(), color.green(), color.blue(), 55))
        p.drawEllipse(circ)
        icons.draw(p, glyph, circ.adjusted(6, 6, -6, -6), color)
        p.setPen(fg)
        p.setFont(font(13, QFont.DemiBold))
        tw = r.width() - 60 - (60 if right_text else 10)
        p.drawText(QRectF(circ.right() + 10, r.top(), tw, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   elide(p, text, tw))
        if right_text:
            p.setPen(color)
            p.drawText(QRectF(r.right() - 70, r.top(), 56, r.height()), Qt.AlignRight | Qt.AlignVCenter,
                       right_text)

    def _media_art(self, size):
        media = self.hub.media
        if not media:
            return None
        key = (media.get("app_id"), size)
        if key != self._art_key:
            self._art_key = key
            try:
                self._art = self.hub.backend.app_icon(media.get("app_id", ""), 64)
            except Exception:
                self._art = None
        return self._art

    def _zone(self, rect, zid, cb, label=""):
        self.zones.append((rect, zid, cb, label))
        return zid == self.hover_zone

    def _paint_expanded(self, p, r):
        fg, fg2 = self.fg(), self.fg2()
        pad = 18
        x0, x1 = r.left() + pad, r.right() - pad
        y = r.top() + pad - (2 if not self.notch else -2)

        # --- header: clock, date & rings
        p.setPen(fg)
        p.setFont(font(30, QFont.DemiBold))
        p.drawText(QRectF(x0, y - 4, 200, 38), Qt.AlignLeft | Qt.AlignVCenter, self._time_text())
        p.setPen(fg2)
        p.setFont(font(12, QFont.Medium))
        p.drawText(QRectF(x0 + 1, y + 34, 240, 16), Qt.AlignLeft | Qt.AlignVCenter,
                   time.strftime("%A, %d %B %Y"))
        rings = []
        b = self.hub.battery
        if b:
            col = self.pal.green if b[1] else (self.pal.red if b[0] <= 20 else QColor("#30D158"))
            rings.append(("bolt" if b[1] else "battery", b[0], col, "Charging" if b[1] else "Battery"))
        if self.c.get("show_stats", True):
            cpu, ram = self.hub.stats
            rings.append(("cpu", cpu, self.pal.accent, "CPU"))
            rings.append(("tasks", ram, QColor("#BF5AF2"), "RAM"))
        rx = x1 - 20
        for glyph, value, col, cap in reversed(rings):
            c = QPointF(rx, y + 20)
            paint_ring(p, c, 17, value / 100.0, col, self.pal if not self.black() else _DarkPal, 3.6)
            p.setPen(fg)
            p.setFont(font(10.5, QFont.DemiBold))
            p.drawText(QRectF(c.x() - 17, c.y() - 17, 34, 34), Qt.AlignCenter, f"{int(round(value))}")
            p.setPen(fg2)
            p.setFont(font(9, QFont.Medium))
            p.drawText(QRectF(c.x() - 24, c.y() + 19, 48, 13), Qt.AlignCenter, cap)
            rx -= 50
        y += 52 + 14

        # --- now playing
        if self.c.get("show_media", True):
            card = QRectF(x0, y, x1 - x0, 60)
            p.setPen(Qt.NoPen)
            p.setBrush(self.tile())
            p.drawRoundedRect(card, 16, 16)
            art = QRectF(card.left() + 9, card.top() + 9, 42, 42)
            media = self.hub.media
            g = QLinearGradient(art.topLeft(), art.bottomRight())
            g.setColorAt(0, self.pal.accent)
            g.setColorAt(1, QColor("#BF5AF2"))
            p.setBrush(g)
            p.drawRoundedRect(art, 11, 11)
            pm = self._media_art(42)
            if pm is not None:
                p.drawPixmap(art.adjusted(7, 7, -7, -7), pm, QRectF(pm.rect()))
            else:
                icons.draw(p, "music", art.adjusted(11, 11, -11, -11), QColor("white"))
            tx = art.right() + 12
            tw = card.right() - tx - 118
            p.setPen(fg)
            p.setFont(font(13, QFont.DemiBold))
            title = media.get("title") if media else "Not Playing"
            sub = (media.get("artist") or media.get("source", "")) if media else "Media keys still work here"
            p.drawText(QRectF(tx, card.top() + 11, tw, 19), Qt.AlignLeft | Qt.AlignVCenter, elide(p, title, tw))
            p.setPen(fg2)
            p.setFont(font(11.5))
            p.drawText(QRectF(tx, card.top() + 30, tw, 17), Qt.AlignLeft | Qt.AlignVCenter, elide(p, sub, tw))
            bx = card.right() - 112
            for glyph, cmd in (("prev", "prev"), ("play" if not media else "pause", "play"), ("next", "next")):
                br = QRectF(bx, card.center().y() - 17, 34, 34)
                hov = self._zone(br, "m_" + cmd, lambda c=cmd: self.hub.backend.media(c),
                                 {"prev": "Previous", "play": "Play / Pause", "next": "Next"}[cmd])
                if hov:
                    p.setPen(Qt.NoPen)
                    p.setBrush(self.tile(True))
                    p.drawEllipse(br)
                s = 15 if cmd == "play" else 13
                icons.draw(p, glyph, QRectF(br.center().x() - s / 2, br.center().y() - s / 2, s, s), fg)
                bx += 38
            y += 60 + 12

        # --- shortcuts
        items = self._shortcuts()
        if items:
            per = self._per_row()
            size, gap = 46, 8
            for row_start in range(0, len(items), per):
                row = items[row_start:row_start + per]
                total = len(row) * size + (len(row) - 1) * gap
                bx = r.center().x() - total / 2
                for sid, label, glyph in row:
                    br = QRectF(bx, y, size, size)
                    hov = self._zone(br, sid, lambda s=sid: self._run_shortcut(s), label)
                    active = (sid == "timer" and self.timer_left) or \
                             (sid == "dnd" and self.cfg.get("general", "do_not_disturb"))
                    p.setPen(Qt.NoPen)
                    p.setBrush(self.pal.accent if active else self.tile(hov))
                    p.drawRoundedRect(br, 14, 14)
                    icons.draw(p, glyph, br.adjusted(13, 13, -13, -13),
                               QColor("white") if active else fg)
                    bx += size + gap
                y += size + 8
            label = self.hover_label if self.hover_zone else ""
            if self.timer_left and not label:
                m, s = divmod(self.timer_left, 60)
                label = f"Timer  {m}:{s:02d}"
            p.setPen(fg2)
            p.setFont(font(11, QFont.Medium))
            p.drawText(QRectF(x0, y - 4, x1 - x0, 18), Qt.AlignCenter, label)

    def _run_shortcut(self, sid):
        if sid not in ("timer", "dnd", "dark_mode"):
            self.t_leave.stop()
            self.collapse()
        self.hub.do(sid)
        self.update()


class _DarkPalProxy:
    """Ring track colour for the black island regardless of system theme."""
    fg = QColor(255, 255, 255)


_DarkPal = _DarkPalProxy()
