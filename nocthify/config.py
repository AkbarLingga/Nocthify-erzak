"""Configuration store for Nocthify.

Settings live in a single JSON file:
  Windows: %APPDATA%\\Nocthify\\config.json
  Linux:   ~/.config/nocthify/config.json

Every change made from the Settings window is saved automatically and
applied live through the ``changed`` signal.  Hand edits to the JSON file
are picked up too (the file is watched).
"""
from __future__ import annotations

import copy
import json
import os
import sys

from PyQt5.QtCore import QFileSystemWatcher, QObject, QTimer, pyqtSignal

APP_NAME = "Nocthify"
APP_VERSION = "1.0.0"
IS_WINDOWS = sys.platform.startswith("win")


def config_dir() -> str:
    override = os.environ.get("NOCTHIFY_CONFIG_DIR")
    if override:
        os.makedirs(override, exist_ok=True)
        return override
    if IS_WINDOWS:
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
        path = os.path.join(base, APP_NAME)
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
        path = os.path.join(base, "nocthify")
    os.makedirs(path, exist_ok=True)
    return path


DEFAULTS = {
    "general": {
        "theme": "auto",            # auto | dark | light
        "accent": "#0A84FF",
        "glass_opacity": 0.62,      # 0.15 (very clear) .. 0.95 (almost solid)
        "real_blur": False,         # OS blur behind panels (Win10/11, KDE) - experimental
        "animations": True,
        "hide_in_fullscreen": True,
        "autostart": True,
        "do_not_disturb": False,
        "clock_24h": True,
        "hotkey_launcher": "alt+shift+space",
        "hotkey_control_center": "alt+shift+c",
        "win_key_launcher": True,   # Windows key opens Nocthify Apps instead of the Start menu
    },
    "island": {
        "enabled": True,
        "style": "island",          # island (floating pill) | notch (attached to top edge)
        "material": "black",        # black (true Dynamic Island) | glass
        "top_offset": 6,
        "compact_width": 200,
        "compact_height": 34,
        "expanded_width": 460,
        "expand_on_hover": True,
        "hover_delay_ms": 160,
        "show_clock": True,
        "show_battery": True,
        "show_media": True,
        "show_stats": True,
        "volume_hud": True,
        "timer_minutes": 5,
        "shortcuts": ["files", "browser", "terminal", "screenshot",
                      "calculator", "timer", "launcher", "control_center"],
    },
    "dock": {
        "enabled": True,
        "position": "bottom",       # bottom | left | right
        "icon_size": 48,
        "magnification": True,
        "magnify_size": 74,
        "autohide": False,
        "reserve_space": True,      # keep maximized windows above the dock
        "edge_margin": 8,
        "show_running": True,
        "show_launcher": True,
        "show_trash": True,
        "show_labels": True,
        "show_tray": True,          # clock, Wi-Fi, volume and battery at the end of the dock
        "genie": True,              # macOS genie effect when minimising / restoring from the dock
        "pinned": [],               # [{"name": str, "path": str, "match": str}]
        "pinned_initialized": False,
    },
    "taskbar": {
        "mode": "hide",             # hide | keep   (native Windows taskbar)
    },
    "control_center": {
        "position": "right",        # right | center
        "show_media": True,
        "show_stats": True,
    },
    "custom_shortcuts": [],         # [{"name": str, "command": str}]
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


class Config(QObject):
    """Tiny observable settings store."""

    changed = pyqtSignal(str)  # section name ("*" = everything)

    def __init__(self, path: str | None = None):
        super().__init__()
        self.path = path or os.path.join(config_dir(), "config.json")
        self.data = copy.deepcopy(DEFAULTS)
        self._saving = False
        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self._write)
        self.load()
        self._watcher = QFileSystemWatcher(self)
        if os.path.exists(self.path):
            self._watcher.addPath(self.path)
        self._watcher.fileChanged.connect(self._on_file_changed)

    # ----------------------------------------------------------------- io
    def load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                user = json.load(fh)
            self.data = _merge(DEFAULTS, user)
        except FileNotFoundError:
            self.data = copy.deepcopy(DEFAULTS)
            self._write()
        except (ValueError, OSError):
            # Broken JSON: keep defaults, never crash on a bad hand edit.
            self.data = copy.deepcopy(DEFAULTS)

    def _write(self):
        self._saving = True
        tmp = self.path + ".tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass
        QTimer.singleShot(300, self._done_saving)

    def _done_saving(self):
        self._saving = False
        if self.path not in self._watcher.files() and os.path.exists(self.path):
            self._watcher.addPath(self.path)

    def _on_file_changed(self, _path):
        if self._saving:
            return
        QTimer.singleShot(150, self._reload_from_disk)

    def _reload_from_disk(self):
        self.load()
        if os.path.exists(self.path) and self.path not in self._watcher.files():
            self._watcher.addPath(self.path)
        self.changed.emit("*")

    # ------------------------------------------------------------- access
    def get(self, section: str, key: str | None = None, default=None):
        sec = self.data.get(section, {})
        if key is None:
            return sec
        if isinstance(sec, dict):
            return sec.get(key, DEFAULTS.get(section, {}).get(key, default))
        return default

    def set(self, section: str, key: str | None, value, emit: bool = True):
        if key is None:
            self.data[section] = value
        else:
            self.data.setdefault(section, {})[key] = value
        self._save_timer.start()
        if emit:
            self.changed.emit(section)

    def reset(self):
        self.data = copy.deepcopy(DEFAULTS)
        self._write()
        self.changed.emit("*")
