import sys

_SCALE = 1.0


def _enable():
    if sys.platform == 'win32':
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except (AttributeError, OSError):
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except (AttributeError, OSError):
                pass


_enable()


def s(value):
    global _SCALE
    if _SCALE == 1.0:
        try:
            import tkinter as tk
            root = tk._default_root
            if root:
                scaling = float(root.tk.call('tk', 'scaling'))
                _SCALE = scaling / 1.3333333333333333
        except Exception:
            pass
    return int(value * _SCALE)
