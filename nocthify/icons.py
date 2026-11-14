"""Built-in vector glyphs (24x24, stroke based) rendered on demand and cached."""
from __future__ import annotations

from PyQt5.QtCore import QByteArray, QRectF, Qt
from PyQt5.QtGui import QColor, QIcon, QPainter, QPixmap
from PyQt5.QtSvg import QSvgRenderer
from PyQt5.QtWidgets import QApplication

_S = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{c}" ' \
     'stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
_F = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="{c}" stroke="none">{body}</svg>'

# name -> (filled?, svg body)
GLYPHS = {
    "wifi": (0, '<path d="M2 8.8a15 15 0 0 1 20 0"/><path d="M5 12.4a10 10 0 0 1 14 0"/>'
                '<path d="M8.5 15.9a5 5 0 0 1 7 0"/><circle cx="12" cy="19.4" r="1" fill="{c}"/>'),
    "bluetooth": (0, '<path d="m7 7 10 10-5 5V2l5 5L7 17"/>'),
    "airplane": (1, '<path d="M21 16v-2l-8-5V3.5a1.5 1.5 0 0 0-3 0V9l-8 5v2l8-2.5V19l-2 1.5V22'
                    'l3.5-1 3.5 1v-1.5L13 19v-5.5z"/>'),
    "moon": (1, '<path d="M20.5 14.6A8.5 8.5 0 1 1 9.4 3.5a7 7 0 0 0 11.1 11.1z"/>'),
    "sun": (0, '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7'
               'l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    "contrast": (0, '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18z" fill="{c}"/>'),
    "volume": (0, '<path d="M11 5 6 9H3v6h3l5 4z" fill="{c}"/><path d="M15.5 8.5a5 5 0 0 1 0 7"/>'
                  '<path d="M18.5 5.5a9 9 0 0 1 0 13"/>'),
    "volume_mute": (0, '<path d="M11 5 6 9H3v6h3l5 4z" fill="{c}"/><path d="m22 9-6 6M16 9l6 6"/>'),
    "play": (1, '<path d="M7 4.5v15a1 1 0 0 0 1.5.9l12-7.5a1 1 0 0 0 0-1.8l-12-7.5A1 1 0 0 0 7 4.5z"/>'),
    "pause": (1, '<rect x="6" y="4" width="4.2" height="16" rx="1.2"/>'
                 '<rect x="13.8" y="4" width="4.2" height="16" rx="1.2"/>'),
    "next": (1, '<path d="M3 5.5v13a1 1 0 0 0 1.6.8L12 14v4.5a1 1 0 0 0 1.6.8l8.4-6.5a1 1 0 0 0 '
                '0-1.6L13.6 4.7A1 1 0 0 0 12 5.5V10L4.6 4.7A1 1 0 0 0 3 5.5z"/>'),
    "prev": (1, '<path d="M21 5.5v13a1 1 0 0 1-1.6.8L12 14v4.5a1 1 0 0 1-1.6.8L2 12.8a1 1 0 0 1 '
                '0-1.6l8.4-6.5A1 1 0 0 1 12 5.5V10l7.4-5.3A1 1 0 0 1 21 5.5z"/>'),
    "music": (0, '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>'),
    "bolt": (1, '<path d="M13 2 4 14h7l-1 8 9-12h-7z"/>'),
    "lock": (0, '<rect x="4" y="11" width="16" height="10" rx="2.5"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>'),
    "power": (0, '<path d="M12 2v10"/><path d="M18.4 6.6a9 9 0 1 1-12.8 0"/>'),
    "settings": (0, '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 '
                    '1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 '
                    '1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 '
                    '.3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 '
                    '0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3'
                    'a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8'
                    'l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 '
                    '0-1.5 1z"/>'),
    "camera": (0, '<path d="M4 8V6a2 2 0 0 1 2-2h2M16 4h2a2 2 0 0 1 2 2v2M20 16v2a2 2 0 0 1-2 2h-2'
                  'M8 20H6a2 2 0 0 1-2-2v-2"/><circle cx="12" cy="12" r="3"/>'),
    "calculator": (0, '<rect x="4" y="2" width="16" height="20" rx="2.5"/><path d="M8 6h8M8 11h.01M12 '
                      '11h.01M16 11h.01M8 15h.01M12 15h.01M16 15v3M8 18.5h4"/>'),
    "folder": (0, '<path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H9l2 2.5h7.5A2.5 2.5 0 0 1 21 10v7.5a2.5 2.5 0 0 '
                  '1-2.5 2.5h-13A2.5 2.5 0 0 1 3 17.5z"/>'),
    "terminal": (0, '<rect x="2.5" y="4" width="19" height="16" rx="3"/><path d="m7 9.5 3 2.5-3 2.5M12.5 '
                    '15H17"/>'),
    "globe": (0, '<circle cx="12" cy="12" r="9.5"/><path d="M2.5 12h19M12 2.5a14.5 14.5 0 0 1 0 19M12 '
                 '2.5a14.5 14.5 0 0 0 0 19"/>'),
    "grid": (1, '<rect x="3" y="3" width="7.5" height="7.5" rx="2"/><rect x="13.5" y="3" width="7.5" '
                'height="7.5" rx="2"/><rect x="3" y="13.5" width="7.5" height="7.5" rx="2"/><rect x="13.5" '
                'y="13.5" width="7.5" height="7.5" rx="2"/>'),
    "search": (0, '<circle cx="11" cy="11" r="7"/><path d="m20.5 20.5-4.5-4.5"/>'),
    "timer": (0, '<circle cx="12" cy="13.5" r="8"/><path d="M12 9.5v4l2.5 2.5M9.5 2.5h5"/>'),
    "sliders": (0, '<path d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M20 18h0"/><circle cx="16" cy="6" r="2"/>'
                   '<circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
    "trash": (0, '<path d="M3.5 6h17M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2M5.5 6l1 14a2 2 0 0 0 2 1.8h7a2 '
                 '2 0 0 0 2-1.8l1-14M10 10.5v7M14 10.5v7"/>'),
    "monitor": (0, '<rect x="2.5" y="3.5" width="19" height="13" rx="2.5"/><path d="M8 21h8M12 16.5V21"/>'),
    "bell_off": (0, '<path d="M8.7 3.7A6 6 0 0 1 18 8.5c0 4 1 6.2 2 7.5M17 17H3.5s2.5-2 2.5-8.5c0-.6.1-1.2'
                    '.2-1.8M10.3 20.5a2 2 0 0 0 3.4 0M2 2l20 20"/>'),
    "battery": (0, '<rect x="2" y="7" width="17" height="10" rx="2.5"/><path d="M22 11v2"/>'),
    "close": (0, '<path d="M6 6l12 12M18 6 6 18"/>'),
    "plus": (0, '<path d="M12 5v14M5 12h14"/>'),
    "cpu": (0, '<rect x="5" y="5" width="14" height="14" rx="2"/><rect x="9" y="9" width="6" height="6" '
               'rx="1"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/>'),
    "nightlight": (0, '<path d="M12 3v1M5.6 5.6l.7.7M3 12h1M20 12h1M17.7 6.3l.7-.7"/><path d="M8 16a4 4 0 '
                      '1 1 8 0"/><path d="M3 20h18"/>'),
    "cast": (0, '<path d="M2 8V6a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-6"/><path d="M2 12a9 9 0 '
                '0 1 8 8M2 16a5 5 0 0 1 4 4"/><circle cx="2.5" cy="20" r=".6" fill="{c}"/>'),
    "taskbar": (0, '<rect x="2.5" y="4" width="19" height="16" rx="2.5"/><path d="M2.5 15.5h19M6 18h2"/>'),
    "app": (0, '<rect x="3" y="3" width="18" height="18" rx="5"/><path d="M8 12h8M12 8v8"/>'),
    "star": (0, '<path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1 6.2L12 17.3 6.5 20.2l1-6.2L3 9.6l6.2-.9z"/>'),
    "restart": (0, '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>'),
    "sleep": (0, '<path d="M4 4h6l-6 7h6M14 10h6l-6 8h6"/>'),
    "logout": (0, '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4M16 17l5-5-5-5M21 12H9"/>'),
    "keyboard": (0, '<rect x="2" y="5" width="20" height="14" rx="2.5"/><path d="M6 9h.01M10 9h.01M14 9h.01'
                    'M18 9h.01M6 13h.01M18 13h.01M10 13h4M7 16.5h10"/>'),
    "tasks": (0, '<path d="M3 12h4l3-8 4 16 3-8h4"/>'),
    "chevron_up": (0, '<path d="m6 15 6-6 6 6"/>'),
    "chevron_left": (0, '<path d="m15 6-6 6 6 6"/>'),
    "chevron_right": (0, '<path d="m9 6 6 6-6 6"/>'),
    "ethernet": (0, '<rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/>'
                    '<rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v4M6 16v-4h12v4"/>'),
    "wifi_off": (0, '<path d="M2 8.8a15 15 0 0 1 20 0" opacity=".35"/><path d="M5 12.4a10 10 0 0 1 14 0" '
                    'opacity=".35"/><path d="M8.5 15.9a5 5 0 0 1 7 0" opacity=".35"/>'
                    '<circle cx="12" cy="19.4" r="1" fill="{c}"/><path d="m3 3 18 18"/>'),
    "clipboard": (0, '<rect x="5" y="4" width="14" height="17" rx="2.5"/><path d="M9 4V3h6v1M9 10h6M9 14h6'
                     'M9 18h3"/>'),
}

_cache: dict = {}


def svg(name: str, color: str = "#ffffff", width: float = 2.0) -> bytes:
    filled, body = GLYPHS.get(name, GLYPHS["app"])
    body = body.replace("{c}", color)
    tpl = _F if filled else _S
    return tpl.replace("{c}", color).replace("{w}", str(width)).replace("{body}", body).encode()


def pixmap(name: str, color, size: int, width: float = 2.0, dpr: float | None = None) -> QPixmap:
    if isinstance(color, QColor):
        color_key = color.name(QColor.HexArgb)
        color_svg = color.name()
        alpha = color.alphaF()
    else:
        color_key = color_svg = str(color)
        alpha = 1.0
    if dpr is None:
        app = QApplication.instance()
        dpr = app.devicePixelRatio() if app else 1.0
    key = (name, color_key, size, width, dpr)
    pm = _cache.get(key)
    if pm is not None:
        return pm
    real = max(1, int(round(size * dpr)))
    pm = QPixmap(real, real)
    pm.fill(Qt.transparent)
    renderer = QSvgRenderer(QByteArray(svg(name, color_svg, width)))
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setOpacity(alpha)
    renderer.render(p, QRectF(0, 0, real, real))
    p.end()
    pm.setDevicePixelRatio(dpr)
    if len(_cache) > 600:
        _cache.clear()
    _cache[key] = pm
    return pm


def icon(name: str, color="#ffffff", size: int = 24) -> QIcon:
    return QIcon(pixmap(name, color, size))


def draw(p: QPainter, name: str, rect: QRectF, color, width: float = 2.0):
    size = int(round(min(rect.width(), rect.height())))
    pm = pixmap(name, color, size, width)
    x = rect.x() + (rect.width() - size) / 2
    y = rect.y() + (rect.height() - size) / 2
    p.drawPixmap(QRectF(x, y, size, size), pm, QRectF(pm.rect()))
