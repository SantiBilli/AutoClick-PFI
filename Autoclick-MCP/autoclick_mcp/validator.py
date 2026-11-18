import json
import math
import re
from datetime import datetime
from typing import Any
from uuid import UUID

from autoclick_mcp.catalog import ActionCatalog
from autoclick_mcp.pending import is_pending_parameter, allows_pending_parameter
from autoclick_mcp.models import McpIssue, McpResult, ValidationResponse


_TEMPLATE_PATTERN = re.compile(r"{{([A-Za-z_][A-Za-z0-9_]*)}}")
_CONDITION_OPERATORS = {
    "eq", "ne", "lt", "lte", "gt", "gte", "contains", "startsWith",
    "endsWith", "in", "empty", "notEmpty",
}
_UNARY_CONDITION_OPERATORS = {"empty", "notEmpty"}
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_MAX_AI_STATE_SIZE = 512 * 1024
_ICON_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
_BOT_FIELDS = {"schemaVersion", "id", "name", "description", "icon", "ai", "flow"}
_NODE_FIELDS = {"id", "type", "params", "slots"}
VISION_DERIVED_SUFFIXES = (
    '_centroX', '_centrox', '_centroY', '_centroy', '_x', '_y',
    '_ancho', '_alto', '_confianza', '_textoDetectado',
    '_textodetectado', '_encontrado',
)
HTTP_DERIVED_SUFFIXES = ('_status', '_body')


class BotValidator:
    def __init__(self, catalog: ActionCatalog | None = None) -> None:
        self._catalog = catalog or ActionCatalog()

    def validate_bot(self, bot: dict[str, Any], mode: str = "proposal") -> ValidationResponse:
        issues: list[McpIssue] = []
        if mode not in {"proposal", "execution"}:
            return _failure("INVALID_MODE", "mode must be 'proposal' or 'execution'", "mode")
        if not isinstance(bot, dict):
            return _failure("INVALID_STRUCTURE", "El bot debe ser un objeto JSON.")

        _unknown_fields(bot, _BOT_FIELDS, "", issues)
        if bot.get("schemaVersion") != 2:
            _add(issues, "UNSUPPORTED_SCHEMA_VERSION", "Solo se admite schemaVersion=2.", "schemaVersion")
        if not _valid_uuid(bot.get("id")):
            _add(issues, "INVALID_BOT_ID", "id debe ser un UUID válido.", "id")
        _bounded_string(bot.get("name"), "name", 1, 120, issues)
        description = bot.get("description", "")
        if not isinstance(description, str) or len(description) > 500:
            _add(issues, "INVALID_METADATA", "description debe ser texto de hasta 500 caracteres.", "description")
        if "icon" in bot and bot["icon"] is not None and (
            not isinstance(bot["icon"], str) or _ICON_PATTERN.fullmatch(bot["icon"].strip()) is None
        ):
            _add(issues, "INVALID_ICON", "icon debe ser un identificador canónico válido.", "icon")
        if "ai" in bot and not _valid_ai_state(bot["ai"]):
            _add(issues, "INVALID_AI_STATE", "ai no cumple el contrato canónico.", "ai")

        flow = bot.get("flow")
        if not isinstance(flow, dict):
            _add(issues, "INVALID_FLOW", "El bot debe contener un objeto 'flow'.", "flow")
            return _result(issues, 0, mode)
        _unknown_fields(flow, {"root", "nodes"}, "flow", issues)
        root, nodes = flow.get("root"), flow.get("nodes")
        if not isinstance(root, list):
            _add(issues, "INVALID_ROOT", "flow.root debe ser una lista.", "flow.root")
        if not isinstance(nodes, list):
            _add(issues, "INVALID_NODES", "flow.nodes debe ser una lista.", "flow.nodes")
        if not isinstance(root, list) or not isinstance(nodes, list):
            return _result(issues, 0, mode)
        if len(nodes) > 1000:
            _add(issues, "TOO_MANY_NODES", "flow.nodes excede el máximo de 1000 nodos.", "flow.nodes")

        by_id: dict[str, dict[str, Any]] = {}
        valid_actions: dict[str, dict[str, Any]] = {}
        for index, node in enumerate(nodes):
            path = f"flow.nodes[{index}]"
            if not isinstance(node, dict):
                _add(issues, "INVALID_NODE_STRUCTURE", "Cada nodo debe ser un objeto.", path)
                continue
            _unknown_fields(node, _NODE_FIELDS, path, issues)
            node_id = node.get("id")
            if not isinstance(node_id, str) or not node_id.strip():
                _add(issues, "MISSING_NODE_ID", "El nodo debe tener un ID no vacío.", f"{path}.id")
                continue
            if node_id in by_id:
                _add(issues, "DUPLICATE_NODE_ID", f"ID de nodo duplicado: '{node_id}'.", f"{path}.id", node_id)
                continue
            by_id[node_id] = node
            action_type = node.get("type")
            action = self._catalog._actions_by_id.get(action_type) if isinstance(action_type, str) else None
            if action is None:
                _add(issues, "UNKNOWN_ACTION", f"Acción desconocida '{action_type}'.", f"{path}.type", node_id, str(action_type))
                continue
            valid_actions[node_id] = action
            self._validate_node(node, action, path, issues, mode)

        placements: dict[str, int] = {}
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in by_id}

        def register(children: Any, path: str, parent_id: str | None = None) -> None:
            if not isinstance(children, list):
                _add(issues, "INVALID_SLOT", "Las secuencias deben ser listas de IDs.", path, parent_id)
                return
            for index, child_id in enumerate(children):
                child_path = f"{path}[{index}]"
                if not isinstance(child_id, str) or not child_id:
                    _add(issues, "INVALID_CHILD_REFERENCE", "La referencia debe ser un ID no vacío.", child_path, parent_id)
                    continue
                if child_id not in by_id:
                    _add(issues, "MISSING_NODE_REFERENCE", f"El nodo '{child_id}' no existe.", child_path, child_id)
                    continue
                placements[child_id] = placements.get(child_id, 0) + 1
                if parent_id is not None:
                    adjacency[parent_id].append(child_id)

        register(root, "flow.root")
        for node_id, node in by_id.items():
            slots = node.get("slots")
            if isinstance(slots, dict):
                for slot, children in slots.items():
                    register(children, f"flow.nodes[{node_id!r}].slots.{slot}", node_id)

        reachable: set[str] = set()
        def mark_reachable(node_id: str) -> None:
            if node_id in reachable:
                return
            reachable.add(node_id)
            for child in adjacency[node_id]:
                mark_reachable(child)
        for node_id in root:
            if isinstance(node_id, str) and node_id in by_id:
                mark_reachable(node_id)

        for node_id in by_id:
            count = placements.get(node_id, 0)
            if node_id not in reachable:
                _add(issues, "ORPHAN_NODE", f"El nodo '{node_id}' no es alcanzable desde la raíz.", node_id=node_id)
            if count > 1:
                _add(issues, "MULTIPLE_PLACEMENT", f"El nodo '{node_id}' está colocado más de una vez.", node_id=node_id)

        state: dict[str, int] = {}
        def visit(node_id: str) -> None:
            if state.get(node_id) == 1:
                _add(issues, "CYCLE", f"El nodo '{node_id}' forma un ciclo.", node_id=node_id)
                return
            if state.get(node_id) == 2:
                return
            state[node_id] = 1
            for child in adjacency[node_id]:
                visit(child)
            state[node_id] = 2
        for node_id in by_id:
            visit(node_id)

        if not any(issue.code in {
            "INVALID_NODE_STRUCTURE", "MISSING_NODE_ID", "DUPLICATE_NODE_ID", "UNKNOWN_ACTION",
            "INVALID_PARAMS", "INVALID_SLOTS", "INVALID_SLOT", "UNDECLARED_SLOT", "MISSING_SLOT",
            "INVALID_CHILD_REFERENCE", "MISSING_NODE_REFERENCE", "MULTIPLE_PLACEMENT",
            "ORPHAN_NODE", "CYCLE",
        } for issue in issues):
            self._validate_dataflow(root, by_id, valid_actions, issues)

        return _result(issues, len(by_id), mode)

    def _validate_node(
        self, node: dict[str, Any], action: dict[str, Any], path: str, issues: list[McpIssue], mode: str
    ) -> None:
        node_id = node["id"]
        params = node.get("params")
        if not isinstance(params, dict):
            _add(issues, "INVALID_PARAMS", "params debe ser un objeto.", f"{path}.params", node_id)
        else:
            fields = {field["name"]: field for field in action.get("fields", [])}
            for name in params.keys() - fields.keys():
                _add(issues, "UNKNOWN_PARAMETER", f"Parámetro desconocido '{name}'.", f"{path}.params.{name}", node_id, action["id"])
            for name, field in fields.items():
                supplied = name in params
                value = params.get(name, action.get("defaults", {}).get(name))
                if is_pending_parameter(value) and allows_pending_parameter(field['type'], name):
                    issues.append(McpIssue(
                        code="PENDING_PARAMETER", message=f"Completá {field.get('label', name)} antes de ejecutar.",
                        path=f"{path}.params.{name}", nodeId=node_id, actionId=action['id'],
                        severity="warning" if mode == "proposal" else "error",
                    ))
                    continue
                if not supplied and name not in action.get("defaults", {}):
                    if field.get("required"):
                        _add(issues, "REQUIRED_PARAMETER", f"Falta el parámetro obligatorio '{name}'.", f"{path}.params.{name}", node_id, action["id"])
                    continue
                if field.get("required") and value == "":
                    _add(issues, "REQUIRED_PARAMETER", f"El parámetro '{name}' no puede estar vacío.", f"{path}.params.{name}", node_id, action["id"])
                elif not _valid_field_value(field, value):
                    _add(issues, "INVALID_PARAMETER", f"Valor inválido para '{name}'.", f"{path}.params.{name}", node_id, action["id"])

            if not any(
                issue.nodeId == node_id and issue.code in {
                    "UNKNOWN_PARAMETER", "REQUIRED_PARAMETER", "INVALID_PARAMETER"
                }
                for issue in issues
            ):
                normalized = _materialize_params(action, params)
                self._validate_action_invariants(node, normalized, path, issues)

        slots = node.get("slots", {})
        if not isinstance(slots, dict):
            _add(issues, "INVALID_SLOTS", "slots debe ser un objeto.", f"{path}.slots", node_id)
            return
        declared = set(action.get("slots", []))
        actual = set(slots)
        for slot in sorted(actual - declared):
            _add(issues, "UNDECLARED_SLOT", f"El slot '{slot}' no está declarado.", f"{path}.slots.{slot}", node_id, action["id"])
        for slot in sorted(declared - actual):
            _add(issues, "MISSING_SLOT", f"Falta el slot declarado '{slot}'.", f"{path}.slots.{slot}", node_id, action["id"])
        for slot, children in slots.items():
            if not isinstance(children, list):
                _add(issues, "INVALID_SLOT", f"El slot '{slot}' debe ser una lista.", f"{path}.slots.{slot}", node_id)

    def _validate_action_invariants(
        self,
        node: dict[str, Any],
        params: dict[str, Any],
        path: str,
        issues: list[McpIssue],
    ) -> None:
        node_id = node["id"]
        action_type = node["type"]
        if action_type == "flow.forEach" and not _is_runtime_value(params.get("items")) and not isinstance(params.get("items"), list):
            _add(issues, "INVALID_PARAMETER", "items debe ser un arreglo JSON.", f"{path}.params.items", node_id, action_type)
        if action_type == "flow.forRange":
            start, end, step = params.get("start"), params.get("end"), params.get("step")
            if not _is_runtime_value(step) and step == 0:
                _add(issues, "INVALID_PARAMETER", "step debe ser distinto de cero.", f"{path}.params.step", node_id, action_type)
            elif all(isinstance(value, int) and not isinstance(value, bool) for value in (start, end, step)) and (end - start) * step < 0:
                _add(issues, "INVALID_PARAMETER", "step debe avanzar hacia end.", f"{path}.params.step", node_id, action_type)
        if action_type in {"mouse.move", "mouse.click", "mouse.rightClick", "mouse.doubleClick"}:
            x, y = params.get("x"), params.get("y")
            if not _is_runtime_value(x) and not _is_runtime_value(y) and (x is None) != (y is None):
                missing = "x" if x is None else "y"
                _add(issues, "COORDINATE_PAIR_REQUIRED", "x e y deben configurarse juntos.", f"{path}.params.{missing}", node_id, action_type)
        if action_type == "http.request":
            for name in ("headers", "query"):
                value = params.get(name)
                if value is not None and not _is_runtime_value(value) and not isinstance(value, dict):
                    _add(issues, "INVALID_PARAMETER", f"{name} debe ser un objeto JSON.", f"{path}.params.{name}", node_id, action_type)
        if action_type == "excel.writeCell":
            value = params.get("value")
            if not _is_runtime_value(value) and not _is_excel_scalar(value):
                _add(issues, "INVALID_PARAMETER", "value debe ser un escalar de Excel.", f"{path}.params.value", node_id, action_type)
        if action_type.startswith("excel."):
            for name in ("cell", "range"):
                value = params.get(name)
                if value is not None and not _is_runtime_value(value) and (
                    not isinstance(value, str)
                    or not _valid_a1_reference(value, allow_range=name == "range")
                ):
                    _add(issues, "INVALID_PARAMETER", f"{name} debe ser una referencia A1 válida.", f"{path}.params.{name}", node_id, action_type)
            path_value = params.get("path")
            if path_value not in (None, "") and not _is_runtime_value(path_value) and (
                not isinstance(path_value, str) or not _valid_excel_path(path_value)
            ):
                _add(issues, "INVALID_PARAMETER", "path debe ser una ruta local de Excel válida.", f"{path}.params.path", node_id, action_type)
        if action_type == "excel.writeRange" and isinstance(params.get("range"), str) and not _is_runtime_value(params.get("value")):
            if not _excel_matrix_matches_range(params.get("value"), params["range"]):
                _add(issues, "INVALID_PARAMETER", "value debe coincidir con el tamaño de range.", f"{path}.params.value", node_id, action_type)
        if action_type == "workflow.run":
            value = params.get("path")
            if not _is_runtime_value(value) and (
                not isinstance(value, str) or re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", value) is None
            ):
                _add(issues, "INVALID_PARAMETER", "path debe ser una ruta absoluta.", f"{path}.params.path", node_id, action_type)
        if action_type.startswith(("file.", "folder.")):
            for name in ("path", "source", "destination"):
                value = params.get(name)
                if value is not None and not _is_runtime_value(value) and (
                    not isinstance(value, str)
                    or re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", value) is None
                ):
                    _add(issues, "INVALID_PARAMETER", f"{name} debe ser una ruta absoluta.", f"{path}.params.{name}", node_id, action_type)

    def _validate_dataflow(
        self,
        root: list[Any],
        by_id: dict[str, dict[str, Any]],
        actions: dict[str, dict[str, Any]],
        issues: list[McpIssue],
    ) -> None:
        State = tuple[frozenset[str], frozenset[str]]
        before: dict[str, State] = {}
        reachable: set[str] = set()

        def join(left: State | None, right: State | None) -> State | None:
            if left is None:
                return right
            if right is None:
                return left
            return left[0] & right[0], left[1] & right[1]

        def leaf(node: dict[str, Any], state: State) -> State:
            variables, workbooks = set(state[0]), set(state[1])
            action = actions[node["id"]]
            params = _materialize_params(action, node["params"])
            if node["type"] == "variable.create" and isinstance(params.get("name"), str):
                variables.add(params["name"])
            elif node["type"] == "variable.delete" and isinstance(params.get("name"), str):
                variables.discard(params["name"])
            for output in action.get("outputs", []):
                name = params.get(output.get("field"))
                if isinstance(name, str):
                    (workbooks if output.get("type") == "workbook" else variables).add(name)
                    if node["type"] == "vision.detectElement":
                        variables.update(name + suffix for suffix in VISION_DERIVED_SUFFIXES)
                    elif node["type"] == "http.request":
                        variables.update(name + suffix for suffix in HTTP_DERIVED_SUFFIXES)
            workbook = params.get("workbookVariable")
            if node["type"] == "excel.close" and isinstance(workbook, str):
                workbooks.discard(workbook)
            return frozenset(variables), frozenset(workbooks)

        def sequence(ids: list[Any], incoming: State) -> State | None:
            valid_ids = [node_id for node_id in ids if isinstance(node_id, str) and node_id in actions]
            if not valid_ids:
                return incoming
            positions = {node_id: index for index, node_id in enumerate(valid_ids)}
            inputs: list[State | None] = [None] * len(valid_ids)
            inputs[0] = incoming
            queue = [0]
            exits: list[State] = []

            def transfer(node: dict[str, Any], state: State) -> State | None:
                params = _materialize_params(actions[node["id"]], node["params"])
                slots = node.get("slots", {})
                if node["type"] == "flow.if":
                    return join(
                        sequence(slots.get("then", []), state),
                        sequence(slots.get("else", []), state),
                    )
                if node["type"] == "flow.tryCatch":
                    variables = set(state[0])
                    error_name = params.get("errorVariable")
                    if isinstance(error_name, str) and error_name:
                        variables.add(error_name)
                    nested = frozenset(variables), state[1]
                    return join(
                        sequence(slots.get("try", []), nested),
                        sequence(slots.get("catch", []), nested),
                    )
                if node["type"] == "flow.group":
                    return sequence(slots.get("body", []), state)
                if node["type"] in {"flow.forRange", "flow.forEach", "flow.while"}:
                    variables = set(state[0])
                    loop_names: list[Any] = []
                    if node["type"] == "flow.forRange":
                        loop_names.append(params.get("currentVariable"))
                    elif node["type"] == "flow.forEach":
                        loop_names.extend((params.get("itemVariable"), params.get("indexVariable")))
                    variables.update(name for name in loop_names if isinstance(name, str) and name)
                    body = sequence(
                        slots.get("body", []),
                        (frozenset(variables), state[1]),
                    )
                    count = _static_loop_iteration_count(node, actions[node["id"]])
                    if body is None:
                        return state if count in {None, 0} else None
                    if count is not None and count > 0:
                        return body
                    return state[0] & body[0], state[1] & body[1]
                return leaf(node, state)

            while queue:
                index = queue.pop(0)
                current = inputs[index]
                if current is None:
                    continue
                node = by_id[valid_ids[index]]
                reachable.add(node["id"])
                before[node["id"]] = join(before.get(node["id"]), current) or current
                output = transfer(node, current)
                if output is None:
                    continue
                if node["type"] == "flow.goTo":
                    successor = positions.get(node["params"].get("targetNodeId"))
                elif node["type"] == "execution.stop":
                    successor = None
                else:
                    successor = index + 1 if index + 1 < len(valid_ids) else None
                if successor is None:
                    if node["type"] != "flow.goTo":
                        exits.append(output)
                    continue
                merged = join(inputs[successor], output)
                if merged != inputs[successor]:
                    inputs[successor] = merged
                    if successor not in queue:
                        queue.append(successor)
            result: State | None = None
            for exit_state in exits:
                result = join(result, exit_state)
            return result

        def validate_goto_targets(ids: list[Any]) -> None:
            positions = {node_id for node_id in ids if isinstance(node_id, str)}
            for node_id in ids:
                if not isinstance(node_id, str) or node_id not in actions:
                    continue
                node = by_id[node_id]
                if node["type"] == "flow.goTo" and node["params"].get("targetNodeId") not in positions:
                    _add(issues, "INVALID_GOTO_TARGET", "goTo debe apuntar a un nodo de la misma secuencia.", f"flow.nodes[{node_id!r}].params.targetNodeId", node_id)
                for children in node.get("slots", {}).values():
                    validate_goto_targets(children)

        validate_goto_targets(root)
        sequence(root, (frozenset(), frozenset()))
        self._validate_repeated_effects(
            root, by_id, actions, before, reachable, issues
        )

        for node_id in reachable:
            node, action = by_id[node_id], actions[node_id]
            params = _materialize_params(action, node["params"])
            variables, workbooks = before.get(node_id, (frozenset(), frozenset()))
            available = variables | workbooks
            for name, value in params.items():
                field = next((field for field in action.get("fields", []) if field["name"] == name), None)
                if field is not None and field.get("type") != "variable":
                    for reference in _template_names(value):
                        if reference not in available:
                            _add(issues, "VARIABLE_MISSING", f"La variable '{reference}' no está definitivamente disponible.", f"flow.nodes[{node_id!r}].params.{name}", node_id)
            if node["type"] in {"variable.update", "variable.delete"}:
                name = params.get("name")
                if isinstance(name, str) and name not in variables:
                    _add(issues, "VARIABLE_MISSING", f"La variable '{name}' no está definitivamente disponible.", f"flow.nodes[{node_id!r}].params.name", node_id)
            workbook = params.get("workbookVariable")
            if isinstance(workbook, str) and node["type"].startswith("excel.") and workbook not in workbooks:
                _add(issues, "WORKBOOK_MISSING", f"El libro '{workbook}' no está definitivamente disponible.", f"flow.nodes[{node_id!r}].params.workbookVariable", node_id)
            if node["type"] == "variable.create" and isinstance(params.get("name"), str) and params["name"] in available:
                _add(issues, "VARIABLE_DUPLICATE", f"La variable '{params['name']}' ya existe.", f"flow.nodes[{node_id!r}].params.name", node_id)
            for output in action.get("outputs", []):
                name = params.get(output.get("field"))
                if not isinstance(name, str) or node["type"] == "variable.create":
                    continue
                names = [name]
                if node["type"] == "vision.detectElement":
                    names.extend(name + suffix for suffix in VISION_DERIVED_SUFFIXES)
                elif node["type"] == "http.request":
                    names.extend(name + suffix for suffix in HTTP_DERIVED_SUFFIXES)
                for output_name in names:
                    if output_name in available:
                        code = "WORKBOOK_DUPLICATE" if output.get("type") == "workbook" else "VARIABLE_DUPLICATE"
                        _add(issues, code, f"La salida '{output_name}' ya existe.", f"flow.nodes[{node_id!r}].params.{output.get('field')}", node_id)

    def _validate_repeated_effects(
        self,
        root: list[Any],
        by_id: dict[str, dict[str, Any]],
        actions: dict[str, dict[str, Any]],
        before: dict[str, tuple[frozenset[str], frozenset[str]]],
        reachable: set[str],
        issues: list[McpIssue],
    ) -> None:
        repeated: set[str] = set()

        def descendants(node_id: str) -> set[str]:
            found = {node_id}
            for children in by_id[node_id].get("slots", {}).values():
                for child_id in children:
                    if child_id in by_id:
                        found.update(descendants(child_id))
            return found

        def goto_cycles(ids: list[Any]) -> None:
            valid_ids = [
                node_id
                for node_id in ids
                if isinstance(node_id, str) and node_id in actions
            ]
            positions = {node_id: index for index, node_id in enumerate(valid_ids)}
            edges: dict[str, list[str]] = {node_id: [] for node_id in valid_ids}
            for index, node_id in enumerate(valid_ids):
                node = by_id[node_id]
                if node["type"] == "flow.goTo":
                    target = node["params"].get("targetNodeId")
                    if isinstance(target, str) and target in positions:
                        edges[node_id].append(target)
                elif node["type"] != "execution.stop" and index + 1 < len(valid_ids):
                    edges[node_id].append(valid_ids[index + 1])

            index_counter = 0
            stack: list[str] = []
            on_stack: set[str] = set()
            indexes: dict[str, int] = {}
            lowlinks: dict[str, int] = {}

            def connect(node_id: str) -> None:
                nonlocal index_counter
                indexes[node_id] = lowlinks[node_id] = index_counter
                index_counter += 1
                stack.append(node_id)
                on_stack.add(node_id)
                for successor in edges[node_id]:
                    if successor not in indexes:
                        connect(successor)
                        lowlinks[node_id] = min(lowlinks[node_id], lowlinks[successor])
                    elif successor in on_stack:
                        lowlinks[node_id] = min(lowlinks[node_id], indexes[successor])
                if lowlinks[node_id] != indexes[node_id]:
                    return
                component: list[str] = []
                while True:
                    member = stack.pop()
                    on_stack.remove(member)
                    component.append(member)
                    if member == node_id:
                        break
                cyclic = len(component) > 1 or component[0] in edges[component[0]]
                if cyclic:
                    for member in component:
                        repeated.update(descendants(member))
                    reachable_members = sorted(set(component) & reachable)
                    if reachable_members:
                        node_id = reachable_members[0]
                        _add(
                            issues,
                            "INFINITE_GOTO_CYCLE",
                            "El ciclo de flow.goTo produce una ejecución infinita.",
                            f"flow.nodes[{node_id!r}].params.targetNodeId",
                            node_id,
                            "flow.goTo",
                        )

            for node_id in valid_ids:
                if node_id not in indexes:
                    connect(node_id)
                for children in by_id[node_id].get("slots", {}).values():
                    goto_cycles(children)

        def structural_loops(ids: list[Any]) -> None:
            for node_id in ids:
                if not isinstance(node_id, str) or node_id not in actions:
                    continue
                node = by_id[node_id]
                if (
                    node_id in reachable
                    and node["type"] in {"flow.forRange", "flow.forEach", "flow.while"}
                    and (
                        (count := _static_loop_iteration_count(node, actions[node_id]))
                        is None or count > 1
                    )
                ):
                    for child_id in node.get("slots", {}).get("body", []):
                        if child_id in by_id:
                            repeated.update(descendants(child_id))
                for children in node.get("slots", {}).values():
                    structural_loops(children)

        goto_cycles(root)
        structural_loops(root)
        for node_id in repeated & reachable:
            node = by_id[node_id]
            params = _materialize_params(actions[node_id], node["params"])
            variables, _workbooks = before.get(
                node_id, (frozenset(), frozenset())
            )
            name = params.get("name")
            if node["type"] == "variable.create":
                _add(issues, "VARIABLE_AMBIGUOUS", "No se puede crear una variable en una región repetible.", f"flow.nodes[{node_id!r}].params.name", node_id)
            if (
                node["type"] == "variable.delete"
                and isinstance(name, str)
                and name in variables
            ):
                _add(issues, "VARIABLE_AMBIGUOUS", "No se puede eliminar una variable entrante en una región repetible.", f"flow.nodes[{node_id!r}].params.name", node_id)
            if node["type"] in {"excel.open", "excel.create"}:
                _add(issues, "WORKBOOK_DUPLICATE", "No se puede abrir el mismo libro en una región repetible.", f"flow.nodes[{node_id!r}].params.outputVariable", node_id)
            if node["type"] == "excel.close":
                _add(issues, "WORKBOOK_CLOSED", "No se puede cerrar el mismo libro en una región repetible.", f"flow.nodes[{node_id!r}].params.workbookVariable", node_id)

    def validate_bot_patch(
        self, base_bot: dict[str, Any], operations: list[dict[str, Any]]
    ) -> McpResult[dict[str, Any]]:
        from autoclick_mcp.preview import PatchError, apply_patch

        try:
            apply_patch(base_bot, operations, self._catalog)
        except PatchError as error:
            return McpResult(
                ok=False,
                data=None,
                issues=[McpIssue(code=error.code, message=str(error), operationIndex=error.operation_index)],
            )
        return McpResult(ok=True, data={"valid": True, "operationCount": len(operations)}, issues=[])


def _valid_field_value(field: dict[str, Any], value: Any) -> bool:
    field_type = field.get("type")
    if _has_malformed_template(value):
        return False
    if field_type != "variable" and _template_names(value):
        return True
    if field_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif field_type == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)
    elif field_type == "boolean":
        valid = isinstance(value, bool)
    elif field_type == "json":
        valid = _finite_json(value)
    elif field_type == "condition":
        valid = _valid_condition(value)
    else:
        valid = isinstance(value, str)
    if not valid:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if field.get("min") is not None and value < field["min"]:
            return False
        if field.get("max") is not None and value > field["max"]:
            return False
    if isinstance(value, str):
        if field.get("minLength") is not None and len(value) < field["minLength"]:
            return False
        if field.get("maxLength") is not None and len(value) > field["maxLength"]:
            return False
        if field.get("pattern") is not None and re.fullmatch(field["pattern"], value) is None:
            return False
        if field.get("options") is not None and value not in field["options"]:
            return False
    return True


def _materialize_params(action: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    return {**action.get("defaults", {}), **params}


def _static_loop_iteration_count(
    node: dict[str, Any], action: dict[str, Any]
) -> int | None:
    params = _materialize_params(action, node["params"])
    max_iterations = params.get("maxIterations")
    valid_max = (
        max_iterations
        if isinstance(max_iterations, int)
        and not isinstance(max_iterations, bool)
        and max_iterations > 0
        else None
    )
    if node["type"] == "flow.forRange":
        start, end, step = params.get("start"), params.get("end"), params.get("step")
        if all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (start, end, step)
        ) and step and (end - start) * step >= 0:
            natural_count = abs(end - start) // abs(step) + 1
            return min(natural_count, valid_max) if valid_max is not None else natural_count
    if node["type"] == "flow.forEach" and isinstance(params.get("items"), list):
        natural_count = len(params["items"])
        return min(natural_count, valid_max) if valid_max is not None else natural_count
    return None


def _is_runtime_value(value: Any) -> bool:
    return is_pending_parameter(value) or bool(_template_names(value))


def _is_excel_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, bool, int)) or isinstance(value, float) and math.isfinite(value)


def _a1_parts(value: str) -> tuple[int, int] | None:
    match = re.fullmatch(r"([A-Za-z]{1,3})([1-9][0-9]{0,6})", value)
    if match is None:
        return None
    column = 0
    for character in match.group(1).upper():
        column = column * 26 + ord(character) - 64
    row = int(match.group(2))
    return (column, row) if column <= 16_384 and row <= 1_048_576 else None


def _valid_a1_reference(value: str, *, allow_range: bool) -> bool:
    parts = value.split(":")
    allowed_lengths = {1, 2} if allow_range else {1}
    return len(parts) in allowed_lengths and all(_a1_parts(part) is not None for part in parts)


def _excel_matrix_matches_range(value: Any, range_value: str) -> bool:
    if not isinstance(value, list) or not value or any(
        not isinstance(row, list) or not row for row in value
    ):
        return False
    width = len(value[0])
    if any(len(row) != width for row in value) or any(
        not _is_excel_scalar(cell) for row in value for cell in row
    ):
        return False
    parts = range_value.split(":")
    if len(parts) not in {1, 2}:
        return False
    start, end = _a1_parts(parts[0]), _a1_parts(parts[-1])
    if start is None or end is None:
        return False
    return (
        len(value) == abs(end[1] - start[1]) + 1
        and width == abs(end[0] - start[0]) + 1
    )


def _valid_excel_path(value: str) -> bool:
    if not value or re.search(r'[\x00-\x1f*?"<>|]', value) or "://" in value:
        return False
    if re.match(r"^(?:\\\\|//|\\\?\\|\\\.\\|\\)", value):
        return False
    drive = re.match(r"^[A-Za-z]:", value)
    if drive and re.match(r"^[A-Za-z]:[\\/]", value) is None:
        return False
    remainder = value[len(drive.group(0)):] if drive else value
    if ":" in remainder:
        return False
    filename = re.split(r"[\\/]", value)[-1]
    return filename.casefold().endswith((".xls", ".xlsx", ".xlsm", ".xlsb"))


def _valid_condition(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {"combinator", "clauses"}:
        return False
    clauses = value.get("clauses")
    if value.get("combinator") not in {"all", "any"} or not isinstance(clauses, list) or not clauses:
        return False
    for clause in clauses:
        if not isinstance(clause, dict) or set(clause) - {"left", "operator", "right"}:
            return False
        operator = clause.get("operator")
        if "left" not in clause or operator not in _CONDITION_OPERATORS:
            return False
        if operator not in _UNARY_CONDITION_OPERATORS and "right" not in clause:
            return False
        if not _finite_json(clause["left"]) or (
            "right" in clause and not _finite_json(clause["right"])
        ):
            return False
    return True


def _finite_json(value: Any) -> bool:
    if value is None or isinstance(value, (str, bool)):
        return True
    if isinstance(value, int):
        return abs(value) <= _MAX_SAFE_INTEGER
    if isinstance(value, float):
        return math.isfinite(value) and (not value.is_integer() or abs(value) <= _MAX_SAFE_INTEGER)
    if isinstance(value, list):
        return all(_finite_json(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _finite_json(item) for key, item in value.items())
    return False


def _valid_uuid(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        UUID(value)
    except (ValueError, AttributeError):
        return False
    return True


def _valid_utc_timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None and parsed.utcoffset().total_seconds() == 0


def _valid_ai_state(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "activeConversationId", "conversations"
    }:
        return False
    if value.get("schemaVersion") != 1 or isinstance(value.get("schemaVersion"), bool):
        return False
    active_id = value.get("activeConversationId")
    if active_id is not None and not _valid_uuid(active_id):
        return False
    conversations = value.get("conversations")
    if not isinstance(conversations, list) or len(conversations) > 10:
        return False
    conversation_ids: set[UUID] = set()
    message_ids: set[UUID] = set()
    for conversation in conversations:
        if not isinstance(conversation, dict) or set(conversation) != {
            "id", "title", "createdAt", "updatedAt", "messages"
        }:
            return False
        if not _valid_uuid(conversation.get("id")):
            return False
        conversation_id = UUID(conversation["id"])
        if conversation_id in conversation_ids:
            return False
        conversation_ids.add(conversation_id)
        title = conversation.get("title")
        if not isinstance(title, str) or not (1 <= len(title.strip()) <= 80):
            return False
        if not _valid_utc_timestamp(conversation.get("createdAt")) or not _valid_utc_timestamp(conversation.get("updatedAt")):
            return False
        messages = conversation.get("messages")
        if not isinstance(messages, list) or len(messages) > 60:
            return False
        for message in messages:
            if not _valid_ai_message(message, message_ids):
                return False
    if active_id is not None and UUID(active_id) not in conversation_ids:
        return False
    try:
        encoded = json.dumps(
            value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError):
        return False
    return len(encoded) <= _MAX_AI_STATE_SIZE


def _valid_ai_message(value: Any, seen_ids: set[UUID]) -> bool:
    if not isinstance(value, dict) or set(value) - {
        "id", "role", "content", "createdAt", "status", "metrics"
    } or not {"id", "role", "content", "createdAt", "status"} <= set(value):
        return False
    if not _valid_uuid(value.get("id")):
        return False
    message_id = UUID(value["id"])
    if message_id in seen_ids:
        return False
    seen_ids.add(message_id)
    role, content, status = value.get("role"), value.get("content"), value.get("status")
    if role not in {"user", "assistant"} or status not in {"complete", "interrupted"}:
        return False
    if not isinstance(content, str) or not (1 <= len(content) <= 8_000):
        return False
    if not _valid_utc_timestamp(value.get("createdAt")):
        return False
    if role == "user" and (status != "complete" or "metrics" in value):
        return False
    if "metrics" in value and not _valid_ai_metrics(value["metrics"]):
        return False
    return True


def _valid_ai_metrics(value: Any) -> bool:
    if not isinstance(value, dict) or set(value) != {
        "totalTimeMs", "inputTokens", "outputTokens"
    }:
        return False
    for name in ("totalTimeMs", "inputTokens", "outputTokens"):
        metric = value[name]
        if name != "totalTimeMs" and metric is None:
            continue
        if isinstance(metric, bool) or not isinstance(metric, int) or not (0 <= metric <= _MAX_SAFE_INTEGER):
            return False
    return True


def _template_names(value: Any) -> set[str]:
    if isinstance(value, str):
        return set(_TEMPLATE_PATTERN.findall(value))
    if isinstance(value, list):
        return set().union(*(_template_names(item) for item in value), set())
    if isinstance(value, dict):
        return set().union(*(_template_names(item) for item in value.values()), set())
    return set()


def _has_malformed_template(value: Any) -> bool:
    if isinstance(value, str):
        return "{{" in _TEMPLATE_PATTERN.sub("", value) or "}}" in _TEMPLATE_PATTERN.sub("", value)
    if isinstance(value, list):
        return any(_has_malformed_template(item) for item in value)
    if isinstance(value, dict):
        return any(_has_malformed_template(item) for item in value.values())
    return False


def _unknown_fields(value: dict[str, Any], allowed: set[str], path: str, issues: list[McpIssue]) -> None:
    for field in sorted(value.keys() - allowed):
        _add(issues, "UNKNOWN_FIELD", f"Campo desconocido '{field}'.", f"{path}.{field}".lstrip("."))


def _non_empty_string(value: Any, path: str, code: str, issues: list[McpIssue]) -> None:
    if not isinstance(value, str) or not value.strip():
        _add(issues, code, f"{path} debe ser texto no vacío.", path)


def _bounded_string(value: Any, path: str, minimum: int, maximum: int, issues: list[McpIssue]) -> None:
    if not isinstance(value, str) or not (minimum <= len(value.strip()) <= maximum):
        _add(issues, "INVALID_METADATA", f"{path} debe tener entre {minimum} y {maximum} caracteres.", path)


def _add(
    issues: list[McpIssue], code: str, message: str, path: str | None = None,
    node_id: str | None = None, action_id: str | None = None,
) -> None:
    issues.append(McpIssue(code=code, message=message, path=path, nodeId=node_id, actionId=action_id))


def _failure(code: str, message: str, path: str | None = None) -> ValidationResponse:
    return McpResult(ok=False, data=None, issues=[McpIssue(code=code, message=message, path=path)])


def _result(issues: list[McpIssue], node_count: int, mode: str) -> ValidationResponse:
    ok = not any(issue.severity == "error" for issue in issues)
    return McpResult(
        ok=ok,
        data={"valid": ok, "nodeCount": node_count, "mode": mode} if ok else None,
        issues=issues,
    )
