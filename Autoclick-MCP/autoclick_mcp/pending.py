"""Explicit draft parameter, distinct from null/default/current pointer position."""
from typing import Any


def is_pending_parameter(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and value.get("$pending") is True


def allows_pending_parameter(field_type: str, field_name: str) -> bool:
    # Internal references must remain resolvable to validate the flow's structure.
    return field_type != "variable" and field_name != "targetNodeId"
