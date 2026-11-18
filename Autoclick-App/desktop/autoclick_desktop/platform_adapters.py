from __future__ import annotations

import importlib
import importlib.util
import os
from pathlib import Path
import subprocess
from typing import Protocol, Sequence
import webbrowser


class OperatingSystemAdapter(Protocol):
    def is_available(self) -> bool: ...
    def run_application(self, path: str, arguments: Sequence[str]) -> None: ...
    def open_browser(self, url: str) -> None: ...
    def open_folder(self, path: Path) -> None: ...


class LocalOperatingSystem:
    def is_available(self) -> bool:
        return True

    def is_handler_available(self, handler_key: str) -> bool:
        return handler_key != "folder.open" or getattr(os, "startfile", None) is not None

    def run_application(self, path: str, arguments: Sequence[str]) -> None:
        subprocess.Popen([path, *arguments])

    def open_browser(self, url: str) -> None:
        if not webbrowser.open(url):
            raise OSError("browser rejected URL")

    def open_folder(self, path: Path) -> None:
        startfile = getattr(os, "startfile", None)
        if startfile is None:
            raise OSError("folder opening is unavailable")
        startfile(str(path))


class WindowAdapter(Protocol):
    def is_available(self) -> bool: ...
    def find(self, title: str) -> object | None: ...
    def focus(self, window: object) -> None: ...
    def move(self, window: object, x: int, y: int) -> None: ...
    def maximize(self, window: object) -> None: ...
    def minimize(self, window: object) -> None: ...
    def resize(self, window: object, width: int, height: int) -> None: ...
    def close(self, window: object) -> None: ...


class NativeWin32Window:
    def __init__(self, hwnd: int, title: str) -> None:
        self._hWnd = hwnd
        self.title = title

    def __repr__(self) -> str:
        return f"<NativeWin32Window hwnd={self._hWnd} title={repr(self.title)}>"


class PyGetWindowAdapter:
    """Lazy optional desktop-window integration."""

    def __init__(self, module: object | None = None) -> None:
        self._module = module

    def _api(self) -> object:
        if self._module is None:
            self._module = importlib.import_module("pygetwindow")
        return self._module

    def is_available(self) -> bool:
        return self._module is not None or module_available("pygetwindow")

    def find(self, title: str) -> object | None:
        needle = title.casefold()
        candidates: list[object] = []

        try:
            import ctypes
            user32 = ctypes.windll.user32

            def enum_cb(hwnd: int, _lparam: object) -> bool:
                length = user32.GetWindowTextLengthW(hwnd)
                if length > 0:
                    buff = ctypes.create_unicode_buffer(length + 1)
                    user32.GetWindowTextW(hwnd, buff, length + 1)
                    if needle in buff.value.casefold():
                        candidates.append(NativeWin32Window(hwnd, buff.value))
                return True

            CMPFUNC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
            callback = CMPFUNC(enum_cb)

            hdesk = user32.OpenInputDesktop(0, False, 0x0100)
            if hdesk:
                user32.EnumDesktopWindows(hdesk, callback, 0)
                user32.CloseDesktop(hdesk)
            user32.EnumWindows(callback, 0)
        except Exception:
            pass

        try:
            for window in self._api().getAllWindows():
                if needle in str(getattr(window, "title", "")).casefold():
                    candidates.append(window)
        except Exception:
            pass

        if not candidates:
            return None

        unique_by_hwnd: dict[int, object] = {}
        for cand in candidates:
            hwnd = getattr(cand, "_hWnd", None)
            if hwnd is not None and hwnd not in unique_by_hwnd:
                unique_by_hwnd[hwnd] = cand

        def window_priority(item: object) -> int:
            hwnd = getattr(item, "_hWnd", None)
            if hwnd is None:
                return 0
            try:
                import ctypes
                user32 = ctypes.windll.user32
                buff = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buff, 256)
                cname = buff.value
                if cname == "ApplicationFrameWindow":
                    return 100
                if cname == "Windows.UI.Core.CoreWindow":
                    return -10
                if user32.IsWindowVisible(hwnd):
                    return 50
                return 10
            except Exception:
                return 0

        ranked = sorted(unique_by_hwnd.values(), key=window_priority, reverse=True)
        return ranked[0] if ranked else (candidates[0] if candidates else None)

    def focus(self, window: object) -> None:
        hwnd = getattr(window, "_hWnd", None)
        if hwnd is not None:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                else:
                    user32.ShowWindow(hwnd, 5)  # SW_SHOW
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                if hasattr(user32, "SwitchToThisWindow"):
                    user32.SwitchToThisWindow(hwnd, True)
                return
            except Exception:
                pass
        if hasattr(window, "activate"):
            window.activate()

    def move(self, window: object, x: int, y: int) -> None:
        hwnd = getattr(window, "_hWnd", None)
        if hwnd is not None:
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                rect = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    w = rect.right - rect.left
                    h = rect.bottom - rect.top
                    user32.MoveWindow(hwnd, int(x), int(y), w, h, True)
                    return
            except Exception:
                pass
        if hasattr(window, "moveTo"):
            window.moveTo(x, y)

    def maximize(self, window: object) -> None:
        hwnd = getattr(window, "_hWnd", None)
        if hwnd is not None:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                if user32.IsIconic(hwnd):
                    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                user32.ShowWindow(hwnd, 3)  # SW_MAXIMIZE
                user32.SetForegroundWindow(hwnd)
                user32.BringWindowToTop(hwnd)
                if hasattr(user32, "SwitchToThisWindow"):
                    user32.SwitchToThisWindow(hwnd, True)
                return
            except Exception:
                pass
        if hasattr(window, "maximize"):
            window.maximize()

    def minimize(self, window: object) -> None:
        hwnd = getattr(window, "_hWnd", None)
        if hwnd is not None:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                return
            except Exception:
                pass
        if hasattr(window, "minimize"):
            window.minimize()

    def resize(self, window: object, width: int, height: int) -> None:
        hwnd = getattr(window, "_hWnd", None)
        if hwnd is not None:
            try:
                import ctypes
                from ctypes import wintypes
                user32 = ctypes.windll.user32
                rect = wintypes.RECT()
                if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                    user32.MoveWindow(hwnd, rect.left, rect.top, int(width), int(height), True)
                    return
            except Exception:
                pass
        if hasattr(window, "resizeTo"):
            window.resizeTo(width, height)

    def close(self, window: object) -> None:
        hwnd = getattr(window, "_hWnd", None)
        if hwnd is not None:
            try:
                import ctypes
                user32 = ctypes.windll.user32
                user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
                return
            except Exception:
                pass
        if hasattr(window, "close"):
            window.close()


def module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, AttributeError, ValueError):
        return False
