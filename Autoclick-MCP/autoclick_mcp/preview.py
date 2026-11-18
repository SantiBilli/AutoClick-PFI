import copy
from typing import Any

from autoclick_mcp.catalog import ActionCatalog
from autoclick_mcp.models import McpIssue, McpResult


class PatchError(ValueError):
    def __init__(self, message: str, *, code: str = "INVALID_PATCH", operation_index: int | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.operation_index = operation_index


def apply_patch(
    base_bot: dict[str, Any],
    operations: list[dict[str, Any]],
    catalog: ActionCatalog | None = None,
) -> dict[str, Any]:
    if not isinstance(base_bot, dict):
        raise PatchError("base bot must be an object", code="INVALID_BASE_BOT")
    if not isinstance(operations, list):
        raise PatchError("operations must be a list", code="INVALID_ARGUMENT")

    action_catalog = catalog or ActionCatalog()
    draft = copy.deepcopy(base_bot)
    for index, operation in enumerate(operations):
        try:
            _apply_operation(draft, operation, action_catalog)
        except PatchError as error:
            if error.operation_index is None:
                error.operation_index = index
            raise

    from autoclick_mcp.validator import BotValidator

    validation = BotValidator(action_catalog).validate_bot(draft, mode="proposal")
    if not validation.ok:
        first = validation.issues[0]
        raise PatchError(
            f"patched bot is invalid: {first.message}",
            code=first.code,
        )
    return draft


def _apply_operation(bot: dict[str, Any], operation: dict[str, Any], catalog: ActionCatalog) -> None:
    if not isinstance(operation, dict):
        raise PatchError("each operation must be an object", code="INVALID_OPERATION_FORMAT")
    op = operation.get("op")
    allowed_fields = {
        "setMetadata": {"op", "name", "description"},
        "addNode": {"op", "node", "location"},
        "removeNode": {"op", "nodeId"},
        "moveNode": {"op", "nodeId", "location"},
        "updateNodeParams": {"op", "nodeId", "params"},
        "replaceNode": {"op", "nodeId", "actionType", "params"},
    }
    if not isinstance(op, str) or op not in allowed_fields:
        raise PatchError(f"unknown operation '{op}'", code="UNKNOWN_OPERATION")
    if set(operation) - allowed_fields[op]:
        raise PatchError("operation contains unknown fields", code="INVALID_OPERATION_FORMAT")

    flow = bot.get("flow")
    if not isinstance(flow, dict) or not isinstance(flow.get("root"), list) or not isinstance(flow.get("nodes"), list):
        raise PatchError("base bot has an invalid flow", code="INVALID_BASE_BOT")
    tree = _Tree(flow)

    if op == "setMetadata":
        supplied = False
        if "name" in operation:
            name = operation["name"]
            if not isinstance(name, str) or not name.strip():
                raise PatchError("metadata name must be a non-empty string")
            bot["name"] = name
            supplied = True
        if "description" in operation:
            description = operation["description"]
            if not isinstance(description, str):
                raise PatchError("metadata description must be a string")
            bot["description"] = description
            supplied = True
        if not supplied:
            raise PatchError("setMetadata requires name or description")
        return

    if op == "addNode":
        node = operation.get("node")
        if not isinstance(node, dict) or set(node) != {"id", "type", "params"}:
            raise PatchError("addNode requires a strict node object", code="INVALID_NODE_DATA")
        node_id, action_type, params = node["id"], node["type"], node["params"]
        if not isinstance(node_id, str) or not node_id or not isinstance(action_type, str) or not isinstance(params, dict):
            raise PatchError("addNode has invalid node fields", code="INVALID_NODE_DATA")
        if node_id in tree.by_id:
            raise PatchError(f"duplicate node ID '{node_id}'", code="DUPLICATE_NODE_ID")
        action = catalog._actions_by_id.get(action_type)
        if action is None:
            raise PatchError(f"unknown action '{action_type}'", code="UNKNOWN_ACTION")
        target, index = tree.target(operation.get("location"), catalog)
        new_node = {
            "id": node_id,
            "type": action_type,
            "params": _normalize_params(action, params),
        }
        if action.get("slots"):
            new_node["slots"] = {slot: [] for slot in action["slots"]}
        flow["nodes"].append(new_node)
        target.insert(index, node_id)
        return

    node_id = operation.get("nodeId")
    if not isinstance(node_id, str) or node_id not in tree.by_id:
        raise PatchError(f"node '{node_id}' does not exist", code="NODE_NOT_FOUND")

    if op == "removeNode":
        source = tree.source(node_id)
        source.remove(node_id)
        removed = tree.descendants(node_id)
        flow["nodes"] = [node for node in flow["nodes"] if node.get("id") not in removed]
        return

    if op == "moveNode":
        location = operation.get("location")
        parent_id = location.get("parentId") if isinstance(location, dict) else None
        if parent_id in tree.descendants(node_id):
            raise PatchError("a node cannot be moved into its descendants", code="CONTAINMENT_CYCLE")
        source = tree.source(node_id)
        source.remove(node_id)
        target, index = tree.target(location, catalog)
        target.insert(index, node_id)
        return

    params = operation.get("params")
    if not isinstance(params, dict):
        raise PatchError(f"{op} requires a params object", code="INVALID_PARAMS")
    node = tree.by_id[node_id]
    if op == "updateNodeParams":
        action = catalog._actions_by_id.get(node.get("type"))
        if action is None:
            raise PatchError("updated node has an unknown action", code="UNKNOWN_ACTION")
        node["params"] = _normalize_params(action, params)
        return

    action_type = operation.get("actionType")
    replacement = catalog._actions_by_id.get(action_type) if isinstance(action_type, str) else None
    if replacement is None:
        raise PatchError(f"unknown action '{action_type}'", code="UNKNOWN_ACTION")
    slots = node.get("slots", {})
    if not isinstance(slots, dict):
        raise PatchError("replaced node has invalid slots", code="INVALID_BASE_BOT")
    current_slots = set(slots)
    replacement_slots = set(replacement.get("slots", []))
    if current_slots != replacement_slots:
        raise PatchError("replacement has incompatible slots", code="INCOMPATIBLE_REPLACEMENT")
    node["type"] = action_type
    node["params"] = _normalize_params(replacement, params)


def _normalize_params(action: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    declared = {field.get("name") for field in action.get("fields", [])}
    unknown = set(params) - declared
    if unknown:
        raise PatchError(
            f"parameters contain unknown fields: {', '.join(sorted(unknown))}",
            code="UNKNOWN_PARAMETER",
        )
    normalized = copy.deepcopy(action.get("defaults", {}))
    normalized.update(copy.deepcopy(params))
    return normalized


class _Tree:
    def __init__(self, flow: dict[str, Any]) -> None:
        self.flow = flow
        self.by_id: dict[str, dict[str, Any]] = {}
        for node in flow["nodes"]:
            if not isinstance(node, dict) or not isinstance(node.get("id"), str):
                raise PatchError("base bot contains an invalid node", code="INVALID_BASE_BOT")
            if node["id"] in self.by_id:
                raise PatchError("base bot contains duplicate node IDs", code="DUPLICATE_NODE_ID")
            self.by_id[node["id"]] = node

    def source(self, node_id: str) -> list[str]:
        matches: list[list[str]] = []
        if node_id in self.flow["root"]:
            matches.append(self.flow["root"])
        for node in self.by_id.values():
            slots = node.get("slots", {})
            if isinstance(slots, dict):
                matches.extend(children for children in slots.values() if isinstance(children, list) and node_id in children)
        if len(matches) != 1:
            raise PatchError("node placement is invalid", code="INVALID_PLACEMENT")
        return matches[0]

    def target(self, location: Any, catalog: ActionCatalog) -> tuple[list[str], int]:
        if not isinstance(location, dict) or set(location) != {"parentId", "slot", "index"}:
            raise PatchError("location must contain parentId, slot, and index", code="INVALID_LOCATION")
        parent_id, slot, index = location["parentId"], location["slot"], location["index"]
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise PatchError("location index is invalid", code="INVALID_INDEX")
        if parent_id is None:
            if slot != "root":
                raise PatchError("root location must use the root slot", code="INVALID_LOCATION")
            target = self.flow["root"]
        else:
            if not isinstance(parent_id, str) or parent_id not in self.by_id:
                raise PatchError(f"parent '{parent_id}' does not exist", code="PARENT_NOT_FOUND")
            parent = self.by_id[parent_id]
            action = catalog._actions_by_id.get(parent.get("type"))
            if action is None or slot not in action.get("slots", []):
                raise PatchError(f"slot '{slot}' is not declared by the parent", code="UNDECLARED_SLOT")
            slots = parent.get("slots")
            if not isinstance(slots, dict) or not isinstance(slots.get(slot), list):
                raise PatchError("parent slot is structurally invalid", code="INVALID_LOCATION")
            target = slots[slot]
        if index > len(target):
            raise PatchError("location index is out of range", code="INVALID_INDEX")
        return target, index

    def descendants(self, node_id: str) -> set[str]:
        found: set[str] = set()
        visiting: set[str] = set()

        def visit(current: str) -> None:
            if current in visiting:
                raise PatchError("base bot contains a cycle", code="CONTAINMENT_CYCLE")
            if current in found:
                return
            visiting.add(current)
            found.add(current)
            node = self.by_id.get(current)
            if node is not None:
                slots = node.get("slots", {})
                if isinstance(slots, dict):
                    for children in slots.values():
                        if isinstance(children, list):
                            for child in children:
                                if isinstance(child, str):
                                    visit(child)
            visiting.remove(current)

        visit(node_id)
        return found


class BotPreviewer:
    def __init__(self, catalog: ActionCatalog | None = None) -> None:
        self._catalog = catalog or ActionCatalog()

    def preview_bot_patch(
        self, base_bot: dict[str, Any], operations: list[dict[str, Any]]
    ) -> McpResult[dict[str, Any]]:
        try:
            result_bot = apply_patch(base_bot, operations, self._catalog)
        except PatchError as error:
            return McpResult(
                ok=False,
                data=None,
                issues=[McpIssue(
                    code=error.code,
                    message=str(error),
                    operationIndex=error.operation_index,
                )],
            )
        return McpResult(ok=True, data={"previewBot": result_bot}, issues=[])
