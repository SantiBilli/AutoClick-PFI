import copy

from pydantic import JsonValue

from autoclick_desktop.execution_models import ResolvedAction
from autoclick_desktop.execution_errors import ExecutionErrorCode, HandlerError


def handle_variable_create(
    action: ResolvedAction, variables: dict[str, JsonValue]
) -> None:
    name = action.params["name"]
    assert isinstance(name, str)
    if name in variables:
        raise HandlerError(ExecutionErrorCode.RESOURCE_ALREADY_DEFINED)
    variables[name] = copy.deepcopy(action.params.get("value", ""))


def handle_variable_update(action: ResolvedAction, variables: dict[str, JsonValue]) -> None:
    name = str(action.params["name"])
    if name not in variables:
        raise HandlerError(ExecutionErrorCode.RESOURCE_NOT_FOUND)
    variables[name] = copy.deepcopy(action.params["value"])


def handle_variable_delete(action: ResolvedAction, variables: dict[str, JsonValue]) -> None:
    name = str(action.params["name"])
    if name not in variables:
        raise HandlerError(ExecutionErrorCode.RESOURCE_NOT_FOUND)
    del variables[name]
