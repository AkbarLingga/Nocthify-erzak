"""Hub: one shared place that polls the system *cheaply* and broadcasts changes.

Every UI piece listens to these signals instead of polling on its own, so
there is only one set of timers for the whole app.  Expensive things (CPU
stats, Wi-Fi name, brightness) are only fetched while a panel that shows
them is open.
"""
from __future__ import annotations

import os
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


BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
            "arc.exe", "zen.exe", "librewolf.exe", "waterfox.exe", "yandex.exe", "iexplore.exe"}


def song_key(media) -> str:
    return f"{(media or {}).get('artist', '')}|{(media or {}).get('title', '')}".lower()


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
    lyrics_ready = pyqtSignal(str, object)  # song key, lyrics result
    _media_raw = pyqtSignal(object)         # from the media watcher thread
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
        self.media_pos = None                # (position s, monotonic sampled, duration s, playing)
        self._media_title = None             # title-based detection (fallback)
        self._media_sys = None               # Windows media session info (preferred)
        self._exe_by_name = {}
        self._lyrics = None
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
        self._media_raw.connect(self._on_media_session)
        self.media_watcher = None        # started lazily: costs ~6 MB, only worth it once music plays
        self._watcher_tried = False
        self._t_trim = QTimer(self, singleShot=True, timeout=self._trim)
        self._t_trim_idle = self._timer(30000, lambda: self.schedule_trim(0))
        self._frozen = not hasattr(__import__("gc"), "freeze")   # gc.freeze: Python 3.7+
        self.busy_checks = []             # callables -> True while UI is animating / hovered
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
        self._t_fullscreen = self._timer(1500, self._check_fullscreen)
        self._t_dirty = QTimer(self, singleShot=True, interval=120, timeout=self._poll_windows)
        self._t_names = QTimer(self, singleShot=True, interval=2500, timeout=self._poll_windows)
        self.hooks = None
        QTimer.singleShot(0, self._initial)

    def _timer(self, ms, fn):
        t = QTimer(self, interval=ms)
        t.timeout.connect(fn)
        t.start()
        return t

    def _initial(self):
        self.schedule_trim(8000)
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
        if self.hooks is not None:
            self.hooks.known = {w.id for w in wins}
            self.hooks.pending = False
            self.hooks.names_pending = False
            self._t_names.stop()
        if sig != self._win_sig:
            self._win_sig = sig
            self.windows = wins
            self.windows_changed.emit(wins)
            if not self._t_media:
                self._media_title = self.backend.media_info(wins)
                self._merge_media()
        self._check_fullscreen()

    def _check_fullscreen(self):
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

    # ----------------------------------------------------------------- media
    def _update_media(self, info):
        """Linux / generic path: one dict, possibly with position & duration."""
        if info:
            info = dict(info)
            pos, dur = info.pop("position", None), info.pop("duration", None)
            if pos is not None:
                self.media_pos = (float(pos), time.monotonic(), float(dur or 0), info.get("playing", True))
        self._set_media(info)

    def _set_media(self, info):
        if info != self.media:
            self.media = info
            self.media_changed.emit(info)

    def _on_media_session(self, info):
        if info:
            self.media_pos = (info["position"], info["sampled"], info["duration"], info["playing"])
        self._media_sys = info
        self._merge_media()

    # ------------------------------------------------------- event-driven mode
    def attach_hooks(self, hooks):
        """Windows told us it will report changes: polls become slow safety nets."""
        self.hooks = hooks
        self._t_windows.setInterval(10000)
        self._t_watchdog.setInterval(3000)
        if self._t_volume:
            self._t_volume.setInterval(2500 if hooks.keyboard_ok else 450)

    def windows_dirty(self):
        if not self._t_dirty.isActive():
            self._t_dirty.start()

    def names_dirty(self):
        if not self._t_names.isActive() and not self._t_dirty.isActive():
            self._t_names.start()

    def poll_volume_soon(self):
        QTimer.singleShot(40, self._poll_volume)
        QTimer.singleShot(260, self._poll_volume)

    def ensure_media_watcher(self):
        """Start the Windows media-session reader (play/pause state, position for lyrics)."""
        if self._watcher_tried or self.backend.name != "windows":
            return
        self._watcher_tried = True
        try:
            from .backends.media_win import MediaWatcher
            watcher = MediaWatcher(self._media_raw.emit)
            if watcher.start():
                self.media_watcher = watcher
        except Exception:
            self.media_watcher = None

    # ---------------------------------------------------------------- memory
    def schedule_trim(self, delay_ms=3000):
        if self.config.get("general", "low_memory"):
            self._t_trim.start(delay_ms)

    def _trim(self):
        if any(check() for check in self.busy_checks):
            self._t_trim.start(4000)          # don't trim mid-animation; try again shortly
            return
        import gc
        gc.collect()
        if not self._frozen:
            # everything alive after start-up lives until exit: park it where the garbage
            # collector never walks it again, so its pages can stay out of RAM
            gc.freeze()
            self._frozen = True
        self.backend.trim_memory()

    def _merge_media(self):
        if self._media_title and not self._watcher_tried:
            self.ensure_media_watcher()
        sys_info = self._media_sys
        if not sys_info:
            self._set_media(self._media_title)
            return
        w = self._media_window(sys_info)
        aumid = sys_info["aumid"]
        exe = os.path.basename(w.exe) if w is not None and w.exe else aumid
        app_id = w.app_id if w is not None else self._exe_path(aumid)
        video = exe.lower() in BROWSERS
        source = "Spotify" if "spotify" in exe.lower() else self.backend.app_name(app_id or exe)
        self._set_media({"title": sys_info["title"], "artist": sys_info["artist"],
                         "album": sys_info["album"], "source": source, "app_id": app_id or "",
                         "exe": exe, "wid": w.id if w is not None else None,
                         "playing": sys_info["playing"], "video": video})

    def _media_window(self, info):
        aumid = info["aumid"].lower()
        stem = aumid[:-4] if aumid.endswith(".exe") else aumid
        title = info["title"].lower()
        by_exe = [w for w in self.windows if stem and stem in os.path.basename(w.exe or "").lower()]
        by_title = [w for w in self.windows if title and title in (w.title or "").lower()]
        for w in by_title:
            if not by_exe or w in by_exe:
                return w
        if by_exe:
            return by_exe[0]
        return by_title[0] if by_title else None

    def _exe_path(self, aumid):
        """'Spotify.exe' -> full path of the running process (for its icon), cached."""
        name = (aumid or "").lower()
        if not name.endswith(".exe"):
            return ""
        if name not in self._exe_by_name:
            path = ""
            try:
                import psutil
                for proc in psutil.process_iter(["name", "exe"]):
                    if (proc.info.get("name") or "").lower() == name and proc.info.get("exe"):
                        path = proc.info["exe"]
                        break
            except Exception:
                path = ""
            self._exe_by_name[name] = path
        return self._exe_by_name[name]

    def media_position(self):
        """Current playback position in seconds (extrapolated), or None."""
        mp = self.media_pos
        if not mp or not self.media:
            return None
        pos, at, dur, playing = mp
        if playing:
            pos += time.monotonic() - at
        return min(pos, dur) if dur else pos

    def media_duration(self):
        mp = self.media_pos
        return mp[2] if mp else 0.0

    def media_command(self, cmd):
        if self.media_watcher is not None and self.media_watcher.command(cmd):
            return
        self.backend.media(cmd)

    def open_media(self):
        """Bring up whatever is playing: the Spotify app, or the browser window with the song."""
        m = self.media
        if not m:
            return
        try:
            self.backend.open_media(m, self.windows)
        except Exception:
            pass

    def request_lyrics(self, media):
        """Fetch lyrics off-thread; answers through lyrics_ready(key, result)."""
        if not media:
            return
        key = song_key(media)
        if self._lyrics is None:
            from .config import config_dir
            from .lyrics import LyricsStore
            self._lyrics = LyricsStore(os.path.join(config_dir(), "lyrics"))
        store, dur = self._lyrics, self.media_duration()
        args = (media.get("title", ""), media.get("artist", ""), media.get("album", ""), dur,
                bool(media.get("video")))
        self.run_async(lambda: store.fetch(*args), lambda res: self.lyrics_ready.emit(key, res))

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
        elif name == "media_open":
            self.open_media()
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
