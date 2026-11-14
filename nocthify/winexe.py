"""Windows: give Nocthify its own ``Nocthify.exe`` so Task Manager shows "Nocthify".

Python apps normally show up as "Python" (pythonw.exe), and a venv adds a second
tiny launcher process on top.  This builds ``<venv>\\Scripts\\Nocthify.exe``: a copy
of the real ``pythonw.exe`` (no launcher in between, so one process instead of two)
with Nocthify's name, version and icon written into its resources.  The Python
runtime DLLs it needs are copied next to it; it finds the venv's packages through
``pyvenv.cfg`` like any venv interpreter does.

Rebuilt automatically when Python is updated or this file's BRAND changes.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import os
import shutil
import struct
import sys

from . import __version__

EXE_NAME = "Nocthify.exe"
BRAND = 2                      # bump to force a rebuild after changing the resources below
RT_ICON, RT_GROUP_ICON, RT_VERSION = 3, 14, 16
LANG = 0x0409
ICON_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def exe_path():
    """Where Nocthify.exe lives (None outside a venv on Windows)."""
    if not sys.platform.startswith("win") or sys.prefix == getattr(sys, "base_prefix", sys.prefix):
        return None
    return os.path.join(sys.prefix, "Scripts", EXE_NAME)


def running_as_exe():
    return os.path.basename(sys.executable).lower() == EXE_NAME.lower()


def _runtime_files(base):
    major, minor = sys.version_info[:2]
    names = [f"python{major}{minor}.dll", "python3.dll", "vcruntime140.dll", "vcruntime140_1.dll"]
    return [n for n in names if os.path.exists(os.path.join(base, n))]


def _stamp(base):
    parts = [str(BRAND), __version__]
    for n in ["pythonw.exe"] + _runtime_files(base):
        st = os.stat(os.path.join(base, n))
        parts.append(f"{n}:{st.st_size}:{int(st.st_mtime)}")
    return "|".join(parts)


def ensure_exe():
    """Build or refresh Nocthify.exe; returns its path, or None if not possible."""
    target = exe_path()
    if target is None:
        return None
    base = sys.base_prefix
    if not os.path.exists(os.path.join(base, "pythonw.exe")):
        return None
    folder = os.path.dirname(target)
    stamp_file = target + ".stamp"
    stamp = _stamp(base)
    _clean_leftovers(folder)
    try:
        with open(stamp_file, encoding="utf-8") as f:
            if f.read() == stamp and os.path.exists(target):
                return target
    except OSError:
        pass
    for n in _runtime_files(base):
        _put(os.path.join(base, n), os.path.join(folder, n))
    tmp = target + ".new"
    shutil.copyfile(os.path.join(base, "pythonw.exe"), tmp)
    _strip_signature(tmp)       # the edit below would leave a broken signature behind
    _brand(tmp)
    _replace(tmp, target)
    with open(stamp_file, "w", encoding="utf-8") as f:
        f.write(stamp)
    return target


# ------------------------------------------------------------------- files
def _same(a, b):
    try:
        sa, sb = os.stat(a), os.stat(b)
        return sa.st_size == sb.st_size and int(sa.st_mtime) == int(sb.st_mtime)
    except OSError:
        return False


def _put(src, dst):
    if _same(src, dst):
        return
    tmp = dst + ".new"
    shutil.copy2(src, tmp)
    _replace(tmp, dst)


def _replace(tmp, dst):
    """Move tmp over dst; a file in use (a running Nocthify) is renamed out of the way."""
    try:
        os.replace(tmp, dst)
        return
    except OSError:
        pass
    for i in range(100):
        old = f"{dst}.old{i}"
        try:
            if os.path.exists(old):
                os.remove(old)
            os.rename(dst, old)
            break
        except OSError:
            continue
    os.replace(tmp, dst)


def _clean_leftovers(folder):
    try:
        for n in os.listdir(folder):
            if ".old" in n and n.lower().endswith(tuple(f".old{i}" for i in range(100))):
                try:
                    os.remove(os.path.join(folder, n))
                except OSError:
                    pass          # still in use by a running copy: next time
    except OSError:
        pass


def _strip_signature(path):
    with open(path, "r+b") as f:
        data = f.read(4096)
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        magic = struct.unpack_from("<H", data, pe + 24)[0]
        dirs = pe + 24 + (112 if magic == 0x20B else 96)
        sec = dirs + 4 * 8                                 # IMAGE_DIRECTORY_ENTRY_SECURITY
        off, size = struct.unpack_from("<II", data, sec)
        if not off:
            return
        f.seek(sec)
        f.write(struct.pack("<II", 0, 0))
        f.seek(0, 2)
        if off + size == f.tell():
            f.truncate(off)


# --------------------------------------------------------------- resources
def _brand(path):
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.LoadLibraryExW.argtypes = [wt.LPCWSTR, wt.HANDLE, wt.DWORD]
    k32.LoadLibraryExW.restype = wt.HMODULE
    k32.FreeLibrary.argtypes = [wt.HMODULE]
    k32.BeginUpdateResourceW.argtypes = [wt.LPCWSTR, wt.BOOL]
    k32.BeginUpdateResourceW.restype = wt.HANDLE
    k32.UpdateResourceW.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.c_void_p, wt.WORD, ctypes.c_void_p, wt.DWORD]
    k32.EndUpdateResourceW.argtypes = [wt.HANDLE, wt.BOOL]

    existing = _list_resources(k32, path, (RT_ICON, RT_GROUP_ICON, RT_VERSION))
    images = _icon_images()
    h = k32.BeginUpdateResourceW(path, False)
    if not h:
        raise ctypes.WinError(ctypes.get_last_error())
    keep = []                                              # buffers must outlive EndUpdateResource

    def put(rtype, name, lang, data):
        name_arg = ctypes.c_void_p(name) if isinstance(name, int) else ctypes.c_wchar_p(name)
        keep.append(name_arg)
        if data is None:
            ok = k32.UpdateResourceW(h, ctypes.c_void_p(rtype), name_arg, lang, None, 0)
        else:
            buf = ctypes.create_string_buffer(data, len(data))
            keep.append(buf)
            ok = k32.UpdateResourceW(h, ctypes.c_void_p(rtype), name_arg, lang, buf, len(data))
        if not ok:
            raise ctypes.WinError(ctypes.get_last_error())

    try:
        for rtype, name, lang in existing:
            put(rtype, name, lang, None)
        group = struct.pack("<HHH", 0, 1, len(images))
        for i, (size, data) in enumerate(images, 1):
            put(RT_ICON, i, LANG, data)
            dim = 0 if size >= 256 else size
            group += struct.pack("<BBBBHHIH", dim, dim, 0, 0, 1, 32, len(data), i)
        put(RT_GROUP_ICON, 1, LANG, group)
        put(RT_VERSION, 1, LANG, _version_info())
    except Exception:
        k32.EndUpdateResourceW(h, True)
        raise
    if not k32.EndUpdateResourceW(h, False):
        raise ctypes.WinError(ctypes.get_last_error())


def _list_resources(k32, path, types):
    NAMEPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)
    LANGPROC = ctypes.WINFUNCTYPE(wt.BOOL, wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p, wt.WORD, ctypes.c_ssize_t)
    k32.EnumResourceNamesW.argtypes = [wt.HMODULE, ctypes.c_void_p, NAMEPROC, ctypes.c_ssize_t]
    k32.EnumResourceLanguagesW.argtypes = [wt.HMODULE, ctypes.c_void_p, ctypes.c_void_p, LANGPROC, ctypes.c_ssize_t]
    mod = k32.LoadLibraryExW(path, None, 0x2)              # LOAD_LIBRARY_AS_DATAFILE
    if not mod:
        return []
    found = []
    try:
        for rtype in types:
            names = []

            def on_name(_m, _t, name, _p, names=names):
                names.append(name if name >> 16 == 0 else ctypes.wstring_at(name))
                return True
            k32.EnumResourceNamesW(mod, rtype, NAMEPROC(on_name), 0)
            for name in names:
                langs = []

                def on_lang(_m, _t, _n, lang, _p, langs=langs):
                    langs.append(lang)
                    return True
                arg = ctypes.c_void_p(name) if isinstance(name, int) else ctypes.c_wchar_p(name)
                k32.EnumResourceLanguagesW(mod, rtype, arg, LANGPROC(on_lang), 0)
                found += [(rtype, name, lang) for lang in langs]
    finally:
        k32.FreeLibrary(mod)
    return found


def _node(key, value=b"", text=False, children=()):
    """One VS_VERSIONINFO block (String / StringTable / Var / ...)."""
    def pad(b):
        return b + b"\0" * (-len(b) % 4)
    body = (key + "\0").encode("utf-16-le")
    out = pad(b"\0" * 6 + body)
    out += value
    for child in children:
        out = pad(out) + child
    value_len = len(value) // 2 if text else len(value)
    return struct.pack("<HHH", len(out), value_len, 1 if text else 0) + out[6:]


def _version_info():
    nums = [int(x) for x in (__version__.split(".") + ["0", "0", "0"])[:4] if x.isdigit()] + [0, 0, 0, 0]
    ms, ls = (nums[0] << 16) | nums[1], (nums[2] << 16) | nums[3]
    fixed = struct.pack("<13I", 0xFEEF04BD, 0x00010000, ms, ls, ms, ls, 0x3F, 0, 0x40004, 1, 0, 0, 0)
    strings = [("CompanyName", "erzak"), ("FileDescription", "Nocthify"), ("FileVersion", __version__),
               ("InternalName", "Nocthify"), ("LegalCopyright", "erzak"),
               ("OriginalFilename", EXE_NAME), ("ProductName", "Nocthify - erzak"),
               ("ProductVersion", __version__)]
    table = _node("040904B0", children=[_node(k, (v + "\0").encode("utf-16-le"), True) for k, v in strings])
    var = _node("VarFileInfo", children=[_node("Translation", struct.pack("<HH", LANG, 1200))])
    return _node("VS_VERSION_INFO", fixed, children=[_node("StringFileInfo", children=[table]), var])


# -------------------------------------------------------------------- icon
def _icon_images():
    """[(size, RT_ICON data)]: 32-bit DIBs, PNG for 256 px."""
    from PyQt5.QtCore import QBuffer, QByteArray, QIODevice
    out = []
    for size in ICON_SIZES:
        img = render_icon(size)
        if size >= 256:
            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(QIODevice.WriteOnly)
            img.save(buf, "PNG")
            out.append((size, bytes(ba)))
            continue
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes() if hasattr(img, "sizeInBytes") else img.byteCount())
        raw = bytes(ptr)
        stride = img.bytesPerLine()
        rows = [raw[y * stride:y * stride + size * 4] for y in range(size)]
        pixels = b"".join(reversed(rows))                  # DIBs are stored bottom-up
        mask_row = ((size + 31) // 32) * 4
        header = struct.pack("<IiiHHIIiiII", 40, size, size * 2, 1, 32, 0, 0, 0, 0, 0, 0)
        out.append((size, header + pixels + b"\0" * (mask_row * size)))
    return out


def render_icon(size):
    """Nocthify's icon: a dark rounded tile with the island on top and the dock below."""
    from PyQt5.QtCore import QRectF, Qt
    from PyQt5.QtGui import QColor, QImage, QLinearGradient, QPainter, QPainterPath
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    s = float(size)
    m = s * (0.04 if size >= 48 else 0.0)
    tile = QRectF(m, m, s - 2 * m, s - 2 * m)
    path = QPainterPath()
    path.addRoundedRect(tile, tile.width() * 0.235, tile.height() * 0.235)
    g = QLinearGradient(tile.topLeft(), tile.bottomRight())
    g.setColorAt(0.0, QColor("#2B3A67"))
    g.setColorAt(0.55, QColor("#16182B"))
    g.setColorAt(1.0, QColor("#0B0B12"))
    p.fillPath(path, g)
    if size >= 32:                                         # soft top highlight
        hi = QLinearGradient(tile.topLeft(), tile.center())
        hi.setColorAt(0.0, QColor(255, 255, 255, 46))
        hi.setColorAt(1.0, QColor(255, 255, 255, 0))
        p.fillPath(path, hi)
    w = tile.width()
    # the island
    iw, ih = w * 0.50, w * 0.15
    island = QRectF(tile.center().x() - iw / 2, tile.top() + w * 0.17, iw, ih)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#000000"))
    p.drawRoundedRect(island, ih / 2, ih / 2)
    if size >= 24:
        dot = ih * 0.36
        p.setBrush(QColor("#30D158"))
        p.drawEllipse(QRectF(island.right() - ih * 0.5 - dot / 2, island.center().y() - dot / 2, dot, dot))
    # the dock
    dw, dh = w * 0.70, w * 0.21
    dock = QRectF(tile.center().x() - dw / 2, tile.bottom() - w * 0.13 - dh, dw, dh)
    p.setBrush(QColor(255, 255, 255, 64))
    p.drawRoundedRect(dock, dh * 0.34, dh * 0.34)
    colors = ("#0A84FF", "#FF9F0A", "#FF375F")
    n = len(colors)
    tile_w = dh * 0.66
    gap = (dw - n * tile_w) / (n + 1)
    for i, col in enumerate(colors):
        r = QRectF(dock.left() + gap + i * (tile_w + gap), dock.center().y() - tile_w / 2, tile_w, tile_w)
        p.setBrush(QColor(col))
        p.drawRoundedRect(r, tile_w * 0.26, tile_w * 0.26)
    p.end()
    return img


if __name__ == "__main__":  # python -m nocthify.winexe
    from PyQt5.QtGui import QGuiApplication
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    print(ensure_exe() or "Nocthify.exe: not available here (needs Windows and a venv)")
