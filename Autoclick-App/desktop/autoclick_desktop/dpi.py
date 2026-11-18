from __future__ import annotations

import sys

_DPI_AWARENESS_SET = False


def enable_windows_dpi_awareness() -> bool:
    """Enable Per-Monitor V2 DPI awareness on Windows so coordinate space matches physical pixels."""
    global _DPI_AWARENESS_SET
    if _DPI_AWARENESS_SET:
        return True
    if sys.platform != "win32":
        return False

    try:
        import ctypes

        user32 = getattr(ctypes, "windll", None)
        if user32 and hasattr(user32, "user32"):
            u32 = user32.user32
            # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
            if hasattr(u32, "SetProcessDpiAwarenessContext"):
                res = u32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
                if res:
                    _DPI_AWARENESS_SET = True
                    return True
        shcore = getattr(ctypes, "windll", None)
        if shcore and hasattr(shcore, "shcore"):
            sh = shcore.shcore
            # PROCESS_PER_MONITOR_DPI_AWARE = 2
            if hasattr(sh, "SetProcessDpiAwareness"):
                res = sh.SetProcessDpiAwareness(2)
                if res == 0:
                    _DPI_AWARENESS_SET = True
                    return True
        if user32 and hasattr(user32, "user32"):
            u32 = user32.user32
            if hasattr(u32, "SetProcessDPIAware"):
                u32.SetProcessDPIAware()
                _DPI_AWARENESS_SET = True
                return True
    except Exception:
        pass
    return False
