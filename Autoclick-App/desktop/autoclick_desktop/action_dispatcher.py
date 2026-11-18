from pathlib import PureWindowsPath
from threading import Event
from pydantic import JsonValue

from autoclick_desktop.excel_actions import ExcelResourceManager, ResourceCleanupOutcome
from typing import Callable

from autoclick_desktop.execution_actions import handle_browser_open, handle_run_application, handle_stop, handle_wait
from autoclick_desktop.execution_context import LocalPathInspector, VirtualDesktopBounds, VirtualDesktopProvider
from autoclick_desktop.execution_errors import (
    ExecutionCancelled,
    ExecutionErrorCode,
    HandlerError,
    PublishedSaveAsError,
    PublishedSaveAsCancellation,
)
from autoclick_desktop.execution_models import (
    ResolvedAction,
    RuntimeValidationState,
    ValidatedAction,
)
from autoclick_desktop.execution_validation import WindowsLocalPathInspector
from autoclick_desktop.keyboard_actions import (
    Clipboard,
    CleanupWarnings,
    KeyboardController,
    PyAutoGuiKeyboard,
    WindowsClipboard,
    handle_keyboard_press,
    handle_keyboard_write,
)
from autoclick_desktop.mouse_actions import (
    MouseController,
    PyAutoGuiMouse,
    WindowsVirtualDesktop,
    handle_mouse_click,
    handle_mouse_double_click,
    handle_mouse_move,
    handle_mouse_right_click,
)
from autoclick_desktop.variable_actions import handle_variable_create, handle_variable_delete, handle_variable_update
from autoclick_desktop.file_actions import handle_file
from autoclick_desktop.misc_actions import current_date, current_user, handle_clipboard, mouse_position
from autoclick_desktop.platform_adapters import LocalOperatingSystem, OperatingSystemAdapter, PyGetWindowAdapter, WindowAdapter, module_available
from autoclick_desktop.window_actions import handle_window
from autoclick_desktop.handler_keys import HANDLER_KEYS
from autoclick_desktop.http_actions import HttpAdapter, UrllibHttpAdapter, handle_http_request
from autoclick_desktop.vision_actions import (
    OcrEngineAdapter,
    ScreenCaptureProvider,
    handle_vision_detect_element,
)


Handler = Callable[[ResolvedAction], object | None]

WINDOW_HANDLER_KEYS = frozenset(key for key in HANDLER_KEYS if key.startswith("window."))
EXCEL_HANDLER_KEYS = frozenset(key for key in HANDLER_KEYS if key.startswith("excel."))
MOUSE_HANDLER_KEYS = frozenset(key for key in HANDLER_KEYS if key.startswith("mouse."))
KEYBOARD_HANDLER_KEYS = frozenset(key for key in HANDLER_KEYS if key.startswith("keyboard."))
CLIPBOARD_HANDLER_KEYS = frozenset(key for key in HANDLER_KEYS if key.startswith("clipboard."))


def available_handler_keys(
    *,
    mouse: MouseController | None = None,
    keyboard: KeyboardController | None = None,
    clipboard: Clipboard | None = None,
    excel: ExcelResourceManager | None = None,
    operating_system: OperatingSystemAdapter | None = None,
    windows: WindowAdapter | None = None,
) -> frozenset[str]:
    available = set(HANDLER_KEYS)
    if not _adapter_available(windows, module="pygetwindow"):
        available.difference_update(WINDOW_HANDLER_KEYS)
    if not _adapter_available(mouse, module="pyautogui"):
        available.difference_update(MOUSE_HANDLER_KEYS)
    if not _adapter_available(keyboard, module="pyautogui"):
        available.difference_update(KEYBOARD_HANDLER_KEYS)
    if not _adapter_available(clipboard, module="win32clipboard"):
        available.difference_update(CLIPBOARD_HANDLER_KEYS)
    if excel is None or not _adapter_available(excel):
        available.difference_update(EXCEL_HANDLER_KEYS)
    operating_system = operating_system or LocalOperatingSystem()
    for key in ("execution.run_application", "browser.open", "folder.open"):
        probe = getattr(operating_system, "is_handler_available", None)
        if not _adapter_available(operating_system) or (probe is not None and not bool(probe(key))):
            available.discard(key)
    return frozenset(available)


def _adapter_available(adapter: object | None, *, module: str | None = None) -> bool:
    if adapter is None:
        return module is not None and module_available(module)
    probe = getattr(adapter, "is_available", None)
    if probe is None:
        return True
    try:
        return bool(probe())
    except Exception:
        return False


class _ScaledMouse:
    def __init__(self, mouse: MouseController, desktop: VirtualDesktopProvider, base: tuple[int, int]) -> None:
        self._mouse, self._bounds, self._base = mouse, desktop.get_bounds(), base

    def _to_screen(self, x: int, y: int) -> tuple[int, int]:
        width, height = self._base
        scaled_x = 0 if width == 1 else round(x * (self._bounds.width - 1) / (width - 1))
        scaled_y = 0 if height == 1 else round(y * (self._bounds.height - 1) / (height - 1))
        return self._bounds.left + scaled_x, self._bounds.top + scaled_y

    def position(self) -> tuple[int, int]:
        x, y = self._mouse.position()
        width, height = self._base
        scaled_x = 0 if self._bounds.width == 1 else round((x - self._bounds.left) * (width - 1) / (self._bounds.width - 1))
        scaled_y = 0 if self._bounds.height == 1 else round((y - self._bounds.top) * (height - 1) / (self._bounds.height - 1))
        return scaled_x, scaled_y

    def move_to(self, x: int, y: int, duration: float) -> None:
        self._mouse.move_to(*self._to_screen(x, y), duration)

    def click(self, *, button: str, x: int | None = None, y: int | None = None) -> None:
        if x is not None and y is not None: x, y = self._to_screen(x, y)
        self._mouse.click(button=button, x=x, y=y)

    def double_click(self, *, button: str, interval: float, x: int | None = None, y: int | None = None) -> None:
        if x is not None and y is not None: x, y = self._to_screen(x, y)
        self._mouse.double_click(button=button, interval=interval, x=x, y=y)


class HandlerRegistry:
    def __init__(self) -> None:
        self._handlers: dict[str, Handler] = {}

    def register(self, key: str, handler: Handler) -> None:
        if key in self._handlers:
            raise ValueError(f"duplicate handler key: {key}")
        self._handlers[key] = handler

    def get(self, key: str) -> Handler | None:
        return self._handlers.get(key)

    @property
    def keys(self) -> frozenset[str]:
        return frozenset(self._handlers)


class ActionDispatcher:
    """Resolves a preflight action immediately before invoking its sealed handler."""

    def __init__(
        self,
        *,
        variables: dict[str, JsonValue],
        bot_directory: PureWindowsPath,
        cancel_event: Event,
        virtual_desktop: VirtualDesktopProvider | None = None,
        local_paths: LocalPathInspector | None = None,
        validation_state: RuntimeValidationState | None = None,
        mouse: MouseController | None = None,
        keyboard: KeyboardController | None = None,
        clipboard: Clipboard | None = None,
        excel: ExcelResourceManager | None = None,
        operating_system: OperatingSystemAdapter | None = None,
        windows: WindowAdapter | None = None,
        handlers: HandlerRegistry | None = None,
        http: HttpAdapter | None = None,
        vision_capture: ScreenCaptureProvider | None = None,
        vision_ocr: OcrEngineAdapter | None = None,
    ) -> None:
        self.variables = variables
        self.bot_directory = bot_directory
        self.cancel_event = cancel_event
        self.virtual_desktop = virtual_desktop or WindowsVirtualDesktop()
        self.local_paths = local_paths or WindowsLocalPathInspector()
        self.validation_state = validation_state or RuntimeValidationState()
        self._mouse = mouse
        self._keyboard = keyboard
        self._clipboard = clipboard
        self._cleanup_warnings = CleanupWarnings()
        self._excel = excel
        self._operating_system = operating_system or LocalOperatingSystem()
        self._windows = windows or PyGetWindowAdapter()
        self._vision_capture = vision_capture
        self._vision_ocr = vision_ocr
        self._base_resolution: tuple[int, int] | None = None
        self._cleanup_outcome = ResourceCleanupOutcome(True)
        self._cleanup_attempt_pending = False
        self._recoverable_failure_depth = 0
        self._http = http or UrllibHttpAdapter()
        self._handlers = handlers or self._default_handlers()

    def dispatch(self, action: ValidatedAction, *, bot_directory: PureWindowsPath | None = None) -> None:
        if self.cancel_event.is_set():
            self._cleanup_failure()
            raise ExecutionCancelled()
        resolved: ResolvedAction | None = None
        try:
            resolved = action.resolve(
                self.variables,
                bot_directory=bot_directory or self.bot_directory,
                virtual_desktop=self.virtual_desktop,
                validation_state=self.validation_state,
                local_paths=self.local_paths,
            )
            self._dispatch_resolved(resolved)
            if resolved.action_id == "excel.save" and resolved.params.get("path") not in (None, ""):
                if not resolved.commit_save_as_claim():
                    raise HandlerError(ExecutionErrorCode.RESOURCE_CLOSED)
            if self.cancel_event.is_set():
                raise ExecutionCancelled()
        except Exception as error:
            if resolved is not None:
                resolved.rollback_open_reservation()
                if resolved.action_id == "excel.close":
                    resolved.rollback_close_claim()
                if resolved.action_id == "excel.save":
                    if isinstance(error, (PublishedSaveAsError, PublishedSaveAsCancellation)):
                        if not resolved.retain_published_save_as_claim(error.identity):
                            error = HandlerError(ExecutionErrorCode.RESOURCE_CLOSED)
                    else:
                        resolved.rollback_save_as_claim()
            if isinstance(error, ExecutionCancelled) or self._recoverable_failure_depth == 0:
                self._cleanup_failure()
            raise error

    def begin_recoverable_failures(self) -> None:
        self._recoverable_failure_depth += 1

    def end_recoverable_failures(self) -> None:
        if self._recoverable_failure_depth < 1:
            raise RuntimeError("recoverable failure scope is not active")
        self._recoverable_failure_depth -= 1

    def _dispatch_resolved(self, action: ResolvedAction) -> None:
        key = action.handler_key
        handler = self._handlers.get(key)
        if handler is None:
            raise HandlerError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
        result = handler(action)
        output = action.params.get("outputVariable")
        if isinstance(output, str) and action.action_id not in {"excel.open", "excel.create"}:
            self.variables[output] = result  # type: ignore[assignment]
            if isinstance(result, dict):
                for sub_key, sub_val in result.items():
                    if isinstance(sub_val, (str, int, float, bool)) or sub_val is None:
                        self.variables[f"{output}_{sub_key}"] = sub_val  # type: ignore[assignment]
                        if sub_key.lower() != sub_key:
                            self.variables[f"{output}_{sub_key.lower()}"] = sub_val  # type: ignore[assignment]

    def _default_handlers(self) -> HandlerRegistry:
        registry = HandlerRegistry()
        register = registry.register
        register("execution.wait", lambda action: handle_wait(action, self.cancel_event))
        register("execution.stop", handle_stop)
        register("execution.run_application", lambda action: handle_run_application(action, self._operating_system))
        register("browser.open", lambda action: handle_browser_open(action, self._operating_system))
        register("variable.create", lambda action: handle_variable_create(action, self.variables))
        register("variable.update", lambda action: handle_variable_update(action, self.variables))
        register("variable.delete", lambda action: handle_variable_delete(action, self.variables))
        register("mouse.move", lambda action: handle_mouse_move(action, self.cancel_event, self._mouse_controller()))
        register("mouse.click", lambda action: handle_mouse_click(action, self.cancel_event, self._mouse_controller()))
        register("mouse.right_click", lambda action: handle_mouse_right_click(action, self.cancel_event, self._mouse_controller()))
        register("mouse.double_click", lambda action: handle_mouse_double_click(action, self.cancel_event, self._mouse_controller()))
        register("mouse.position", lambda _action: mouse_position(self.cancel_event, self._mouse_controller()))
        register("keyboard.press", lambda action: handle_keyboard_press(action, self.cancel_event, self._keyboard_controller(), self._cleanup_warnings))
        register("keyboard.write", lambda action: handle_keyboard_write(action, self.cancel_event, self._keyboard_controller(), self._clipboard_controller(), cleanup_warnings=self._cleanup_warnings))
        for key in ("clipboard.write", "clipboard.read", "clipboard.clear"):
            register(key, lambda action: handle_clipboard(action, self._clipboard_controller()))
        register("system.current_user", lambda _action: current_user())
        register("system.current_date", current_date)
        register("system.set_base_resolution", self._set_base_resolution)
        register("flow.comment", lambda _action: None)
        for key in ("flow.group", "flow.if", "flow.for_range", "flow.for_each", "flow.while", "flow.try_catch", "workflow.run", "flow.go_to"):
            register(key, lambda _action: None)
        register("http.request", lambda action: handle_http_request(action, self._http, self.cancel_event))
        register(
            "vision.detect_element",
            lambda action: handle_vision_detect_element(
                action,
                self.cancel_event,
                self._vision_capture,
                self._vision_ocr,
                base_resolution=self._base_resolution,
                desktop_bounds=self._safe_desktop_bounds(),
            ),
        )
        for key in ("window.focus", "window.wait", "window.move", "window.maximize", "window.minimize", "window.resize", "window.close"):
            register(key, lambda action: handle_window(action, self.cancel_event, self._windows))
        for key in ("file.read", "file.write", "file.copy", "file.move", "file.delete", "file.rename", "file.exists", "folder.create", "folder.list_files", "folder.delete", "folder.move", "folder.rename", "folder.open"):
            register(key, lambda action: handle_file(action, self._operating_system))
        register("excel.open", lambda action: self._excel_manager().open(action))
        register("excel.create", lambda action: self._excel_manager().create(action))
        register("excel.read_cell", lambda action: self._excel_manager().read_cell(action))
        register("excel.write_cell", lambda action: self._excel_manager().write_cell(action))
        register("excel.save", lambda action: self._excel_manager().save(action))
        register("excel.close", lambda action: self._excel_manager().close(action))
        for key in ("excel.add_worksheet", "excel.delete_worksheet", "excel.rename_worksheet", "excel.activate_worksheet", "excel.select_cell", "excel.select_range", "excel.clear_cell", "excel.read_range", "excel.write_range", "excel.delete_empty_rows", "excel.find_values", "excel.last_row", "excel.last_column"):
            register(key, lambda action: self._excel_manager().operate(action))
        if registry.keys != HANDLER_KEYS:
            raise RuntimeError("default handler registry is incomplete")
        return registry

    def _safe_desktop_bounds(self) -> VirtualDesktopBounds | None:
        try:
            return self.virtual_desktop.get_bounds()
        except Exception:
            return None

    def _set_base_resolution(self, action: ResolvedAction) -> None:
        self._base_resolution = int(action.params["width"]), int(action.params["height"])
        action.set_base_resolution(*self._base_resolution)

    def close(self) -> ResourceCleanupOutcome:
        if self._cleanup_attempt_pending:
            self._cleanup_attempt_pending = False
            return self._cleanup_outcome
        if self._excel is not None:
            self._record_cleanup(self._excel.shutdown())
        return self._cleanup_outcome

    def consume_cleanup_warning(self) -> bool:
        if self._cleanup_warnings.consume():
            return True
        return self._excel is not None and self._excel.consume_cleanup_warning()

    def _cleanup_failure(self) -> None:
        if self._excel is not None:
            self._record_cleanup(self._excel.shutdown())
            self._cleanup_attempt_pending = True

    def _record_cleanup(self, outcome: ResourceCleanupOutcome) -> None:
        self._cleanup_outcome = self._cleanup_outcome.merge(outcome)

    def _mouse_controller(self) -> MouseController:
        if self._mouse is None:
            try:
                self._mouse = PyAutoGuiMouse()
            except Exception:
                raise HandlerError(
                    ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE
                ) from None
        if self._base_resolution is not None:
            return _ScaledMouse(self._mouse, self.virtual_desktop, self._base_resolution)
        return self._mouse

    def _keyboard_controller(self) -> KeyboardController:
        if self._keyboard is None:
            try:
                self._keyboard = PyAutoGuiKeyboard()
            except Exception:
                raise HandlerError(
                    ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE
                ) from None
        return self._keyboard

    def _clipboard_controller(self) -> Clipboard:
        if self._clipboard is None:
            try:
                self._clipboard = WindowsClipboard()
            except Exception:
                raise HandlerError(
                    ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE
                ) from None
        return self._clipboard

    def _excel_manager(self) -> ExcelResourceManager:
        if self._excel is None:
            self._excel = ExcelResourceManager(self.cancel_event, self.local_paths)
        return self._excel
