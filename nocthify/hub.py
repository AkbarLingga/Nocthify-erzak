"""Hub: one shared place that polls the system *cheaply* and broadcasts changes.

Every UI piece listens to these signals instead of polling on its own, so
there is only one set of timers for the whole app.  Expensive things (CPU
stats, Wi-Fi name, brightness) are only fetched while a panel that shows
them is open.
"""
from __future__ import annotations

import threading
import time

from PyQt5.QtCore import QObject, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication

from .theme import Palette, is_dark_system

SHORTCUTS = {
    "files": ("Files", "folder"),
    "browser": ("Browser", "globe"),
    "terminal": ("Terminal", "terminal"),
    "screenshot": ("Screenshot", "camera"),
    "calculator": ("Calculator", "calculator"),
    "timer": ("Timer", "timer"),
    "launcher": ("Apps", "grid"),
    "control_center": ("Control Center", "sliders"),
    "settings": ("Nocthify Settings", "settings"),
    "system_settings": ("System Settings", "monitor"),
    "task_manager": ("Task Manager", "tasks"),
    "lock": ("Lock", "lock"),
    "sleep": ("Sleep", "sleep"),
    "dark_mode": ("Dark Mode", "contrast"),
    "dnd": ("Do Not Disturb", "moon"),
    "taskbar": ("Show System Tray", "taskbar"),
}


class Hub(QObject):
    windows_changed = pyqtSignal(list)
    media_changed = pyqtSignal(object)
    volume_changed = pyqtSignal(int, bool)
    battery_changed = pyqtSignal(object)
    stats_changed = pyqtSignal(float, float)
    theme_changed = pyqtSignal()
    fullscreen_changed = pyqtSignal(bool)
    activity = pyqtSignal(dict)
    timer_tick = pyqtSignal(object)      # remaining seconds or None
    network_changed = pyqtSignal(object)  # ("wifi", ssid) | ("ethernet", "") | ("none", "")
    _async_done = pyqtSignal(object, object)

    def __init__(self, config, backend):
        super().__init__()
        self.config = config
        self.backend = backend
        self.windows = []
        self.media = None
        self.volume = None
        self.battery = None
        self.stats = (0.0, 0.0)
        self.fullscreen = False
        self.network = None
        self.dock = None                     # set by the app; popups anchor to it
        self.timer_end = None
        self.cc_open = False
        self.handlers = {}
        self._win_sig = None
        self._stats_users = 0
        self._low_warned = False
        self._dark = None
        self.palette = None
        self._async_done.connect(lambda cb, res: cb(res) if cb else None)
        self.refresh_palette(emit=False)

        linux = backend.name == "linux"
        self._t_windows = self._timer(1500 if linux else 1000, self._poll_windows)
        self._t_media = self._timer(3000, self._poll_media) if linux else None
        self._t_volume = self._timer(450, self._poll_volume) if backend.supports_volume_poll else None
        self._t_battery = self._timer(15000, self._poll_battery)
        self._t_stats = QTimer(self, interval=2000)
        self._t_stats.timeout.connect(self._poll_stats)
        self._t_theme = self._timer(8000, self._poll_theme)
        self._t_network = self._timer(15000, self.poll_network)
        self._t_timer = QTimer(self, interval=1000)
        self._t_timer.timeout.connect(self._tick_timer)
        self._t_watchdog = self._timer(500 if backend.name == "windows" else 5000,
                                       backend.taskbar_watchdog)
        QTimer.singleShot(0, self._initial)

    def _timer(self, ms, fn):
        t = QTimer(self, interval=ms)
        t.timeout.connect(fn)
        t.start()
        return t

    def _initial(self):
        self._poll_windows()
        self.poll_network()
        self._poll_battery()
        if self._t_volume:
            v = self.backend.get_volume()
            if v:
                self.volume = v
                self.volume_changed.emit(*v)
        if self._t_media:
            self._poll_media()

    # ---------------------------------------------------------------- utils
    def run_async(self, fn, callback=None):
        def worker():
            try:
                res = fn()
            except Exception:
                res = None
            self._async_done.emit(callback, res)
        threading.Thread(target=worker, daemon=True).start()

    def refresh_palette(self, emit=True):
        g = self.config.get("general")
        theme = g.get("theme", "auto")
        dark = is_dark_system() if theme == "auto" else theme == "dark"
        self._dark = dark
        self.palette = Palette(dark, g.get("accent", "#0A84FF"), g.get("glass_opacity", 0.62))
        if emit:
            self.theme_changed.emit()

    def notify(self, text: str, glyph: str = "bell_off", color=None, kind="notice"):
        if self.config.get("general", "do_not_disturb") and kind == "notice":
            return
        self.activity.emit({"kind": kind, "text": text, "glyph": glyph, "color": color})

    # -------------------------------------------------------------- polling
    def _poll_windows(self):
        try:
            wins = self.backend.list_windows()
        except Exception:
            wins = []
        sig = tuple(w.key() for w in wins)
        if sig != self._win_sig:
            self._win_sig = sig
            self.windows = wins
            self.windows_changed.emit(wins)
            if not self._t_media:
                self._update_media(self.backend.media_info(wins))
        if self.config.get("general", "hide_in_fullscreen"):
            try:
                fs = self.backend.is_fullscreen_foreground()
            except Exception:
                fs = False
        else:
            fs = False
        if fs != self.fullscreen:
            self.fullscreen = fs
            self.fullscreen_changed.emit(fs)

    def _poll_media(self):
        self.run_async(lambda: self.backend.media_info(self.windows), self._update_media)

    def _update_media(self, info):
        if info != self.media:
            self.media = info
            self.media_changed.emit(info)

    def _poll_volume(self):
        v = self.backend.get_volume()
        if v is None or v == self.volume:
            return
        first = self.volume is None
        self.volume = v
        self.volume_changed.emit(*v)
        if not first and self.config.get("island", "volume_hud") and not self.cc_open:
            self.activity.emit({"kind": "volume", "value": v[0], "muted": v[1]})

    def _poll_battery(self):
        b = self.backend.battery()
        old = self.battery
        if b == old:
            return
        self.battery = b
        self.battery_changed.emit(b)
        if b is None or old is None:
            return
        pct, plugged = b
        if plugged and not old[1]:
            self.activity.emit({"kind": "charging", "value": pct})
        if not plugged and pct <= 15 and not self._low_warned:
            self._low_warned = True
            self.activity.emit({"kind": "lowbattery", "value": pct})
        if plugged or pct > 20:
            self._low_warned = False

    def poll_network(self):
        self.run_async(self.backend.network_state, self._set_network)

    def _set_network(self, state):
        if state and state != self.network:
            self.network = state
            self.network_changed.emit(state)

    def want_stats(self, on: bool):
        self._stats_users = max(0, self._stats_users + (1 if on else -1))
        if self._stats_users and not self._t_stats.isActive():
            self._poll_stats()
            self._t_stats.start()
        elif not self._stats_users:
            self._t_stats.stop()

    def _poll_stats(self):
        s = self.backend.cpu_ram()
        if s:
            self.stats = s
            self.stats_changed.emit(*s)

    def _poll_theme(self):
        if self.config.get("general", "theme") != "auto":
            return
        if is_dark_system() != self._dark:
            self.refresh_palette()

    # ---------------------------------------------------------------- timer
    def toggle_timer(self):
        if self.timer_end:
            self.timer_end = None
            self._t_timer.stop()
            self.timer_tick.emit(None)
            self.notify("Timer cancelled", "timer", kind="system")
            return
        minutes = max(1, int(self.config.get("island", "timer_minutes") or 5))
        self.timer_end = time.time() + minutes * 60
        self._t_timer.start()
        self._tick_timer()
        self.notify(f"Timer started  {minutes} min", "timer", kind="system")

    def _tick_timer(self):
        if not self.timer_end:
            return
        remaining = int(round(self.timer_end - time.time()))
        if remaining <= 0:
            self.timer_end = None
            self._t_timer.stop()
            self.timer_tick.emit(None)
            QApplication.beep()
            self.activity.emit({"kind": "timer_done", "text": "Time's up!", "glyph": "timer"})
            return
        self.timer_tick.emit(remaining)

    # -------------------------------------------------------------- actions
    def do(self, name: str):
        if name.startswith("custom:"):
            try:
                item = self.config.get("custom_shortcuts")[int(name.split(":", 1)[1])]
                self.backend.launch(item.get("command", ""))
            except (IndexError, ValueError, TypeError, AttributeError):
                pass
            return
        handler = self.handlers.get(name)
        if handler:
            handler()
            return
        if name == "timer":
            self.toggle_timer()
        elif name == "dark_mode":
            dark = not self.backend.is_dark_mode()
            self.backend.set_dark_mode(dark)
            QTimer.singleShot(600, self.refresh_palette)
            self.notify("Dark Mode " + ("On" if dark else "Off"), "contrast", kind="system")
        elif name == "dnd":
            on = not self.config.get("general", "do_not_disturb")
            self.config.set("general", "do_not_disturb", on)
            self.activity.emit({"kind": "system", "text": "Do Not Disturb " + ("On" if on else "Off"),
                                "glyph": "moon"})
        elif name == "taskbar":
            self.backend.peek_taskbar()
        else:
            self.backend.action(name)

    def shortcut_meta(self, sid: str):
        if sid.startswith("custom:"):
            try:
                item = self.config.get("custom_shortcuts")[int(sid.split(":", 1)[1])]
                return item.get("name", "Custom"), item.get("glyph", "star")
            except (IndexError, ValueError, TypeError, AttributeError):
                return None
        return SHORTCUTS.get(sid)
