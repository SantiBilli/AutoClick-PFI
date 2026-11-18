from dataclasses import dataclass, field
import importlib
from threading import Event, Lock
from typing import Protocol

from autoclick_desktop.execution_errors import (
    ExecutionCancelled,
    ExecutionErrorCode,
    HandlerError,
)
from autoclick_desktop.execution_models import ResolvedAction


DIRECT_CHARACTERS = frozenset(chr(codepoint) for codepoint in range(32, 127))


class KeyboardController(Protocol):
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...
    def press(self, key: str) -> None: ...
    def write(self, text: str) -> None: ...


@dataclass(frozen=True, slots=True)
class ClipboardItem:
    format_id: int
    data: str | bytes = field(repr=False)


@dataclass(frozen=True, slots=True)
class ClipboardSnapshot:
    items: tuple[ClipboardItem, ...] = field(repr=False)


class Clipboard(Protocol):
    def snapshot(self) -> ClipboardSnapshot: ...
    def set_text(self, text: str) -> None: ...
    def restore(self, snapshot: ClipboardSnapshot) -> None: ...
    def read_text(self) -> str: ...
    def clear(self) -> None: ...


class CleanupWarningRecorder(Protocol):
    def record(self) -> None: ...


class CleanupWarnings:
    """Counts cleanup problems without retaining keys, paths, or clipboard content."""

    def __init__(self) -> None:
        self._count = 0
        self._lock = Lock()

    def record(self) -> None:
        with self._lock:
            self._count += 1

    def consume(self) -> bool:
        with self._lock:
            if self._count == 0:
                return False
            self._count -= 1
            return True


class _IgnoreCleanupWarnings:
    def record(self) -> None:
        pass


_IGNORE_CLEANUP_WARNINGS = _IgnoreCleanupWarnings()


class PyAutoGuiKeyboard:
    def __init__(self, module: object | None = None) -> None:
        self._module = module or importlib.import_module("pyautogui")
        self._module.FAILSAFE = False

    def key_down(self, key: str) -> None:
        self._module.keyDown(key)

    def key_up(self, key: str) -> None:
        self._module.keyUp(key)

    def press(self, key: str) -> None:
        self._module.press(key)

    def write(self, text: str) -> None:
        self._module.write(text, interval=0)


class WindowsClipboard:
    """Snapshots every clipboard format that pywin32 can safely round-trip."""

    def __init__(self, module: object | None = None) -> None:
        self._module = module

    def _api(self) -> object:
        if self._module is None:
            self._module = importlib.import_module("win32clipboard")
        return self._module

    def snapshot(self) -> ClipboardSnapshot:
        api = self._api()
        opened = False
        items: list[ClipboardItem] = []
        failure: Exception | None = None
        try:
            api.OpenClipboard()
            opened = True
            format_id = 0
            while True:
                format_id = int(api.EnumClipboardFormats(format_id))
                if format_id == 0:
                    break
                data = api.GetClipboardData(format_id)
                if type(data) not in {str, bytes}:
                    raise TypeError("clipboard format is not safely restorable")
                items.append(ClipboardItem(format_id, data[:] if isinstance(data, bytes) else data))
        except Exception as error:
            failure = error
        finally:
            if opened:
                try:
                    api.CloseClipboard()
                except Exception as error:
                    failure = failure or error
        if failure is not None:
            raise HandlerError(ExecutionErrorCode.CLIPBOARD_UNAVAILABLE) from None
        return ClipboardSnapshot(tuple(items))

    def set_text(self, text: str) -> None:
        api = self._api()
        opened = False
        failure: Exception | None = None
        try:
            api.OpenClipboard()
            opened = True
            api.EmptyClipboard()
            api.SetClipboardData(api.CF_UNICODETEXT, text)
        except Exception as error:
            failure = error
        finally:
            if opened:
                try:
                    api.CloseClipboard()
                except Exception as error:
                    failure = failure or error
        if failure is not None:
            raise HandlerError(ExecutionErrorCode.CLIPBOARD_UNAVAILABLE) from None

    def restore(self, snapshot: ClipboardSnapshot) -> None:
        api = self._api()
        opened = False
        failed = False
        try:
            api.OpenClipboard()
            opened = True
            try:
                api.EmptyClipboard()
            except Exception:
                failed = True
            for item in snapshot.items:
                try:
                    api.SetClipboardData(item.format_id, item.data)
                except Exception:
                    failed = True
        except Exception:
            failed = True
        finally:
            if opened:
                try:
                    api.CloseClipboard()
                except Exception:
                    failed = True
        if failed:
            raise HandlerError(ExecutionErrorCode.CLIPBOARD_UNAVAILABLE)

    def read_text(self) -> str:
        api = self._api()
        opened = False
        value: str | None = None
        failure: Exception | None = None
        try:
            api.OpenClipboard()
            opened = True
            candidate = api.GetClipboardData(api.CF_UNICODETEXT)
            if not isinstance(candidate, str):
                raise TypeError
            value = candidate
        except Exception as error:
            failure = error
        finally:
            if opened:
                try:
                    api.CloseClipboard()
                except Exception as error:
                    failure = failure or error
        if failure is not None or value is None:
            raise HandlerError(ExecutionErrorCode.CLIPBOARD_UNAVAILABLE) from None
        return value

    def clear(self) -> None:
        api = self._api()
        opened = False
        failure: Exception | None = None
        try:
            api.OpenClipboard()
            opened = True
            api.EmptyClipboard()
        except Exception as error:
            failure = error
        finally:
            if opened:
                try:
                    api.CloseClipboard()
                except Exception as error:
                    failure = failure or error
        if failure is not None:
            raise HandlerError(ExecutionErrorCode.CLIPBOARD_UNAVAILABLE) from None


def _check_cancel(cancel_event: Event) -> None:
    if cancel_event.is_set():
        raise ExecutionCancelled()


def _release_keys(
    keyboard: KeyboardController, keys: list[str], *, attempts: int = 2
) -> bool:
    failed = False
    for key in reversed(keys):
        released = False
        for _attempt in range(attempts):
            try:
                keyboard.key_up(key)
                released = True
                break
            except Exception:
                pass
        if not released:
            failed = True
    return failed


def handle_keyboard_press(
    action: ResolvedAction,
    cancel_event: Event,
    keyboard: KeyboardController,
    cleanup_warnings: CleanupWarningRecorder | None = None,
) -> None:
    warnings = cleanup_warnings or _IGNORE_CLEANUP_WARNINGS
    parts = str(action.params["key"]).split("+")
    modifiers, key = parts[:-1], parts[-1]
    pressed: list[str] = []
    failure: Exception | None = None
    try:
        _check_cancel(cancel_event)
        for modifier in modifiers:
            pressed.append(modifier)
            keyboard.key_down(modifier)
            _check_cancel(cancel_event)
        keyboard.press(key)
        _check_cancel(cancel_event)
    except ExecutionCancelled as error:
        failure = error
    except Exception:
        failure = HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED)
    if _release_keys(keyboard, pressed):
        if failure is not None:
            warnings.record()
            raise failure
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED)
    if failure is not None:
        raise failure


def _paste(
    keyboard: KeyboardController,
    clipboard: Clipboard,
    text: str,
    cleanup_warnings: CleanupWarningRecorder,
) -> None:
    clipboard.set_text(text)
    pressed: list[str] = []
    failure: Exception | None = None
    try:
        pressed.append("ctrl")
        keyboard.key_down("ctrl")
        keyboard.press("v")
    except Exception:
        failure = HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED)
    if _release_keys(keyboard, pressed):
        if failure is not None:
            cleanup_warnings.record()
            raise failure
        raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED)
    if failure is not None:
        raise failure


def handle_keyboard_write(
    action: ResolvedAction,
    cancel_event: Event,
    keyboard: KeyboardController,
    clipboard: Clipboard,
    *,
    paste_chunk_size: int = 256,
    cleanup_warnings: CleanupWarningRecorder | None = None,
) -> None:
    warnings = cleanup_warnings or _IGNORE_CLEANUP_WARNINGS
    text = str(action.params["text"])
    interval = int(action.params.get("intervalMs", 0)) / 1000
    _check_cancel(cancel_event)
    if all(character in DIRECT_CHARACTERS for character in text):
        try:
            for character in text:
                _check_cancel(cancel_event)
                keyboard.write(character)
                if interval and cancel_event.wait(interval):
                    raise ExecutionCancelled()
        except ExecutionCancelled:
            raise
        except Exception:
            raise HandlerError(ExecutionErrorCode.DESKTOP_INPUT_FAILED) from None
        return

    snapshot = clipboard.snapshot()
    failure: Exception | None = None
    try:
        for offset in range(0, len(text), paste_chunk_size):
            _check_cancel(cancel_event)
            _paste(
                keyboard,
                clipboard,
                text[offset : offset + paste_chunk_size],
                warnings,
            )
            if interval and cancel_event.wait(interval):
                raise ExecutionCancelled()
    except Exception as error:
        failure = error
    restored = False
    for _attempt in range(2):
        try:
            clipboard.restore(snapshot)
            restored = True
            break
        except Exception:
            pass
    if not restored:
        if failure is not None:
            warnings.record()
            raise failure
        raise HandlerError(ExecutionErrorCode.CLIPBOARD_UNAVAILABLE) from None
    if failure is not None:
        raise failure
