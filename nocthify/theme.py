"""Shared look & feel: colours, fonts and the "liquid glass" painter."""
from __future__ import annotations

import sys

from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import (QBrush, QColor, QFont, QFontDatabase, QLinearGradient,
                         QPainter, QPainterPath, QPen)

_FONT_FAMILY = None


def font_family() -> str:
    global _FONT_FAMILY
    if _FONT_FAMILY is None:
        families = set(QFontDatabase().families())
        for name in ("SF Pro Display", "Segoe UI Variable Display", "Segoe UI Variable Text",
                     "Inter", "Segoe UI", "Cantarell", "Noto Sans", "Ubuntu", "DejaVu Sans"):
            if name in families:
                _FONT_FAMILY = name
                break
        else:
            _FONT_FAMILY = QFont().defaultFamily()
    return _FONT_FAMILY


def font(px: float, weight: int = QFont.Normal) -> QFont:
    f = QFont(font_family())
    f.setPixelSize(max(1, int(round(px))))
    f.setWeight(weight)
    f.setHintingPreference(QFont.PreferNoHinting)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


class Palette:
    """Colour set derived from dark/light mode, accent and glass opacity."""

    def __init__(self, dark: bool, accent: str, opacity: float):
        self.dark = dark
        self.accent = QColor(accent) if QColor(accent).isValid() else QColor("#0A84FF")
        opacity = max(0.08, min(1.0, float(opacity)))
        self.opacity = opacity
        if dark:
            self.base = QColor(22, 22, 28)
            self.fg = QColor(255, 255, 255)
            self.fg2 = QColor(255, 255, 255, 165)
            self.fg3 = QColor(255, 255, 255, 95)
            self.tile = QColor(255, 255, 255, 26)
            self.tile_hover = QColor(255, 255, 255, 44)
            self.rim_top = QColor(255, 255, 255, 95)
            self.rim_bottom = QColor(255, 255, 255, 18)
            self.sheen = QColor(255, 255, 255, 30)
            self.shadow = QColor(0, 0, 0, 70)
        else:
            self.base = QColor(250, 250, 253)
            self.fg = QColor(18, 18, 22)
            self.fg2 = QColor(18, 18, 22, 160)
            self.fg3 = QColor(18, 18, 22, 90)
            self.tile = QColor(0, 0, 0, 16)
            self.tile_hover = QColor(0, 0, 0, 30)
            self.rim_top = QColor(255, 255, 255, 230)
            self.rim_bottom = QColor(255, 255, 255, 70)
            self.sheen = QColor(255, 255, 255, 70)
            self.shadow = QColor(0, 0, 0, 45)
        self.base.setAlphaF(opacity)
        self.green = QColor("#30D158")
        self.red = QColor("#FF453A")
        self.orange = QColor("#FF9F0A")
        self.yellow = QColor("#FFD60A")

    def with_alpha(self, color: QColor, alpha: int) -> QColor:
        c = QColor(color)
        c.setAlpha(alpha)
        return c


def rounded_path(rect: QRectF, radius: float) -> QPainterPath:
    path = QPainterPath()
    radius = min(radius, rect.height() / 2, rect.width() / 2)
    path.addRoundedRect(rect, radius, radius)
    return path


def notch_path(rect: QRectF, radius: float) -> QPainterPath:
    """Flat top, rounded bottom, with tiny inverted 'ears' like a real notch."""
    r = min(radius, rect.height() / 2, rect.width() / 2)
    ear = min(8.0, r)
    x0, y0, x1, y1 = rect.left(), rect.top(), rect.right(), rect.bottom()
    p = QPainterPath()
    p.moveTo(x0 - ear, y0)
    p.lineTo(x1 + ear, y0)
    p.quadTo(x1, y0, x1, y0 + ear)
    p.lineTo(x1, y1 - r)
    p.quadTo(x1, y1, x1 - r, y1)
    p.lineTo(x0 + r, y1)
    p.quadTo(x0, y1, x0, y1 - r)
    p.lineTo(x0, y0 + ear)
    p.quadTo(x0, y0, x0 - ear, y0)
    p.closeSubpath()
    return p


def paint_shadow(p: QPainter, path: QPainterPath, pal: Palette, spread: int = 10, dy: float = 4):
    """Cheap soft shadow: a few expanding translucent strokes."""
    p.save()
    p.setBrush(Qt.NoBrush)
    base = pal.shadow.alpha()
    p.translate(0, dy)
    for i in range(spread, 0, -2):
        c = QColor(pal.shadow)
        c.setAlpha(int(base * (1 - i / (spread + 1)) * 0.35))
        p.setPen(QPen(c, i * 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPath(path)
    p.restore()


def paint_glass(p: QPainter, path: QPainterPath, pal: Palette, solid_black: bool = False,
                shadow: bool = True, tint: QColor | None = None):
    """Paint an iOS-style translucent glass surface with rim light."""
    rect = path.boundingRect()
    if shadow:
        paint_shadow(p, path, pal)
    p.save()
    p.setPen(Qt.NoPen)
    if solid_black:
        p.setBrush(QColor(0, 0, 0, 250))
        p.drawPath(path)
        rim = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        rim.setColorAt(0, QColor(255, 255, 255, 0))
        rim.setColorAt(1, QColor(255, 255, 255, 28))
        p.setPen(QPen(QBrush(rim), 1))
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)
        p.restore()
        return
    p.setBrush(tint if tint is not None else pal.base)
    p.drawPath(path)
    # Soft vertical sheen (top is brighter, like light hitting glass)
    sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
    sheen.setColorAt(0.0, pal.sheen)
    sheen.setColorAt(0.45, QColor(255, 255, 255, 0))
    p.setBrush(QBrush(sheen))
    p.drawPath(path)
    # Rim light
    rim = QLinearGradient(rect.topLeft(), rect.bottomRight())
    rim.setColorAt(0.0, pal.rim_top)
    rim.setColorAt(0.5, pal.rim_bottom)
    rim.setColorAt(1.0, pal.with_alpha(pal.rim_top, pal.rim_top.alpha() // 2))
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(QBrush(rim), 1.0))
    inset = QPainterPath(path)
    p.drawPath(inset)
    p.restore()


def paint_tile(p: QPainter, rect: QRectF, radius: float, pal: Palette, hover=False,
               active=False):
    p.save()
    p.setPen(Qt.NoPen)
    if active:
        p.setBrush(pal.accent)
    else:
        p.setBrush(pal.tile_hover if hover else pal.tile)
    p.drawRoundedRect(rect, radius, radius)
    p.restore()


def paint_ring(p: QPainter, center: QPointF, radius: float, value: float, color: QColor,
               pal: Palette, width: float = 3.5):
    p.save()
    rect = QRectF(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
    track = QColor(pal.fg)
    track.setAlpha(40)
    p.setPen(QPen(track, width, Qt.SolidLine, Qt.RoundCap))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(rect)
    p.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap))
    span = int(-max(0.0, min(1.0, value)) * 360 * 16)
    p.drawArc(rect, 90 * 16, span)
    p.restore()


def elide(p: QPainter, text: str, width: float) -> str:
    return p.fontMetrics().elidedText(text or "", Qt.ElideRight, int(max(0, width)))


def menu_stylesheet(pal: Palette) -> str:
    bg = QColor(pal.base)
    bg.setAlpha(max(225, bg.alpha()))
    fg = pal.fg.name()
    sel = pal.accent.name()
    border = "rgba(255,255,255,60)" if pal.dark else "rgba(0,0,0,40)"
    fam = font_family()
    return f"""
    QMenu {{
        background: rgba({bg.red()},{bg.green()},{bg.blue()},{bg.alpha()});
        color: {fg}; border: 1px solid {border}; border-radius: 10px; padding: 6px;
        font-family: '{fam}'; font-size: 13px;
    }}
    QMenu::item {{ padding: 6px 22px 6px 14px; border-radius: 6px; background: transparent; }}
    QMenu::item:selected {{ background: {sel}; color: white; }}
    QMenu::item:disabled {{ color: rgba(128,128,128,160); }}
    QMenu::separator {{ height: 1px; margin: 5px 8px; background: {border}; }}
    QToolTip {{ background: rgba({bg.red()},{bg.green()},{bg.blue()},240); color: {fg};
                border: 1px solid {border}; border-radius: 6px; padding: 4px 8px; }}
    """


def is_dark_system() -> bool:
    if sys.platform.startswith("win"):
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                                 r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return value == 0
        except OSError:
            return True  # Windows 7/8 have no dark mode flag: glass looks best dark
    # Linux: GNOME / GTK hints
    import os
    import subprocess
    gtk_theme = os.environ.get("GTK_THEME", "")
    if gtk_theme:
        return "dark" in gtk_theme.lower()
    try:
        out = subprocess.run(["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                             capture_output=True, text=True, timeout=1).stdout
        if out:
            return "dark" in out
    except (OSError, subprocess.SubprocessError):
        pass
    return True
