"""macOS-style dock that replaces the taskbar.

* pinned apps + running apps (grouped per program) with a dot indicator
* smooth magnification, launch bounce, hover labels
* click: open / focus / minimise / cycle windows;  middle-click: new window
* drag a pinned icon to reorder it, drag it away from the dock to unpin
* right-click menus, auto-hide, bottom / left / right placement
Everything is drawn on one translucent window; an animation timer only runs
while something is actually moving.
"""
from __future__ import annotations

import math
import os
import sys
import time

from PyQt5.QtCore import QDate, QLocale, QPoint, QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QFontMetricsF, QLinearGradient, QPainter, QRegion
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from .. import icons
from ..theme import elide, font, menu_stylesheet, paint_battery, paint_glass, rounded_path

IS_LINUX = not sys.platform.startswith("win")


class Item:
    __slots__ = ("kind", "key", "path", "name", "windows", "pinned", "bounce_t0")

    def __init__(self, kind, key="", path="", name="", pinned=False):
        self.kind = kind
        self.key = key
        self.path = path
        self.name = name
        self.windows = []
        self.pinned = pinned
        self.bounce_t0 = 0.0


class Dock(QWidget):
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

        self.items = []
        self.running_order = []
        self.mouse = None            # QPointF while the cursor is over the dock
        self.mag_at = None           # last cursor point: magnification relaxes around it after leaving
        self.tray_hover = None       # hovered part of the status area
        self._genie = None
        self._snaps = {}             # wid -> (QImage, QRectF) snapshot used for the restore genie
        self._vol_popup = None
        self._cal_popup = None
        self._tray_popup = None
        self._scaled = {}            # (icon key, px) -> icon pre-scaled with a high-quality filter
        self._has_battery = None
        self._clock = QTimer(self, singleShot=True, timeout=self._clock_tick)
        self.hover = 0.0             # 0..1 magnification blend
        self.hover_target = 0.0
        self.hidden_amt = 0.0        # 0 = visible, 1 = tucked away (autohide)
        self.hidden_target = 0.0
        self.press = None            # (item, QPointF)
        self.drag = None
        self.menu_open = False
        self._icons = {}
        self._frame = QTimer(self, interval=16, timeout=self._step)
        self._autohide_timer = QTimer(self, singleShot=True, timeout=self._maybe_hide)

        hub.windows_changed.connect(self._on_windows)
        hub.theme_changed.connect(self.update)
        hub.fullscreen_changed.connect(self._on_fullscreen)
        hub.volume_changed.connect(self._tray_changed)
        hub.network_changed.connect(self._tray_changed)
        hub.battery_changed.connect(self._on_battery)
        self.reload()
        self._clock_tick()

    # ------------------------------------------------------------- config
    @property
    def c(self):
        return self.cfg.get("dock")

    @property
    def pal(self):
        return self.hub.palette

    def reload(self):
        c = self.c
        if not c.get("pinned_initialized"):
            self.cfg.data["dock"]["pinned"] = self.hub.backend.default_pinned()
            self.cfg.set("dock", "pinned_initialized", True, emit=False)
        self.pos_kind = c.get("position", "bottom") if c.get("position") in ("bottom", "left", "right") else "bottom"
        self.base = max(24, min(128, int(c.get("icon_size", 48))))
        self.mag = max(self.base, int(c.get("magnify_size", 74))) if c.get("magnification", True) else self.base
        self.em = int(c.get("edge_margin", 8))
        self.autohide = bool(c.get("autohide", False))
        self.hidden_amt = self.hidden_target = 1.0 if self.autohide else 0.0
        self._icons.clear()
        self._scaled.clear()
        self._rebuild()
        if c.get("enabled", True) and not self.hub.fullscreen:
            self.show()
            self.hub.backend.prepare_own_window(self)
        else:
            self.hide()
        self._reserve()

    def _reserve(self):
        be = self.hub.backend
        if self.c.get("enabled", True) and self.c.get("reserve_space", True) and not self.autohide:
            dpr = self.devicePixelRatioF() or 1.0
            be.reserve_edge(self.pos_kind, int(math.ceil((self.em + self.thick() + 4) * dpr)))
        else:
            be.release_edge()

    # ------------------------------------------------------------- items
    def _rebuild(self):
        c = self.c
        old = {(i.kind, i.key): i for i in self.items}
        items = []
        if c.get("show_launcher", True):
            items.append(old.get(("launcher", "")) or Item("launcher", name="Apps"))
        groups = {}
        for w in self.hub.windows:
            groups.setdefault(w.app_id, []).append(w)
        pinned_keys = set()
        for pin in c.get("pinned", []):
            key = os.path.normcase(pin.get("match") or pin.get("path", "")) \
                if not str(pin.get("match", "")).startswith("wm:") else pin["match"]
            pinned_keys.add(key)
            it = old.get(("app", key)) or Item("app", key, pin.get("path", ""), pin.get("name", ""), True)
            it.pinned, it.path, it.name = True, pin.get("path", ""), pin.get("name") or it.name
            it.windows = groups.get(key, [])
            items.append(it)
        if c.get("show_running", True):
            for key in list(groups):
                if key not in self.running_order:
                    self.running_order.append(key)
            self.running_order = [k for k in self.running_order if k in groups]
            running = [k for k in self.running_order if k not in pinned_keys]
            if running:
                items.append(old.get(("sep", "")) or Item("sep"))
            for key in running:
                ws = groups[key]
                it = old.get(("app", key)) or Item("app", key, ws[0].exe, self.hub.backend.app_name(key))
                it.pinned = False
                it.windows = ws
                if not it.path:
                    it.path = ws[0].exe
                items.append(it)
        if c.get("show_trash", True):
            if not any(i.kind == "sep" for i in items):
                items.append(old.get(("sep", "")) or Item("sep"))
            items.append(old.get(("trash", "")) or Item("trash", name="Trash"))
        if c.get("show_tray", True):
            items.append(old.get(("sep", "tray")) or Item("sep", "tray"))
            items.append(old.get(("tray", "")) or Item("tray", name="Status"))
        self.items = items
        for k in [k for k, v in self._icons.items() if v is None]:
            del self._icons[k]
        self._resize()
        self.update()

    def _on_windows(self, wins):
        # a snapshot is only valid while its window stays minimised the way we left it
        minimized = {w.id for w in wins if w.minimized}
        for wid in [w for w in self._snaps if w not in minimized]:
            del self._snaps[wid]
        if self.drag is None:
            self._rebuild()

    # ------------------------------------------------------- status area
    def _tray_changed(self, *_a):
        if self.c.get("show_tray", True):
            self.update()

    def _on_battery(self, b):
        has = b is not None
        if has != self._has_battery:
            self._has_battery = has
            self._rebuild()
        else:
            self._tray_changed()

    def _clock_tick(self):
        self._tray_changed()
        now = time.localtime()
        self._clock.start(int((60 - now.tm_sec) * 1000 + 50))

    def _clock_texts(self):
        if self.cfg.get("general", "clock_24h"):
            t = time.strftime("%H:%M")
        else:
            t = time.strftime("%I:%M %p").lstrip("0")
        d = QLocale.system().toString(QDate.currentDate(), QLocale.ShortFormat)
        return t, d

    def _tray_fonts(self):
        b = self.base
        return font(max(11.0, b * 0.27), QFont.DemiBold), font(max(9.5, b * 0.215))

    def _tray_parts(self):
        """[(key, length along the dock)] for the status area."""
        b = self.base
        horiz = self.pos_kind == "bottom"
        parts = []
        if self.hub.backend.name == "windows" and self.cfg.get("taskbar", "mode") == "hide":
            parts.append(("chev", b * 0.5))
        parts.append(("net", b * 0.66))
        parts.append(("vol", b * 0.66))
        if self.hub.battery is not None:
            parts.append(("bat", b * 1.3 if horiz else b * 0.86))
        if horiz:
            f1, f2 = self._tray_fonts()
            sample_t = "23:59" if self.cfg.get("general", "clock_24h") else "12:59 PM"
            sample_d = QLocale.system().toString(QDate(2026, 12, 28), QLocale.ShortFormat)
            w = max(QFontMetricsF(f1).horizontalAdvance(sample_t), QFontMetricsF(f2).horizontalAdvance(sample_d))
            parts.append(("clock", w + b * 0.4))
        else:
            parts.append(("clock", b * 1.0))
        return parts

    def _tray_len(self):
        return sum(length for _k, length in self._tray_parts())

    def _tray_part_at(self, pt):
        lay, _a, _b = self.layout()
        m = self._main(pt)
        for it, x, _s in lay:
            if it.kind == "tray":
                pos = x
                for key, length in self._tray_parts():
                    if pos <= m < pos + length:
                        return key, pos, length
                    pos += length
        return None

    def _tray_tip(self, key):
        h = self.hub
        if key == "chev":
            return "Show hidden icons"
        if key == "net":
            kind, name = h.network or ("none", "")
            return f"Wi-Fi  ·  {name}" if kind == "wifi" else "Ethernet" if kind == "ethernet" else "Not connected"
        if key == "vol":
            v = h.volume
            return "Volume" if not v else ("Muted" if v[1] else f"Volume  ·  {v[0]}%")
        if key == "bat" and h.battery:
            pct, plugged = h.battery
            return f"Battery  ·  {pct}%" + ("  ·  charging" if plugged else "")
        if key == "clock":
            return QLocale.system().toString(QDate.currentDate(), "dddd, d MMMM yyyy")
        return ""

    def _tray_click(self, pt):
        hit = self._tray_part_at(pt)
        if hit is None:
            return
        key, pos, length = hit
        center = self.mapToGlobal(QPoint(0, 0))
        center = (center.x() if self.pos_kind == "bottom" else center.y()) + pos + length / 2
        if key == "chev":
            if self._tray_popup is None:
                from .tray_popups import TrayPopup
                self._tray_popup = TrayPopup(self.hub)
            if self._tray_popup.isVisible():
                self._tray_popup.hide()
                return
            if self.hub.backend.tray_icons() is None:     # e.g. Windows 11 22H2+: no readable tray
                self.hub.backend.peek_taskbar()
                return
            self._tray_popup.load()
            pos_, rise = self.popup_pos(self._tray_popup.width(), self._tray_popup.height(), center)
            self._tray_popup.popup_at(pos_, rise)
        elif key in ("net", "bat"):
            self.hub.do("control_center")
        elif key == "vol":
            if self._vol_popup is None:
                from .tray_popups import VolumePopup
                self._vol_popup = VolumePopup(self.hub)
            if self._vol_popup.isVisible():
                self._vol_popup.hide()
                return
            self._vol_popup.adjustSize()
            pos_, rise = self.popup_pos(self._vol_popup.width(), self._vol_popup.sizeHint().height(), center)
            self._vol_popup.open_at(pos_, rise)
        elif key == "clock":
            if self._cal_popup is None:
                from .tray_popups import CalendarPopup
                self._cal_popup = CalendarPopup(self.hub)
            if self._cal_popup.isVisible():
                self._cal_popup.hide()
                return
            pos_, rise = self.popup_pos(self._cal_popup.width(), self._cal_popup.height(), center)
            self._cal_popup.open_at(pos_, rise)

    def popup_pos(self, w, h, center=None, margin=16):
        """Top-left (global) for a w x h popup next to the dock, plus the offset it rises from."""
        lay, a, b = self.layout()
        pill = self._rect(a, b - a, self.em, self.thick())
        g0 = self.mapToGlobal(QPoint(0, 0))
        screen = (QApplication.screenAt(g0 + QPoint(self.width() // 2, self.height() // 2))
                  or QApplication.primaryScreen()).geometry()
        gap = 10
        if self.pos_kind == "bottom":
            cx = center if center is not None else g0.x() + pill.center().x()
            x, y = cx - w / 2, g0.y() + pill.top() - gap - (h - margin)
            rise = QPoint(0, 40)
        elif self.pos_kind == "left":
            cy = center if center is not None else g0.y() + pill.center().y()
            x, y = g0.x() + pill.right() + gap - margin, cy - h / 2
            rise = QPoint(-40, 0)
        else:
            cy = center if center is not None else g0.y() + pill.center().y()
            x, y = g0.x() + pill.left() - gap - (w - margin), cy - h / 2
            rise = QPoint(40, 0)
        x = max(screen.left() + 4 - margin, min(screen.right() - w + margin - 4, x))
        y = max(screen.top() + 4 - margin, min(screen.bottom() - h + margin - 4, y))
        return QPoint(int(x), int(y)), rise

    # ------------------------------------------------------------ genie
    def _genie_on(self):
        return (self.hub.backend.supports_genie and self.c.get("genie", True)
                and self.cfg.get("general", "animations"))

    def _item_global_rect(self, it):
        lay, _a, _b = self.layout()
        for i, x, s in lay:
            if i is it:
                r = self._rect(x, s, self.em + self.pad(), s)
                return r.translated(QPointF(self.mapToGlobal(QPoint(0, 0))))
        return None

    def _genie_widget(self):
        if self._genie is None:
            from .genie import Genie
            self._genie = Genie()
        return self._genie

    def _minimize(self, it, wid):
        be = self.hub.backend
        dst = self._item_global_rect(it)
        cap = be.capture_window(wid) if self._genie_on() and dst is not None else None
        if cap is None:
            be.minimize(wid)
            return
        img, (l, t, r, b) = cap
        dpr = self.devicePixelRatioF() or 1.0
        src = QRectF(l / dpr, t / dpr, (r - l) / dpr, (b - t) / dpr)
        self._genie_widget().play(img, src, dst, self.pos_kind)
        be.minimize(wid, animate=False)
        # Keep the snapshot at full resolution for a crisp restore, but losslessly
        # compressed (PNG, ~1 MB instead of ~8 MB raw), encoded off the GUI thread.
        self._snaps[wid] = (img, src)
        while len(self._snaps) > 4:
            del self._snaps[next(iter(self._snaps))]

        def encode(image=img):
            from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
            data = QByteArray()
            buf = QBuffer(data)
            buf.open(QIODevice.WriteOnly)
            image.save(buf, "PNG", 85)
            buf.close()
            return bytes(data)

        def stored(data, w=wid, s=src, image=img):
            cur = self._snaps.get(w)
            if data and cur is not None and cur[0] is image:
                self._snaps[w] = (data, s)
        self.hub.run_async(encode, stored)

    def _restore(self, it, wid):
        be = self.hub.backend
        snap = self._snaps.pop(wid, None)
        dst = self._item_global_rect(it)
        if snap is None or dst is None or not self._genie_on():
            be.activate(wid)
            return
        img, src = snap
        if isinstance(img, bytes):
            from PyQt5.QtGui import QImage
            img = QImage.fromData(img, "PNG")
            if img.isNull():
                be.activate(wid)
                return
        self._genie_widget().play(img, src, dst, self.pos_kind, reverse=True,
                                  on_done=lambda: be.activate(wid, animate=False))

    def _on_fullscreen(self, fs):
        if not self.c.get("enabled", True):
            return
        if fs:
            self.hide()
        else:
            self.show()
            self.hub.backend.prepare_own_window(self)

    # ------------------------------------------------------------ geometry
    def pad(self):
        return max(6.0, self.base * 0.17)

    def gap(self):
        return max(4.0, self.base * 0.14)

    def thick(self):
        return self.base + 2 * self.pad()

    def _width_of(self, it, size):
        if it.kind == "sep":
            return max(2.0, self.gap() * 0.6)
        if it.kind == "tray":
            return self._tray_len()
        return size

    def _screen(self):
        screen = QApplication.primaryScreen()
        if IS_LINUX:
            return screen.availableGeometry()  # sit next to GNOME/KDE/XFCE panels, not over them
        g = screen.geometry()
        tray = self.hub.backend.taskbar_rect()
        if tray is None:
            return g
        dpr = screen.devicePixelRatio() or 1.0
        l, t, r, b = (v / dpr for v in tray)
        if t > g.height() / 2:            # taskbar at the bottom
            g.setBottom(int(t) - 1)
        elif r < g.width() / 2:           # left
            g.setLeft(int(r))
        elif l > g.width() / 2:           # right
            g.setRight(int(l) - 1)
        return g

    def _resize(self):
        g = self._screen()
        main_screen = g.width() if self.pos_kind == "bottom" else g.height()
        n = len(self.items) or 1
        base_total = sum(self._width_of(i, self.base) for i in self.items) + self.gap() * (n - 1) + 2 * self.pad()
        if base_total > main_screen * 0.94:  # too many apps: shrink icons to fit
            scale = main_screen * 0.94 / base_total
            self.base = max(20, int(self.base * scale))
            self.mag = max(self.base, int(self.mag * scale))
            base_total = main_screen * 0.94
        extra = (self.mag - self.base) * 3.2
        length = int(min(main_screen, base_total + extra + 220))
        cross = int(self.em + self.pad() + self.mag + 52)
        if self.pos_kind == "bottom":
            self.setFixedSize(length, cross)
            self.move(g.x() + (g.width() - length) // 2, g.y() + g.height() - cross)
        elif self.pos_kind == "left":
            self.setFixedSize(cross, length)
            self.move(g.x(), g.y() + (g.height() - length) // 2)
        else:
            self.setFixedSize(cross, length)
            self.move(g.x() + g.width() - cross, g.y() + (g.height() - length) // 2)

    def _main_len(self):
        return self.width() if self.pos_kind == "bottom" else self.height()

    def _main(self, pt):
        return pt.x() if self.pos_kind == "bottom" else pt.y()

    def _cross(self, pt):
        if self.pos_kind == "bottom":
            return self.height() - pt.y()
        if self.pos_kind == "left":
            return pt.x()
        return self.width() - pt.x()

    def _rect(self, m0, length, c0, thick):
        if self.pos_kind == "bottom":
            return QRectF(m0, self.height() - c0 - thick, length, thick)
        if self.pos_kind == "left":
            return QRectF(c0, m0, thick, length)
        return QRectF(self.width() - c0 - thick, m0, thick, length)

    def _hide_offset(self):
        return -(self.em + self.thick() + 8) * self.hidden_amt

    def layout(self):
        """Return ([(item, main_start, size)], pill_main_start, pill_main_end)."""
        n = len(self.items)
        if not n:
            return [], 0, 0
        gap, pad = self.gap(), self.pad()
        L = self._main_len()
        widths = [self._width_of(i, self.base) for i in self.items]
        base_total = sum(widths) + gap * (n - 1)
        start = (L - base_total) / 2
        centers, x = [], start
        for w in widths:
            centers.append(x + w / 2)
            x += w + gap
        sizes = list(widths)
        focus = self.mouse if self.mouse is not None else self.mag_at
        if focus is not None and self.mag > self.base and self.hover > 0.001:
            # after the cursor leaves, the icons shrink back smoothly around where it left
            mm = self._main(focus)
            rng = self.base * 2.6
            for i, it in enumerate(self.items):
                if it.kind in ("sep", "tray"):
                    continue
                d = abs(mm - centers[i])
                f = math.cos(min(1.0, d / rng) * math.pi / 2) ** 2 if d < rng else 0.0
                sizes[i] = self.base + (self.mag - self.base) * f * self.hover
        total = sum(sizes) + gap * (n - 1)
        # keep the item under the cursor roughly under the cursor while growing
        start = (L - total) / 2
        out, x = [], start
        for it, s in zip(self.items, sizes):
            out.append((it, x, s))
            x += s + gap
        return out, start - pad, start + total + pad

    def item_at(self, pt):
        lay, _a, _b = self.layout()
        m = self._main(pt)
        c = self._cross(pt) - self._hide_offset()
        for it, x, s in lay:
            cross = self.base if it.kind == "tray" else s
            if x - self.gap() / 2 <= m <= x + s + self.gap() / 2 and c <= self.em + self.pad() + cross + 4:
                return it
        return None

    # ------------------------------------------------------------ animation
    def _kick(self):
        if not self._frame.isActive():
            self._frame.start()

    def _step(self):
        busy = False
        animate = self.cfg.get("general", "animations")
        for attr, target in (("hover", self.hover_target), ("hidden_amt", self.hidden_target)):
            cur = getattr(self, attr)
            if abs(cur - target) > 0.002:
                # grow quickly, settle back a little slower so leaving the dock feels soft
                k = 0.24 if target > cur or attr == "hidden_amt" else 0.15
                setattr(self, attr, target if not animate else cur + (target - cur) * k)
                busy = True
            else:
                setattr(self, attr, target)
        if self.hover <= 0.0 and self.mouse is None:
            self.mag_at = None
        now = time.time()
        if any(now - i.bounce_t0 < 1.5 for i in self.items):
            busy = True
        if not busy:
            self._frame.stop()
        self._update_mask()
        self.update()

    def _update_mask(self):
        if not IS_LINUX:
            return
        if self.hidden_amt > 0.98:
            self.setMask(QRegion(self._rect(0, self._main_len(), 0, 3).toAlignedRect()))
        elif self.mouse is None and self.drag is None:
            _l, a, b = self.layout()
            self.setMask(QRegion(self._rect(a - 4, b - a + 8, 0, self.em + self.thick() + 4).toAlignedRect()))
        else:
            self.clearMask()

    def _maybe_hide(self):
        if self.autohide and self.mouse is None and not self.menu_open and self.drag is None:
            self.hidden_target = 1.0
            self._kick()

    # --------------------------------------------------------------- input
    def mouseMoveEvent(self, e):
        pt = QPointF(e.pos())
        if self.press and not self.drag:
            it, p0 = self.press
            if it.pinned and (abs(self._main(pt) - self._main(p0)) > 8 or abs(self._cross(pt) - self._cross(p0)) > 8):
                self.drag = it
        if self.drag is not None:
            self.mouse = pt
            self._drag_reorder(pt)
            self.update()
            return
        over_dock = self._cross(pt) <= self.em + self.thick() + (self.mag - self.base) * self.hover + 6
        _l, a, b = self.layout()
        m = self._main(pt)
        if self.hidden_amt > 0.5:
            over_dock = self._cross(pt) <= 3 and a <= m <= b
        else:
            over_dock = over_dock and a - 6 <= m <= b + 6
        if over_dock:
            self.mouse = pt
            self.mag_at = pt
            under = self.item_at(pt)
            hit = self._tray_part_at(pt) if under is not None and under.kind == "tray" else None
            key = hit[0] if hit else None
            if key != self.tray_hover:
                self.tray_hover = key
                self.update()
            self.hover_target = 1.0
            self.hidden_target = 0.0
            self._autohide_timer.stop()
        elif self.mouse is not None:
            self._mouse_gone()
        self._kick()

    def _mouse_gone(self):
        self.mouse = None
        self.tray_hover = None
        self.hover_target = 0.0
        if self.autohide:
            self._autohide_timer.start(650)
        self._kick()

    def leaveEvent(self, e):
        if self.drag is None:
            self._mouse_gone()

    def mousePressEvent(self, e):
        it = self.item_at(QPointF(e.pos()))
        if e.button() == Qt.LeftButton and it is not None:
            self.press = (it, QPointF(e.pos()))
        elif e.button() == Qt.MiddleButton and it is not None and it.kind == "app" and it.path:
            self._launch(it)
        elif e.button() == Qt.RightButton:
            self._context(it, e.globalPos())

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.LeftButton:
            return
        if self.drag is not None:
            it = self.drag
            self.drag = None
            self.press = None
            if self._cross(QPointF(e.pos())) > self.em + self.thick() + 40 or not self.rect().contains(e.pos()):
                self._unpin(it)
            else:
                self._save_pin_order()
            self._mouse_gone()
            return
        if self.press:
            it, _p = self.press
            self.press = None
            if self.item_at(QPointF(e.pos())) is it:
                self._click(it, QPointF(e.pos()))

    def wheelEvent(self, e):
        it = self.item_at(QPointF(e.pos()))
        if it is not None and it.kind == "tray":
            hit = self._tray_part_at(QPointF(e.pos()))
            if hit and hit[0] == "vol" and self.hub.volume:
                level = max(0, min(100, self.hub.volume[0] + (2 if e.angleDelta().y() > 0 else -2)))
                self.hub.backend.set_volume(level)
                self.hub._poll_volume()
            return
        if it and it.windows:
            # scroll on an app to cycle through its windows
            self.hub.backend.activate(it.windows[-1 if e.angleDelta().y() > 0 else 0].id)

    def _drag_reorder(self, pt):
        pinned = [i for i in self.items if i.pinned]
        if self.drag not in pinned:
            return
        lay, _a, _b = self.layout()
        m = self._main(pt)
        target = None
        for it, x, s in lay:
            if it.pinned and x <= m <= x + s:
                target = it
                break
        if target is None or target is self.drag:
            return
        a, b = self.items.index(self.drag), self.items.index(target)
        self.items.insert(b, self.items.pop(a))

    def _save_pin_order(self):
        by_key = {}
        for pin in self.c.get("pinned", []):
            m = pin.get("match") or pin.get("path", "")
            k = m if str(m).startswith("wm:") else os.path.normcase(m)
            by_key[k] = pin
        order = [by_key[i.key] for i in self.items if i.pinned and i.key in by_key]
        self.cfg.set("dock", "pinned", order, emit=False)
        self._rebuild()

    # -------------------------------------------------------------- actions
    def _click(self, it, pt=None):
        be = self.hub.backend
        if it.kind == "tray":
            if pt is not None:
                self._tray_click(pt)
            return
        if it.kind == "launcher":
            self.hub.do("launcher")
        elif it.kind == "trash":
            be.open_trash()
        elif it.kind == "app":
            if not it.windows:
                self._launch(it)
                return
            fg = be.foreground()
            ids = [w.id for w in it.windows]
            if fg in ids:
                if len(ids) > 1:
                    be.activate(ids[(ids.index(fg) + 1) % len(ids)])
                else:
                    self._minimize(it, fg)
            else:
                target = next((w for w in it.windows if not w.minimized), it.windows[0])
                if be.is_minimized(target.id):
                    self._restore(it, target.id)
                else:
                    be.activate(target.id)
            QTimer.singleShot(250, self.hub._poll_windows)

    def _launch(self, it):
        if it.path and self.hub.backend.launch(it.path):
            it.bounce_t0 = time.time()
            self._kick()

    def _pin(self, it):
        pins = list(self.c.get("pinned", []))
        entry = self.hub.backend.resolve_pin(it.path) if it.path else None
        if entry is None:
            return
        entry["name"] = it.name or entry["name"]
        entry["match"] = it.key
        pins.append(entry)
        self.cfg.set("dock", "pinned", pins)

    def _unpin(self, it):
        pins = []
        for p in self.c.get("pinned", []):
            m = p.get("match") or p.get("path", "")
            k = m if str(m).startswith("wm:") else os.path.normcase(m)
            if k != it.key:
                pins.append(p)
        self.cfg.set("dock", "pinned", pins)

    def _context(self, it, gpos):
        m = QMenu(self)
        m.setAttribute(Qt.WA_TranslucentBackground)
        m.setWindowFlags(m.windowFlags() | Qt.FramelessWindowHint | Qt.NoDropShadowWindowHint)
        m.setStyleSheet(menu_stylesheet(self.pal))
        be = self.hub.backend
        if it is not None and it.kind == "app":
            for w in it.windows[:12]:
                m.addAction(elide_text(w.title, 48), lambda wid=w.id: be.activate(wid))
            if it.windows:
                m.addSeparator()
            if it.path:
                m.addAction("New Window" if it.windows else "Open", lambda: self._launch(it))
            if it.pinned:
                m.addAction("Remove from Dock", lambda: self._unpin(it))
            elif it.path:
                m.addAction("Keep in Dock", lambda: self._pin(it))
            if it.windows:
                m.addSeparator()
                label = "Close Window" if len(it.windows) == 1 else f"Close {len(it.windows)} Windows"
                m.addAction(label, lambda: [be.close(w.id) for w in it.windows])
        elif it is not None and it.kind == "trash":
            m.addAction("Open Trash", be.open_trash)
        else:
            pos = m.addMenu("Position on Screen")
            pos.setStyleSheet(menu_stylesheet(self.pal))
            for key, label in (("left", "Left"), ("bottom", "Bottom"), ("right", "Right")):
                a = pos.addAction(label, lambda k=key: self.cfg.set("dock", "position", k))
                a.setCheckable(True)
                a.setChecked(self.pos_kind == key)
            a = m.addAction("Turn Hiding " + ("Off" if self.autohide else "On"),
                            lambda: self.cfg.set("dock", "autohide", not self.autohide))
            a = m.addAction("Turn Magnification " + ("Off" if self.c.get("magnification", True) else "On"),
                            lambda: self.cfg.set("dock", "magnification", not self.c.get("magnification", True)))
            m.addSeparator()
            if be.name == "windows":
                m.addAction("Show System Tray", be.peek_taskbar)
            m.addAction("Dock Settings…", lambda: self.hub.do("settings"))
            m.addSeparator()
            m.addAction("Quit Nocthify", lambda: self.hub.do("quit"))
        self.menu_open = True
        m.exec_(gpos)
        self.menu_open = False
        self.press = None
        if not self.rect().contains(self.mapFromGlobal(self.cursor().pos())):
            self._mouse_gone()

    # -------------------------------------------------------------- painting
    def _icon(self, it, size_px):
        key = (it.kind, it.key or it.path)
        pm = self._icons.get(key, False)
        if pm is False:
            source = it.key if it.key and not it.key.startswith(("class:",)) else it.path
            if source and not os.path.exists(source) and it.path:
                source = it.path
            try:
                pm = self.hub.backend.app_icon(source, size_px, it.windows[0].id if it.windows else None)
            except Exception:
                pm = None
            if pm is None and it.path and it.path != source:
                try:
                    pm = self.hub.backend.app_icon(it.path, size_px)
                except Exception:
                    pm = None
            self._icons[key] = pm  # failed lookups are retried on the next window change
        return pm

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pal = self.pal
        lay, a, b = self.layout()
        if not lay:
            return
        off = self._hide_offset()
        pad = self.pad()
        if self.autohide:  # 1-alpha strip so the hidden dock still feels the mouse
            p.fillRect(self._rect(a, b - a, 0, 2), QColor(0, 0, 0, 2))
        if self.hidden_amt > 0.995:
            return
        pill = self._rect(a, b - a, self.em + off, self.thick())
        radius = pad + self.base * 0.26
        paint_glass(p, rounded_path(pill, radius), pal)
        dpr = self.devicePixelRatioF() or 1.0
        icon_px = int(self.mag * dpr)
        now = time.time()
        hovered = self.item_at(self.mouse) if self.mouse is not None and self.drag is None else None
        for it, x, s in lay:
            if it.kind == "sep":
                line = self._rect(x + s / 2 - 0.5, 1, self.em + off + pad * 0.9, self.base - pad * 0.3)
                p.fillRect(line, pal.with_alpha(pal.fg, 60))
                continue
            lift = 0.0
            t = now - it.bounce_t0
            if t < 1.5:
                lift = abs(math.sin(t * math.pi * 2.4)) * self.base * 0.42 * (1 - t / 1.5)
            if it is self.drag and self.mouse is not None:
                lift += max(0.0, self._cross(self.mouse) - self.em - self.thick() / 2 - s / 2)
            if it.kind == "tray":
                self._paint_tray(p, x, off)
                continue
            r = self._rect(x, s, self.em + off + pad + lift, s)
            self._paint_item(p, it, r, icon_px)
            if it.windows:
                dot = self._rect(x + s / 2 - 2.2, 4.4, self.em + off + pad * 0.32, 4.4)
                p.setPen(Qt.NoPen)
                p.setBrush(pal.with_alpha(pal.fg, 210))
                p.drawEllipse(dot)
        if hovered is not None and hovered.kind == "tray":
            hit = self._tray_part_at(self.mouse)
            if hit:
                tip = self._tray_tip(hit[0])
                if tip:
                    self._paint_label(p, tip, hit[1], hit[2], self.base, off)
        elif hovered is not None and hovered.kind != "sep" and self.c.get("show_labels", True):
            for it, x, s in lay:
                if it is hovered:
                    name = it.name or self.hub.backend.app_name(it.key)
                    if it.windows and len(it.windows) > 1:
                        name = f"{name}  ·  {len(it.windows)}"
                    self._paint_label(p, name, x, s, s, off)

    def _paint_item(self, p, it, r, icon_px):
        pal = self.pal
        if it.kind == "launcher":
            g = QLinearGradient(r.topLeft(), r.bottomRight())
            g.setColorAt(0, QColor("#5AC8FA"))
            g.setColorAt(0.55, pal.accent)
            g.setColorAt(1, QColor("#BF5AF2"))
            p.setPen(Qt.NoPen)
            p.setBrush(g)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), r.width() * 0.23, r.width() * 0.23)
            icons.draw(p, "grid", r.adjusted(r.width() * 0.27, r.height() * 0.27, -r.width() * 0.27,
                                             -r.height() * 0.27), QColor(255, 255, 255, 240))
            return
        if it.kind == "trash":
            p.setPen(Qt.NoPen)
            g = QLinearGradient(r.topLeft(), r.bottomLeft())
            g.setColorAt(0, QColor(255, 255, 255, 235))
            g.setColorAt(1, QColor(214, 218, 226, 235))
            p.setBrush(g)
            p.drawRoundedRect(r.adjusted(1, 1, -1, -1), r.width() * 0.23, r.width() * 0.23)
            icons.draw(p, "trash", r.adjusted(r.width() * 0.25, r.height() * 0.25, -r.width() * 0.25,
                                              -r.height() * 0.25), QColor(70, 74, 84), 1.8)
            return
        pm = self._icon(it, icon_px)
        if pm is not None and not pm.isNull():
            # QPainter's bilinear filter turns a 128 px icon drawn at 48 px soft and jaggy.
            # Pre-scale with Qt's area-averaging filter to the exact device size instead.
            # Only two copies per icon: the resting size (drawn 1:1) and the fully magnified
            # size, which is drawn slightly smaller in between (<1.6x: bilinear stays sharp).
            dpr = self.devicePixelRatioF() or 1.0
            px = max(1, int(round(r.width() * dpr)))
            base_px = max(1, int(round(self.base * dpr)))
            which = "base" if px <= base_px else "mag"
            size = base_px if which == "base" else max(px, int(round(self.mag * dpr)))
            key = (it.kind, it.key or it.path, which)
            spm = self._scaled.get(key)
            if spm is None or spm.width() != size and spm.height() != size:
                spm = pm if pm.width() == size else pm.scaled(size, size, Qt.KeepAspectRatio,
                                                               Qt.SmoothTransformation)
                spm.setDevicePixelRatio(dpr)
                self._scaled[key] = spm
            if spm.width() == px or spm.height() == px:
                w, h = spm.width() / dpr, spm.height() / dpr
                x = round((r.center().x() - w / 2) * dpr) / dpr
                y = round((r.center().y() - h / 2) * dpr) / dpr
                p.drawPixmap(QPointF(x, y), spm)
            else:
                p.drawPixmap(r, spm, QRectF(spm.rect()))
            return
        p.setPen(Qt.NoPen)
        g = QLinearGradient(r.topLeft(), r.bottomRight())
        g.setColorAt(0, QColor("#8E8E93"))
        g.setColorAt(1, QColor("#48484A"))
        p.setBrush(g)
        p.drawRoundedRect(r.adjusted(1, 1, -1, -1), r.width() * 0.23, r.width() * 0.23)
        p.setPen(QColor("white"))
        p.setFont(font(r.height() * 0.42, QFont.DemiBold))
        p.drawText(r, Qt.AlignCenter, (it.name or "?")[:1].upper())

    def _paint_tray(self, p, x, off):
        pal = self.pal
        b = self.base
        c0 = self.em + off + self.pad()
        horiz = self.pos_kind == "bottom"
        fg = pal.fg
        pos = x
        for key, length in self._tray_parts():
            r = self._rect(pos, length, c0, b)
            pos += length
            if key == self.tray_hover:
                p.setPen(Qt.NoPen)
                p.setBrush(pal.tile_hover)
                p.drawRoundedRect(r.adjusted(1.5, 3, -1.5, -3) if horiz else r.adjusted(3, 1.5, -3, -1.5),
                                  b * 0.2, b * 0.2)
            g = b * 0.40
            box = QRectF(r.center().x() - g / 2, r.center().y() - g / 2, g, g)
            if key == "chev":
                icons.draw(p, "chevron_up", box.adjusted(g * 0.1, g * 0.1, -g * 0.1, -g * 0.1), fg, 2.2)
            elif key == "net":
                kind = (self.hub.network or ("none", ""))[0]
                glyph = {"wifi": "wifi", "ethernet": "ethernet"}.get(kind, "wifi_off")
                icons.draw(p, glyph, box, fg)
            elif key == "vol":
                v = self.hub.volume
                muted = bool(v and (v[1] or v[0] == 0))
                icons.draw(p, "volume_mute" if muted else "volume", box, fg)
            elif key == "bat":
                pct, plugged = self.hub.battery or (0, False)
                p.setFont(font(max(10.0, b * 0.24), QFont.DemiBold))
                txt = f"{pct}%"
                if horiz:
                    bw, bh = b * 0.46, b * 0.24
                    tw = p.fontMetrics().horizontalAdvance(txt)
                    total = bw + 5 + tw
                    x0 = r.center().x() - total / 2
                    paint_battery(p, QRectF(x0, r.center().y() - bh / 2, bw, bh), pct, plugged, fg, pal)
                    p.setPen(fg)
                    p.drawText(QRectF(x0 + bw + 5, r.top(), tw + 2, r.height()), Qt.AlignLeft | Qt.AlignVCenter, txt)
                else:
                    bw, bh = b * 0.42, b * 0.22
                    paint_battery(p, QRectF(r.center().x() - bw / 2, r.top() + r.height() * 0.2, bw, bh),
                                  pct, plugged, fg, pal)
                    p.setFont(font(max(9.0, b * 0.2), QFont.DemiBold))
                    p.setPen(fg)
                    p.drawText(QRectF(r.left(), r.top() + r.height() * 0.5, r.width(), r.height() * 0.4),
                               Qt.AlignCenter, txt)
            elif key == "clock":
                t, d = self._clock_texts()
                f1, f2 = self._tray_fonts()
                if horiz:
                    p.setFont(f1)
                    p.setPen(fg)
                    p.drawText(QRectF(r.left(), r.top() + b * 0.06, r.width(), b * 0.46),
                               Qt.AlignHCenter | Qt.AlignBottom, t)
                    p.setFont(f2)
                    p.setPen(pal.fg2)
                    p.drawText(QRectF(r.left(), r.top() + b * 0.54, r.width(), b * 0.4),
                               Qt.AlignHCenter | Qt.AlignTop, d)
                else:
                    hh, _sep, mm = time.strftime("%H:%M" if self.cfg.get("general", "clock_24h")
                                                 else "%I:%M").partition(":")
                    p.setFont(f1)
                    p.setPen(fg)
                    p.drawText(QRectF(r.left(), r.top() + r.height() * 0.08, r.width(), r.height() * 0.42),
                               Qt.AlignHCenter | Qt.AlignBottom, hh)
                    p.drawText(QRectF(r.left(), r.top() + r.height() * 0.5, r.width(), r.height() * 0.42),
                               Qt.AlignHCenter | Qt.AlignTop, mm)

    def _paint_label(self, p, name, x, s, cross, off):
        pal = self.pal
        p.setFont(font(12.5, QFont.Medium))
        tw = min(320, p.fontMetrics().horizontalAdvance(name) + 24)
        th = 26
        c0 = self.em + off + self.pad() + cross + 10
        if self.pos_kind == "bottom":
            cx = x + s / 2
            rect = QRectF(cx - tw / 2, self.height() - c0 - th, tw, th)
            rect.moveLeft(max(4, min(self.width() - tw - 4, rect.left())))
        elif self.pos_kind == "left":
            rect = QRectF(c0, x + s / 2 - th / 2, tw, th)
        else:
            rect = QRectF(self.width() - c0 - tw, x + s / 2 - th / 2, tw, th)
        paint_glass(p, rounded_path(rect, 8), pal, shadow=False)
        p.setPen(pal.fg)
        p.drawText(rect, Qt.AlignCenter, elide(p, name, tw - 16))


def elide_text(text, n):
    return text if len(text) <= n else text[: n - 1] + "…"
