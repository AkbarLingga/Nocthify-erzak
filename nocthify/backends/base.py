"""Platform-independent backend interface + shared helpers."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys

try:
    import psutil
except ImportError:  # psutil is optional: stats simply disappear without it
    psutil = None


class WinInfo:
    __slots__ = ("id", "title", "app_id", "pid", "minimized", "exe")

    def __init__(self, wid, title, app_id, pid=0, minimized=False, exe=""):
        self.id = wid
        self.title = title
        self.app_id = app_id      # grouping key (normalised exe path / wm class)
        self.pid = pid
        self.minimized = minimized
        self.exe = exe

    def key(self):
        return (self.id, self.title, self.minimized)


class AppEntry:
    __slots__ = ("name", "path", "icon_hint", "keywords")

    def __init__(self, name, path, icon_hint="", keywords=""):
        self.name = name
        self.path = path
        self.icon_hint = icon_hint
        self.keywords = keywords


class Backend:
    name = "generic"
    supports_window_list = False
    supports_volume_poll = False
    supports_genie = False       # can snapshot windows + minimise without the OS animation

    # ---------------------------------------------------------- windows
    def list_windows(self) -> list:
        return []

    def foreground(self):
        return None

    def activate(self, wid):
        pass

    def minimize(self, wid):
        pass

    def close(self, wid):
        pass

    def is_fullscreen_foreground(self) -> bool:
        return False

    def is_minimized(self, wid) -> bool:
        return False

    def capture_window(self, wid):
        """(QImage, (l, t, r, b) physical px) of a visible window, or None."""
        return None

    def restore_animation(self, gen=None):
        pass

    def app_icon(self, app_id: str, size: int, wid=None):
        return None

    def file_icon(self, path: str, size: int = 48):
        return None

    def app_name(self, app_id: str) -> str:
        base = os.path.basename(app_id or "")
        name = os.path.splitext(base)[0]
        return name[:1].upper() + name[1:] if name else "App"

    def prepare_own_window(self, widget, no_activate: bool = True):
        pass

    def apply_blur(self, widget, radius: int, enable: bool, dark: bool):
        pass

    # ------------------------------------------------------------ apps
    def launch(self, target: str, args: str = "") -> bool:
        try:
            if os.path.exists(target):
                if args:
                    subprocess.Popen([target] + shlex.split(args), close_fds=True)
                else:
                    self._open_path(target)
            else:
                subprocess.Popen(target if sys.platform.startswith("win") else shlex.split(target),
                                 shell=sys.platform.startswith("win"), close_fds=True)
            return True
        except (OSError, ValueError):
            return False

    def _open_path(self, path: str):
        raise NotImplementedError

    def list_apps(self) -> list:
        return []

    def prefetch_apps(self):
        """Optionally warm slow parts of list_apps() in the background."""

    def default_pinned(self) -> list:
        return []

    def resolve_pin(self, path: str) -> dict:
        name = os.path.splitext(os.path.basename(path))[0]
        return {"name": name, "path": path, "match": os.path.normcase(path)}

    def open_trash(self):
        pass

    # ----------------------------------------------------- system info
    def battery(self):
        if psutil is None:
            return None
        try:
            b = psutil.sensors_battery()
        except Exception:
            return None
        if b is None:
            return None
        return int(round(b.percent)), bool(b.power_plugged)

    def cpu_ram(self):
        if psutil is None:
            return None
        try:
            return psutil.cpu_percent(interval=None), psutil.virtual_memory().percent
        except Exception:
            return None

    # ----------------------------------------------------- media/audio
    def get_volume(self):
        """Return (level 0..100, muted) or None."""
        return None

    def set_volume(self, level: int):
        pass

    def set_mute(self, mute: bool):
        pass

    def get_brightness(self):
        return None

    def set_brightness(self, level: int):
        pass

    def set_brightness_async(self, level: int):
        """Apply brightness off the UI thread; while one change is being applied only the
        newest requested level is kept, so dragging a slider never queues up a backlog."""
        import threading
        lock = self.__dict__.setdefault("_bright_lock", threading.Lock())
        with lock:
            self._bright_want = int(level)
            if getattr(self, "_bright_busy", False):
                return
            self._bright_busy = True

        def worker():
            while True:
                with lock:
                    level = self._bright_want
                    self._bright_want = None
                    if level is None:
                        self._bright_busy = False
                        return
                try:
                    self.set_brightness(level)
                except Exception:
                    pass
        threading.Thread(target=worker, name="nocthify-brightness", daemon=True).start()

    def media_info(self, windows: list):
        """Return dict(title, artist, source) or None."""
        return None

    def media(self, cmd: str):
        """cmd: play | next | prev"""
        pass

    def open_media(self, media: dict, windows: list) -> bool:
        """Bring the player of `media` to the front (app window or the browser tab's window)."""
        title = (media.get("title") or "").lower()
        wid = media.get("wid")
        target = None
        if wid is not None and any(w.id == wid for w in windows):
            target = wid
        else:
            for w in windows:
                if title and title in (w.title or "").lower():
                    target = w.id
                    break
        if target is not None:
            self.activate(target)
            return True
        return False

    # ---------------------------------------------------- quick actions
    def action(self, name: str) -> bool:
        return False

    def wifi_name(self):
        return None

    def network_state(self):
        """('wifi', ssid) | ('ethernet', '') | ('none', '')."""
        ssid = self.wifi_name()
        if ssid:
            return "wifi", ssid
        if psutil is not None:
            try:
                for name, st in psutil.net_if_stats().items():
                    if st.isup and not name.lower().startswith(("lo", "wl", "docker", "veth", "virbr", "br-", "tun", "tailscale")):
                        return "ethernet", ""
            except Exception:
                pass
        return "none", ""

    def is_dark_mode(self) -> bool:
        from ..theme import is_dark_system
        return is_dark_system()

    def set_dark_mode(self, dark: bool):
        pass

    # --------------------------------------------------------- shell
    def hide_taskbar(self):
        pass

    def restore_taskbar(self):
        pass

    def peek_taskbar(self):
        pass

    def tray_icons(self):
        """[{hwnd, uid, msg, tip, pixmap}] of notification-area icons, or None if unsupported."""
        return None

    def tray_click(self, icon, button="left"):
        pass

    def taskbar_rect(self):
        """Physical rect (l, t, r, b) of a visible native taskbar, else None."""
        return None

    def taskbar_watchdog(self):
        pass

    def reserve_edge(self, edge: str, thickness_px: int):
        pass

    def release_edge(self):
        pass

    def set_autostart(self, enabled: bool, command: str):
        pass

    def trim_memory(self):
        """Give freed heap memory back to the OS (Linux: glibc malloc_trim)."""
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except (OSError, AttributeError):
            pass
