from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager, suppress
from dataclasses import dataclass
from typing import Any

from autoclick_mcp.catalog import ActionCatalog
from autoclick_mcp.preview import BotPreviewer
from autoclick_mcp.server import open_client_session
from autoclick_mcp.validator import BotValidator
from app.schemas import Capabilities

_catalog = ActionCatalog()
_validator = BotValidator(_catalog)
_previewer = BotPreviewer(_catalog)

_CAPABILITY_ACTION_KEYS = {
    "id",
    "category",
    "categoryName",
    "title",
    "description",
    "fields",
    "defaults",
    "output",
    "outputs",
    "slots",
    "platform",
}
_MODEL_TOOL_NAMES = {
    "search_actions",
    "get_action_schemas",
    "list_categories",
    "search_product_docs",
}
_INVALID_TOOL_ARGUMENTS = {
    "ok": False,
    "error": {
        "code": "INVALID_TOOL_ARGUMENTS",
        "message": "Los argumentos de la herramienta no son válidos.",
    },
}
_UNKNOWN_TOOL = {
    "ok": False,
    "error": {
        "code": "UNKNOWN_TOOL",
        "message": "La herramienta solicitada no está disponible.",
    },
}
_MCP_UNAVAILABLE = {
    "ok": False,
    "error": {
        "code": "MCP_UNAVAILABLE",
        "message": "El catálogo local de AutoClick no está disponible.",
    },
}


@dataclass
class _ToolCall:
    name: str
    arguments: dict[str, Any]
    result: asyncio.Future[dict[str, Any]]
    deadline: float


class McpRuntime:
    """Persistent, protocol-backed MCP session owned by the application lifespan."""

    def __init__(
        self,
        session_factory: Callable[[], AbstractAsyncContextManager[Any]] = open_client_session,
    ) -> None:
        self._session_factory = session_factory
        self._worker_task: asyncio.Task[None] | None = None
        self._commands: asyncio.Queue[_ToolCall | None] = asyncio.Queue()
        self._pending: set[asyncio.Future[dict[str, Any]]] = set()
        self._failed = False
        self._closing = False
        self._tool_names: frozenset[str] = frozenset()
        self.editor_tools: list[dict[str, Any]] = []
        self.home_tools: list[dict[str, Any]] = []

    async def __aenter__(self) -> McpRuntime:
        self._commands = asyncio.Queue()
        self._pending = set()
        self._failed = False
        self._closing = False
        loop = asyncio.get_running_loop()
        ready: asyncio.Future[None] = loop.create_future()
        self._worker_task = asyncio.create_task(self._run(ready))
        try:
            await ready
        except asyncio.CancelledError:
            await self._close_worker()
            raise
        except BaseException:
            await self._close_worker()
            raise RuntimeError("MCP runtime unavailable") from None
        return self

    async def _run(self, ready: asyncio.Future[None]) -> None:
        try:
            while not self._closing:
                restart = False
                async with self._session_factory() as session:
                    await self._discover(session)
                    if not ready.done():
                        ready.set_result(None)
                    while True:
                        command = await self._commands.get()
                        if command is None:
                            return
                        loop = asyncio.get_running_loop()
                        if command.result.done() or command.deadline <= loop.time():
                            if not command.result.done():
                                command.result.set_result(self._unavailable())
                            continue
                        call_task = asyncio.create_task(
                            session.call_tool(command.name, command.arguments)
                        )
                        try:
                            done, _ = await asyncio.wait(
                                (call_task, command.result),
                                timeout=max(0.0, command.deadline - loop.time()),
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                            if command.result in done:
                                call_task.cancel()
                                with suppress(asyncio.CancelledError):
                                    await call_task
                                restart = True
                                break
                            if call_task not in done:
                                call_task.cancel()
                                with suppress(asyncio.CancelledError):
                                    await call_task
                                if not command.result.done():
                                    command.result.set_result(self._unavailable())
                                restart = True
                                break
                            result = await call_task
                            if result.is_error or not isinstance(result.structured_content, dict):
                                if not command.result.done():
                                    command.result.set_result(
                                        {
                                            **_INVALID_TOOL_ARGUMENTS,
                                            "error": {
                                                **_INVALID_TOOL_ARGUMENTS["error"],
                                                "tool": command.name,
                                                "inputSchema": next(
                                                    tool["function"]["parameters"]
                                                    for tool in self.editor_tools
                                                    if tool["function"]["name"] == command.name
                                                ),
                                            },
                                        }
                                    )
                            elif not command.result.done():
                                command.result.set_result(result.structured_content)
                        except BaseException:
                            if not call_task.done():
                                call_task.cancel()
                            if not command.result.done():
                                command.result.set_result(self._unavailable())
                            raise
                if not restart:
                    return
        except BaseException as exc:
            self._failed = True
            if not ready.done():
                ready.set_exception(RuntimeError("MCP runtime unavailable"))
        finally:
            self._fail_pending()

    @staticmethod
    def _unavailable() -> dict[str, Any]:
        return {**_MCP_UNAVAILABLE, "error": _MCP_UNAVAILABLE["error"].copy()}

    def _fail_pending(self) -> None:
        for result in tuple(self._pending):
            if not result.done():
                result.set_result(self._unavailable())

    async def _discover(self, session) -> None:
        discovered = {tool.name: tool for tool in (await session.list_tools()).tools}
        missing = _MODEL_TOOL_NAMES - discovered.keys()
        if missing:
            raise RuntimeError(f"MCP consultation tools unavailable: {sorted(missing)}")

        tools: list[dict[str, Any]] = []
        for name in sorted(_MODEL_TOOL_NAMES):
            tool = discovered[name]
            annotations = tool.annotations
            if annotations is None or annotations.read_only_hint is not True:
                raise RuntimeError(f"MCP tool is not declared read-only: {name}")
            schema = tool.input_schema
            if schema.get("type") != "object" or schema.get("additionalProperties") is not False:
                raise RuntimeError(f"MCP tool does not publish a closed input schema: {name}")
            tools.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": tool.description or "",
                        "parameters": schema,
                    },
                }
            )
        self._tool_names = frozenset(discovered)
        self.editor_tools = tools
        self.home_tools = list(tools)

    async def _close_worker(self) -> None:
        task = self._worker_task
        self._worker_task = None
        self._closing = True
        self._fail_pending()
        try:
            if task is not None and not task.done():
                task.cancel()
            if task is not None:
                with suppress(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=2.0)
        finally:
            self._pending.clear()
            self._tool_names = frozenset()
            self.editor_tools = []
            self.home_tools = []

    async def __aexit__(self, exc_type, exc, traceback) -> None:
        await self._close_worker()

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, Any],
        timeout_seconds: float = 30.0,
    ) -> dict[str, Any]:
        task = self._worker_task
        if task is None or task.done() or self._failed or self._closing:
            return self._unavailable()
        if name not in self._tool_names or name not in _MODEL_TOOL_NAMES:
            return {**_UNKNOWN_TOOL, "error": _UNKNOWN_TOOL["error"].copy()}
        if timeout_seconds <= 0:
            return self._unavailable()
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        result = loop.create_future()
        self._pending.add(result)
        await self._commands.put(_ToolCall(name, arguments, result, deadline))
        try:
            try:
                async with asyncio.timeout_at(deadline):
                    return await asyncio.shield(result)
            except TimeoutError:
                if not result.done():
                    result.cancel()
                return self._unavailable()
            except asyncio.CancelledError:
                if not result.done():
                    result.cancel()
                raise
        finally:
            self._pending.discard(result)


async def execute_mcp_tool(
    name: str,
    arguments: dict[str, Any],
    runtime: McpRuntime | None = None,
    *,
    timeout_seconds: float = 30.0,
) -> dict[str, Any]:
    if runtime is not None:
        return await runtime.call_tool(name, arguments, timeout_seconds)
    async with McpRuntime() as temporary:
        return await temporary.call_tool(name, arguments, timeout_seconds)


def mcp_catalog_snapshot() -> dict[str, Any]:
    """Return trusted MCP metadata for validation and prompt construction only.

    This is not a model-facing response path. Model discovery and calls must use
    ``McpRuntime`` and the MCP ``tools/call`` protocol.
    """
    return {
        "catalogVersion": _catalog.catalog_version,
        "catalogHash": _catalog.catalog_hash,
        "actions": _catalog.get_all_actions(),
    }


def mcp_canonical_capabilities() -> Capabilities:
    """Build trusted request metadata; never render it as an automatic answer."""
    snapshot = mcp_catalog_snapshot()
    capabilities = Capabilities.model_validate(
        {
            "catalogVersion": snapshot["catalogVersion"],
            "catalogHash": snapshot["catalogHash"],
            "actions": [
                {
                    key: value
                    for key, value in action.items()
                    if key in _CAPABILITY_ACTION_KEYS
                }
                for action in snapshot["actions"]
            ],
        }
    )
    if (
        capabilities.catalog_version != _catalog.catalog_version
        or capabilities.catalog_hash != _catalog.catalog_hash
        or len(capabilities.actions) != len(snapshot["actions"])
    ):
        raise RuntimeError("canonical MCP catalog identity validation failed")
    return capabilities


# Synchronous adapters remain for deterministic validation/diff hot paths. Model-facing
# discovery and calls always use McpRuntime and the MCP protocol above.
def mcp_search_actions(
    query: str,
    category: str | None = None,
    platform: str | None = None,
    limit: int = 6,
) -> dict[str, Any]:
    return _catalog.search_actions(
        query=query, category=category, platform=platform, limit=limit
    ).model_dump(by_alias=True)


def mcp_get_action_schemas(action_ids: list[str]) -> dict[str, Any]:
    return _catalog.get_action_schemas(action_ids=action_ids).model_dump(by_alias=True)


def mcp_list_categories(include_actions: bool = False) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    for action in _catalog.get_all_actions():
        category_id = action.get("category", "general")
        category = categories.setdefault(
            category_id,
            {
                "id": category_id,
                "name": action.get("categoryName") or category_id.capitalize(),
                "actionCount": 0,
                "actions": [],
            },
        )
        category["actionCount"] += 1
        if include_actions:
            category["actions"].append(
                {
                    "id": action["id"],
                    "title": action.get("title", ""),
                    "description": action.get("description", ""),
                }
            )
    return {
        "ok": True,
        "categories": list(categories.values()),
        "totalActions": len(_catalog.get_all_actions()),
    }


def mcp_validate_bot(bot: dict[str, Any], mode: str = "proposal") -> dict[str, Any]:
    return _validator.validate_bot(bot=bot, mode=mode).model_dump(by_alias=True)


def mcp_validate_bot_patch(
    base_bot: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    return _validator.validate_bot_patch(
        base_bot=base_bot, operations=operations
    ).model_dump(by_alias=True)


def mcp_preview_bot_patch(
    base_bot: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    return _previewer.preview_bot_patch(
        base_bot=base_bot, operations=operations
    ).model_dump(by_alias=True)
