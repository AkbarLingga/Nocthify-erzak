"""Build the Windows installer: release/NocthifySetup-<version>.exe

    .venv\\Scripts\\python.exe build.py          (or double-click build.bat)

Steps: render the app icon -> PyInstaller (one folder, no console) -> Inno Setup.
Needs PyInstaller in the venv (installed automatically) and Inno Setup 6.
Friends who install the result need neither Python nor PowerShell.
"""
from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BUILD = os.path.join(ROOT, "build")
DIST = os.path.join(ROOT, "dist")
RELEASE = os.path.join(ROOT, "release")
sys.path.insert(0, ROOT)


def step(msg):
    print(f"\n==> {msg}", flush=True)


def version() -> str:
    from nocthify.config import APP_VERSION
    return APP_VERSION


def write_icon(path):
    """Multi-size .ico from the same drawing Nocthify uses for its own icon."""
    from PyQt5.QtGui import QGuiApplication
    from nocthify.winexe import _icon_images
    _app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])  # noqa: F841
    images = _icon_images()
    offset = 6 + 16 * len(images)
    header = struct.pack("<HHH", 0, 1, len(images))
    entries, blobs = b"", b""
    for size, data in images:
        dim = 0 if size >= 256 else size
        entries += struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(data), offset + len(blobs))
        blobs += data
    with open(path, "wb") as fh:
        fh.write(header + entries + blobs)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        step("Installing PyInstaller into this venv")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "pyinstaller"])


def pyinstaller(icon):
    step("PyInstaller: bundling Python + Qt into dist\\Nocthify")
    args = [
        sys.executable, "-m", "PyInstaller", os.path.join(ROOT, "run.pyw"),
        "--name", "Nocthify", "--noconfirm", "--clean", "--windowed", "--onedir",
        "--icon", icon,
        "--distpath", DIST, "--workpath", os.path.join(BUILD, "pyinstaller"),
        "--specpath", BUILD,
        # imported lazily / inside functions, so PyInstaller can't see them on its own
        "--hidden-import", "PyQt5.QtWinExtras",
        "--hidden-import", "PyQt5.QtSvg",
        "--hidden-import", "nocthify.backends.windows",
        "--hidden-import", "nocthify.backends.win_hooks",
        "--hidden-import", "nocthify.backends.media_win",
        "--collect-submodules", "nocthify.ui",
        # trim what Nocthify never uses (smaller download, nothing extra loaded)
        "--exclude-module", "tkinter",
        "--exclude-module", "unittest",
        "--exclude-module", "pydoc",
        "--exclude-module", "PyQt5.QtQml",
        "--exclude-module", "PyQt5.QtQuick",
        "--exclude-module", "PyQt5.QtWebEngineWidgets",
        "--exclude-module", "PyQt5.QtMultimedia",
        "--exclude-module", "PyQt5.QtBluetooth",
        "--exclude-module", "PyQt5.QtSql",
        "--exclude-module", "PyQt5.QtTest",
        "--exclude-module", "PyQt5.QtDBus",
    ]
    try:
        import winrt  # noqa: F401  (optional: now-playing info / synced lyrics)
        args += ["--collect-submodules", "winrt"]
    except ImportError:
        print("   (winrt not installed: the build falls back to window-title media detection)")
    subprocess.check_call(args, cwd=ROOT)
    exe = os.path.join(DIST, "Nocthify", "Nocthify.exe")
    if not os.path.isfile(exe):
        sys.exit("PyInstaller finished but dist\\Nocthify\\Nocthify.exe is missing")
    return exe


def find_iscc():
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    for base in (os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", ""),
                 os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
        cand = os.path.join(base, "Inno Setup 6", "ISCC.exe")
        if base and os.path.isfile(cand):
            return cand
    return None


def inno(ver, icon):
    iscc = find_iscc()
    if iscc is None:
        sys.exit("Inno Setup 6 not found. Install it once with:\n"
                 "    winget install --id JRSoftware.InnoSetup -e\n"
                 "then run build.py again. (The app itself is ready in dist\\Nocthify.)")
    step("Inno Setup: packing release\\NocthifySetup-%s.exe" % ver)
    os.makedirs(RELEASE, exist_ok=True)
    subprocess.check_call([iscc, "/Q", f"/DAppVersion={ver}", f"/DSourceDir={DIST}\\Nocthify",
                           f"/DIconFile={icon}", f"/DOutputDir={RELEASE}",
                           os.path.join(ROOT, "packaging", "installer.iss")])
    return os.path.join(RELEASE, f"NocthifySetup-{ver}.exe")


def main():
    if not sys.platform.startswith("win"):
        sys.exit("The installer is Windows-only (Linux users: install.sh).")
    ver = version()
    os.makedirs(BUILD, exist_ok=True)
    step(f"Nocthify {ver}: rendering icon")
    icon = os.path.join(BUILD, "nocthify.ico")
    write_icon(icon)
    ensure_pyinstaller()
    pyinstaller(icon)
    setup = inno(ver, icon)
    size = os.path.getsize(setup) / (1024 * 1024)
    step(f"Done: {setup}  ({size:.1f} MB)")


if __name__ == "__main__":
    main()
