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

from PyQt5.QtCore import QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QRegion
from PyQt5.QtWidgets import QApplication, QMenu, QWidget

from .. import icons
from ..theme import elide, font, menu_stylesheet, paint_glass, rounded_path

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
        self.reload()

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
        self.items = items
        for k in [k for k, v in self._icons.items() if v is None]:
            del self._icons[k]
        self._resize()
        self.update()

    def _on_windows(self, _wins):
        if self.drag is None:
            self._rebuild()

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
        return max(2.0, self.gap() * 0.6) if it.kind == "sep" else size

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
        if self.mouse is not None and self.mag > self.base and self.hover > 0.001:
            mm = self._main(self.mouse)
            rng = self.base * 2.6
            for i, it in enumerate(self.items):
                if it.kind == "sep":
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
            if x - self.gap() / 2 <= m <= x + s + self.gap() / 2 and c <= self.em + self.pad() + s + 4:
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
                setattr(self, attr, target if not animate else cur + (target - cur) * 0.24)
                busy = True
            else:
                setattr(self, attr, target)
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
            self.hover_target = 1.0
            self.hidden_target = 0.0
            self._autohide_timer.stop()
        elif self.mouse is not None:
            self._mouse_gone()
        self._kick()

    def _mouse_gone(self):
        self.mouse = None
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
                self._click(it)

    def wheelEvent(self, e):
        it = self.item_at(QPointF(e.pos()))
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
    def _click(self, it):
        be = self.hub.backend
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
                    be.minimize(fg)
            else:
                target = next((w for w in it.windows if not w.minimized), it.windows[0])
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
            r = self._rect(x, s, self.em + off + pad + lift, s)
            self._paint_item(p, it, r, icon_px)
            if it.windows:
                dot = self._rect(x + s / 2 - 2.2, 4.4, self.em + off + pad * 0.32, 4.4)
                p.setPen(Qt.NoPen)
                p.setBrush(pal.with_alpha(pal.fg, 210))
                p.drawEllipse(dot)
        if hovered is not None and hovered.kind != "sep" and self.c.get("show_labels", True):
            for it, x, s in lay:
                if it is hovered:
                    self._paint_label(p, it, x, s, off)

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
            p.drawPixmap(r, pm, QRectF(pm.rect()))
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

    def _paint_label(self, p, it, x, s, off):
        pal = self.pal
        name = it.name or self.hub.backend.app_name(it.key)
        if it.windows and len(it.windows) > 1:
            name = f"{name}  ·  {len(it.windows)}"
        p.setFont(font(12.5, QFont.Medium))
        tw = min(320, p.fontMetrics().horizontalAdvance(name) + 24)
        th = 26
        c0 = self.em + off + self.pad() + s + 10
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
