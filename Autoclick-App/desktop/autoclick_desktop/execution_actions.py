from threading import Event

from autoclick_desktop.execution_errors import ExecutionCancelled, ExecutionErrorCode, ExecutionStopped, HandlerError
from autoclick_desktop.execution_models import ResolvedAction
from autoclick_desktop.platform_adapters import OperatingSystemAdapter


def handle_wait(action: ResolvedAction, cancel_event: Event) -> None:
    milliseconds = action.params["milliseconds"]
    assert isinstance(milliseconds, int) and not isinstance(milliseconds, bool)
    if cancel_event.wait(milliseconds / 1000):
        raise ExecutionCancelled()


def handle_stop(_action: ResolvedAction) -> None:
    raise ExecutionStopped()


def parse_windows_arguments(value: str) -> list[str]:
    """Parse the Microsoft C runtime command-line format used by Windows apps."""
    arguments: list[str] = []
    index = 0
    length = len(value)
    while True:
        while index < length and value[index] in " \t\r\n":
            index += 1
        if index >= length:
            return arguments

        argument: list[str] = []
        quoted = False
        while index < length:
            if value[index] in " \t\r\n" and not quoted:
                break
            if value[index] == "\\":
                start = index
                while index < length and value[index] == "\\":
                    index += 1
                backslashes = index - start
                if index < length and value[index] == '"':
                    argument.extend("\\" for _ in range(backslashes // 2))
                    if backslashes % 2:
                        argument.append('"')
                    else:
                        quoted = not quoted
                    index += 1
                else:
                    argument.extend("\\" for _ in range(backslashes))
                continue
            if value[index] == '"':
                if quoted and index + 1 < length and value[index + 1] == '"':
                    argument.append('"')
                    index += 2
                else:
                    quoted = not quoted
                    index += 1
                continue
            argument.append(value[index])
            index += 1
        arguments.append("".join(argument))


def handle_run_application(action: ResolvedAction, operating_system: OperatingSystemAdapter) -> None:
    try:
        arguments = parse_windows_arguments(str(action.params.get("arguments", "")))
        operating_system.run_application(str(action.params["path"]), arguments)
    except Exception:
        raise HandlerError(ExecutionErrorCode.PROCESS_START_FAILED) from None


def handle_browser_open(action: ResolvedAction, operating_system: OperatingSystemAdapter) -> None:
    try:
        operating_system.open_browser(str(action.params["url"]))
    except Exception:
        raise HandlerError(ExecutionErrorCode.PROCESS_START_FAILED) from None
