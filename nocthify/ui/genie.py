"""macOS-style "genie" effect for minimising to / restoring from the dock.

A click-through overlay draws a snapshot of the window being sucked into
(or poured out of) its dock icon.  The snapshot is cut into thin bands along
the flow direction; each band slides and narrows on its own schedule, the
bands nearest the dock leading, which produces the funnel shape.

Quality rules (so the effect never looks lower-res than the real window):
* band edges are snapped to whole device pixels and never overlap, so an
  un-squeezed band is copied 1:1 with no resampling at all;
* the very first / last frame is the untouched snapshot at its exact spot;
* the overlay only covers the area the animation actually needs.
"""
from __future__ import annotations

import math

from PyQt5.QtCore import QEasingCurve, QPointF, QRectF, Qt, QTimer, QVariantAnimation
from PyQt5.QtGui import QPainter, QPixmap
from PyQt5.QtWidgets import QApplication, QWidget


def _smooth(x):
    x = 0.0 if x < 0 else 1.0 if x > 1 else x
    return x * x * (3 - 2 * x)


def _lerp(a, b, t):
    return a + (b - a) * t


class Genie(QWidget):
    LAG = 0.55          # how much later the far edge starts moving than the near edge

    def __init__(self):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool |
                         Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus |
                         Qt.NoDropShadowWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.pm = None
        self.src = QRectF()
        self.dst = QRectF()
        self.edge = "bottom"
        self.reverse = False
        self.t = 0.0
        self._done = None
        self.anim = QVariantAnimation(self)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.InOutSine)
        self.anim.valueChanged.connect(self._on_value)
        self.anim.finished.connect(self._finish)

    @property
    def running(self):
        return self.anim.state() == QVariantAnimation.Running

    def play(self, image, src_global: QRectF, dst_global: QRectF, edge="bottom", reverse=False,
             on_done=None, duration=480):
        """image: QImage/QPixmap of the window (device pixels); rects: global logical coords."""
        self.stop()
        screen = QApplication.screenAt(src_global.center().toPoint()) or QApplication.primaryScreen()
        area = src_global.united(dst_global).adjusted(-2, -2, 2, 2).intersected(QRectF(screen.geometry()))
        geo = area.toAlignedRect()
        self.setGeometry(geo)
        self.pm = image if isinstance(image, QPixmap) else QPixmap.fromImage(image)
        self.src = src_global.translated(-geo.x(), -geo.y())
        self.dst = dst_global.translated(-geo.x(), -geo.y())
        self.edge = edge
        self.reverse = reverse
        self._done = on_done
        self.t = 1.0 if reverse else 0.0
        self.anim.setDuration(duration)
        self.show()
        self.raise_()
        self.repaint()                  # first frame must be on screen before the window vanishes
        self.anim.start()

    def stop(self):
        if self.running:
            self.anim.stop()
            self._finish()

    def _on_value(self, v):
        self.t = 1.0 - v if self.reverse else v
        self.update()

    def _finish(self):
        cb, self._done = self._done, None
        self.t = 0.0 if self.reverse else 1.0
        if cb is not None:
            cb()                        # e.g. restore the real window first...
        if self.reverse:                # ...and keep the crisp last frame until it has painted
            self.repaint()
            QTimer.singleShot(110, self._clear)
        else:
            self._clear()

    def _clear(self):
        if self.running:
            return
        self.hide()
        self.pm = None

    # ------------------------------------------------------------- drawing
    def paintEvent(self, _e):
        if self.pm is None or self.pm.isNull():
            return
        p = QPainter(self)
        dpr = self.devicePixelRatioF() or 1.0
        t = self.t
        S, D = self.src, self.dst
        if t <= 0.0005:
            # untouched snapshot, pixel-exact: indistinguishable from the real window
            x = round(S.left() * dpr) / dpr
            y = round(S.top() * dpr) / dpr
            pm = self.pm
            pm.setDevicePixelRatio(dpr)
            p.drawPixmap(QPointF(x, y), pm)
            return
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if t > 0.82:
            p.setOpacity(1.0 - (t - 0.82) / 0.18 * 0.55)
        vertical = self.edge not in ("left", "right")     # flow along y (dock at the bottom)
        if vertical:
            a0, a1, c0, c1 = S.top(), S.bottom(), S.left(), S.right()
            ta0, ta1, tc0, tc1 = D.top(), D.bottom(), D.left(), D.right()
        else:
            a0, a1, c0, c1 = S.left(), S.right(), S.top(), S.bottom()
            ta0, ta1, tc0, tc1 = D.left(), D.right(), D.top(), D.bottom()
        toward_end = (ta0 + ta1) / 2 >= (a0 + a1) / 2        # dock lies after the window on the axis
        span = max(1.0, a1 - a0)
        pw, ph = self.pm.width(), self.pm.height()
        src_len = ph if vertical else pw
        step = max(2, int(math.ceil(src_len / 120.0)))      # source rows per band (<= 120 bands)
        squeeze = _smooth(t / 0.38)                          # phase 1: the sides pull in
        lag = self.LAG
        near = ta0 if toward_end else ta1
        far = a0 if toward_end else a1
        reach = (near - far) or 1.0

        def along(v):
            lead = v if toward_end else 1.0 - v             # bands nearest the dock move first
            k = _smooth(t * (1 + lag) - (1 - lead) * lag)
            pos = _lerp(a0 + v * span, ta0 + v * (ta1 - ta0), k)
            return round(pos * dpr) / dpr                    # snap to device pixels: no seams, no overlap

        def cross(pos):
            q = _smooth((pos - far) / reach) * squeeze
            lo = _lerp(c0, tc0, q)
            hi = _lerp(c1, tc1, q)
            return round(lo * dpr) / dpr, round(hi * dpr) / dpr

        r0 = 0
        prev = along(0.0)
        while r0 < src_len:
            r1 = min(src_len, r0 + step)
            cur = along(r1 / src_len)
            lo, hi = (prev, cur) if cur >= prev else (cur, prev)
            if hi - lo >= 0.5 / dpr:
                l, r = cross((lo + hi) / 2)
                if r - l >= 0.5:
                    if vertical:
                        p.drawPixmap(QRectF(l, lo, r - l, hi - lo), self.pm, QRectF(0, r0, pw, r1 - r0))
                    else:
                        p.drawPixmap(QRectF(lo, l, hi - lo, r - l), self.pm, QRectF(r0, 0, r1 - r0, ph))
            prev = cur
            r0 = r1
