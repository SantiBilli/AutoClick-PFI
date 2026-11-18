import ctypes
import importlib
import math
from threading import Event
from typing import Protocol

from autoclick_desktop.dpi import enable_windows_dpi_awareness
from autoclick_desktop.execution_context import VirtualDesktopBounds
from autoclick_desktop.execution_errors import (
    ExecutionCancelled,
    ExecutionErrorCode,
    HandlerError,
)
from autoclick_desktop.execution_models import ResolvedAction


class MouseController(Protocol):
    def position(self) -> tuple[int, int]: ...
    def move_to(self, x: int, y: int, duration: float) -> None: ...
    def click(self, *, button: str, x: int | None = None, y: int | None = None) -> None: ...
    def double_click(
        self, *, button: str, interval: float, x: int | None = None, y: int | None = None
    ) -> None: ...


class WindowsVirtualDesktop:
    def __init__(self, user32: object | None = None) -> None:
        enable_windows_dpi_awareness()
        self._user32 = user32

    def get_bounds(self) -> VirtualDesktopBounds:
        user32 = self._user32 or ctypes.windll.user32
        return VirtualDesktopBounds(
            int(user32.GetSystemMetrics(76)),
            int(user32.GetSystemMetrics(77)),
            int(user32.GetSystemMetrics(78)),
            int(user32.GetSystemMetrics(79)),
        )


class PyAutoGuiMouse:
    def __init__(self, module: object | None = None) -> None:
        enable_windows_dpi_awareness()
        self._module = module or importlib.import_module("pyautogui")
        self._module.FAILSAFE = False

    def position(self) -> tuple[int, int]:
        point = self._module.position()
        return int(point[0]), int(point[1])

    def move_to(self, x: int, y: int, duration: float) -> None:
        self._module.moveTo(x, y, duration=duration)

    def click(self, *, button: str, x: int | None = None, y: int | None = None) -> None:
        self._module.click(x=x, y=y, button=button)

    def double_click(
        self, *, button: str, interval: float, x: int | None = None, y: int | None = None
    ) -> None:
        self._module.doubleClick(x=x, y=y, button=button, interval=interval)


def _cancelled(cancel_event: Event) -> None:
    if cancel_event.is_set():
        raise ExecutionCancelled()


def handle_mouse_move(
    action: ResolvedAction,
    cancel_event: Event,
    mouse: MouseController,
    *,
    chunk_seconds: float = 0.05,
) -> None:
    x, y = action.params["x"], action.params["y"]
    duration_ms = action.params.get("durationMs", 0)
    assert isinstance(x, int) and isinstance(y, int) and isinstance(duration_ms, int)
    _cancelled(cancel_event)
    try:
        start_x, start_y = mouse.position()
        duration = duration_ms / 1000
        steps = max(1, math.ceil(duration / chunk_seconds))
        for step in range(1, steps + 1):
            _cancelled(cancel_event)
            mouse.move_to(
                round(start_x + (x - start_x) * step / steps),
                round(start_y + (y - start_y) * step / steps),
                0,
            )
            if duration and cancel_event.wait(duration / steps):
                raise ExecutionCancelled()
        _cancelled(cancel_event)
    except ExecutionCancelled:
        raise
    except Exception:
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED) from None


def handle_mouse_click(
    action: ResolvedAction, cancel_event: Event, mouse: MouseController
) -> None:
    _cancelled(cancel_event)
    try:
        mouse.click(
            button=str(action.params.get("button", "left")),
            x=action.params.get("x"),  # type: ignore[arg-type]
            y=action.params.get("y"),  # type: ignore[arg-type]
        )
    except Exception:
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED) from None
    _cancelled(cancel_event)


def handle_mouse_double_click(
    action: ResolvedAction, cancel_event: Event, mouse: MouseController
) -> None:
    _cancelled(cancel_event)
    button = str(action.params.get("button", "left"))
    x = action.params.get("x")
    y = action.params.get("y")
    interval = int(action.params.get("intervalMs", 100)) / 1000
    try:
        mouse.click(button=button, x=x, y=y)  # type: ignore[arg-type]
    except Exception:
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED) from None
    if cancel_event.wait(interval):
        raise ExecutionCancelled()
    try:
        mouse.click(button=button, x=x, y=y)  # type: ignore[arg-type]
    except Exception:
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED) from None
    _cancelled(cancel_event)


def handle_mouse_right_click(action: ResolvedAction, cancel_event: Event, mouse: MouseController) -> None:
    _cancelled(cancel_event)
    try:
        mouse.click(button="right", x=action.params.get("x"), y=action.params.get("y"))  # type: ignore[arg-type]
    except Exception:
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED) from None
    _cancelled(cancel_event)
