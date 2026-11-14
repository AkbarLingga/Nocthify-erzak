"""Linux backend (GNOME, KDE, XFCE, Cinnamon, MATE, LXQt, i3 ...).

Uses only standard command line tools when they are present, so nothing
extra is loaded into memory:
  windows:     wmctrl (+ xprop)            audio:  pactl / amixer
  media:       playerctl                   light:  brightnessctl / /sys/class/backlight
Missing tools simply disable the matching feature instead of crashing.
"""
from __future__ import annotations

import configparser
import glob
import os
import shlex
import shutil
import subprocess

from PyQt5.QtGui import QIcon

from .base import AppEntry, Backend, WinInfo


def _run(args, timeout=2.0) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _spawn(args) -> bool:
    try:
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return True
    except OSError:
        return False


def _first(*cmds):
    for c in cmds:
        exe = c.split()[0]
        if shutil.which(exe):
            return c
    return None


class LinuxBackend(Backend):
    name = "linux"

    def __init__(self):
        self.has_wmctrl = bool(shutil.which("wmctrl"))
        self.has_xdotool = bool(shutil.which("xdotool"))
        self.has_xprop = bool(shutil.which("xprop"))
        self.supports_window_list = self.has_wmctrl
        self._own_pid = os.getpid()
        self._desktop_cache = None
        self._icon_cache = {}

    # ------------------------------------------------------------ windows
    def list_windows(self) -> list:
        if not self.has_wmctrl:
            return []
        out = _run(["wmctrl", "-lpx"])
        res = []
        for line in out.splitlines():
            parts = line.split(None, 5)
            if len(parts) < 5:
                continue
            wid, desk, pid, wmclass = parts[0], parts[1], parts[2], parts[3]
            title = parts[5] if len(parts) > 5 else ""
            if desk == "-1":           # sticky panels/docks/desktop
                continue
            try:
                pid_i = int(pid)
            except ValueError:
                pid_i = 0
            if pid_i == self._own_pid:
                continue
            cls = wmclass.split(".")[-1] if "." in wmclass else wmclass
            res.append(WinInfo(int(wid, 16), title, "wm:" + cls.lower(), pid_i, False, cls))
        return res

    def foreground(self):
        if not self.has_xprop:
            return None
        out = _run(["xprop", "-root", "_NET_ACTIVE_WINDOW"])
        try:
            return int(out.strip().split()[-1], 16)
        except (ValueError, IndexError):
            return None

    def activate(self, wid):
        if self.has_wmctrl:
            _spawn(["wmctrl", "-ia", hex(wid)])

    def minimize(self, wid):
        if self.has_xdotool:
            _spawn(["xdotool", "windowminimize", str(wid)])

    def close(self, wid):
        if self.has_wmctrl:
            _spawn(["wmctrl", "-ic", hex(wid)])

    def is_fullscreen_foreground(self) -> bool:
        wid = self.foreground()
        if not wid or not self.has_xprop:
            return False
        out = _run(["xprop", "-id", hex(wid), "_NET_WM_STATE"])
        return "_NET_WM_STATE_FULLSCREEN" in out

    # -------------------------------------------------------------- icons
    def _desktop_entries(self):
        if self._desktop_cache is not None:
            return self._desktop_cache
        dirs = [os.path.expanduser("~/.local/share/applications"), "/usr/share/applications",
                "/usr/local/share/applications", "/var/lib/flatpak/exports/share/applications",
                os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
                "/var/lib/snapd/desktop/applications"]
        entries, seen = [], set()
        for d in dirs:
            for path in glob.glob(os.path.join(d, "*.desktop")):
                base = os.path.basename(path)
                if base in seen:
                    continue
                seen.add(base)
                cp = configparser.RawConfigParser(strict=False, interpolation=None)
                try:
                    cp.read(path, encoding="utf-8")
                    sec = cp["Desktop Entry"]
                except Exception:
                    continue
                if sec.get("NoDisplay", "false").lower() == "true" or sec.get("Type", "Application") != "Application":
                    continue
                if sec.get("Hidden", "false").lower() == "true":
                    continue
                entries.append({
                    "file": path, "id": base[:-8].lower(), "name": sec.get("Name", base[:-8]),
                    "icon": sec.get("Icon", ""), "exec": sec.get("Exec", ""),
                    "wmclass": sec.get("StartupWMClass", "").lower(),
                    "keywords": sec.get("Keywords", "") + " " + sec.get("GenericName", ""),
                })
        self._desktop_cache = entries
        return entries

    def _entry_for(self, app_id: str):
        cls = app_id[3:] if app_id.startswith("wm:") else os.path.basename(app_id).lower()
        if app_id.endswith(".desktop"):
            for e in self._desktop_entries():
                if e["file"] == app_id:
                    return e
        for e in self._desktop_entries():
            if cls and (e["wmclass"] == cls or e["id"] == cls or e["id"].endswith("." + cls)):
                return e
        for e in self._desktop_entries():
            exe = os.path.basename(shlex.split(e["exec"])[0]) if e["exec"].strip() else ""
            if cls and exe.lower() == cls:
                return e
        return None

    def app_icon(self, app_id: str, size: int, wid=None):
        key = (app_id, size)
        if key in self._icon_cache:
            return self._icon_cache[key]
        icon = QIcon()
        e = self._entry_for(app_id)
        name = e["icon"] if e else (app_id[3:] if app_id.startswith("wm:") else app_id)
        if name and os.path.isabs(name) and os.path.exists(name):
            icon = QIcon(name)
        elif name:
            icon = QIcon.fromTheme(name)
            if icon.isNull():
                icon = QIcon.fromTheme(name.lower())
        pm = icon.pixmap(size, size) if not icon.isNull() else None
        self._icon_cache[key] = pm
        return pm

    def app_name(self, app_id: str) -> str:
        e = self._entry_for(app_id)
        if e:
            return e["name"]
        return super().app_name(app_id[3:] if app_id.startswith("wm:") else app_id)

    def prepare_own_window(self, widget, no_activate: bool = True):
        pass

    def apply_blur(self, widget, radius: int, enable: bool, dark: bool):
        # KDE Plasma honours this hint (compositor blur behind the window)
        if not shutil.which("xprop"):
            return
        wid = hex(int(widget.winId()))
        if enable:
            _spawn(["xprop", "-id", wid, "-f", "_KDE_NET_WM_BLUR_BEHIND_REGION", "32c",
                    "-set", "_KDE_NET_WM_BLUR_BEHIND_REGION", "0"])
        else:
            _spawn(["xprop", "-id", wid, "-remove", "_KDE_NET_WM_BLUR_BEHIND_REGION"])

    # --------------------------------------------------------------- apps
    def _open_path(self, path: str):
        if path.endswith(".desktop"):
            if shutil.which("gtk-launch"):
                _spawn(["gtk-launch", os.path.basename(path)])
                return
            e = self._entry_for(path)
            if e:
                cmd = [a for a in shlex.split(e["exec"]) if not a.startswith("%")]
                _spawn(cmd)
                return
        if os.access(path, os.X_OK) and not os.path.isdir(path):
            _spawn([path])
        else:
            _spawn(["xdg-open", path])

    def launch(self, target: str, args: str = "") -> bool:
        if os.path.exists(target) and not args:
            self._open_path(target)
            return True
        try:
            return _spawn(shlex.split(target) + (shlex.split(args) if args else []))
        except ValueError:
            return False

    def list_apps(self) -> list:
        apps = [AppEntry(e["name"], e["file"], e["file"], e["keywords"]) for e in self._desktop_entries()]
        apps.sort(key=lambda a: a.name.lower())
        return apps

    def resolve_pin(self, path: str) -> dict:
        if path.endswith(".desktop"):
            e = self._entry_for(path)
            if e:
                match = "wm:" + (e["wmclass"] or os.path.basename(shlex.split(e["exec"])[0] if e["exec"] else e["id"]).lower())
                return {"name": e["name"], "path": path, "match": match}
        name = os.path.basename(path)
        return {"name": name, "path": path, "match": "wm:" + name.lower()}

    def default_pinned(self) -> list:
        wanted = ["org.gnome.nautilus", "nautilus", "org.kde.dolphin", "dolphin", "thunar", "nemo",
                  "pcmanfm", "firefox", "google-chrome", "chromium", "chromium-browser", "brave-browser",
                  "org.gnome.terminal", "gnome-terminal", "org.kde.konsole", "konsole",
                  "xfce4-terminal", "code", "spotify"]
        out, seen_names = [], set()
        entries = {e["id"]: e for e in self._desktop_entries()}
        for wid in wanted:
            e = entries.get(wid)
            if e and e["name"] not in seen_names:
                seen_names.add(e["name"])
                out.append(self.resolve_pin(e["file"]))
        return out[:6]

    def open_trash(self):
        _spawn(["xdg-open", "trash:///"]) or _spawn(["xdg-open", os.path.expanduser("~/.local/share/Trash/files")])

    # ---------------------------------------------------------- audio/media
    def get_volume(self):
        if shutil.which("pactl"):
            out = _run(["pactl", "get-sink-volume", "@DEFAULT_SINK@"])
            mute = _run(["pactl", "get-sink-mute", "@DEFAULT_SINK@"])
            try:
                pct = int(out.split("%")[0].split()[-1])
                return pct, "yes" in mute
            except (ValueError, IndexError):
                pass
        if shutil.which("amixer"):
            out = _run(["amixer", "get", "Master"])
            import re
            m = re.search(r"\[(\d+)%\].*?\[(on|off)\]", out)
            if m:
                return int(m.group(1)), m.group(2) == "off"
        return None

    def set_volume(self, level: int):
        level = max(0, min(100, int(level)))
        if shutil.which("pactl"):
            _spawn(["pactl", "set-sink-volume", "@DEFAULT_SINK@", f"{level}%"])
            if level > 0:
                _spawn(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "0"])
        elif shutil.which("amixer"):
            _spawn(["amixer", "-q", "set", "Master", f"{level}%", "unmute"])

    def set_mute(self, mute: bool):
        if shutil.which("pactl"):
            _spawn(["pactl", "set-sink-mute", "@DEFAULT_SINK@", "1" if mute else "0"])
        elif shutil.which("amixer"):
            _spawn(["amixer", "-q", "set", "Master", "mute" if mute else "unmute"])

    def get_brightness(self):
        if shutil.which("brightnessctl"):
            out = _run(["brightnessctl", "-m"])
            try:
                return int(out.split(",")[3].rstrip("%"))
            except (IndexError, ValueError):
                pass
        for d in glob.glob("/sys/class/backlight/*"):
            try:
                cur = int(open(os.path.join(d, "brightness")).read())
                mx = int(open(os.path.join(d, "max_brightness")).read())
                return int(round(cur * 100 / max(1, mx)))
            except (OSError, ValueError):
                continue
        return None

    def set_brightness(self, level: int):
        level = max(1, min(100, int(level)))
        if shutil.which("brightnessctl"):
            _spawn(["brightnessctl", "-q", "set", f"{level}%"])
            return
        for d in glob.glob("/sys/class/backlight/*"):
            try:
                mx = int(open(os.path.join(d, "max_brightness")).read())
                with open(os.path.join(d, "brightness"), "w") as fh:
                    fh.write(str(int(mx * level / 100)))
                return
            except (OSError, ValueError):
                continue

    def media_info(self, windows: list):
        if not shutil.which("playerctl"):
            return None
        status = _run(["playerctl", "status"], 1).strip()
        if status not in ("Playing", "Paused"):
            return None
        meta = _run(["playerctl", "metadata", "--format", "{{title}}\t{{artist}}\t{{playerName}}"], 1)
        parts = meta.rstrip("\n").split("\t")
        if not parts or not parts[0]:
            return None
        while len(parts) < 3:
            parts.append("")
        return {"title": parts[0], "artist": parts[1], "source": parts[2].capitalize(),
                "playing": status == "Playing", "app_id": "wm:" + parts[2].lower()}

    def media(self, cmd: str):
        if shutil.which("playerctl"):
            _spawn(["playerctl", {"play": "play-pause", "next": "next", "prev": "previous"}.get(cmd, cmd)])

    # ---------------------------------------------------------- quick actions
    def action(self, name: str) -> bool:
        cmds = {
            "files": _first("xdg-open " + os.path.expanduser("~")),
            "browser": "xdg-open https://www.google.com",
            "terminal": _first("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal",
                               "tilix", "alacritty", "kitty", "xterm"),
            "screenshot": _first("flameshot gui", "spectacle -r", "gnome-screenshot -i",
                                 "xfce4-screenshooter", "scrot -s"),
            "calculator": _first("gnome-calculator", "kcalc", "galculator", "qalculate-gtk",
                                 "mate-calc", "xcalc"),
            "task_manager": _first("gnome-system-monitor", "plasma-systemmonitor", "ksysguard",
                                   "xfce4-taskmanager", "lxtask", "htop"),
            "lock": _first("loginctl lock-session", "xdg-screensaver lock", "dm-tool lock"),
            "sleep": "systemctl suspend",
            "shutdown": "systemctl poweroff",
            "restart": "systemctl reboot",
            "logout": _first("gnome-session-quit --logout --no-prompt", "qdbus org.kde.ksmserver "
                             "/KSMServer logout 0 0 0", "xfce4-session-logout --logout",
                             "loginctl terminate-user " + os.environ.get("USER", "")),
            "system_settings": _first("gnome-control-center", "systemsettings", "systemsettings5",
                                      "xfce4-settings-manager", "cinnamon-settings", "mate-control-center"),
            "wifi": _first("gnome-control-center wifi", "nm-connection-editor", "systemsettings kcm_networkmanagement"),
            "bluetooth": _first("gnome-control-center bluetooth", "blueman-manager", "systemsettings kcm_bluetooth"),
            "airplane": _first("gnome-control-center wifi", "nm-connection-editor"),
            "nightlight": _first("gnome-control-center display", "systemsettings kcm_nightcolor"),
            "display": _first("gnome-control-center display", "systemsettings kcm_kscreen", "arandr",
                              "xfce4-display-settings"),
            "sound": _first("gnome-control-center sound", "pavucontrol", "systemsettings kcm_pulseaudio"),
            "battery": _first("gnome-control-center power", "systemsettings kcm_powerdevilprofilesconfig",
                              "xfce4-power-manager-settings"),
            "notifications": _first("gnome-control-center notifications", "systemsettings kcm_notifications"),
            "project": _first("gnome-control-center display", "arandr"),
        }
        cmd = cmds.get(name)
        if not cmd:
            return False
        if name == "terminal" and cmd == "htop":
            cmd = "x-terminal-emulator -e htop"
        return _spawn(shlex.split(cmd))

    def wifi_name(self):
        if shutil.which("nmcli"):
            out = _run(["nmcli", "-t", "-f", "active,ssid", "dev", "wifi"])
            for line in out.splitlines():
                if line.startswith("yes:"):
                    return line[4:]
        if shutil.which("iwgetid"):
            return _run(["iwgetid", "-r"]).strip() or None
        return None

    def set_dark_mode(self, dark: bool):
        if shutil.which("gsettings"):
            _spawn(["gsettings", "set", "org.gnome.desktop.interface", "color-scheme",
                    "prefer-dark" if dark else "default"])
        if shutil.which("plasma-apply-colorscheme"):
            _spawn(["plasma-apply-colorscheme", "BreezeDark" if dark else "BreezeLight"])
        if shutil.which("xfconf-query"):
            _spawn(["xfconf-query", "-c", "xsettings", "-p", "/Net/ThemeName", "-s",
                    "Adwaita-dark" if dark else "Adwaita"])

    def set_autostart(self, enabled: bool, command: str):
        d = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "autostart")
        path = os.path.join(d, "nocthify.desktop")
        if not enabled:
            try:
                os.remove(path)
            except OSError:
                pass
            return
        os.makedirs(d, exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("[Desktop Entry]\nType=Application\nName=Nocthify\nComment=Dynamic Island & Dock\n"
                     f"Exec={command}\nX-GNOME-Autostart-enabled=true\nX-GNOME-Autostart-Delay=3\n"
                     "Terminal=false\n")
