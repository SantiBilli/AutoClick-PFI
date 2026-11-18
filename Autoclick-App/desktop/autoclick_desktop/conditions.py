import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, JsonValue, model_validator

from autoclick_desktop.execution_variables import RuntimeUnknown, resolve_value


MAX_SAFE_INTEGER = 9_007_199_254_740_991


ConditionOperator = Literal[
    "eq", "ne", "lt", "lte", "gt", "gte", "contains", "startsWith",
    "endsWith", "in", "empty", "notEmpty",
]
UNARY_CONDITION_OPERATORS = frozenset({"empty", "notEmpty"})


class ConditionClause(BaseModel):
    model_config = ConfigDict(extra="forbid")

    left: JsonValue
    operator: ConditionOperator
    right: JsonValue | None = None

    @model_validator(mode="before")
    @classmethod
    def validate_right_operand(cls, value: object) -> object:
        if isinstance(value, dict):
            operator = value.get("operator")
            if operator not in UNARY_CONDITION_OPERATORS and "right" not in value:
                raise ValueError("binary condition operators require a right operand")
        return value

    @model_validator(mode="after")
    def validate_safe_numbers(self) -> "ConditionClause":
        _validate_safe_numbers(self.left)
        if self.operator not in UNARY_CONDITION_OPERATORS:
            _validate_safe_numbers(self.right)
        return self


class Condition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    combinator: Literal["all", "any"]
    clauses: list[ConditionClause]

    @model_validator(mode="after")
    def validate_clauses(self) -> "Condition":
        if not self.clauses:
            raise ValueError("conditions require at least one clause")
        return self


def evaluate_condition(
    condition: Condition, variables: dict[str, JsonValue | RuntimeUnknown]
) -> bool:
    results = (
        evaluate_clause(
            clause.operator,
            resolve_value(clause.left, variables),
            resolve_value(clause.right, variables)
            if clause.operator not in UNARY_CONDITION_OPERATORS
            else None,
        )
        for clause in condition.clauses
    )
    return all(results) if condition.combinator == "all" else any(results)


def evaluate_clause(operator: ConditionOperator, left: object, right: object = None) -> bool:
    if isinstance(left, RuntimeUnknown) or isinstance(right, RuntimeUnknown):
        return False
    if operator == "empty":
        return _is_emptiable(left) and not left
    if operator == "notEmpty":
        return _is_emptiable(left) and bool(left)
    if operator == "eq":
        return _json_equal(left, right)
    if operator == "ne":
        return not _json_equal(left, right)
    if operator in {"lt", "lte", "gt", "gte"}:
        if not (_same_ordered_type(left, right)):
            return False
        return {
            "lt": left < right,
            "lte": left <= right,
            "gt": left > right,
            "gte": left >= right,
        }[operator]
    if operator == "contains":
        if isinstance(left, str) and isinstance(right, str):
            return right in left
        if isinstance(left, list):
            return any(_json_equal(item, right) for item in left)
        return False
    if operator == "startsWith":
        return isinstance(left, str) and isinstance(right, str) and left.startswith(right)
    if operator == "endsWith":
        return isinstance(left, str) and isinstance(right, str) and left.endswith(right)
    if operator == "in":
        return isinstance(right, list) and any(_json_equal(left, item) for item in right)
    return False


def _is_emptiable(value: object) -> bool:
    return value is None or isinstance(value, (str, list, dict))


def _same_ordered_type(left: object, right: object) -> bool:
    numbers = (
        isinstance(left, (int, float)) and not isinstance(left, bool)
        and isinstance(right, (int, float)) and not isinstance(right, bool)
    )
    return numbers or isinstance(left, str) and isinstance(right, str)


def _json_equal(left: object, right: object) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_equal(a, b) for a, b in zip(left, right, strict=True)
        )
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(
            _json_equal(left[key], right[key]) for key in left
        )
    return left == right


def _validate_safe_numbers(value: object) -> None:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("condition numbers must be finite")
        if value.is_integer() and abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("condition integers must be JavaScript-safe")
    elif isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("condition integers must be JavaScript-safe")
    if isinstance(value, list):
        for item in value:
            _validate_safe_numbers(item)
    elif isinstance(value, dict):
        for item in value.values():
            _validate_safe_numbers(item)
