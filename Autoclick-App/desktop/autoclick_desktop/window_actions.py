from __future__ import annotations

import time
from threading import Event

from autoclick_desktop.execution_errors import ExecutionCancelled, ExecutionErrorCode, HandlerError
from autoclick_desktop.execution_models import ResolvedAction
from autoclick_desktop.platform_adapters import WindowAdapter


def handle_window(action: ResolvedAction, cancel_event: Event, windows: WindowAdapter) -> None:
    try:
        if action.action_id == "window.wait":
            deadline = time.monotonic() + int(action.params["timeoutMs"]) / 1000
            interval = int(action.params.get("pollIntervalMs", 100)) / 1000
            while True:
                if cancel_event.is_set():
                    raise ExecutionCancelled()
                if windows.find(str(action.params["title"])) is not None:
                    return
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise HandlerError(ExecutionErrorCode.WINDOW_NOT_FOUND)
                if cancel_event.wait(min(interval, remaining)):
                    raise ExecutionCancelled()
        window = windows.find(str(action.params["title"]))
        if window is None:
            raise HandlerError(ExecutionErrorCode.WINDOW_NOT_FOUND)
        operation = action.action_id.removeprefix("window.")
        if operation == "focus": windows.focus(window)
        elif operation == "move": windows.move(window, int(action.params["x"]), int(action.params["y"]))
        elif operation == "maximize": windows.maximize(window)
        elif operation == "minimize": windows.minimize(window)
        elif operation == "resize": windows.resize(window, int(action.params["width"]), int(action.params["height"]))
        elif operation == "close": windows.close(window)
    except (ExecutionCancelled, HandlerError):
        raise
    except Exception:
        raise HandlerError(ExecutionErrorCode.WINDOW_OPERATION_FAILED) from None
