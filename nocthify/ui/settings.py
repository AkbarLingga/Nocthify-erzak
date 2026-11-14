"""Settings window - every option applies live and is saved automatically."""
from __future__ import annotations

import os
import sys

from PyQt5.QtCore import QRectF, QSize, Qt, QTimer, QUrl
from PyQt5.QtGui import QColor, QDesktopServices, QPainter
from PyQt5.QtWidgets import (QAbstractButton, QColorDialog, QComboBox, QFileDialog, QFrame,
                             QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSlider,
                             QStackedWidget, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from .. import icons
from ..config import APP_VERSION, config_dir
from ..hub import SHORTCUTS
from ..theme import font_family

IS_WIN = sys.platform.startswith("win")
ACCENTS = ["#0A84FF", "#5E5CE6", "#BF5AF2", "#FF375F", "#FF9F0A", "#FFD60A", "#30D158", "#64D2FF",
           "#8E8E93"]


class Switch(QAbstractButton):
    def __init__(self, accent: QColor, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.accent = accent
        self.setFixedSize(46, 28)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(Qt.NoPen)
        p.setBrush(self.accent if self.isChecked() else QColor(120, 120, 128, 90))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.right() - d - 2 if self.isChecked() else r.left() + 2
        p.setBrush(QColor("white"))
        p.drawEllipse(QRectF(x, r.top() + 2, d, d))

    def sizeHint(self):
        return QSize(46, 28)


class Swatch(QAbstractButton):
    def __init__(self, color, selected, parent=None):
        super().__init__(parent)
        self.color = QColor(color)
        self.selected = selected
        self.setFixedSize(26, 26)
        self.setCursor(Qt.PointingHandCursor)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(3, 3, -3, -3)
        p.setPen(Qt.NoPen)
        p.setBrush(self.color)
        p.drawEllipse(r)
        if self.selected:
            p.setBrush(QColor("white"))
            p.drawEllipse(QRectF(r.center().x() - 3.5, r.center().y() - 3.5, 7, 7))


class SettingsWindow(QWidget):
    PAGES = [("General", "settings"), ("Dynamic Island", "app"), ("Dock", "grid"),
             ("Control Center", "sliders"), ("Shortcuts", "star"), ("About", "monitor")]

    def __init__(self, hub, app_ref):
        super().__init__(None, Qt.Window)
        self.hub = hub
        self.cfg = hub.config
        self.app_ref = app_ref
        self.setWindowTitle("Nocthify Settings")
        self.setWindowIcon(icons.icon("app", "#0A84FF", 64))
        self.resize(820, 620)
        self.setMinimumSize(720, 520)
        self._building = False
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.side = QListWidget()
        self.side.setObjectName("side")
        self.side.setFixedWidth(210)
        self.side.setIconSize(QSize(18, 18))
        self.stack = QStackedWidget()
        lay.addWidget(self.side)
        lay.addWidget(self.stack, 1)
        self.side.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.rebuild()
        hub.theme_changed.connect(self.rebuild)

    # ------------------------------------------------------------ building
    def rebuild(self):
        row = max(0, self.side.currentRow())
        self._building = True
        pal = self.hub.palette
        self.side.clear()
        while self.stack.count():
            w = self.stack.widget(0)
            self.stack.removeWidget(w)
            w.deleteLater()
        for name, glyph in self.PAGES:
            it = QListWidgetItem(icons.icon(glyph, pal.accent.name(), 18), "  " + name)
            it.setSizeHint(QSize(190, 38))
            self.side.addItem(it)
        for builder in (self._page_general, self._page_island, self._page_dock, self._page_cc,
                        self._page_shortcuts, self._page_about):
            self.stack.addWidget(self._scroll(builder()))
        self.side.setCurrentRow(row)
        self._style()
        self._building = False

    def _style(self):
        pal = self.hub.palette
        dark = pal.dark
        bg = "#1C1C1E" if dark else "#F2F2F7"
        side = "#232326" if dark else "#E9E9EE"
        card = "#2C2C2E" if dark else "#FFFFFF"
        fg = "#FFFFFF" if dark else "#1C1C1E"
        fg2 = "rgba(235,235,245,150)" if dark else "rgba(60,60,67,150)"
        line = "rgba(255,255,255,22)" if dark else "rgba(0,0,0,18)"
        acc = pal.accent.name()
        fam = font_family()
        self.setStyleSheet(f"""
        QWidget {{ background: {bg}; color: {fg}; font-family: '{fam}'; font-size: 13px; }}
        QListWidget#side {{ background: {side}; border: none; padding: 14px 10px; outline: none; }}
        QListWidget#side::item {{ border-radius: 8px; padding: 2px 6px; margin: 1px 0; }}
        QListWidget#side::item:selected {{ background: {acc}; color: white; }}
        QListWidget#side::item:hover:!selected {{ background: {line}; }}
        QScrollArea {{ border: none; }}
        QFrame#card {{ background: {card}; border-radius: 12px; }}
        QFrame#card QWidget {{ background: transparent; }}
        QFrame#sep {{ background: {line}; max-height: 1px; min-height: 1px; border: none; }}
        QLabel#h1 {{ font-size: 24px; font-weight: 700; background: transparent; }}
        QLabel#h2 {{ font-size: 12px; font-weight: 600; color: {fg2}; background: transparent;
                     padding: 10px 6px 4px 6px; }}
        QLabel#hint {{ color: {fg2}; font-size: 11.5px; }}
        QComboBox, QLineEdit {{ background: {bg}; border: 1px solid {line}; border-radius: 7px;
                     padding: 5px 9px; min-width: 150px; }}
        QComboBox::drop-down {{ border: none; width: 18px; }}
        QComboBox QAbstractItemView {{ background: {card}; selection-background-color: {acc};
                     border: 1px solid {line}; outline: none; }}
        QPushButton {{ background: {line}; border: none; border-radius: 7px; padding: 6px 14px; }}
        QPushButton:hover {{ background: {acc}; color: white; }}
        QPushButton#primary {{ background: {acc}; color: white; }}
        QSlider::groove:horizontal {{ height: 4px; background: {line}; border-radius: 2px; }}
        QSlider::sub-page:horizontal {{ background: {acc}; border-radius: 2px; }}
        QSlider::handle:horizontal {{ background: white; width: 18px; height: 18px; margin: -8px 0;
                     border-radius: 9px; border: 1px solid rgba(0,0,0,40); }}
        QListWidget#editor, QTableWidget {{ background: {bg}; border: 1px solid {line}; border-radius: 8px;
                     outline: none; gridline-color: {line}; }}
        QListWidget#editor::item {{ padding: 5px; border-radius: 6px; }}
        QListWidget#editor::item:selected, QTableWidget::item:selected {{ background: {acc}; color: white; }}
        QHeaderView::section {{ background: {card}; border: none; padding: 5px; color: {fg2}; }}
        QScrollBar:vertical {{ background: transparent; width: 10px; }}
        QScrollBar::handle:vertical {{ background: {line}; border-radius: 5px; min-height: 30px; }}
        QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
        """)

    def _scroll(self, inner):
        sa = QScrollArea()
        sa.setWidgetResizable(True)
        sa.setWidget(inner)
        return sa

    def _page(self, title):
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(30, 26, 30, 26)
        v.setSpacing(6)
        h = QLabel(title)
        h.setObjectName("h1")
        v.addWidget(h)
        return w, v

    def _card(self, v, title=None):
        if title:
            lab = QLabel(title.upper())
            lab.setObjectName("h2")
            v.addWidget(lab)
        card = QFrame()
        card.setObjectName("card")
        cv = QVBoxLayout(card)
        cv.setContentsMargins(16, 6, 16, 6)
        cv.setSpacing(0)
        v.addWidget(card)
        return cv

    def _row(self, cv, label, widget, hint=None):
        if cv.count():
            sep = QFrame()
            sep.setObjectName("sep")
            cv.addWidget(sep)
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 9, 0, 9)
        texts = QVBoxLayout()
        texts.setSpacing(1)
        texts.addWidget(QLabel(label))
        if hint:
            hl = QLabel(hint)
            hl.setObjectName("hint")
            hl.setWordWrap(True)
            texts.addWidget(hl)
        h.addLayout(texts, 1)
        h.addWidget(widget, 0, Qt.AlignRight | Qt.AlignVCenter)
        cv.addWidget(row)

    # ------------------------------------------------------------- controls
    def _bool(self, cv, sec, key, label, hint=None):
        sw = Switch(self.hub.palette.accent)
        sw.setChecked(bool(self.cfg.get(sec, key)))
        sw.toggled.connect(lambda val: self._set(sec, key, val))
        self._row(cv, label, sw, hint)
        return sw

    def _choice(self, cv, sec, key, label, options, hint=None):
        cb = QComboBox()
        cur = self.cfg.get(sec, key)
        for value, text in options:
            cb.addItem(text, value)
            if value == cur:
                cb.setCurrentIndex(cb.count() - 1)
        cb.currentIndexChanged.connect(lambda i: self._set(sec, key, cb.itemData(i)))
        self._row(cv, label, cb, hint)

    def _int(self, cv, sec, key, label, lo, hi, suffix="", hint=None, scale=1.0):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        s = QSlider(Qt.Horizontal)
        s.setFixedWidth(200)
        s.setRange(lo, hi)
        raw = self.cfg.get(sec, key)
        s.setValue(int(round(float(raw) * (100 if scale != 1.0 else 1))))
        val = QLabel()
        val.setFixedWidth(56)
        val.setAlignment(Qt.AlignRight | Qt.AlignVCenter)

        def show(v):
            val.setText(f"{v}{suffix}")

        def commit():
            v = s.value()
            self._set(sec, key, v / 100.0 if scale != 1.0 else v)

        show(s.value())
        s.valueChanged.connect(show)
        s.valueChanged.connect(lambda _v: None if s.isSliderDown() else commit())
        s.sliderReleased.connect(commit)
        h.addWidget(s)
        h.addWidget(val)
        self._row(cv, label, box, hint)

    def _text(self, cv, sec, key, label, hint=None):
        e = QLineEdit(str(self.cfg.get(sec, key) or ""))
        e.editingFinished.connect(lambda: self._set(sec, key, e.text().strip()))
        self._row(cv, label, e, hint)

    def _set(self, sec, key, value):
        if self._building:
            return
        self.cfg.set(sec, key, value)

    # ---------------------------------------------------------------- pages
    def _page_general(self):
        w, v = self._page("General")
        cv = self._card(v, "Appearance")
        self._choice(cv, "general", "theme", "Theme",
                     [("auto", "Follow system"), ("dark", "Dark"), ("light", "Light")])
        acc = QWidget()
        h = QHBoxLayout(acc)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        cur = str(self.cfg.get("general", "accent")).upper()
        for col in ACCENTS:
            sw = Swatch(col, col.upper() == cur)
            sw.clicked.connect(lambda _=False, c=col: self._set("general", "accent", c) or self._later_rebuild())
            h.addWidget(sw)
        more = QPushButton("…")
        more.setFixedWidth(34)
        more.clicked.connect(self._pick_accent)
        h.addWidget(more)
        self._row(cv, "Accent color", acc)
        self._int(cv, "general", "glass_opacity", "Glass tint", 15, 95, "%",
                  "Lower = more transparent (pure iOS glass), higher = easier to read", scale=100)
        self._bool(cv, "general", "real_blur", "Real background blur (experimental)",
                   "Uses the OS compositor blur for panels (Win 10/11 acrylic, Win 7 Aero, KDE)")
        self._bool(cv, "general", "animations", "Animations")
        cv = self._card(v, "Behaviour")
        self._bool(cv, "general", "hide_in_fullscreen", "Hide in fullscreen apps",
                   "Games and videos stay clean")
        self._bool(cv, "general", "autostart", "Start with system")
        self._bool(cv, "general", "low_memory", "Low memory mode",
                   "Give unused memory back to the system while idle (~8 MB instead of ~30 MB)")
        self._bool(cv, "general", "clock_24h", "24-hour clock")
        if IS_WIN:
            self._choice(cv, "taskbar", "mode", "Windows taskbar",
                         [("hide", "Hide (use Nocthify dock)"), ("keep", "Keep visible")],
                         "It always comes back when Nocthify quits")
        cv = self._card(v, "Keyboard shortcuts")
        self._text(cv, "general", "hotkey_launcher", "Open apps", "e.g. alt+shift+space")
        self._text(cv, "general", "hotkey_control_center", "Open Control Center", "e.g. alt+shift+c")
        if IS_WIN:
            self._bool(cv, "general", "win_key_launcher", "Windows key opens Nocthify Apps",
                       "Tap the Windows key alone to open Apps above the Dock. Win+E, Win+D… still work")
        v.addStretch(1)
        return w

    def _pick_accent(self):
        c = QColorDialog.getColor(QColor(self.cfg.get("general", "accent")), self, "Accent color")
        if c.isValid():
            self._set("general", "accent", c.name())
            self._later_rebuild()

    def _later_rebuild(self):
        QTimer.singleShot(50, self.rebuild)

    def _page_island(self):
        w, v = self._page("Dynamic Island")
        cv = self._card(v, "Look")
        self._bool(cv, "island", "enabled", "Show Dynamic Island")
        self._choice(cv, "island", "style", "Style",
                     [("island", "Floating island"), ("notch", "Notch (attached to top)")])
        self._choice(cv, "island", "material", "Material",
                     [("black", "Black (like iPhone)"), ("glass", "Glass (transparent)")])
        self._int(cv, "island", "top_offset", "Distance from top", 0, 40, " px")
        self._int(cv, "island", "compact_width", "Compact width", 140, 380, " px")
        self._int(cv, "island", "compact_height", "Compact height", 26, 48, " px")
        self._int(cv, "island", "expanded_width", "Expanded width", 360, 640, " px")
        cv = self._card(v, "Behaviour")
        self._bool(cv, "island", "expand_on_hover", "Expand on hover", "Otherwise click to expand")
        self._int(cv, "island", "hover_delay_ms", "Hover delay", 0, 1000, " ms")
        self._bool(cv, "island", "volume_hud", "Volume HUD", "Show volume changes in the island "
                   "(scroll on the island to change volume)")
        self._int(cv, "island", "timer_minutes", "Timer length", 1, 180, " min")
        cv = self._card(v, "Content")
        self._bool(cv, "island", "show_clock", "Clock")
        self._bool(cv, "island", "show_battery", "Battery")
        self._bool(cv, "island", "show_media", "Now playing", "Spotify, YouTube, VLC… (playerctl on Linux)")
        self._bool(cv, "island", "lyrics", "Lyrics",
                   "Hold the music to show time-synced lyrics. Song title & artist are looked up on lrclib.net")
        self._bool(cv, "island", "show_stats", "CPU & RAM rings")
        cv = self._card(v, "Shortcuts in the island (tick, then order)")
        cv.addWidget(self._shortcut_editor())
        v.addStretch(1)
        return w

    def _shortcut_editor(self):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 8, 0, 8)
        lst = QListWidget()
        lst.setObjectName("editor")
        lst.setFixedHeight(260)
        pal = self.hub.palette
        chosen = list(self.cfg.get("island", "shortcuts") or [])
        all_ids = chosen + [k for k in SHORTCUTS if k not in chosen]
        all_ids += [f"custom:{i}" for i in range(len(self.cfg.get("custom_shortcuts") or []))
                    if f"custom:{i}" not in all_ids]
        for sid in all_ids:
            meta = self.hub.shortcut_meta(sid)
            if not meta:
                continue
            it = QListWidgetItem(icons.icon(meta[1], pal.fg.name(), 18), meta[0])
            it.setData(Qt.UserRole, sid)
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            it.setCheckState(Qt.Checked if sid in chosen else Qt.Unchecked)
            lst.addItem(it)

        def save(*_):
            if self._building:
                return
            ids = [lst.item(i).data(Qt.UserRole) for i in range(lst.count())
                   if lst.item(i).checkState() == Qt.Checked]
            self.cfg.set("island", "shortcuts", ids)

        def move(d):
            r = lst.currentRow()
            if r < 0 or not 0 <= r + d < lst.count():
                return
            it = lst.takeItem(r)
            lst.insertItem(r + d, it)
            lst.setCurrentRow(r + d)
            save()

        lst.itemChanged.connect(save)
        btns = QVBoxLayout()
        for text, fn in (("Up", lambda: move(-1)), ("Down", lambda: move(1))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addWidget(lst, 1)
        lay.addLayout(btns)
        return box

    def _page_dock(self):
        w, v = self._page("Dock")
        cv = self._card(v, "Look")
        self._bool(cv, "dock", "enabled", "Show Dock")
        self._choice(cv, "dock", "position", "Position on screen",
                     [("bottom", "Bottom"), ("left", "Left"), ("right", "Right")])
        self._int(cv, "dock", "icon_size", "Icon size", 28, 96, " px")
        self._bool(cv, "dock", "magnification", "Magnification")
        self._int(cv, "dock", "magnify_size", "Magnified size", 32, 128, " px")
        self._int(cv, "dock", "edge_margin", "Distance from edge", 0, 40, " px")
        self._bool(cv, "dock", "show_labels", "Show app names on hover")
        self._bool(cv, "dock", "show_tray", "Status area",
                   "Clock, Wi-Fi, volume and battery at the end of the Dock")
        cv = self._card(v, "Behaviour")
        if IS_WIN:
            self._bool(cv, "dock", "genie", "Genie effect",
                       "Windows minimise into and restore out of their Dock icon (needs Animations on)")
        self._bool(cv, "dock", "autohide", "Automatically hide and show the Dock")
        self._bool(cv, "dock", "reserve_space", "Keep windows above the Dock",
                   "Maximised windows won't go under the Dock")
        self._bool(cv, "dock", "show_running", "Show running apps")
        self._bool(cv, "dock", "show_launcher", "Show Apps button")
        self._bool(cv, "dock", "show_trash", "Show Trash")
        cv = self._card(v, "Pinned apps  (tip: drag icons in the Dock to reorder, drag out to remove)")
        cv.addWidget(self._pinned_editor())
        v.addStretch(1)
        return w

    def _pinned_editor(self):
        box = QWidget()
        lay = QHBoxLayout(box)
        lay.setContentsMargins(0, 8, 0, 8)
        lst = QListWidget()
        lst.setObjectName("editor")
        lst.setFixedHeight(220)
        be = self.hub.backend

        def fill():
            lst.clear()
            for pin in self.cfg.get("dock", "pinned") or []:
                it = QListWidgetItem(pin.get("name") or pin.get("path"))
                pm = None
                try:
                    pm = be.app_icon(pin.get("match") if os.path.exists(pin.get("match", "")) else pin.get("path"), 32)
                except Exception:
                    pass
                if pm is not None:
                    from PyQt5.QtGui import QIcon
                    it.setIcon(QIcon(pm))
                it.setToolTip(pin.get("path", ""))
                lst.addItem(it)

        def add():
            if IS_WIN:
                flt = "Apps (*.exe *.lnk *.bat *.cmd);;All files (*)"
                start = os.path.join(os.environ.get("ProgramData", "C:\\ProgramData"),
                                     r"Microsoft\Windows\Start Menu\Programs")
            else:
                flt = "Applications (*.desktop);;All files (*)"
                start = "/usr/share/applications"
            path, _ = QFileDialog.getOpenFileName(self, "Choose an app", start, flt)
            if path:
                path = os.path.normpath(path)
                pins = list(self.cfg.get("dock", "pinned") or [])
                pins.append(be.resolve_pin(path))
                self.cfg.set("dock", "pinned", pins)
                fill()

        def remove():
            r = lst.currentRow()
            pins = list(self.cfg.get("dock", "pinned") or [])
            if 0 <= r < len(pins):
                pins.pop(r)
                self.cfg.set("dock", "pinned", pins)
                fill()

        def move(d):
            r = lst.currentRow()
            pins = list(self.cfg.get("dock", "pinned") or [])
            if 0 <= r < len(pins) and 0 <= r + d < len(pins):
                pins.insert(r + d, pins.pop(r))
                self.cfg.set("dock", "pinned", pins)
                fill()
                lst.setCurrentRow(r + d)

        fill()
        btns = QVBoxLayout()
        for text, fn in (("Add…", add), ("Remove", remove), ("Up", lambda: move(-1)), ("Down", lambda: move(1))):
            b = QPushButton(text)
            if text == "Add…":
                b.setObjectName("primary")
            b.clicked.connect(fn)
            btns.addWidget(b)
        btns.addStretch(1)
        lay.addWidget(lst, 1)
        lay.addLayout(btns)
        return box

    def _page_cc(self):
        w, v = self._page("Control Center")
        cv = self._card(v)
        self._choice(cv, "control_center", "position", "Open at",
                     [("right", "Top right (like macOS)"), ("center", "Under the island")])
        self._bool(cv, "control_center", "show_media", "Now playing card")
        self._bool(cv, "control_center", "show_stats", "CPU & RAM")
        hint = QLabel("Open it from the island, the Apps button, or the keyboard shortcut "
                      "(default Alt+Shift+C).")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        v.addStretch(1)
        return w

    def _page_shortcuts(self):
        w, v = self._page("Custom Shortcuts")
        hint = QLabel("Add your own buttons: any program, file, folder, website or command. "
                      "Then tick them under Dynamic Island → Shortcuts.")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        v.addWidget(hint)
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(["Name", "Command / path / URL"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        table.verticalHeader().setVisible(False)
        table.setMinimumHeight(300)
        for item in self.cfg.get("custom_shortcuts") or []:
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem(item.get("name", "")))
            table.setItem(r, 1, QTableWidgetItem(item.get("command", "")))

        def save(*_):
            if self._building:
                return
            out = []
            for r in range(table.rowCount()):
                n = table.item(r, 0).text().strip() if table.item(r, 0) else ""
                c = table.item(r, 1).text().strip() if table.item(r, 1) else ""
                if n or c:
                    out.append({"name": n or "Custom", "command": c, "glyph": "star"})
            self.cfg.set("custom_shortcuts", None, out)

        def add():
            r = table.rowCount()
            table.insertRow(r)
            table.setItem(r, 0, QTableWidgetItem("My shortcut"))
            table.setItem(r, 1, QTableWidgetItem("https://github.com"))
            save()

        def remove():
            r = table.currentRow()
            if r >= 0:
                table.removeRow(r)
                save()

        table.itemChanged.connect(save)
        v.addWidget(table)
        row = QHBoxLayout()
        b_add = QPushButton("Add shortcut")
        b_add.setObjectName("primary")
        b_add.clicked.connect(add)
        b_rm = QPushButton("Remove selected")
        b_rm.clicked.connect(remove)
        row.addWidget(b_add)
        row.addWidget(b_rm)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        return w

    def _page_about(self):
        w, v = self._page("About")
        cv = self._card(v)
        info = QLabel(f"<b>Nocthify</b> &nbsp;by erzak<br>Version {APP_VERSION}<br>"
                      "Dynamic Island, Control Center and Dock for Windows 7–11 and Linux.")
        info.setWordWrap(True)
        info.setContentsMargins(0, 10, 0, 10)
        cv.addWidget(info)
        cv = self._card(v, "Maintenance")
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 10, 0, 10)
        for text, fn in (("Open config folder", lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(config_dir()))),
                         ("Restore Windows taskbar" if IS_WIN else "Reload", self._restore_taskbar),
                         ("Reset all settings", self._reset),
                         ("Quit Nocthify", lambda: self.hub.do("quit"))):
            b = QPushButton(text)
            b.clicked.connect(fn)
            h.addWidget(b)
        h.addStretch(1)
        cv.addWidget(row)
        v.addStretch(1)
        return w

    def _restore_taskbar(self):
        if IS_WIN:
            self.cfg.set("taskbar", "mode", "keep")
            self.rebuild()

    def _reset(self):
        if QMessageBox.question(self, "Nocthify", "Reset every setting to its default?") == QMessageBox.Yes:
            self.cfg.reset()
            self.rebuild()

    def show_page(self, index=0):
        self.side.setCurrentRow(index)
        self.show()
        self.raise_()
        self.activateWindow()
