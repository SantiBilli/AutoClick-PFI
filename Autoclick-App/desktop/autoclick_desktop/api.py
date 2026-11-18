from collections.abc import Sequence
from contextlib import AbstractContextManager
import ctypes
import threading
import time
from typing import Generic, Literal, Protocol, TypeAlias, TypeVar, TypedDict, cast

from webview import FOLDER_DIALOG, OPEN_DIALOG, SAVE_DIALOG

from autoclick_desktop.action_registry import load_action_registry
from autoclick_desktop.bot_service import (
    BotCatalog,
    BotService,
    BotServiceError,
    EditorExecutionAuthorization,
    LoadedBot,
    SavedBot,
    SavedBotAi,
    SavedPendingAiProposal,
)
from autoclick_desktop.bot_schema import (
    CanonicalAiInput,
    CanonicalBotInput,
    CanonicalPendingAiProposalInput,
)
from autoclick_desktop.coordinate_capture import (
    CoordinateCaptureError,
    CoordinateCaptureService,
    MousePosition,
)
from autoclick_desktop.execution_errors import (
    ExecutionErrorCode,
    SafeExecutionError,
)
from autoclick_desktop.execution_service import (
    ExecutionCancelResult,
    ExecutionService,
    ExecutionStartResult,
    ExecutionStatusResult,
)


PickPathErrorCode = Literal["DESKTOP_BRIDGE_UNAVAILABLE"]

SelectDirectoryErrorCode = Literal[
    "DIRECTORY_SELECTION_CANCELLED",
    "DIRECTORY_UNAVAILABLE",
    "CATALOG_READ_FAILED",
    "DESKTOP_BRIDGE_UNAVAILABLE",
]
CatalogErrorCode = Literal["DIRECTORY_UNAVAILABLE", "CATALOG_READ_FAILED"]
LoadBotErrorCode = Literal[
    "BOT_ENTRY_NOT_FOUND",
    "BOT_LOAD_FAILED",
    "BOT_INVALID",
    "DIRECTORY_UNAVAILABLE",
]
CreateBotErrorCode = Literal[
    "BOT_INVALID",
    "BOT_SAVE_FAILED",
    "DIRECTORY_UNAVAILABLE",
]
DeleteBotErrorCode = Literal[
    "BOT_ENTRY_NOT_FOUND",
    "BOT_SAVE_FAILED",
    "DIRECTORY_UNAVAILABLE",
    "DESKTOP_BRIDGE_UNAVAILABLE",
]
SaveBotErrorCode = Literal[
    "BOT_ENTRY_NOT_FOUND",
    "BOT_INVALID",
    "BOT_CHANGED_EXTERNALLY",
    "BOT_SAVE_FAILED",
    "DIRECTORY_UNAVAILABLE",
]
SaveBotAiErrorCode = Literal[
    "BOT_ENTRY_NOT_FOUND",
    "BOT_AI_INVALID",
    "BOT_AI_TOO_LARGE",
    "BOT_CHANGED_EXTERNALLY",
    "BOT_AI_SAVE_FAILED",
]
SavePendingAiProposalErrorCode = Literal[
    "BOT_ENTRY_NOT_FOUND",
    "BOT_PENDING_AI_INVALID",
    "BOT_PENDING_AI_STALE",
    "BOT_PENDING_AI_TOO_LARGE",
    "BOT_CHANGED_EXTERNALLY",
    "BOT_PENDING_AI_SAVE_FAILED",
]
ExecuteBotErrorCode = Literal[
    "EXECUTION_ALREADY_ACTIVE",
    "EXECUTION_CAPTURE_ACTIVE",
    "EXECUTION_BOT_INVALID",
    "EXECUTION_UNSUPPORTED_ACTION",
    "EXECUTION_VARIABLE_INVALID",
    "EXECUTION_ENVIRONMENT_UNAVAILABLE",
    "EXECUTION_START_FAILED",
    "EXECUTION_SHUTTING_DOWN",
    "WORKFLOW_LOAD_FAILED",
    "WORKFLOW_CYCLE",
    "WORKFLOW_DEPTH_EXCEEDED",
    "WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED",
    "WORKFLOW_INVOCATION_LIMIT_EXCEEDED",
    "WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED",
    "WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED",
]
CancelExecutionErrorCode = Literal[
    "EXECUTION_NOT_FOUND", "EXECUTION_NOT_ACTIVE", "EXECUTION_STATUS_FAILED"
]
ExecutionStatusErrorCode = Literal["EXECUTION_NOT_FOUND", "EXECUTION_STATUS_FAILED"]
CaptureMouseErrorCode = Literal[
    "CAPTURE_CANCELLED",
    "CAPTURE_TIMEOUT",
    "CAPTURE_ALREADY_ACTIVE",
    "CAPTURE_ENVIRONMENT_UNAVAILABLE",
    "CAPTURE_SHUTTING_DOWN",
]
ResponseData = TypeVar("ResponseData")
ErrorCodeData = TypeVar("ErrorCodeData", bound=str)


class ApiError(TypedDict, Generic[ErrorCodeData]):
    code: ErrorCodeData
    message: str


class ApiSuccess(TypedDict, Generic[ResponseData]):
    ok: Literal[True]
    data: ResponseData
    error: None


class ApiFailure(TypedDict, Generic[ErrorCodeData]):
    ok: Literal[False]
    data: None
    error: ApiError[ErrorCodeData]


ApiResponse: TypeAlias = ApiSuccess[ResponseData] | ApiFailure[ErrorCodeData]
PickPathResponse: TypeAlias = ApiResponse[str | None, PickPathErrorCode]


class HealthData(TypedDict):
    status: str
    version: str


HealthResponse: TypeAlias = ApiSuccess[HealthData]
SelectDirectoryResponse: TypeAlias = ApiResponse[BotCatalog, SelectDirectoryErrorCode]
CatalogResponse: TypeAlias = ApiResponse[BotCatalog | None, CatalogErrorCode]
LoadBotResponse: TypeAlias = ApiResponse[LoadedBot, LoadBotErrorCode]
CreateBotResponse: TypeAlias = ApiResponse[LoadedBot, CreateBotErrorCode]
DeleteBotResponse: TypeAlias = ApiResponse[bool, DeleteBotErrorCode]
SaveBotResponse: TypeAlias = ApiResponse[SavedBot, SaveBotErrorCode]
SaveBotAiResponse: TypeAlias = ApiResponse[SavedBotAi, SaveBotAiErrorCode]
SavePendingAiProposalResponse: TypeAlias = ApiResponse[
    SavedPendingAiProposal, SavePendingAiProposalErrorCode
]
ExecuteBotResponse: TypeAlias = ApiResponse[ExecutionStartResult, ExecuteBotErrorCode]
CancelExecutionResponse: TypeAlias = ApiResponse[
    ExecutionCancelResult, CancelExecutionErrorCode
]
ExecutionStatusResponse: TypeAlias = ApiResponse[
    ExecutionStatusResult, ExecutionStatusErrorCode
]
CaptureMouseResponse: TypeAlias = ApiResponse[MousePosition, CaptureMouseErrorCode]


class BotCatalogService(Protocol):
    def select_directory(self, directory: str) -> BotCatalog: ...

    def get_catalog(self) -> BotCatalog | None: ...

    def load_bot(self, entry_id: str) -> LoadedBot: ...

    def create_bot(self, name: str) -> LoadedBot: ...

    def save_bot(
        self,
        editor_token: str,
        expected_revision: str,
        bot: CanonicalBotInput,
        clear_pending_ai_proposal: bool = False,
    ) -> SavedBot: ...

    def save_ai(
        self,
        editor_token: str,
        expected_revision: str,
        ai: CanonicalAiInput,
    ) -> SavedBotAi: ...

    def save_pending_ai_proposal(
        self,
        editor_token: str,
        expected_revision: str,
        pending: CanonicalPendingAiProposalInput | None,
    ) -> SavedPendingAiProposal: ...

    def authorize_execution(
        self, editor_token: str
    ) -> AbstractContextManager[EditorExecutionAuthorization]: ...


class DesktopWindow(Protocol):
    native: object

    def create_file_dialog(self, dialog_type: int) -> Sequence[str] | None: ...


class NativeWindowController(Protocol):
    def get_handle(self, window: DesktopWindow) -> int: ...

    def minimize(self, handle: int) -> None: ...

    def restore_and_focus(self, handle: int) -> None: ...


class _WindowsHwndController:
    SW_MINIMIZE = 6
    SW_RESTORE = 9

    def __init__(self) -> None:
        from ctypes import wintypes

        self._user32 = ctypes.WinDLL("user32", use_last_error=True)
        self._user32.IsWindow.argtypes = [wintypes.HWND]
        self._user32.IsWindow.restype = wintypes.BOOL
        self._user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
        self._user32.ShowWindow.restype = wintypes.BOOL
        self._user32.BringWindowToTop.argtypes = [wintypes.HWND]
        self._user32.BringWindowToTop.restype = wintypes.BOOL
        self._user32.SetForegroundWindow.argtypes = [wintypes.HWND]
        self._user32.SetForegroundWindow.restype = wintypes.BOOL

    def get_handle(self, window: DesktopWindow) -> int:
        native = getattr(window, "native", None)
        raw_handle = getattr(native, "Handle", None)
        to_int64 = getattr(raw_handle, "ToInt64", None)
        try:
            handle = int(to_int64() if callable(to_int64) else raw_handle)
        except (TypeError, ValueError, OverflowError):
            raise OSError("native window handle unavailable") from None
        self._validate(handle)
        return handle

    def minimize(self, handle: int) -> None:
        self._validate(handle)
        self._user32.ShowWindow(handle, self.SW_MINIMIZE)

    def restore_and_focus(self, handle: int) -> None:
        self._validate(handle)
        self._user32.ShowWindow(handle, self.SW_RESTORE)
        if not self._user32.BringWindowToTop(handle):
            raise OSError("native window activation failed")
        if not self._user32.SetForegroundWindow(handle):
            raise OSError("native window focus failed")

    def _validate(self, handle: int) -> None:
        if handle <= 0 or not self._user32.IsWindow(handle):
            raise OSError("native window handle unavailable")


_ERROR_MESSAGES: dict[str, str] = {
    "DIRECTORY_SELECTION_CANCELLED": "No se seleccionó ninguna carpeta.",
    "DIRECTORY_UNAVAILABLE": "La carpeta seleccionada no está disponible.",
    "CATALOG_READ_FAILED": "No se pudo leer el catálogo de bots.",
    "BOT_ENTRY_NOT_FOUND": "El bot ya no está disponible.",
    "BOT_LOAD_FAILED": "No se pudo cargar el bot.",
    "BOT_INVALID": "El bot no tiene un formato válido.",
    "BOT_CHANGED_EXTERNALLY": "El bot cambió fuera del editor.",
    "BOT_SAVE_FAILED": "No se pudo guardar el bot.",
    "BOT_AI_INVALID": "El historial de chat no tiene un formato válido.",
    "BOT_AI_TOO_LARGE": "El historial de chat supera el límite de tamaño.",
    "BOT_AI_SAVE_FAILED": "No se pudo guardar el historial de chat.",
    "BOT_PENDING_AI_INVALID": "La propuesta pendiente no tiene un formato válido.",
    "BOT_PENDING_AI_STALE": "La propuesta pendiente pertenece a otra versión del bot.",
    "BOT_PENDING_AI_TOO_LARGE": "La propuesta pendiente supera el límite de tamaño.",
    "BOT_PENDING_AI_SAVE_FAILED": "No se pudo guardar la propuesta pendiente.",
    "DESKTOP_BRIDGE_UNAVAILABLE": "El selector de carpetas no está disponible.",
    "EXECUTION_ALREADY_ACTIVE": "Ya hay una ejecución activa.",
    "EXECUTION_CAPTURE_ACTIVE": "No se puede iniciar la ejecución mientras se seleccionan coordenadas.",
    "EXECUTION_BOT_INVALID": "El bot no es válido para ejecutar.",
    "EXECUTION_UNSUPPORTED_ACTION": "El bot contiene una acción no compatible.",
    "EXECUTION_VARIABLE_INVALID": "Una referencia de variable no es válida.",
    "EXECUTION_ENVIRONMENT_UNAVAILABLE": "El entorno de ejecución no está disponible.",
    "EXECUTION_START_FAILED": "No se pudo iniciar la ejecución.",
    "EXECUTION_SHUTTING_DOWN": "La aplicación se está cerrando.",
    "WORKFLOW_LOAD_FAILED": "No se pudo cargar el flujo anidado.",
    "WORKFLOW_CYCLE": "El flujo anidado contiene una llamada circular.",
    "WORKFLOW_DEPTH_EXCEEDED": "Los flujos anidados superan la profundidad permitida.",
    "WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED": "Los flujos anidados contienen demasiados archivos únicos.",
    "WORKFLOW_INVOCATION_LIMIT_EXCEEDED": "Los flujos anidados contienen demasiadas invocaciones.",
    "WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED": "Los flujos anidados contienen demasiados bloques expandidos.",
    "WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED": "Los flujos anidados exceden el tamaño acumulado permitido.",
    "EXECUTION_NOT_FOUND": "No se encontró la ejecución.",
    "EXECUTION_NOT_ACTIVE": "La ejecución ya no está activa.",
    "EXECUTION_STATUS_FAILED": "No se pudo consultar la ejecución.",
    "CAPTURE_CANCELLED": "La selección fue cancelada.",
    "CAPTURE_TIMEOUT": "La selección agotó el tiempo de espera.",
    "CAPTURE_ALREADY_ACTIVE": "Ya hay una selección activa.",
    "CAPTURE_ENVIRONMENT_UNAVAILABLE": "La selección en pantalla no está disponible.",
    "CAPTURE_SHUTTING_DOWN": "La aplicación se está cerrando.",
}

_LOAD_ERROR_CODES: set[LoadBotErrorCode] = {
    "BOT_ENTRY_NOT_FOUND",
    "BOT_LOAD_FAILED",
    "BOT_INVALID",
    "DIRECTORY_UNAVAILABLE",
}
_CREATE_ERROR_CODES: set[CreateBotErrorCode] = {
    "BOT_INVALID",
    "BOT_SAVE_FAILED",
    "DIRECTORY_UNAVAILABLE",
}
_SAVE_ERROR_CODES: set[SaveBotErrorCode] = {
    "BOT_ENTRY_NOT_FOUND",
    "BOT_INVALID",
    "BOT_CHANGED_EXTERNALLY",
    "BOT_SAVE_FAILED",
    "DIRECTORY_UNAVAILABLE",
}
_SAVE_AI_ERROR_CODES: set[SaveBotAiErrorCode] = {
    "BOT_ENTRY_NOT_FOUND",
    "BOT_AI_INVALID",
    "BOT_AI_TOO_LARGE",
    "BOT_CHANGED_EXTERNALLY",
    "BOT_AI_SAVE_FAILED",
}
_SAVE_PENDING_AI_ERROR_CODES: set[SavePendingAiProposalErrorCode] = {
    "BOT_ENTRY_NOT_FOUND",
    "BOT_PENDING_AI_INVALID",
    "BOT_PENDING_AI_STALE",
    "BOT_PENDING_AI_TOO_LARGE",
    "BOT_CHANGED_EXTERNALLY",
    "BOT_PENDING_AI_SAVE_FAILED",
}
_EXECUTE_ERROR_CODES: set[ExecuteBotErrorCode] = {
    "EXECUTION_ALREADY_ACTIVE",
    "EXECUTION_CAPTURE_ACTIVE",
    "EXECUTION_BOT_INVALID",
    "EXECUTION_UNSUPPORTED_ACTION",
    "EXECUTION_VARIABLE_INVALID",
    "EXECUTION_ENVIRONMENT_UNAVAILABLE",
    "EXECUTION_START_FAILED",
    "EXECUTION_SHUTTING_DOWN",
    "WORKFLOW_LOAD_FAILED",
    "WORKFLOW_CYCLE",
    "WORKFLOW_DEPTH_EXCEEDED",
    "WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED",
    "WORKFLOW_INVOCATION_LIMIT_EXCEEDED",
    "WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED",
    "WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED",
}
_CANCEL_ERROR_CODES: set[CancelExecutionErrorCode] = {
    "EXECUTION_NOT_FOUND",
    "EXECUTION_NOT_ACTIVE",
    "EXECUTION_STATUS_FAILED",
}
_STATUS_ERROR_CODES: set[ExecutionStatusErrorCode] = {
    "EXECUTION_NOT_FOUND",
    "EXECUTION_STATUS_FAILED",
}
_CAPTURE_ERROR_CODES: set[CaptureMouseErrorCode] = {
    "CAPTURE_CANCELLED",
    "CAPTURE_TIMEOUT",
    "CAPTURE_ALREADY_ACTIVE",
    "CAPTURE_ENVIRONMENT_UNAVAILABLE",
    "CAPTURE_SHUTTING_DOWN",
}


class DesktopApi:
    def __init__(
        self,
        bot_service: BotCatalogService | None = None,
        execution_service: ExecutionService | None = None,
        coordinate_capture_service: CoordinateCaptureService | None = None,
        native_window_controller: NativeWindowController | None = None,
    ) -> None:
        self._action_registry = load_action_registry()
        self._bot_service = bot_service if bot_service is not None else BotService()
        self._execution_service = (
            execution_service
            if execution_service is not None
            else ExecutionService(self._bot_service, registry=self._action_registry)
        )
        self._coordinate_capture_service = (
            coordinate_capture_service
            if coordinate_capture_service is not None
            else CoordinateCaptureService()
        )
        self._native_window_controller = (
            native_window_controller
            if native_window_controller is not None
            else _WindowsHwndController()
        )
        self._window: DesktopWindow | None = None
        self._operation_condition = threading.Condition(threading.Lock())
        self._capture_reserved = False
        self._execution_start_reserved = False
        self._closing = False

    def _attach_window(self, window: DesktopWindow) -> None:
        self._window = window

    def health(self) -> HealthResponse:
        return {
            "ok": True,
            "data": {"status": "ready", "version": "0.1.0"},
            "error": None,
        }

    def pick_file_path(self, dialog_type: str = "file") -> PickPathResponse:
        if self._window is None:
            return self._error("DESKTOP_BRIDGE_UNAVAILABLE")

        dtype = FOLDER_DIALOG if dialog_type == "folder" else (SAVE_DIALOG if dialog_type == "save" else OPEN_DIALOG)
        try:
            selected_paths = self._window.create_file_dialog(dtype)
        except Exception:
            return self._error("DESKTOP_BRIDGE_UNAVAILABLE")

        if not selected_paths:
            return {"ok": True, "data": None, "error": None}

        return {"ok": True, "data": selected_paths[0], "error": None}

    def select_bot_directory(self) -> SelectDirectoryResponse:
        if self._window is None:
            return self._error("DESKTOP_BRIDGE_UNAVAILABLE")

        try:
            selected_paths = self._window.create_file_dialog(FOLDER_DIALOG)
        except Exception:
            return self._error("DESKTOP_BRIDGE_UNAVAILABLE")

        if not selected_paths:
            return self._error("DIRECTORY_SELECTION_CANCELLED")

        try:
            catalog = self._bot_service.select_directory(selected_paths[0])
        except NotADirectoryError:
            return self._error("DIRECTORY_UNAVAILABLE")
        except Exception:
            return self._error("CATALOG_READ_FAILED")

        return {"ok": True, "data": catalog, "error": None}

    def get_bot_catalog(self) -> CatalogResponse:
        try:
            catalog = self._bot_service.get_catalog()
        except NotADirectoryError:
            return self._error("DIRECTORY_UNAVAILABLE")
        except Exception:
            return self._error("CATALOG_READ_FAILED")

        return {"ok": True, "data": catalog, "error": None}

    def load_bot(self, entry_id: str) -> LoadBotResponse:
        try:
            loaded_bot = self._bot_service.load_bot(entry_id)
        except BotServiceError as error:
            code = (
                cast(LoadBotErrorCode, error.code)
                if error.code in _LOAD_ERROR_CODES
                else "BOT_LOAD_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("BOT_LOAD_FAILED")

        return {"ok": True, "data": loaded_bot, "error": None}

    def create_bot(self, name: str) -> CreateBotResponse:
        try:
            loaded_bot = self._bot_service.create_bot(name)
        except BotServiceError as error:
            code = (
                cast(CreateBotErrorCode, error.code)
                if error.code in _CREATE_ERROR_CODES
                else "BOT_SAVE_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("BOT_SAVE_FAILED")

        return {"ok": True, "data": loaded_bot, "error": None}

    def delete_bot(self, entry_id: str) -> DeleteBotResponse:
        try:
            self._bot_service.delete_bot(entry_id)
        except BotServiceError as error:
            code = (
                cast(DeleteBotErrorCode, error.code)
                if error.code in {"BOT_ENTRY_NOT_FOUND", "DIRECTORY_UNAVAILABLE", "BOT_SAVE_FAILED"}
                else "BOT_SAVE_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("BOT_SAVE_FAILED")

        return {"ok": True, "data": True, "error": None}

    def save_bot(
        self,
        editor_token: str,
        expected_revision: str,
        bot: CanonicalBotInput,
        clear_pending_ai_proposal: bool = False,
    ) -> SaveBotResponse:
        if not isinstance(clear_pending_ai_proposal, bool):
            raise TypeError("clear_pending_ai_proposal must be a boolean")
        try:
            saved_bot = (
                self._bot_service.save_bot(
                    editor_token,
                    expected_revision,
                    bot,
                    True,
                )
                if clear_pending_ai_proposal
                else self._bot_service.save_bot(editor_token, expected_revision, bot)
            )
        except BotServiceError as error:
            code = (
                cast(SaveBotErrorCode, error.code)
                if error.code in _SAVE_ERROR_CODES
                else "BOT_SAVE_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("BOT_SAVE_FAILED")

        return {"ok": True, "data": saved_bot, "error": None}

    def save_bot_ai(
        self,
        editor_token: str,
        expected_revision: str,
        ai: CanonicalAiInput,
    ) -> SaveBotAiResponse:
        try:
            saved_ai = self._bot_service.save_ai(
                editor_token, expected_revision, ai
            )
        except BotServiceError as error:
            code = (
                cast(SaveBotAiErrorCode, error.code)
                if error.code in _SAVE_AI_ERROR_CODES
                else "BOT_AI_SAVE_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("BOT_AI_SAVE_FAILED")

        return {"ok": True, "data": saved_ai, "error": None}

    def save_pending_ai_proposal(
        self,
        editor_token: str,
        expected_revision: str,
        pending: CanonicalPendingAiProposalInput | None,
    ) -> SavePendingAiProposalResponse:
        try:
            saved = self._bot_service.save_pending_ai_proposal(
                editor_token, expected_revision, pending
            )
        except BotServiceError as error:
            code = (
                cast(SavePendingAiProposalErrorCode, error.code)
                if error.code in _SAVE_PENDING_AI_ERROR_CODES
                else "BOT_PENDING_AI_SAVE_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("BOT_PENDING_AI_SAVE_FAILED")

        return {"ok": True, "data": saved, "error": None}

    def execute_bot(
        self, editor_token: str, bot: CanonicalBotInput
    ) -> ExecuteBotResponse:
        with self._operation_condition:
            if self._closing:
                return self._error("EXECUTION_SHUTTING_DOWN")
            if self._capture_reserved:
                return self._error("EXECUTION_CAPTURE_ACTIVE")
            if self._execution_start_reserved:
                return self._error("EXECUTION_ALREADY_ACTIVE")
            self._execution_start_reserved = True

        error_code: ExecuteBotErrorCode | None = None
        result: ExecutionStartResult | None = None
        try:
            result = self._execution_service.start(editor_token, bot)
        except SafeExecutionError as error:
            raw_code = error.code.value
            error_code = (
                cast(ExecuteBotErrorCode, raw_code)
                if raw_code in _EXECUTE_ERROR_CODES
                else "EXECUTION_START_FAILED"
            )
        except Exception:
            error_code = "EXECUTION_START_FAILED"
        finally:
            with self._operation_condition:
                self._execution_start_reserved = False
                closing = self._closing
                self._operation_condition.notify_all()

        if closing:
            return self._error("EXECUTION_SHUTTING_DOWN")
        if error_code is not None:
            return self._error(error_code)
        if result is None:
            return self._error("EXECUTION_START_FAILED")
        return {"ok": True, "data": result, "error": None}

    def capture_mouse_position(self) -> CaptureMouseResponse:
        with self._operation_condition:
            if self._closing:
                return self._error("CAPTURE_SHUTTING_DOWN")
            if self._capture_reserved:
                return self._error("CAPTURE_ALREADY_ACTIVE")
            if self._execution_start_reserved:
                return self._error("CAPTURE_ENVIRONMENT_UNAVAILABLE")
            try:
                execution_active = self._execution_service.has_active_run()
            except Exception:
                return self._error("CAPTURE_ENVIRONMENT_UNAVAILABLE")
            if execution_active:
                return self._error("CAPTURE_ENVIRONMENT_UNAVAILABLE")
            self._capture_reserved = True
            window = self._window
            if window is None:
                self._capture_reserved = False
                self._operation_condition.notify_all()
                return self._error("CAPTURE_ENVIRONMENT_UNAVAILABLE")
            try:
                handle = self._native_window_controller.get_handle(window)
                self._native_window_controller.minimize(handle)
            except Exception:
                self._capture_reserved = False
                self._operation_condition.notify_all()
                return self._error("CAPTURE_ENVIRONMENT_UNAVAILABLE")

        try:
            position = self._coordinate_capture_service.capture()
            x = position["x"]
            y = position["y"]
            if type(x) is not int or type(y) is not int:
                raise ValueError("invalid coordinate capture result")
            response: CaptureMouseResponse = {
                "ok": True,
                "data": {"x": x, "y": y},
                "error": None,
            }
        except CoordinateCaptureError as error:
            raw_code = error.code.value
            code = (
                cast(CaptureMouseErrorCode, raw_code)
                if raw_code in _CAPTURE_ERROR_CODES
                else "CAPTURE_ENVIRONMENT_UNAVAILABLE"
            )
            response = self._error(code)
        except Exception:
            response = self._error("CAPTURE_ENVIRONMENT_UNAVAILABLE")

        window_lifecycle_failed = False
        with self._operation_condition:
            try:
                if not self._closing:
                    self._native_window_controller.restore_and_focus(handle)
            except Exception:
                window_lifecycle_failed = True
            finally:
                self._capture_reserved = False
                self._operation_condition.notify_all()

        if window_lifecycle_failed and response["ok"]:
            return self._error("CAPTURE_ENVIRONMENT_UNAVAILABLE")
        return response

    def cancel_execution(self, run_id: str) -> CancelExecutionResponse:
        try:
            result = self._execution_service.cancel(run_id)
        except SafeExecutionError as error:
            raw_code = error.code.value
            code = (
                cast(CancelExecutionErrorCode, raw_code)
                if raw_code in _CANCEL_ERROR_CODES
                else "EXECUTION_STATUS_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("EXECUTION_STATUS_FAILED")
        return {"ok": True, "data": result, "error": None}

    def get_execution_status(
        self, run_id: str, after_sequence: int
    ) -> ExecutionStatusResponse:
        try:
            result = self._execution_service.status(run_id, after_sequence)
        except SafeExecutionError as error:
            raw_code = error.code.value
            code = (
                cast(ExecutionStatusErrorCode, raw_code)
                if raw_code in _STATUS_ERROR_CODES
                else "EXECUTION_STATUS_FAILED"
            )
            return self._error(code)
        except Exception:
            return self._error("EXECUTION_STATUS_FAILED")
        return {"ok": True, "data": result, "error": None}

    def _cancel_active_for_close(self, timeout: float = 10.0) -> bool:
        deadline = time.monotonic() + max(0.0, timeout)
        if not self._operation_condition.acquire(
            timeout=max(0.0, deadline - time.monotonic())
        ):
            return False
        try:
            self._closing = True
        finally:
            self._operation_condition.release()

        capture_request_ok = True
        execution_request_ok = True
        try:
            self._coordinate_capture_service.shutdown(0.0)
        except Exception:
            capture_request_ok = False
        try:
            self._execution_service.begin_shutdown()
        except Exception:
            execution_request_ok = False

        try:
            capture_stopped = self._coordinate_capture_service.shutdown(
                max(0.0, deadline - time.monotonic())
            )
        except Exception:
            capture_stopped = False
        reservations_released = False
        if self._operation_condition.acquire(
            timeout=max(0.0, deadline - time.monotonic())
        ):
            try:
                reservations_released = self._operation_condition.wait_for(
                    lambda: not self._capture_reserved
                    and not self._execution_start_reserved,
                    max(0.0, deadline - time.monotonic()),
                )
            finally:
                self._operation_condition.release()

        try:
            execution_stopped = self._execution_service.cancel_active_and_wait(
                max(0.0, deadline - time.monotonic())
            )
        except Exception:
            execution_stopped = False

        return (
            capture_request_ok
            and execution_request_ok
            and capture_stopped
            and execution_stopped
            and reservations_released
        )

    @staticmethod
    def _error(code: ErrorCodeData) -> ApiFailure[ErrorCodeData]:
        return {
            "ok": False,
            "data": None,
            "error": {"code": code, "message": _ERROR_MESSAGES[code]},
        }
