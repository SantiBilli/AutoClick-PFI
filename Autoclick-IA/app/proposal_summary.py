"""Describe validated parameter-only proposals from their actual before/after diff."""
import copy
import json
import re

from app.schemas import Capabilities


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def parameter_change_summary(before: dict, after: dict, capabilities: Capabilities) -> str | None:
    """No mutation, intent inference, patch repair or omission of changed fields."""
    old, new = copy.deepcopy(before), copy.deepcopy(after)
    old_nodes = old.get("flow", {}).get("nodes", [])
    new_nodes = new.get("flow", {}).get("nodes", [])
    if not old_nodes or len(old_nodes) != len(new_nodes):
        return None
    actions = {action.id: action for action in capabilities.actions}
    changes = []
    for left, right in zip(old_nodes, new_nodes):
        action = actions.get(left.get("type"))
        if action is None:
            return None
        old_params = action.defaults | left.pop("params", {})
        new_params = action.defaults | right.pop("params", {})
        labels = {field.name: field.label for field in action.fields}
        for key in sorted(old_params.keys() | new_params.keys()):
            old_value = _json(old_params[key]) if key in old_params else "(sin configurar)"
            new_value = _json(new_params[key]) if key in new_params else "(sin configurar)"
            if old_value != new_value:
                changes.append((action.title, labels.get(key, key), old_value, new_value))
    # Includes IDs, node order, slots, root, metadata and every non-parameter key.
    if _json(old) != _json(new) or not changes:
        return None
    lines = []
    for title, field, previous, proposed in changes:
        # JSON quoting preserves types and punctuation; Markdown code spans
        # prevent user values from becoming formatting or instructions.
        def quote(value):
            fence = "`" * (max((len(part) for part in re.findall(r"`+", value)), default=0) + 1)
            return fence + " " + value + " " + fence
        lines.append(f"- {title} · {field}: {quote(previous)} → {quote(proposed)}.")
    summary = "Cambios propuestos:\n" + "\n".join(lines)
    if len(summary) > 1600:
        return f"Se proponen cambios en {len(changes)} parámetros. Los valores completos se muestran en la comparación del bot."
    return summary
