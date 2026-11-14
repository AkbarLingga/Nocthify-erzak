"""Pick the right backend for the running OS."""
import sys

_backend = None


def get_backend():
    global _backend
    if _backend is None:
        if sys.platform.startswith("win"):
            from .windows import WindowsBackend
            _backend = WindowsBackend()
        else:
            from .linux import LinuxBackend
            _backend = LinuxBackend()
    return _backend
