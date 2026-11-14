"""Reusable painted widgets in the iOS / macOS control-center style."""
from __future__ import annotations

import sys

from PyQt5.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRectF, Qt,
                          QVariantAnimation, pyqtSignal)
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath
from PyQt5.QtWidgets import QWidget

from .. import icons
from ..theme import elide, font, paint_glass, rounded_path

IS_LINUX = not sys.platform.startswith("win")


class GlassPopup(QWidget):
    """Floating translucent panel that animates in and closes on outside click."""

    closed = pyqtSignal()
    RADIUS = 22

    def __init__(self, hub, focusable=False):
        flags = Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.NoDropShadowWindowHint
        flags |= Qt.Popup if not focusable else Qt.Tool
        super().__init__(None, flags)
        self.hub = hub
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating, False)
        self._anim = None
        self._blur_on = False
        hub.theme_changed.connect(self.on_theme)

    @property
    def pal(self):
        return self.hub.palette

    @property
    def margin(self):
        return 2 if self._blur_on else 16

    def on_theme(self):
        self.update()

    def panel_rect(self) -> QRectF:
        m = self.margin
        return QRectF(m, m, self.width() - 2 * m, self.height() - 2 * m)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = rounded_path(self.panel_rect(), self.RADIUS)
        paint_glass(p, path, self.pal, shadow=not self._blur_on)
        self.paint_content(p)

    def paint_content(self, p):
        pass

    def popup_at(self, pos: QPoint, rise: QPoint = None):
        """Show at pos. rise = offset the panel slides in from (e.g. QPoint(0, 40) = up from the dock)."""
        self._blur_on = bool(self.hub.config.get("general", "real_blur"))
        animate = bool(self.hub.config.get("general", "animations"))
        start = pos + rise if (rise is not None and animate) else pos
        self.move(start)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        if not IS_LINUX:
            # opened from a keyboard hook / tray: make sure we really get the keyboard focus
            try:
                self.hub.backend.activate(int(self.winId()))
            except Exception:
                pass
        if self._blur_on:
            self.hub.backend.apply_blur(self, self.RADIUS, True, self.pal.dark)
        # once it has settled, hand the memory touched while opening back to Windows
        self.hub.schedule_trim(2500)
        if animate:
            self._anim = QPropertyAnimation(self, b"windowOpacity", self)
            self._anim.setDuration(170)
            self._anim.setStartValue(0.0)
            self._anim.setEndValue(1.0)
            self._anim.setEasingCurve(QEasingCurve.OutCubic)
            self._anim.start()
            if start != pos:
                self._anim_pos = QPropertyAnimation(self, b"pos", self)
                self._anim_pos.setDuration(260)
                self._anim_pos.setStartValue(start)
                self._anim_pos.setEndValue(pos)
                self._anim_pos.setEasingCurve(QEasingCurve.OutCubic)
                self._anim_pos.start()
        else:
            self.setWindowOpacity(1.0)

    def hideEvent(self, ev):
        super().hideEvent(ev)
        self.closed.emit()
        self.hub.schedule_trim(1500)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.hide()
        else:
            super().keyPressEvent(ev)


class _Hoverable(QWidget):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.hover = False
        self.pressed = False
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)

    def pal(self):
        w = self.window()
        return w.hub.palette

    def enterEvent(self, e):
        self.hover = True
        self.update()

    def leaveEvent(self, e):
        self.hover = False
        self.pressed = False
        self.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self.pressed = True
            self.update()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton and self.pressed:
            self.pressed = False
            self.update()
            if self.rect().contains(e.pos()):
                self.clicked.emit()


class Tile(_Hoverable):
    """Rounded control tile. layout: 'row' (icon + text) or 'square' (icon above label)."""

    def __init__(self, glyph, title, subtitle="", layout="row", toggle=False, parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.title = title
        self.subtitle = subtitle
        self.layout_kind = layout
        self.toggle = toggle
        self.active = False

    def set_state(self, active=None, subtitle=None, glyph=None, title=None):
        if active is not None:
            self.active = active
        if subtitle is not None:
            self.subtitle = subtitle
        if glyph is not None:
            self.glyph = glyph
        if title is not None:
            self.title = title
        self.update()

    def paintEvent(self, _e):
        pal = self.pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        bg = QColor(pal.tile_hover if self.hover else pal.tile)
        if self.pressed:
            bg.setAlpha(min(255, bg.alpha() + 30))
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(r, 16, 16)
        if self.layout_kind == "square":
            d = min(r.width(), r.height()) * 0.46
            circ = QRectF(r.center().x() - d / 2, r.top() + (r.height() - d) / 2 - 7, d, d)
            p.setBrush(pal.accent if self.active else pal.with_alpha(pal.fg, 28))
            p.drawEllipse(circ)
            fg = QColor("#ffffff") if self.active else pal.fg
            icons.draw(p, self.glyph, circ.adjusted(d * 0.25, d * 0.25, -d * 0.25, -d * 0.25), fg)
            p.setFont(font(10.5, QFont.Medium))
            p.setPen(pal.fg2)
            tr = QRectF(r.left() + 2, circ.bottom() + 2, r.width() - 4, 16)
            p.drawText(tr, Qt.AlignCenter, elide(p, self.title, tr.width()))
            return
        d = 32.0
        circ = QRectF(r.left() + 10, r.center().y() - d / 2, d, d)
        p.setBrush(pal.accent if self.active else pal.with_alpha(pal.fg, 28))
        p.drawEllipse(circ)
        fg = QColor("#ffffff") if self.active else pal.fg
        icons.draw(p, self.glyph, circ.adjusted(8, 8, -8, -8), fg)
        tx = circ.right() + 9
        tw = r.right() - tx - 8
        p.setPen(pal.fg)
        p.setFont(font(12.5, QFont.DemiBold))
        if self.subtitle:
            p.drawText(QRectF(tx, r.center().y() - 16, tw, 17), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(p, self.title, tw))
            p.setFont(font(11))
            p.setPen(pal.fg2)
            p.drawText(QRectF(tx, r.center().y() + 1, tw, 15), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(p, self.subtitle, tw))
        else:
            p.drawText(QRectF(tx, r.top(), tw, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       elide(p, self.title, tw))


class RoundButton(_Hoverable):
    def __init__(self, glyph, size=34, flat=False, tooltip="", parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.flat = flat
        self.setFixedSize(size, size)
        if tooltip:
            self.setToolTip(tooltip)

    def set_glyph(self, glyph):
        self.glyph = glyph
        self.update()

    def paintEvent(self, _e):
        pal = self.pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if not self.flat or self.hover:
            p.setPen(Qt.NoPen)
            p.setBrush(pal.tile_hover if self.hover else pal.tile)
            p.drawEllipse(r)
        s = r.width() * (0.5 if self.flat else 0.44)
        icons.draw(p, self.glyph, QRectF(r.center().x() - s / 2, r.center().y() - s / 2, s, s), pal.fg)


class BigSlider(QWidget):
    """Thick iOS-style slider with an icon inside the track."""

    valueChanged = pyqtSignal(int)      # live while dragging
    valueCommitted = pyqtSignal(int)    # on release
    iconClicked = pyqtSignal()

    def __init__(self, glyph, title="", parent=None):
        super().__init__(parent)
        self.glyph = glyph
        self.title = title
        self.value = 50
        self.enabled_state = True
        self._drag = False
        self.setFixedHeight(56 if title else 34)
        self.setCursor(Qt.PointingHandCursor)

    def pal(self):
        return self.window().hub.palette

    def track(self) -> QRectF:
        top = 22 if self.title else 0
        return QRectF(0.5, top + 0.5, self.width() - 1, 33)

    def setValue(self, v, emit=False):
        v = max(0, min(100, int(v)))
        if v != self.value:
            self.value = v
            self.update()
            if emit:
                self.valueChanged.emit(v)

    def set_glyph(self, glyph):
        self.glyph = glyph
        self.update()

    def paintEvent(self, _e):
        pal = self.pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self.title:
            p.setPen(pal.fg)
            p.setFont(font(12.5, QFont.DemiBold))
            p.drawText(QRectF(2, 0, self.width(), 18), Qt.AlignLeft | Qt.AlignVCenter, self.title)
        tr = self.track()
        path = rounded_path(tr, tr.height() / 2)
        p.setPen(Qt.NoPen)
        p.setBrush(pal.with_alpha(pal.fg, 30))
        p.drawPath(path)
        frac = self.value / 100.0 if self.enabled_state else 0
        fill_w = max(tr.height(), tr.width() * frac)
        fill = QRectF(tr.left(), tr.top(), fill_w, tr.height())
        p.save()
        p.setClipPath(path)
        p.setBrush(QColor(255, 255, 255, 235) if pal.dark else QColor(255, 255, 255, 255))
        p.drawRoundedRect(fill, tr.height() / 2, tr.height() / 2)
        p.restore()
        ic = QRectF(tr.left() + 9, tr.center().y() - 8, 16, 16)
        icons.draw(p, self.glyph, ic, QColor(40, 40, 46) if fill.right() > ic.right() else pal.fg)
        if not self.enabled_state:
            p.setPen(pal.fg3)
            p.setFont(font(11))
            p.drawText(tr.adjusted(32, 0, -10, 0), Qt.AlignRight | Qt.AlignVCenter, "Not available")

    def _set_from_x(self, x):
        tr = self.track()
        frac = (x - tr.left()) / max(1.0, tr.width())
        self.setValue(round(frac * 100), emit=True)

    def mousePressEvent(self, e):
        if not self.enabled_state or e.button() != Qt.LeftButton:
            return
        tr = self.track()
        if e.pos().x() < tr.left() + 30 and tr.contains(e.pos()):
            self.iconClicked.emit()
            return
        self._drag = True
        self._set_from_x(e.pos().x())

    def mouseMoveEvent(self, e):
        if self._drag:
            self._set_from_x(e.pos().x())

    def mouseReleaseEvent(self, e):
        if self._drag:
            self._drag = False
            self.valueCommitted.emit(self.value)

    def wheelEvent(self, e):
        if self.enabled_state:
            self.setValue(self.value + (5 if e.angleDelta().y() > 0 else -5), emit=True)
            self.valueCommitted.emit(self.value)


class Anim(QVariantAnimation):
    """Tiny helper: animate a float and call back on every frame."""

    def __init__(self, parent, on_value, duration=260, curve=QEasingCurve.OutCubic):
        super().__init__(parent)
        self.setDuration(duration)
        self.setEasingCurve(curve)
        self.valueChanged.connect(on_value)

    def go(self, start, end, duration=None, curve=None):
        self.stop()
        if duration is not None:
            self.setDuration(duration)
        if curve is not None:
            self.setEasingCurve(curve)
        self.setStartValue(float(start))
        self.setEndValue(float(end))
        self.start()


def path_for(rect: QRectF, radius: float) -> QPainterPath:
    return rounded_path(rect, radius)
