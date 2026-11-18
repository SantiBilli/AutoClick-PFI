import copy
from autoclick_desktop.pending_parameters import is_pending_parameter
import ctypes
import math
import ntpath
import os
import re
import sys
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import Any, Iterable, Mapping
from dataclasses import replace

from pydantic import JsonValue, ValidationError

from autoclick_desktop.action_registry import (
    ActionDefinition,
    ActionField,
    ActionRegistry,
    load_action_registry,
)
from autoclick_desktop.bot_schema import MAX_SAFE_INTEGER, Bot, BotNode, CanonicalBotInput, validate_finite_json
from autoclick_desktop.conditions import Condition
from autoclick_desktop.execution_context import (
    LocalPathInspector,
    VirtualDesktopBounds,
    VirtualDesktopProvider,
)
from autoclick_desktop.execution_errors import (
    ExecutionErrorCode,
    SafeExecutionError,
    VariableResolutionError,
)
from autoclick_desktop.execution_models import (
    DeferredFieldValidation,
    ExecutionPlan,
    ResolvedAction,
    RuntimeCloseClaim,
    RuntimeCloseConflict,
    RuntimeOpenReservation,
    RuntimeReservationConflict,
    RuntimeSaveAsClaim,
    RuntimeSaveAsConflict,
    RuntimeValidationState,
    PlannedNode,
    ValidatedAction,
    ValidationIssue,
    ValidationIssueCode,
    assign_public_block_ids,
    normalize_windows_path_key,
)
from autoclick_desktop.execution_variables import (
    RUNTIME_UNKNOWN,
    RuntimeUnknown,
    resolve_value,
    token_names,
)
from autoclick_desktop.handler_keys import HANDLER_KEYS


KNOWN_HANDLER_KEYS = HANDLER_KEYS
EXCEL_EXTENSIONS = frozenset({".xls", ".xlsx", ".xlsm", ".xlsb"})
WINDOWS_DEVICE_NAMES = frozenset(
    {"con", "prn", "aux", "nul"}
    | {f"com{index}" for index in range(1, 10)}
    | {f"lpt{index}" for index in range(1, 10)}
    | {f"com{index}" for index in "¹²³"}
    | {f"lpt{index}" for index in "¹²³"}
)
A1_CELL = re.compile(r"^([A-Za-z]{1,3})([1-9][0-9]{0,6})$")
MODIFIER_KEYS = frozenset({"ctrl", "shift", "alt", "win"})
NAMED_KEYS = frozenset(
    {
        "backspace", "tab", "enter", "esc", "space", "delete", "insert", "home", "end",
        "pageup", "pagedown", "left", "right", "up", "down", "capslock", "numlock",
        "scrolllock", "pause", "printscreen", "decimal", "add", "subtract", "multiply",
        "divide", "separator", "volumeup", "volumedown", "volumemute",
        "accept", "apps", "browserback", "browserfavorites", "browserforward", "browserhome",
        "browserrefresh", "browsersearch", "browserstop", "clear", "convert", "del", "escape",
        "execute", "final", "fn", "hanguel", "hangul", "hanja", "help", "junja", "kana",
        "kanji", "launchapp1", "launchapp2", "launchmail", "launchmediaselect", "modechange",
        "nexttrack", "nonconvert", "pgdn", "pgup", "playpause", "prevtrack", "print",
        "prntscrn", "prtsc", "prtscr", "return", "select", "sleep", "stop", "yen",
        "command", "option", "optionleft", "optionright", "altleft", "altright", "ctrlleft",
        "ctrlright", "shiftleft", "shiftright", "winleft", "winright",
    }
)
KEY_ALLOWLIST = frozenset(
    set(MODIFIER_KEYS)
    | set(NAMED_KEYS)
    | set("abcdefghijklmnopqrstuvwxyz0123456789")
    | {f"num{index}" for index in range(10)}
    | {f"f{index}" for index in range(1, 25)}
)


class ExecutionPreflightError(SafeExecutionError):
    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        codes = {issue.code for issue in self.issues}
        if ValidationIssueCode.UNSUPPORTED_ACTION in codes or ValidationIssueCode.UNKNOWN_HANDLER in codes:
            code = ExecutionErrorCode.EXECUTION_UNSUPPORTED_ACTION
        elif any(issue_code.value.startswith("VARIABLE_") for issue_code in codes):
            code = ExecutionErrorCode.EXECUTION_VARIABLE_INVALID
        else:
            code = ExecutionErrorCode.EXECUTION_BOT_INVALID
        super().__init__(code)


class ResolvedActionValidationError(SafeExecutionError):
    def __init__(self, issues: Iterable[ValidationIssue]) -> None:
        self.issues = tuple(issues)
        super().__init__(ExecutionErrorCode.ACTION_PARAMETER_INVALID)


class WindowsLocalPathInspector:
    """Read-only Windows path checks used by preflight; no file is opened."""

    def is_local_drive(self, path: PureWindowsPath) -> bool:
        drive_type = ctypes.windll.kernel32.GetDriveTypeW(f"{path.drive}\\")
        return drive_type not in {0, 1, 4}

    def exists(self, path: PureWindowsPath) -> bool:
        return os.path.exists(path)

    def is_file(self, path: PureWindowsPath) -> bool:
        return os.path.isfile(path)

    def is_directory(self, path: PureWindowsPath) -> bool:
        return os.path.isdir(path)

    def is_reparse_point(self, path: PureWindowsPath) -> bool:
        try:
            return bool(os.lstat(path).st_file_attributes & 0x400)
        except (AttributeError, FileNotFoundError, OSError):
            return False


def validate_execution_draft(
    draft: CanonicalBotInput | Mapping[str, Any],
    *,
    bot_directory: str | Path | PureWindowsPath,
    virtual_desktop: VirtualDesktopProvider,
    local_paths: LocalPathInspector | None = None,
    registry: ActionRegistry | None = None,
    known_handler_keys: frozenset[str] = KNOWN_HANDLER_KEYS,
    initial_variables: Mapping[str, JsonValue] | None = None,
    initial_workbooks: frozenset[str] = frozenset(),
    initial_base_resolution: tuple[int, int] | None = None,
    workflow_node_ids: frozenset[str] = frozenset(),
    editor_node_ids: frozenset[str] | None = None,
    event_paths: Mapping[str, tuple[str, ...]] | None = None,
    source_directories: Mapping[str, PureWindowsPath] | None = None,
) -> ExecutionPlan:
    try:
        bot = Bot.model_validate(draft)
    except (ValidationError, TypeError, ValueError):
        raise ExecutionPreflightError([ValidationIssue(ValidationIssueCode.BOT_INVALID)]) from None

    issues: list[ValidationIssue] = []
    if not bot.flow.root:
        issues.append(ValidationIssue(ValidationIssueCode.EMPTY_BOT))

    base_directory = _validate_bot_directory(bot_directory)
    path_inspector = local_paths or WindowsLocalPathInspector()
    definitions = {action.id: action for action in (registry or load_action_registry()).actions}
    if workflow_node_ids and "workflow.run" not in known_handler_keys:
        issues.extend(
            ValidationIssue(ValidationIssueCode.UNKNOWN_HANDLER, node_id)
            for node_id in workflow_node_ids
        )
    values: dict[str, JsonValue | RuntimeUnknown] = {}
    actions: list[ValidatedAction] = []
    bounds: VirtualDesktopBounds | None = None
    node_by_id = {node.id: node for node in bot.flow.nodes}
    root_editor_node_ids = editor_node_ids if editor_node_ids is not None else frozenset(node_by_id)
    variable_states, ambiguous_variable_states, reachable_nodes = _variable_states(
        bot, definitions, initial_variables or {}
    )
    variable_owners = _variable_owners(bot, definitions)
    node_directories = {
        node.id: (source_directories or {}).get(node.id, base_directory)
        for node in bot.flow.nodes
    }
    resource_states = _resource_states(
        bot, base_directory, initial_workbooks, initial_base_resolution,
        source_directories=node_directories,
    )
    resource_owners, opened_path_owners = _resource_owners(
        bot, base_directory, source_directories=node_directories
    )
    ordered_nodes: list[tuple[BotNode, tuple[str, ...]]] = []
    def collect(ids: list[str], path: tuple[str, ...]) -> None:
        for index, node_id in enumerate(ids):
            node = node_by_id[node_id]
            node_path = (*path, str(index))
            ordered_nodes.append((node, node_path))
            for slot, children in node.slots.items():
                collect(children, (*node_path, node.id, slot))
    collect(bot.flow.root, ("root",))
    public_block_ids = assign_public_block_ids([node.id for node, _path in ordered_nodes])
    _validate_variable_definition_graph(bot, issues, variable_states)
    _validate_loop_safety(bot, issues)
    _validate_goto_safety(bot, definitions, issues)

    def create_validated_action(
        block_id: str,
        definition: ActionDefinition,
        params: Mapping[str, JsonValue | PureWindowsPath],
        deferred: tuple[DeferredFieldValidation, ...],
        exact_token_fields: frozenset[str],
        path: tuple[str, ...],
    ) -> ValidatedAction:
        instance = object.__new__(ValidatedAction)
        object.__setattr__(instance, "_block_id", block_id)
        object.__setattr__(instance, "_source_node_id", node.id)
        object.__setattr__(
            instance,
            "_editor_block_id",
            node.id if node.id in root_editor_node_ids else None,
        )
        object.__setattr__(instance, "_action_id", definition.id)
        object.__setattr__(instance, "_handler_key", definition.handler_key)
        object.__setattr__(instance, "_title", definition.title)
        object.__setattr__(instance, "_params", copy.deepcopy(dict(params)))
        object.__setattr__(
            instance,
            "_fields",
            tuple(field.model_copy(deep=True) for field in definition.fields),
        )
        object.__setattr__(
            instance,
            "_deferred_validations",
            tuple(
                DeferredFieldValidation(item.field.model_copy(deep=True))
                for item in deferred
            ),
        )
        object.__setattr__(instance, "_exact_token_fields", exact_token_fields)
        object.__setattr__(instance, "_path", path)
        object.__setattr__(instance, "_event_path", (event_paths or {}).get(node.id, path))
        object.__setattr__(instance, "_source_directory", node_directories[node.id])
        object.__setattr__(instance, "_slots", tuple(definition.slots))
        return instance

    for block_index, (node, node_path) in enumerate(ordered_nodes):
        values = dict(variable_states.get(node.id, {}))
        ambiguous_values = set(ambiguous_variable_states.get(node.id, set()))
        invalid_blocks = {issue.block_id for issue in issues}
        values = {
            name: value
            for name, value in values.items()
            if variable_owners.get(name) not in invalid_blocks
        }
        (
            live_workbooks,
            maybe_live_workbooks,
            closed_workbooks,
            opened_paths,
            logical_resolution,
        ) = resource_states[node.id]
        live_workbooks = {
            name for name in live_workbooks
            if resource_owners.get(name) not in invalid_blocks
        }
        maybe_live_workbooks = {
            name for name in maybe_live_workbooks
            if resource_owners.get(name) not in invalid_blocks
        }
        closed_workbooks = set(closed_workbooks)
        opened_paths = {
            path for path in opened_paths
            if opened_path_owners.get(path) not in invalid_blocks
        }
        logical_bounds = (
            VirtualDesktopBounds(0, 0, *logical_resolution)
            if logical_resolution is not None
            else None
        )
        action = definitions.get(node.type)
        if action is None:
            issues.append(_issue(ValidationIssueCode.UNSUPPORTED_ACTION, node))
            continue
        if action.handler_key not in known_handler_keys:
            issues.append(_issue(ValidationIssueCode.UNKNOWN_HANDLER, node))
            continue
        if action.platform == "windows" and sys.platform != "win32":
            issues.append(_issue(ValidationIssueCode.UNKNOWN_HANDLER, node))
            continue

        params, static_params, deferred, field_issues = _normalized_params(
            node, action, values, ambiguous_values
        )
        issues.extend(field_issues)
        if field_issues:
            continue

        if node.type in {"mouse.move", "mouse.click", "mouse.rightClick", "mouse.doubleClick"}:
            x, y = static_params.get("x"), static_params.get("y")
            if x is RUNTIME_UNKNOWN or y is RUNTIME_UNKNOWN:
                pass
            elif (x is None) != (y is None):
                issues.append(_issue(ValidationIssueCode.COORDINATE_PAIR_REQUIRED, node))
            elif isinstance(x, int) and isinstance(y, int):
                if logical_bounds is not None:
                    coordinate_bounds = logical_bounds
                else:
                    if bounds is None:
                        try:
                            bounds = virtual_desktop.get_bounds()
                        except Exception:
                            raise SafeExecutionError(
                                ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE
                            ) from None
                    coordinate_bounds = bounds
                if not coordinate_bounds.contains(x, y):
                    issues.append(_issue(ValidationIssueCode.COORDINATE_OUT_OF_BOUNDS, node))

        if node.type == "system.setBaseResolution":
            width, height = static_params.get("width"), static_params.get("height")
            if isinstance(width, int) and isinstance(height, int):
                logical_bounds = VirtualDesktopBounds(0, 0, width, height)

        if node.type == "keyboard.press":
            try:
                static_key = static_params["key"]
                if static_key is not RUNTIME_UNKNOWN:
                    params["key"] = "+".join(
                        parse_keyboard_key(_string_param(static_params, "key"))
                    )
            except ValueError:
                issues.append(_issue(ValidationIssueCode.KEY_INVALID, node, "key"))

        if node.type == "flow.forRange":
            start, end, step = static_params.get("start"), static_params.get("end"), static_params.get("step")
            if step is not RUNTIME_UNKNOWN and (
                not isinstance(step, int) or isinstance(step, bool) or step == 0
            ):
                issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, "step"))
            elif all(isinstance(value, int) and not isinstance(value, bool) for value in (start, end, step)) and (end - start) * step < 0:
                issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, "step"))
        if node.type == "flow.forEach":
            items = static_params.get("items")
            if items is not RUNTIME_UNKNOWN and not isinstance(items, list):
                issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, "items"))
        if node.type == "workflow.run":
            path_value = static_params.get("path")
            if path_value is not RUNTIME_UNKNOWN and (
                not isinstance(path_value, str) or not PureWindowsPath(path_value).is_absolute()
            ):
                issues.append(_issue(ValidationIssueCode.PATH_INVALID, node, "path"))

        workbook_name = static_params.get("workbookVariable")
        if isinstance(workbook_name, str) and workbook_name in maybe_live_workbooks:
            issues.append(_issue(ValidationIssueCode.WORKBOOK_MISSING, node, "workbookVariable"))
        output_name = static_params.get("outputVariable")
        if node.type in {"excel.open", "excel.create"} and isinstance(output_name, str) and output_name in maybe_live_workbooks:
            issues.append(_issue(ValidationIssueCode.WORKBOOK_DUPLICATE, node, "outputVariable"))

        if node.type.startswith("excel."):
            for field_name in ("cell",):
                if field_name in static_params and static_params[field_name] is not RUNTIME_UNKNOWN:
                    try:
                        params[field_name] = normalize_a1_cell(
                            _string_param(static_params, field_name)
                        )
                    except ValueError:
                        issues.append(_issue(ValidationIssueCode.CELL_INVALID, node, field_name))
            range_value = static_params.get("range")
            if range_value is not None and range_value is not RUNTIME_UNKNOWN:
                try:
                    params["range"] = normalize_a1_range(_string_param(static_params, "range"))
                except ValueError:
                    issues.append(_issue(ValidationIssueCode.CELL_INVALID, node, "range"))
            if node.type == "excel.writeRange" and isinstance(params.get("range"), str):
                matrix = static_params.get("value")
                if matrix is not RUNTIME_UNKNOWN and not _excel_matrix_matches_range(
                    matrix, str(params["range"])
                ):
                    issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, "value"))
            for field_name in ("path",):
                raw_path = static_params.get(field_name)
                if raw_path not in (None, "") and not isinstance(raw_path, RuntimeUnknown):
                    try:
                        params[field_name] = resolve_excel_path(
                            _string_param(params, field_name), node_directories[node.id]
                        )
                        _validate_inspected_path(
                            params[field_name],
                            source=node.type == "excel.open",
                            inspector=path_inspector,
                        )
                    except ValueError:
                        issues.append(_issue(ValidationIssueCode.PATH_INVALID, node, field_name))
                    except Exception:
                        raise SafeExecutionError(
                            ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE
                        ) from None

        if node.type.startswith(("file.", "folder.")):
            for field_name in ("path", "source", "destination"):
                path_value = static_params.get(field_name)
                if path_value is not None and path_value is not RUNTIME_UNKNOWN and (
                    not isinstance(path_value, str) or not PureWindowsPath(path_value).is_absolute()
                ):
                    issues.append(_issue(ValidationIssueCode.PATH_INVALID, node, field_name))

        if node.type == "vision.detectElement":
            scope = static_params.get("scope", "pantalla")
            if scope == "region":
                for dim_name in ("x", "y", "width", "height"):
                    dim_val = static_params.get(dim_name)
                    if dim_val is RUNTIME_UNKNOWN:
                        continue
                    if dim_val is None or not isinstance(dim_val, int) or isinstance(dim_val, bool):
                        issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, dim_name))
                    elif dim_name in ("width", "height") and dim_val <= 0:
                        issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, dim_name))
                    elif dim_name in ("x", "y") and dim_val < 0:
                        issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, dim_name))

        if any(issue.block_id == node.id for issue in issues):
            continue
        if node.id in reachable_nodes:
            _validate_dataflow(
                node, action, params, values, live_workbooks, closed_workbooks, opened_paths, issues
            )
        if not any(issue.block_id == node.id for issue in issues):
            actions.append(
                create_validated_action(
                    public_block_ids[block_index],
                    action,
                    dict(params),
                    deferred,
                    frozenset(
                        field.name
                        for field in action.fields
                        if field.type != "variable"
                        and isinstance(node.params.get(field.name), str)
                        and re.fullmatch(
                            r"{{[A-Za-z_][A-Za-z0-9_]*}}",
                            node.params[field.name],
                        )
                    ),
                    node_path,
                )
            )

    if issues:
        if event_paths:
            issues = [
                replace(issue, block_path=event_paths.get(issue.block_id))
                if issue.block_id in event_paths else issue
                for issue in issues
            ]
        raise ExecutionPreflightError(issues)
    plan = object.__new__(ExecutionPlan)
    object.__setattr__(plan, "_bot", bot.model_copy(deep=True))
    object.__setattr__(plan, "actions", tuple(actions))
    actions_by_source_id = {node.id: action for (node, _path), action in zip(ordered_nodes, actions, strict=True)}
    def planned(ids: list[str]) -> tuple[PlannedNode, ...]:
        return tuple(
            PlannedNode(
                actions_by_source_id[node_id],
                MappingProxyType({slot: planned(children) for slot, children in node_by_id[node_id].slots.items()}),
            )
            for node_id in ids
        )
    object.__setattr__(plan, "roots", planned(bot.flow.root))
    object.__setattr__(plan, "bot_directory", base_directory)
    for action in plan.actions:
        if action.source_node_id in workflow_node_ids:
            object.__setattr__(action, "_action_id", "workflow.run")
            object.__setattr__(action, "_handler_key", "workflow.run")
            object.__setattr__(action, "_title", "Ejecutar flujo")
    return plan


def _normalized_params(
    node: BotNode,
    action: ActionDefinition,
    variables: Mapping[str, JsonValue | RuntimeUnknown],
    ambiguous_variables: set[str] | frozenset[str] = frozenset(),
) -> tuple[
    dict[str, JsonValue | PureWindowsPath],
    dict[str, JsonValue | PureWindowsPath | RuntimeUnknown],
    tuple[DeferredFieldValidation, ...],
    list[ValidationIssue],
]:
    normalized: dict[str, JsonValue | PureWindowsPath] = {}
    static: dict[str, JsonValue | PureWindowsPath | RuntimeUnknown] = {}
    issues: list[ValidationIssue] = []
    deferred: list[DeferredFieldValidation] = []
    for field in action.fields:
        supplied = field.name in node.params or field.name in action.defaults
        configured_value = node.params.get(field.name)
        if (
            field.name not in node.params
            or configured_value is None and field.type != "json"
        ):
            configured_value = action.defaults.get(field.name)
        if not supplied or (field.required and configured_value == ""):
            if field.required:
                issues.append(_issue(ValidationIssueCode.PARAMETER_REQUIRED, node, field.name))
            continue
        value = configured_value
        if is_pending_parameter(value):
            issues.append(_issue(ValidationIssueCode.PARAMETER_REQUIRED, node, field.name))
            continue
        try:
            referenced = _template_names(configured_value) if field.type != "variable" else set()
        except VariableResolutionError as error:
            issues.append(_issue(_variable_issue_code(error.code), node, field.name))
            continue
        if referenced & ambiguous_variables:
            issues.append(_issue(ValidationIssueCode.VARIABLE_AMBIGUOUS, node, field.name))
            continue
        if field.type == "variable" and isinstance(value, str) and value in ambiguous_variables:
            output_fields = {output.field for output in action.outputs}
            if action.output is not None:
                output_fields.add(action.output.field)
            if field.name not in output_fields or node.type in {"variable.create", "variable.update", "variable.delete"}:
                issues.append(_issue(ValidationIssueCode.VARIABLE_AMBIGUOUS, node, field.name))
                continue
        try:
            templated = field.type != "variable" and _contains_template(configured_value)
        except VariableResolutionError as error:
            issues.append(_issue(_variable_issue_code(error.code), node, field.name))
            continue
        if field.type == "condition" or templated:
            try:
                value = resolve_value(value, variables)
            except VariableResolutionError as error:
                issues.append(_issue(_variable_issue_code(error.code), node, field.name))
                continue
        if field.type == "condition" and _has_runtime_unknown(value):
            value = RUNTIME_UNKNOWN
        json_value_field = field.type in {"json", "condition"} or field.name == "value" and node.type in {
            "variable.create", "excel.writeCell"
        }
        if (
            node.type == "excel.writeCell"
            and field.name == "value"
            and value is not RUNTIME_UNKNOWN
            and not _is_excel_scalar(value)
        ):
            issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, field.name))
            continue
        if not json_value_field and value is not RUNTIME_UNKNOWN and not _field_accepts(field, value):
            issues.append(_issue(ValidationIssueCode.PARAMETER_INVALID, node, field.name))
            continue
        static[field.name] = value
        normalized[field.name] = configured_value if value is RUNTIME_UNKNOWN or field.type == "condition" or templated else value
        if value is RUNTIME_UNKNOWN:
            deferred.append(DeferredFieldValidation(field))
    return normalized, static, tuple(deferred), issues


def _resolve_validated_action(
    action: ValidatedAction,
    variables: Mapping[str, JsonValue],
    *,
    bot_directory: str | Path | PureWindowsPath,
    virtual_desktop: VirtualDesktopProvider,
    validation_state: RuntimeValidationState,
    local_paths: LocalPathInspector | None = None,
) -> ResolvedAction:
    """Resolve and validate exact action parameters immediately before side effects."""
    base_directory = _validate_bot_directory(
        getattr(action, "_source_directory", bot_directory)
    )
    resolved: dict[str, JsonValue | PureWindowsPath] = {}
    issues: list[ValidationIssue] = []
    deferred_names = {item.field.name for item in action.deferred_validations}
    fields = {field.name: field for field in action.fields}

    if not set(action.params) <= set(fields):
        issues.append(ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id))

    for name, configured in action.params.items():
        field = fields.get(name)
        if field is None:
            issues.append(ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id, name))
            continue
        try:
            value = (
                configured
                if field.type == "variable" or isinstance(configured, PureWindowsPath)
                else resolve_value(configured, variables)
            )
        except VariableResolutionError:
            raise
        if value is RUNTIME_UNKNOWN or _has_residual_token(value):
            issues.append(ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id, name))
            continue
        resolved[name] = value

    if set(resolved) != set(action.params):
        issues.append(ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id))

    for field in action.fields:
        if field.name not in resolved:
            if field.required:
                issues.append(
                    ValidationIssue(ValidationIssueCode.PARAMETER_REQUIRED, action.block_id, field.name)
                )
            continue
        value = resolved[field.name]
        json_value_field = field.type in {"json", "condition"} or field.name == "value" and action.action_id in {
            "variable.create", "excel.writeCell"
        }
        if (value is None and not json_value_field) or (field.required and value == ""):
            issues.append(
                ValidationIssue(
                    ValidationIssueCode.PARAMETER_REQUIRED
                    if field.required
                    else ValidationIssueCode.PARAMETER_INVALID,
                    action.block_id,
                    field.name,
                )
            )
            continue
        if (
            action.action_id == "excel.writeCell"
            and field.name == "value"
            and not _is_excel_scalar(value)
        ):
            issues.append(
                ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id, field.name)
            )
            continue
        if not json_value_field and not _field_accepts(field, value):
            issues.append(
                ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id, field.name)
            )

    if deferred_names and not deferred_names <= resolved.keys():
        issues.append(ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id))

    if action.action_id in {"mouse.move", "mouse.click", "mouse.rightClick", "mouse.doubleClick"}:
        x, y = resolved.get("x"), resolved.get("y")
        if (x is None) != (y is None):
            issues.append(ValidationIssue(ValidationIssueCode.COORDINATE_PAIR_REQUIRED, action.block_id))
        elif isinstance(x, int) and not isinstance(x, bool) and isinstance(y, int) and not isinstance(y, bool):
            base_resolution = validation_state.get_base_resolution()
            if base_resolution is not None:
                bounds = VirtualDesktopBounds(0, 0, *base_resolution)
            else:
                try:
                    bounds = virtual_desktop.get_bounds()
                except Exception:
                    raise SafeExecutionError(ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE) from None
            if not bounds.contains(x, y):
                issues.append(ValidationIssue(ValidationIssueCode.COORDINATE_OUT_OF_BOUNDS, action.block_id))

    if action.action_id == "keyboard.press" and isinstance(resolved.get("key"), str):
        try:
            resolved["key"] = "+".join(parse_keyboard_key(resolved["key"]))
        except ValueError:
            issues.append(ValidationIssue(ValidationIssueCode.KEY_INVALID, action.block_id, "key"))

    if action.action_id.startswith("excel."):
        cell = resolved.get("cell")
        if isinstance(cell, str):
            try:
                resolved["cell"] = normalize_a1_cell(cell)
            except ValueError:
                issues.append(ValidationIssue(ValidationIssueCode.CELL_INVALID, action.block_id, "cell"))
        range_value = resolved.get("range")
        if isinstance(range_value, str):
            try:
                resolved["range"] = normalize_a1_range(range_value)
            except ValueError:
                issues.append(ValidationIssue(ValidationIssueCode.CELL_INVALID, action.block_id, "range"))
        if (
            action.action_id == "excel.writeRange"
            and isinstance(resolved.get("range"), str)
            and not _excel_matrix_matches_range(resolved.get("value"), str(resolved["range"]))
        ):
            issues.append(ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id, "value"))
        path = resolved.get("path")
        if path not in (None, ""):
            try:
                if isinstance(path, PureWindowsPath):
                    raw_path = str(path)
                elif isinstance(path, str):
                    raw_path = path
                else:
                    raise ValueError("path is not text")
                normalized_path = resolve_excel_path(raw_path, base_directory)
                _validate_inspected_path(
                    normalized_path,
                    source=action.action_id == "excel.open",
                    inspector=local_paths or WindowsLocalPathInspector(),
                )
                resolved["path"] = normalized_path
            except ValueError:
                issues.append(ValidationIssue(ValidationIssueCode.PATH_INVALID, action.block_id, "path"))
            except Exception:
                raise SafeExecutionError(ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE) from None

    if action.action_id.startswith(("file.", "folder.")):
        for field_name in ("path", "source", "destination"):
            path_value = resolved.get(field_name)
            if path_value is not None and (
                not isinstance(path_value, str) or not PureWindowsPath(path_value).is_absolute()
            ):
                issues.append(ValidationIssue(ValidationIssueCode.PATH_INVALID, action.block_id, field_name))
        if not issues:
            try:
                for field_name in _invalid_file_action_paths(
                    action.action_id, resolved, local_paths or WindowsLocalPathInspector()
                ):
                    issues.append(ValidationIssue(ValidationIssueCode.PATH_INVALID, action.block_id, field_name))
            except Exception:
                raise SafeExecutionError(ExecutionErrorCode.EXECUTION_ENVIRONMENT_UNAVAILABLE) from None

    if action.action_id == "http.request":
        for field_name in ("headers", "query"):
            if not isinstance(resolved.get(field_name, {}), dict):
                issues.append(ValidationIssue(ValidationIssueCode.PARAMETER_INVALID, action.block_id, field_name))
    if action.action_id == "workflow.run":
        path_value = resolved.get("path")
        if not isinstance(path_value, str) or not PureWindowsPath(path_value).is_absolute():
            issues.append(ValidationIssue(ValidationIssueCode.PATH_INVALID, action.block_id, "path"))

    reservation: RuntimeOpenReservation | None = None
    close_claim: RuntimeCloseClaim | None = None
    workbook_reservation: RuntimeOpenReservation | None = None
    save_as_claim: RuntimeSaveAsClaim | None = None
    if not issues and action.action_id in {"excel.open", "excel.create"}:
        path = resolved.get("path")
        name = resolved.get("outputVariable")
        if action.action_id == "excel.create" and isinstance(name, str):
            path = PureWindowsPath("C:/__autoclick_new__") / f"{name}.xlsx"
        if isinstance(path, PureWindowsPath) and isinstance(name, str):
            try:
                reservation = validation_state.reserve_open(name, path)
            except RuntimeReservationConflict as conflict:
                if conflict.name:
                    issues.append(
                        ValidationIssue(
                            ValidationIssueCode.WORKBOOK_DUPLICATE,
                            action.block_id,
                            "outputVariable",
                        )
                    )
                if conflict.path:
                    issues.append(
                        ValidationIssue(
                            ValidationIssueCode.WORKBOOK_PATH_DUPLICATE,
                            action.block_id,
                            "path",
                        )
                    )

    if not issues and action.action_id == "excel.close":
        name = resolved.get("workbookVariable")
        if isinstance(name, str):
            try:
                close_claim = validation_state.claim_close(name)
            except RuntimeCloseConflict:
                issues.append(
                    ValidationIssue(
                        ValidationIssueCode.WORKBOOK_CLOSED,
                        action.block_id,
                        "workbookVariable",
                    )
                )
            if close_claim is None and not issues:
                issues.append(
                    ValidationIssue(
                        ValidationIssueCode.WORKBOOK_MISSING,
                        action.block_id,
                        "workbookVariable",
                    )
                )

    if (
        not issues
        and action.action_id.startswith("excel.")
        and action.action_id not in {"excel.open", "excel.create", "excel.close"}
    ):
        name = resolved.get("workbookVariable")
        if isinstance(name, str):
            workbook_reservation = validation_state.get_open(name)
            if workbook_reservation is None:
                issues.append(
                    ValidationIssue(
                        ValidationIssueCode.WORKBOOK_MISSING,
                        action.block_id,
                        "workbookVariable",
                    )
                )
            elif action.action_id == "excel.save":
                destination = resolved.get("path")
                if isinstance(destination, PureWindowsPath):
                    try:
                        save_as_claim = validation_state.claim_save_as(
                            workbook_reservation, destination
                        )
                    except RuntimeSaveAsConflict as conflict:
                        issues.append(
                            ValidationIssue(
                                ValidationIssueCode.WORKBOOK_PATH_DUPLICATE
                                if conflict.path
                                else ValidationIssueCode.WORKBOOK_CLOSED,
                                action.block_id,
                                "path" if conflict.path else "workbookVariable",
                            )
                        )
    if issues:
        raise ResolvedActionValidationError(dict.fromkeys(issues))

    def create_resolved_action() -> ResolvedAction:
        instance = object.__new__(ResolvedAction)
        object.__setattr__(instance, "block_id", action.block_id)
        object.__setattr__(instance, "action_id", action.action_id)
        object.__setattr__(instance, "handler_key", action.handler_key)
        object.__setattr__(instance, "title", action.title)
        object.__setattr__(instance, "params", MappingProxyType(dict(resolved)))
        object.__setattr__(instance, "_validation_state", validation_state)
        object.__setattr__(instance, "_open_reservation", reservation)
        object.__setattr__(instance, "_close_claim", close_claim)
        object.__setattr__(instance, "_workbook_reservation", workbook_reservation)
        object.__setattr__(instance, "_save_as_claim", save_as_claim)
        object.__setattr__(instance, "_exact_token_fields", action._exact_token_fields)
        return instance

    try:
        return create_resolved_action()
    except BaseException:
        if reservation is not None:
            reservation.rollback()
        if close_claim is not None:
            close_claim.rollback()
        if save_as_claim is not None:
            save_as_claim.rollback()
        raise


def _has_residual_token(value: object) -> bool:
    if isinstance(value, str):
        try:
            return bool(token_names(value))
        except VariableResolutionError:
            return True
    if isinstance(value, list):
        return any(_has_residual_token(item) for item in value)
    if isinstance(value, dict):
        return any(
            _has_residual_token(item)
            for pair in value.items()
            for item in pair
        )
    return False


def _has_runtime_unknown(value: object) -> bool:
    if value is RUNTIME_UNKNOWN:
        return True
    if isinstance(value, list):
        return any(_has_runtime_unknown(item) for item in value)
    if isinstance(value, dict):
        return any(_has_runtime_unknown(item) for item in value.values())
    return False


def _contains_template(value: object) -> bool:
    if isinstance(value, str):
        return bool(token_names(value))
    if isinstance(value, list):
        return any(_contains_template(item) for item in value)
    if isinstance(value, dict):
        return any(_contains_template(item) for item in value.values())
    return False


def _template_names(value: object) -> set[str]:
    if isinstance(value, str):
        return set(token_names(value))
    if isinstance(value, list):
        return set().union(*(_template_names(item) for item in value)) if value else set()
    if isinstance(value, dict):
        return set().union(*(_template_names(item) for item in value.values())) if value else set()
    return set()


def _field_accepts(field: ActionField, value: object) -> bool:
    if field.type == "integer":
        valid_type = (
            isinstance(value, int)
            and not isinstance(value, bool)
            and abs(value) <= MAX_SAFE_INTEGER
        )
    elif field.type == "number":
        valid_type = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif field.type == "boolean":
        valid_type = isinstance(value, bool)
    elif field.type == "json":
        try:
            validate_finite_json(value)
            valid_type = value is None or isinstance(value, (str, int, float, bool, list, dict))
        except (TypeError, ValueError):
            valid_type = False
    elif field.type == "condition":
        try:
            Condition.model_validate(value)
            valid_type = True
        except (TypeError, ValueError):
            valid_type = False
    elif field.type == "file" and isinstance(value, PureWindowsPath):
        valid_type = True
    else:
        valid_type = isinstance(value, str)
    if not valid_type:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if field.min is not None and value < field.min:
            return False
        if field.max is not None and value > field.max:
            return False
    if isinstance(value, str):
        if field.min_length is not None and len(value) < field.min_length:
            return False
        if field.max_length is not None and len(value) > field.max_length:
            return False
        if field.pattern is not None and re.fullmatch(field.pattern, value) is None:
            return False
        if field.options is not None and value not in field.options:
            return False
    return True


def _is_excel_scalar(value: object) -> bool:
    if isinstance(value, float):
        return math.isfinite(value)
    return value is None or isinstance(value, (str, bool, int))


def _validate_dataflow(
    node: BotNode,
    action: ActionDefinition,
    params: dict[str, JsonValue | PureWindowsPath | RuntimeUnknown],
    values: dict[str, JsonValue | RuntimeUnknown],
    live: set[str],
    closed: set[str],
    opened_paths: set[str],
    issues: list[ValidationIssue],
) -> None:
    if node.type == "variable.create":
        name = _string_param(params, "name")
        if name in values:
            issues.append(_issue(ValidationIssueCode.VARIABLE_DUPLICATE, node, "name"))
        else:
            value = params.get("value", "")
            if not isinstance(value, PureWindowsPath):
                values[name] = value
        return

    if node.type in {"variable.update", "variable.delete"}:
        name = _string_param(params, "name")
        if name not in values:
            issues.append(_issue(ValidationIssueCode.VARIABLE_MISSING, node, "name"))
        elif node.type == "variable.update":
            value = params.get("value")
            if not isinstance(value, PureWindowsPath): values[name] = value
        else:
            del values[name]
        return

    if node.type in {"excel.open", "excel.create"}:
        name = _string_param(params, "outputVariable")
        valid_output = True
        if name in live:
            issues.append(_issue(ValidationIssueCode.WORKBOOK_DUPLICATE, node, "outputVariable"))
            valid_output = False
        path = params.get("path")
        valid_path = True
        if isinstance(path, PureWindowsPath):
            path_key = normalize_windows_path_key(path)
            if path_key in opened_paths:
                issues.append(_issue(ValidationIssueCode.WORKBOOK_PATH_DUPLICATE, node, "path"))
                valid_path = False
        if valid_output and valid_path:
            live.add(name)
            closed.discard(name)
            if isinstance(path, PureWindowsPath):
                opened_paths.add(path_key)
        return

    workbook_name = params.get("workbookVariable")
    workbook_is_valid = True
    if isinstance(workbook_name, str) and node.type.startswith("excel."):
        if workbook_name in closed:
            issues.append(_issue(ValidationIssueCode.WORKBOOK_CLOSED, node, "workbookVariable"))
            workbook_is_valid = False
        elif workbook_name not in live:
            issues.append(_issue(ValidationIssueCode.WORKBOOK_MISSING, node, "workbookVariable"))
            workbook_is_valid = False

    if node.type == "excel.close" and isinstance(workbook_name, str) and workbook_name in live:
        live.remove(workbook_name)
        closed.add(workbook_name)
        return
    if node.type.startswith("excel.") and not workbook_is_valid:
        return
    for output_definition in action.outputs or (() if action.output is None else (action.output,)):
        if output_definition.type == "workbook":
            continue
        output = _string_param(params, output_definition.field)
        if output in values:
            issues.append(_issue(ValidationIssueCode.VARIABLE_DUPLICATE, node, output_definition.field))
        else:
            values[output] = RUNTIME_UNKNOWN


def parse_keyboard_key(value: str) -> tuple[str, ...]:
    if not value or "," in value or value != value.strip():
        raise ValueError("invalid key")
    parts = tuple(part.casefold() for part in value.split("+"))
    if any(not part for part in parts) or any(part not in KEY_ALLOWLIST for part in parts):
        raise ValueError("invalid key")
    if len(parts) > 1:
        modifiers, key = parts[:-1], parts[-1]
        if key in MODIFIER_KEYS or any(part not in MODIFIER_KEYS for part in modifiers):
            raise ValueError("invalid chord")
        if len(modifiers) != len(set(modifiers)):
            raise ValueError("duplicate modifier")
    return parts


def normalize_a1_cell(value: str) -> str:
    match = A1_CELL.fullmatch(value)
    if match is None:
        raise ValueError("invalid A1 cell")
    column, row_text = match.groups()
    column_number = 0
    for character in column.upper():
        column_number = column_number * 26 + ord(character) - ord("A") + 1
    if column_number > 16_384 or int(row_text) > 1_048_576:
        raise ValueError("A1 cell is outside Excel bounds")
    return f"{column.upper()}{int(row_text)}"


def normalize_a1_range(value: str) -> str:
    parts = value.split(":")
    if len(parts) not in {1, 2}:
        raise ValueError("invalid A1 range")
    normalized = [normalize_a1_cell(part) for part in parts]
    return ":".join(normalized)


def _excel_matrix_matches_range(value: object, range_value: str) -> bool:
    if not isinstance(value, list) or not value or any(not isinstance(row, list) or not row for row in value):
        return False
    width = len(value[0])
    if any(len(row) != width for row in value):
        return False
    if any(not _is_excel_scalar(cell) for row in value for cell in row):
        return False
    start, *end = range_value.split(":")
    end_cell = end[0] if end else start
    start_column, start_row = _a1_parts(start)
    end_column, end_row = _a1_parts(end_cell)
    expected_rows = abs(end_row - start_row) + 1
    expected_columns = abs(end_column - start_column) + 1
    return len(value) == expected_rows and width == expected_columns


def _a1_parts(value: str) -> tuple[int, int]:
    match = A1_CELL.fullmatch(value)
    if match is None:
        raise ValueError("invalid A1 cell")
    letters, row = match.groups()
    column = 0
    for character in letters.upper():
        column = column * 26 + ord(character) - 64
    return column, int(row)


def resolve_excel_path(value: str, bot_directory: PureWindowsPath) -> PureWindowsPath:
    if not value or any(ord(character) < 32 for character in value):
        raise ValueError("invalid path")
    if any(character in value for character in "*?\"<>|"):
        raise ValueError("invalid path")
    if "://" in value or value.startswith(("\\\\", "//", "\\?\\", "\\.\\", "\\")):
        raise ValueError("non-local path")
    candidate = PureWindowsPath(value)
    if candidate.drive and not candidate.root:
        raise ValueError("drive-relative paths are unsupported")
    if not candidate.is_absolute():
        candidate = bot_directory / candidate
    _validate_windows_segments(candidate)
    normalized = PureWindowsPath(ntpath.normpath(str(candidate)))
    if not normalized.drive or not normalized.root or normalized.drive.startswith("\\"):
        raise ValueError("path must be on a local drive")
    if ":" in str(normalized)[len(normalized.drive):]:
        raise ValueError("alternate data streams are unsupported")
    if normalized.suffix.casefold() not in EXCEL_EXTENSIONS:
        raise ValueError("unsupported workbook extension")
    return normalized


def _validate_windows_segments(path: PureWindowsPath) -> None:
    for segment in path.parts[1:]:
        if not segment or segment in {".", ".."} or segment.endswith((".", " ")):
            raise ValueError("ambiguous Windows path segment")
        if ":" in segment:
            raise ValueError("alternate data streams are unsupported")
        device_base = segment.rstrip(". ").split(".", 1)[0].rstrip(" ").casefold()
        if device_base in WINDOWS_DEVICE_NAMES:
            raise ValueError("Windows device paths are unsupported")


def _validate_inspected_path(
    path: PureWindowsPath, *, source: bool, inspector: LocalPathInspector
) -> None:
    if not inspector.is_local_drive(path):
        raise ValueError("network drives are unsupported")
    current = PureWindowsPath(path.anchor)
    for part in path.parts[1:-1]:
        current /= part
        if inspector.is_reparse_point(current):
            raise ValueError("reparse traversal is unsupported")
    if inspector.is_reparse_point(path):
        raise ValueError("reparse paths are unsupported")
    if source:
        if not inspector.is_file(path):
            raise ValueError("source workbook does not exist")
    elif inspector.exists(path) or not inspector.is_directory(path.parent):
        raise ValueError("destination exists or parent is missing")


def _invalid_file_action_paths(
    action_id: str,
    params: Mapping[str, JsonValue | PureWindowsPath | RuntimeUnknown],
    inspector: LocalPathInspector,
) -> tuple[str, ...]:
    invalid: list[str] = []

    def path(name: str) -> PureWindowsPath | None:
        value = params.get(name)
        return PureWindowsPath(value) if isinstance(value, str) else None

    source_name = "source" if "source" in params else "path"
    source = path(source_name)
    file_sources = {"file.read", "file.delete", "file.copy", "file.move", "file.rename"}
    folder_sources = {"folder.listFiles", "folder.delete", "folder.move", "folder.rename", "folder.open"}
    if action_id in file_sources and source is not None and not inspector.is_file(source):
        invalid.append(source_name)
    if action_id in folder_sources and source is not None and not inspector.is_directory(source):
        invalid.append(source_name)

    destination = path("destination")
    if source is not None and destination is not None:
        if normalize_windows_path_key(source) == normalize_windows_path_key(destination):
            invalid.extend((source_name, "destination"))
        if not inspector.is_directory(destination.parent):
            invalid.append("destination")
        if inspector.exists(destination):
            expected_directory = action_id.startswith("folder.")
            correct_type = inspector.is_directory(destination) if expected_directory else inspector.is_file(destination)
            if not correct_type or not bool(params.get("overwrite", False)):
                invalid.append("destination")

    target = path("path")
    if action_id == "file.write" and target is not None:
        if not inspector.is_directory(target.parent):
            invalid.append("path")
        elif inspector.exists(target) and (
            not inspector.is_file(target) or not bool(params.get("overwrite", False))
        ):
            invalid.append("path")
    if action_id == "folder.create" and target is not None and inspector.exists(target) and not inspector.is_directory(target):
        invalid.append("path")
    return tuple(dict.fromkeys(invalid))


def _validate_variable_definition_graph(
    bot: Bot,
    issues: list[ValidationIssue],
    variable_states: Mapping[str, Mapping[str, JsonValue | RuntimeUnknown]],
) -> None:
    definitions: dict[str, JsonValue] = {}
    owners: dict[str, BotNode] = {}
    for node in bot.flow.nodes:
        if node.type != "variable.create":
            continue
        name = node.params.get("name")
        value = node.params.get("value", "")
        if not isinstance(name, str) or re.fullmatch(r"^[A-Za-z_][A-Za-z0-9_]*$", name) is None:
            continue
        if name in variable_states.get(node.id, {}):
            issues.append(_issue(ValidationIssueCode.VARIABLE_DUPLICATE, node, "name"))
            continue
        if name in definitions:
            continue
        definitions[name] = value
        owners[name] = node
    for name, node in owners.items():
        try:
            resolve_value(f"{{{{{name}}}}}", definitions)
        except VariableResolutionError as error:
            if error.code in {
                ExecutionErrorCode.VARIABLE_CYCLE,
                ExecutionErrorCode.VARIABLE_DEPTH_EXCEEDED,
                ExecutionErrorCode.VARIABLE_EXPANDED_SIZE_EXCEEDED,
                ExecutionErrorCode.VARIABLE_TOKEN_COUNT_EXCEEDED,
            }:
                issue = _issue(_variable_issue_code(error.code), node, "value")
                if issue not in issues:
                    issues.append(issue)


def _resource_states(
    bot: Bot,
    base_directory: PureWindowsPath,
    initial_workbooks: frozenset[str] = frozenset(),
    initial_resolution: tuple[int, int] | None = None,
    *,
    source_directories: Mapping[str, PureWindowsPath] | None = None,
) -> dict[
    str,
    tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None],
]:
    by_id = {node.id: node for node in bot.flow.nodes}
    before: dict[
        str,
        tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None],
    ] = {}

    def path_key(node: BotNode) -> str | None:
        raw = node.params.get("path")
        if not isinstance(raw, str) or _template_names(raw):
            return None
        try:
            directory = (source_directories or {}).get(node.id, base_directory)
            return normalize_windows_path_key(resolve_excel_path(raw, directory))
        except ValueError:
            return None

    def snapshot(
        live: set[str],
        maybe_live: set[str],
        closed: set[str],
        opened: set[str],
        resolution: tuple[int, int] | None,
    ) -> tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None]:
        return set(live), set(maybe_live), set(closed), set(opened), resolution

    def merge_states(
        states: list[tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None]],
    ) -> tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None]:
        definite_live = set.intersection(*(state[0] for state in states))
        possible_live = set().union(*(state[0] | state[1] for state in states))
        closed = set.intersection(*(state[2] for state in states))
        opened = set().union(*(state[3] for state in states))
        resolution = states[0][4] if all(state[4] == states[0][4] for state in states[1:]) else None
        return definite_live, possible_live - definite_live, closed, opened, resolution

    def can_fail(node: BotNode) -> bool:
        if node.type == "flow.if":
            return bool(_template_names(node.params.get("condition")))
        if node.type in {"flow.forRange", "flow.forEach", "flow.while"}:
            return bool(_template_names(node.params))
        return node.type not in {
            "flow.group",
            "flow.tryCatch",
            "flow.comment",
            "variable.create",
            "variable.update",
            "variable.delete",
            "system.setBaseResolution",
        }

    def sequence(
        ids: list[str],
        live: set[str],
        maybe_live: set[str],
        closed: set[str],
        opened: set[str],
        resolution: tuple[int, int] | None,
        failures: list[tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None]] | None = None,
    ) -> tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None] | None:
        incoming = snapshot(live, maybe_live, closed, opened, resolution)
        if not ids:
            return incoming

        def merge_optional(*states):
            present = [state for state in states if state is not None]
            return merge_states(present) if present else None

        def transfer(node: BotNode, current):
            live, maybe_live, closed, opened, resolution = snapshot(*current)
            if failures is not None and can_fail(node):
                failures.append(snapshot(live, maybe_live, closed, opened, resolution))
            if node.type == "flow.if":
                left = sequence(node.slots["then"], live, maybe_live, closed, opened, resolution, failures)
                right = sequence(node.slots["else"], live, maybe_live, closed, opened, resolution, failures)
                return merge_optional(left, right)
            if node.type == "flow.group":
                return sequence(
                    node.slots["body"], live, maybe_live, closed, opened, resolution, failures
                )
            if node.type == "flow.tryCatch":
                caught_failures: list[
                    tuple[set[str], set[str], set[str], set[str], tuple[int, int] | None]
                ] = []
                tried = sequence(
                    node.slots["try"], live, maybe_live, closed, opened, resolution, caught_failures
                )
                catch_input = merge_states(caught_failures) if caught_failures else snapshot(
                    live, maybe_live, closed, opened, resolution
                )
                caught = sequence(node.slots["catch"], *catch_input, failures)
                return merge_optional(tried, caught)
            if node.type in {"flow.forRange", "flow.forEach", "flow.while"}:
                body = sequence(
                    node.slots["body"], live, maybe_live, closed, opened, resolution, failures
                )
                if _static_loop_iteration_count(node) == 1:
                    return body
                return merge_optional(snapshot(live, maybe_live, closed, opened, resolution), body)
            if node.type in {"excel.open", "excel.create"}:
                name = node.params.get("outputVariable")
                if isinstance(name, str):
                    live.add(name)
                    maybe_live.discard(name)
                    closed.discard(name)
                key = path_key(node)
                if key is not None:
                    opened.add(key)
            elif node.type == "excel.close":
                name = node.params.get("workbookVariable")
                if isinstance(name, str):
                    live.discard(name)
                    maybe_live.discard(name)
                    closed.add(name)
            elif node.type == "system.setBaseResolution":
                width, height = node.params.get("width"), node.params.get("height")
                resolution = (
                    (width, height)
                    if all(isinstance(value, int) and not isinstance(value, bool) for value in (width, height))
                    else None
                )
            return snapshot(live, maybe_live, closed, opened, resolution)

        positions = {node_id: index for index, node_id in enumerate(ids)}
        inputs = [None] * len(ids)
        inputs[0] = incoming
        queue = [0]
        exits = {}
        while queue:
            index = queue.pop(0)
            current = inputs[index]
            if current is None:
                continue
            node = by_id[ids[index]]
            recorded = merge_optional(before.get(node.id), current)
            assert recorded is not None
            before[node.id] = recorded
            output = transfer(node, current)
            if output is None:
                continue
            if node.type == "flow.goTo":
                target = node.params.get("targetNodeId")
                if not isinstance(target, str) or target not in positions:
                    continue
                successors = [positions[target]]
            elif index + 1 < len(ids):
                successors = [index + 1]
            else:
                exits[index] = output
                continue
            for successor in successors:
                merged = merge_optional(inputs[successor], output)
                if merged != inputs[successor]:
                    inputs[successor] = merged
                    if successor not in queue:
                        queue.append(successor)
        return merge_optional(*exits.values())

    sequence(bot.flow.root, set(initial_workbooks), set(), set(), set(), initial_resolution)
    for node in bot.flow.nodes:
        before.setdefault(node.id, (set(), set(), set(), set(), None))
    return before


def _static_loop_iteration_count(node: BotNode) -> int | None:
    if node.type == "flow.forRange":
        start, end, step = (
            node.params.get("start"), node.params.get("end"), node.params.get("step")
        )
        if all(
            isinstance(value, int) and not isinstance(value, bool)
            for value in (start, end, step)
        ) and step and (end - start) * step >= 0:
            if start == 0 and end == 0:
                return 0
            return abs(end - start) // abs(step) + 1
    if node.type == "flow.forEach" and isinstance(node.params.get("items"), list):
        return len(node.params["items"])
    return None


def _resource_owners(
    bot: Bot,
    base_directory: PureWindowsPath,
    *,
    source_directories: Mapping[str, PureWindowsPath] | None = None,
) -> tuple[dict[str, str], dict[str, str]]:
    names: dict[str, str] = {}
    paths: dict[str, str] = {}
    for node in bot.flow.nodes:
        if node.type not in {"excel.open", "excel.create"}:
            continue
        name = node.params.get("outputVariable")
        if isinstance(name, str):
            names.setdefault(name, node.id)
        raw_path = node.params.get("path")
        if isinstance(raw_path, str) and not _template_names(raw_path):
            try:
                directory = (source_directories or {}).get(node.id, base_directory)
                key = normalize_windows_path_key(resolve_excel_path(raw_path, directory))
            except ValueError:
                continue
            paths.setdefault(key, node.id)
    return names, paths


def _variable_states(
    bot: Bot,
    definitions: Mapping[str, ActionDefinition],
    initial_variables: Mapping[str, JsonValue] | None = None,
) -> tuple[
    dict[str, dict[str, JsonValue | RuntimeUnknown]],
    dict[str, set[str]],
    set[str],
]:
    by_id = {node.id: node for node in bot.flow.nodes}
    before: dict[str, dict[str, JsonValue | RuntimeUnknown]] = {}
    ambiguous_before: dict[str, set[str]] = {}
    reachable: set[str] = set()

    def merge(
        left: dict[str, JsonValue | RuntimeUnknown],
        left_ambiguous: set[str],
        right: dict[str, JsonValue | RuntimeUnknown],
        right_ambiguous: set[str],
    ) -> tuple[dict[str, JsonValue | RuntimeUnknown], set[str]]:
        definite = {
            name: left[name] if left[name] == right[name] else RUNTIME_UNKNOWN
            for name in left.keys() & right.keys()
        }
        possible = left.keys() | right.keys() | left_ambiguous | right_ambiguous
        return definite, set(possible - definite.keys())

    def apply_leaf(
        node: BotNode,
        state: dict[str, JsonValue | RuntimeUnknown],
        ambiguous: set[str],
    ) -> None:
        if node.type == "variable.create":
            name = node.params.get("name")
            if isinstance(name, str) and name not in state and name not in ambiguous:
                state[name] = node.params.get("value", "")
            return
        if node.type == "variable.update":
            name = node.params.get("name")
            if isinstance(name, str) and name in state:
                state[name] = RUNTIME_UNKNOWN
            return
        if node.type == "variable.delete":
            name = node.params.get("name")
            if isinstance(name, str):
                state.pop(name, None)
                ambiguous.discard(name)
            return
        definition = definitions.get(node.type)
        if definition is not None:
            for output in definition.outputs or (() if definition.output is None else (definition.output,)):
                if output.type == "workbook":
                    continue
                name = node.params.get(output.field)
                if isinstance(name, str) and name not in state and name not in ambiguous:
                    state[name] = RUNTIME_UNKNOWN
                    if node.type == "vision.detectElement":
                        for sub_field in ("x", "y", "centroX", "centroY", "ancho", "alto", "confianza", "textoDetectado", "encontrado"):
                            flat_var = f"{name}_{sub_field}"
                            state[flat_var] = RUNTIME_UNKNOWN
                            ambiguous.discard(flat_var)
                    elif node.type == "http.request":
                        for sub_field in ("status", "body"):
                            flat_var = f"{name}_{sub_field}"
                            state[flat_var] = RUNTIME_UNKNOWN
                            ambiguous.discard(flat_var)

    def defined_names(ids: list[str]) -> set[str]:
        names: set[str] = set()
        for node_id in ids:
            node = by_id[node_id]
            if node.type == "variable.create":
                name = node.params.get("name")
                if isinstance(name, str):
                    names.add(name)
            definition = definitions.get(node.type)
            if definition is not None:
                for output in definition.outputs:
                    name = node.params.get(output.field)
                    if output.type != "workbook" and isinstance(name, str):
                        names.add(name)
                        if node.type == "vision.detectElement":
                            for sub_field in ("x", "y", "centroX", "centroY", "ancho", "alto", "confianza", "textoDetectado", "encontrado"):
                                names.add(f"{name}_{sub_field}")
                        elif node.type == "http.request":
                            names.update(f"{name}_{field}" for field in ("status", "body"))
            for children in node.slots.values():
                names.update(defined_names(children))
        return names

    def catch_entry(
        ids: list[str],
        incoming: dict[str, JsonValue | RuntimeUnknown],
        incoming_ambiguous: set[str],
    ) -> tuple[dict[str, JsonValue | RuntimeUnknown], set[str]]:
        state, ambiguous = dict(incoming), set(incoming_ambiguous)
        for index, node_id in enumerate(ids):
            node = by_id[node_id]
            if node.type in {"variable.create", "variable.update", "variable.delete", "flow.comment"}:
                apply_leaf(node, state, ambiguous)
                continue
            ambiguous.update(defined_names(ids[index:]) - state.keys())
            break
        return state, ambiguous

    def sequence(
        ids: list[str],
        incoming: dict[str, JsonValue | RuntimeUnknown],
        incoming_ambiguous: set[str],
    ) -> tuple[dict[str, JsonValue | RuntimeUnknown], set[str]] | None:
        if not ids:
            return dict(incoming), set(incoming_ambiguous)

        def merge_optional(
            *states: tuple[dict[str, JsonValue | RuntimeUnknown], set[str]] | None,
        ) -> tuple[dict[str, JsonValue | RuntimeUnknown], set[str]] | None:
            present = [state for state in states if state is not None]
            if not present:
                return None
            result = present[0]
            for state in present[1:]:
                result = merge(*result, *state)
            return result

        def transfer(
            node: BotNode,
            state: dict[str, JsonValue | RuntimeUnknown],
            ambiguous: set[str],
        ) -> tuple[dict[str, JsonValue | RuntimeUnknown], set[str]] | None:
            state, ambiguous = dict(state), set(ambiguous)
            if node.type == "flow.if":
                return merge_optional(
                    sequence(node.slots["then"], state, ambiguous),
                    sequence(node.slots["else"], state, ambiguous),
                )
            if node.type == "flow.tryCatch":
                error_name = node.params.get("errorVariable")
                base = dict(state)
                base_ambiguous = set(ambiguous)
                if isinstance(error_name, str) and error_name:
                    base[error_name] = None
                    base_ambiguous.discard(error_name)
                tried = sequence(node.slots["try"], base, base_ambiguous)
                catch_state, catch_ambiguous = catch_entry(
                    node.slots["try"], base, base_ambiguous
                )
                caught = sequence(
                    node.slots["catch"], catch_state, catch_ambiguous
                )
                combined = merge_optional(tried, caught)
                if combined is None:
                    return None
                state, ambiguous = combined
                if isinstance(error_name, str) and error_name:
                    state[error_name] = RUNTIME_UNKNOWN
                    ambiguous.discard(error_name)
                return state, ambiguous
            if node.type == "flow.group":
                return sequence(node.slots["body"], state, ambiguous)
            if node.type in {"flow.forRange", "flow.forEach", "flow.while"}:
                loop_incoming_names = set(state)
                body_state = dict(state)
                body_ambiguous = set(ambiguous)
                loop_names: list[object] = []
                if node.type == "flow.forRange":
                    loop_names.append(node.params.get("currentVariable"))
                elif node.type == "flow.forEach":
                    loop_names.extend((node.params.get("itemVariable"), node.params.get("indexVariable")))
                for name in loop_names:
                    if isinstance(name, str) and name:
                        body_state[name] = RUNTIME_UNKNOWN
                        body_ambiguous.discard(name)
                body_result = sequence(
                    node.slots["body"], body_state, body_ambiguous
                )
                count = _static_loop_iteration_count(node)
                if body_result is None:
                    return (state, ambiguous) if count in {None, 0} else None
                body_result_values, body_result_ambiguous = body_result
                if count == 1:
                    return body_result_values, body_result_ambiguous
                guaranteed = count is not None and count > 0
                for name in tuple(state):
                    if body_result_values.get(name) != state[name] or name not in body_result_values:
                        state[name] = RUNTIME_UNKNOWN
                new_names = body_result_values.keys() - loop_incoming_names
                if guaranteed:
                    for name in new_names:
                        state[name] = RUNTIME_UNKNOWN
                        ambiguous.discard(name)
                else:
                    ambiguous.update(new_names)
                ambiguous.update(body_result_ambiguous - state.keys())
                if guaranteed:
                    for name in loop_names:
                        if isinstance(name, str) and name:
                            state[name] = RUNTIME_UNKNOWN
                            ambiguous.discard(name)
                else:
                    ambiguous.update(
                        name for name in loop_names if isinstance(name, str) and name
                    )
                return state, ambiguous
            apply_leaf(node, state, ambiguous)
            return state, ambiguous

        positions = {node_id: index for index, node_id in enumerate(ids)}
        inputs: list[tuple[dict[str, JsonValue | RuntimeUnknown], set[str]] | None] = [None] * len(ids)
        inputs[0] = (dict(incoming), set(incoming_ambiguous))
        queue = [0]
        exits: dict[int, tuple[dict[str, JsonValue | RuntimeUnknown], set[str]]] = {}
        while queue:
            index = queue.pop(0)
            current = inputs[index]
            if current is None:
                continue
            state, ambiguous = current
            node = by_id[ids[index]]
            reachable.add(node.id)
            previous = (
                (before[node.id], ambiguous_before[node.id])
                if node.id in before else None
            )
            recorded = merge_optional(previous, current)
            assert recorded is not None
            before[node.id], ambiguous_before[node.id] = recorded
            output = transfer(node, state, ambiguous)
            if output is None:
                continue
            if node.type == "flow.goTo":
                target = node.params.get("targetNodeId")
                if not isinstance(target, str) or target not in positions:
                    continue
                successors = [positions[target]]
            elif index + 1 < len(ids):
                successors = [index + 1]
            else:
                exits[index] = output
                continue
            for successor in successors:
                merged = merge_optional(inputs[successor], output)
                if merged != inputs[successor]:
                    inputs[successor] = merged
                    if successor not in queue:
                        queue.append(successor)
        return merge_optional(*exits.values())

    sequence(bot.flow.root, dict(initial_variables or {}), set())
    for node in bot.flow.nodes:
        before.setdefault(node.id, {})
        ambiguous_before.setdefault(node.id, set())
    return before, ambiguous_before, reachable


def _validate_loop_safety(
    bot: Bot,
    issues: list[ValidationIssue],
) -> None:
    by_id = {node.id: node for node in bot.flow.nodes}

    def validate_body(ids: list[str], count: int | None, incoming_names: set[str]) -> None:
        for node_id in ids:
            node = by_id[node_id]
            name = node.params.get("name")
            if node.type == "variable.create" and (count is None or count > 1):
                issues.append(_issue(ValidationIssueCode.VARIABLE_AMBIGUOUS, node, "name"))
            if node.type == "variable.delete" and isinstance(name, str) and name in incoming_names:
                issues.append(_issue(ValidationIssueCode.VARIABLE_AMBIGUOUS, node, "name"))
            if node.type in {"excel.open", "excel.create"} and (count is None or count > 1):
                issues.append(_issue(ValidationIssueCode.WORKBOOK_DUPLICATE, node, "outputVariable"))
            if node.type == "excel.close" and (count is None or count > 1):
                issues.append(_issue(ValidationIssueCode.WORKBOOK_CLOSED, node, "workbookVariable"))
            for children in node.slots.values():
                validate_body(children, count, incoming_names)

    def walk(ids: list[str], known_names: set[str]) -> None:
        for node_id in ids:
            node = by_id[node_id]
            if node.type in {"flow.forRange", "flow.forEach", "flow.while"}:
                validate_body(
                    node.slots["body"], _static_loop_iteration_count(node), set(known_names)
                )
            for children in node.slots.values():
                walk(children, set(known_names))
            if node.type == "variable.create" and isinstance(node.params.get("name"), str):
                known_names.add(node.params["name"])

    walk(bot.flow.root, set())


def _validate_goto_safety(
    bot: Bot,
    definitions: Mapping[str, ActionDefinition],
    issues: list[ValidationIssue],
) -> None:
    """Validate jump scope; CFG fixed points provide the dataflow proof."""
    by_id = {node.id: node for node in bot.flow.nodes}

    def validate_container(ids: list[str]) -> None:
        positions = {node_id: index for index, node_id in enumerate(ids)}
        for index, node_id in enumerate(ids):
            node = by_id[node_id]
            if node.type == "flow.goTo":
                target = node.params.get("targetNodeId")
                if not isinstance(target, str) or target not in positions:
                    issues.append(_issue(ValidationIssueCode.INVALID_SEQUENCE, node, "targetNodeId"))
            for children in node.slots.values():
                validate_container(children)

    validate_container(bot.flow.root)


def _variable_owners(
    bot: Bot, definitions: Mapping[str, ActionDefinition]
) -> dict[str, str]:
    owners: dict[str, str] = {}
    for node in bot.flow.nodes:
        names: list[object] = []
        if node.type == "variable.create":
            names.append(node.params.get("name"))
        definition = definitions.get(node.type)
        if definition is not None:
            names.extend(
                node.params.get(output.field)
                for output in definition.outputs
                if output.type != "workbook"
            )
            if node.type == "vision.detectElement":
                var_name = node.params.get("outputVariable")
                if isinstance(var_name, str):
                    for sub_field in ("x", "y", "centroX", "centroY", "ancho", "alto", "confianza", "textoDetectado", "encontrado"):
                        names.append(f"{var_name}_{sub_field}")
        for name in names:
            if isinstance(name, str):
                owners.setdefault(name, node.id)
    return owners


def _validate_bot_directory(value: str | Path | PureWindowsPath) -> PureWindowsPath:
    directory = PureWindowsPath(str(value))
    if not directory.is_absolute() or directory.drive.startswith("\\"):
        raise ExecutionPreflightError([ValidationIssue(ValidationIssueCode.PATH_INVALID)])
    return PureWindowsPath(ntpath.normpath(str(directory)))


def _string_param(
    params: Mapping[str, JsonValue | PureWindowsPath | RuntimeUnknown], name: str
) -> str:
    value = params[name]
    if not isinstance(value, str):
        raise ValueError("parameter is not a string")
    return value


def _issue(code: ValidationIssueCode, node: BotNode, field: str | None = None) -> ValidationIssue:
    return ValidationIssue(code=code, block_id=node.id, field_name=field)


def _variable_issue_code(code: ExecutionErrorCode) -> ValidationIssueCode:
    return {
        ExecutionErrorCode.VARIABLE_TOKEN_INVALID: ValidationIssueCode.VARIABLE_TOKEN_INVALID,
        ExecutionErrorCode.VARIABLE_MISSING: ValidationIssueCode.VARIABLE_MISSING,
        ExecutionErrorCode.VARIABLE_CYCLE: ValidationIssueCode.VARIABLE_CYCLE,
        ExecutionErrorCode.VARIABLE_DEPTH_EXCEEDED: ValidationIssueCode.VARIABLE_DEPTH_EXCEEDED,
        ExecutionErrorCode.VARIABLE_EXPANDED_SIZE_EXCEEDED: ValidationIssueCode.VARIABLE_EXPANDED_SIZE_EXCEEDED,
        ExecutionErrorCode.VARIABLE_TOKEN_COUNT_EXCEEDED: ValidationIssueCode.VARIABLE_TOKEN_COUNT_EXCEEDED,
    }[code]
