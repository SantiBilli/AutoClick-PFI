from enum import StrEnum


class ExecutionErrorCode(StrEnum):
    EXECUTION_ALREADY_ACTIVE = "EXECUTION_ALREADY_ACTIVE"
    EXECUTION_CAPTURE_ACTIVE = "EXECUTION_CAPTURE_ACTIVE"
    EXECUTION_BOT_INVALID = "EXECUTION_BOT_INVALID"
    EXECUTION_UNSUPPORTED_ACTION = "EXECUTION_UNSUPPORTED_ACTION"
    EXECUTION_VARIABLE_INVALID = "EXECUTION_VARIABLE_INVALID"
    EXECUTION_ENVIRONMENT_UNAVAILABLE = "EXECUTION_ENVIRONMENT_UNAVAILABLE"
    EXECUTION_START_FAILED = "EXECUTION_START_FAILED"
    EXECUTION_SHUTTING_DOWN = "EXECUTION_SHUTTING_DOWN"
    EXECUTION_NOT_FOUND = "EXECUTION_NOT_FOUND"
    EXECUTION_NOT_ACTIVE = "EXECUTION_NOT_ACTIVE"
    EXECUTION_STATUS_FAILED = "EXECUTION_STATUS_FAILED"
    VARIABLE_TOKEN_INVALID = "VARIABLE_TOKEN_INVALID"
    VARIABLE_MISSING = "VARIABLE_MISSING"
    VARIABLE_CYCLE = "VARIABLE_CYCLE"
    VARIABLE_DEPTH_EXCEEDED = "VARIABLE_DEPTH_EXCEEDED"
    VARIABLE_EXPANDED_SIZE_EXCEEDED = "VARIABLE_EXPANDED_SIZE_EXCEEDED"
    RESOURCE_NOT_FOUND = "RESOURCE_NOT_FOUND"
    RESOURCE_ALREADY_DEFINED = "RESOURCE_ALREADY_DEFINED"
    RESOURCE_CLOSED = "RESOURCE_CLOSED"
    RESOURCE_CLEANUP_FAILED = "RESOURCE_CLEANUP_FAILED"
    ACTION_PARAMETER_INVALID = "ACTION_PARAMETER_INVALID"
    EVENT_CURSOR_AHEAD = "EVENT_CURSOR_AHEAD"
    VARIABLE_TOKEN_COUNT_EXCEEDED = "VARIABLE_TOKEN_COUNT_EXCEEDED"
    EXECUTION_CANCELLED = "EXECUTION_CANCELLED"
    DESKTOP_INPUT_FAILED = "DESKTOP_INPUT_FAILED"
    CLIPBOARD_UNAVAILABLE = "CLIPBOARD_UNAVAILABLE"
    EXCEL_UNAVAILABLE = "EXCEL_UNAVAILABLE"
    EXCEL_OPEN_FAILED = "EXCEL_OPEN_FAILED"
    EXCEL_WORKSHEET_NOT_FOUND = "EXCEL_WORKSHEET_NOT_FOUND"
    EXCEL_READ_FAILED = "EXCEL_READ_FAILED"
    EXCEL_WRITE_FAILED = "EXCEL_WRITE_FAILED"
    EXCEL_SAVE_FAILED = "EXCEL_SAVE_FAILED"
    EXCEL_DESTINATION_EXISTS = "EXCEL_DESTINATION_EXISTS"
    EXCEL_CLOSE_FAILED = "EXCEL_CLOSE_FAILED"
    EXCEL_VALUE_UNSUPPORTED = "EXCEL_VALUE_UNSUPPORTED"
    FILESYSTEM_OPERATION_FAILED = "FILESYSTEM_OPERATION_FAILED"
    PROCESS_START_FAILED = "PROCESS_START_FAILED"
    WINDOW_NOT_FOUND = "WINDOW_NOT_FOUND"
    WINDOW_OPERATION_FAILED = "WINDOW_OPERATION_FAILED"
    HTTP_REQUEST_FAILED = "HTTP_REQUEST_FAILED"
    HTTP_RESPONSE_TOO_LARGE = "HTTP_RESPONSE_TOO_LARGE"
    WORKFLOW_LOAD_FAILED = "WORKFLOW_LOAD_FAILED"
    WORKFLOW_CYCLE = "WORKFLOW_CYCLE"
    WORKFLOW_DEPTH_EXCEEDED = "WORKFLOW_DEPTH_EXCEEDED"
    WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED = "WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED"
    WORKFLOW_INVOCATION_LIMIT_EXCEEDED = "WORKFLOW_INVOCATION_LIMIT_EXCEEDED"
    WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED = "WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED"
    WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED = "WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED"
    STEP_BUDGET_EXCEEDED = "STEP_BUDGET_EXCEEDED"
    VISION_OCR_UNAVAILABLE = "VISION_OCR_UNAVAILABLE"
    VISION_ELEMENT_NOT_FOUND = "VISION_ELEMENT_NOT_FOUND"
    VISION_CAPTURE_FAILED = "VISION_CAPTURE_FAILED"


_SAFE_MESSAGES: dict[ExecutionErrorCode, str] = {
    ExecutionErrorCode.EXECUTION_ALREADY_ACTIVE: "Ya hay una ejecución activa.",
    ExecutionErrorCode.EXECUTION_CAPTURE_ACTIVE: "No se puede iniciar la ejecución mientras se seleccionan coordenadas.",
    ExecutionErrorCode.EXECUTION_BOT_INVALID: "El bot no es válido para ejecutar.",
    ExecutionErrorCode.EXECUTION_UNSUPPORTED_ACTION: "El bot contiene una acción no compatible.",
    ExecutionErrorCode.EXECUTION_VARIABLE_INVALID: "Una referencia de variable no es válida.",
    ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE: "El entorno de ejecución no está disponible.",
    ExecutionErrorCode.EXECUTION_START_FAILED: "No se pudo iniciar la ejecución.",
    ExecutionErrorCode.EXECUTION_SHUTTING_DOWN: "La aplicación se está cerrando.",
    ExecutionErrorCode.EXECUTION_NOT_FOUND: "No se encontró la ejecución.",
    ExecutionErrorCode.EXECUTION_NOT_ACTIVE: "La ejecución ya no está activa.",
    ExecutionErrorCode.EXECUTION_STATUS_FAILED: "No se pudo consultar la ejecución.",
    ExecutionErrorCode.VARIABLE_TOKEN_INVALID: "La referencia de variable tiene un formato inválido.",
    ExecutionErrorCode.VARIABLE_MISSING: "No se encontró una variable requerida.",
    ExecutionErrorCode.VARIABLE_CYCLE: "Las variables contienen una referencia circular.",
    ExecutionErrorCode.VARIABLE_DEPTH_EXCEEDED: "Las variables exceden la profundidad permitida.",
    ExecutionErrorCode.VARIABLE_EXPANDED_SIZE_EXCEEDED: "El valor expandido excede el tamaño permitido.",
    ExecutionErrorCode.RESOURCE_NOT_FOUND: "No se encontró un recurso requerido.",
    ExecutionErrorCode.RESOURCE_ALREADY_DEFINED: "El recurso ya está definido.",
    ExecutionErrorCode.RESOURCE_CLOSED: "El recurso ya está cerrado.",
    ExecutionErrorCode.RESOURCE_CLEANUP_FAILED: "No se pudo verificar la limpieza de los recursos.",
    ExecutionErrorCode.ACTION_PARAMETER_INVALID: "Un parámetro de la acción no es válido.",
    ExecutionErrorCode.EVENT_CURSOR_AHEAD: "La posición de eventos solicitada no es válida.",
    ExecutionErrorCode.VARIABLE_TOKEN_COUNT_EXCEEDED: "El valor contiene demasiadas referencias de variables.",
    ExecutionErrorCode.EXECUTION_CANCELLED: "La ejecución fue cancelada.",
    ExecutionErrorCode.DESKTOP_INPUT_FAILED: "No se pudo controlar el dispositivo de entrada.",
    ExecutionErrorCode.CLIPBOARD_UNAVAILABLE: "El portapapeles no está disponible.",
    ExecutionErrorCode.EXCEL_UNAVAILABLE: "Microsoft Excel no está disponible.",
    ExecutionErrorCode.EXCEL_OPEN_FAILED: "No se pudo abrir el libro de Excel.",
    ExecutionErrorCode.EXCEL_WORKSHEET_NOT_FOUND: "No se encontró la hoja solicitada.",
    ExecutionErrorCode.EXCEL_READ_FAILED: "No se pudo leer la celda de Excel.",
    ExecutionErrorCode.EXCEL_WRITE_FAILED: "No se pudo escribir la celda de Excel.",
    ExecutionErrorCode.EXCEL_SAVE_FAILED: "No se pudo guardar el libro de Excel.",
    ExecutionErrorCode.EXCEL_DESTINATION_EXISTS: "El archivo de destino ya existe.",
    ExecutionErrorCode.EXCEL_CLOSE_FAILED: "No se pudo cerrar el libro de Excel.",
    ExecutionErrorCode.EXCEL_VALUE_UNSUPPORTED: "Excel devolvió un tipo de valor no compatible.",
    ExecutionErrorCode.FILESYSTEM_OPERATION_FAILED: "No se pudo completar la operación de archivo o carpeta.",
    ExecutionErrorCode.PROCESS_START_FAILED: "No se pudo iniciar la aplicación o abrir el destino.",
    ExecutionErrorCode.WINDOW_NOT_FOUND: "No se encontró la ventana solicitada.",
    ExecutionErrorCode.WINDOW_OPERATION_FAILED: "No se pudo controlar la ventana.",
    ExecutionErrorCode.HTTP_REQUEST_FAILED: "No se pudo completar la solicitud HTTP.",
    ExecutionErrorCode.HTTP_RESPONSE_TOO_LARGE: "La respuesta HTTP excede el tamaño permitido.",
    ExecutionErrorCode.WORKFLOW_LOAD_FAILED: "No se pudo cargar el flujo anidado.",
    ExecutionErrorCode.WORKFLOW_CYCLE: "El flujo anidado contiene una llamada circular.",
    ExecutionErrorCode.WORKFLOW_DEPTH_EXCEEDED: "Los flujos anidados superan la profundidad permitida.",
    ExecutionErrorCode.WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED: "Los flujos anidados contienen demasiados archivos únicos.",
    ExecutionErrorCode.WORKFLOW_INVOCATION_LIMIT_EXCEEDED: "Los flujos anidados contienen demasiadas invocaciones.",
    ExecutionErrorCode.WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED: "Los flujos anidados contienen demasiados bloques expandidos.",
    ExecutionErrorCode.WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED: "Los flujos anidados exceden el tamaño acumulado permitido.",
    ExecutionErrorCode.STEP_BUDGET_EXCEEDED: "La ejecución superó el límite global de pasos.",
    ExecutionErrorCode.VISION_OCR_UNAVAILABLE: "El motor OCR no está disponible o no está instalado.",
    ExecutionErrorCode.VISION_ELEMENT_NOT_FOUND: "No se encontró el elemento en la pantalla antes del tiempo límite.",
    ExecutionErrorCode.VISION_CAPTURE_FAILED: "No se pudo capturar la pantalla o región especificada.",
}


class SafeExecutionError(Exception):
    """An error whose fixed message is safe to expose through the desktop bridge."""

    def __init__(self, code: ExecutionErrorCode) -> None:
        self.code = code
        self.safe_message = _SAFE_MESSAGES[code]
        super().__init__(self.safe_message)


class VariableResolutionError(SafeExecutionError):
    pass


class ResourceError(SafeExecutionError):
    pass


class HandlerError(SafeExecutionError):
    """A fixed, payload-free action failure safe for events and API responses."""


class ExecutionCancelled(HandlerError):
    def __init__(self) -> None:
        super().__init__(ExecutionErrorCode.EXECUTION_CANCELLED)


class ExecutionStopped(Exception):
    """Successful user-authored control signal for execution.stop."""


class UncatchableExecutionSignal(BaseException):
    """Base for safety controls that try/catch must never recover from."""


class StepBudgetExceeded(UncatchableExecutionSignal):
    code = ExecutionErrorCode.STEP_BUDGET_EXCEEDED


class PublishedSaveAsError(HandlerError):
    """Save As published a file that must remain historically reserved."""

    def __init__(self, identity: object) -> None:
        self.identity = identity
        super().__init__(ExecutionErrorCode.EXCEL_SAVE_FAILED)


class PublishedSaveAsCancellation(ExecutionCancelled):
    def __init__(self, identity: object) -> None:
        self.identity = identity
        super().__init__()
