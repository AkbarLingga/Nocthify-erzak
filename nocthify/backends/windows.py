"""Windows backend (Windows 7, 8, 8.1, 10, 11) built on plain ctypes.

No pywin32 / comtypes required: everything is a direct Win32 / COM call,
which keeps the install tiny and the memory footprint low.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import winreg

from PyQt5.QtCore import QFileInfo

from PyQt5.QtWidgets import QFileIconProvider

from .base import AppEntry, Backend, WinInfo

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
shell32 = ctypes.WinDLL("shell32")
gdi32 = ctypes.WinDLL("gdi32")
try:
    dwmapi = ctypes.WinDLL("dwmapi")
except OSError:  # pragma: no cover - only on XP-class systems
    dwmapi = None

WINVER = sys.getwindowsversion()
IS_WIN7 = (WINVER.major, WINVER.minor) <= (6, 1)
IS_WIN10_PLUS = WINVER.major >= 10
IS_WIN11 = IS_WIN10_PLUS and WINVER.build >= 22000

CREATE_NO_WINDOW = 0x08000000
GWL_STYLE = -16
GWL_EXSTYLE = -20
GW_OWNER = 4
WS_CAPTION = 0x00C00000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOACTIVATE = 0x08000000
SW_HIDE, SW_SHOWNA, SW_SHOW, SW_MINIMIZE, SW_RESTORE = 0, 8, 5, 6, 9
WM_CLOSE = 0x0010
WM_GETICON = 0x007F
SMTO_ABORTIFHUNG = 0x0002
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ABM_GETSTATE, ABM_SETSTATE = 4, 10
ABS_AUTOHIDE, ABS_ALWAYSONTOP = 1, 2
SPI_GETWORKAREA, SPI_SETWORKAREA = 0x0030, 0x002F
SPIF_SENDCHANGE = 0x0002
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x1, 0x2
VK_MEDIA_NEXT, VK_MEDIA_PREV, VK_MEDIA_PLAY = 0xB0, 0xB1, 0xB3
VK_LWIN = 0x5B
_INJECT_MARK = 0x4E4F4354    # same tag as app.WinKeyHook.MARK

WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.EnumChildWindows.argtypes = [wt.HWND, WNDENUMPROC, wt.LPARAM]
user32.IsWindowVisible.argtypes = [wt.HWND]
user32.IsWindow.argtypes = [wt.HWND]
user32.IsIconic.argtypes = [wt.HWND]
user32.IsZoomed.argtypes = [wt.HWND]
user32.GetWindow.argtypes = [wt.HWND, wt.UINT]
user32.GetWindow.restype = wt.HWND
user32.GetWindowLongW.argtypes = [wt.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wt.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.GetWindowTextLengthW.argtypes = [wt.HWND]
user32.GetWindowTextW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wt.HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.GetForegroundWindow.restype = wt.HWND
user32.SetForegroundWindow.argtypes = [wt.HWND]
user32.BringWindowToTop.argtypes = [wt.HWND]
user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                       ctypes.POINTER(ctypes.c_size_t)]
user32.SendMessageTimeoutW.restype = ctypes.c_size_t
user32.FindWindowW.argtypes = [wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowW.restype = wt.HWND
user32.FindWindowExW.argtypes = [wt.HWND, wt.HWND, wt.LPCWSTR, wt.LPCWSTR]
user32.FindWindowExW.restype = wt.HWND
user32.GetWindowRect.argtypes = [wt.HWND, ctypes.POINTER(wt.RECT)]
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
user32.SystemParametersInfoW.argtypes = [wt.UINT, wt.UINT, ctypes.c_void_p, wt.UINT]
user32.MonitorFromWindow.argtypes = [wt.HWND, wt.DWORD]
user32.MonitorFromWindow.restype = wt.HANDLE
user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
user32.MonitorFromPoint.restype = wt.HANDLE
user32.DestroyIcon.argtypes = [wt.HICON]
user32.PrivateExtractIconsW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                        ctypes.POINTER(wt.HICON), ctypes.POINTER(wt.UINT),
                                        wt.UINT, wt.UINT]
user32.PrivateExtractIconsW.restype = wt.UINT
user32.SetWindowRgn.argtypes = [wt.HWND, wt.HANDLE, wt.BOOL]
try:
    user32.GetClassLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetClassLongPtrW.restype = ctypes.c_size_t
    _GetClassLongPtr = user32.GetClassLongPtrW
except AttributeError:  # 32-bit Python
    user32.GetClassLongW.argtypes = [wt.HWND, ctypes.c_int]
    user32.GetClassLongW.restype = ctypes.c_ulong
    _GetClassLongPtr = user32.GetClassLongW
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR,
                                                ctypes.POINTER(wt.DWORD)]
kernel32.GetCurrentThreadId.restype = wt.DWORD
kernel32.VirtualAllocEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD, wt.DWORD]
kernel32.VirtualAllocEx.restype = ctypes.c_void_p
kernel32.VirtualFreeEx.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wt.DWORD]
kernel32.ReadProcessMemory.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t,
                                       ctypes.c_void_p]
gdi32.CreateRoundRectRgn.argtypes = [ctypes.c_int] * 6
gdi32.CreateRoundRectRgn.restype = wt.HANDLE
user32.GetDC.argtypes = [wt.HWND]
user32.GetDC.restype = wt.HDC
user32.ReleaseDC.argtypes = [wt.HWND, wt.HDC]
user32.PrintWindow.argtypes = [wt.HWND, wt.HDC, wt.UINT]
gdi32.CreateCompatibleDC.argtypes = [wt.HDC]
gdi32.CreateCompatibleDC.restype = wt.HDC
gdi32.CreateCompatibleBitmap.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int]
gdi32.CreateCompatibleBitmap.restype = wt.HBITMAP
gdi32.SelectObject.argtypes = [wt.HDC, wt.HGDIOBJ]
gdi32.SelectObject.restype = wt.HGDIOBJ
gdi32.DeleteDC.argtypes = [wt.HDC]
gdi32.DeleteObject.argtypes = [wt.HGDIOBJ]
SPI_GETANIMATION, SPI_SETANIMATION = 0x0048, 0x0049


class ANIMATIONINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.UINT), ("iMinAnimate", ctypes.c_int)]



class APPBARDATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hWnd", wt.HWND), ("uCallbackMessage", wt.UINT),
                ("uEdge", wt.UINT), ("rc", wt.RECT), ("lParam", wt.LPARAM)]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT),
                ("dwFlags", wt.DWORD)]


user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]
shell32.SHGetFileInfoW.argtypes = [wt.LPCWSTR, wt.DWORD, ctypes.c_void_p, wt.UINT, wt.UINT]
shell32.SHGetFileInfoW.restype = ctypes.c_size_t
shell32.SHAppBarMessage.argtypes = [wt.DWORD, ctypes.POINTER(APPBARDATA)]
shell32.SHAppBarMessage.restype = ctypes.c_size_t

IGNORED_CLASSES = {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
                   "Windows.UI.Core.CoreWindow", "Button", "DV2ControlHost",
                   "MsgrIMEWindowClass", "SysShadow", "XamlExplorerHostIslandWindow"}
IGNORED_EXES = {"textinputhost.exe", "shellexperiencehost.exe", "searchui.exe",
                "searchapp.exe", "startmenuexperiencehost.exe", "lockapp.exe",
                "systemsettingsbroker.exe", "searchhost.exe"}


def _class_name(hwnd) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _title(hwnd) -> str:
    n = user32.GetWindowTextLengthW(hwnd)
    if n <= 0:
        return ""
    buf = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(hwnd, buf, n + 1)
    return buf.value


def _pid(hwnd) -> int:
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def _hidden_run(args, timeout=6):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              creationflags=CREATE_NO_WINDOW,
                              encoding="utf-8", errors="replace").stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _powershell(script: str, timeout=8) -> str:
    return _hidden_run(["powershell.exe", "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                        "Bypass", "-Command", script], timeout)


def _send_keys(*vks):
    # tagged so Nocthify's own Windows-key hook lets these through untouched
    for vk in vks:
        user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY, _INJECT_MARK)
    for vk in reversed(vks):
        user32.keybd_event(vk, 0, KEYEVENTF_EXTENDEDKEY | KEYEVENTF_KEYUP, _INJECT_MARK)


def _startfile(target: str) -> bool:
    try:
        os.startfile(target)
        return True
    except OSError:
        return False


# --------------------------------------------------------------------------
# Minimal COM access to the default audio endpoint (works on Vista..Win11)
# --------------------------------------------------------------------------
class _GUID(ctypes.Structure):
    _fields_ = [("Data1", wt.DWORD), ("Data2", wt.WORD), ("Data3", wt.WORD),
                ("Data4", ctypes.c_ubyte * 8)]


def _guid(text: str) -> _GUID:
    g = _GUID()
    ctypes.oledll.ole32.CLSIDFromString(ctypes.c_wchar_p(text), ctypes.byref(g))
    return g


def _vcall(ptr, index, argtypes, *args):
    vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
    proto = ctypes.WINFUNCTYPE(ctypes.HRESULT, ctypes.c_void_p, *argtypes)
    return proto(vtbl[index])(ptr, *args)


def _release(ptr):
    if ptr:
        vtbl = ctypes.cast(ctypes.c_void_p(ptr), ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(ptr)


class _Audio:
    def __init__(self):
        self.ok = False
        self.enum = None
        try:
            ctypes.oledll.ole32.CoInitialize(None)
        except OSError:
            pass  # already initialised by Qt (RPC_E_CHANGED_MODE etc.)
        try:
            self.CLSID = _guid("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
            self.IID_ENUM = _guid("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
            self.IID_VOL = _guid("{5CDF2C82-841E-4546-9722-0CF74078229A}")
            enum = ctypes.c_void_p()
            ctypes.oledll.ole32.CoCreateInstance(ctypes.byref(self.CLSID), None, 23,
                                                 ctypes.byref(self.IID_ENUM), ctypes.byref(enum))
            self.enum = enum.value
            self.ok = bool(self.enum)
        except OSError:
            self.ok = False

    def _endpoint(self):
        dev = ctypes.c_void_p()
        _vcall(self.enum, 4, (ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.c_void_p)),
               0, 1, ctypes.byref(dev))
        vol = ctypes.c_void_p()
        try:
            _vcall(dev.value, 3, (ctypes.POINTER(_GUID), wt.DWORD, ctypes.c_void_p,
                                  ctypes.POINTER(ctypes.c_void_p)),
                   ctypes.byref(self.IID_VOL), 23, None, ctypes.byref(vol))
        finally:
            _release(dev.value)
        return vol.value

    def get(self):
        if not self.ok:
            return None
        try:
            vol = self._endpoint()
        except OSError:
            return None
        try:
            level = ctypes.c_float()
            mute = wt.BOOL()
            _vcall(vol, 9, (ctypes.POINTER(ctypes.c_float),), ctypes.byref(level))
            _vcall(vol, 15, (ctypes.POINTER(wt.BOOL),), ctypes.byref(mute))
            return int(round(level.value * 100)), bool(mute.value)
        except OSError:
            return None
        finally:
            _release(vol)

    def set(self, level=None, mute=None):
        if not self.ok:
            return
        try:
            vol = self._endpoint()
        except OSError:
            return
        try:
            if level is not None:
                _vcall(vol, 7, (ctypes.c_float, ctypes.c_void_p),
                       max(0.0, min(1.0, level / 100.0)), None)
                if level > 0:
                    _vcall(vol, 14, (wt.BOOL, ctypes.c_void_p), False, None)
            if mute is not None:
                _vcall(vol, 14, (wt.BOOL, ctypes.c_void_p), bool(mute), None)
        except OSError:
            pass
        finally:
            _release(vol)


def _opaque_rect(img):
    """Bounding box of non-transparent pixels (coarse scan, fast enough for 256px)."""
    from PyQt5.QtCore import QRect
    w, h = img.width(), img.height()
    xs, ys = [], []
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            if (img.pixel(x, y) >> 24) & 0xFF > 16:
                xs.append(x)
                ys.append(y)
    if not xs:
        return None
    return QRect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)


# --------------------------------------------------------------------------
class WindowsBackend(Backend):
    name = "windows"
    supports_window_list = True
    supports_volume_poll = True
    supports_genie = True

    def __init__(self):
        self._exe_cache = {}
        self._icon_cache = {}
        self._imagelists = None
        self._audio = None
        self._own_pid = os.getpid()
        self._taskbar_hidden = False
        self._peek_until = 0.0
        self._reserved = None
        self._tray_hwnd = None
        self._anim_lock = threading.Lock()
        self._anim_saved = None
        self._anim_gen = 0
        from ..config import config_dir
        self._state_path = os.path.join(config_dir(), "taskbar_state.json")
        self._orig_workarea = self._load_state().get("workarea") or self._get_workarea()

    # ------------------------------------------------------------ windows
    def _exe_for(self, pid: int) -> str:
        exe = self._exe_cache.get(pid)
        if exe is not None:
            return exe
        exe = ""
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if h:
            try:
                size = wt.DWORD(1024)
                buf = ctypes.create_unicode_buffer(1024)
                if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    exe = buf.value
            finally:
                kernel32.CloseHandle(h)
        if len(self._exe_cache) > 400:
            self._exe_cache.clear()
        self._exe_cache[pid] = exe
        return exe

    @staticmethod
    def _cloaked(hwnd) -> bool:
        if dwmapi is None or IS_WIN7:
            return False
        val = ctypes.c_int(0)
        try:
            dwmapi.DwmGetWindowAttribute(wt.HWND(hwnd), 14, ctypes.byref(val), 4)
        except OSError:
            return False
        return val.value != 0

    def _uwp_exe(self, hwnd, host_pid) -> str:
        found = []

        def cb(child, _):
            if _class_name(child) == "Windows.UI.Core.CoreWindow":
                pid = _pid(child)
                if pid != host_pid:
                    found.append(self._exe_for(pid))
                    return False
            return True

        user32.EnumChildWindows(hwnd, WNDENUMPROC(cb), 0)
        return found[0] if found else ""

    def list_windows(self) -> list:
        out = []

        def cb(hwnd, _):
            try:
                if not user32.IsWindowVisible(hwnd) or user32.GetWindow(hwnd, GW_OWNER):
                    return True
                ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
                if (ex & WS_EX_TOOLWINDOW or ex & WS_EX_NOACTIVATE) and not ex & WS_EX_APPWINDOW:
                    return True
                title = _title(hwnd)
                if not title:
                    return True
                cls = _class_name(hwnd)
                if cls in IGNORED_CLASSES or self._cloaked(hwnd):
                    return True
                pid = _pid(hwnd)
                if pid == self._own_pid:
                    return True
                exe = self._exe_for(pid)
                base = os.path.basename(exe).lower()
                if base in IGNORED_EXES:
                    return True
                if base == "applicationframehost.exe":
                    exe = self._uwp_exe(hwnd, pid) or exe
                app_id = os.path.normcase(exe) if exe else "class:" + cls
                out.append(WinInfo(int(hwnd), title, app_id, pid, bool(user32.IsIconic(hwnd)), exe))
            except Exception:
                pass
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return out

    def foreground(self):
        h = user32.GetForegroundWindow()
        return int(h) if h else None

    def activate(self, wid, animate=True):
        hwnd = wt.HWND(wid)
        if user32.IsIconic(hwnd):
            if animate:
                user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                self._without_min_anim(lambda: user32.ShowWindow(hwnd, SW_RESTORE))
        fg = user32.GetForegroundWindow()
        cur = kernel32.GetCurrentThreadId()
        fg_thread = user32.GetWindowThreadProcessId(fg, None) if fg else 0
        attached = False
        if fg_thread and fg_thread != cur:
            attached = bool(user32.AttachThreadInput(fg_thread, cur, True))
        try:
            user32.BringWindowToTop(hwnd)
            ok = user32.SetForegroundWindow(hwnd)
        finally:
            if attached:
                user32.AttachThreadInput(fg_thread, cur, False)
        if not ok:
            # Foreground lock: a (tagged) Alt tap counts as user input and unlocks switching.
            user32.keybd_event(0x12, 0, 0, _INJECT_MARK)
            user32.keybd_event(0x12, 0, KEYEVENTF_KEYUP, _INJECT_MARK)
            ok = user32.SetForegroundWindow(hwnd)
        if not ok:
            try:
                user32.SwitchToThisWindow(hwnd, True)
            except Exception:
                pass

    def minimize(self, wid, animate=True):
        if animate:
            user32.ShowWindow(wt.HWND(wid), SW_MINIMIZE)
        else:
            self._without_min_anim(lambda: user32.ShowWindow(wt.HWND(wid), SW_MINIMIZE))

    # --- minimise/restore without the OS zoom animation (Nocthify draws its own genie).
    # The switch is in-memory only (no SPIF_UPDATEINIFILE) and is put back ~0.6 s later.
    def _without_min_anim(self, fn):
        with self._anim_lock:
            if self._anim_saved is None:
                ai = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), 0)
                user32.SystemParametersInfoW(SPI_GETANIMATION, ai.cbSize, ctypes.byref(ai), 0)
                self._anim_saved = ai.iMinAnimate
                if ai.iMinAnimate:
                    ai.iMinAnimate = 0
                    user32.SystemParametersInfoW(SPI_SETANIMATION, ai.cbSize, ctypes.byref(ai), 0)
            self._anim_gen += 1
            gen = self._anim_gen
        try:
            fn()
        finally:
            t = threading.Timer(0.6, self.restore_animation, (gen,))
            t.daemon = True
            t.start()

    def restore_animation(self, gen=None):
        with self._anim_lock:
            if gen is not None and gen != self._anim_gen:
                return
            if self._anim_saved:
                ai = ANIMATIONINFO(ctypes.sizeof(ANIMATIONINFO), self._anim_saved)
                user32.SystemParametersInfoW(SPI_SETANIMATION, ai.cbSize, ctypes.byref(ai), 0)
            self._anim_saved = None

    def is_minimized(self, wid) -> bool:
        return bool(user32.IsIconic(wt.HWND(wid)))

    def window_rect(self, wid):
        """Visible frame (l, t, r, b) in physical pixels, without the invisible resize borders."""
        hwnd = wt.HWND(wid)
        r = wt.RECT()
        if dwmapi is not None and not dwmapi.DwmGetWindowAttribute(hwnd, 9, ctypes.byref(r), ctypes.sizeof(r)):
            if r.right > r.left and r.bottom > r.top:
                return (r.left, r.top, r.right, r.bottom)
        if user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return (r.left, r.top, r.right, r.bottom)
        return None

    def capture_window(self, wid):
        """Snapshot of a visible window: (QImage, (l, t, r, b) physical) or None."""
        hwnd = wt.HWND(wid)
        if user32.IsIconic(hwnd) or not user32.IsWindowVisible(hwnd):
            return None
        wr = wt.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(wr)):
            return None
        frame = self.window_rect(wid) or (wr.left, wr.top, wr.right, wr.bottom)
        w, h = wr.right - wr.left, wr.bottom - wr.top
        if w <= 0 or h <= 0 or w * h > 8000 * 8000:
            return None
        screen_dc = user32.GetDC(None)
        mem = gdi32.CreateCompatibleDC(screen_dc)
        bmp = gdi32.CreateCompatibleBitmap(screen_dc, w, h)
        img = None
        try:
            old = gdi32.SelectObject(mem, bmp)
            flags = 2 if (WINVER.major, WINVER.minor) >= (6, 3) else 0   # PW_RENDERFULLCONTENT on 8.1+
            ok = user32.PrintWindow(hwnd, mem, flags)
            gdi32.SelectObject(mem, old)
            if ok:
                from PyQt5.QtWinExtras import QtWin
                img = QtWin.fromHBITMAP(bmp, QtWin.HBitmapNoAlpha).toImage()
        finally:
            gdi32.DeleteDC(mem)
            user32.ReleaseDC(None, screen_dc)
            gdi32.DeleteObject(bmp)
        if img is None or img.isNull():
            return None
        l, t, r, b = frame
        img = img.copy(max(0, l - wr.left), max(0, t - wr.top), r - l, b - t)
        # Some GPU-rendered windows come back completely black: treat that as "no snapshot".
        sx, sy = max(1, img.width() // 9), max(1, img.height() // 9)
        if all(img.pixel(x, y) & 0xFFFFFF == 0 for x in range(sx, img.width(), sx)
               for y in range(sy, img.height(), sy)):
            return None
        return img, frame

    def network_state(self):
        """('wifi', ssid) | ('ethernet', '') | ('none', '')."""
        ssid = self.wifi_name()
        if ssid:
            return "wifi", ssid
        flags = wt.DWORD()
        try:
            online = bool(ctypes.windll.wininet.InternetGetConnectedState(ctypes.byref(flags), 0))
        except (OSError, AttributeError):
            online = False
        return ("ethernet", "") if online else ("none", "")

    def close(self, wid):
        user32.PostMessageW(wt.HWND(wid), WM_CLOSE, 0, 0)

    def is_fullscreen_foreground(self) -> bool:
        fg = user32.GetForegroundWindow()
        if not fg:
            return False
        if _class_name(fg) in ("Progman", "WorkerW", "Shell_TrayWnd") or _pid(fg) == self._own_pid:
            return False
        if user32.IsZoomed(fg):
            return False
        rect = wt.RECT()
        user32.GetWindowRect(fg, ctypes.byref(rect))
        mon = user32.MonitorFromWindow(fg, 2)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        if not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
            return False
        m = mi.rcMonitor
        return (rect.left <= m.left and rect.top <= m.top and rect.right >= m.right
                and rect.bottom >= m.bottom)

    # ---------------------------------------------------------------- icons
    def _extract(self, path: str, size: int):
        hicon = wt.HICON()
        icon_id = wt.UINT()
        try:
            n = user32.PrivateExtractIconsW(path, 0, size, size, ctypes.byref(hicon),
                                            ctypes.byref(icon_id), 1, 0)
        except OSError:
            return None
        if not n or not hicon:
            return None
        try:
            from PyQt5.QtWinExtras import QtWin
            pm = QtWin.fromHICON(int(hicon.value) if not isinstance(hicon.value, int) else hicon.value)
            return pm if pm and not pm.isNull() else None
        except Exception:
            return None
        finally:
            user32.DestroyIcon(hicon)

    def _window_icon(self, wid):
        try:
            from PyQt5.QtWinExtras import QtWin
        except ImportError:
            return None
        res = ctypes.c_size_t(0)
        for which in (1, 2, 0):  # ICON_BIG, ICON_SMALL2, ICON_SMALL
            user32.SendMessageTimeoutW(wt.HWND(wid), WM_GETICON, which, 0, SMTO_ABORTIFHUNG, 60,
                                       ctypes.byref(res))
            if res.value:
                break
        h = res.value or _GetClassLongPtr(wt.HWND(wid), -14) or _GetClassLongPtr(wt.HWND(wid), -34)
        if not h:
            return None
        pm = QtWin.fromHICON(h)
        return pm if pm and not pm.isNull() else None

    def file_icon(self, path: str, size: int = 48):
        """Clean shell icon (no shortcut arrow) for any file/.lnk/folder, up to 256px."""
        class SHFILEINFOW(ctypes.Structure):
            _fields_ = [("hIcon", wt.HICON), ("iIcon", ctypes.c_int), ("dwAttributes", wt.DWORD),
                        ("szDisplayName", wt.WCHAR * 260), ("szTypeName", wt.WCHAR * 80)]
        try:
            from PyQt5.QtWinExtras import QtWin
            info = SHFILEINFOW()
            if not shell32.SHGetFileInfoW(path, 0, ctypes.byref(info), ctypes.sizeof(info), 0x4000):
                return None
            if self._imagelists is None:
                self._imagelists = {}
            which = 4 if size > 48 else 2           # SHIL_JUMBO (256) / SHIL_EXTRALARGE (48)
            il = self._imagelists.get(which)
            if il is None:
                iid = _guid("{46EB5926-582E-4017-9FDF-E8998DAA0950}")
                ptr = ctypes.c_void_p()
                shell32.SHGetImageList(which, ctypes.byref(iid), ctypes.byref(ptr))
                il = self._imagelists[which] = ptr.value
            if not il:
                return None
            hicon = wt.HICON()
            _vcall(il, 10, (ctypes.c_int, wt.UINT, ctypes.POINTER(wt.HICON)),
                   info.iIcon, 1, ctypes.byref(hicon))
            if not hicon.value:
                return None
            try:
                pm = QtWin.fromHICON(hicon.value)
            finally:
                user32.DestroyIcon(hicon)
            if pm.isNull():
                return None
            if which == 4:  # jumbo list pads small-only icons into a corner: crop to content
                img = pm.toImage()
                rect = _opaque_rect(img)
                if rect is not None and rect.width() < pm.width() * 0.5:
                    return self.file_icon(path, 48)
            return pm
        except Exception:
            return None

    def app_icon(self, app_id: str, size: int, wid=None):
        key = (app_id, size)
        if key in self._icon_cache:
            return self._icon_cache[key]
        pm = None
        path = app_id if app_id and not app_id.startswith("class:") else ""
        if path and path.lower().endswith(".exe") and os.path.isfile(path):
            # Ask for a generous size so HiDPI stays crisp
            pm = self._extract(path, max(size, 64) if size <= 64 else 128)
        if pm is None and wid:
            pm = self._window_icon(wid)
        if pm is None and path and os.path.exists(path):
            pm = self.file_icon(path, size)
        if pm is None and path and os.path.exists(path):
            ic = QFileIconProvider().icon(QFileInfo(path))
            pm = ic.pixmap(size, size) if not ic.isNull() else None
        if pm is not None and pm.isNull():
            pm = None
        if pm is not None or not wid:
            self._icon_cache[key] = pm
        return pm

    def app_name(self, app_id: str) -> str:
        friendly = {"explorer.exe": "File Explorer", "msedge.exe": "Microsoft Edge",
                    "chrome.exe": "Google Chrome", "firefox.exe": "Firefox", "code.exe": "VS Code",
                    "windowsterminal.exe": "Terminal", "notepad.exe": "Notepad",
                    "spotify.exe": "Spotify", "cmd.exe": "Command Prompt",
                    "powershell.exe": "PowerShell", "taskmgr.exe": "Task Manager",
                    "calculatorapp.exe": "Calculator", "systemsettings.exe": "Settings"}
        base = os.path.basename(app_id or "").lower()
        if base in friendly:
            return friendly[base]
        return super().app_name(app_id)

    def prepare_own_window(self, widget, no_activate: bool = True):
        hwnd = wt.HWND(int(widget.winId()))
        ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
        ex |= WS_EX_TOOLWINDOW
        if no_activate:
            ex |= WS_EX_NOACTIVATE
        ex &= ~WS_EX_APPWINDOW
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ex)

    def apply_blur(self, widget, radius: int, enable: bool, dark: bool):
        hwnd = int(widget.winId())
        dpr = widget.devicePixelRatioF()
        w, h = int(widget.width() * dpr), int(widget.height() * dpr)
        if not enable:
            user32.SetWindowRgn(wt.HWND(hwnd), None, True)
            if IS_WIN10_PLUS:
                self._accent(hwnd, 0, 0)
            return
        r = int(radius * 2 * dpr)
        rgn = gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r)
        user32.SetWindowRgn(wt.HWND(hwnd), rgn, True)
        if IS_WIN10_PLUS:
            tint = 0x55101014 if dark else 0x40F5F5F8  # AABBGGRR
            state = 4 if WINVER.build >= 17134 else 3   # acrylic needs 1803+
            self._accent(hwnd, state, tint)
        elif dwmapi is not None:
            class DWM_BLURBEHIND(ctypes.Structure):
                _fields_ = [("dwFlags", wt.DWORD), ("fEnable", wt.BOOL),
                            ("hRgnBlur", wt.HANDLE), ("fTransitionOnMaximized", wt.BOOL)]
            bb = DWM_BLURBEHIND(1 | 2, True, gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, r, r), False)
            try:
                dwmapi.DwmEnableBlurBehindWindow(wt.HWND(hwnd), ctypes.byref(bb))
            except OSError:
                pass

    @staticmethod
    def _accent(hwnd, state, color):
        class ACCENT(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_int), ("AccentFlags", ctypes.c_int),
                        ("GradientColor", ctypes.c_uint), ("AnimationId", ctypes.c_int)]

        class WCAD(ctypes.Structure):
            _fields_ = [("Attribute", ctypes.c_int), ("Data", ctypes.c_void_p),
                        ("SizeOfData", ctypes.c_size_t)]
        accent = ACCENT(state, 2, color, 0)
        data = WCAD(19, ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p), ctypes.sizeof(accent))
        try:
            user32.SetWindowCompositionAttribute(wt.HWND(hwnd), ctypes.byref(data))
        except (OSError, AttributeError):
            pass

    # ----------------------------------------------------------------- apps
    def _open_path(self, path: str):
        os.startfile(path)

    def launch(self, target: str, args: str = "") -> bool:
        if not args and (os.path.exists(target) or ":" in target[2:] or target.startswith("ms-")):
            return _startfile(target)
        try:
            subprocess.Popen(f'"{target}" {args}' if os.path.exists(target) else target,
                             shell=not os.path.exists(target), creationflags=CREATE_NO_WINDOW
                             if not os.path.exists(target) else 0, close_fds=True)
            return True
        except OSError:
            return False

    def list_apps(self) -> list:
        roots = [os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"),
                              r"Microsoft\Windows\Start Menu\Programs"),
                 os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs")]
        seen, apps = set(), []
        skip = ("uninstall", "readme", "help", "documentation", "website", "license", "release notes")
        for root in roots:
            for dirpath, _dirs, files in os.walk(root):
                for f in files:
                    if not f.lower().endswith((".lnk", ".url", ".appref-ms")):
                        continue
                    name = os.path.splitext(f)[0]
                    low = name.lower()
                    if any(s in low for s in skip) or low in seen:
                        continue
                    seen.add(low)
                    apps.append(AppEntry(name, os.path.join(dirpath, f)))
        extras = [("Settings", "ms-settings:" if IS_WIN10_PLUS else "control.exe", "settings"),
                  ("Calculator", "calc.exe", "calculator"),
                  ("Control Panel", "control.exe", "sliders"),
                  ("Task Manager", "taskmgr.exe", "tasks"),
                  ("This PC", "shell:MyComputerFolder", "folder"),
                  ("Recycle Bin", "shell:RecycleBinFolder", "trash")]
        for name, path, glyph in extras:
            if name.lower() not in seen:
                apps.append(AppEntry(name, path, "glyph:" + glyph))
        apps.sort(key=lambda a: a.name.lower())
        return apps

    def resolve_pin(self, path: str) -> dict:
        name = os.path.splitext(os.path.basename(path))[0]
        match = path
        if path.lower().endswith(".lnk"):
            safe = path.replace("'", "''")
            target = _powershell(f"(New-Object -ComObject WScript.Shell).CreateShortcut('{safe}')"
                                 ".TargetPath").strip()
            if target:
                match = target
        elif path.lower().endswith(".exe"):
            name = self.app_name(os.path.normcase(path))
        return {"name": name, "path": path, "match": os.path.normcase(match)}

    def default_pinned(self) -> list:
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        windir = os.environ.get("WINDIR", r"C:\Windows")
        candidates = [
            ("File Explorer", os.path.join(windir, "explorer.exe")),
            ("Google Chrome", os.path.join(pf, r"Google\Chrome\Application\chrome.exe")),
            ("Google Chrome", os.path.join(pf86, r"Google\Chrome\Application\chrome.exe")),
            ("Google Chrome", os.path.join(local, r"Google\Chrome\Application\chrome.exe")),
            ("Microsoft Edge", os.path.join(pf86, r"Microsoft\Edge\Application\msedge.exe")),
            ("Microsoft Edge", os.path.join(pf, r"Microsoft\Edge\Application\msedge.exe")),
            ("Firefox", os.path.join(pf, r"Mozilla Firefox\firefox.exe")),
            ("Firefox", os.path.join(pf86, r"Mozilla Firefox\firefox.exe")),
            ("VS Code", os.path.join(local, r"Programs\Microsoft VS Code\Code.exe")),
            ("Spotify", os.path.join(os.environ.get("APPDATA", ""), r"Spotify\Spotify.exe")),
            ("Notepad", os.path.join(windir, r"System32\notepad.exe")),
        ]
        out, names = [], set()
        for name, path in candidates:
            if name in names or not os.path.isfile(path):
                continue
            names.add(name)
            out.append({"name": name, "path": path, "match": os.path.normcase(path)})
        return out

    def open_trash(self):
        _startfile("shell:RecycleBinFolder")

    # ---------------------------------------------------------- audio/media
    def get_volume(self):
        if self._audio is None:
            self._audio = _Audio()
        return self._audio.get()

    def set_volume(self, level: int):
        if self._audio is None:
            self._audio = _Audio()
        self._audio.set(level=level)

    def set_mute(self, mute: bool):
        if self._audio is None:
            self._audio = _Audio()
        self._audio.set(mute=mute)

    def get_brightness(self):
        out = _powershell("(Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightness "
                          "-ErrorAction SilentlyContinue | Select-Object -First 1).CurrentBrightness")
        try:
            return int(out.strip().splitlines()[0])
        except (ValueError, IndexError):
            return None

    def set_brightness(self, level: int):
        level = max(0, min(100, int(level)))
        _powershell("$m = Get-WmiObject -Namespace root/WMI -Class WmiMonitorBrightnessMethods "
                    f"-ErrorAction SilentlyContinue; if ($m) {{ $m | ForEach-Object {{ "
                    f"$_.WmiSetBrightness(1, {level}) }} }}")

    _YT = re.compile(r"^(?:\(\d+\)\s*)?(.+?) - (YouTube Music|YouTube)\b")
    _BROWSERS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe", "vivaldi.exe",
                 "browser.exe", "iexplore.exe"}

    def media_info(self, windows: list):
        for w in windows:
            base = os.path.basename(w.exe or "").lower()
            t = w.title
            if base == "spotify.exe":
                if " - " in t and not t.lower().startswith("spotify"):
                    artist, song = t.split(" - ", 1)
                    return {"title": song, "artist": artist, "source": "Spotify", "app_id": w.app_id}
            elif base in self._BROWSERS:
                m = self._YT.match(t)
                if m:
                    return {"title": m.group(1), "artist": m.group(2), "source": m.group(2),
                            "app_id": w.app_id}
            elif base in ("vlc.exe", "foobar2000.exe", "musicbee.exe", "aimp.exe", "wmplayer.exe"):
                for suffix in (" - VLC media player", " - foobar2000", " - MusicBee", " - Windows Media Player"):
                    if t.endswith(suffix):
                        return {"title": t[: -len(suffix)], "artist": suffix[3:], "source": suffix[3:],
                                "app_id": w.app_id}
        return None

    def open_media(self, media: dict, windows: list) -> bool:
        if super().open_media(media, windows):
            return True
        exe = (media.get("exe") or "").lower()
        for w in windows:
            if exe and os.path.basename(w.exe or "").lower() == exe:
                self.activate(w.id)
                return True
        if "spotify" in exe or (media.get("source") or "").lower() == "spotify":
            return _startfile("spotify:")          # Spotify hidden in the tray: this brings it back
        app = media.get("app_id") or ""
        return self.launch(app) if app and os.path.isfile(app) else False

    def media(self, cmd: str):
        vk = {"play": VK_MEDIA_PLAY, "next": VK_MEDIA_NEXT, "prev": VK_MEDIA_PREV}.get(cmd)
        if vk:
            _send_keys(vk)

    # ---------------------------------------------------------- quick actions
    def action(self, name: str) -> bool:
        win = os.environ.get("WINDIR", r"C:\Windows")
        ms = IS_WIN10_PLUS
        if name == "files":
            return self.launch(os.path.join(win, "explorer.exe"))
        if name == "browser":
            return _startfile("https://www.google.com")
        if name == "terminal":
            if shutil.which("wt"):
                return self.launch("wt")
            return self.launch("powershell.exe" if shutil.which("powershell") else "cmd.exe")
        if name == "screenshot":
            if ms and _startfile("ms-screenclip:"):
                return True
            return self.launch(os.path.join(win, "System32", "SnippingTool.exe"))
        if name == "calculator":
            return self.launch("calc.exe")
        if name == "task_manager":
            return self.launch("taskmgr.exe")
        if name == "lock":
            return bool(user32.LockWorkStation())
        if name == "sleep":
            try:
                ctypes.WinDLL("powrprof").SetSuspendState(False, False, False)
                return True
            except OSError:
                return False
        if name == "shutdown":
            return self.launch("shutdown /s /t 0")
        if name == "restart":
            return self.launch("shutdown /r /t 0")
        if name == "logout":
            return self.launch("shutdown /l")
        pages = {
            "wifi": ("ms-settings:network-wifi", "control.exe ncpa.cpl"),
            "bluetooth": ("ms-settings:bluetooth", "control.exe bthprops.cpl"),
            "airplane": ("ms-settings:network-airplanemode", "control.exe ncpa.cpl"),
            "nightlight": ("ms-settings:nightlight", "control.exe desk.cpl"),
            "display": ("ms-settings:display", "control.exe desk.cpl"),
            "sound": ("ms-settings:sound", "control.exe mmsys.cpl"),
            "battery": ("ms-settings:batterysaver", "control.exe powercfg.cpl"),
            "system_settings": ("ms-settings:", "control.exe"),
            "notifications": ("ms-settings:notifications", "control.exe"),
        }
        if name in pages:
            modern, legacy = pages[name]
            if ms and _startfile(modern):
                return True
            return self.launch(legacy)
        if name == "project":
            _send_keys(VK_LWIN, ord("P"))
            return True
        if name == "start_menu":
            _send_keys(VK_LWIN)
            return True
        return False

    def wifi_name(self):
        out = _hidden_run(["netsh", "wlan", "show", "interfaces"], timeout=4)
        m = re.search(r"^\s*SSID\s*:\s*(.+)$", out, re.MULTILINE)
        return m.group(1).strip() if m else None

    def set_dark_mode(self, dark: bool):
        try:
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                                   r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            winreg.SetValueEx(key, "AppsUseLightTheme", 0, winreg.REG_DWORD, 0 if dark else 1)
            winreg.SetValueEx(key, "SystemUsesLightTheme", 0, winreg.REG_DWORD, 0 if dark else 1)
            winreg.CloseKey(key)
            res = ctypes.c_size_t(0)
            buf = ctypes.create_unicode_buffer("ImmersiveColorSet")
            user32.SendMessageTimeoutW(wt.HWND(0xFFFF), 0x001A, 0, ctypes.addressof(buf),
                                       SMTO_ABORTIFHUNG, 200, ctypes.byref(res))
        except OSError:
            pass

    # ------------------------------------------------------- native taskbar
    def _tray_windows(self):
        res = []
        main = user32.FindWindowW("Shell_TrayWnd", None)
        if main:
            res.append(main)
        h = None
        while True:
            h = user32.FindWindowExW(None, h, "Shell_SecondaryTrayWnd", None)
            if not h:
                break
            res.append(h)
        if main and IS_WIN7:  # the round Start orb is a separate top-level window
            tray_pid = _pid(main)
            h = None
            while True:
                h = user32.FindWindowExW(None, h, "Button", None)
                if not h:
                    break
                if _pid(h) == tray_pid:
                    res.append(h)
        return res

    def _appbar_state(self, main):
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        abd.hWnd = main
        return int(shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(abd)))

    def _set_appbar_state(self, main, state):
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        abd.hWnd = main
        abd.lParam = state
        shell32.SHAppBarMessage(ABM_SETSTATE, ctypes.byref(abd))

    def _load_state(self) -> dict:
        try:
            with open(self._state_path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _get_workarea(self):
        r = wt.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
        return [r.left, r.top, r.right, r.bottom]

    def _set_workarea(self, rect):
        r = wt.RECT(*rect)
        user32.SystemParametersInfoW(SPI_SETWORKAREA, 0, ctypes.byref(r), SPIF_SENDCHANGE)

    def _primary_monitor(self):
        mon = user32.MonitorFromPoint(wt.POINT(0, 0), 1)
        mi = MONITORINFO()
        mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(mon, ctypes.byref(mi))
        m = mi.rcMonitor
        return [m.left, m.top, m.right, m.bottom]

    def hide_taskbar(self):
        main = user32.FindWindowW("Shell_TrayWnd", None)
        if not main:
            return
        state = self._load_state()
        if not state:
            state = {"appbar": self._appbar_state(main), "workarea": self._orig_workarea}
            try:
                with open(self._state_path, "w", encoding="utf-8") as fh:
                    json.dump(state, fh)
            except OSError:
                pass
        self._set_appbar_state(main, ABS_AUTOHIDE | (state.get("appbar", 0) & ABS_ALWAYSONTOP))
        for h in self._tray_windows():
            user32.ShowWindow(h, SW_HIDE)
        self._tray_hwnd = int(main)
        self._taskbar_hidden = True

    def restore_taskbar(self):
        state = self._load_state()
        main = user32.FindWindowW("Shell_TrayWnd", None)
        if main:
            self._set_appbar_state(main, state.get("appbar", ABS_ALWAYSONTOP) if state else ABS_ALWAYSONTOP)
            for h in self._tray_windows():
                user32.ShowWindow(h, SW_SHOWNA)
        wa = (state or {}).get("workarea")
        if wa:
            self._set_workarea(wa)
        try:
            os.remove(self._state_path)
        except OSError:
            pass
        self._taskbar_hidden = False

    def taskbar_rect(self):
        if self._taskbar_hidden:
            return None
        main = user32.FindWindowW("Shell_TrayWnd", None)
        if not main or not user32.IsWindowVisible(main):
            return None
        if self._appbar_state(main) & ABS_AUTOHIDE:
            return None
        r = wt.RECT()
        user32.GetWindowRect(main, ctypes.byref(r))
        return (r.left, r.top, r.right, r.bottom)

    # ------------------------------------------------------- tray icons
    # The notification-area icons live in two toolbars owned by explorer.exe (the visible
    # strip and the "hidden icons" overflow).  Their button data points to explorer's
    # TRAYDATA {hwnd, uID, uCallbackMessage, ..., hIcon}, read here with ReadProcessMemory.
    # Win7 - Win10 (and Win11 before 22H2).  Returns None where that layout doesn't exist.
    def tray_icons(self):
        if ctypes.sizeof(ctypes.c_void_p) != 8:
            return None
        tray = user32.FindWindowW("Shell_TrayWnd", None)
        notify = user32.FindWindowExW(tray, None, "TrayNotifyWnd", None) if tray else None
        pager = user32.FindWindowExW(notify, None, "SysPager", None) if notify else None
        bars = []
        for parent in (pager, notify):
            tb = user32.FindWindowExW(parent, None, "ToolbarWindow32", None) if parent else None
            if tb:
                bars.append(tb)
                break
        overflow = user32.FindWindowW("NotifyIconOverflowWindow", None)
        tb = user32.FindWindowExW(overflow, None, "ToolbarWindow32", None) if overflow else None
        if tb:
            bars.append(tb)
        if not bars:
            return None
        explorer_pid = _pid(bars[0])
        hproc = kernel32.OpenProcess(0x0008 | 0x0010 | 0x0020 | 0x0400, False, explorer_pid)
        if not hproc:
            return None
        remote = kernel32.VirtualAllocEx(hproc, None, 4096, 0x3000, 0x04)
        out, seen = [], set()
        try:
            from PyQt5.QtWinExtras import QtWin

            def send(h, msg, wp, lp):
                r = ctypes.c_size_t(0)
                user32.SendMessageTimeoutW(h, msg, wp, lp, SMTO_ABORTIFHUNG, 250, ctypes.byref(r))
                return r.value

            def read(addr, n):
                buf = (ctypes.c_ubyte * n)()
                if not kernel32.ReadProcessMemory(hproc, addr, buf, n, None):
                    return None
                return bytes(buf)

            for tb in bars:
                for i in range(min(64, send(tb, 0x418, 0, 0))):          # TB_BUTTONCOUNT
                    if not send(tb, 0x417, i, remote):                   # TB_GETBUTTON
                        continue
                    btn = read(remote, 32)
                    if not btn or btn[8] & 0x08:                         # TBSTATE_HIDDEN
                        continue
                    cmd = int.from_bytes(btn[4:8], "little", signed=True)
                    td = read(int.from_bytes(btn[16:24], "little"), 32)
                    if not td:
                        continue
                    hwnd = int.from_bytes(td[0:8], "little")
                    uid = int.from_bytes(td[8:12], "little")
                    cbmsg = int.from_bytes(td[12:16], "little")
                    hicon = int.from_bytes(td[24:32], "little")
                    if not hwnd or not user32.IsWindow(wt.HWND(hwnd)) or (hwnd, uid) in seen:
                        continue
                    if _pid(wt.HWND(hwnd)) == explorer_pid:   # clock/volume/network: the dock has those
                        continue
                    seen.add((hwnd, uid))
                    tip = ""
                    n = send(tb, 0x44B, cmd, remote + 64)                # TB_GETBUTTONTEXTW
                    if 0 < n < 1000:
                        raw = read(remote + 64, (n + 1) * 2)
                        if raw:
                            tip = raw.decode("utf-16-le", "replace").split("\x00")[0]
                    pm = None
                    if hicon:
                        try:
                            pm = QtWin.fromHICON(hicon)
                        except Exception:
                            pm = None
                    if pm is None or pm.isNull():
                        # some apps' tray HICONs can't be copied across processes: use the exe icon
                        exe = self._exe_for(_pid(wt.HWND(hwnd)))
                        pm = self._extract(exe, 32) if exe else None
                    out.append({"hwnd": hwnd, "uid": uid, "msg": cbmsg, "tip": tip.strip(),
                                "pixmap": pm if pm is not None and not pm.isNull() else None})
        finally:
            kernel32.VirtualFreeEx(hproc, remote, 0, 0x8000)
            kernel32.CloseHandle(hproc)
        return out

    def _windows_of_pid(self, pid):
        found = set()

        def cb(h, _):
            if user32.IsWindowVisible(h) and _pid(h) == pid:
                found.add(int(h) if not isinstance(h, int) else h)
            return True
        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return found

    def tray_click(self, icon, button="left"):
        """Deliver a click to a tray icon the way explorer would (old + version-4 styles)."""
        hwnd, uid, msg = wt.HWND(icon["hwnd"]), icon["uid"], icon["msg"]
        if not user32.IsWindow(hwnd):
            return
        pid = _pid(hwnd)
        try:
            user32.AllowSetForegroundWindow(pid)
        except Exception:
            pass
        post = user32.PostMessageW
        if button == "right":
            before = self._windows_of_pid(pid)
            post(hwnd, msg, uid, 0x0204)            # WM_RBUTTONDOWN
            post(hwnd, msg, uid, 0x0205)            # WM_RBUTTONUP

            def fallback():
                # Version-4 icons only answer WM_CONTEXTMENU; send it only if no menu showed up,
                # so classic icons never get a second menu.
                time.sleep(0.35)
                if self._windows_of_pid(pid) - before:
                    return
                pt = wt.POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                post(hwnd, msg, (pt.x & 0xFFFF) | ((pt.y & 0xFFFF) << 16), 0x007B | (uid << 16))
            threading.Thread(target=fallback, daemon=True).start()
        else:
            post(hwnd, msg, uid, 0x0201)            # WM_LBUTTONDOWN
            post(hwnd, msg, uid, 0x0202)            # WM_LBUTTONUP
            if button == "double":
                post(hwnd, msg, uid, 0x0203)        # WM_LBUTTONDBLCLK
                post(hwnd, msg, uid, 0x0202)

    def peek_taskbar(self):
        main = user32.FindWindowW("Shell_TrayWnd", None)
        if not main:
            return
        self._peek_until = time.time() + 8
        for h in self._tray_windows():
            user32.ShowWindow(h, SW_SHOW)
        user32.SetForegroundWindow(main)

    def taskbar_watchdog(self):
        """Safety net (every 3 s, and right away when the taskbar fires a 'shown' event):
        cheap visibility check, heavier checks every other call."""
        self._wd_tick = getattr(self, "_wd_tick", 0) + 1
        heavy = self._wd_tick % 2 == 0
        main = None
        if self._taskbar_hidden and time.time() > self._peek_until:
            main = user32.FindWindowW("Shell_TrayWnd", None)
            if main and int(main) != self._tray_hwnd:  # explorer restarted
                self.hide_taskbar()
                if self._reserved:
                    self._appbar_registered = False
                    self._apply_appbar(force=True)
                return
            if main and user32.IsWindowVisible(main):
                for h in self._tray_windows():
                    user32.ShowWindow(h, SW_HIDE)
            elif heavy:
                for h in self._tray_windows():
                    if user32.IsWindowVisible(h):
                        user32.ShowWindow(h, SW_HIDE)
        if heavy and self._reserved:
            self._apply_appbar()

    # The dock reserves its screen edge as a real AppBar (the official Win32 way):
    # maximised windows stop above it, and Windows releases it automatically
    # if Nocthify ever crashes.
    _EDGES = {"left": 0, "top": 1, "right": 2, "bottom": 3}

    def _appbar_data(self):
        abd = APPBARDATA()
        abd.cbSize = ctypes.sizeof(APPBARDATA)
        abd.hWnd = self._appbar_hwnd
        abd.uCallbackMessage = 0x8000 + 77
        return abd

    def _apply_appbar(self, force=False):
        edge, thick = self._reserved
        if not getattr(self, "_appbar_registered", False):
            if getattr(self, "_appbar_widget", None) is None:
                from PyQt5.QtCore import Qt
                from PyQt5.QtWidgets import QWidget
                self._appbar_widget = QWidget(None, Qt.Tool | Qt.FramelessWindowHint)
                self._appbar_hwnd = int(self._appbar_widget.winId())
            shell32.SHAppBarMessage(0, ctypes.byref(self._appbar_data()))  # ABM_NEW
            self._appbar_registered = True
            force = True
        l, t, r, b = self._primary_monitor()
        abd = self._appbar_data()
        abd.uEdge = self._EDGES.get(edge, 3)
        abd.rc = wt.RECT(l, t, r, b)
        if edge == "bottom":
            abd.rc.top = b - thick
        elif edge == "left":
            abd.rc.right = l + thick
        elif edge == "right":
            abd.rc.left = r - thick
        shell32.SHAppBarMessage(2, ctypes.byref(abd))  # ABM_QUERYPOS
        if edge == "bottom":
            abd.rc.top = abd.rc.bottom - thick
        elif edge == "left":
            abd.rc.right = abd.rc.left + thick
        elif edge == "right":
            abd.rc.left = abd.rc.right - thick
        rect = (abd.rc.left, abd.rc.top, abd.rc.right, abd.rc.bottom)
        if force or rect != getattr(self, "_appbar_rect", None):
            shell32.SHAppBarMessage(3, ctypes.byref(abd))  # ABM_SETPOS
            self._appbar_rect = rect

    def reserve_edge(self, edge: str, thickness_px: int):
        new = (edge, int(thickness_px))
        changed = new != self._reserved
        self._reserved = new
        self._apply_appbar(force=changed)

    def release_edge(self):
        if self._reserved is None:
            return
        self._reserved = None
        if getattr(self, "_appbar_registered", False):
            shell32.SHAppBarMessage(1, ctypes.byref(self._appbar_data()))  # ABM_REMOVE
            self._appbar_registered = False
            self._appbar_rect = None

    def trim_memory(self):
        """Move pages we haven't touched lately out of our working set.  They stay in RAM
        (standby list) and come back instantly if needed, but Task Manager shows only what
        Nocthify is really using right now."""
        try:
            psapi = ctypes.windll.psapi
            psapi.EmptyWorkingSet.argtypes = [wt.HANDLE]
            psapi.EmptyWorkingSet(wt.HANDLE(-1))          # -1 = this process (pseudo handle)
        except (OSError, AttributeError, ctypes.ArgumentError):
            pass

    def set_autostart(self, enabled: bool, command: str):
        path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_SET_VALUE)
            if enabled:
                winreg.SetValueEx(key, "Nocthify", 0, winreg.REG_SZ, command)
            else:
                try:
                    winreg.DeleteValue(key, "Nocthify")
                except OSError:
                    pass
            winreg.CloseKey(key)
        except OSError:
            pass

    # Brightness/wifi are slow (spawn a process): helpers to run them off-thread
    @staticmethod
    def run_async(fn, callback=None):
        def worker():
            result = fn()
            if callback:
                callback(result)
        threading.Thread(target=worker, daemon=True).start()
