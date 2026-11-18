from typing import Any


def is_pending_parameter(value: Any) -> bool:
    return isinstance(value, dict) and len(value) == 1 and value.get("$pending") is True
