import copy
import json
import re
from dataclasses import dataclass
from typing import Final, Mapping

from pydantic import JsonValue

from autoclick_desktop.execution_errors import ExecutionErrorCode, VariableResolutionError


VARIABLE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
TOKEN = re.compile(r"{{([A-Za-z_][A-Za-z0-9_]*)}}")
MAX_RESOLUTION_DEPTH: Final = 10
MAX_EXPANDED_STRING_LENGTH: Final = 100_000
MAX_TOKEN_COUNT: Final = 10_000


@dataclass(frozen=True, slots=True)
class RuntimeUnknown:
    """Marks a preflight-defined value whose type is only known at runtime."""


RUNTIME_UNKNOWN = RuntimeUnknown()


def token_names(value: str, *, max_tokens: int = MAX_TOKEN_COUNT) -> tuple[str, ...]:
    if "{{{" in value or "}}}" in value:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_TOKEN_INVALID)
    matches = tuple(TOKEN.finditer(value))
    if len(matches) > max_tokens:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_TOKEN_COUNT_EXCEEDED)
    consumed = TOKEN.sub("", value)
    if "{{" in consumed or "}}" in consumed:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_TOKEN_INVALID)
    return tuple(match.group(1) for match in matches)


def resolve_value(
    value: JsonValue | RuntimeUnknown,
    variables: Mapping[str, JsonValue | RuntimeUnknown],
    *,
    max_depth: int = MAX_RESOLUTION_DEPTH,
    max_expanded_length: int = MAX_EXPANDED_STRING_LENGTH,
    max_tokens: int = MAX_TOKEN_COUNT,
) -> JsonValue | RuntimeUnknown:
    token_budget = [max_tokens]
    resolved = _resolve(value, variables, (), 0, max_depth, max_expanded_length, token_budget)
    if resolved is not RUNTIME_UNKNOWN and _json_string_size(resolved) > max_expanded_length:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_EXPANDED_SIZE_EXCEEDED)
    return resolved


def _resolve(
    value: JsonValue | RuntimeUnknown,
    variables: Mapping[str, JsonValue | RuntimeUnknown],
    stack: tuple[str, ...],
    depth: int,
    max_depth: int,
    max_length: int,
    token_budget: list[int],
) -> JsonValue | RuntimeUnknown:
    if value is RUNTIME_UNKNOWN:
        return value
    if isinstance(value, list):
        if depth >= max_depth:
            raise VariableResolutionError(ExecutionErrorCode.VARIABLE_DEPTH_EXCEEDED)
        return [
            _resolve(item, variables, stack, depth + 1, max_depth, max_length, token_budget)
            for item in value
        ]
    if isinstance(value, dict):
        if depth >= max_depth:
            raise VariableResolutionError(ExecutionErrorCode.VARIABLE_DEPTH_EXCEEDED)
        return {
            key: _resolve(item, variables, stack, depth + 1, max_depth, max_length, token_budget)
            for key, item in value.items()
        }
    if not isinstance(value, str):
        return copy.deepcopy(value)
    matches = tuple(TOKEN.finditer(value))
    consumed = TOKEN.sub("", value)
    if "{{{" in value or "}}}" in value or "{{" in consumed or "}}" in consumed:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_TOKEN_INVALID)
    token_budget[0] -= len(matches)
    if token_budget[0] < 0:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_TOKEN_COUNT_EXCEEDED)
    if not matches:
        _check_size(value, max_length)
        return value
    whole = TOKEN.fullmatch(value)
    if whole is not None:
        return _resolve_name(
            whole.group(1), variables, stack, depth, max_depth, max_length, token_budget
        )

    result: list[str] = []
    cursor = 0
    result_length = 0
    deferred = False
    for match in matches:
        literal = value[cursor:match.start()]
        result.append(literal)
        result_length += len(literal)
        resolved = _resolve_name(
            match.group(1), variables, stack, depth, max_depth, max_length, token_budget
        )
        if resolved is RUNTIME_UNKNOWN:
            deferred = True
        else:
            rendered = _stringify(resolved)
            result.append(rendered)
            result_length += len(rendered)
            if result_length > max_length:
                raise VariableResolutionError(ExecutionErrorCode.VARIABLE_EXPANDED_SIZE_EXCEEDED)
        cursor = match.end()
    tail = value[cursor:]
    result.append(tail)
    result_length += len(tail)
    if result_length > max_length:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_EXPANDED_SIZE_EXCEEDED)
    if deferred:
        return RUNTIME_UNKNOWN
    expanded = "".join(result)
    return expanded


def _resolve_name(
    name: str,
    variables: Mapping[str, JsonValue | RuntimeUnknown],
    stack: tuple[str, ...],
    depth: int,
    max_depth: int,
    max_length: int,
    token_budget: list[int],
) -> JsonValue | RuntimeUnknown:
    if name in stack:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_CYCLE)
    if name not in variables:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_MISSING)
    if depth >= max_depth:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_DEPTH_EXCEEDED)
    return _resolve(
        variables[name], variables, (*stack, name), depth + 1, max_depth, max_length,
        token_budget,
    )


def _stringify(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _check_size(value: str, maximum: int) -> None:
    if len(value) > maximum:
        raise VariableResolutionError(ExecutionErrorCode.VARIABLE_EXPANDED_SIZE_EXCEEDED)


def _json_string_size(value: JsonValue) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, list):
        return sum(_json_string_size(item) for item in value)
    if isinstance(value, dict):
        return sum(_json_string_size(item) for item in value.values())
    return 0
