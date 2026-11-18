import asyncio
import json
import re
import unicodedata
from importlib.resources import files
from contextlib import asynccontextmanager
from typing import Annotated, Any, AsyncIterator, Literal

import anyio
from mcp import ClientSession
from mcp.server.mcpserver import MCPServer
from mcp.shared.memory import create_client_server_memory_streams
from mcp.types import ToolAnnotations
from pydantic import Field, StrictBool

from autoclick_mcp.catalog import ActionCatalog
from autoclick_mcp.validator import BotValidator
from autoclick_mcp.preview import BotPreviewer

server = MCPServer(
    name="autoclick-mcp",
    instructions="Servidor MCP de herramientas y recursos para AutoClick"
)

catalog = ActionCatalog()
validator = BotValidator(catalog)
previewer = BotPreviewer(catalog)

_QUERY = Annotated[str, Field(strict=True, min_length=1, max_length=240)]
_CATEGORY = Annotated[
    str, Field(strict=True, min_length=1, max_length=80, pattern=r"^[A-Za-z][A-Za-z0-9_-]{0,79}$")
]
_ACTION_ID = Annotated[
    str, Field(strict=True, min_length=1, max_length=120, pattern=r"^[A-Za-z][A-Za-z0-9_.-]{0,119}$")
]
_ACTION_IDS = Annotated[
    list[_ACTION_ID], Field(min_length=1, max_length=10, json_schema_extra={"uniqueItems": True})
]
_LIMIT = Annotated[int, Field(strict=True, ge=1, le=10)]
_MODE = Literal["proposal", "execution"]
_READ_ONLY = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)

def _load_product_docs() -> dict[str, Any]:
    try:
        payload = json.loads(
            files("autoclick_mcp").joinpath("data/product_docs.json").read_text(
                encoding="utf-8"
            )
        )
        if not isinstance(payload.get("version"), int) or payload["version"] < 1:
            raise ValueError("invalid documentation version")
        if not isinstance(payload.get("documents"), list):
            raise ValueError("invalid documentation collection")
        return payload
    except (OSError, json.JSONDecodeError, ValueError, TypeError) as exc:
        raise RuntimeError("cannot load versioned AutoClick product documentation") from exc


_PRODUCT_DOCS = _load_product_docs()


def _search_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(
        character for character in normalized if not unicodedata.combining(character)
    )))


_STOPWORDS = {
    "a", "al", "como", "cual", "de", "del", "el", "en", "es", "esta",
    "funciona", "funcionar", "la", "las", "los", "para", "por", "que", "se",
    "un", "una", "y", "bloque", "bloques", "bot", "autoclick",
}
_ACTION_ALIASES = {
    "execution.wait": (
        "pausar el bot", "pausar", "hacer una pausa", "esperar", "wait", "delay", "sleep",
    ),
    "mouse.click": (
        "hacer clic", "hacer click", "clic izquierdo", "click izquierdo", "left click",
    ),
    "mouse.doubleClick": ("doble clic", "doble click", "double click"),
    "mouse.rightClick": ("clic derecho", "click derecho", "right click"),
    "browser.open": ("abrir navegador", "abrir pagina web", "open browser", "open url"),
    "keyboard.write": ("escribir con teclado", "tipear texto", "type text"),
    "keyboard.press": ("presionar tecla", "pulsar tecla", "press key"),
    "file.read": ("leer archivo", "read file"),
    "file.write": ("escribir archivo", "write file"),
    "excel.readCell": ("leer celda", "read cell"),
    "excel.writeCell": ("escribir celda", "write cell"),
    "http.request": ("solicitud http", "peticion http", "http request"),
}
_DOCUMENT_ALIASES = {
    "editor": ("como funciona el editor", "como funciona el flujo"),
    "execution": ("por que no ejecuta", "porque no ejecuta", "no puede ejecutar"),
    "persistence": ("como se guardan las propuestas", "restaurar una propuesta"),
    "common-failures": ("troubleshooting", "problemas frecuentes", "propuesta invalida"),
    "actions": ("como funcionan las acciones", "como funcionan los bloques"),
}


def _query_terms(query: str) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(term for term in _search_text(query).split() if term not in _STOPWORDS)
    )


def _list_categories(include_actions: bool = False) -> dict[str, Any]:
    categories: dict[str, dict[str, Any]] = {}
    actions = catalog.get_all_actions()
    for action in actions:
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
        "catalogVersion": catalog.catalog_version,
        "catalogHash": catalog.catalog_hash,
        "categories": list(categories.values()),
        "totalActions": len(actions),
    }


@server.tool(annotations=_READ_ONLY)
def search_actions(
    query: _QUERY,
    category: _CATEGORY | None = None,
    platform: Literal["windows", "linux", "darwin"] | None = None,
    limit: _LIMIT = 5,
) -> dict[str, Any]:
    """Busca bloques concretos por tarea, nombre o descripción (por ejemplo: copiar archivo).
    No enumera el catálogo completo: para todos los bloques usa list_categories(include_actions=true).
    limit debe estar entre 1 y 10. Cero coincidencias solo describe esta búsqueda.
    """
    result = catalog.search_actions(query=query, category=category, platform=platform, limit=limit)
    return result.model_dump(by_alias=True)


@server.tool(annotations=_READ_ONLY)
def get_action_schemas(action_ids: _ACTION_IDS) -> dict[str, Any]:
    """Obtiene esquemas exactos junto con la versión y el hash del catálogo canónico."""
    result = catalog.get_action_schemas(action_ids=action_ids)
    return result.model_dump(by_alias=True)


@server.tool(annotations=_READ_ONLY)
def list_categories(include_actions: StrictBool = False) -> dict[str, Any]:
    """Obtiene el inventario completo de bloques disponibles, sin búsqueda por palabras.
    Usa include_actions=true para incluir TODOS los IDs, nombres y descripciones por categoría.
    Incluye totalActions. Para parámetros de bloques específicos usa después get_action_schemas.
    """
    return _list_categories(include_actions=include_actions)


@server.tool(annotations=_READ_ONLY)
def search_product_docs(query: _QUERY, limit: _LIMIT = 5) -> dict[str, Any]:
    """Busca información del producto AutoClick en documentación local, versionada y de solo lectura."""
    normalized_query = _search_text(query)
    terms = _query_terms(query)
    if not terms:
        return {
            "version": _PRODUCT_DOCS["version"],
            "catalogVersion": catalog.catalog_version,
            "catalogHash": catalog.catalog_hash,
            "results": [],
        }
    ranked: list[tuple[int, str, dict[str, Any]]] = []
    for action in catalog.get_all_actions():
        action_id = str(action["id"])
        title = _search_text(str(action.get("title", "")))
        description = _search_text(str(action.get("description", "")))
        fields = " ".join(
            _search_text(f"{field.get('name', '')} {field.get('label', '')}")
            for field in action.get("fields", [])
        )
        identifier = _search_text(action_id.replace(".", " "))
        title_terms = set(title.split())
        identifier_terms = set(identifier.split())
        field_terms = set(fields.split())
        description_terms = set(description.split())
        aliases = tuple(_search_text(alias) for alias in _ACTION_ALIASES.get(action_id, ()))
        score = sum(18 for term in terms if term in title_terms)
        score += sum(14 for term in terms if term in identifier_terms)
        score += sum(7 for term in terms if term in field_terms)
        score += sum(4 for term in terms if term in description_terms)
        if normalized_query == title or normalized_query == _search_text(action_id):
            score += 40
        if normalized_query in aliases:
            score += 100
        else:
            score += sum(45 for alias in aliases if alias in normalized_query)
            alias_terms = {term for alias in aliases for term in alias.split()}
            score += sum(12 for term in terms if term in alias_terms)
        if score:
            action_schema = {
                key: action.get(key)
                for key in (
                    "id", "category", "categoryName", "title", "description",
                    "fields", "defaults", "output", "outputs", "slots", "platform",
                )
                if key in action or key == "slots"
            }
            ranked.append(
                (
                    score,
                    f"action:{action_id}",
                    {
                        "id": action_id,
                        "kind": "action",
                        "title": action.get("title", action_id),
                        "content": (
                            f"{action.get('description', '')} Parámetros: "
                            + ", ".join(
                                f"{field.get('name')} ({field.get('type')}, "
                                f"{'obligatorio' if field.get('required') else 'opcional'})"
                                for field in action.get("fields", [])
                            )
                            + "."
                        ),
                        "action": action_schema,
                    },
                )
            )
    for document in _PRODUCT_DOCS["documents"]:
        title = _search_text(str(document.get("title", "")))
        topics = _search_text(" ".join(document.get("topics", [])))
        content = _search_text(str(document.get("content", "")))
        searchable = f"{title} {topics} {content}"
        title_terms = set(title.split())
        topic_terms = set(topics.split())
        content_terms = set(content.split())
        score = sum(10 for term in terms if term in title_terms)
        score += sum(7 for term in terms if term in topic_terms)
        score += sum(2 for term in terms if term in content_terms)
        if normalized_query in searchable:
            score += 8
        score += sum(
            100
            for alias in _DOCUMENT_ALIASES.get(str(document.get("id")), ())
            if normalized_query == _search_text(alias)
        )
        if score:
            ranked.append(
                (
                    score,
                    f"product:{document.get('id', '')}",
                    {
                        "id": document["id"],
                        "kind": "product",
                        "title": document["title"],
                        "content": document["content"],
                    },
                )
            )
    ranked.sort(key=lambda item: (-item[0], item[1]))
    results = [document for _, _, document in ranked[:limit]]
    return {
        "version": _PRODUCT_DOCS["version"],
        "catalogVersion": catalog.catalog_version,
        "catalogHash": catalog.catalog_hash,
        "results": results,
    }


@server.tool(annotations=_READ_ONLY)
def validate_bot(bot: dict[str, Any], mode: _MODE = "proposal") -> dict[str, Any]:
    """Valida un bot completo contra las reglas de estructura y capacidades canónicas de AutoClick."""
    result = validator.validate_bot(bot=bot, mode=mode)
    return result.model_dump(by_alias=True)


@server.tool(annotations=_READ_ONLY)
def validate_bot_patch(
    base_bot: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Valida un conjunto de operaciones de parche sobre un bot base."""
    result = validator.validate_bot_patch(base_bot=base_bot, operations=operations)
    return result.model_dump(by_alias=True)


@server.tool(annotations=_READ_ONLY)
def preview_bot_patch(
    base_bot: dict[str, Any], operations: list[dict[str, Any]]
) -> dict[str, Any]:
    """Aplica atómicamente operaciones sobre una copia y retorna el bot validado resultante."""
    result = previewer.preview_bot_patch(base_bot=base_bot, operations=operations)
    return result.model_dump(by_alias=True)


for _registered_tool in server._tool_manager._tools.values():
    _registered_tool.parameters["additionalProperties"] = False
    _registered_tool.fn_metadata.arg_model.model_config["extra"] = "forbid"
    _registered_tool.fn_metadata.arg_model.model_rebuild(force=True)


@asynccontextmanager
async def open_client_session() -> AsyncIterator[ClientSession]:
    """Connect a real MCP ClientSession to this server through an in-process transport."""
    async with create_client_server_memory_streams() as (client_streams, server_streams):
        async with anyio.create_task_group() as tasks:
            async def run_server() -> None:
                await server._lowlevel_server.run(
                    server_streams[0],
                    server_streams[1],
                    server._lowlevel_server.create_initialization_options(),
                    raise_exceptions=True,
                )

            tasks.start_soon(run_server)
            async with ClientSession(*client_streams) as session:
                await session.initialize()
                yield session
            tasks.cancel_scope.cancel()


def main():
    asyncio.run(server.run_stdio_async())


if __name__ == "__main__":
    main()
