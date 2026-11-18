from __future__ import annotations

import ctypes
import math
import sys
import threading
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Callable, Protocol, TypedDict, cast


WH_MOUSE_LL = 14
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
VK_ESCAPE = 0x1B
VK_LBUTTON = 0x01
PM_REMOVE = 0x0001
LLMHF_INJECTED = 0x00000001
LLMHF_LOWER_IL_INJECTED = 0x00000002
MAX_MESSAGES_PER_PUMP = 8
BUTTON_RELEASE_GRACE_SECONDS = 0.5
QS_ALLINPUT = 0x04FF
MWMO_INPUTAVAILABLE = 0x0004
WAIT_OBJECT_0 = 0x00000000
WAIT_TIMEOUT = 0x00000102
WAIT_FAILED = 0xFFFFFFFF


class MousePosition(TypedDict):
    x: int
    y: int


class CoordinateCaptureErrorCode(StrEnum):
    CAPTURE_CANCELLED = "CAPTURE_CANCELLED"
    CAPTURE_TIMEOUT = "CAPTURE_TIMEOUT"
    CAPTURE_ALREADY_ACTIVE = "CAPTURE_ALREADY_ACTIVE"
    CAPTURE_ENVIRONMENT_UNAVAILABLE = "CAPTURE_ENVIRONMENT_UNAVAILABLE"
    CAPTURE_SHUTTING_DOWN = "CAPTURE_SHUTTING_DOWN"


_SAFE_MESSAGES: dict[CoordinateCaptureErrorCode, str] = {
    CoordinateCaptureErrorCode.CAPTURE_CANCELLED: "La selección fue cancelada.",
    CoordinateCaptureErrorCode.CAPTURE_TIMEOUT: "La selección agotó el tiempo de espera.",
    CoordinateCaptureErrorCode.CAPTURE_ALREADY_ACTIVE: "Ya hay una selección activa.",
    CoordinateCaptureErrorCode.CAPTURE_ENVIRONMENT_UNAVAILABLE: "La selección en pantalla no está disponible.",
    CoordinateCaptureErrorCode.CAPTURE_SHUTTING_DOWN: "La aplicación se está cerrando.",
}


class CoordinateCaptureError(Exception):
    """Fixed, payload-free capture failure safe to expose through the bridge."""

    def __init__(self, code: CoordinateCaptureErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)


HookCallback = Callable[[int, int, int], int]


class _Win32Adapter(Protocol):
    def create_hook_callback(self, callback: HookCallback) -> HookCallback: ...

    def install_hook(self, callback: HookCallback) -> object: ...

    def call_next_hook(self, handle: object | None, code: int, message: int, data: int) -> int: ...

    def unhook(self, handle: object) -> bool: ...

    def pump_messages(self, max_messages: int) -> int: ...

    def wait_for_input(self, timeout_seconds: float) -> bool: ...

    def escape_is_down(self) -> bool: ...

    def left_button_is_down(self) -> bool: ...

    def mouse_event_from_hook_data(self, data: int) -> tuple[int, int, bool]: ...

    def virtual_screen_metrics(self) -> tuple[int, int, int, int]: ...


@dataclass(slots=True)
class _CaptureState:
    cancel: threading.Event = field(default_factory=threading.Event)
    terminal: threading.Event = field(default_factory=threading.Event)
    started: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    hook: object | None = None
    callback: HookCallback | None = None
    pressed_position: MousePosition | None = None
    selected_sequence_complete: bool = False
    release_grace_deadline: float | None = None
    position: MousePosition | None = None
    failure: CoordinateCaptureError | None = None


_PROCESS_LOCK = threading.Lock()
_PROCESS_ACTIVE: _CaptureState | None = None


class CoordinateCaptureService:
    def __init__(
        self,
        adapter: _Win32Adapter | None = None,
        *,
        poll_interval_seconds: float = 0.01,
        unhook_retry_interval_seconds: float = 0.05,
    ) -> None:
        self._adapter = adapter
        self._poll_interval = poll_interval_seconds
        self._unhook_retry_interval = unhook_retry_interval_seconds
        self._shutting_down = False

    def capture(self, timeout_seconds: float = 30.0) -> MousePosition:
        global _PROCESS_ACTIVE

        state = _CaptureState()
        thread = threading.Thread(
            target=self._run_capture,
            args=(state, max(0.0, timeout_seconds)),
            name="coordinate-capture",
            daemon=False,
        )
        state.thread = thread
        with _PROCESS_LOCK:
            if self._shutting_down:
                raise CoordinateCaptureError(
                    CoordinateCaptureErrorCode.CAPTURE_SHUTTING_DOWN
                )
            if _PROCESS_ACTIVE is not None:
                raise CoordinateCaptureError(
                    CoordinateCaptureErrorCode.CAPTURE_ALREADY_ACTIVE
                )
            _PROCESS_ACTIVE = state

        try:
            thread.start()
            state.started.set()
        except BaseException:
            with _PROCESS_LOCK:
                if _PROCESS_ACTIVE is state:
                    _PROCESS_ACTIVE = None
            state.started.set()
            state.done.set()
            raise CoordinateCaptureError(
                CoordinateCaptureErrorCode.CAPTURE_ENVIRONMENT_UNAVAILABLE
            ) from None

        state.done.wait()
        thread.join()
        if state.failure is not None:
            raise state.failure
        if state.position is None:
            raise CoordinateCaptureError(
                CoordinateCaptureErrorCode.CAPTURE_ENVIRONMENT_UNAVAILABLE
            )
        return state.position

    def cancel_and_wait(self, timeout: float) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        with _PROCESS_LOCK:
            state = _PROCESS_ACTIVE
            if state is None:
                return True
            state.cancel.set()
            thread = state.thread

        if thread is None:
            return False
        if not state.started.wait(max(0.0, deadline - time.monotonic())):
            return False
        if not thread.ident:
            return state.done.is_set()
        thread.join(max(0.0, deadline - time.monotonic()))
        if thread.is_alive() or not state.done.is_set():
            return False
        with _PROCESS_LOCK:
            return _PROCESS_ACTIVE is not state

    def shutdown(self, timeout: float) -> bool:
        with _PROCESS_LOCK:
            self._shutting_down = True
        return self.cancel_and_wait(timeout)

    def is_active(self) -> bool:
        with _PROCESS_LOCK:
            return _PROCESS_ACTIVE is not None

    def _run_capture(self, state: _CaptureState, timeout_seconds: float) -> None:
        adapter = self._adapter
        try:
            if adapter is None:
                adapter = _CtypesWin32Adapter()

            def request_terminal(error: CoordinateCaptureError) -> None:
                if state.failure is None:
                    state.failure = error
                if (
                    state.pressed_position is None
                    or state.selected_sequence_complete
                ):
                    state.terminal.set()
                elif state.release_grace_deadline is None:
                    state.release_grace_deadline = (
                        time.monotonic() + BUTTON_RELEASE_GRACE_SECONDS
                    )

            def hook_callback(code: int, message: int, data: int) -> int:
                try:
                    if state.terminal.is_set() or state.selected_sequence_complete:
                        return adapter.call_next_hook(state.hook, code, message, data)
                    if code < 0:
                        return adapter.call_next_hook(state.hook, code, message, data)
                    if message in (WM_LBUTTONDOWN, WM_LBUTTONUP):
                        x, y, injected = adapter.mouse_event_from_hook_data(data)
                        if injected:
                            return adapter.call_next_hook(
                                state.hook, code, message, data
                            )
                    if message == WM_LBUTTONDOWN and state.pressed_position is None:
                        left, top, width, height = adapter.virtual_screen_metrics()
                        if not (
                            width > 0
                            and height > 0
                            and left <= x < left + width
                            and top <= y < top + height
                        ):
                            raise OSError("captured point outside virtual screen")
                        state.pressed_position = {"x": x, "y": y}
                        return 1
                    if state.pressed_position is not None:
                        if message == WM_LBUTTONUP:
                            state.position = state.pressed_position
                            state.selected_sequence_complete = True
                            state.terminal.set()
                            return 1
                        if message == WM_LBUTTONDOWN:
                            return 1
                    return adapter.call_next_hook(state.hook, code, message, data)
                except BaseException:
                    request_terminal(
                        CoordinateCaptureError(
                            CoordinateCaptureErrorCode.CAPTURE_ENVIRONMENT_UNAVAILABLE
                        )
                    )
                    try:
                        return adapter.call_next_hook(state.hook, code, message, data)
                    except BaseException:
                        return 0

            state.callback = adapter.create_hook_callback(hook_callback)
            hook = adapter.install_hook(state.callback)
            if not hook:
                raise OSError("hook installation failed")
            state.hook = hook

            deadline = time.monotonic() + timeout_seconds
            while not state.terminal.is_set():
                if state.failure is None:
                    if state.cancel.is_set():
                        request_terminal(
                            CoordinateCaptureError(
                                CoordinateCaptureErrorCode.CAPTURE_CANCELLED
                            )
                        )
                    elif time.monotonic() >= deadline:
                        request_terminal(
                            CoordinateCaptureError(
                                CoordinateCaptureErrorCode.CAPTURE_TIMEOUT
                            )
                        )
                    elif adapter.escape_is_down():
                        request_terminal(
                            CoordinateCaptureError(
                                CoordinateCaptureErrorCode.CAPTURE_CANCELLED
                            )
                        )
                if state.release_grace_deadline is not None:
                    if time.monotonic() >= state.release_grace_deadline:
                        state.selected_sequence_complete = True
                        state.terminal.set()
                if state.terminal.is_set():
                    break
                processed = adapter.pump_messages(MAX_MESSAGES_PER_PUMP)
                if (
                    not state.terminal.is_set()
                    and state.release_grace_deadline is not None
                    and (
                        not adapter.left_button_is_down()
                        or time.monotonic() >= state.release_grace_deadline
                    )
                ):
                    state.selected_sequence_complete = True
                    state.terminal.set()
                if not state.terminal.is_set():
                    if processed >= MAX_MESSAGES_PER_PUMP:
                        continue
                    poll_seconds = max(self._poll_interval, 0.001)
                    wait_seconds = (
                        min(
                            poll_seconds,
                            max(
                                0.0,
                                state.release_grace_deadline - time.monotonic(),
                            ),
                        )
                        if state.release_grace_deadline is not None
                        else min(
                            poll_seconds,
                            max(0.0, deadline - time.monotonic()),
                        )
                    )
                    adapter.wait_for_input(wait_seconds)
        except BaseException:
            if state.failure is None:
                state.failure = CoordinateCaptureError(
                    CoordinateCaptureErrorCode.CAPTURE_ENVIRONMENT_UNAVAILABLE
                )
        finally:
            if state.hook is not None:
                retry_interval = max(self._unhook_retry_interval, 0.001)
                retry_deadline = time.monotonic()
                while True:
                    now = time.monotonic()
                    if now >= retry_deadline:
                        try:
                            unhooked = bool(adapter and adapter.unhook(state.hook))
                        except BaseException:
                            unhooked = False
                        if unhooked:
                            break
                        retry_deadline = time.monotonic() + retry_interval
                    try:
                        processed = adapter.pump_messages(MAX_MESSAGES_PER_PUMP)
                    except BaseException:
                        processed = 0
                    if processed >= MAX_MESSAGES_PER_PUMP:
                        continue
                    wait_seconds = max(0.0, retry_deadline - time.monotonic())
                    try:
                        adapter.wait_for_input(wait_seconds)
                    except BaseException:
                        time.sleep(wait_seconds)
            state.callback = None
            global _PROCESS_ACTIVE
            with _PROCESS_LOCK:
                if _PROCESS_ACTIVE is state:
                    _PROCESS_ACTIVE = None
            state.done.set()


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int32), ("y", ctypes.c_int32)]


class _MSLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("pt", _POINT),
        ("mouseData", ctypes.c_uint32),
        ("flags", ctypes.c_uint32),
        ("time", ctypes.c_uint32),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _CtypesWin32Adapter:
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise OSError("Windows capture unavailable")
        from ctypes import wintypes

        self._wintypes = wintypes
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        callback_factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        self._callback_type = callback_factory(
            ctypes.c_ssize_t,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        )

        self._user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int,
            self._callback_type,
            wintypes.HINSTANCE,
            wintypes.DWORD,
        ]
        self._user32.SetWindowsHookExW.restype = wintypes.HHOOK
        self._user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK,
            ctypes.c_int,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        self._user32.CallNextHookEx.restype = ctypes.c_ssize_t
        self._user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        self._user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        self._user32.PeekMessageW.argtypes = [
            ctypes.POINTER(wintypes.MSG),
            wintypes.HWND,
            wintypes.UINT,
            wintypes.UINT,
            wintypes.UINT,
        ]
        self._user32.PeekMessageW.restype = wintypes.BOOL
        self._user32.MsgWaitForMultipleObjectsEx.argtypes = [
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.DWORD,
        ]
        self._user32.MsgWaitForMultipleObjectsEx.restype = wintypes.DWORD
        self._user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
        self._user32.GetAsyncKeyState.restype = ctypes.c_short
        self._user32.GetSystemMetrics.argtypes = [ctypes.c_int]
        self._user32.GetSystemMetrics.restype = ctypes.c_int
        self._kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
        self._kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    def create_hook_callback(self, callback: HookCallback) -> HookCallback:
        return cast(HookCallback, self._callback_type(callback))

    def install_hook(self, callback: HookCallback) -> object:
        module = self._kernel32.GetModuleHandleW(None)
        return self._user32.SetWindowsHookExW(WH_MOUSE_LL, callback, module, 0)

    def call_next_hook(self, handle: object | None, code: int, message: int, data: int) -> int:
        return int(self._user32.CallNextHookEx(handle, code, message, data))

    def unhook(self, handle: object) -> bool:
        return bool(self._user32.UnhookWindowsHookEx(handle))

    def pump_messages(self, max_messages: int) -> int:
        message = self._wintypes.MSG()
        processed = 0
        while processed < max_messages and self._user32.PeekMessageW(
            ctypes.byref(message), None, 0, 0, PM_REMOVE
        ):
            self._user32.TranslateMessage(ctypes.byref(message))
            self._user32.DispatchMessageW(ctypes.byref(message))
            processed += 1
        return processed

    def wait_for_input(self, timeout_seconds: float) -> bool:
        timeout_milliseconds = min(
            math.ceil(max(0.0, timeout_seconds) * 1000),
            WAIT_FAILED - 1,
        )
        result = int(
            self._user32.MsgWaitForMultipleObjectsEx(
                0,
                None,
                timeout_milliseconds,
                QS_ALLINPUT,
                MWMO_INPUTAVAILABLE,
            )
        )
        if result == WAIT_OBJECT_0:
            return True
        if result == WAIT_TIMEOUT:
            return False
        if result == WAIT_FAILED:
            raise OSError(ctypes.get_last_error(), "input wait failed")
        raise OSError("unexpected input wait result")

    def escape_is_down(self) -> bool:
        return bool(self._user32.GetAsyncKeyState(VK_ESCAPE) & 0x8000)

    def left_button_is_down(self) -> bool:
        return bool(self._user32.GetAsyncKeyState(VK_LBUTTON) & 0x8000)

    def mouse_event_from_hook_data(self, data: int) -> tuple[int, int, bool]:
        event = ctypes.cast(data, ctypes.POINTER(_MSLLHOOKSTRUCT)).contents
        injected = bool(
            event.flags & (LLMHF_INJECTED | LLMHF_LOWER_IL_INJECTED)
        )
        return int(event.pt.x), int(event.pt.y), injected

    def virtual_screen_metrics(self) -> tuple[int, int, int, int]:
        return (
            self._user32.GetSystemMetrics(self.SM_XVIRTUALSCREEN),
            self._user32.GetSystemMetrics(self.SM_YVIRTUALSCREEN),
            self._user32.GetSystemMetrics(self.SM_CXVIRTUALSCREEN),
            self._user32.GetSystemMetrics(self.SM_CYVIRTUALSCREEN),
        )
