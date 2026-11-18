import unicodedata
import uuid
import copy
from autoclick_mcp.pending import is_pending_parameter, allows_pending_parameter
from autoclick_mcp.validator import VISION_DERIVED_SUFFIXES, HTTP_DERIVED_SUFFIXES
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import PureWindowsPath
from typing import Annotated, Any, Literal, Self

from pydantic import (
    ConfigDict,
    Field,
    ModelWrapValidatorHandler,
    StrictInt,
    StrictStr,
    TypeAdapter,
    field_validator,
    model_validator,
)

from app.config import (
    CANONICAL_MAX_BOT_NODES,
    DEFAULT_MAX_JSON_DEPTH,
    MAX_GENERATION_BYTES,
    MAX_GENERATION_CODE_POINTS,
)
from app.schemas import (
    ActionFieldDefinition,
    ActionDefinition,
    ChatRequest,
    HomeBotDraft,
    JsonValue,
    StrictModel,
    is_valid_action_field_value,
    validate_json_tree,
)
from app.external_facts import (
    EvidenceAssignment,
    EvidenceSpan,
    ExternalFactRequirement,
    FactFieldRef,
    FieldSemantics,
    build_evidence_ledger,
    classify_field,
    discover_external_facts,
    plain_text,
    render_fact_labels,
    value_matches_assignment,
)
from app.editor_safety import classify_editor_intent
from app.home_intent import web_vision_click_intent
from app.mcp_client import (
    mcp_catalog_snapshot,
    mcp_preview_bot_patch,
    mcp_validate_bot,
)
from app.tree_diff import (
    TreeDiffError,
    canonical_bot_hash,
    canonicalize_bot,
    derive_tree_operations,
    dump_tree_operations,
)

MAX_PROPOSAL_OPERATIONS = 200

BoundedId = Annotated[StrictStr, Field(min_length=1, max_length=200)]


class _AgentProtocolModel(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        populate_by_name=True,
    )


class ProposalLocation(_AgentProtocolModel):
    parent_id: BoundedId | None = Field(
        alias="parentId",
        description=(
            "null only for root nodes; otherwise the ID of a parent addNode that "
            "appears earlier in operations and whose action declares the chosen slot"
        ),
    )
    slot: BoundedId = Field(
        description="exactly 'root' when parentId is null; otherwise a slot declared by the parent action"
    )
    index: StrictInt = Field(
        ge=0,
        le=1_000,
        description=(
            "zero-based insertion index among siblings already added to this exact "
            "parentId and slot; first child is 0, second sibling is 1"
        ),
    )

    @model_validator(mode="after")
    def validate_root_location(self) -> "ProposalLocation":
        if (self.parent_id is None) != (self.slot == "root"):
            raise ValueError("root is valid only with a null parentId")
        return self


class ProposalNode(_AgentProtocolModel):
    id: BoundedId
    type: BoundedId
    params: dict[str, JsonValue]


class SetMetadataOperation(_AgentProtocolModel):
    op: Literal["setMetadata"]
    name: StrictStr | None = Field(default=None, max_length=120)
    description: StrictStr | None = Field(default=None, max_length=500)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("name must not be blank")
        return value

    @model_validator(mode="after")
    def require_change(self) -> "SetMetadataOperation":
        if self.name is None and self.description is None:
            raise ValueError("setMetadata requires name or description")
        return self


class AddNodeOperation(_AgentProtocolModel):
    op: Literal["addNode"]
    node: ProposalNode
    location: ProposalLocation


class RemoveNodeOperation(_AgentProtocolModel):
    op: Literal["removeNode"]
    node_id: BoundedId = Field(alias="nodeId")


class MoveNodeOperation(_AgentProtocolModel):
    op: Literal["moveNode"]
    node_id: BoundedId = Field(alias="nodeId")
    location: ProposalLocation


class UpdateNodeParamsOperation(_AgentProtocolModel):
    op: Literal["updateNodeParams"]
    node_id: BoundedId = Field(alias="nodeId")
    params: dict[str, JsonValue]


class ReplaceNodeOperation(_AgentProtocolModel):
    op: Literal["replaceNode"]
    node_id: BoundedId = Field(alias="nodeId")
    action_type: BoundedId = Field(alias="actionType")
    params: dict[str, JsonValue]


ProposalOperation = Annotated[
    SetMetadataOperation
    | AddNodeOperation
    | RemoveNodeOperation
    | MoveNodeOperation
    | UpdateNodeParamsOperation
    | ReplaceNodeOperation,
    Field(discriminator="op"),
]


class AgentProposalArguments(_AgentProtocolModel):
    summary: StrictStr = Field(min_length=1, max_length=1_000)
    operations: list[ProposalOperation] = Field(
        min_length=1,
        max_length=MAX_PROPOSAL_OPERATIONS,
        description="A JSON array of operation objects. Never encode this array as a string.",
    )

    @field_validator("summary")
    @classmethod
    def reject_blank_summary(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value

    @model_validator(mode="after")
    def validate_json_bounds(self) -> "AgentProposalArguments":
        validate_json_tree(
            self.model_dump(mode="python", by_alias=True), DEFAULT_MAX_JSON_DEPTH
        )
        return self


class AgentAnswer(_AgentProtocolModel):
    kind: Literal["answer"]
    message: StrictStr = Field(min_length=1, max_length=64_000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class AgentClarification(_AgentProtocolModel):
    kind: Literal["clarification"]
    message: StrictStr = Field(
        min_length=1,
        max_length=64_000,
        description=(
            "Una sola clausula breve que comienza directamente con un verbo para "
            "pedir informacion, por ejemplo Indicame, y coordina juntos todos los "
            "datos obligatorios faltantes. No incluye introduccion, explicacion, "
            "ejemplo, alternativa, valor sugerido ni una segunda oracion."
        ),
    )

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class AgentProposal(_AgentProtocolModel):
    kind: Literal["proposal"]
    proposal: AgentProposalArguments


AgentTurn = Annotated[
    AgentAnswer | AgentClarification | AgentProposal,
    Field(discriminator="kind"),
]
AGENT_TURN_ADAPTER = TypeAdapter(AgentTurn)


def _ollama_compatible_schema(schema: dict[str, object]) -> dict[str, object]:
    pending: list[object] = [schema]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            # Ollama's grammar compiler rejects these protocol-sized bounds.
            value.pop("maxLength", None)
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    return schema


def agent_turn_schema() -> dict[str, object]:
    return _ollama_compatible_schema(AGENT_TURN_ADAPTER.json_schema(by_alias=True))


def parse_agent_turn(content: str) -> AgentTurn:
    return AGENT_TURN_ADAPTER.validate_json(content)


def _clean_home_intent_text(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    cleaned = "".join(c for c in nfkd if not unicodedata.combining(c)).casefold().strip()
    strip_chars = set(['\xbf', '\xa1', '?', '!', '.', ',', ';', ':', ' ', '"', "'", '(', ')', '_', '-'])
    while cleaned and cleaned[0] in strip_chars:
        cleaned = cleaned[1:].strip()
    while cleaned and cleaned[-1] in strip_chars:
        cleaned = cleaned[:-1].strip()
    return cleaned


def _is_informational_question(cleaned: str) -> bool:
    if re.search(r"\b(?:hacelo|hacemelo|armalo|armamelo|crealo|creamelo|generalo|generamelo|pone\s+cualquier)\b", cleaned):
        return False
    if re.search(r"^(?:crea|creame|arma|armame|hace|haceme|genera|generame)\s+(?:(?:un|una|el|la|mi)\s+)?(?:primer(?:a)?\s+)?(?:bot|flujo|automatizacion)\b", cleaned):
        return False

    # Asking to describe or recommend an automation does not authorize a draft.
    # This selects the output contract; the model still interprets and answers.
    recommendation = re.search(
        r"\b(?:decime|dime|contame|cuentame|sugerime|sugiereme|recomendame|recomiendame)\s+"
        r"(?:una?|alguna?|otra?)\s+(?:automatizacion|bot|flujo|tarea|opcion)\b",
        cleaned,
    )
    explicit_creation = re.search(
        r"\b(?:creame|armame|generame|haceme|construime)\b", cleaned
    )
    if recommendation and not explicit_creation:
        return True

    # A question about whether detection itself clicks describes block behavior.
    # "necesito otro paso" is not a request to create that step.
    if re.search(
        r"\b(?:hace|realiza)\s+(?:un\s+)?(?:clic|click)\s+o\s+"
        r"(?:necesito|hace\s+falta|requiere)\b", cleaned,
    ):
        return True

    # Bare bot requests without details (e.g. "Quiero hacer un bot", "Necesito un bot", "Quiero armar una automatización", "Quiero empezar un bot nuevo") need clarification
    if re.search(r"^(?:quiero|haceme|creame|armame|necesito|deseo|me\s+gustaria)\s+(?:hacer\s+|armar\s+|crear\s+|empezar\s+|arrancar\s+)?(?:un\s+|una\s+|el\s+|este\s+)?(?:bot|flujo|script|automatizacion|bot\s+nuevo|nuevo\s+bot|flujo\s+nuevo|nuevo\s+flujo)\s*$", cleaned):
        return True

    info_patterns = [
        r"\b(?:me\s+)?(?:podes|podrias|puedes)\s+explicar(?:me)?\b",
        r"\bque\s+tipo[s]?\s+de\s+(?:bots|automatizaciones|flujos)\b",
        r"\b(?:que|cuales)\s+(?:bots|automatizaciones)\s+(?:podes|podrias|se\s+pueden|puedo)\s+(?:hacer|armar|crear)\b",
        r"\bque\s+(?:cosas\s+)?(?:podes|se\s+pueden?)\s+automatizar\b",
        r"\bpor\s+donde\s+(?:empiezo|arranco|comienzo)\b",
        r"\bque\s+(?:tipos?\s+de\s+)?procesos\b",
        r"\b(?:recomendados?|recomendacion|consejos?)\b",
        r"\b(?:lista|listado|resumen|catalogo|lsita|detalle|detalles)\s+de\s+(?:todos\s+los\s+|todas\s+las\s+)?(?:bloques|acciones|categorias)?\b",
        r"\b(?:todos\s+los\s+bloques|que\s+bloques|cuales\s+(?:son\s+los\s+)?bloques|bloques\s+que\s+tenes|bloques\s+disponibles|bloques\s+hay|bloques\s+tengo)\b",
        r"^(?:dame|mostra(?:me)?|pasar|pasame|ver|quiero\s+ver)\s+(?:todos|todas|todo)\b",
        r"^(?:todos|todas|todo)\s*[\.!?]*$",
        r"\b(?:todos|todas)\s+los\s+bloques\b",
        r"\b(?:dame|mostra(?:me)?|pasar|pasame)\s+(?:los\s+)?bloques\b",
        r"\b(?:ver|mostra(?:me)?|dame)\s+(?:el\s+)?catalogo\b",
        r"^(?:navegacion(?:\s+web)?|control(?:\s+de\s+flujos?)?|archivos?|excel|variables?|mouse|teclado|pantalla|espera|ejecucion)\s*[\.!?]*$",
        r"\b(?:para\s+que\s+sirve[ns]?|como\s+funciona[n]?|que\s+hace[n]?|para\s+que\s+me\s+sirve[ns]?)\b",
        r"\b(?:explicame|explicar|contame|mostrame|decime|dar(?:me)?|pasame)\s+(?:un\s+|el\s+|los\s+|las\s+)?(?:l[i\xed]sta|listado|detalle|detalles|resumen|info|catalogo)\b",
        r"\b(?:detalle|detalles|resumen)\s+(?:de\s+)?(?:todos|todas|cada\s+uno)\b",
        r"\b(?:ideas?|sugerencias?|recomendaciones?|recomendas|recomiendas|ejemplos?|pasos)\b",
        r"^(?:como|que|cuales|cual|para\s+que|explicame|explicar)\s+(?:creo|crear|hago|hacer|armo|armar|abro|abrir|uso|usar|funciona|sirve|son|puedo|podria|se\s+puede|recomiendas|sugieres|agregarle|agregar|bloques|acciones|otros\s+bloques|automatizo|automatizar|se\s+automatiza)\b",
        r"^(?:se\s+puede|se\s+pueden|puedo|es\s+posible|como\s+se\s+puede)\b",
        r"^(?:como\s+funciona|que\s+es|que\s+otros)\b",
        r"\b(?:que\s+acciones|cuales\s+acciones)\b",
        r"^(?:hola|buen\s+dia|buenos\s+dias|buenas\s+tardes|buenas\s+noches|como\s+estas|que\s+tal|ayuda)\b",
        r"\b(?:ayudame|ayudanos|ayuda|ayudas|me\s+ayudas?)\s+a\s+(?:crear|hacer|armar|automatizar|empezar)\b",
        r"\bno\s+s[e\xe9]\s+por\s+d[o\xf3]nde\b",
        r"\bno\s+s[e\xe9]\s+qu[e\xe9]\b",
        r"\b(?:necesito|quiero|busco)\s+ayuda\b",
        r"\b(?:como|por\s+donde)\s+(?:arrancar|empezar|comenzar)\b",
        r"\bpara\s+no\s+hacer\s+todo\s+manual\b",
        r"^(?:quiero|necesito|deseo|me\s+gustaria)\s+automatizar\s+(?:mi\s+|el\s+|mis\s+)?(?:trabajo|tarea[s]?|dia|vida|empresa|negocio|proceso[s]?)(?:\s+diario|\s+manual)?\s*[\.!?]*$",
        r"\b(?:podes|podias|podrias|se\s+puede|es\s+posible)\s+automatizar\b",
        r"\b(?:gracias|muchas\s+gracias|mil\s+gracias|te\s+agradezco|chau|adios|hasta\s+luego|nos\s+vemos)\b",
        r"\b(?:pregunta|preguntas|consulta|consultas|duda|dudas)\b",
        r"^(?:genial|excelente|perfecto|joya|buenisimo|de\s+nada|un\s+placer|ok\s+gracias|dale\s+gracias)(?:\s+.*)?$",
    ]
    if any(re.search(pat, cleaned) for pat in info_patterns):
        return True

    return False


def is_home_creation_deferred(message: str) -> bool:
    instructions = re.sub(r'"[^"\n]*"|\x60[^\x60\n]*\x60|«[^»\n]*»', '', message)
    cleaned = _clean_home_intent_text(instructions)
    return bool(re.search(
        r'\b(?:por\s+ahora|de\s+momento)\s+(?:solo\s+)?(?:explicame|contame|quiero\s+saber)\b'
        r'|\bsin\s+(?:armar|crear|hacer|generar|preparar)\s+(?:(?:un|una|el|la|ningun|ninguna)\s+)?(?:bot|flujo|automatizacion)\b'
        r'|\bno\s+(?:lo|la|el\s+bot)\s+(?:armes|crees|generes|hagas|prepares)\b'
        r'|\bno\s+(?:armes|crees|generes|hagas|prepares)\s+'
        r'(?:todavia|aun|nada|(?:ningun|un|el)\s+(?:bot|flujo)|por\s+ahora|de\s+momento)\b'
        r'|\bno\s+(?:armes|crees|generes|hagas|prepares)\s*(?=$|[.!?;,:])',
        cleaned,
    ))


def is_home_creation_request(request: ChatRequest) -> bool:
    if request.editor_context is not None:
        return False
    user_messages = [item.content for item in request.messages if item.role == "user"]
    if not user_messages:
        return False

    latest_cleaned = _clean_home_intent_text(plain_text(user_messages[-1]))
    latest_cleaned = re.sub(
        r"^(?:hola|buenas|buenos dias|buen dia|buenas tardes|buenas noches|genial|perfecto|gracias)\b[\s,!.:;]*",
        "", latest_cleaned,
    ).strip()
    latest_cleaned = re.sub(r"[,;.!]?\s*(?:muchas )?gracias$", "", latest_cleaned).strip()
    # Removing a greeting can expose the opening punctuation of the actual
    # question. Normalize that boundary again, without rewriting user data.
    latest_cleaned = _clean_home_intent_text(latest_cleaned)
    if is_home_creation_deferred(user_messages[-1]):
        return False
    # A direct, enumerated action request can omit the word "bot".
    # Explanations, quotations and deferrals must not acquire mutation intent.
    if (re.match(
        r'^(?:quiero|necesito|deseo|me\s+gustaria)\s+'
        r'(?:estos|estas|los\s+siguientes|las\s+siguientes)\s+'
        r'(?:(?:\d+|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez)\s+)?'
        r'(?:pasos|acciones)\s*(?:en\s+orden\s*)?:',
        latest_cleaned,
    ) and not re.search(r'\b(?:solo|solamente)\s+(?:explica\w*|describi\w*|conta\w*|decime)\b', latest_cleaned)
            and not user_messages[-1].lstrip().startswith('¿')):
        return True
    # An indirect desire or a concrete example can still request a draft.
    # Preserve questions and deferrals before interpreting conversational words
    # such as "ejemplo" or "otros pasos" as purely informational.
    indirect = re.match(
        r'^(?:me\s+(?:sirve|vendria\s+bien|gustaria)\s+(?:un|una)\s+(?:bot|flujo|automatizacion)\s+(?:que|para)\b'
        r'|(?:quiero|necesito)\s+un\s+ejemplo\s+(?:que|para|con)\b)', latest_cleaned,
    )
    if (indirect and not user_messages[-1].lstrip().startswith('¿')
            and '?' not in user_messages[-1]
            and not re.search(r'\b(?:solo|solamente)\s+(?:explica\w*|conta\w*|decime)\b', latest_cleaned)):
        return True
    # A direct request can contain conversational phrases such as "como lo
    # hago yo" or "no se como explicartelo". Those phrases do not turn a
    # request for a bot into a question about the product.
    if re.match(
        r'^(?:(?:quiero|necesito|deseo|me\s+gustaria)\s+(?:(?:crear|armar|hacer)\s+)?'
        r'(?:un|una|el|la)\s+(?:bot|flujo|automatizacion|rutina|grupo|bucle|rango|recorrido)\b'
        r'|(?:quiero|necesito)\s+automatizar\b'
        r'|(?:crea(?:me)?|arma(?:me)?|hace(?:me)?|genera(?:me)?|prepara(?:me)?)\s+'
        r'(?:un|una|el|la)\s+(?:bot|flujo|automatizacion|rutina|grupo|bucle|rango|recorrido)\b)',
        latest_cleaned,
    ) and not re.search(r'\b(?:solo|solamente|por\s+ahora)\s+(?:explica\w*|conta\w*|decime)\b', latest_cleaned):
        return True
    if (classify_editor_intent(user_messages[-1]) == "informational"
            or classify_editor_intent(latest_cleaned) == "informational"):
        return False
    # A request to prepare actions need not contain the product's word "bot".
    # In particular, conversational nouns such as "consulta" may describe an
    # actual HTTP task. Explicit deferrals and informational intent were checked
    # first; the model still decides whether the routine needs clarification.
    construction = re.search(
        r'\b(?:crea(?:me)?|arma(?:me)?|prepara(?:me)?|genera(?:me)?|hace(?:me)?|'
        r'organiza(?:lo|melo)?|construi(?:me)?)\b'
        r'|\busa(?:me)?\s+(?:repeticiones|bucles)\b', latest_cleaned,
    )
    explanation = re.search(
        r'\b(?:arma(?:me)?|prepara(?:me)?|genera(?:me)?|hace(?:me)?)\s+'
        r'(?:(?:un|una|el|la)\s+)?(?:explicacion|guia|resumen|lista|listado|detalle|catalogo)\b',
        latest_cleaned,
    )
    if classify_editor_intent(latest_cleaned) == 'mutation' and construction and not explanation:
        return True
    if re.fullmatch(r"(?:hacelo|hacemelo|armalo|armamelo|crealo|creamelo|generalo|generamelo)", latest_cleaned):
        return any(
            re.search(r"\b(?:crear|crea|armar|arma|hacer|hace|quiero|necesito)\b.*\b(?:bot|flujo|automatizacion)\b", _clean_home_intent_text(text))
            for text in user_messages[-3:-1]
        )
    if latest_cleaned == "quiero crear el bot":
        return True

    if len(user_messages) >= 2:
        last_assistant_msg = next(
            (m.content for m in reversed(request.messages[:-1]) if m.role == "assistant"),
            ""
        ).lower()
        explicit_bot_offer = (
            r"\b(?:quer[eé]s\s+que\s+(?:cree|arme|construya|generemos|hagamos)|"
            r"te\s+armo\s+un\s+bot|te\s+creo\s+el\s+bot|quer[eé]s\s+que\s+lo\s+(?:arme|cree|haga)|"
            r"armamos\s+el\s+bot|creamos\s+el\s+bot|"
            r"te\s+gustar[ií]a\s+(?:que\s+)?(?:armar|crear|hacer|construir)\s+(?:este|un|el)?\s*bot)\b"
        )
        has_assistant_offer = bool(re.search(explicit_bot_offer, last_assistant_msg))

        # If user gives a bare bot request like "creame el bot", "haceme el bot", "quiero el bot"
        bare_bot_request = r"^\s*(?:quiero|haceme|creame|armame|necesito|deseo|me\s+gustaria)\s+(?:hacer\s+|armar\s+|crear\s+|empezar\s+|arrancar\s+)?(?:un\s+|una\s+|el\s+|este\s+)?(?:bot|flujo|script|automatizacion)\s*[.!?]*$"
        if re.match(bare_bot_request, latest_cleaned):
            if has_assistant_offer or any(
                re.search(
                    r"\b(?:bot|flujo|automatizar|abrir|excel|navegador|login|facebook|web|google|url|libro|hoja|fila|celda|vision|pantalla|click|teclado)\b",
                    _clean_home_intent_text(plain_text(m)),
                )
                is not None
                for m in user_messages[-4:-1]
            ):
                return True

    if _is_informational_question(latest_cleaned):
        return False

    creation_pattern = (
        r"\b(?:crea(?:me)?|crear|creo|hace(?:me)?|hacer|arma(?:me)?|armar|genera(?:me)?|generar|prepara(?:me)?|preparar|construir|construye|quiero|necesito|deseo|podes|podras|podria|favor\s+de|inventa(?:me)?|dame|proba|mostra(?:me)?)\b.*?\b(?:bot|flujo|script|automatizaci[o\xc3\xa1\xc3\xb3a-z0-9]+|otro|otra|uno|una|este|esto)(?!\s+(?:pregunta|consulta|duda|cosa|aclaracion))\b|"
        r"\b(?:un|el|este|nuevo|otro|uno|una|otra)\s+(?:bot|flujo|script|automatizacion|ejemplo)?\s*(?:que|para|de|con|en)\b|"
        r"\b(?:haceme|armame|creame|generame|inventame|mostrame|dame)\s+(?:otro|otra|uno|una|un|el|nuevo|este|esto)\b|"
        r"\b(?:hacer\s+este|hacer\s+esto|quiero\s+hacer|necesito\s+hacer)\b|"
        r"^(?:otro|otra)\b|"
        r"\b(?:automatizar|automatizame|automatiza)\b|"
        r"^(?:bot|flujo|script)\s+(?:que|para|de|con|en)\b|"
        r"\b(?:quiero|necesito)\s+que\b|"
        r"\b(?:hacelo|hacemelo|armalo|armamelo|crealo|creamelo|generalo|generamelo)\b|"
        r"\bque\s+se\s+llame\b|"
        r"^\s*crear\s+(?:el\s+)?(?:bot|flujo)\s*[.!?]*\s*$"
    )
    if re.search(creation_pattern, latest_cleaned):
        return True

    if len(user_messages) < 2:
        return False

    follow_up_pattern = (
        r"\b(?:hacelo|hacemelo|armalo|armamelo|crealo|creamelo|generalo|generamelo)\b|"
        r"^\s*(?:me\s+)?(?:lo\s+)?(?:podes|podras)\s+(?:hacer|armar|crear|generar|hacerlo|armarlo)(?:\s+(?:este|el|un)\s+bot)?\s*[.!?]*$|"
        r"\b(?:pone|poneme|usa|usame|con)\s+(?:cualquier|datos|valores|ejemplo)\b|"
        r"\b(?:creamelo|crealo|armamelo|armalo|hacemelo|hacelo)\s+vos\b|"
        r"\b(?:despues|luego)\s+(?:yo\s+)?(?:los|lo)\s+(?:cambio|acomodo|modifico|ajusto)\b|"
        r"^(?:otro|otra|uno\s+mas|otra\s+opcion)\b"
    )
    if re.search(follow_up_pattern, latest_cleaned):
        return any(
            re.search(
                r"\b(?:bot|flujo|automatizar|abrir|excel|navegador|login|facebook|web|google|url|libro|hoja|fila|celda)\b",
                _clean_home_intent_text(plain_text(m)),
            )
            is not None
            for m in user_messages[-3:-1]
        )

    bare_confirmation_pattern = r"^\s*(?:si|dale|ok|bueno|por\s+favor|adelante)(?:[,\s]+(?:tambien|hacelo|armalo|crealo))?\s*[.!?]*$"
    if re.match(bare_confirmation_pattern, latest_cleaned):
        last_assistant_msg = next(
            (m.content for m in reversed(request.messages[:-1]) if m.role == "assistant"),
            ""
        ).lower()
        explicit_bot_offer = (
            r"\b(?:quer[eé]s\s+que\s+(?:cree|arme|construya|generemos|hagamos)|"
            r"te\s+armo\s+un\s+bot|te\s+creo\s+el\s+bot|quer[eé]s\s+que\s+lo\s+(?:arme|cree|haga)|"
            r"armamos\s+el\s+bot|creamos\s+el\s+bot|"
            r"te\s+gustar[ií]a\s+(?:que\s+)?(?:armar|crear|hacer|construir)\s+(?:este|un|el)?\s*bot)\b"
        )
        if re.search(explicit_bot_offer, last_assistant_msg):
            return True
        preceding_user = _clean_home_intent_text(plain_text(user_messages[-2]))
        if re.search(r'\bofreceme\s+(?:armar|crear|hacer)\s+(?:el\s+|un\s+)?bot\b', preceding_user):
            return True
        return False

    # A reply supplying missing values remains in the creation conversation.
    # This enables the answer/clarification/flow schema; the model still chooses
    # the appropriate outcome. Do not require another explicit 'create a bot'.
    if (len(request.messages) >= 3 and request.messages[-2].role == "assistant"
            and request.messages[-3].role == "user"):
        previous = request.model_copy(update={"messages": request.messages[:-2]})
        if is_home_creation_request(previous):
            return True
    return False


def _home_bot_draft_schema(chat_request: ChatRequest) -> dict[str, object]:
    # Every Home turn can answer, clarify or propose. Keyword routing used to
    # forbid genuine requests containing "No agregues otros pasos", while the
    # creation branch required a flow even for an ordinary answer.
    if (not is_home_creation_request(chat_request) and
            (is_home_creation_deferred(chat_request.messages[-1].content)
             or classify_editor_intent(chat_request.messages[-1].content) == "informational"
             or _is_informational_question(_clean_home_intent_text(chat_request.messages[-1].content)))):
        return {"oneOf": [{"type": "object", "properties": {
            "kind": {"const": "answer"}, "message": {"type": "string", "minLength": 1},
        }, "required": ["kind", "message"], "additionalProperties": False}]}
    snapshot = mcp_catalog_snapshot()
    task_text = _home_latest_task_text(chat_request)
    copy_only = _copy_only_intent(task_text)
    if not copy_only and re.search(r'\bcopiarlo\b', _clean_home_intent_text(task_text)):
        copy_only = any(
            _copy_only_intent(message.content)
            for message in chat_request.messages[:-1] if message.role == 'user'
        )
    web_vision = web_vision_click_intent(task_text)
    last_row_range = re.search(
        r'\bdesde\s+[a-z]{1,3}(\d+)\s+hasta\s+la\s+ultima\s+fila\b',
        _clean_home_intent_text(task_text),
    )
    allowed_actions = (
        {'file.copy'} if copy_only else
        {'browser.open', 'execution.wait', 'vision.detectElement', 'mouse.click'} if web_vision else None
    )
    if last_row_range is not None:
        allowed_actions = {
            'excel.open', 'excel.lastRow', 'flow.forRange',
            'excel.readCell', 'excel.writeCell', 'excel.save',
        }
    node_variants = [
        _updated_flow_action_schema(action)
        for action in _canonical_action_definitions(snapshot)
        if allowed_actions is None or action.id in allowed_actions
    ]
    forced_pending = _explicit_pending_fields(task_text)
    if web_vision is not None and web_vision.wait_milliseconds is None:
        forced_pending['execution.wait'] = ('milliseconds',)
    pending_only = {
        'type': 'object', 'properties': {'$pending': {'const': True}},
        'required': ['$pending'], 'additionalProperties': False,
    }
    for variant in node_variants:
        action_id = variant['properties']['type']['const']
        params = variant['properties']['params']['properties']
        if web_vision is not None:
            if action_id == 'browser.open':
                params['url'] = {'const': web_vision.url}
            elif action_id == 'vision.detectElement':
                params['text'] = {'const': web_vision.target_text}
            elif action_id == 'execution.wait' and web_vision.wait_milliseconds is not None:
                params['milliseconds'] = {'const': web_vision.wait_milliseconds}
        if action_id == 'flow.forRange' and last_row_range is not None:
            params['start'] = {'const': int(last_row_range.group(1))}
            params['step'] = {'const': 1}
        for field in forced_pending.get(action_id, ()):
            if field in params:
                params[field] = copy.deepcopy(pending_only)
    if last_row_range is not None:
        cell_variants = [
            copy.deepcopy(variant) for variant in node_variants
            if variant['properties']['type']['const'] in {'excel.readCell', 'excel.writeCell'}
        ]
        for variant in node_variants:
            if variant['properties']['type']['const'] == 'flow.forRange':
                variant['properties']['slots']['properties']['body'] = {
                    'type': 'array', 'minItems': 2, 'maxItems': 2,
                    'items': {'oneOf': cell_variants},
                }
    if not node_variants:
        raise ProposalValidationError("no actions are representable in updatedFlow")
    answers = [
        {
            "type": "object",
            "properties": {
                "kind": {"const": kind},
                "message": {"type": "string", "minLength": 1, "maxLength": 64000},
            },
            "required": ["kind", "message"],
            "additionalProperties": False,
        }
        for kind in ("answer", "clarification")
    ]
    return _ollama_compatible_schema({
        "$defs": {"UpdatedFlowNode": {"oneOf": node_variants}},
        "oneOf": [
            *answers,
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "updatedFlow"},
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "description": {"type": "string", "maxLength": 500},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "flow": {
                        "type": "array", "minItems": 4 if web_vision or last_row_range else 1,
                        "maxItems": 4 if web_vision else 1 if copy_only else CANONICAL_MAX_BOT_NODES,
                        "items": {"$ref": "#/$defs/UpdatedFlowNode"},
                    },
                    "catalogVersion": {"const": snapshot["catalogVersion"]},
                    "catalogHash": {"const": snapshot["catalogHash"]},
                },
                "required": ["kind", "name", "description", "summary", "flow"],
                "additionalProperties": False,
            },
        ],
    })


def _nest_flat_loop_bodies(items: list[Any]) -> list[Any]:
    if not isinstance(items, list):
        return items
    nested: list[Any] = []
    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, dict):
            item = copy.deepcopy(item)
            item_type = item.get("type")
            slots = item.get("slots")
            if not isinstance(slots, dict):
                slots = {}
                item["slots"] = slots
            for slot_key, slot_children in list(slots.items()):
                if isinstance(slot_children, list):
                    slots[slot_key] = _nest_flat_loop_bodies(slot_children)
            if item_type in ("flow.forRange", "flow.forEach") and not slots.get("body"):
                body_items: list[Any] = []
                j = i + 1
                while j < len(items):
                    next_item = items[j]
                    if isinstance(next_item, dict) and next_item.get("type") in ("flow.forRange", "flow.forEach", "flow.if"):
                        break
                    body_items.append(_nest_flat_loop_bodies([next_item])[0] if isinstance(next_item, dict) else next_item)
                    j += 1
                if body_items:
                    slots["body"] = body_items
                    i = j - 1
            nested.append(item)
        else:
            nested.append(item)
        i += 1
    return nested


def _flatten_home_tree(
    flow_items: list[Any], actions: dict[str, Any]
) -> tuple[list[str], dict[str, dict[str, JsonValue]]]:
    used_ids: set[str] = set()
    nodes_by_id: dict[str, dict[str, JsonValue]] = {}

    def process_node(item: Any) -> str:
        if not isinstance(item, dict):
            raise ProposalValidationError("each node in flow must be a JSON object")
        node_type = item.get("type")
        if not isinstance(node_type, str) or node_type not in actions:
            raise ProposalValidationError(f"unknown action type: {node_type}")
        action = actions[node_type]
        node_id = item.get("id")
        if not isinstance(node_id, str) or not node_id.strip() or node_id in used_ids:
            node_id = f"node-{len(used_ids) + 1}-{uuid.uuid4().hex[:6]}"
        used_ids.add(node_id)

        raw_params = item.get("params")
        if not isinstance(raw_params, dict):
            raise ProposalValidationError(f"node {node_id} params must be an object")
        params = copy.deepcopy(getattr(action, "defaults", {}))
        params.update(raw_params)

        raw_slots = item.get("slots") or {}
        if not isinstance(raw_slots, dict):
            raise ProposalValidationError(f"node {node_id} slots must be an object")
        slots: dict[str, list[str]] = {}
        for slot_name in getattr(action, "slots", []):
            children = raw_slots.get(slot_name, [])
            if not isinstance(children, list):
                raise ProposalValidationError(f"node {node_id} slot {slot_name} must be an array")
            slots[slot_name] = [process_node(child) for child in children]

        nodes_by_id[node_id] = {
            "id": node_id,
            "type": node_type,
            "params": params,
            "slots": slots,
        }
        return node_id

    root_ids = [process_node(item) for item in flow_items]
    return root_ids, nodes_by_id


def validate_home_bot_draft(
    bot: dict[str, Any], chat_request: ChatRequest
) -> HomeBotDraft:
    latest_user_text = _home_latest_task_text(chat_request)

    snapshot = mcp_catalog_snapshot()
    catalog_version = bot.get("catalogVersion") if "catalogVersion" in bot else chat_request.capabilities.catalog_version
    catalog_hash = bot.get("catalogHash") if "catalogHash" in bot else chat_request.capabilities.catalog_hash

    if (
        catalog_version != snapshot["catalogVersion"]
        or catalog_hash != snapshot["catalogHash"]
        or catalog_version != chat_request.capabilities.catalog_version
        or catalog_hash != chat_request.capabilities.catalog_hash
    ):
        raise ProposalValidationError("home draft catalog identity does not match MCP")

    # If it is a full HomeBotDraft payload with "bot"
    if "bot" in bot and isinstance(bot["bot"], dict):
        raw_bot = bot["bot"]
        name = bot.get("name") or raw_bot.get("name")
        summary = bot.get("summary")
        if not isinstance(name, str) or not name.strip() or not isinstance(summary, str) or not summary.strip():
            raise ProposalValidationError("home draft requires a model-generated name and summary")
        if raw_bot.get("schemaVersion") != 2 or not isinstance(raw_bot.get("id"), str) or not raw_bot["id"]:
            raise ProposalValidationError("home draft bot identity is invalid")
        if raw_bot.get("name") != name:
            raise ProposalValidationError("home draft name must match bot name")
        flow = raw_bot.get("flow")
        if not isinstance(flow, dict) or not isinstance(flow.get("root"), list) or not isinstance(flow.get("nodes"), list):
            raise ProposalValidationError("home draft flow is invalid")
        actions = _verified_canonical_actions(chat_request)
        nodes = {
            node.get("id"): node
            for node in flow["nodes"]
            if isinstance(node, dict) and isinstance(node.get("id"), str)
        }
        if len(nodes) != len(flow["nodes"]):
            raise ProposalValidationError("home draft node IDs are invalid")
        _validate_home_excel_last_row({"flow": {"root": flow["root"], "nodes": list(nodes.values())}}, latest_user_text)
        normalized = _validate_resulting_bot(flow["root"], nodes, actions, None)
        validated_bot = {
            key: copy.deepcopy(value) for key, value in raw_bot.items() if key != "flow"
        }
        validated_bot["flow"] = {
            "root": copy.deepcopy(flow["root"]),
            "nodes": list(normalized.values()),
        }
        mcp_result = mcp_validate_bot(validated_bot, mode="proposal")
        errors = [
            issue for issue in mcp_result.get("issues", [])
            if isinstance(issue, dict) and issue.get("severity", "error") == "error"
        ]
        if not mcp_result.get("ok") or errors:
            error_msgs = [e.get("message", "Error") for e in errors]
            raise ProposalValidationError(
                f"MCP rejected the Home bot draft: {'; '.join(error_msgs)}",
                repair_details=[f"Error de validación MCP a corregir: {e}" for e in error_msgs],
            )
        _validate_explicit_repeat_count(validated_bot, latest_user_text)
        _validate_requested_control_flow(validated_bot, latest_user_text)
        _validate_home_excel_last_row(validated_bot, latest_user_text)
        _validate_home_excel_condition(validated_bot, latest_user_text)
        _validate_simple_single_action(validated_bot, chat_request)
        _validate_home_paths(validated_bot, chat_request)
        _validate_explicit_pending_fields(validated_bot, latest_user_text)
        _validate_copy_without_move(validated_bot, latest_user_text)
        _validate_vision_click_flow(validated_bot, latest_user_text)
        _validate_web_click_wait(validated_bot, latest_user_text)
        _validate_web_vision_click_intent(validated_bot, latest_user_text)
        summary = _ground_home_summary(summary, validated_bot, actions)
        return HomeBotDraft(
            bot=validated_bot,
            name=name,
            summary=summary,
            catalog_version=catalog_version,
            catalog_hash=catalog_hash,
        )

    # Otherwise if it is an updatedFlow tree
    name = bot.get("name")
    description = bot.get("description") or ""
    summary = bot.get("summary")
    if not isinstance(name, str) or not name.strip() or not isinstance(summary, str) or not summary.strip():
        raise ProposalValidationError("home draft requires a model-generated name and summary")

    clean_flow_items = bot.get("flow")
    if not isinstance(clean_flow_items, list) or not clean_flow_items:
        raise ProposalValidationError("home draft must contain a nonempty flow")
    actions = _verified_canonical_actions(chat_request)
    count = [0]
    for item in clean_flow_items:
        _parse_updated_flow_node(item, actions, count=count, depth=1,
                                 max_depth=DEFAULT_MAX_JSON_DEPTH)

    actions = _verified_canonical_actions(chat_request)
    root_ids, nodes_by_id = _flatten_home_tree(clean_flow_items, actions)
    _validate_home_excel_last_row({"flow": {"root": root_ids, "nodes": list(nodes_by_id.values())}}, latest_user_text)
    normalized = _validate_resulting_bot(root_ids, nodes_by_id, actions, None)

    canonical_bot = {
        "schemaVersion": 2,
        "id": str(uuid.uuid4()),
        "name": name,
        "description": description,
        "icon": "bot",
        "flow": {
            "root": root_ids,
            "nodes": list(normalized.values()),
        },
    }
    mcp_result = mcp_validate_bot(canonical_bot, mode="proposal")
    errors = [
        issue for issue in mcp_result.get("issues", [])
        if isinstance(issue, dict) and issue.get("severity", "error") == "error"
    ]
    if not mcp_result.get("ok") or errors:
        error_msgs = [e.get("message", "Error") for e in errors]
        raise ProposalValidationError(
            f"MCP rejected the Home bot draft: {'; '.join(error_msgs)}",
            repair_details=[f"Error de validación MCP a corregir: {e}" for e in error_msgs],
        )
    _validate_explicit_repeat_count(canonical_bot, latest_user_text)
    _validate_requested_control_flow(canonical_bot, latest_user_text)
    _validate_home_excel_last_row(canonical_bot, latest_user_text)
    _validate_home_excel_condition(canonical_bot, latest_user_text)
    _validate_simple_single_action(canonical_bot, chat_request)
    _validate_home_paths(canonical_bot, chat_request)
    _validate_explicit_pending_fields(canonical_bot, latest_user_text)
    _validate_copy_without_move(canonical_bot, latest_user_text)
    _validate_vision_click_flow(canonical_bot, latest_user_text)
    _validate_web_click_wait(canonical_bot, latest_user_text)
    _validate_web_vision_click_intent(canonical_bot, latest_user_text)
    summary = _ground_home_summary(summary, canonical_bot, actions)
    return HomeBotDraft(
        bot=canonical_bot,
        name=name,
        summary=summary,
        catalog_version=catalog_version,
        catalog_hash=catalog_hash,
    )


def _ground_home_summary(summary: str, bot: dict[str, Any], actions: dict[str, Any]) -> str:
    """Reject false claims without replacing the model's visible wording."""
    # A schema-field name in prose must refer to an actual field/value. This
    # catches copied prompt jargon while allowing those words as user data.
    technical = {field.name for action in actions.values() for field in action.fields
                 if re.search(r'[a-z][A-Z]', field.name)}
    actual_fields = {key for node in bot['flow']['nodes'] for key in node['params']}
    actual_values = json.dumps([node['params'] for node in bot['flow']['nodes']], ensure_ascii=False)
    unsupported = sorted(field for field in technical - actual_fields
                         if re.search(r'\b' + re.escape(field) + r'\b', summary)
                         and not re.search(r'\b' + re.escape(field) + r'\b', actual_values))
    if unsupported:
        raise ProposalValidationError('summary mentions absent fields', repair_details=[
            'El resumen menciona campos ausentes del flujo: ' + ', '.join(unsupported)
            + '. Reescribilo en lenguaje cotidiano según los pasos reales, sin copiar instrucciones del esquema.'
        ])
    missing = {
        (node['type'], field)
        for node in bot['flow']['nodes']
        for field, value in node['params'].items()
        if is_pending_parameter(value)
    }
    normalized = _clean_home_intent_text(summary)
    if missing:
        if re.search(r'\b(?:no\s+(?:falta|faltan|queda|quedan)|todos?\s+los\s+datos\s+(?:estan|quedaron)\s+completos?)\b', normalized):
            raise ProposalValidationError(
                'home draft summary denies pending values',
                repair_details=['El borrador tiene parámetros pendientes. Describí los pasos y aclaralo en el resumen.'],
            )
        return summary
    stale_missing = re.search(
        r'\b(?:falta(?:n)?\s+(?:configurar|completar|indicar)|'
        r'debe(?:n)?\s+(?:completarse|configurarse)|'
        r'sigue(?:n)?\s+pendiente(?:s)?|'
        r'queda(?:n)?\s+pendiente(?:s)?)\b',
        normalized,
    )
    if not stale_missing:
        return summary
    raise ProposalValidationError(
        'home draft summary incorrectly describes pending values',
        repair_details=['Reescribí el resumen según el borrador validado; no afirmes que faltan datos si los parámetros están completos.'],
    )


def _validate_home_excel_last_row(bot: dict[str, Any], message: str) -> None:
    """Reject a last-row loop that is valid JSON but misses the requested rows."""
    cleaned = _clean_home_intent_text(message)
    source = re.search(r"\bdesde\s+([a-z]{1,3})(\d+)\s+hasta\s+la\s+ultima\s+fila\b", cleaned)
    destination = re.search(r"\bcolumna\s+([a-z]{1,3})\b", cleaned[source.end():] if source else '')
    if source is None or destination is None:
        return
    source_col, first_row = source.group(1).upper(), int(source.group(2))
    target_col = destination.group(1).upper()
    nodes = {node['id']: node for node in bot['flow']['nodes']}
    last_rows = [node for node in nodes.values() if node['type'] == 'excel.lastRow']
    loops = [node for node in nodes.values() if node['type'] == 'flow.forRange']
    details = ['Usa Obtener última fila; el bucle comienza en la primera fila indicada, termina en la última fila obtenida y avanza de a una fila.']
    if len(last_rows) != 1 or len(loops) != 1:
        raise ProposalValidationError('Excel last-row traversal needs one lastRow and one forRange', repair_details=details)
    last_row_var = last_rows[0]['params'].get('outputVariable')
    loop = loops[0]
    params = loop['params']
    row_var = params.get('currentVariable')
    if (params.get('start') != first_row or params.get('end') != f'{{{{{last_row_var}}}}}'
            or params.get('step') != 1 or not isinstance(row_var, str)):
        raise ProposalValidationError('Excel last-row traversal has incorrect loop bounds', repair_details=details)
    body = [nodes[identity] for identity in loop.get('slots', {}).get('body', [])]
    reads = [node for node in body if node['type'] == 'excel.readCell'
             and node['params'].get('cell') == f'{source_col}{{{{{row_var}}}}}']
    writes = [node for node in body if node['type'] == 'excel.writeCell'
              and node['params'].get('cell') == f'{target_col}{{{{{row_var}}}}}']
    if len(reads) != 1 or len(writes) != 1 or any(node['type'] == 'excel.writeRange' for node in nodes.values()):
        raise ProposalValidationError('Excel last-row body has missing or extra cell operations', repair_details=[
            f'Dentro del bucle lee {source_col}{{{{{row_var}}}}} y escribe {target_col}{{{{{row_var}}}}}; no agregues Escribir rango.',
        ])
    if re.search(r'\bguard(?:a|ar|e)\b', cleaned):
        saves = [node for node in nodes.values() if node['type'] == 'excel.save']
        root = bot['flow'].get('root', [])
        if len(saves) != 1 or loop['id'] not in root or saves[0]['id'] not in root or root.index(saves[0]['id']) <= root.index(loop['id']):
            raise ProposalValidationError(
                'Excel last-row task must save once after the loop',
                repair_details=['Coloca exactamente un bloque Guardar libro después del bucle en el flujo principal. No guardes dentro del cuerpo del bucle ni repitas Guardar libro.'],
            )


def _validate_home_excel_condition(bot: dict[str, Any], message: str) -> None:
    """Check the two explicit outcomes cannot be overwritten by later writes."""
    cleaned = _clean_home_intent_text(message)
    rows = re.search(r'\b([a-z]{1,3})(\d+):([a-z]{1,3})(\d+)\b', cleaned)
    outcomes = re.search(r'\bescriba\s+(\S+)\s+en\s+([a-z]{1,3})\s+si\b.*?\bmenor\s+a\s+(\d+)\s*,?\s*o\s+(\S+)\s+si\s+es\s+(\d+)\s+o\s+mas\b', cleaned)
    if rows is None or outcomes is None or rows.group(1) != rows.group(3) or outcomes.group(3) != outcomes.group(5):
        return
    source_col, start, _, end = rows.groups()
    low, target_col, threshold, high, _ = outcomes.groups()
    nodes = {node['id']: node for node in bot['flow']['nodes']}
    loops = [node for node in nodes.values() if node['type'] == 'flow.forRange']
    error = ['Recorre el rango pedido con un único bucle; dentro lee la celda, compara el valor y escribe una sola alternativa en cada rama. Guarda después; no agregues Escribir rango ni sobrescribas el resultado.']
    if len(loops) != 1 or any(node['type'] == 'excel.writeRange' for node in nodes.values()):
        raise ProposalValidationError('Excel conditional flow has extra writes or loop', repair_details=error)
    loop = loops[0]
    params, body = loop['params'], loop.get('slots', {}).get('body', [])
    row_var = params.get('currentVariable')
    if (params.get('start') != int(start) or params.get('end') != int(end)
            or params.get('step') != 1 or not isinstance(row_var, str)):
        raise ProposalValidationError('Excel conditional loop uses wrong rows', repair_details=error)
    reads = [nodes[node_id] for node_id in body if nodes[node_id]['type'] == 'excel.readCell'
             and nodes[node_id]['params'].get('cell') == f'{source_col.upper()}{{{{{row_var}}}}}']
    branches = [nodes[node_id] for node_id in body if nodes[node_id]['type'] == 'flow.if']
    if len(reads) != 1 or len(branches) != 1:
        raise ProposalValidationError('Excel conditional body is incomplete', repair_details=error)
    value_var = reads[0]['params'].get('outputVariable')
    branch = branches[0]
    clauses = branch['params'].get('condition', {}).get('clauses', [])
    if not any(clause.get('left') == f'{{{{{value_var}}}}}' and clause.get('operator') == 'lt'
               and clause.get('right') == int(threshold) for clause in clauses if isinstance(clause, dict)):
        raise ProposalValidationError('Excel conditional comparison is incorrect', repair_details=error)
    expected_cell = f'{target_col.upper()}{{{{{row_var}}}}}'
    for slot, expected_value in (('then', low), ('else', high)):
        slot_nodes = [nodes[node_id] for node_id in branch.get('slots', {}).get(slot, [])]
        writes = [node for node in slot_nodes if node['type'] == 'excel.writeCell'
                  and node['params'].get('cell') == expected_cell
                  and str(node['params'].get('value', '')).casefold() == expected_value]
        if len(writes) != 1:
            raise ProposalValidationError('Excel conditional outcome is incorrect', repair_details=error)
    all_writes = [node for node in nodes.values() if node['type'] == 'excel.writeCell']
    if len(all_writes) != 2 or (re.search(r'\bguarda\b', cleaned)
                                 and not any(node['type'] == 'excel.save' for node in nodes.values())):
        raise ProposalValidationError('Excel conditional flow has extra writes or omitted save', repair_details=error)


def _validate_simple_single_action(bot: dict[str, Any], request: ChatRequest) -> None:
    """Keep an explicit one-action copy or move free of unrelated steps."""
    latest = _clean_home_intent_text(request.messages[-1].content)
    expected = None
    match = re.search(r'\b(?:armame|creame|haceme)\s+un\s+bot\s+para\s+mover\s+una\s+carpeta\b', latest)
    if match:
        expected = 'folder.move'
    else:
        match = re.search(r'\b(?:armame|creame|haceme)\s+un\s+bot\s+para\s+copiar\s+un\s+archivo\b', latest)
    if match and expected is None:
        expected = 'file.copy'
    if match is None:
        match = re.search(r'\b(?:armame|creame|haceme)\s+ese\s+bot\s+para\s+copiarlo\b', latest)
    if match and expected is None:
        previous = ' '.join(_clean_home_intent_text(item.content) for item in request.messages[:-1] if item.role == 'user')
        if re.search(r'\bcopiar\s+un\s+archivo\b', previous):
            expected = 'file.copy'
    same_sentence_tail = latest[match.end():].split('.')[0] if match else ''
    if expected is None or re.search(r'\b(?:y|luego|despues|tambien)\b', same_sentence_tail):
        return
    if [node['type'] for node in bot['flow']['nodes']] != [expected]:
        raise ProposalValidationError('simple task contains missing or extra actions', repair_details=[
            f'Este pedido requiere únicamente el bloque {"Mover carpeta" if expected == "folder.move" else "Copiar archivo"}. '
            'No agregues Comentario ni otros pasos; deja rutas faltantes pendientes.',
        ])


def pending_parameter_labels(bot: dict[str, Any], actions: dict[str, Any]) -> list[tuple[str, str]]:
    """Name missing values from the canonical flow in words suitable for users."""
    missing = {
        (node['type'], field)
        for node in bot['flow']['nodes']
        for field, value in node['params'].items()
        if is_pending_parameter(value)
    }
    labels: list[tuple[str, str]] = []
    consumed: set[tuple[str, str]] = set()
    for action_id in ('file.copy', 'file.move', 'folder.copy', 'folder.move'):
        both = {(action_id, 'source'), (action_id, 'destination')}
        if both <= missing:
            labels.append(('las rutas de origen y destino', r'\brutas?\b'))
            consumed.update(both)
    for action_id in ('mouse.click', 'mouse.doubleClick', 'mouse.move'):
        both = {(action_id, 'x'), (action_id, 'y')}
        if both <= missing:
            labels.append(('las coordenadas del clic', r'\bcoordenad\w*\b'))
            consumed.update(both)
    if ('execution.wait', 'milliseconds') in missing:
        labels.append(('la duración de la espera', r'\b(?:duracion|espera)\b'))
        consumed.add(('execution.wait', 'milliseconds'))
    if ('browser.open', 'url') in missing:
        labels.append(('la dirección de la página', r'\b(?:url|direccion)\b'))
        consumed.add(('browser.open', 'url'))
    for action_id, field in sorted(missing - consumed):
        action = actions[action_id]
        field_label = next((item.label for item in action.fields if item.name == field), field)
        labels.append((f"{field_label.lower()} de {action.title}", re.escape(_clean_home_intent_text(field_label))))
    return labels


def _home_latest_task_text(request: ChatRequest) -> str:
    """Resolve a brief approval against the user's preceding task description."""
    user_messages = [message.content for message in request.messages if message.role == 'user']
    if not user_messages:
        return ''
    latest = user_messages[-1]
    cleaned = _clean_home_intent_text(latest)
    if len(user_messages) > 1 and re.fullmatch(
        r'(?:si|dale|ok|bueno|adelante|hacelo|armalo|crealo)(?:[,\s]+tambien)?',
        cleaned,
    ):
        return f'{user_messages[-2]} {latest}'
    return latest


def _explicit_pending_fields(message: str) -> dict[str, tuple[str, ...]]:
    """Constrain values the user explicitly says they cannot provide yet."""
    text = _clean_home_intent_text(message)
    result: dict[str, tuple[str, ...]] = {}
    if (
        re.search(r'\b(?:espera\w*|espere\w*)\b.{0,40}\b(?:cargue|carga|cargar)\b', text)
        and not re.search(r'\b\d+\s*(?:milisegundos?|ms|segundos?|s)\b', text)
    ):
        result['execution.wait'] = ('milliseconds',)
    pending = re.search(r'\b(?:no\s+(?:tengo|se|conozco)|pendiente\w*|despues|luego|todavia)\b', text)
    if pending is None:
        return result
    if re.search(r'\b(?:rutas?|origen|destino)\b', text) and not re.search(r'\b[A-Za-z]:[/\\]', message):
        for action_id in ('file.copy', 'file.move', 'folder.copy', 'folder.move'):
            result[action_id] = ('source', 'destination')
    if re.search(r'\b(?:coordenadas?|posicion|ubicacion)\b', text) and not re.search(r'\b(?:detect\w*|bus[qc]\w*|encontr\w*|encuentr\w*|locali[cz]\w*|ocr)\b', text):
        for action_id in ('mouse.click', 'mouse.doubleClick', 'mouse.move'):
            result[action_id] = ('x', 'y')
    if re.search(r'\bno\s+(?:te\s+)?(?:paso|doy|indico|tengo)\b.{0,50}\b(?:usuario|texto)\b', text):
        result['keyboard.write'] = ('text',)
    return result


def _validate_explicit_pending_fields(bot: dict[str, Any], message: str) -> None:
    forced = _explicit_pending_fields(message)
    for node in bot['flow']['nodes']:
        for field in forced.get(node['type'], ()):
            if not is_pending_parameter(node['params'].get(field)):
                raise ProposalValidationError(
                    'explicitly unavailable parameter was filled with a guess',
                    repair_details=[f'El usuario dijo que no conoce {field}. Deja {node["type"]}.{field} exactamente como {{"$pending":true}} para completarlo luego en el editor.'],
                )


def _validate_copy_without_move(bot: dict[str, Any], message: str) -> None:
    """A copy that preserves its source must not acquire a destructive move."""
    if _copy_only_intent(message):
        action_ids = [node['type'] for node in bot['flow']['nodes']]
        if action_ids != ['file.copy']:
            raise ProposalValidationError(
                'simple copy request acquired unrequested actions',
                repair_details=['Este pedido requiere exactamente un bloque Copiar archivo. Quitá apertura de carpeta, portapapeles, movimiento, comentario y Detener: no fueron pedidos ni son necesarios.'],
            )
        return
    requested = _clean_home_intent_text(message)
    copy_only = re.search(r'\bcopiar\s+(?:un\s+|el\s+)?archivo\b', requested) and re.search(
        r'\b(?:sin\s+(?:borrar|eliminar)|conserv\w*\s+(?:el\s+)?original)\b', requested,
    )
    if not copy_only:
        return
    if re.search(r'\b(?:tambien|ademas|y)\s+(?:quiero\s+|necesito\s+)?mover\b', requested):
        return
    extra = {node['type'] for node in bot['flow']['nodes']} & {
        'file.move', 'folder.move', 'file.delete', 'folder.delete', 'flow.comment',
    }
    if extra:
        raise ProposalValidationError(
            'copy request acquired unrequested actions',
            repair_details=[
                'El usuario pidió copiar el archivo conservando el original. El flujo debe contener Copiar archivo; '
                'quita Mover archivo, eliminar y comentarios no pedidos. No conviertas una comparación de la respuesta anterior en pasos ejecutables.'
            ],
        )


def _copy_only_intent(message: str) -> bool:
    requested = _clean_home_intent_text(message)
    return bool(
        re.search(r'\bcopiar\s+(?:un\s+|el\s+)?archivo\b', requested)
        and re.search(r'\b(?:sin\s+(?:borrar|eliminar)|conserv\w*\s+(?:el\s+)?original)\b', requested)
        and not re.search(
            r'\b(?:tambien|ademas|y)\s+(?:quiero\s+|necesito\s+)?(?:mover|abrir|escribir|leer|guardar|descargar|avisar)\b',
            requested,
        )
    )


def _provided_rename_destination(source: str, destination: str, request: ChatRequest) -> bool:
    """A provided source plus a requested basename authorizes a same-folder rename."""
    original, result = PureWindowsPath(source), PureWindowsPath(destination)
    if original.parent != result.parent:
        return False
    boundary = r'(?=$|[\s\"\'`,;).!?])'
    source_pattern = re.escape(source.replace('\\', '/').casefold()) + boundary
    name_pattern = r'\b(?:a|como|por)\s+[\"\'`]?' + re.escape(result.name.casefold()) + boundary
    for message in request.messages:
        if message.role != 'user':
            continue
        text = message.content.replace('\\', '/').casefold()
        for verb in re.finditer(r'\b(?:renombr\w*|cambi\w*\s+(?:el\s+)?nombre)\b', text):
            if re.search(r'\b(?:no|sin)\s+(?:\w+\s+){0,2}$', text[max(0, verb.start()-40):verb.start()]):
                continue
            clause = text[verb.end():verb.end()+400].split('\n', 1)[0]
            provided = re.search(source_pattern, clause)
            if provided and re.match(r'\s*'+name_pattern, clause[provided.end():]):
                return True
    return False


def _provided_child_path(value: str, request: ChatRequest) -> bool:
    """Allow a basename explicitly placed inside a supplied directory, not guessed paths."""
    result = PureWindowsPath(value)
    parent = str(result.parent).replace('\\', '/').casefold()
    name = result.name.casefold()
    boundary = r'(?=$|[\s\"\'`,;).!?])'
    for message in request.messages:
        if message.role != 'user':
            continue
        text = _clean_home_intent_text(message.content.replace('\\', '/'))
        pattern = (re.escape(parent) + boundary + r'[^\n.!?]{0,120}?'
                   + r'\b(?:alli|ahi|dentro|en esa carpeta|en la misma carpeta)\b'
                   + r'[^\n.!?]{0,60}?\b' + re.escape(name) + boundary)
        if re.search(pattern, text):
            return True
    return False


def _validate_home_paths(bot: dict[str, Any], request: ChatRequest) -> None:
    """A generated draft must not substitute absolute paths from training examples."""
    evidence = '\n'.join(message.content for message in request.messages if message.role == 'user')
    evidence = evidence.replace('\\', '/').casefold()
    for node in bot['flow']['nodes']:
        for field in ('path', 'source', 'destination'):
            value = node['params'].get(field)
            if not isinstance(value, str) or not re.match(r'^(?:[a-zA-Z]:[\\/]|\\\\)', value):
                continue
            normalized = value.replace('\\', '/').casefold()
            if re.search(re.escape(normalized) + r'(?=$|[\s\"\'`,;).!?])', evidence):
                continue
            if _provided_child_path(value, request):
                continue
            # A trailing directory separator does not designate a different
            # folder. Preserve the generated value; only compare provenance.
            if node['type'].startswith('folder.') and len(normalized.rstrip('/')) > 2:
                folder = normalized.rstrip('/')
                if re.search(re.escape(folder) + r'/?(?=$|[\s"\'\x60,;).!?])', evidence):
                    continue
            if field == 'destination' and node['type'] in {'file.rename', 'folder.rename'}:
                source = node['params'].get('source')
                if isinstance(source, str) and _provided_rename_destination(source, value, request):
                    continue
            raise ProposalValidationError(
                'home draft contains an absolute path without user provenance',
                repair_details=[
                    f'El parametro {field} de {node["type"]} contiene una ruta que el usuario no proporciono. '
                    'Conserva exactamente las rutas indicadas en los mensajes del usuario. '
                    'Si falta una ruta, usa {"$pending":true}; no reutilices rutas de ejemplos ni del entrenamiento.'
                ],
            )


def _validate_vision_click_flow(bot: dict[str, Any], message: str) -> None:
    """Protect an explicit detect-and-click request from a partial valid flow."""
    requested = _clean_home_intent_text(message)
    if not (
        re.search(r'\b(?:detect\w*|busc\w*|busqu\w*|encuentr\w*|localiz\w*|ocr)\b', requested)
        and re.search(r'\b(?:clic\w*|click\w*)\b', requested)
    ):
        return
    if re.search(r'\bno\s+(?:hagas?|hacer|agregues?)\s+(?:un\s+)?(?:clic|click)\b', requested):
        return
    nodes = bot['flow']['nodes']
    detectors = [node for node in nodes if node['type'] == 'vision.detectElement']
    clicks = [node for node in nodes if node['type'] == 'mouse.click']
    if not detectors or not clicks:
        raise ProposalValidationError(
            'requested detection and click are not both present',
            repair_details=[
                'El usuario pidio detectar texto y hacer clic. Incluye vision.detectElement y despues mouse.click; detectar por si solo no hace clic.'
            ],
        )
    root = bot['flow'].get('root', [])
    if all(node['id'] in root for node in (detectors[0], clicks[0])) and root.index(clicks[0]['id']) < root.index(detectors[0]['id']):
        raise ProposalValidationError(
            'requested click appears before detection',
            repair_details=['Coloca Detectar elemento antes del clic que usa sus coordenadas.'],
        )
    if 'centro' in requested:
        outputs = [node['params'].get('outputVariable') for node in detectors]
        if not any(
            isinstance(name, str)
            and click['params'].get('x') == '{{' + name + '_centroX}}'
            and click['params'].get('y') == '{{' + name + '_centroY}}'
            for name in outputs for click in clicks
        ):
            raise ProposalValidationError(
                'requested click does not use detected center coordinates',
                repair_details=[
                    'Usa en mouse.click las variables derivadas del outputVariable de vision.detectElement: x="{{nombre_centroX}}", y="{{nombre_centroY}}".'
                ],
            )


def _validate_web_click_wait(bot: dict[str, Any], message: str) -> None:
    """Keep an explicitly requested web wait between navigation and click."""
    requested = _clean_home_intent_text(message)
    nodes = bot['flow']['nodes']
    browsers = [node for node in nodes if node['type'] == 'browser.open']
    clicks = [node for node in nodes if node['type'] == 'mouse.click']
    loading_wait = bool(
        re.search(r'\b(?:cargue|carga|cargar)\b', requested)
        and re.search(r'\b(?:clic|click)\b', requested)
        and re.search(r'\b(?:https|pagina|web|navegador)\b', requested)
        and 'ventana' not in requested
    )
    before_click = re.search(r'\bantes\s+del?\s+(?:clic|click)\b', requested) is not None
    if not loading_wait and not before_click:
        return
    if not browsers or not clicks:
        raise ProposalValidationError('web click request omitted an action', repair_details=[
            'El pedido de abrir una página y hacer clic necesita Abrir URL, Esperar y Click, en ese orden. No omitas el clic ni la espera por faltar datos: dejalos pendientes.',
        ])
    if loading_wait and any(node['type'] == 'window.wait' for node in nodes):
        raise ProposalValidationError(
            'window wait was substituted for page load wait',
            repair_details=['Para esperar despues de abrir una pagina usa execution.wait, no window.wait. No inventes un titulo de ventana.'],
        )
    waits = [node for node in nodes if node['type'] == 'execution.wait']
    root = bot['flow'].get('root', [])
    if all(node['id'] in root for node in (browsers[0], clicks[0])):
        waits = [node for node in waits if node['id'] in root and root.index(browsers[0]['id']) < root.index(node['id']) < root.index(clicks[0]['id'])]
    duration = re.search(r'\b(\d+)\s*(milisegundos?|ms|segundos?|s)\b', requested)
    if duration is not None:
        expected = int(duration.group(1)) * (1 if duration.group(2).startswith(('mili', 'ms')) else 1000)
        if any(node['params'].get('milliseconds') == expected for node in waits):
            return
        raise ProposalValidationError(
            'requested wait duration or placement is missing',
            repair_details=[f'Agrega una espera de {expected} milisegundos despues de abrir la pagina y antes del clic; conserva los demas pasos.'],
        )
    if loading_wait and not any(is_pending_parameter(node['params'].get('milliseconds')) for node in waits):
        raise ProposalValidationError(
            'page load wait is missing or guessed',
            repair_details=['Incluye execution.wait despues de browser.open y antes de mouse.click con milliseconds={"$pending":true}, porque el usuario no indico una duracion.'],
        )


def _validate_web_vision_click_intent(bot: dict[str, Any], message: str) -> None:
    """Keep a bounded web text-click flow faithful to the user's supplied data."""
    intent = web_vision_click_intent(message)
    if intent is None:
        return
    flow = bot['flow']
    by_id = {node['id']: node for node in flow['nodes']}
    expected = ['browser.open', 'execution.wait', 'vision.detectElement', 'mouse.click']
    if len(by_id) != 4 or [by_id[node_id]['type'] for node_id in flow['root']] != expected:
        raise ProposalValidationError(
            'web text-click flow has missing or extra steps',
            repair_details=['Usa exactamente Abrir URL, Esperar, Detectar elemento y Click, en ese orden. No agregues una espera después del clic.'],
        )
    browser, wait, detector, click = (by_id[node_id] for node_id in flow['root'])
    if browser['params'].get('url') != intent.url or detector['params'].get('text') != intent.target_text:
        raise ProposalValidationError(
            'web text-click flow changed user-supplied address or target',
            repair_details=[f'Conserva la dirección exacta {intent.url} y el texto a detectar {intent.target_text!r}. No uses una variable para una URL que el usuario ya indicó.'],
        )
    duration = wait['params'].get('milliseconds')
    if (intent.wait_milliseconds is None and not is_pending_parameter(duration)) or (
        intent.wait_milliseconds is not None and duration != intent.wait_milliseconds
    ):
        raise ProposalValidationError(
            'web loading wait changed the requested duration',
            repair_details=['Dejá la duración de la espera pendiente si el usuario no indicó segundos; si indicó un tiempo, usa ese valor exacto.'],
        )
    output = detector['params'].get('outputVariable')
    if not isinstance(output, str) or (
        click['params'].get('x') != '{{' + output + '_centroX}}'
        or click['params'].get('y') != '{{' + output + '_centroY}}'
    ):
        raise ProposalValidationError(
            'web click is not linked to the detected button',
            repair_details=['El clic debe usar el centro detectado: x="{{variable_centroX}}" e y="{{variable_centroY}}", con el nombre elegido en outputVariable.'],
        )


def _validate_requested_control_flow(bot: dict[str, Any], message: str) -> None:
    """Reject missing requested control structures, without constructing them."""
    text = _clean_home_intent_text(message)
    nodes = bot['flow']['nodes']
    actions = {node['type'] for node in nodes}
    handles_failure = re.search(r'\b(?:si|cuando)\b.{0,90}\b(?:falla|fallara|error)\b', text)
    recovery = [node for node in nodes if node['type'] == 'flow.tryCatch'
                and node.get('slots', {}).get('try') and node.get('slots', {}).get('catch')]
    if handles_failure and not recovery:
        raise ProposalValidationError('requested error handling has no recovery container', repair_details=[
            'La accion que puede fallar va dentro de try de Intentar y recuperar. La respuesta al error va en catch, no como un paso que se ejecuta siempre.',
        ])
    if re.search(r'\bsi\b', text) and re.search(r'\b(?:en caso contrario|si no|sino)\b', text) and 'flow.if' not in actions:
        raise ProposalValidationError('requested alternatives have no condition', repair_details=[
            'Incluye Si con la comparacion pedida; coloca una alternativa en then y la otra en else. No ejecutes ambas en secuencia.',
        ])


def _validate_explicit_repeat_count(bot: dict[str, Any], message: str) -> None:
    """Check a single explicit repetition count without rewriting model output.

    More complex/nested or dynamic counts require a different semantic analysis;
    do not guess which loop a number belongs to in those cases.
    """
    numbers = dict(zip(('uno', 'dos', 'tres', 'cuatro', 'cinco', 'seis', 'siete', 'ocho', 'nueve', 'diez'), range(1, 11)))
    numbers['una'] = 1
    counts = re.findall(r'\b(\d+|' + '|'.join(numbers) + r')\s+(?:vez|veces|vueltas|time|times)\b', _clean_home_intent_text(message))
    counts = [str(numbers.get(value, value)) for value in counts]
    loops = [node for node in bot['flow']['nodes'] if node['type'] in {'flow.forRange', 'flow.forEach', 'flow.while'}]
    if len(counts) != 1 or len(counts[0]) > 16:
        return
    if not loops and int(counts[0]) > 1:
        raise ProposalValidationError(
            'explicit repetition is missing from the proposed flow',
            repair_details=['El usuario pidio repetir una secuencia. Incluye el bucle y coloca todos los pasos repetidos dentro de su slot body.'],
        )
    if len(loops) != 1 or loops[0]['type'] != 'flow.forRange':
        return
    params = loops[0]['params']
    start, end, step = (params.get(key) for key in ('start', 'end', 'step'))
    if not all(type(value) is int for value in (start, end, step)) or step == 0:
        return
    # Match the executor's empty 0..0 range; integer arithmetic also avoids
    # overflowing len(range(...)) for otherwise representable JSON integers.
    actual = 0 if start == end == 0 or (end - start) * step < 0 else abs(end - start) // abs(step) + 1
    requested = int(counts[0])
    errors = []
    limit = params.get('maxIterations', 1000)
    if type(limit) is int and limit < requested:
        errors.append(f'maxIterations={limit} impide completar las {requested} repeticiones pedidas. Aumenta ese limite sin cambiar el texto ni las pausas.')
    if actual != requested:
        errors.append(
            f'El rango propuesto ejecuta {actual} iteraciones, pero el usuario pidio {requested}. '
            'Corrige start, end y step: el rango es inclusivo. maxIterations es un limite de seguridad, no la cantidad de repeticiones.'
        )
    simple = re.search(r'\brepita\s+\d+\s+veces\s*:\s*escribir\s+exactamente\s+(.+?)\s+y\s+esperar\s+(\d+)\s+milisegundos\b', _clean_home_intent_text(message))
    if simple is not None and 'no agregues otros pasos' in _clean_home_intent_text(message):
        by_id = {node['id']: node for node in bot['flow']['nodes']}
        body = [by_id[identity] for identity in loops[0].get('slots', {}).get('body', [])]
        expected = [node['type'] for node in body] == ['keyboard.write', 'execution.wait']
        expected = expected and body[0]['params'].get('text', '').casefold() == simple.group(1)
        expected = expected and body[1]['params'].get('milliseconds') == int(simple.group(2))
        if bot['flow']['root'] != [loops[0]['id']] or not expected or len(bot['flow']['nodes']) != 3:
            errors.append('Coloca Escribir texto y Esperar solamente dentro de un único Repetir rango; no agregues pasos antes ni después.')
    if errors:
        raise ProposalValidationError(
            'loop count does not match explicit request',
            repair_details=errors,
        )


def extract_json_payload(content: str) -> str:
    """Extract clean JSON from model output, handling think tags, markdown blocks, and surrounding whitespace."""
    text = content.strip()
    if "<think>" in text and "</think>" in text:
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    elif "</think>" in text:
        text = text.split("</think>", 1)[1].strip()

    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text)
    if match:
        candidate = match.group(1).strip()
        if candidate.startswith("{") and candidate.endswith("}"):
            return candidate

    start = text.find("{")
    if start != -1:
        candidate = text[start:]
        end = candidate.rfind("}")
        if end != -1:
            candidate_sub = candidate[: end + 1]
            try:
                json.loads(candidate_sub)
                return candidate_sub
            except Exception:
                pass
    return text


def parse_home_bot_draft(
    content: str, chat_request: ChatRequest
) -> HomeBotDraft | AgentClarification | AgentAnswer:
    cleaned = extract_json_payload(content)
    if len(cleaned) > MAX_GENERATION_CODE_POINTS or len(cleaned.encode("utf-8")) > MAX_GENERATION_BYTES:
        raise ProposalValidationError("home draft exceeds generation limits")
    try:
        raw = json.loads(
            cleaned,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
        validate_json_tree(raw, DEFAULT_MAX_JSON_DEPTH)
    except (ValueError, RecursionError) as error:
        raise ProposalValidationError(
            "home draft is not valid bounded JSON",
            repair_details=["Genera un objeto JSON completo, sin omitir pasos del pedido."],
        ) from error

    if not isinstance(raw, dict):
        raise ProposalValidationError("home draft must be a JSON object")

    kind = raw.get("kind")
    if kind == "clarification":
        message = raw.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ProposalValidationError("clarification message must not be blank")
        return AgentClarification(kind="clarification", message=message.strip())
    if kind == "answer":
        message = raw.get("message")
        if not isinstance(message, str) or not message.strip():
            raise ProposalValidationError("answer message must not be blank")
        return AgentAnswer(kind="answer", message=message.strip())

    return validate_home_bot_draft(raw, chat_request)


@dataclass(frozen=True)
class ReplacementNode:
    type: str
    params: dict[str, JsonValue]
    slots: dict[str, tuple["ReplacementNode", ...]]


@dataclass(frozen=True)
class ModelReplacementProposal:
    summary: str
    replacement: tuple[ReplacementNode, ...]


ModelReplacementTurn = AgentAnswer | AgentClarification | ModelReplacementProposal


def full_replacement_intent(request: ChatRequest) -> bool:
    return False


def replacement_turn_schema(request: ChatRequest) -> dict[str, object]:
    node_variants = [
        _replacement_action_schema(action)
        for action in request.capabilities.actions
        if action.id != "flow.goTo"
    ]
    if not node_variants:
        raise ProposalValidationError("no actions are representable as a replacement tree")
    schema: dict[str, object] = {
        "$defs": {
            "ReplacementNode": {
                "oneOf": node_variants,
                "description": (
                    "A desired AutoClick node. Nest children only under the exact "
                    "slot keys declared by this action."
                ),
            }
        },
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "answer"},
                    "message": {"type": "string", "minLength": 1},
                },
                "required": ["kind", "message"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "clarification"},
                    "message": {"type": "string", "minLength": 1},
                },
                "required": ["kind", "message"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "proposal"},
                    "summary": {"type": "string", "minLength": 1},
                    "replacement": {
                        "type": "array",
                        "minItems": 1,
                        "maxItems": MAX_PROPOSAL_OPERATIONS,
                        "items": {"$ref": "#/$defs/ReplacementNode"},
                        "description": "The complete desired ordered root sequence.",
                    },
                },
                "required": ["kind", "summary", "replacement"],
                "additionalProperties": False,
            },
        ],
    }
    return _ollama_compatible_schema(schema)


def _replacement_action_schema(action: ActionDefinition) -> dict[str, object]:
    params_properties = {
        field.name: _field_json_schema(field)
        for field in (action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', []))
    }
    required_params = [
        field.name
        for field in (action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', []))
        if field.required and field.name not in (action.get('defaults', {}) if isinstance(action, dict) else getattr(action, 'defaults', {}))
    ]
    slots_properties = {
        slot: {
            "type": "array",
            "maxItems": MAX_PROPOSAL_OPERATIONS,
            "items": {"$ref": "#/$defs/ReplacementNode"},
        }
        for slot in (action.get('slots', []) if isinstance(action, dict) else getattr(action, 'slots', []))
    }
    params: dict[str, object] = {
        "type": "object",
        "properties": params_properties,
        "additionalProperties": False,
        "description": (
            f"Parameters for {action.id}. Omitted fields may use catalog defaults; "
            "do not add fields from another action."
        ),
    }
    if required_params:
        params["required"] = required_params
    return {
        "type": "object",
        "properties": {
            "type": {"const": action.id},
            "params": params,
            "slots": {
                "type": "object",
                "properties": slots_properties,
                "required": list((action.get('slots', []) if isinstance(action, dict) else getattr(action, 'slots', []))),
                "additionalProperties": False,
                "description": (
                    "Exactly the declared child slots. Use an empty object for a "
                    "slot-less action."
                ),
            },
        },
        "required": ["type", "params", "slots"],
        "additionalProperties": False,
    }


def _field_json_schema(field: ActionFieldDefinition) -> dict[str, object]:
    if field.type in ("integer", "number"):
        primitive_type = "integer" if field.type == "integer" else "number"
        prim_schema: dict[str, object] = {"type": primitive_type}
        if field.min is not None:
            prim_schema["minimum"] = int(field.min) if field.type == "integer" else field.min
        if field.max is not None:
            prim_schema["maximum"] = int(field.max) if field.type == "integer" else field.max
        schema: dict[str, object] = {
            "anyOf": [
                prim_schema,
                {"type": "string", "pattern": r"^\{\{[A-Za-z_][A-Za-z0-9_]*\}\}$"}
            ]
        }
    elif field.type == "boolean":
        schema = {"type": "boolean"}
    elif field.type == "select":
        schema = {"type": "string", "enum": list(field.options or [])}
    elif field.type == "condition":
        schema = {
            "type": "object",
            "properties": {
                "combinator": {"type": "string", "enum": ["all", "any"]},
                "clauses": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "type": "object",
                        "properties": {
                            "left": {
                                "type": ["string", "number", "boolean", "null", "array"],
                                "description": (
                                    "Left operand. For a prior action output, use its "
                                    "runtime variable exactly as {{variableName}}."
                                )
                            },
                            "operator": {
                                "type": "string",
                                "enum": [
                                    "eq", "ne", "lt", "lte", "gt", "gte",
                                    "contains", "startsWith", "endsWith", "in",
                                    "empty", "notEmpty",
                                ],
                                "description": (
                                    "Use lt for strict menor a, lte for menor o igual, "
                                    "gt for strict mayor a, and gte for mayor o igual."
                                ),
                            },
                            "right": {
                                "type": ["string", "number", "boolean", "null", "array"],
                                "description": (
                                    "Right operand. A numeric comparison threshold must "
                                    "be a JSON number, never numeric text."
                                )
                            },
                        },
                        "required": ["left", "operator"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["combinator", "clauses"],
            "additionalProperties": False,
        }
    elif field.type == "json":
        schema = {}
    else:
        schema = {"type": "string"}
    if field.min is not None:
        schema["minimum"] = int(field.min) if field.type == "integer" else field.min
    if field.max is not None:
        schema["maximum"] = int(field.max) if field.type == "integer" else field.max
    if field.min_length is not None:
        schema["minLength"] = field.min_length
    if field.max_length is not None:
        schema["maxLength"] = field.max_length
    if field.pattern is not None:
        schema["pattern"] = field.pattern
    schema["description"] = f"{field.label} ({field.name})."
    if allows_pending_parameter(field.type, field.name):
        schema = {"anyOf": [schema, {
            "type": "object", "properties": {"$pending": {"const": True}},
            "required": ["$pending"], "additionalProperties": False,
        }], "description": f"{field.label}. Usa {{\"$pending\":true}} si falta este dato en un borrador; no lo inventes."}
    if not field.required:
        return {"anyOf": [schema, {"type": "null"}]}
    return schema


def parse_replacement_turn(
    content: str,
    request: ChatRequest,
    *,
    max_depth: int = DEFAULT_MAX_JSON_DEPTH,
) -> ModelReplacementTurn:
    if (
        len(content) > MAX_GENERATION_CODE_POINTS
        or len(content.encode("utf-8")) > MAX_GENERATION_BYTES
    ):
        raise _replacement_tree_error()
    try:
        raw = json.loads(
            content,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
        validate_json_tree(raw, max_depth)
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise ProposalValidationError(
            "replacement output is not valid bounded JSON",
            repair_details=["Return one complete result matching the replacement tree schema."],
        ) from error
    if not isinstance(raw, dict):
        raise _replacement_tree_error()
    kind = raw.get("kind")
    if kind == "answer":
        return AgentAnswer.model_validate(raw)
    if kind == "clarification":
        return AgentClarification.model_validate(raw)
    if kind != "proposal" or set(raw) != {"kind", "summary", "replacement"}:
        raise _replacement_tree_error()
    summary = raw["summary"]
    if not isinstance(summary, str):
        raise _replacement_tree_error()
    replacement = raw["replacement"]
    if not isinstance(replacement, list) or not replacement:
        raise _replacement_tree_error()
    actions = {
        action.id: action
        for action in request.capabilities.actions
        if action.id != "flow.goTo"
    }
    count = [0]
    nodes = tuple(
        _parse_replacement_node(item, actions, count=count, depth=1)
        for item in replacement
    )
    return ModelReplacementProposal(summary, nodes)


def _parse_replacement_node(
    raw: object,
    actions: dict[str, ActionDefinition],
    *,
    count: list[int],
    depth: int,
) -> ReplacementNode:
    if depth > DEFAULT_MAX_JSON_DEPTH or count[0] >= CANONICAL_MAX_BOT_NODES:
        raise _replacement_tree_error()
    count[0] += 1
    if not isinstance(raw, dict) or set(raw) != {"type", "params", "slots"}:
        raise _replacement_tree_error()
    action_type, params, raw_slots = raw["type"], raw["params"], raw["slots"]
    action = actions.get(action_type) if isinstance(action_type, str) else None
    if action is None or not isinstance(params, dict) or not isinstance(raw_slots, dict):
        raise _replacement_tree_error()
    action_slots = getattr(action, 'slots', None) if not isinstance(action, dict) else action.get('slots', [])
    if set(raw_slots) != set(action_slots) or any(
        not isinstance(children, list) for children in raw_slots.values()
    ):
        raise _replacement_tree_error()
    try:
        _validate_params(params, action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', []), action.get('defaults', {}) if isinstance(action, dict) else getattr(action, 'defaults', {}))
    except ProposalValidationError as error:
        raise _replacement_tree_error() from error
    slots = {
        slot: tuple(
            _parse_replacement_node(child, actions, count=count, depth=depth + 1)
            for child in raw_slots[slot]
        )
        for slot in (action.get('slots', []) if isinstance(action, dict) else getattr(action, 'slots', []))
    }
    return ReplacementNode(action_type, copy.deepcopy(params), slots)


def _replacement_tree_error() -> "ProposalValidationError":
    return ProposalValidationError(
        "replacement tree does not match the capability schema",
        repair_details=[
            "Return a complete ordered root tree using only catalog action types, "
            "their exact parameter fields, and their exact declared slot keys."
        ],
    )


def lower_replacement_tree(
    outcome: ModelReplacementProposal,
    request: ChatRequest,
) -> AgentProposalArguments:
    context = request.editor_context
    if context is None:
        raise ProposalValidationError("replacement requires editor context")
    baseline = context.working_bot if context.working_bot is not None else context.bot
    flow = baseline.get("flow")
    if not isinstance(flow, dict):
        raise ProposalValidationError("the baseline flow is invalid")
    roots, raw_nodes = flow.get("root"), flow.get("nodes")
    if not isinstance(roots, list) or not isinstance(raw_nodes, list):
        raise ProposalValidationError("the baseline must contain a tree flow")
    nodes_by_id = {
        node.get("id"): node
        for node in raw_nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    if len(nodes_by_id) != len(raw_nodes) or not all(
        isinstance(node_id, str) for node_id in roots
    ):
        raise ProposalValidationError("the baseline contains an invalid node")

    removal_ids: list[str] = []
    visited: set[str] = set()

    def collect_removals(node_id: str) -> None:
        if node_id in visited or node_id not in nodes_by_id:
            raise ProposalValidationError("the baseline contains an invalid node placement")
        visited.add(node_id)
        raw_slots = nodes_by_id[node_id].get("slots", {})
        if not isinstance(raw_slots, dict):
            raise ProposalValidationError("the baseline contains an invalid node")
        for children in raw_slots.values():
            if not isinstance(children, list) or not all(isinstance(child, str) for child in children):
                raise ProposalValidationError("the baseline contains an invalid node")
            for child in children:
                collect_removals(child)
        removal_ids.append(node_id)

    for root in roots:
        collect_removals(root)
    if visited != set(nodes_by_id):
        raise ProposalValidationError("every node must be placed exactly once")

    operations: list[dict[str, object]] = [
        {"op": "removeNode", "nodeId": node_id}
        for node_id in removal_ids
    ]
    unavailable_ids = set(nodes_by_id)
    next_counter = 1

    def add_sequence(
        sequence: tuple[ReplacementNode, ...], parent_id: str | None, slot: str
    ) -> None:
        nonlocal next_counter
        for index, node in enumerate(sequence):
            while f"node-{next_counter}" in unavailable_ids:
                next_counter += 1
            node_id = f"node-{next_counter}"
            next_counter += 1
            unavailable_ids.add(node_id)
            operations.append(
                {
                    "op": "addNode",
                    "node": {
                        "id": node_id,
                        "type": node.type,
                        "params": copy.deepcopy(node.params),
                    },
                    "location": {
                        "parentId": parent_id,
                        "slot": slot,
                        "index": index,
                    },
                }
            )
            for child_slot, children in node.slots.items():
                add_sequence(children, node_id, child_slot)

    add_sequence(outcome.replacement, None, "root")
    if len(operations) > MAX_PROPOSAL_OPERATIONS:
        raise ProposalValidationError("replacement exceeds the operation limit")
    return AgentProposalArguments.model_validate(
        {
            "summary": outcome.summary,
            "operations": operations,
        }
    )



class EditorAnswer(_AgentProtocolModel):
    kind: Literal["answer"]
    message: StrictStr = Field(min_length=1, max_length=64_000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


class EditorClarification(_AgentProtocolModel):
    kind: Literal["clarification"]
    message: StrictStr = Field(min_length=1, max_length=64_000)

    @field_validator("message")
    @classmethod
    def reject_blank_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value


@dataclass(frozen=True)
class UpdatedFlowNode:
    id: str | None
    type: str
    params: dict[str, JsonValue]
    slots: dict[str, tuple["UpdatedFlowNode", ...]]


@dataclass(frozen=True)
class EditorUpdatedFlow:
    kind: Literal["updatedFlow"]
    summary: str
    name: str
    description: str
    flow: tuple[UpdatedFlowNode, ...]


EditorTurn = EditorAnswer | EditorClarification | EditorUpdatedFlow


@dataclass(frozen=True)
class ValidatedUpdatedBot:
    bot: dict[str, JsonValue]
    node_count: int
    matched_baseline_ids: frozenset[str]


@dataclass(frozen=True)
class DerivedProposal:
    summary: str
    operations: tuple[object, ...]
    resulting_bot: dict[str, JsonValue]
    baseline_bot_revision: str


def editor_turn_schema(request: ChatRequest) -> dict[str, object]:
    node_variants = [
        _updated_flow_action_schema(action)
        for action in _canonical_action_definitions()
    ]
    if not node_variants:
        raise ProposalValidationError("no actions are representable in updatedFlow")
    schema: dict[str, object] = {
        "$defs": {
            "UpdatedFlowNode": {
                "oneOf": node_variants,
                "description": (
                    "A desired AutoClick node. Nest children only under the exact "
                    "slot keys declared by this action."
                ),
            }
        },
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "updatedFlow"},
                    "summary": {"type": "string", "minLength": 1, "maxLength": 1000},
                    "name": {"type": "string", "minLength": 1, "maxLength": 120},
                    "description": {"type": "string", "maxLength": 500},
                    "flow": {
                        "type": "array",
                        "minItems": 0,
                        "maxItems": CANONICAL_MAX_BOT_NODES,
                        "items": {"$ref": "#/$defs/UpdatedFlowNode"},
                    },
                },
                "required": ["kind", "summary", "name", "description", "flow"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "answer"},
                    "message": {"type": "string", "minLength": 1, "maxLength": 64000},
                },
                "required": ["kind", "message"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "kind": {"const": "clarification"},
                    "message": {"type": "string", "minLength": 1, "maxLength": 64000},
                },
                "required": ["kind", "message"],
                "additionalProperties": False,
            },
        ],
    }
    if classify_editor_intent(request.messages[-1].content) == "informational":
        # Do not ask a small model to choose between editing and answering when
        # the current turn explicitly requests information or denies changes.
        schema = {"oneOf": [schema["oneOf"][1]]}
    return _ollama_compatible_schema(schema)


def _updated_flow_action_schema(action: ActionDefinition) -> dict[str, object]:
    params_properties = {
        field.name: _field_json_schema(field)
        for field in (action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', []))
    }
    required_params = [
        field.name
        for field in (action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', []))
        if field.required
    ]
    # Coordinates without defaults must be explicit in generated flows: null
    # means the current cursor, whereas $pending means an unfinished target.
    if action.category == "mouse":
        required_params.extend(
            field.name for field in action.fields
            if field.name in {"x", "y"} and field.name not in required_params
        )
    slots_properties = {
        slot: {
            "type": "array",
            "maxItems": CANONICAL_MAX_BOT_NODES,
            "items": {"$ref": "#/$defs/UpdatedFlowNode"},
        }
        for slot in (action.get('slots', []) if isinstance(action, dict) else getattr(action, 'slots', []))
    }
    params: dict[str, object] = {
        "type": "object",
        "properties": params_properties,
        "additionalProperties": False,
        "description": (
            f"Parameters for {action.id}. Omitted fields may use catalog defaults; "
            "do not add fields from another action."
        ),
    }
    if required_params:
        params["required"] = required_params
    return {
        "type": "object",
        "properties": {
            "id": {
                "anyOf": [
                    {"type": "string", "minLength": 1, "maxLength": 200},
                    {"type": "null"},
                ]
            },
            "type": {"const": action.id},
            "params": params,
            "slots": {
                "type": "object",
                "properties": slots_properties,
                "required": list((action.get('slots', []) if isinstance(action, dict) else getattr(action, 'slots', []))),
                "additionalProperties": False,
                "description": (
                    "Exactly the declared child slots. Use an empty object for a "
                    "slot-less action."
                ),
            },
        },
        "required": ["type", "params", "slots"],
        "additionalProperties": False,
    }


_CANONICAL_ACTION_KEYS = {
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


def _canonical_action_definitions(
    snapshot: dict[str, Any] | None = None,
) -> list[ActionDefinition]:
    resolved = snapshot if snapshot is not None else mcp_catalog_snapshot()
    return [
        ActionDefinition.model_validate(
            {
                key: value
                for key, value in action.items()
                if key in _CANONICAL_ACTION_KEYS
            }
        )
        for action in resolved["actions"]
    ]


def _verified_canonical_actions(request: ChatRequest) -> dict[str, ActionDefinition]:
    snapshot = mcp_catalog_snapshot()
    canonical = _canonical_action_definitions(snapshot)
    capabilities = request.capabilities
    if (
        capabilities.catalog_version != snapshot["catalogVersion"]
        or capabilities.catalog_hash != snapshot["catalogHash"]
        or capabilities.actions != canonical
    ):
        raise ProposalValidationError("editor capabilities do not match the canonical MCP catalog")
    return {action.id: action for action in canonical}


def parse_editor_turn(
    content: str,
    request: ChatRequest,
    *,
    max_depth: int = DEFAULT_MAX_JSON_DEPTH,
) -> EditorTurn:
    cleaned = extract_json_payload(content)
    try:
        byte_length = len(cleaned.encode("utf-8"))
    except UnicodeEncodeError as error:
        raise ProposalValidationError("editor output is not valid Unicode") from error
    if len(cleaned) > MAX_GENERATION_CODE_POINTS or byte_length > MAX_GENERATION_BYTES:
        raise ProposalValidationError("editor generation exceeds length limits")
    
    try:
        raw = json.loads(
            cleaned,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
            object_pairs_hook=_reject_duplicate_json_keys,
        )
    except (json.JSONDecodeError, RecursionError, ValueError) as error:
        raise ProposalValidationError(
            "editor output is not valid bounded JSON",
            repair_details=["Return one complete result matching the editor schema."],
        ) from error

    try:
        validate_json_tree(raw, max_depth)
    except (RecursionError, ValueError) as error:
        raise ProposalValidationError("editor output is not valid bounded JSON") from error
    if not isinstance(raw, dict):
        raise ProposalValidationError("editor output must be a JSON object")
    kind = raw.get("kind")
    if kind == "answer":
        try:
            return EditorAnswer.model_validate(raw)
        except ValueError as error:
            raise ProposalValidationError("answer does not match the editor schema") from error
    if kind == "clarification":
        try:
            return EditorClarification.model_validate(raw)
        except ValueError as error:
            raise ProposalValidationError("clarification does not match the editor schema") from error
    if kind != "updatedFlow":
        raise ProposalValidationError("editor output kind must be answer, clarification, or updatedFlow")

    if set(raw) != {"kind", "summary", "name", "description", "flow"}:
        raise ProposalValidationError("updatedFlow does not match the editor schema")
    summary, name, description, flow_raw = (
        raw["summary"], raw["name"], raw["description"], raw["flow"]
    )
    if not isinstance(summary, str) or not summary.strip() or len(summary) > 1_000:
        raise ProposalValidationError("updatedFlow summary is invalid")
    if not isinstance(name, str) or not name.strip() or len(name) > 120:
        raise ProposalValidationError("updatedFlow name is invalid")
    if not isinstance(description, str) or len(description) > 500:
        raise ProposalValidationError("updatedFlow description is invalid")
    if not isinstance(flow_raw, list) or len(flow_raw) > CANONICAL_MAX_BOT_NODES:
        raise ProposalValidationError("updatedFlow flow is invalid")

    actions = _verified_canonical_actions(request)
    count = [0]
    nodes = tuple(
        _parse_updated_flow_node(
            item, actions, count=count, depth=1, max_depth=max_depth
        )
        for item in flow_raw
    )
    return EditorUpdatedFlow(kind="updatedFlow", summary=summary, name=name, description=description, flow=nodes)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _parse_updated_flow_node(
    raw: object,
    actions: dict[str, ActionDefinition],
    *,
    count: list[int],
    depth: int,
    max_depth: int,
) -> UpdatedFlowNode:
    if depth > max_depth or count[0] >= CANONICAL_MAX_BOT_NODES:
        raise ProposalValidationError("updatedFlow tree exceeds node or depth limit")
    count[0] += 1
    if not isinstance(raw, dict) or not set(raw).issubset({"id", "type", "params", "slots"}):
        raise ProposalValidationError("updatedFlow node must be a JSON object")
    if not {"type", "params", "slots"}.issubset(raw):
        raise ProposalValidationError("updatedFlow node requires type, params, and slots")

    node_id = raw.get("id")
    if node_id is not None and (
        not isinstance(node_id, str) or not node_id or len(node_id) > 200
    ):
        raise ProposalValidationError("updatedFlow node id is invalid")
    action_type = raw.get("type")
    action = actions.get(action_type) if isinstance(action_type, str) else None
    if action is None:
        raise ProposalValidationError(f"unknown or missing action type: {action_type}")
    
    params = raw["params"]
    if not isinstance(params, dict):
        raise ProposalValidationError("updatedFlow node params must be an object")

    raw_slots = raw["slots"]
    if not isinstance(raw_slots, dict):
        raise ProposalValidationError("updatedFlow node slots must be an object")

    action_slots = action.get("slots", []) if isinstance(action, dict) else getattr(action, "slots", [])
    action_fields = action.get("fields", []) if isinstance(action, dict) else getattr(action, "fields", [])
    action_defaults = action.get("defaults", {}) if isinstance(action, dict) else getattr(action, "defaults", {})
    
    _validate_params(params, action_fields, action_defaults)
    if set(raw_slots) != set(action_slots):
        raise ProposalValidationError("updatedFlow node slots do not match the action catalog")

    slots: dict[str, tuple[UpdatedFlowNode, ...]] = {}
    for slot in action_slots:
        raw_children = raw_slots[slot]
        if not isinstance(raw_children, list):
            raise ProposalValidationError("updatedFlow slot children must be a list")
        slots[slot] = tuple(
            _parse_updated_flow_node(
                child,
                actions,
                count=count,
                depth=depth + 1,
                max_depth=max_depth,
            )
            for child in raw_children
        )

    return UpdatedFlowNode(node_id, action_type, copy.deepcopy(params), slots)


class ProposalValidationError(ValueError):
    def __init__(
        self, message: str, *, repair_details: list[str] | None = None
    ) -> None:
        super().__init__(message)
        self.repair_details = repair_details or []


class ExternalFactValidationError(ProposalValidationError):
    def __init__(self, requirements: set[ExternalFactRequirement]) -> None:
        bounded = tuple(sorted(requirements, key=lambda item: item.key)[:20])
        labels = [requirement.label for requirement in bounded]
        super().__init__(
            "proposal contains external values without user provenance",
            repair_details=[
                "external values require explicit user provenance for fields: "
                + ", ".join(labels)
            ],
        )
        self.requirements = frozenset(bounded)


def validate_proposal_semantics(
    proposal: AgentProposalArguments, request: ChatRequest
) -> None:
    context = request.editor_context
    if context is None:
        raise ProposalValidationError("an editor context is required")
    original = context.bot
    baseline = context.working_bot if context.working_bot is not None else context.bot
    if original.get("id") != baseline.get("id"):
        raise ProposalValidationError("working bot must preserve the bot ID")
    if baseline.get("schemaVersion") != 2:
        raise ProposalValidationError("only canonical schema v2 bots are editable")
    flow = baseline.get("flow")
    if not isinstance(flow, dict):
        raise ProposalValidationError("the baseline flow is invalid")
    raw_root, raw_nodes = flow.get("root"), flow.get("nodes")
    if not isinstance(raw_root, list) or not isinstance(raw_nodes, list):
        raise ProposalValidationError("the baseline must contain a tree flow")

    actions = {action.id: action for action in request.capabilities.actions}
    root = copy.deepcopy(raw_root)
    if not all(isinstance(node_id, str) for node_id in root):
        raise ProposalValidationError("the baseline root is invalid")
    nodes: dict[str, dict[str, object]] = {}
    for raw_node in raw_nodes:
        if not isinstance(raw_node, dict):
            raise ProposalValidationError("the baseline contains an invalid node")
        node_id, action_type = raw_node.get("id"), raw_node.get("type")
        raw_slots = raw_node.get("slots", {})
        if (
            not isinstance(node_id, str)
            or not node_id
            or node_id in nodes
            or not isinstance(action_type, str)
            or not isinstance(raw_slots, dict)
            or any(
                not isinstance(slot, str)
                or not isinstance(children, list)
                or not all(isinstance(child, str) for child in children)
                for slot, children in raw_slots.items()
            )
        ):
            raise ProposalValidationError("the baseline contains an invalid node")
        nodes[node_id] = {
            "type": action_type,
            "slots": copy.deepcopy(raw_slots),
            "params": copy.deepcopy(raw_node.get("params", {})),
        }
    _validate_placements(root, nodes)
    baseline_ids = set(nodes)
    baseline_nodes = copy.deepcopy(nodes)
    result_nodes = _validate_resulting_bot(root, nodes, actions, proposal)
    from app.text_literals import requested_replacement_literals
    replacement_literals = requested_replacement_literals(request.messages[-1].content)
    if len(replacement_literals) == 1:
        changed_texts = [after['params'].get('text') for node_id, after in result_nodes.items()
            if node_id in baseline_nodes and after['type'] == baseline_nodes[node_id]['type'] == 'keyboard.write'
            and after['params'].get('text') != baseline_nodes[node_id]['params'].get('text')]
        if any(text != replacement_literals[0] for text in changed_texts):
            raise ProposalValidationError('requested replacement literal was altered',
                repair_details=['Conserva exactamente el texto entre comillas del ultimo pedido, sin abreviarlo, cambiar mayusculas ni agregar puntuacion.'])
    latest = _clean_home_intent_text(request.messages[-1].content)
    if re.search(r'\b(?:cambia|cambiar|modifica|modificar|reemplaza|reemplazar)\b.{0,80}\btexto\b', latest) and not re.search(r'\b(?:intervalo|velocidad|ritmo)\b', latest):
        replacement = re.search(r'\btexto\s+(\S+)\s+por\s+(\S+)', latest)
        for node_id in baseline_ids & set(result_nodes):
            before, after = baseline_nodes[node_id], result_nodes[node_id]
            if before['type'] != 'keyboard.write' or after['type'] != 'keyboard.write':
                continue
            previous = before['params'].get('intervalMs', actions['keyboard.write'].defaults.get('intervalMs'))
            current = after['params'].get('intervalMs', actions['keyboard.write'].defaults.get('intervalMs'))
            if previous != current:
                raise ProposalValidationError(
                    'text edit also changed typing interval',
                    repair_details=['El usuario pidio cambiar el texto, no el intervalo de escritura. Actualiza solo params.text y conserva intervalMs.'],
                )
            if replacement is not None and str(before['params'].get('text', '')).casefold() == replacement.group(1).rstrip(',.!;:') and str(after['params'].get('text', '')).casefold() != replacement.group(2).rstrip(',.!;:'):
                raise ProposalValidationError(
                    'requested replacement text is missing',
                    repair_details=[f'Cambia el texto del bloque de escritura de {replacement.group(1)} a {replacement.group(2)} y conserva su intervalo de escritura.'],
                )
    _validate_vision_click_flow(
        {'flow': {'root': root, 'nodes': [{'id': node_id, **node} for node_id, node in result_nodes.items()]}},
        request.messages[-1].content,
    )
    _validate_web_click_wait(
        {'flow': {'root': root, 'nodes': [{'id': node_id, **node} for node_id, node in result_nodes.items()]}},
        request.messages[-1].content,
    )


def _validate_request_alignment(
    request: ChatRequest,
    nodes: dict[str, dict[str, object]],
    baseline_ids: set[str],
) -> None:
    requested = _relevant_user_request(request).casefold()
    strict_less = re.search(r"\bmenor\s+(?:a|que)\s*(-?\d+(?:[.,]\d+)?)", requested)
    strict_greater = re.search(r"\bmayor\s+(?:a|que)\s*(-?\d+(?:[.,]\d+)?)", requested)
    greater_or_equal = re.search(
        r"\bmayor\s+o\s+igual\s+(?:a|que)\s*(-?\d+(?:[.,]\d+)?)",
        requested,
    )
    less_or_equal = re.search(
        r"\bmenor\s+o\s+igual\s+(?:a|que)\s*(-?\d+(?:[.,]\d+)?)",
        requested,
    )
    errors: list[str] = []
    if re.search(
        r"\b(?:cambiar|reemplazar)\s+(?:el\s+bot\s+)?(?:por\s+completo|todo)\b",
        requested,
    ) and baseline_ids.intersection(nodes):
        errors.append("full replacement requests cannot retain baseline node IDs")

    comparisons: list[tuple[object, object]] = []
    for node in nodes.values():
        if node.get("type") != "flow.if":
            continue
        params = node.get("params")
        condition = params.get("condition") if isinstance(params, dict) else None
        clauses = condition.get("clauses") if isinstance(condition, dict) else None
        if not isinstance(clauses, list):
            continue
        for clause in clauses:
            if not isinstance(clause, dict):
                continue
            operator, right = clause.get("operator"), clause.get("right")
            comparisons.append((operator, right))

    for match, operator, inclusive_operator, wording in (
        (strict_less, "lt", "lte", "menor a"),
        (strict_greater, "gt", "gte", "mayor a"),
    ):
        if match is None:
            continue
        expected = match.group(1)
        matching = [
            (candidate_operator, right)
            for candidate_operator, right in comparisons
            if candidate_operator in {operator, inclusive_operator}
            and (
                _same_number(right, expected)
                or _same_numeric_text(right, expected)
            )
        ]
        if any(
            candidate_operator == inclusive_operator
            and _same_number(right, expected)
            for candidate_operator, right in matching
        ):
            errors.append(
                f"strict '{wording}' requires operator {operator}, not {inclusive_operator}"
            )
        if not any(
            candidate_operator == operator and _same_number(right, expected)
            for candidate_operator, right in matching
        ):
            errors.append(
                f"strict '{wording}' requires operator {operator} with numeric JSON value {expected}"
            )

    action_types = [str(node.get("type")) for node in nodes.values()]
    writes_workbook = any(
        action_type in {"excel.writeCell", "excel.writeRange"}
        for action_type in action_types
    )
    # Draft proposals may intentionally leave a workbook dirty for later edits.
    requests_condition = strict_less is not None or strict_greater is not None
    if requests_condition and "flow.if" not in action_types:
        errors.append("the requested comparison requires flow.if")
    complementary_outcomes = (
        strict_less is not None
        and greater_or_equal is not None
        and _same_number_text(strict_less.group(1), greater_or_equal.group(1))
    ) or (
        strict_greater is not None
        and less_or_equal is not None
        and _same_number_text(strict_greater.group(1), less_or_equal.group(1))
    )
    if complementary_outcomes and action_types.count("flow.if") != 1:
        errors.append("complementary outcomes require exactly one flow.if")
    if requests_condition and action_types.count("excel.writeCell") < 2:
        errors.append("the requested two outcomes require two excel.writeCell branches")

    range_match = re.search(
        r"\b([a-z]{1,3})(\d+):([a-z]{1,3})(\d+)\b", requested
    )
    iterates_range = re.search(
        r"\b(?:recorre|recorrer|itera|iterar|iterate|loop|for\s+each)\b",
        requested,
    ) is not None
    if range_match is not None and iterates_range:
        start_column, start_row, end_column, end_row = range_match.groups()
        if start_column.casefold() == end_column.casefold():
            start, end = int(start_row), int(end_row)
            expected_iterations = abs(end - start) + 1
            loops = [
                node.get("params")
                for node in nodes.values()
                if node.get("type") == "flow.forRange"
            ]
            if len(loops) != 1 or not isinstance(loops[0], dict):
                errors.append("the requested cell range requires one flow.forRange")
            else:
                loop = loops[0]
                variable = loop.get("currentVariable")
                expected_step = 1 if end >= start else -1
                if (
                    loop.get("start") != start
                    or loop.get("end") != end
                    or loop.get("step") != expected_step
                    or loop.get("maxIterations") != expected_iterations
                    or variable != "row"
                ):
                    errors.append(
                        "flow.forRange must use the request-derived values "
                        f"start={start}, end={end}, step={expected_step}, "
                        f"currentVariable=row, and maxIterations={expected_iterations}"
                    )
                elif not _uses_row_template(
                    nodes,
                    column=start_column.upper(),
                    variable="row",
                ):
                    errors.append(
                        "the requested cell range must use the canonical row "
                        f"template {start_column.upper()}{{{{row}}}}"
                    )
        # Verificación de no-omisión accidental de bloques existentes
    latest_user_message = requested
    is_new_bot_intent = bool(
        re.search(
            r"\b(?:hace(?:me)?|crea(?:me)?|crealo|nuevo|otro|reemplaza(?:r)?|arma(?:me)?)\s+(?:un\s+)?(?:bot|flujo)\b|\b(?:hacelo|crealo(?:\s+asi)?|otro\s+que\s+no\s+sea)\b",
            requested,
            re.IGNORECASE,
        )
    )
    is_addition_only = bool(
        re.search(r"\b(?:agrega|agregar|agregame|sumar|incluir|a[ñn]adir)\b", latest_user_message, re.IGNORECASE)
    )
    is_deletion_requested = bool(
        re.search(r"\b(?:elimina|eliminar|borra|borrar|quita|quitar|reemplaza|reemplazar)\b", latest_user_message, re.IGNORECASE)
    )
    if is_addition_only and not is_deletion_requested and not is_new_bot_intent:
        missing_ids = baseline_ids - set(nodes)
        if missing_ids:
            errors.append(f"La propuesta eliminó accidentalmente {len(missing_ids)} bloques existentes del bot sin que se haya pedido borrarlos. Debes conservar TODOS los bloques existentes del [BOT_ACTUAL_EN_EDITOR] además de agregar el nuevo bloque solicitado.")

    if errors:
        raise ProposalValidationError(
            "; ".join(dict.fromkeys(errors)),
            repair_details=list(dict.fromkeys(errors)),
        )


def _same_number(value: object, expected: str) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return float(value) == float(expected.replace(",", "."))
    except ValueError:
        return False


def _same_numeric_text(value: object, expected: str) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return float(value.replace(",", ".")) == float(expected.replace(",", "."))
    except ValueError:
        return False


def _same_number_text(left: str, right: str) -> bool:
    try:
        return float(left.replace(",", ".")) == float(right.replace(",", "."))
    except ValueError:
        return False


def _uses_row_template(
    nodes: dict[str, dict[str, object]], *, column: str, variable: str
) -> bool:
    expected = f"{column}{{{{{variable}}}}}"
    return any(
        node.get("type") in {"excel.readCell", "excel.readRange"}
        and isinstance(node.get("params"), dict)
        and node["params"].get("cell") == expected
        for node in nodes.values()
    )


def _validate_resulting_bot(
    root: list[str],
    nodes: dict[str, dict[str, object]],
    actions: dict[str, object],
    proposal: AgentProposalArguments | None,
) -> dict[str, dict[str, object]]:
    if len(nodes) > CANONICAL_MAX_BOT_NODES:
        raise ProposalValidationError("resulting bot exceeds the node limit")
    _validate_placements(root, nodes)
    by_id = nodes

    def depth(ids: list[str], level: int) -> None:
        if level > DEFAULT_MAX_JSON_DEPTH:
            raise ProposalValidationError("resulting bot exceeds the depth limit")
        for node_id in ids:
            slots = by_id[node_id]["slots"]
            if isinstance(slots, dict):
                for children in slots.values():
                    if isinstance(children, list):
                        depth(children, level + 1)

    depth(root, 1)
    for node_id, node in by_id.items():
        action = actions.get(str(node["type"]))
        if action is None:
            raise ProposalValidationError("resulting bot references an unknown action")
        slots = node.get("slots")
        if not isinstance(slots, dict) or set(slots) != set(getattr(action, "slots", [])):
            raise ProposalValidationError("resulting bot slots do not match the action catalog")
        params = node.get("params")
        if not isinstance(params, dict):
            raise ProposalValidationError("resulting bot parameters are invalid")
        _validate_params(params, getattr(action, "fields"), getattr(action, "defaults"))

    def referenced_variables(value: object) -> set[str]:
        if isinstance(value, str):
            if "{{" in value or "}}" in value:
                matches = list(re.finditer(r"{{([A-Za-z_][A-Za-z0-9_]*)}}", value))
                if re.sub(r"{{[A-Za-z_][A-Za-z0-9_]*}}", "", value).find("{{") >= 0 or re.sub(
                    r"{{[A-Za-z_][A-Za-z0-9_]*}}", "", value
                ).find("}}") >= 0:
                    raise ProposalValidationError(
                        "operation contains a malformed variable reference",
                        repair_details=[
                            'Dentro de {{}} solo va el nombre de una variable ya creada. No pongas expresiones, condicionales ni código en parámetros. Para elegir entre dos valores usa un bloque Si con una escritura distinta en then y else.'
                        ],
                    )
                return {match.group(1) for match in matches}
            return set()
        if isinstance(value, list):
            return set().union(*(referenced_variables(item) for item in value)) if value else set()
        if isinstance(value, dict):
            return set().union(*(referenced_variables(item) for item in value.values())) if value else set()
        return set()

    def sequence(
        ids: list[str], variables: set[str], workbooks: set[str]
    ) -> tuple[set[str], set[str]]:
        current_variables = set(variables)
        current_workbooks = set(workbooks)
        positions = set(ids)
        for node_id in ids:
            node = by_id[node_id]
            action_type = str(node["type"])
            action = actions[action_type]
            params = {**getattr(action, "defaults"), **dict(node["params"])}
            outputs = getattr(action, "outputs", []) or (
                [getattr(action, "output")] if getattr(action, "output", None) is not None else []
            )
            output_fields = {output.field for output in outputs}
            declarations = set(output_fields)
            if action_type == "flow.forRange":
                if proposal is None and params.get('step') == 0:
                    raise ProposalValidationError('range step cannot be zero', repair_details=['El paso de flow.forRange debe ser distinto de cero.'])
                declarations.add("currentVariable")
            elif action_type == "flow.forEach":
                declarations.update({"itemVariable", "indexVariable"})
            elif action_type == "flow.tryCatch":
                declarations.add("errorVariable")
            if proposal is None and action_type in {'flow.if', 'flow.while'}:
                condition = params.get('condition')
                clauses = condition.get('clauses', []) if isinstance(condition, dict) else []
                for clause in clauses:
                    for side in ('left', 'right'):
                        operand = clause.get(side)
                        if isinstance(operand, dict) and 'operator' in operand and {'field', 'left', 'variable'} & operand.keys():
                            raise ProposalValidationError(
                                'condition operand contains an unsupported expression object',
                                repair_details=['Una clausula compara valores: {"left":"{{nota}}","operator":"lt","right":6}. Usa el nombre real de la variable y el umbral pedido. No anides objetos field/operator dentro de left o right: se compararian como datos literales, no se ejecutan.'],
                            )
            for name, value in params.items():
                if name not in declarations:
                    missing = referenced_variables(value) - current_variables
                    if missing:
                        raise ProposalValidationError(
                            f"operation references an unavailable variable: {missing}",
                            repair_details=[
                                f"La variable {missing} no esta disponible en este alcance. Las variables de un bucle solo existen dentro de su body. No las uses fuera de su bucle."
                            ],
                        )

            workbook_name = params.get("workbookVariable")
            if action_type.startswith("excel.") and action_type not in {"excel.open", "excel.create"}:
                if not isinstance(workbook_name, str) or workbook_name not in current_workbooks:
                    raise ProposalValidationError("operation references an unavailable workbook")

            slots = node["slots"]
            assert isinstance(slots, dict)
            if action_type == "flow.group":
                current_variables, current_workbooks = sequence(
                    slots.get("body", []), current_variables, current_workbooks
                )
            elif action_type == "flow.if":
                then_state = sequence(slots.get("then", []), current_variables, current_workbooks)
                else_state = sequence(slots.get("else", []), current_variables, current_workbooks)
                current_variables = then_state[0] & else_state[0]
                current_workbooks = then_state[1] & else_state[1]
            elif action_type == "flow.tryCatch":
                error_name = params.get("errorVariable")
                branch_variables = set(current_variables)
                if isinstance(error_name, str) and error_name:
                    branch_variables.add(error_name)
                tried = sequence(slots.get("try", []), branch_variables, current_workbooks)
                caught = sequence(slots.get("catch", []), branch_variables, current_workbooks)
                current_variables = tried[0] & caught[0]
                current_workbooks = tried[1] & caught[1]
            elif action_type in {"flow.forRange", "flow.forEach", "flow.while"}:
                body_variables = set(current_variables)
                for field_name in declarations:
                    value = params.get(field_name)
                    if isinstance(value, str) and value:
                        body_variables.add(value)
                _, current_workbooks = sequence(
                    slots.get("body", []), body_variables, current_workbooks
                )
            elif action_type == "flow.goTo":
                target = params.get("targetNodeId")
                if not isinstance(target, str) or target not in positions:
                    raise ProposalValidationError("goTo target must be in the same sequence")
            elif action_type == "variable.create":
                name = params.get("name")
                if not isinstance(name, str) or not name.strip():
                    raise ProposalValidationError("variable declaration is invalid")
                current_variables.add(name)
            elif action_type in {"variable.update", "variable.delete"}:
                name = params.get("name")
                if not isinstance(name, str) or name not in current_variables:
                    raise ProposalValidationError("operation references an unavailable variable")
                if action_type == "variable.delete":
                    current_variables.remove(name)
            elif action_type in {"excel.open", "excel.create"}:
                name = params.get("outputVariable")
                if isinstance(name, str) and name.strip():
                    current_workbooks.add(name)
            elif action_type == "excel.close":
                assert isinstance(workbook_name, str)
                current_workbooks.remove(workbook_name)

            if action_type not in {"variable.create", "excel.open", "excel.create"}:
                for output in outputs:
                    if output.type == "workbook":
                        continue
                    name = params.get(output.field)
                    if isinstance(name, str) and name.strip():
                        current_variables.add(name)
                        if action_type == 'vision.detectElement':
                            current_variables.update(name + suffix for suffix in VISION_DERIVED_SUFFIXES)
                        elif action_type == 'http.request':
                            current_variables.update(name + suffix for suffix in HTTP_DERIVED_SUFFIXES)
        return current_variables, current_workbooks

    sequence(root, set(), set())

    if proposal is None:
        return nodes

    for operation in proposal.operations:
        if isinstance(operation, SetMetadataOperation):
            continue
        if isinstance(operation, AddNodeOperation):
            node_id = operation.node.id
            if node_id in nodes:
                raise ProposalValidationError("addNode IDs must be unique")
            action = actions.get(operation.node.type)
            if action is None:
                raise ProposalValidationError("addNode references an unknown action")
            _validate_params(operation.node.params, (action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', [])), (action.get('defaults', {}) if isinstance(action, dict) else getattr(action, 'defaults', {})))
            target = _target_sequence(operation.location, root, nodes, actions)
            if operation.location.index > len(target):
                raise ProposalValidationError("addNode index is outside its sequence")
            nodes[node_id] = {
                "type": operation.node.type,
                "slots": {slot: [] for slot in (action.get('slots', []) if isinstance(action, dict) else getattr(action, 'slots', []))},
                "params": copy.deepcopy(operation.node.params),
            }
            target.insert(operation.location.index, node_id)
            continue
        if isinstance(operation, RemoveNodeOperation):
            if operation.node_id not in nodes:
                raise ProposalValidationError("removeNode references an unknown node")
            source = _source_sequence(operation.node_id, root, nodes)
            source.remove(operation.node_id)
            for node_id in _descendants(operation.node_id, nodes):
                nodes.pop(node_id, None)
            continue
        if isinstance(operation, MoveNodeOperation):
            if operation.node_id not in nodes:
                raise ProposalValidationError("moveNode references an unknown node")
            if operation.location.parent_id in _descendants(operation.node_id, nodes):
                raise ProposalValidationError("moveNode cannot create a containment cycle")
            source = _source_sequence(operation.node_id, root, nodes)
            source.remove(operation.node_id)
            target = _target_sequence(operation.location, root, nodes, actions)
            if operation.location.index > len(target):
                raise ProposalValidationError("moveNode index is outside its sequence")
            target.insert(operation.location.index, operation.node_id)
            continue
        if isinstance(operation, UpdateNodeParamsOperation):
            node = nodes.get(operation.node_id)
            if node is None:
                raise ProposalValidationError("updateNodeParams references an unknown node")
            action = actions.get(str(node["type"]))
            if action is None:
                raise ProposalValidationError("updateNodeParams references an unknown action")
            _validate_params(operation.params, (action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', [])), (action.get('defaults', {}) if isinstance(action, dict) else getattr(action, 'defaults', {})))
            node["params"] = copy.deepcopy(operation.params)
            continue
        if isinstance(operation, ReplaceNodeOperation):
            node = nodes.get(operation.node_id)
            action = actions.get(operation.action_type)
            if node is None or action is None:
                raise ProposalValidationError("replaceNode references an unknown node or action")
            slots = node["slots"]
            if not isinstance(slots, dict) or set(slots) != set((action.get('slots', []) if isinstance(action, dict) else getattr(action, 'slots', []))):
                raise ProposalValidationError("replaceNode must preserve declared slots")
            _validate_params(operation.params, (action.get('fields', []) if isinstance(action, dict) else getattr(action, 'fields', [])), (action.get('defaults', {}) if isinstance(action, dict) else getattr(action, 'defaults', {})))
            node["type"] = operation.action_type
            node["params"] = copy.deepcopy(operation.params)

    _validate_placements(root, nodes)
    return _validate_resulting_bot(root, nodes, actions, None)


def _validate_params(
    params: dict[str, JsonValue],
    fields: list[ActionFieldDefinition],
    defaults: dict[str, JsonValue],
) -> None:
    validated_fields = [
        field
        if isinstance(field, ActionFieldDefinition)
        else ActionFieldDefinition.model_validate(field)
        for field in fields
    ]
    fields_by_name = {field.name: field for field in validated_fields}
    unknown = set(params) - set(fields_by_name)
    if unknown:
        raise ProposalValidationError(
            "unknown action parameter fields: " + ", ".join(sorted(unknown))
        )
    resolved = {**defaults, **params}
    for field in validated_fields:
        if field.name not in resolved:
            if field.required:
                raise ProposalValidationError(
                    f"missing required action parameter '{field.name}'"
                )
            continue
        value = resolved[field.name]
        if is_pending_parameter(value) and allows_pending_parameter(field.type, field.name):
            continue
        if field.type == "json":
            _reject_templated_json_keys(value)
        if field.required and isinstance(value, str) and not value:
            raise ProposalValidationError(
                f"required action parameter '{field.name}' must not be empty"
            )
        if not is_valid_action_field_value(field, value, required=field.required):
            raise ProposalValidationError(f"invalid action parameter '{field.name}'")


def _reject_templated_json_keys(value: JsonValue) -> None:
    pending: list[JsonValue] = [value]
    while pending:
        current = pending.pop()
        if isinstance(current, list):
            pending.extend(current)
        elif isinstance(current, dict):
            for key, item in current.items():
                if re.search(r"\{\{.*?\}\}", key, re.DOTALL):
                    raise ProposalValidationError(
                        "JSON object keys cannot contain variable templates"
                    )
                pending.append(item)


_INTERNAL_REFERENCE_FIELDS = {
    "currentVariable",
    "errorVariable",
    "indexVariable",
    "itemVariable",
    "outputVariable",
    "targetNodeId",
    "workbookVariable",
}
_STRUCTURAL_FIELDS = {
    "condition",
    "maxIterations",
    "start",
    "end",
    "step",
}
_VARIABLE_REFERENCE = re.compile(r"{{([A-Za-z_][A-Za-z0-9_]*)}}")


def _validate_external_fact_provenance(
    proposal: AgentProposalArguments,
    request: ChatRequest,
    actions: dict[str, object],
    baseline_nodes: dict[str, dict[str, object]],
) -> None:
    missing: set[ExternalFactRequirement] = set()
    known_nodes = copy.deepcopy(baseline_nodes)
    external_values: list[
        tuple[ExternalFactRequirement, ActionFieldDefinition, JsonValue]
    ] = []

    for operation in proposal.operations:
        action_type: str | None = None
        params: dict[str, JsonValue] | None = None
        prior_params: dict[str, object] = {}
        if isinstance(operation, AddNodeOperation):
            action_type = operation.node.type
            params = operation.node.params
            known_nodes[operation.node.id] = {
                "type": action_type,
                "params": copy.deepcopy(params),
            }
        elif isinstance(operation, RemoveNodeOperation):
            known_nodes.pop(operation.node_id, None)
        elif isinstance(operation, ReplaceNodeOperation):
            action_type = operation.action_type
            params = operation.params
            prior = known_nodes.get(operation.node_id)
            if prior is not None and prior.get("type") == action_type:
                prior_params = dict(prior.get("params", {}))
            known_nodes[operation.node_id] = {
                "type": action_type,
                "params": copy.deepcopy(params),
            }
        elif isinstance(operation, UpdateNodeParamsOperation):
            prior = known_nodes.get(operation.node_id)
            if prior is not None:
                action_type = str(prior.get("type"))
                prior_params = dict(prior.get("params", {}))
                params = operation.params
                prior["params"] = copy.deepcopy(params)
        if action_type is None or params is None:
            continue

        action = actions.get(action_type)
        if action is None:
            continue
        defaults = getattr(action, "defaults", {})
        for field in getattr(action, "fields", []):
            name = field.name
            if name not in params:
                continue
            value = params[name]
            if is_pending_parameter(value):
                continue
            if value == "" or value is None or value == prior_params.get(name) or value == defaults.get(name):
                continue
            if field.type == "condition":
                external_values.extend(
                    _condition_literal_requirements(action_type, action, field, value)
                )
                continue
            if classify_field(action, field) is not FieldSemantics.EXTERNAL:
                continue
            if action_type.startswith("mouse."):
                continue
            requirement = ExternalFactRequirement.from_field(
                action_type,
                field,
                action_title=str(getattr(action, "title", "")),
            )
            if isinstance(value, str) and _is_pure_runtime_reference(value):
                continue
            if (
                isinstance(value, str)
                and _VARIABLE_REFERENCE.search(value)
                and field.name in {"cell", "range"}
            ):
                continue
            external_values.append((requirement, field, value))

    requirements = tuple(dict.fromkeys(item[0] for item in external_values))
    evidence_assignments: dict[FactFieldRef, list[EvidenceAssignment]] = {}
    for assignment in build_evidence_ledger(request, requirements):
        evidence_assignments.setdefault(assignment.field_ref, []).append(assignment)
    for requirement, field, value in external_values:
        if not any(
            value_matches_assignment(field, value, assignment)
            for assignment in evidence_assignments.get(requirement.ref, [])
        ):
            missing.add(requirement)

    if missing:
        raise ExternalFactValidationError(missing)


def _condition_literal_requirements(
    action_type: str,
    action: object,
    field: ActionFieldDefinition,
    value: JsonValue,
) -> list[tuple[ExternalFactRequirement, ActionFieldDefinition, JsonValue]]:
    if not isinstance(value, dict) or not isinstance(value.get("clauses"), list):
        return []
    found: list[tuple[ExternalFactRequirement, ActionFieldDefinition, JsonValue]] = []
    for index, clause in enumerate(value["clauses"]):
        if not isinstance(clause, dict):
            continue
        for operand in ("left", "right"):
            if operand not in clause:
                continue
            literal = clause[operand]
            if isinstance(literal, str) and _is_pure_runtime_reference(literal):
                continue
            literal_field = _condition_literal_field(field, literal)
            side = "izquierdo" if operand == "left" else "derecho"
            requirement = ExternalFactRequirement.from_field(
                action_type,
                literal_field,
                action_title=str(getattr(action, "title", "")),
                semantic_label=f"el valor {side} de la condicion {index + 1}",
            )
            requirement = ExternalFactRequirement(
                FactFieldRef(action_type, f"{field.name}.{index}.{operand}"),
                literal_field,
                requirement.action_title,
                requirement.semantic_label,
            )
            found.append((requirement, literal_field, literal))
    return found


def _condition_literal_field(
    condition_field: ActionFieldDefinition, value: JsonValue
) -> ActionFieldDefinition:
    if isinstance(value, bool):
        field_type = "boolean"
    elif isinstance(value, int):
        field_type = "integer"
    elif isinstance(value, float):
        field_type = "number"
    elif isinstance(value, (dict, list)) or value is None:
        field_type = "json"
    else:
        field_type = "text"
    return ActionFieldDefinition(
        name="conditionLiteral",
        label=condition_field.label,
        type=field_type,
        required=True,
    )


def _is_pure_runtime_reference(value: str) -> bool:
    return re.fullmatch(r"{{[A-Za-z_][A-Za-z0-9_]*}}", value) is not None


def _is_deterministic_cell_template(value: str, request: ChatRequest) -> bool:
    match = re.fullmatch(r"([A-Za-z]{1,3}){{([A-Za-z_][A-Za-z0-9_]*)}}", value)
    if match is None:
        return False
    requested = _relevant_user_request(request)
    column = re.escape(match.group(1))
    return re.search(
        rf"\b{column}\d+(?::{column}\d+)?\b|\b(?:en|columna)\s+{column}\b",
        requested,
        re.IGNORECASE,
    ) is not None


def _relevant_user_request(request: ChatRequest) -> str:
    user_messages = [
        message.content for message in request.messages if message.role == "user"
    ]
    if not user_messages:
        return ""
    latest = user_messages[-1]
    normalized = latest.strip().casefold()
    depends_on_previous = len(normalized.split()) <= 16 and re.search(
        r"^(?:ahora|entonces|ademas|tambien|dale\b|y\b|pero\b|hacelo\b|"
        r"cambialo\b|cambiala\b|agregalo\b|agregala\b|quit[áa]lo\b|"
        r"eso\b|esto\b|asi\b|lo mismo\b)",
        normalized,
    )
    supplies_requested_facts = re.search(
        r"\b(?:ruta|hoja|url|celda|rango|valor|nombre|titulo|x|y)\s*"
        r"(?:exacta?\s*)?(?:es|:|=)",
        normalized,
    )
    if (depends_on_previous or supplies_requested_facts) and len(user_messages) > 1:
        return f"{user_messages[-2]} {latest}"
    return latest


def _target_sequence(
    location: ProposalLocation,
    root: list[str],
    nodes: dict[str, dict[str, object]],
    actions: dict[str, object],
) -> list[str]:
    if location.parent_id is None:
        return root
    parent = nodes.get(location.parent_id)
    if parent is None:
        raise ProposalValidationError("location references an unknown parent")
    action = actions.get(str(parent["type"]))
    declared_slots = set(getattr(action, "slots", []))
    slots = parent.get("slots")
    if (
        location.slot not in declared_slots
        or not isinstance(slots, dict)
        or not isinstance(slots.get(location.slot), list)
    ):
        raise ProposalValidationError("location references an undeclared slot")
    return slots[location.slot]


def _source_sequence(
    node_id: str, root: list[str], nodes: dict[str, dict[str, object]]
) -> list[str]:
    matches: list[list[str]] = []
    if node_id in root:
        matches.append(root)
    for node in nodes.values():
        slots = node.get("slots")
        if isinstance(slots, dict):
            for children in slots.values():
                if isinstance(children, list) and node_id in children:
                    matches.append(children)
    if len(matches) != 1:
        raise ProposalValidationError("node placement is invalid")
    return matches[0]


def _descendants(node_id: str, nodes: dict[str, dict[str, object]]) -> set[str]:
    found: set[str] = set()

    def visit(current: str) -> None:
        if current in found:
            return
        found.add(current)
        slots = nodes.get(current, {}).get("slots")
        if isinstance(slots, dict):
            for children in slots.values():
                if isinstance(children, list):
                    for child in children:
                        if isinstance(child, str):
                            visit(child)

    visit(node_id)
    return found


def _validate_placements(root: list[str], nodes: dict[str, dict[str, object]]) -> None:
    placements = list(root)
    for node in nodes.values():
        slots = node.get("slots")
        if not isinstance(slots, dict):
            raise ProposalValidationError("node slots are invalid")
        for children in slots.values():
            if not isinstance(children, list):
                raise ProposalValidationError("node slots are invalid")
            placements.extend(children)
    if len(placements) != len(set(placements)) or set(placements) != set(nodes):
        raise ProposalValidationError("every node must be placed exactly once")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visiting:
            raise ProposalValidationError("the baseline contains a cycle")
        if node_id in visited:
            return
        node = nodes.get(node_id)
        if node is None:
            raise ProposalValidationError("placement references an unknown node")
        visiting.add(node_id)
        slots = node["slots"]
        if isinstance(slots, dict):
            for children in slots.values():
                if isinstance(children, list):
                    for child in children:
                        visit(child)
        visiting.remove(node_id)
        visited.add(node_id)

    for node_id in root:
        visit(node_id)
    for node_id in nodes:
        visit(node_id)


def validate_updated_flow(
    outcome: EditorUpdatedFlow,
    request: ChatRequest,
) -> ValidatedUpdatedBot:
    context = request.editor_context
    if context is None:
        raise ProposalValidationError("an editor context is required")
    baseline = context.working_bot if context.working_bot is not None else context.bot
    if baseline.get("schemaVersion") != 2:
        raise ProposalValidationError("only canonical schema v2 bots are editable")
    bot_id = baseline.get("id")
    if not isinstance(bot_id, str) or not bot_id:
        raise ProposalValidationError("working bot must contain a valid bot ID")
    
    if not outcome.flow and not _explicit_remove_all_intent(request):
        raise ProposalValidationError(
            "updatedFlow may be empty only when the user explicitly requests removing all nodes"
        )

    actions = _verified_canonical_actions(request)
    baseline_flow = baseline.get("flow")
    if not isinstance(baseline_flow, dict):
        raise ProposalValidationError("the baseline flow is invalid")
    raw_baseline_nodes = baseline_flow.get("nodes")
    if not isinstance(raw_baseline_nodes, list):
        raise ProposalValidationError("the baseline nodes are invalid")
    baseline_by_id = {
        node["id"]: node
        for node in raw_baseline_nodes
        if isinstance(node, dict) and isinstance(node.get("id"), str)
    }
    if len(baseline_by_id) != len(raw_baseline_nodes):
        raise ProposalValidationError("the baseline contains invalid node IDs")

    used_ids: set[str] = set()
    matched_ids: set[str] = set()
    node_list: list[dict[str, JsonValue]] = []
    node_matches: dict[tuple[object, ...], str] = {}
    baseline_root = baseline_flow.get("root", []) if isinstance(baseline_flow.get("root"), list) else []
    baseline_placement: dict[str, tuple[str | None, str, int]] = {}

    def index_baseline(ids: list[object], parent_id: str | None, slot_name: str) -> None:
        for index, node_id in enumerate(ids):
            if not isinstance(node_id, str) or node_id not in baseline_by_id:
                continue
            baseline_placement[node_id] = (parent_id, slot_name, index)
            slots = baseline_by_id[node_id].get("slots", {})
            if isinstance(slots, dict):
                for child_slot, children in slots.items():
                    if isinstance(children, list):
                        index_baseline(children, node_id, child_slot)

    index_baseline(baseline_root, None, "root")

    def params_match(node_type: str, node_params: dict[str, JsonValue], b_node: dict[str, JsonValue]) -> bool:
        if b_node.get("type") != node_type:
            return False
        action = actions.get(node_type)
        defaults = getattr(action, "defaults", {}) if action else {}
        p1 = {**defaults, **node_params}
        p2 = {**defaults, **(b_node.get("params", {}) if isinstance(b_node.get("params"), dict) else {})}
        return p1 == p2

    def match_level(
        proposed_nodes: tuple[UpdatedFlowNode, ...],
        expected_parent_id: str | None,
        slot_name: str,
        path_prefix: tuple[object, ...],
    ) -> None:
        if expected_parent_id is None and slot_name == "root":
            container_b_ids = [nid for nid in baseline_root if isinstance(nid, str) and nid not in matched_ids]
        elif expected_parent_id and expected_parent_id in baseline_by_id:
            parent_b_node = baseline_by_id[expected_parent_id]
            parent_slots = parent_b_node.get("slots", {}) if isinstance(parent_b_node.get("slots"), dict) else {}
            slot_children = parent_slots.get(slot_name, []) if isinstance(parent_slots.get(slot_name), list) else []
            container_b_ids = [nid for nid in slot_children if isinstance(nid, str) and nid not in matched_ids]
        else:
            container_b_ids = []

        for p_idx, p_node in enumerate(proposed_nodes):
            current_path = (*path_prefix, p_idx)
            matched_b_id: str | None = None
            if p_node.id is not None and p_node.id in baseline_by_id and p_node.id not in matched_ids:
                matched_b_id = p_node.id
            elif p_node.id is None:
                # Prefer the same container and relative position. This keeps an
                # unchanged node's identity stable when siblings are deleted.
                candidates = [
                    b_id
                    for b_id in container_b_ids
                    if b_id not in matched_ids
                    and params_match(p_node.type, p_node.params, baseline_by_id[b_id])
                ]
                if candidates:
                    matched_b_id = min(
                        candidates,
                        key=lambda b_id: (
                            abs(baseline_placement.get(b_id, (None, "", 0))[2] - p_idx),
                            baseline_placement.get(b_id, (None, "", 0))[2],
                        ),
                    )
                else:
                    # In-place parameter modification: prefer an unmatched node of the same type at the same index in this container
                    for b_id in container_b_ids:
                        if b_id not in matched_ids and baseline_by_id[b_id].get("type") == p_node.type:
                            if baseline_placement.get(b_id, (None, "", -1))[2] == p_idx:
                                matched_b_id = b_id
                                break
                    if matched_b_id is None:
                        # A moved node may no longer be in the same container. Only
                        # use the global fallback after structural and in-place candidates
                        # in the same container are exhausted.
                        candidates = [
                            b_id
                            for b_id, b_node in baseline_by_id.items()
                            if b_id not in matched_ids
                            and params_match(p_node.type, p_node.params, b_node)
                        ]
                        if candidates:
                            matched_b_id = min(
                                candidates,
                                key=lambda b_id: (
                                    baseline_placement.get(b_id, (None, "", 0))[2],
                                    b_id,
                                ),
                            )

            if matched_b_id is not None:
                matched_ids.add(matched_b_id)
                node_matches[current_path] = matched_b_id

            for child_slot, children in p_node.slots.items():
                match_level(children, matched_b_id, child_slot, (*current_path, child_slot))

    match_level(outcome.flow, None, "root", ("root",))

    def assign_ids(
        nodes: tuple[UpdatedFlowNode, ...], path_prefix: tuple[object, ...]
    ) -> list[str]:
        assigned_ids: list[str] = []
        for index, node in enumerate(nodes):
            path = (*path_prefix, index)
            action = actions.get(node.type)
            if action is None:
                raise ProposalValidationError(f"unknown action type: {node.type}")
            params = copy.deepcopy(action.defaults)
            params.update(copy.deepcopy(node.params))
            candidate_id = node_matches.get(path)
            if candidate_id is None:
                if node.id is not None:
                    candidate_id = node.id
                else:
                    path_text = "/".join(str(part) for part in path)
                    counter = 0
                    while True:
                        suffix = f":{counter}" if counter > 0 else ""
                        digest = hashlib.sha256(
                            f"{bot_id}:{path_text}:{node.type}{suffix}".encode("utf-8")
                        ).hexdigest()[:16]
                        candidate_id = f"ai-{digest}"
                        if candidate_id not in used_ids and candidate_id not in baseline_by_id:
                            break
                        counter += 1
            if candidate_id in used_ids:
                raise ProposalValidationError(f"duplicate updatedFlow node id: {candidate_id}")
            used_ids.add(candidate_id)
            if candidate_id in baseline_by_id:
                matched_ids.add(candidate_id)
            assigned_ids.append(candidate_id)
            node_dict: dict[str, JsonValue] = {
                "id": candidate_id,
                "type": node.type,
                "params": params,
                "slots": {},
            }
            node_list.append(node_dict)
            node_dict["slots"] = {
                slot_name: assign_ids(children, (*path, slot_name))
                for slot_name, children in node.slots.items()
            }
        return assigned_ids

    root_ids = assign_ids(outcome.flow, ("root",))
    nodes_by_id = {str(node["id"]): node for node in node_list}

    explicit_ids = {
        node.id
        for node in _walk_updated_flow(outcome.flow)
        if node.id is not None
    }
    for node in nodes_by_id.values():
        if node["type"] != "flow.goTo":
            continue
        params = node["params"]
        target = params.get("targetNodeId") if isinstance(params, dict) else None
        if target not in explicit_ids:
            raise ProposalValidationError("flow.goTo target must use an explicit node id")

    _validate_resulting_bot(
        root_ids,
        nodes_by_id,
        actions,
        None,
    )
    _validate_updated_flow_provenance(nodes_by_id, baseline_by_id, actions, request)

    name, description = _validated_metadata(outcome, request, baseline)
    resulting_bot = {
        "schemaVersion": 2,
        "id": bot_id,
        "name": name,
        "description": description,
        "icon": baseline.get("icon", "bot"),
        "flow": {
            "root": root_ids,
            "nodes": node_list,
        },
    }
    if "ai" in baseline:
        resulting_bot["ai"] = copy.deepcopy(baseline["ai"])
    mcp_result = mcp_validate_bot(resulting_bot, mode="proposal")
    mcp_errors = [
        issue
        for issue in mcp_result.get("issues", [])
        if isinstance(issue, dict) and issue.get("severity", "error") == "error"
    ]
    if not mcp_result.get("ok") or mcp_errors:
        details = [
            str(issue.get("message") or issue.get("code") or "MCP validation error")
            for issue in mcp_errors[:20]
        ]
        message = "MCP rejected the resulting bot"
        if details:
            message += ": " + "; ".join(details)
        raise ProposalValidationError(
            message,
            repair_details=details,
        )

    return ValidatedUpdatedBot(
        bot=resulting_bot,
        node_count=len(node_list),
        matched_baseline_ids=frozenset(matched_ids),
    )


def _walk_updated_flow(
    roots: tuple[UpdatedFlowNode, ...],
) -> tuple[UpdatedFlowNode, ...]:
    found: list[UpdatedFlowNode] = []
    pending = list(reversed(roots))
    while pending:
        node = pending.pop()
        found.append(node)
        for children in reversed(tuple(node.slots.values())):
            pending.extend(reversed(children))
    return tuple(found)


def _validated_metadata(
    outcome: EditorUpdatedFlow,
    request: ChatRequest,
    baseline: dict[str, JsonValue],
) -> tuple[str, str]:
    latest = next(
        (message.content for message in reversed(request.messages) if message.role == "user"),
        "",
    )
    creative_replacement = _creative_full_replacement_intent(latest)
    rename_requested = _metadata_field_requested(latest, "name")
    description_requested = _metadata_field_requested(latest, "description")
    requested_name = _metadata_assignment_value(latest, "name")
    requested_description = _metadata_assignment_value(latest, "description")
    baseline_name = baseline.get("name")
    baseline_description = baseline.get("description", "")
    if not isinstance(baseline_name, str) or not isinstance(baseline_description, str):
        raise ProposalValidationError("the baseline metadata is invalid")
    if creative_replacement:
        return outcome.name, outcome.description

    def validated_field(
        proposed: str,
        baseline_value: str,
        requested: bool,
        evidenced_value: str | None,
        field: str,
    ) -> str:
        if not requested:
            return baseline_value
        if evidenced_value is None:
            if proposed != baseline_value:
                raise ProposalValidationError(
                    f"updatedFlow {field} changed without a user-provided value"
                )
            return baseline_value
        if proposed != evidenced_value:
            raise ProposalValidationError(
                f"updatedFlow {field} must exactly match the user-provided value"
            )
        return evidenced_value

    return (
        validated_field(
            outcome.name, baseline_name, rename_requested, requested_name, "name"
        ),
        validated_field(
            outcome.description,
            baseline_description,
            description_requested,
            requested_description,
            "description",
        ),
    )


@dataclass(frozen=True)
class _IntentPredicate:
    words: tuple[str, ...]
    negated: bool
    has_exception: bool


@dataclass(frozen=True)
class _IntentClause:
    predicates: tuple[_IntentPredicate, ...]


_INTENT_NEGATIONS = {"no", "nunca", "never", "not"}
_INTENT_COORDINATORS = {
    "and",
    "but",
    "however",
    "luego",
    "pero",
    "sino",
    "then",
    "y",
}
_INTENT_EXCEPTION_WORDS = {
    "except",
    "excepto",
    "excepcion",
    "excluding",
    "exception",
    "menos",
    "salvo",
}


def _analyze_intent(message: str) -> tuple[_IntentClause, ...]:
    tokens = re.findall(r"[a-z0-9]+|[.!?;,\n\r]+", plain_text(message))
    raw_clauses: list[list[tuple[str, ...]]] = []
    raw_predicates: list[tuple[str, ...]] = []
    words: list[str] = []

    def finish_predicate() -> None:
        if words:
            raw_predicates.append(tuple(words))
            words.clear()

    def finish_clause() -> None:
        finish_predicate()
        if raw_predicates:
            raw_clauses.append(list(raw_predicates))
            raw_predicates.clear()

    for token in tokens:
        if token[0] in ".!?;\n\r":
            finish_clause()
        elif token == "," or token in _INTENT_COORDINATORS:
            finish_predicate()
        else:
            words.append(token)
    finish_clause()

    clauses: list[_IntentClause] = []
    for raw_clause in raw_clauses:
        exception_scopes = [
            any(word in _INTENT_EXCEPTION_WORDS for word in predicate)
            for predicate in raw_clause
        ]
        pending_exception = False
        for index, predicate in enumerate(raw_clause):
            starts_exception = (
                predicate[0] in {"except", "excepto", "excluding", "menos", "salvo"}
                or predicate[:2] == ("con", "excepcion")
                or predicate[:2] == ("with", "exception")
                or predicate[:3] == ("with", "the", "exception")
            )
            if pending_exception:
                exception_scopes[index] = True
                pending_exception = False
            if starts_exception:
                if index == 0:
                    pending_exception = True
                else:
                    exception_scopes[index - 1] = True

        clauses.append(
            _IntentClause(
                tuple(
                    _IntentPredicate(
                        predicate,
                        any(word in _INTENT_NEGATIONS for word in predicate),
                        exception_scopes[index],
                    )
                    for index, predicate in enumerate(raw_clause)
                )
            )
        )
    return tuple(clauses)


def _metadata_field_requested(message: str, field: Literal["name", "description"]) -> bool:
    direct_verbs = (
        {"llama", "llamar", "rename", "renombra", "renombrar"}
        if field == "name"
        else {"describe", "describir"}
    )
    nouns = {"name", "nombre"} if field == "name" else {"descripcion", "description"}
    change_verbs = {
        "agrega",
        "agregar",
        "asigna",
        "asignar",
        "anade",
        "anadir",
        "cambia",
        "cambiar",
        "change",
        "pone",
        "poner",
        "set",
    }
    competing_objects = {
        "accion",
        "archivo",
        "block",
        "bloque",
        "comentario",
        "comment",
        "file",
        "resultado",
        "result",
        "variable",
    }
    all_metadata_verbs = change_verbs | direct_verbs | {
        "describe",
        "describir",
        "llama",
        "llamar",
        "rename",
        "renombra",
        "renombrar",
    }
    for clause in _analyze_intent(message):
        inherited_change = False
        inherited_bot = False
        for predicate in clause.predicates:
            words = predicate.words
            local_verb_indexes = [
                index for index, word in enumerate(words) if word in all_metadata_verbs
            ]
            local_change = any(word in change_verbs for word in words)
            local_direct = any(word in direct_verbs for word in words)
            local_bot_indexes = [
                index
                for index, word in enumerate(words)
                if word in {"bot", "flow", "flujo"}
            ]
            has_noun = any(word in nouns for word in words)
            effective_change = local_change or (not local_verb_indexes and inherited_change)
            has_competing_object = any(word in competing_objects for word in words)
            effective_bot = (
                bool(local_bot_indexes)
                or inherited_bot
                or (has_noun and not has_competing_object)
            )
            has_field_intent = local_direct or (effective_change and has_noun)
            if not has_field_intent or not effective_bot or predicate.negated:
                if local_verb_indexes:
                    inherited_change = local_change
                if local_bot_indexes:
                    inherited_bot = True
                continue

            verb_index = local_verb_indexes[0] if local_verb_indexes else -1
            bot_index = next(
                (
                    candidate for candidate in local_bot_indexes if candidate > verb_index
                ),
                None,
            )
            if bot_index is not None and any(
                candidate in competing_objects
                for candidate in words[verb_index + 1 : bot_index]
            ):
                continue
            return True
    return False


def _metadata_assignment_value(
    message: str, field: Literal["name", "description"]
) -> str | None:
    assignment_verbs = r"(?:asigna|asigná|asignar|cambia|cambiá|cambiar|change|pone|poné|poner|set)"
    if field == "name":
        labels = r"(?:(?:el\s+)?nombre(?:\s+del\s+bot)?|(?:the\s+)?(?:bot\s+)?name)"
        patterns = (
            rf"\b(?:pone|poné|poner|asigna|asigná|asignar|set)\s+(?P<value>.+?)\s+(?:como|as)\s+{labels}(?=[.!?;\r\n]|$)",
            rf"\b{assignment_verbs}\s+{labels}\s+(?:a|as|to)\s+(?P<value>.+?)(?=\s+(?:y|and)\s+(?:no|not)\b|[.!?;\r\n]|$)",
            r"\b(?:llama|llamá|llamar|rename|renombra|renombrá|renombrar)\s+(?:el\s+|the\s+)?bot\s+(?:a|as|to)\s+(?P<value>.+?)(?=[.!?;\r\n]|$)",
        )
    else:
        labels = r"(?:(?:la\s+)?descripci[oó]n(?:\s+del\s+bot)?|(?:the\s+)?bot\s+description|(?:the\s+)?description(?:\s+of\s+the\s+bot)?)"
        patterns = (
            rf"\b{assignment_verbs}\s+{labels}\s+(?:a|as|to)\s+(?P<value>.+?)(?=\s+(?:y|and)\s+(?:no|not)\b|[.!?;\r\n]|$)",
            rf"\b(?:describe|describí|describir)\s+(?:el\s+|the\s+)?bot\s+(?:como|as)\s+(?P<value>.+?)(?=[.!?;\r\n]|$)",
        )

    for pattern in patterns:
        match = re.search(pattern, message, flags=re.IGNORECASE)
        if match is None:
            continue
        value = match.group("value").strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'", "`"}:
            value = value[1:-1].strip()
        if value:
            return value
    return None


def _creative_full_replacement_intent(message: str) -> bool:
    if classify_editor_intent(message) != "mutation":
        return False
    pattern = re.compile(
        r"\b(?:inventame|inventa|creame|crea|armame|arma|make|create)\b"
        r"\s+(?:(?:un|el|este|otro|nuevo|a|the|this|new)\s+){0,2}(?:bot|flujo|flow)\b"
        r"|\b(?:inventame|inventa|creame|crea)\b.{0,24}\b(?:uno|algo|one)\b"
        r"|\b(?:armame|arma)\b.{0,32}\b(?:el que|lo que|uno|one)\b"
        r"|\b(?:cambiame|cambia|reemplaza|reemplazar|replace)\b"
        r".{0,40}\b(?:bot|flujo|flow)\b.{0,30}\b(?:otro|nuevo|distinto|different|new)\b"
        r"|\b(?:cambiame|cambia|reemplaza|reemplazar|replace)\b"
        r".{0,40}\b(?:por otro|por uno nuevo|with a new one)\b"
    )
    for clause in _analyze_intent(message):
        for predicate in clause.predicates:
            if any(
                word in {"descripcion", "description", "name", "nombre"}
                for word in predicate.words
            ):
                continue
            if not predicate.negated and pattern.search(" ".join(predicate.words)):
                return True
    return False


def _explicit_remove_any_intent(request: ChatRequest) -> bool:
    latest = next(
        (message.content for message in reversed(request.messages) if message.role == "user"),
        "",
    )
    destructive = {
        "borra",
        "borrar",
        "clear",
        "delete",
        "elimina",
        "eliminar",
        "limpia",
        "limpiar",
        "quita",
        "quitar",
        "remove",
        "remover",
        "saca",
        "sacar",
        "vacia",
        "vaciar",
    }
    words = set(re.findall(r"[a-z0-9_]+", latest.casefold()))
    return bool(words & destructive)


def _explicit_remove_all_intent(request: ChatRequest) -> bool:
    latest = next(
        (message.content for message in reversed(request.messages) if message.role == "user"),
        "",
    )
    destructive = {
        "borra",
        "borrar",
        "clear",
        "delete",
        "elimina",
        "eliminar",
        "limpia",
        "limpiar",
        "quita",
        "quitar",
        "remove",
        "remover",
        "saca",
        "sacar",
        "vacia",
        "vaciar",
    }
    editor_objects = {
        "acciones",
        "actions",
        "blocks",
        "bloques",
        "bot",
        "bots",
        "flow",
        "flows",
        "flujo",
        "flujos",
        "nodes",
        "nodos",
    }
    competing_objects = {
        "archivo",
        "carpeta",
        "contenido",
        "content",
        "document",
        "documento",
        "file",
        "folder",
    }
    editor_antecedent = False

    def destructive_token(word: str) -> tuple[str | None, bool]:
        if word in destructive:
            return word, False
        for suffix in ("las", "los", "la", "lo"):
            if word.endswith(suffix) and word[: -len(suffix)] in destructive:
                return word[: -len(suffix)], True
        return None, False

    for clause in _analyze_intent(latest):
        for predicate in clause.predicates:
            words = predicate.words
            if predicate.negated or predicate.has_exception:
                if any(word in competing_objects for word in words):
                    editor_antecedent = False
                elif any(word in editor_objects for word in words):
                    editor_antecedent = True
                continue
            for index, word in enumerate(words):
                destructive_word, has_object_pronoun = destructive_token(word)
                if destructive_word is None:
                    continue
                tail = words[index + 1 :]
                has_editor_object = any(item in tail for item in editor_objects)
                removes_all = (
                    ("todo" in tail or "everything" in tail)
                    and has_editor_object
                    or (
                        any(item in tail for item in ("all", "todas", "todos"))
                        and has_editor_object
                    )
                    or (
                        any(item in tail for item in ("bot", "flujo", "flow"))
                        and any(item in tail for item in ("completo", "entero", "entire", "complete"))
                    )
                    or (
                        destructive_word in {"clear", "vacia", "vaciar"}
                        and any(item in tail for item in ("bot", "flow", "flujo"))
                    )
                    or (has_object_pronoun and editor_antecedent)
                )
                if removes_all:
                    return True
            leaves_empty = (
                any(word in words for word in ("deja", "dejar", "leave"))
                and any(word in words for word in ("bot", "flujo", "flow"))
                and any(word in words for word in ("vacio", "empty"))
            )
            if leaves_empty:
                return True
            if any(word in competing_objects for word in words):
                editor_antecedent = False
            elif any(word in editor_objects for word in words):
                editor_antecedent = True
    return False


def _validate_updated_flow_provenance(
    nodes: dict[str, dict[str, object]],
    baseline_nodes: dict[str, dict[str, object]],
    actions: dict[str, ActionDefinition],
    request: ChatRequest,
) -> None:
    external_values: list[
        tuple[ExternalFactRequirement, ActionFieldDefinition, JsonValue]
    ] = []
    trusted_values: dict[tuple[str, str], list[JsonValue]] = {}
    for baseline_node in baseline_nodes.values():
        action_type = baseline_node.get("type")
        params = baseline_node.get("params")
        action = actions.get(action_type) if isinstance(action_type, str) else None
        if action is None or not isinstance(params, dict):
            continue
        for field in action.fields:
            if field.name in params:
                trusted_values.setdefault((action.id, field.name), []).append(params[field.name])

    for node in nodes.values():
        action = actions[str(node["type"])]
        params = node["params"]
        assert isinstance(params, dict)
        for field in action.fields:
            if field.name not in params:
                continue
            value = params[field.name]
            if is_pending_parameter(value):
                continue
            if field.name in action.defaults and _trusted_field_value_matches(
                field, value, action.defaults[field.name]
            ):
                continue
            if any(
                _trusted_field_value_matches(field, value, trusted)
                for trusted in trusted_values.get((action.id, field.name), [])
            ):
                continue
            if field.type == "condition":
                external_values.extend(
                    _condition_literal_requirements(action.id, action, field, value)
                )
                continue
            if classify_field(action, field) is not FieldSemantics.EXTERNAL:
                continue
            if action.category == "mouse":
                continue
            if isinstance(value, str) and _is_pure_runtime_reference(value):
                continue
            if (
                field.name in {"cell", "range"}
                and isinstance(value, str)
                and _is_deterministic_cell_template(value, request)
            ):
                continue
            external_values.append(
                (
                    ExternalFactRequirement.from_field(
                        action.id, field, action_title=action.title
                    ),
                    field,
                    value,
                )
            )

    requirements = tuple(dict.fromkeys(item[0] for item in external_values))
    assignments: dict[FactFieldRef, list[EvidenceAssignment]] = {}
    for assignment in build_evidence_ledger(request, requirements):
        assignments.setdefault(assignment.field_ref, []).append(assignment)
    missing = {
        requirement
        for requirement, field, value in external_values
        if not any(
            value_matches_assignment(field, value, assignment)
            for assignment in assignments.get(requirement.ref, [])
        )
    }
    if missing:
        raise ExternalFactValidationError(missing)


def _trusted_field_value_matches(
    field: ActionFieldDefinition, value: JsonValue, trusted: JsonValue
) -> bool:
    assignment = EvidenceAssignment(
        FactFieldRef("trusted", field.name),
        EvidenceSpan(0, trusted, "", 0, 0, frozenset()),
    )
    return value_matches_assignment(field, value, assignment)


def derive_public_proposal(
    validated: ValidatedUpdatedBot,
    request: ChatRequest,
    *,
    summary: str,
) -> DerivedProposal:
    context = request.editor_context
    assert context is not None
    baseline = context.working_bot if context.working_bot is not None else context.bot

    result_bot = copy.deepcopy(validated.bot)
    base_nodes = {node['id']: node for node in baseline['flow']['nodes']}
    action_defaults = {action.id: action.defaults for action in request.capabilities.actions}
    for node in result_bot['flow']['nodes']:
        before = base_nodes.get(node['id'])
        if before is None or before['type'] != node['type']:
            continue
        defaults = action_defaults.get(node['type'], {})
        effective_before = {**defaults, **before['params']}
        if json.dumps(effective_before, sort_keys=True) == json.dumps(node['params'], sort_keys=True):
            node['params'] = copy.deepcopy(before['params'])
    try:
        operations = derive_tree_operations(baseline, result_bot)
    except TreeDiffError as error:
        raise ProposalValidationError(str(error)) from error
    if not operations:
        raise ProposalValidationError(
            "La propuesta no contiene ningún cambio respecto al bot actual en el editor. Debes incluir las nuevas acciones solicitadas dentro del array 'flow'."
        )
    preview = mcp_preview_bot_patch(baseline, dump_tree_operations(operations))
    data = preview.get("data")
    applied = data.get("previewBot") if isinstance(data, dict) else None
    if (
        not preview.get("ok")
        or not isinstance(applied, dict)
        or canonicalize_bot(applied) != canonicalize_bot(result_bot)
    ):
        raise ProposalValidationError(
            "derived operations do not reproduce resulting bot"
        )
    return DerivedProposal(
        summary=summary,
        operations=operations,
        resulting_bot=result_bot,
        baseline_bot_revision=canonical_bot_hash(baseline),
    )
