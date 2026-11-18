import json
import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
from typing import Mapping

from pydantic import JsonValue, ValidationError

from autoclick_desktop.bot_schema import Bot, LegacyBot, parse_bot_data
from autoclick_desktop.bot_service import MAX_BOT_FILE_SIZE
from autoclick_desktop.execution_errors import ExecutionErrorCode, SafeExecutionError


MAX_WORKFLOW_DEPTH = 20
MAX_WORKFLOW_UNIQUE_FILES = 128
MAX_WORKFLOW_INVOCATIONS = 1_024
MAX_WORKFLOW_EXPANDED_NODES = 20_000
MAX_WORKFLOW_CUMULATIVE_BYTES = 16 * 1024 * 1024
WORKFLOW_COMPILER_ERROR_CODES = frozenset({
    ExecutionErrorCode.EXECUTION_BOT_INVALID,
    ExecutionErrorCode.WORKFLOW_LOAD_FAILED,
    ExecutionErrorCode.WORKFLOW_CYCLE,
    ExecutionErrorCode.WORKFLOW_DEPTH_EXCEEDED,
    ExecutionErrorCode.WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED,
    ExecutionErrorCode.WORKFLOW_INVOCATION_LIMIT_EXCEEDED,
    ExecutionErrorCode.WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED,
    ExecutionErrorCode.WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED,
})


@dataclass(frozen=True, slots=True)
class CompiledWorkflowDraft:
    draft: dict[str, object]
    workflow_node_ids: frozenset[str]
    editor_node_ids: frozenset[str]
    event_paths: Mapping[str, tuple[str, ...]]
    source_directories: Mapping[str, PureWindowsPath]


@dataclass(frozen=True, slots=True)
class _CachedWorkflow:
    bot: Bot
    path: Path


def compile_workflow_graph(
    root_draft: object, *, root_directory: PureWindowsPath
) -> CompiledWorkflowDraft:
    """Load and expand every static workflow reference without mutating source files."""
    try:
        root = Bot.model_validate(root_draft)
    except (ValidationError, TypeError, ValueError):
        raise SafeExecutionError(ExecutionErrorCode.EXECUTION_BOT_INVALID) from None

    workflow_nodes: set[str] = set()
    event_paths: dict[str, tuple[str, ...]] = {}
    source_directories: dict[str, PureWindowsPath] = {}
    cache: dict[str, _CachedWorkflow] = {}
    invocation_count = 0
    expanded_node_count = 0
    cumulative_bytes = 0

    def load(path_text: object) -> tuple[Bot, Path, str]:
        nonlocal cumulative_bytes
        if not isinstance(path_text, str) or "{{" in path_text or "}}" in path_text:
            raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_LOAD_FAILED)
        windows_path = PureWindowsPath(path_text)
        if not windows_path.is_absolute():
            raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_LOAD_FAILED)
        try:
            path = Path(path_text).resolve(strict=True)
            identity = os.path.normcase(str(path))
            cached = cache.get(identity)
            if cached is not None:
                return cached.bot, cached.path, identity
            file_stat = path.stat()
            if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size > MAX_BOT_FILE_SIZE:
                raise ValueError("unsafe bot file")
            if len(cache) >= MAX_WORKFLOW_UNIQUE_FILES:
                raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_UNIQUE_FILE_LIMIT_EXCEEDED)
            if cumulative_bytes + file_stat.st_size > MAX_WORKFLOW_CUMULATIVE_BYTES:
                raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED)
            with path.open("rb") as source:
                raw = source.read(MAX_BOT_FILE_SIZE + 1)
            if len(raw) > MAX_BOT_FILE_SIZE:
                raise ValueError("bot file exceeds size limit")
            if cumulative_bytes + len(raw) > MAX_WORKFLOW_CUMULATIVE_BYTES:
                raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_CUMULATIVE_BYTE_LIMIT_EXCEEDED)
            data = json.loads(
                raw.decode("utf-8-sig"),
                parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            )
            parsed = parse_bot_data(data)
            if isinstance(parsed, LegacyBot):
                raise ValueError("non-linear schema-v1 workflow")
            parsed = parsed.model_copy(update={"ai": None})
            cumulative_bytes += len(raw)
            cache[identity] = _CachedWorkflow(parsed, path)
            return parsed, path, identity
        except SafeExecutionError:
            raise
        except Exception:
            raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_LOAD_FAILED) from None

    def expand(
        bot: Bot,
        *,
        namespace: str,
        stack: tuple[str, ...],
        workflow_path: tuple[str, ...],
        source_directory: PureWindowsPath,
    ) -> tuple[list[str], list[dict[str, object]]]:
        nonlocal invocation_count, expanded_node_count
        by_id = {node.id: node for node in bot.flow.nodes}
        expanded_nodes: list[dict[str, object]] = []

        def mapped(node_id: str) -> str:
            return f"{namespace}::{node_id}" if namespace else node_id

        def append_node(node: dict[str, object]) -> None:
            nonlocal expanded_node_count
            if expanded_node_count >= MAX_WORKFLOW_EXPANDED_NODES:
                raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_EXPANDED_NODE_LIMIT_EXCEEDED)
            expanded_node_count += 1
            expanded_nodes.append(node)

        def expand_container(ids: list[str], structural_path: tuple[str, ...]) -> list[str]:
            nonlocal invocation_count
            result: list[str] = []
            for index, node_id in enumerate(ids):
                node = by_id[node_id]
                expanded_id = mapped(node.id)
                node_path = (*structural_path, str(index))
                node_event_path = (*workflow_path, "structure", *node_path, "node", node.id)
                result.append(expanded_id)
                source_directories[expanded_id] = source_directory
                if namespace:
                    event_paths[expanded_id] = node_event_path
                params = node.model_dump(mode="json")["params"]
                if node.type == "flow.goTo" and isinstance(params.get("targetNodeId"), str):
                    params["targetNodeId"] = mapped(params["targetNodeId"])
                if node.type == "workflow.run":
                    if invocation_count >= MAX_WORKFLOW_INVOCATIONS:
                        raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_INVOCATION_LIMIT_EXCEEDED)
                    invocation_count += 1
                    child, child_path, identity = load(params.get("path"))
                    if identity in stack:
                        raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_CYCLE)
                    if len(stack) >= MAX_WORKFLOW_DEPTH:
                        raise SafeExecutionError(ExecutionErrorCode.WORKFLOW_DEPTH_EXCEEDED)
                    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:16]
                    child_namespace = f"{expanded_id}@{digest}"
                    child_workflow_path = (*node_event_path, "workflow", str(child_path))
                    event_paths[expanded_id] = child_workflow_path
                    child_root, child_nodes = expand(
                        child,
                        namespace=child_namespace,
                        stack=(*stack, identity),
                        workflow_path=child_workflow_path,
                        source_directory=PureWindowsPath(str(child_path.parent)),
                    )
                    workflow_nodes.add(expanded_id)
                    append_node({
                        "id": expanded_id,
                        "type": "flow.group",
                        "params": {},
                        "slots": {"body": child_root},
                    })
                    expanded_nodes.extend(child_nodes)
                    continue
                slots = {
                    slot: expand_container(children, (*node_path, "slot", slot))
                    for slot, children in node.slots.items()
                }
                expanded = {"id": expanded_id, "type": node.type, "params": params}
                if slots:
                    expanded["slots"] = slots
                append_node(expanded)
            return result

        root = expand_container(bot.flow.root, ("root",))
        return root, expanded_nodes

    root_ids, nodes = expand(
        root,
        namespace="",
        stack=(),
        workflow_path=(),
        source_directory=root_directory,
    )
    expanded_draft: dict[str, object] = {
        "schemaVersion": 2,
        "id": str(root.id),
        "name": root.name,
        "description": root.description,
        "flow": {"root": root_ids, "nodes": nodes},
    }
    if root.icon is not None:
        expanded_draft["icon"] = root.icon
    return CompiledWorkflowDraft(
        expanded_draft,
        frozenset(workflow_nodes),
        frozenset(node.id for node in root.flow.nodes),
        event_paths,
        source_directories,
    )
