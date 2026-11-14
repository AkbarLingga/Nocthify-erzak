"""Application bootstrap: wires config, backend, hub and all UI pieces together."""
from __future__ import annotations

import atexit
import logging
import os
import signal
import sys
import traceback

IS_WIN = sys.platform.startswith("win")
IS_LINUX = not IS_WIN

if IS_LINUX and os.environ.get("WAYLAND_DISPLAY") and not os.environ.get("QT_QPA_PLATFORM"):
    # Wayland forbids apps from placing their own windows; XWayland allows it.
    os.environ["QT_QPA_PLATFORM"] = "xcb"

from PyQt5.QtCore import QCoreApplication, QObject, Qt, QTimer, pyqtSignal  # noqa: E402
from PyQt5.QtGui import QPixmapCache  # noqa: E402
from PyQt5.QtNetwork import QLocalServer, QLocalSocket  # noqa: E402
from PyQt5.QtWidgets import QApplication, QMenu, QSystemTrayIcon, QWidget  # noqa: E402

from . import icons  # noqa: E402
from .config import APP_NAME, Config, config_dir  # noqa: E402
from .hub import Hub  # noqa: E402
from .backends import get_backend  # noqa: E402
from .theme import menu_stylesheet  # noqa: E402

SERVER_NAME = "nocthify-erzak-" + (os.environ.get("USERNAME") or os.environ.get("USER") or "user")
COMMANDS = {"--launcher": "launcher", "--control-center": "control_center", "--settings": "settings",
            "--quit": "quit", "--timer": "timer", "--show": "show"}

log = logging.getLogger("nocthify")


def _setup_logging():
    path = os.path.join(config_dir(), "nocthify.log")
    try:
        if os.path.exists(path) and os.path.getsize(path) > 512 * 1024:
            os.remove(path)
    except OSError:
        pass
    logging.basicConfig(filename=path, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")

    def hook(etype, value, tb):
        # Never let one bad paint/slot kill the whole shell: log and keep running.
        log.error("Unhandled error:\n%s", "".join(traceback.format_exception(etype, value, tb)))

    sys.excepthook = hook


class WinHotkeys(QWidget):
    """Global hotkeys through RegisterHotKey (works on Windows 7 → 11)."""

    MODS = {"alt": 0x1, "ctrl": 0x2, "control": 0x2, "shift": 0x4, "win": 0x8, "super": 0x8}
    KEYS = {"space": 0x20, "enter": 0x0D, "tab": 0x09, "esc": 0x1B, "home": 0x24, "end": 0x23,
            "`": 0xC0, "-": 0xBD, "=": 0xBB, ",": 0xBC, ".": 0xBE, "/": 0xBF, ";": 0xBA}

    def __init__(self, callback):
        super().__init__()
        import ctypes
        self.user32 = ctypes.windll.user32
        self.callback = callback
        self.ids = {}
        self.winId()

    def parse(self, combo: str):
        mods, vk = 0, None
        for part in (combo or "").lower().replace(" ", "").split("+"):
            if part in self.MODS:
                mods |= self.MODS[part]
            elif part in self.KEYS:
                vk = self.KEYS[part]
            elif len(part) == 1 and part.isalnum():
                vk = ord(part.upper())
            elif part.startswith("f") and part[1:].isdigit():
                vk = 0x6F + int(part[1:])
        return mods, vk

    def register(self, mapping: dict):
        hwnd = int(self.winId())
        for hid in list(self.ids):
            self.user32.UnregisterHotKey(hwnd, hid)
        self.ids.clear()
        failed = []
        for i, (name, combo) in enumerate(mapping.items(), start=1):
            mods, vk = self.parse(combo)
            if vk is None or not mods:
                continue
            if self.user32.RegisterHotKey(hwnd, i, mods | 0x4000, vk):
                self.ids[i] = name
            else:
                failed.append(combo)
                log.warning("Hotkey %s (%s) is already used by another app", combo, name)
        return failed

    def nativeEvent(self, event_type, message):
        try:
            import ctypes.wintypes as wt
            msg = wt.MSG.from_address(int(message))
            if msg.message == 0x0312:
                name = self.ids.get(int(msg.wParam))
                if name:
                    QTimer.singleShot(0, lambda: self.callback(name))
                return True, 0
        except Exception:
            pass
        return False, 0


class HookBridge(QObject):
    """Carries events from the hook thread to the UI thread."""
    event = pyqtSignal(str)


class NocthifyApp:
    def __init__(self, qapp: QApplication):
        self.qapp = qapp
        self.config = Config()
        self.backend = get_backend()
        self.hub = Hub(self.config, self.backend)
        self._restored = False
        self.launcher = None
        self.cc = None
        self.settings = None
        self.hotkeys = None
        self.hooks = None

        h = self.hub.handlers
        h["launcher"] = self.toggle_launcher
        h["control_center"] = self.toggle_cc
        h["settings"] = self.open_settings
        h["quit"] = self.quit
        h["show"] = self.show_all

        from .ui.dock import Dock
        from .ui.island import Island
        self.apply_taskbar_mode()
        self.dock = Dock(self.hub)
        self.hub.dock = self.dock
        self.hub.busy_checks.append(lambda: self.dock.mouse is not None or
                                    bool(self.dock._genie and self.dock._genie.isVisible()))
        self.island = Island(self.hub)
        self.hub.busy_checks.append(lambda: self.island.inside or self.island.mode != "compact")
        self._reap_launcher = QTimer(singleShot=True, timeout=self._drop_launcher)
        self._start_hooks()
        self._tray()
        self._hotkeys()
        self._autostart()
        self.config.changed.connect(self.on_config)
        self.qapp.setStyleSheet(menu_stylesheet(self.hub.palette))
        self.hub.theme_changed.connect(self._on_theme)
        QTimer.singleShot(1200, lambda: self.hub.notify("Nocthify is ready", "star", kind="system"))

    # ------------------------------------------------------------- pieces
    def _tray(self):
        self.tray = None
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.tray = QSystemTrayIcon(icons.icon("app", "#0A84FF", 32))
        self.tray.setToolTip("Nocthify")
        menu = QMenu()
        menu.addAction("Apps", self.toggle_launcher)
        menu.addAction("Control Center", self.toggle_cc)
        menu.addAction("Settings…", self.open_settings)
        menu.addSeparator()
        menu.addAction("Quit Nocthify", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.toggle_cc() if r == QSystemTrayIcon.Trigger else None)
        self._tray_menu = menu
        self.tray.show()

    def _hotkeys(self):
        if not IS_WIN:
            return
        if self.hotkeys is None:
            self.hotkeys = WinHotkeys(self.hub.do)
        g = self.config.get("general")
        if self.hooks is not None:
            self.hooks.win_key = bool(g.get("win_key_launcher", True))
        failed = self.hotkeys.register({"launcher": g.get("hotkey_launcher", ""),
                                        "control_center": g.get("hotkey_control_center", "")})
        if failed:
            QTimer.singleShot(4200, lambda: self.hub.notify(
                f"{failed[0]} is taken by another app. Change it in Settings", "keyboard", kind="system"))

    def _start_hooks(self):
        """Windows: let the OS tell us about window / taskbar / key changes (no busy polling)."""
        if not IS_WIN:
            return
        try:
            from .backends.win_hooks import HookThread
        except Exception:
            log.exception("hooks")
            return
        self._bridge = HookBridge()
        self._bridge.event.connect(self._on_hook)
        self.hooks = HookThread(self._bridge.event.emit)
        self.hooks.win_key = bool(self.config.get("general", "win_key_launcher"))
        self.hooks.start()
        self.hooks.ready.wait(2.0)
        self.hub.attach_hooks(self.hooks)

    def _on_hook(self, kind):
        if kind == "win_tap":
            self.hub.do("launcher")
        elif kind == "windows":
            self.hub.windows_dirty()
        elif kind == "names":
            self.hub.names_dirty()
        elif kind == "volume":
            self.hub.poll_volume_soon()
        elif kind == "media":
            if self.hub.media_watcher is not None:
                self.hub.media_watcher.poke()
        elif kind == "taskbar":
            self.backend.taskbar_watchdog()

    def _autostart(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        script = os.path.join(root, "run.pyw")
        exe = sys.executable
        if IS_WIN:
            pyw = os.path.join(os.path.dirname(exe), "pythonw.exe")
            cmd = f'"{pyw if os.path.exists(pyw) else exe}" "{script}"'
        else:
            cmd = f'"{exe}" "{script}"'
        try:
            self.backend.set_autostart(bool(self.config.get("general", "autostart")), cmd)
        except Exception:
            log.exception("autostart")

    def apply_taskbar_mode(self):
        if not IS_WIN:
            return
        if self.config.get("taskbar", "mode") == "hide" and self.config.get("dock", "enabled"):
            self.backend.hide_taskbar()
        else:
            self.backend.restore_taskbar()

    # ------------------------------------------------------------ reacting
    def on_config(self, section):
        if section in ("general", "*"):
            self.hub.refresh_palette()
            self._hotkeys()
            self._autostart()
        if section in ("taskbar", "dock", "*"):
            self.apply_taskbar_mode()
        if section in ("dock", "general", "taskbar", "*"):
            self.dock.reload()
        if section in ("island", "general", "custom_shortcuts", "*"):
            self.island.reload()

    def _on_theme(self):
        self.qapp.setStyleSheet(menu_stylesheet(self.hub.palette))
        self.dock.update()
        self.island.update()

    def toggle_launcher(self):
        self._reap_launcher.stop()
        if self.launcher is None:
            from .ui.launcher import Launcher
            self.launcher = Launcher(self.hub)
            self.launcher.closed.connect(self._launcher_closed)
        if self.cc is not None and self.cc.isVisible():
            self.cc.hide()
        self.launcher.toggle()

    def _launcher_closed(self):
        self.hub.schedule_trim()
        # the app grid holds ~100 icons: free it if Apps isn't reopened for a couple of minutes
        if self.config.get("general", "low_memory"):
            self._reap_launcher.start(120000)

    def _drop_launcher(self):
        if self.launcher is not None and not self.launcher.isVisible():
            self.launcher.deleteLater()
            self.launcher = None
            self.hub.schedule_trim(1500)

    def toggle_cc(self):
        if self.cc is None:
            from .ui.control_center import ControlCenter
            self.cc = ControlCenter(self.hub)
            self.cc.closed.connect(lambda: self.hub.schedule_trim())
        if self.launcher is not None and self.launcher.isVisible():
            self.launcher.hide()
        self.cc.toggle()

    def open_settings(self):
        if self.settings is None:
            from .ui.settings import SettingsWindow
            self.settings = SettingsWindow(self.hub, self)
            # Settings is big and rarely open: destroy it on close instead of keeping it around
            self.settings.setAttribute(Qt.WA_DeleteOnClose, True)
            self.settings.destroyed.connect(self._settings_gone)
        self.settings.show_page(self.settings.side.currentRow() if self.settings.isVisible() else 0)

    def _settings_gone(self, *_):
        self.settings = None
        self.hub.schedule_trim(1500)

    def show_all(self):
        self.config.set("island", "enabled", True, emit=False)
        self.config.set("dock", "enabled", True)

    def handle_command(self, cmd: str):
        if cmd in ("launcher", "control_center", "settings", "quit", "timer", "show"):
            self.hub.do(cmd)

    # ---------------------------------------------------------------- exit
    def restore(self):
        if self._restored:
            return
        self._restored = True
        try:
            if self.hooks is not None:
                self.hooks.stop()
            self.backend.restore_animation()
            self.backend.release_edge()
            if IS_WIN:
                self.backend.restore_taskbar()
        except Exception:
            log.exception("restore")

    def quit(self):
        self.restore()
        if self.tray:
            self.tray.hide()
        self.qapp.quit()


def _send_to_running(cmd: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SERVER_NAME)
    if not sock.waitForConnected(400):
        return False
    sock.write(cmd.encode())
    sock.flush()
    sock.waitForBytesWritten(400)
    sock.disconnectFromServer()
    return True


def main(argv=None):
    argv = list(sys.argv if argv is None else argv)
    if "--restore-taskbar" in argv:
        # Emergency switch: quit a running copy, bring the taskbar back and keep it.
        core = QCoreApplication(argv)  # noqa: F841 - Qt objects need an app instance
        _send_to_running("quit")
        cfg = Config()
        cfg.set("taskbar", None, {"mode": "keep"}, emit=False)
        cfg._write()
        if IS_WIN:
            get_backend().restore_taskbar()
        if sys.stdout is not None:  # pythonw has no console
            print("Windows taskbar restored. Nocthify will keep it visible from now on.")
        return 0

    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
    try:
        QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    except AttributeError:
        pass
    qapp = QApplication(argv)
    qapp.setApplicationName(APP_NAME)
    qapp.setQuitOnLastWindowClosed(False)
    QPixmapCache.setCacheLimit(2048)        # KB; Qt's default 10 MB is far more than we need
    _setup_logging()

    cmd = next((COMMANDS[a] for a in argv[1:] if a in COMMANDS), "show")
    if _send_to_running(cmd):
        return 0
    if cmd == "quit":
        return 0

    QLocalServer.removeServer(SERVER_NAME)
    server = QLocalServer()
    server.listen(SERVER_NAME)

    app = NocthifyApp(qapp)

    def on_conn():
        conn = server.nextPendingConnection()
        if conn is None:
            return

        def read():
            app.handle_command(bytes(conn.readAll()).decode(errors="ignore").strip())
        conn.readyRead.connect(read)

    server.newConnection.connect(on_conn)
    atexit.register(app.restore)
    qapp.aboutToQuit.connect(app.restore)
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, lambda *_: app.quit())
    # Let Python handle Ctrl+C / SIGTERM while Qt's loop is running
    tick = QTimer()
    tick.start(500)
    tick.timeout.connect(lambda: None)
    if cmd not in ("show",):
        QTimer.singleShot(400, lambda: app.handle_command(cmd))
    log.info("Nocthify started (%s)", app.backend.name)
    code = qapp.exec_()
    app.restore()
    return code
