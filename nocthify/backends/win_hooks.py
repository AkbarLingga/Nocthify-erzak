"""Event hooks for Windows, on their own thread.

Instead of re-scanning every window each second, Windows tells us when something
changes:

* WinEvent hooks: a top-level window was created / destroyed / shown / hidden /
  minimised / restored / focused / cloaked            ->  "windows"
  renamed (throttled: spinners in titles are common)  ->  "names"
  the native taskbar tried to show itself again       ->  "taskbar"
* a low-level keyboard hook:
  - volume keys pressed                               ->  "volume"
  - media keys pressed                                ->  "media"
  - the Windows key tapped on its own (if enabled)    ->  "win_tap"
    Win+<anything> combos are left alone.  For a lone tap the key-up is swallowed
    and replaced by "mask key + Win up" (the AutoHotkey trick), so the Start menu
    stays shut.

The hooks live on a dedicated thread with its own message loop, so a busy UI
thread can never make typing lag.  ``emit(kind)`` must be thread-safe (a Qt
signal's emit is).
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import threading

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, wt.WPARAM, wt.LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(None, wt.HANDLE, wt.DWORD, wt.HWND, wt.LONG, wt.LONG, wt.DWORD, wt.DWORD)

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wt.HINSTANCE, wt.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, wt.WPARAM, wt.LPARAM]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.SetWinEventHook.argtypes = [wt.DWORD, wt.DWORD, wt.HMODULE, WINEVENTPROC, wt.DWORD, wt.DWORD, wt.DWORD]
user32.SetWinEventHook.restype = wt.HANDLE
user32.UnhookWinEvent.argtypes = [wt.HANDLE]
user32.GetAncestor.argtypes = [wt.HWND, wt.UINT]
user32.GetAncestor.restype = wt.HWND
user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
user32.GetMessageW.argtypes = [ctypes.POINTER(wt.MSG), wt.HWND, wt.UINT, wt.UINT]
user32.PostThreadMessageW.argtypes = [wt.DWORD, wt.UINT, wt.WPARAM, wt.LPARAM]
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
kernel32.GetModuleHandleW.restype = wt.HMODULE


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [("vkCode", wt.DWORD), ("scanCode", wt.DWORD), ("flags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


MARK = 0x4E4F4354            # dwExtraInfo tag on events Nocthify injects itself ("NOCT")
VK_MASK = 0xE8               # unassigned virtual key used to "mask" a lone Win tap
WM_QUIT = 0x0012
WM_APP_TAP = 0x8000 + 0x21
VOLUME_KEYS = (0xAD, 0xAE, 0xAF)
MEDIA_KEYS = (0xB0, 0xB1, 0xB2, 0xB3)
EVENT_RANGES = ((0x0003, 0x0003),     # SYSTEM_FOREGROUND
                (0x0016, 0x0017),     # SYSTEM_MINIMIZESTART / END
                (0x8000, 0x8003),     # OBJECT_CREATE / DESTROY / SHOW / HIDE
                (0x800C, 0x800C),     # OBJECT_NAMECHANGE
                (0x8017, 0x8018))     # OBJECT_CLOAKED / UNCLOAKED (UWP apps, virtual desktops)
TRAY_CLASSES = ("Shell_TrayWnd", "Shell_SecondaryTrayWnd")


class HookThread(threading.Thread):
    def __init__(self, emit):
        super().__init__(name="nocthify-hooks", daemon=True)
        self.emit = emit
        self.win_key = False          # set from the UI thread
        self.known = set()            # hwnds of the current window list (from the UI thread)
        self.pending = False          # a "windows" event is queued; cleared by the UI thread
        self.names_pending = False    # same for title-only changes (throttled harder)
        self.tid = 0
        self._win_down = False
        self._combo = False
        self._kb = None
        self._events = []
        self._kb_proc = HOOKPROC(self._on_key)
        self._ev_proc = WINEVENTPROC(self._on_event)
        self.ready = threading.Event()

    # ------------------------------------------------------------- lifecycle
    def run(self):
        self.tid = kernel32.GetCurrentThreadId()
        self._kb = user32.SetWindowsHookExW(13, self._kb_proc, kernel32.GetModuleHandleW(None), 0)
        for lo, hi in EVENT_RANGES:
            h = user32.SetWinEventHook(lo, hi, None, self._ev_proc, 0, 0, 0x0000 | 0x0002)  # OUTOFCONTEXT|SKIPOWNPROCESS
            if h:
                self._events.append(h)
        self.ready.set()
        msg = wt.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_APP_TAP:
                self._finish_tap(int(msg.wParam))
        for h in self._events:
            user32.UnhookWinEvent(h)
        if self._kb:
            user32.UnhookWindowsHookEx(self._kb)

    def stop(self):
        if self.tid:
            user32.PostThreadMessageW(self.tid, WM_QUIT, 0, 0)

    @property
    def keyboard_ok(self):
        return bool(self._kb)

    # -------------------------------------------------------------- keyboard
    def _on_key(self, code, wparam, lparam):
        try:
            if code == 0:
                kb = KBDLLHOOKSTRUCT.from_address(lparam)
                if kb.dwExtraInfo != MARK:
                    vk = kb.vkCode
                    down = wparam in (0x100, 0x104)
                    if vk in (0x5B, 0x5C):
                        if down:
                            if not self._win_down:
                                self._win_down, self._combo = True, False
                        else:
                            lone = self._win_down and not self._combo
                            self._win_down = False
                            if lone and self.win_key:
                                user32.PostThreadMessageW(self.tid, WM_APP_TAP, vk, 0)
                                return 1          # swallow the key-up; replaced in _finish_tap
                    else:
                        if down and self._win_down:
                            self._combo = True
                        if down and vk in VOLUME_KEYS:
                            self.emit("volume")
                        elif down and vk in MEDIA_KEYS:
                            self.emit("media")
        except Exception:
            pass
        return user32.CallNextHookEx(None, code, wparam, lparam)

    def _finish_tap(self, vk):
        kd = user32.keybd_event
        kd(VK_MASK, 0, 0, MARK)
        kd(VK_MASK, 0, 2, MARK)
        kd(vk, 0, 1 | 2, MARK)        # extended key-up for the Win key
        self.emit("win_tap")

    # ----------------------------------------------------------------- windows
    def _on_event(self, _hook, event, hwnd, id_object, id_child, _thread, _time):
        try:
            if id_object != 0 or id_child != 0 or not hwnd:
                return
            h = hwnd if isinstance(hwnd, int) else int(hwnd)
            if event in (0x8001, 0x8003, 0x8017):        # destroy / hide / cloak: only windows we list
                if h not in self.known:
                    return
            elif event != 0x0003:
                root = user32.GetAncestor(hwnd, 2)       # GA_ROOT: ignore child controls
                if not root or int(root) != h:
                    return
                if event == 0x8002:                      # shown: is it the native taskbar?
                    buf = ctypes.create_unicode_buffer(32)
                    user32.GetClassNameW(hwnd, buf, 32)
                    if buf.value in TRAY_CLASSES:
                        self.emit("taskbar")
                        return
            if event == 0x800C:                          # title only: animated titles are common
                if not self.names_pending and not self.pending:
                    self.names_pending = True
                    self.emit("names")
            elif not self.pending:
                self.pending = True
                self.emit("windows")
        except Exception:
            pass
