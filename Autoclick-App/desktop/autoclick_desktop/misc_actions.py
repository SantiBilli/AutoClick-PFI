from __future__ import annotations

from datetime import datetime
import getpass
from threading import Event
from typing import Callable

from autoclick_desktop.execution_errors import ExecutionCancelled, ExecutionErrorCode, HandlerError
from autoclick_desktop.execution_models import ResolvedAction
from autoclick_desktop.keyboard_actions import Clipboard
from autoclick_desktop.mouse_actions import MouseController


def handle_clipboard(action: ResolvedAction, clipboard: Clipboard) -> object | None:
    try:
        if action.action_id == "clipboard.write": clipboard.set_text(str(action.params["text"]))
        elif action.action_id == "clipboard.read": return clipboard.read_text()
        else: clipboard.clear()
        return None
    except HandlerError:
        raise
    except Exception:
        raise HandlerError(ExecutionErrorCode.CLIPBOARD_UNAVAILABLE) from None


def current_user() -> str:
    return getpass.getuser()


def current_date(action: ResolvedAction, now: Callable[[], datetime] = datetime.now) -> str:
    value = now()
    format_name = str(action.params.get("format", "iso"))
    include_time = bool(action.params.get("includeTime", False))
    if format_name == "iso":
        return value.isoformat(timespec="seconds") if include_time else value.date().isoformat()
    pattern = "%Y-%m-%d" if format_name == "yyyy-MM-dd" else "%d/%m/%Y"
    if include_time: pattern += " %H:%M:%S"
    return value.strftime(pattern)


def mouse_position(cancel_event: Event, mouse: MouseController) -> dict[str, int]:
    if cancel_event.is_set(): raise ExecutionCancelled()
    try:
        x, y = mouse.position()
        return {"x": x, "y": y}
    except Exception:
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED) from None
