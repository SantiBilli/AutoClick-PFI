import copy
import json
from functools import lru_cache
from importlib.resources import files

from app.mcp_client import mcp_catalog_snapshot
from app.schemas import ActionDefinition, ActionOutputDefinition, Capabilities


_FLOW_EXAMPLE_REQUIREMENTS = {
    "variable.create": {
        "fields": frozenset({"name", "value"}),
        "outputs": frozenset({("name", "value")}),
        "slots": frozenset(),
    },
    "flow.forRange": {
        "fields": frozenset(
            {"start", "end", "step", "currentVariable", "maxIterations"}
        ),
        "outputs": frozenset(),
        "slots": frozenset({"body"}),
    },
    "flow.if": {
        "fields": frozenset({"condition"}),
        "outputs": frozenset(),
        "slots": frozenset({"then", "else"}),
    },
}

_FLOW_EXAMPLE = {
    "description": (
        "Declara una variable con variable.create, interpolala como {{nombre}}, "
        "anida flow.if en body de flow.forRange y coloca sus ramas en then y else."
    ),
    "actions": [
        {
            "id": "variable.create",
            "fields": ["name", "value"],
            "outputs": ["name"],
        },
        {
            "id": "flow.forRange",
            "fields": [
                "start",
                "end",
                "step",
                "currentVariable",
                "maxIterations",
            ],
            "slots": ["body"],
        },
        {"id": "flow.if", "fields": ["condition"], "slots": ["then", "else"]},
    ],
}

_EXCEL_EXAMPLE_REQUIREMENTS = {
    "excel.open": {
        "fields": frozenset({"path", "outputVariable"}),
        "outputs": frozenset({("outputVariable", "workbook")}),
        "slots": frozenset(),
    },
    "excel.readCell": {
        "fields": frozenset(
            {"workbookVariable", "sheet", "cell", "outputVariable"}
        ),
        "outputs": frozenset({("outputVariable", "value")}),
        "slots": frozenset(),
    },
    "excel.writeCell": {
        "fields": frozenset({"workbookVariable", "sheet", "cell", "value"}),
        "outputs": frozenset(),
        "slots": frozenset(),
    },
    "excel.save": {
        "fields": frozenset({"workbookVariable"}),
        "outputs": frozenset(),
        "slots": frozenset(),
    },
}

_EXCEL_EXAMPLE = {
    "description": (
        "Para abrir un libro y leer o escribir celdas se necesitan una ruta "
        "absoluta de archivo y una hoja explicita aportadas por el usuario. Un "
        "nombre de archivo o una ubicacion relativa no completa la ruta, y el "
        "nombre del libro no completa la hoja. Si falta cualquier dato externo "
        'obligatorio, usa {"$pending":true} en ese parametro y genera el borrador. '
        "Los datos pendientes se completan en el editor antes de ejecutar."
    ),
    "actions": [
        {"id": "excel.open", "fields": ["path", "outputVariable"]},
        {
            "id": "excel.readCell",
            "fields": ["workbookVariable", "sheet", "cell", "outputVariable"],
        },
        {
            "id": "excel.writeCell",
            "fields": ["workbookVariable", "sheet", "cell", "value"],
        },
        {"id": "excel.save", "fields": ["workbookVariable"]},
    ],
}

_EXCEL_CONDITIONAL_FLOW_REQUIREMENTS = {
    "excel.open": _EXCEL_EXAMPLE_REQUIREMENTS["excel.open"],
    "flow.forRange": _FLOW_EXAMPLE_REQUIREMENTS["flow.forRange"],
    "excel.readCell": _EXCEL_EXAMPLE_REQUIREMENTS["excel.readCell"],
    "flow.if": _FLOW_EXAMPLE_REQUIREMENTS["flow.if"],
    "excel.writeCell": _EXCEL_EXAMPLE_REQUIREMENTS["excel.writeCell"],
    "excel.save": _EXCEL_EXAMPLE_REQUIREMENTS["excel.save"],
}

_EXCEL_CONDITIONAL_FLOW_EXAMPLE = {
    "description": (
        "Patron generico para recorrer celdas y escribir dos resultados "
        "complementarios: excel.open, flow.forRange y excel.save son hermanos "
        "en root. Dentro de flow.forRange.body son hermanos excel.readCell y "
        "exactamente un flow.if. Coloca un excel.writeCell en flow.if.then y el "
        "otro en flow.if.else. Las dos ramas son alternativas del mismo flow.if; "
        "no agregues un segundo flow.if. El patron tiene siete nodos nuevos y las "
        "acciones sin slots nunca son parents."
    ),
    "actions": [
        {"id": "excel.open", "location": "root sibling"},
        {
            "id": "flow.forRange",
            "location": "root sibling",
            "slots": ["body"],
        },
        {"id": "excel.readCell", "location": "flow.forRange.body sibling"},
        {
            "id": "flow.if",
            "location": "flow.forRange.body sibling",
            "slots": ["then", "else"],
        },
        {"id": "excel.writeCell", "location": "flow.if.then"},
        {"id": "excel.writeCell", "location": "flow.if.else"},
        {"id": "excel.save", "location": "root sibling"},
    ],
}

_EXAMPLES = (
    (_FLOW_EXAMPLE_REQUIREMENTS, _FLOW_EXAMPLE),
    (_EXCEL_EXAMPLE_REQUIREMENTS, _EXCEL_EXAMPLE),
    (_EXCEL_CONDITIONAL_FLOW_REQUIREMENTS, _EXCEL_CONDITIONAL_FLOW_EXAMPLE),
)


def _action_outputs(action: ActionDefinition) -> list[ActionOutputDefinition]:
    if action.outputs:
        return action.outputs
    return [action.output] if action.output is not None else []


def _document_action(action: ActionDefinition) -> dict[str, object]:
    documented: dict[str, object] = {
        "id": action.id,
        "title": action.title,
        "description": action.description,
        "fields": [
            field.model_dump(mode="json", by_alias=True, exclude_none=True)
            for field in action.fields
        ],
        "defaults": copy.deepcopy(action.defaults),
        "outputs": [
            output.model_dump(mode="json", by_alias=True)
            for output in _action_outputs(action)
        ],
        "slots": list(action.slots),
    }
    if action.platform is not None:
        documented["platform"] = action.platform
    return documented


def _supports_requirements(
    actions: dict[str, ActionDefinition], requirements: dict[str, dict[str, frozenset]]
) -> bool:
    for action_id, required in requirements.items():
        action = actions.get(action_id)
        if action is None:
            return False
        fields = {field.name for field in action.fields}
        outputs = {(output.field, output.type) for output in _action_outputs(action)}
        if not required["fields"].issubset(fields):
            return False
        if not required["outputs"].issubset(outputs):
            return False
        if not required["slots"].issubset(action.slots):
            return False
    return True


def supported_examples(capabilities: Capabilities) -> list[dict[str, object]]:
    actions = {action.id: action for action in capabilities.actions}
    return [
        copy.deepcopy(example)
        for requirements, example in _EXAMPLES
        if _supports_requirements(actions, requirements)
    ]


def _document_action_compact(action: ActionDefinition) -> dict[str, object]:
    # Compact means no examples, not missing facts. Small models can answer
    # without choosing a tool; retain the schema that grounds those answers.
    return _document_action(action)


@lru_cache(maxsize=1)
def _product_documentation() -> dict[str, object]:
    return json.loads(files("autoclick_mcp").joinpath("data/product_docs.json").read_text(encoding="utf-8"))


def build_capability_document(
    capabilities: Capabilities,
    *,
    compact: bool = False,
) -> dict[str, object]:
    categories: dict[str, dict[str, object]] = {}
    for action in capabilities.actions:
        category = categories.setdefault(
            action.category,
            {
                "id": action.category,
                "name": action.category_name,
                "actions": [],
            },
        )
        actions = category["actions"]
        assert isinstance(actions, list)
        actions.append(
            _document_action_compact(action) if compact else _document_action(action)
        )
    documented = list(categories.values())
    for category in documented:
        actions = category["actions"]
        assert isinstance(actions, list)
        category["actionCount"] = len(actions)
    snapshot = mcp_catalog_snapshot()
    canonical_actions = [
        ActionDefinition.model_validate(
            {
                key: value
                for key, value in action.items()
                if key
                in {
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
            }
        )
        for action in snapshot["actions"]
    ]
    identity_verified = (
        capabilities.catalog_version == snapshot["catalogVersion"]
        and capabilities.catalog_hash == snapshot["catalogHash"]
        and capabilities.actions == canonical_actions
    )
    result: dict[str, object] = {
        "catalogIdentityVerified": identity_verified,
        "actionCount": len(capabilities.actions),
        "categoryCount": len(documented),
        "categories": documented,
        "examples": [] if compact else supported_examples(capabilities),
    }
    if identity_verified:
        result["catalogVersion"] = snapshot["catalogVersion"]
        result["catalogHash"] = snapshot["catalogHash"]
        result["productDocumentation"] = copy.deepcopy(_product_documentation())
    return result
