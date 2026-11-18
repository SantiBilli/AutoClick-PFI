import json
import ntpath
import re
import unicodedata
from dataclasses import dataclass
from enum import Enum

from app.schemas import ActionDefinition, ActionFieldDefinition, ChatRequest, JsonValue


class FieldSemantics(Enum):
    INTERNAL = "internal"
    CONTROL = "control"
    EXTERNAL = "external"


@dataclass(frozen=True)
class FactFieldRef:
    action_id: str
    field_name: str

    @property
    def key(self) -> str:
        return f"{self.action_id}:{self.field_name}"


@dataclass(frozen=True)
class ExternalFactRequirement:
    ref: FactFieldRef
    field: ActionFieldDefinition
    action_title: str = ""
    semantic_label: str = ""

    @classmethod
    def from_field(
        cls,
        action_id: str,
        field: ActionFieldDefinition,
        *,
        action_title: str = "",
        semantic_label: str = "",
    ) -> "ExternalFactRequirement":
        return cls(
            FactFieldRef(action_id, field.name),
            field,
            action_title,
            semantic_label,
        )

    @property
    def action_id(self) -> str:
        return self.ref.action_id

    @property
    def key(self) -> str:
        return self.ref.key

    @property
    def label(self) -> str:
        return (self.semantic_label or self.field.label)[:80]

    def __hash__(self) -> int:
        return hash(self.ref)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, ExternalFactRequirement) and self.ref == other.ref

@dataclass(frozen=True)
class ExternalFactDiscovery:
    requirements: tuple[ExternalFactRequirement, ...]
    ambiguous_action_intent: bool
    mutation_index: int | None
    assignments: tuple["EvidenceAssignment", ...] = ()


@dataclass(frozen=True)
class PendingClarification:
    mutation_index: int
    intent: str
    requirements: tuple[ExternalFactRequirement, ...]
    assignments: tuple["EvidenceAssignment", ...]
    quantity: int = 1

    @property
    def missing(self) -> tuple[ExternalFactRequirement, ...]:
        if len(self.assignments) >= self.quantity:
            return ()
        return self.requirements


@dataclass(frozen=True)
class EvidenceSpan:
    span_id: int
    value: JsonValue
    raw: str
    start: int
    end: int
    labels: frozenset[str]


@dataclass(frozen=True)
class EvidenceAssignment:
    field_ref: FactFieldRef
    span: EvidenceSpan

    @property
    def requirement_key(self) -> str:
        return self.field_ref.key


@dataclass
class MatchingWork:
    edge_checks: int = 0
    matching_runs: int = 0
    budget_exhausted: bool = False


# The canonical catalog has 69 actions. These caps allow several facts per
# action while bounding adversarial requests independently of the 1 MiB body cap.
MAX_LEDGER_REQUIREMENTS = 256
MAX_EVIDENCE_SPANS = 256
MAX_MATCHING_EDGES = 4_096
MAX_MATCHING_RUNS = 4_096
MAX_MATCHING_CHECKS = 4_096


class _MatchingBudgetExceeded(RuntimeError):
    pass


_INTENT_STOP_WORDS = frozenset(
    {
        "accion", "agrega", "agregar", "archivo", "bloque", "bot", "completo",
        "crea", "crear", "datos", "exacto", "flujo", "para", "quiero", "ruta",
        "the", "with", "file", "action", "block",
    }
)
_STRONG_DOMAIN_TERMS = re.compile(
    r"\b(?:autoclick|automat\w*|automation|automate|rpa|"
    r"bots?|flujos?|flows?|bloques?|blocks?)\b"
)
_GENERIC_TECH_TERMS = re.compile(
    r"\b(?:excel|mouse|teclado|keyboard|navegador|browser|variables?|"
    r"archivos?|files?|carpetas?|folders?|http|urls?|webhooks?|windows)\b"
)
_UNAMBIGUOUS_ACTION_ALIAS = re.compile(
    r"\b(?:clic izquierdo|click izquierdo|left click|doble clic|doble click|"
    r"double click|clic derecho|click derecho|right click|presionar una? tecla|"
    r"pulsar una? tecla|press a? ?key|solicitud http|peticion http|http request|"
    r"(?:esper\w*|wait)\s+(?:[a-z0-9]+\s+){0,2}(?:segundos?|seconds?)|"
    r"how\s+(?:does\s+)?wait\s+work(?:s)?|"
    r"valor derecho de la condicion|right(?:-hand)? value of the condition)\b"
)
_ABSOLUTE_PATH = re.compile(
    r"(?<![a-z0-9_])(?:[a-z]:[\\/](?:[^\s,;]+)|"
    r"\\\\[^\\/\s]+[\\/][^\s,;]+)",
    re.IGNORECASE,
)
_URL = re.compile(r"https?://[^\s,;]+", re.IGNORECASE)
_BARE_DOMAIN = re.compile(r"(?<![@\w])(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:/[^\s,;]*)?", re.IGNORECASE)
_KNOWN_WEB_SERVICES = {
    "facebook": "https://facebook.com",
    "google": "https://google.com",
    "youtube": "https://youtube.com",
    "twitter": "https://twitter.com",
    "x": "https://x.com",
    "instagram": "https://instagram.com",
    "linkedin": "https://linkedin.com",
    "github": "https://github.com",
    "gmail": "https://mail.google.com",
    "reddit": "https://reddit.com",
    "wikipedia": "https://wikipedia.org",
}

_DIRECT_CLARIFICATION = re.compile(
    r"^(?:(?:por\s+favor|disculpa|disculpe|perdon),?\s*)?(?:¿\s*)?"
    r"(?:indicame|indica|decime|dime|digame|diga|proporcioname|proporciona|"
    r"compartime|comparte|especificame|especifica|confirmame|confirma|"
    r"necesito|(?:me\s+)?(?:puedes|podes|podrias|puede|podria)\s+"
    r"(?:indicar(?:me)?|decir(?:me)?|dar(?:me)?|proporcionar(?:me)?|"
    r"compartir(?:me)?|especificar(?:me)?|confirmar(?:me)?)|"
    r"me\s+(?:indicas|decis|dices|das|proporcionas|compartes|especificas|confirmas)|"
    r"(?:cual|que)\s+(?:es|seria)|como\s+se\s+llama)\b[^.!;\n\r]*[.?]?$"
)


def plain_text(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    return "".join(
        character for character in decomposed if not unicodedata.combining(character)
    )


def _identifier_words(value: str) -> set[str]:
    separated = re.sub(r"([a-z])([A-Z])", r"\1 \2", value.replace(".", " "))
    return {
        word
        for word in re.findall(r"[a-z0-9]+", plain_text(separated))
        if len(word) >= 3 and word not in _INTENT_STOP_WORDS
    }


def action_terms(action: ActionDefinition) -> set[str]:
    return (
        _identifier_words(action.id)
        | _identifier_words(action.title)
        | _identifier_words(action.category_name)
        | _identifier_words(action.description)
    )


def render_fact_labels(
    requirements: tuple[ExternalFactRequirement, ...],
) -> dict[FactFieldRef, str]:
    bases = {item.ref: _human_fact_label(item) for item in requirements}
    counts = {
        label: sum(other == label for other in bases.values())
        for label in set(bases.values())
    }
    rendered: dict[FactFieldRef, str] = {}
    used: set[str] = set()
    for requirement in sorted(requirements, key=lambda item: item.key):
        base = bases[requirement.ref]
        label = base
        if counts[base] > 1:
            purpose = plain_text(requirement.action_title).strip() or plain_text(
                requirement.action_id.replace(".", " ")
            )
            label = _label_with_suffix(base, f"para {purpose}")
        if label in used:
            suffix = plain_text(requirement.ref.field_name.replace(".", " "))
            label = _label_with_suffix(label, f"({suffix})")
        ordinal = 2
        candidate = label
        while candidate in used:
            candidate = _label_with_suffix(label, f"({ordinal})")
            ordinal += 1
        label = candidate
        rendered[requirement.ref] = label
        used.add(label)
    return rendered


def _label_with_suffix(base: str, suffix: str) -> str:
    bounded_suffix = suffix[:40].rstrip()
    available = 80 - len(bounded_suffix) - 1
    return f"{base[:available].rstrip()} {bounded_suffix}"


def _human_fact_label(requirement: ExternalFactRequirement) -> str:
    if requirement.semantic_label:
        return plain_text(requirement.semantic_label)
    labels = {
        "url": "la url exacta",
        "path": "la ruta absoluta del archivo",
        "source": "la ruta de origen exacta",
        "destination": "la ruta de destino exacta",
        "sheet": "la hoja exacta",
        "body": "el cuerpo exacto",
        "headers": "los encabezados exactos",
        "query": "los parametros exactos",
        "value": "el valor",
    }
    return labels.get(requirement.field.name, plain_text(requirement.field.label))


def _message_is_independently_in_domain(request: ChatRequest, message: str) -> bool:
    normalized = plain_text(message)
    if _STRONG_DOMAIN_TERMS.search(normalized):
        return True

    exact_action_reference = any(
        plain_text(action.id) in normalized
        for action in request.capabilities.actions
    )
    if exact_action_reference:
        return True
    return _UNAMBIGUOUS_ACTION_ALIAS.search(normalized) is not None


def _is_direct_external_fact_request(value: str) -> bool:
    return _DIRECT_CLARIFICATION.fullmatch(value.strip()) is not None


def request_is_in_domain(request: ChatRequest, message: str) -> bool:
    normalized = plain_text(message)
    if _message_is_independently_in_domain(request, normalized):
        return True

    current_has_technical_context = _GENERIC_TECH_TERMS.search(normalized) is not None
    if not current_has_technical_context:
        return False

    latest = plain_text(request.messages[-1].content)
    history = (
        request.messages[:-1]
        if normalized == latest
        else request.messages
    )
    prior_user_turns = (
        item.content
        for item in history
        if item.role == "user"
    )
    return any(
        _message_is_independently_in_domain(request, turn)
        for turn in prior_user_turns
    )


def _intended_actions(
    request_text: str, actions: list[ActionDefinition]
) -> tuple[list[ActionDefinition], bool]:
    normalized = plain_text(request_text)
    words = set(re.findall(r"[a-z0-9]+", normalized))
    mentioned_categories = {
        action.category
        for action in actions
        if words
        & (
            _identifier_words(action.category)
            | _identifier_words(action.category_name)
        )
    }
    if words & {"pagina", "sitio", "url", "website", "web"} or re.search(
        r"\bhttps?://", normalized
    ):
        mentioned_categories.add("browser")
    scored: list[tuple[int, ActionDefinition]] = []
    for action in actions:
        if mentioned_categories and action.category not in mentioned_categories:
            continue
        operation_terms = _identifier_words(action.id.split(".")[-1]) | _identifier_words(
            action.title
        )
        score = len(words & operation_terms) * 3
        if plain_text(action.id.replace(".", " ")) in normalized:
            score += 12
        title = plain_text(action.title)
        if re.search(rf"(?<![a-z0-9]){re.escape(title)}(?![a-z0-9])", normalized):
            score += 10
        if score >= 3:
            scored.append((score, action))

    if "excel" in words and re.search(
        r"\b[a-z]{1,3}\d+(?::[a-z]{1,3}\d+)?\b", normalized
    ):
        wants_read = re.search(r"\b(?:lee|leer|read|recorr\w*)\b", normalized)
        wants_write = re.search(r"\b(?:escrib\w*|write)\b", normalized)
        for action in actions:
            operation = action.id.split(".")[-1].casefold()
            if action.category == "excel" and (
                (wants_read and operation == "readcell")
                or (wants_write and operation == "writecell")
            ) and all(existing.id != action.id for _, existing in scored):
                scored.append((8, action))

        selected_excel_operations = {
            "readcell",
            "writecell",
        }
        scored = [
            (score, action)
            for score, action in scored
            if action.category != "excel"
            or action.id.split(".")[-1].casefold() in selected_excel_operations
        ]

    if not scored:
        category_matches = {
            action.id
            for action in actions
            if action.category in mentioned_categories
        }
        return [], len(category_matches) > 1

    best = max(score for score, _ in scored)
    selected = [action for score, action in scored if score >= max(3, best - 2)]
    if "excel" in words and re.search(
        r"\b(?:recorr\w*|misma\s+fila|cada\s+fila)\b", normalized
    ):
        selected = [
            action
            for action in selected
            if action.id not in {"excel.readRange", "excel.writeRange"}
        ]
    substantive_categories = {
        action.category
        for action in selected
        if action.category not in {"execution", "flow", "variables"}
    }
    return selected, len(substantive_categories) > 1


def classify_field(action: ActionDefinition, field: ActionFieldDefinition) -> FieldSemantics:
    output_fields = {output.field for output in action.outputs}
    if action.output is not None:
        output_fields.add(action.output.field)
    if field.type == "variable" or field.name in output_fields:
        return FieldSemantics.INTERNAL
    if action.category == "flow" or field.type == "condition":
        return FieldSemantics.CONTROL
    if field.type in {"file", "key", "text", "multiline", "json"}:
        return FieldSemantics.EXTERNAL
    if field.type in {"integer", "number", "boolean", "select"}:
        if field.name in action.defaults:
            return FieldSemantics.CONTROL
        return FieldSemantics.EXTERNAL
    return FieldSemantics.EXTERNAL


def _field_terms(field: ActionFieldDefinition) -> set[str]:
    terms = _identifier_words(field.label) | set(
        re.findall(r"[a-z0-9]+", plain_text(field.label))
    )
    type_terms = {
        "file": {"archivo", "file", "ruta", "path", "origen", "destino"},
        "key": {"tecla", "key"},
        "json": {"json", "cuerpo", "body", "payload", "encabezados", "headers", "query"},
        "integer": {"numero", "cantidad", "coordenada"},
        "number": {"numero", "cantidad", "coordenada"},
        "text": {"texto", "nombre", "titulo", "celda", "rango", "url"},
        "multiline": {"texto", "contenido"},
        "select": set(field.options or []),
    }
    return terms | {plain_text(term) for term in type_terms.get(field.type, set())}


def field_requested(field: ActionFieldDefinition, request_text: str) -> bool:
    normalized = plain_text(request_text)
    label_words = _identifier_words(field.label)
    distinctive = label_words - {"json", "texto", "text", "exacto"}
    if distinctive and any(
        re.search(rf"\b{re.escape(word)}\b", normalized) for word in distinctive
    ):
        return True
    generic_by_type = {
        "file": {"archivo", "file", "ruta", "path", "origen", "destino"},
        "key": {"tecla", "key"},
        "integer": {"numero", "cantidad", "coordenada"},
        "number": {"numero", "cantidad", "coordenada"},
    }
    return any(
        re.search(rf"\b{re.escape(term)}\b", normalized)
        for term in generic_by_type.get(field.type, set())
    )


def _json_values(value: str) -> list[JsonValue]:
    decoder = json.JSONDecoder()
    found: list[JsonValue] = []
    for match in re.finditer(r"[\[{]", value):
        try:
            parsed, _ = decoder.raw_decode(value[match.start() :])
        except json.JSONDecodeError:
            continue
        found.append(parsed)
    return found


def _span_labels(text: str, start: int) -> frozenset[str]:
    prefix = plain_text(text[max(0, start - 96) : start])
    clause = re.split(r"[.;\n]", prefix)[-1]
    labels = set(re.findall(r"[a-z0-9]+", clause))
    if re.search(r"\b(?:escrib\w*|write(?:s|ten|ting)?)\s*$", clause):
        labels.update({"valor", "value", "contenido", "content"})
    if re.search(r"\b(?:de|desde)\s*$", clause):
        labels.update({"origen", "source"})
    if re.search(r"\b(?:a|hacia|hasta)\s*$", clause):
        labels.update({"destino", "destination"})
    return frozenset(labels)


def extract_evidence_spans(text: str) -> tuple[EvidenceSpan, ...]:
    candidates: list[tuple[int, int, JsonValue, str]] = []
    # Preserve the literal replacement, including spaces. Quoted literals are
    # handled below; never infer a new value from the old value or the model.
    for match in re.finditer(
        r"\b(?:cambi[aá](?:me)?|reemplaz[aá](?:me)?|sustitu[ií])\s+(?:el\s+)?"
        r"(?:texto|contenido|valor)\s+[^,;\n]+?\s+por\s+"
        r"(?P<value>[^\"'\n,;]+?)(?=\s*[,;]|\s+(?:y\s+(?:manten|conserv|no\s+cambi)|manteniendo|conservando)\b|\.?$)",
        text, re.IGNORECASE,
    ):
        raw = match.group('value').strip().removesuffix('.')
        if raw:
            start = match.start('value')
            candidates.append((start, start + len(raw), raw, raw))
    for match in re.finditer(
        r"\b[A-Za-z][A-Za-z0-9._-]+\s+[A-Za-z][A-Za-z0-9_-]*\s*[:=]\s*"
        r"(?:\"([^\"\n]+)\"|'([^'\n]+)'|([^.;\n]+?)(?=\s+(?:y|e|and)\s+\w+\s*[:=]|,\s*\w+\s*[:=]|[.;\n]|$))",
        text,
    ):
        raw = next(group for group in match.groups() if group is not None).strip()
        if raw.startswith(("{", "[")):
            continue
        if re.fullmatch(r'-?\d+(?:[.,]\d+)?', raw):
            continue  # Preserve the typed numeric span extracted below.
        start = text.find(raw, match.start(), match.end())
        candidates.append((start, start + len(raw), raw, raw))
    for match in _ABSOLUTE_PATH.finditer(text):
        raw = match.group().rstrip(".")
        candidates.append((match.start(), match.start() + len(raw), raw, raw))
    for match in _URL.finditer(text):
        candidates.append((*match.span(), match.group().rstrip("."), match.group().rstrip(".")))
    for match in _BARE_DOMAIN.finditer(text):
        raw = match.group().rstrip(".")
        candidates.append((match.start(), match.start() + len(raw), raw, raw))
    for service_name, service_url in _KNOWN_WEB_SERVICES.items():
        for match in re.finditer(rf"\b{re.escape(service_name)}\b", text, re.IGNORECASE):
            candidates.append((match.start(), match.end(), service_url, service_url))
    decoder = json.JSONDecoder()
    for match in re.finditer(r"[\[{]", text):
        try:
            value, end = decoder.raw_decode(text[match.start() :])
        except json.JSONDecodeError:
            continue
        raw = text[match.start() : match.start() + end]
        candidates.append((match.start(), match.start() + end, value, raw))
    for match in re.finditer(
        r"(?<![\w.,-])-?\d+(?:[.,]\d+)?(?!\w|,\d|\.\d)", text
    ):
        raw = match.group()
        value: JsonValue = float(raw.replace(",", ".")) if re.search(r"[.,]", raw) else int(raw)
        candidates.append((*match.span(), value, raw))
    for match in re.finditer(r"\b[A-Za-z]{1,3}\d+(?::[A-Za-z]{1,3}\d+)?\b", text):
        candidates.append((*match.span(), match.group(), match.group()))
    for match in re.finditer(r"[\"']([^\"'\n]{1,1000})[\"']", text):
        candidates.append((match.start(1), match.end(1), match.group(1), match.group(1)))
    for match in re.finditer(
        r"\b([\wÁÉÍÓÚÜÑáéíóúüñ]{1,30}(?:\s+[\wÁÉÍÓÚÜÑáéíóúüñ]{1,30}){0,3})"
        r"\s*(?::|=)\s*"
        r"([^.;\n]{1,1000}?)(?=\s+(?:y|e|and)\s+\w+\s*[:=]|,\s*\w+\s*[:=]|[.;\n]|$)",
        text,
        re.IGNORECASE,
    ):
        label = match.group(1).strip()
        raw_value = match.group(2).strip()
        normalized_value = plain_text(raw_value)
        value: JsonValue = (
            normalized_value in {"true", "si", "verdadero"}
            if normalized_value in {"true", "false", "si", "no", "verdadero", "falso"}
            else raw_value
        )
        if (
            re.fullmatch(r"[A-Za-z]{1,3}\d+(?::[A-Za-z]{1,3}\d+)?", label)
            or _ABSOLUTE_PATH.fullmatch(raw_value)
            or re.fullmatch(r"-?\d+(?:[.,]\d+)?", raw_value)
            or raw_value.startswith(("{", "["))
        ):
            continue
        candidates.append((match.start(2), match.end(2), value, raw_value))
    for match in re.finditer(
        r"\b(?:hoja|worksheet|pestaña|pestana|hora)\b[\s\w]{0,50}?(?:es|se llama|llamada|nombrada|llamado)\s+([\w.-]+)",
        text,
        re.IGNORECASE,
    ):
        raw = match.group(1).rstrip(".")
        candidates.append((match.start(1), match.start(1) + len(raw), raw, raw))
    for match in re.finditer(
        r"\b(?:hoja|worksheet|pestaña|pestana)\b\s*(?:es|se llama|llamada)?\s+([\w.-]+)",
        text,
        re.IGNORECASE,
    ):
        raw = match.group(1).rstrip(".")
        candidates.append((match.start(1), match.start(1) + len(raw), raw, raw))
    for match in re.finditer(r"\bSheet\d+\b", text, re.IGNORECASE):
        raw = match.group()
        candidates.append((match.start(), match.end(), raw, raw))
    for match in re.finditer(
        r"\b(?:hoja|worksheet)\b\s+para\s+(?:leer|read|escribir|write)\s+"
        r"(?:celda|cell|rango|range)\s+(?:es|se llama|llamada)\s+([\w.-]+)",
        text,
        re.IGNORECASE,
    ):
        raw = match.group(1).rstrip(".")
        candidates.append((match.start(1), match.start(1) + len(raw), raw, raw))
    for match in re.finditer(
        r"\b(?:escrib\w*|write(?:s|ten|ting)?)\s+(.+?)\s+en\s+"
        r"(?=[A-Za-z]:[\\/]|\\\\|(?:la\s+)?(?:celda|columna)\b|[A-Za-z](?:\d|\s))",
        text,
        re.IGNORECASE,
    ):
        value = match.group(1).strip()
        if plain_text(value) not in {"el resultado", "la salida", "resultado", "salida"}:
            candidates.append((match.start(1), match.start(1) + len(value), value, value))
    for match in re.finditer(
        r"\b(?:escrib\w*|write(?:s|ten|ting)?)\s+([^\s,.;]{1,80})",
        text,
        re.IGNORECASE,
    ):
        value = match.group(1)
        if plain_text(value) not in {"resultado", "salida"}:
            candidates.append((match.start(1), match.end(1), value, value))
    for match in re.finditer(
        r"\b(?:clave|key|valor|value|contenido|content)\b\s+(?:literal\s+)?"
        r"([^\s,.;]{1,80})",
        text,
        re.IGNORECASE,
    ):
        candidates.append((match.start(1), match.end(1), match.group(1), match.group(1)))

    occupied: list[tuple[int, int]] = []
    spans: list[EvidenceSpan] = []
    for start, end, value, raw in sorted(
        candidates, key=lambda item: (item[0], -(item[1] - item[0]))
    ):
        if any(start >= left and end <= right for left, right in occupied):
            continue
        occupied.append((start, end))
        explicit_prefix = plain_text(text[max(0, start - 64) : start])
        explicit_clause = re.split(r"[.;\n]", explicit_prefix)[-1]
        explicit_labels = set(re.findall(r"[a-z0-9]+", explicit_clause))
        spans.append(
            EvidenceSpan(
                span_id=len(spans),
                value=value,
                raw=raw,
                start=start,
                end=end,
                labels=_span_labels(text, start) | frozenset(explicit_labels),
            )
        )
    return tuple(spans)


def _typed_value_matches(field: ActionFieldDefinition, value: str) -> bool:
    stripped = value.strip().strip(". ")
    if not stripped or len(stripped) > 4_096:
        return False
    if field.type == "file":
        return _ABSOLUTE_PATH.search(stripped) is not None
    label = plain_text(field.label)
    if field.type == "text" and "url" in label:
        return (
            re.fullmatch(r"https?://\S+", stripped, re.IGNORECASE) is not None
            or re.fullmatch(r"(?:[a-z0-9-]+\.)+[a-z]{2,}(?:/\S*)?", stripped, re.IGNORECASE)
            is not None
        )
    if field.type == "text" and any(term in label for term in ("celda", "cell")):
        return re.fullmatch(
            r"[A-Za-z]{1,3}\d+(?::[A-Za-z]{1,3}\d+)?", stripped
        ) is not None
    if field.type == "text" and any(term in label for term in ("rango", "range")):
        return re.fullmatch(r"[A-Za-z]{1,3}\d+:[A-Za-z]{1,3}\d+", stripped) is not None
    if field.type == "text" and any(term in label for term in ("hoja", "worksheet")):
        return (
            re.fullmatch(r"[\w.-]{1,80}", stripped, re.UNICODE) is not None
            and re.fullmatch(r"[A-Za-z]{1,3}\d+(?::[A-Za-z]{1,3}\d+)?", stripped) is None
        )
    if field.type == "json":
        return bool(_json_values(stripped))
    if field.type in {"integer", "number"}:
        return re.fullmatch(r"-?\d+(?:[.,]\d+)?", stripped) is not None
    if field.type == "boolean":
        return plain_text(stripped) in {"true", "false", "si", "no", "verdadero", "falso"}
    if field.type == "select":
        return any(stripped.casefold() == option.casefold() for option in field.options or [])
    if field.type == "key":
        return len(stripped) <= 80 and re.fullmatch(r"[\w+ -]+", stripped) is not None
    if field.type in {"text", "multiline"}:
        return len(stripped) <= 1_000 and "?" not in stripped and "\n" not in stripped
    return False


def _allows_unlabeled_single(requirement: ExternalFactRequirement) -> bool:
    field = requirement.field
    if field.type in {"file", "json", "integer", "number", "boolean", "select", "key"}:
        return True
    label = plain_text(field.label)
    return field.type == "text" and (
        "worksheet" in requirement.action_id.casefold()
        or any(
            term in label
            for term in ("hoja", "worksheet", "celda", "cell", "rango", "range", "url")
        )
    )


def _span_compatible(field: ActionFieldDefinition, span: EvidenceSpan) -> bool:
    if field.type == "json":
        return isinstance(span.value, (dict, list))
    if field.type == "integer":
        return isinstance(span.value, int) and not isinstance(span.value, bool)
    if field.type == "number":
        return isinstance(span.value, (int, float)) and not isinstance(span.value, bool)
    if field.type == "boolean":
        return isinstance(span.value, bool)
    if not isinstance(span.value, str):
        return False
    return _typed_value_matches(field, span.value)


def _label_matches(
    requirement: ExternalFactRequirement,
    span: EvidenceSpan,
    rendered_label: str | None = None,
) -> bool:
    if rendered_label is not None:
        words = set(re.findall(r"[a-z0-9]+", plain_text(rendered_label)))
        if words and words.issubset(span.labels):
            return True
        condition_match = re.fullmatch(
            r"condition\.(\d+)\.(left|right)", requirement.ref.field_name
        )
        if condition_match:
            index, operand = condition_match.groups()
            side = "izquierdo" if operand == "left" else "derecho"
            if {"valor", side, "condicion", str(int(index) + 1)}.issubset(
                span.labels
            ):
                return True
            if operand == "right" and span.labels.intersection(
                {"menor", "mayor", "igual", "less", "greater"}
            ):
                return True
        return False
    field_terms = _identifier_words(requirement.field.label) | set(
        re.findall(r"[a-z0-9]+", plain_text(requirement.field.label))
    ) | _identifier_words(requirement.field.name) | set(
        re.findall(r"[a-z0-9]+", plain_text(requirement.field.name))
    )
    if requirement.field.type == "file":
        field_terms.update({"excel", "archivo", "libro", "planilla", "file", "path", "ruta", "documento"})
    if requirement.field.name == "sheet":
        field_terms.update({"hoja", "sheet", "worksheet", "hora", "pestana", "pestaña", "llama", "llamada"})
    if requirement.field.name == "value":
        field_terms.update({"valor", "value", "ponga", "poner", "pon", "escriba", "escribir", "escribe", "texto", "resultado", "contenido"})
    if requirement.field.name == "text" and requirement.action_id.startswith("keyboard."):
        field_terms.update({"texto", "text", "escribir", "escribe", "escriba", "tipear", "teclear", "write", "type", "ingresar", "ingresa", "contenido"})

    action_specific = _identifier_words(requirement.action_id) | set(
        re.findall(r"[a-z0-9]+", plain_text(requirement.action_id))
    )
    if requirement.action_id.startswith("excel."):
        action_specific.update({"excel", "libro", "planilla", "hoja", "sheet", "notas"})
    operation = requirement.action_id.split(".")[-1].casefold()
    if operation.startswith("read"):
        action_specific.update({"leer", "lee", "lectura"})
    if operation.startswith("write"):
        action_specific.update({"escribir", "escribe", "ponga", "poner", "pon", "coloque", "colocar"})
    same_field_refs = requirement.field.name in {"cell", "range", "value"}
    if same_field_refs and action_specific:
        return bool(field_terms & set(span.labels)) and bool(
            action_specific & set(span.labels)
        )
    return bool(field_terms & set(span.labels))


def assign_evidence(
    requirements: tuple[ExternalFactRequirement, ...],
    spans: tuple[EvidenceSpan, ...],
    *,
    work: MatchingWork | None = None,
) -> tuple[EvidenceAssignment, ...]:
    tracker = work if work is not None else MatchingWork()
    if not requirements or not spans:
        return ()
    if len(requirements) > MAX_LEDGER_REQUIREMENTS or len(spans) > MAX_EVIDENCE_SPANS:
        tracker.budget_exhausted = True
        return ()
    labels = render_fact_labels(requirements)
    base_labels = [_human_fact_label(item) for item in requirements]
    raw_compatible: dict[FactFieldRef, tuple[EvidenceSpan, ...]] = {}
    labeled: dict[FactFieldRef, tuple[EvidenceSpan, ...]] = {}
    try:
        for requirement in requirements:
            compatible_spans: list[EvidenceSpan] = []
            for span in spans:
                _consume_matching_check(tracker)
                if _span_compatible(requirement.field, span):
                    compatible_spans.append(span)
            raw_compatible[requirement.ref] = tuple(compatible_spans)

            rendered_label = (
                labels[requirement.ref]
                if requirement.semantic_label
                or base_labels.count(_human_fact_label(requirement)) > 1
                else None
            )
            labeled_spans: list[EvidenceSpan] = []
            for span in compatible_spans:
                _consume_matching_check(tracker)
                if _label_matches(requirement, span, rendered_label):
                    labeled_spans.append(span)
            labeled[requirement.ref] = tuple(labeled_spans)
    except _MatchingBudgetExceeded:
        tracker.budget_exhausted = True
        return ()
    explicitly_bound = {
        span.span_id
        for candidates in labeled.values()
        for span in candidates
    }
    compatible = {
        requirement.ref: tuple(
            span
            for span in raw_compatible[requirement.ref]
            if span.span_id not in explicitly_bound
            or span in labeled[requirement.ref]
        )
        if not requirement.semantic_label
        and base_labels.count(_human_fact_label(requirement)) == 1
        else ()
        for requirement in requirements
    }
    ordered = tuple(
        sorted(
            requirements,
            key=lambda item: (
                0 if labeled[item.ref] else 1,
                len(labeled[item.ref] or compatible[item.ref]),
                item.key,
            ),
        )
    )
    edges: dict[FactFieldRef, tuple[int, ...]] = {}
    edge_count = 0
    for item in ordered:
        candidates = tuple(
            span.span_id for span in (labeled[item.ref] or compatible[item.ref])
        )
        edge_count += len(candidates)
        if edge_count > MAX_MATCHING_EDGES:
            tracker.budget_exhausted = True
            return ()
        edges[item.ref] = candidates
    by_id = {span.span_id: span for span in spans}
    try:
        maximum = _maximum_matching(tuple(item.ref for item in ordered), edges, work=tracker)
        target = len(maximum)
        stable: dict[FactFieldRef, EvidenceSpan] = {}
        for ref, span_id in maximum.items():
            remaining_refs = tuple(item_ref for item_ref in edges if item_ref != ref)
            remaining_edges = {
                item_ref: candidates
                for item_ref, candidates in edges.items()
                if item_ref != ref
            }
            if len(_maximum_matching(remaining_refs, remaining_edges, work=tracker)) == target:
                continue
            preserving = [
                forced_span
                for forced_span in edges[ref]
                if forced_span != span_id
                and 1 + len(
                    _maximum_matching(
                        remaining_refs,
                        {
                            item_ref: tuple(
                                candidate
                                for candidate in candidates
                                if candidate != forced_span
                            )
                            for item_ref, candidates in remaining_edges.items()
                        },
                        work=tracker,
                    )
                )
                == target
            ]
            if any(
                not _json_values_match(by_id[span_id].value, by_id[item].value)
                for item in preserving
            ):
                continue
            stable[ref] = by_id[span_id]
    except _MatchingBudgetExceeded:
        tracker.budget_exhausted = True
        return ()
    return tuple(
        EvidenceAssignment(requirement.ref, stable[requirement.ref])
        for requirement in requirements
        if requirement.ref in stable
    )


def _maximum_matching(
    refs: tuple[FactFieldRef, ...],
    edges: dict[FactFieldRef, tuple[int, ...]],
    *,
    work: MatchingWork | None,
) -> dict[FactFieldRef, int]:
    if work is not None:
        if work.matching_runs >= MAX_MATCHING_RUNS:
            raise _MatchingBudgetExceeded
        work.matching_runs += 1
    span_to_ref: dict[int, FactFieldRef] = {}

    for ref in refs:
        pending = [ref]
        visited_refs = {ref}
        visited_spans: set[int] = set()
        parent: dict[FactFieldRef, tuple[FactFieldRef, int]] = {}
        free_span: int | None = None
        terminal_ref: FactFieldRef | None = None
        while pending and free_span is None:
            current = pending.pop()
            for span_id in edges.get(current, ()):
                if work is not None:
                    _consume_matching_check(work)
                if span_id in visited_spans:
                    continue
                visited_spans.add(span_id)
                owner = span_to_ref.get(span_id)
                if owner is None:
                    free_span = span_id
                    terminal_ref = current
                    break
                if owner not in visited_refs:
                    visited_refs.add(owner)
                    parent[owner] = (current, span_id)
                    pending.append(owner)
        if free_span is None:
            continue
        assert terminal_ref is not None
        current = terminal_ref
        span_id = free_span
        while True:
            span_to_ref[span_id] = current
            if current == ref:
                break
            current, span_id = parent[current]
    return {ref: span_id for span_id, ref in span_to_ref.items()}


def _consume_matching_check(work: MatchingWork) -> None:
    if work.edge_checks >= MAX_MATCHING_CHECKS:
        raise _MatchingBudgetExceeded
    work.edge_checks += 1


def build_evidence_ledger(
    request: ChatRequest,
    requirements: tuple[ExternalFactRequirement, ...],
    *,
    mutation_index: int | None = None,
    work: MatchingWork | None = None,
) -> tuple[EvidenceAssignment, ...]:
    tracker = work if work is not None else MatchingWork()
    if len(requirements) > MAX_LEDGER_REQUIREMENTS:
        tracker.budget_exhausted = True
        return ()
    start = mutation_index if mutation_index is not None else 0
    user_text = " ".join(
        message.content
        for message in request.messages[start:]
        if message.role == "user"
    )
    spans = extract_evidence_spans(user_text)
    if len(spans) > MAX_EVIDENCE_SPANS:
        tracker.budget_exhausted = True
        return ()
    url_requirements = tuple(
        item for item in requirements
        if item.field.type == "text" and "url" in plain_text(item.field.label)
    )
    url_spans = tuple(
        span for span in spans
        if isinstance(span.value, str) and _typed_value_matches(
            url_requirements[0].field, span.value
        )
    ) if url_requirements else ()
    if len(url_requirements) == 1 and len(url_spans) > 1:
        return tuple(
            EvidenceAssignment(url_requirements[0].ref, span)
            for span in url_spans
        )
    primary = assign_evidence(requirements, spans, work=tracker)
    if tracker.budget_exhausted:
        return ()
    labels = render_fact_labels(requirements)
    base_labels = [_human_fact_label(item) for item in requirements]
    assigned = list(primary)
    owned_spans = {item.span.span_id: item.field_ref for item in primary}
    stable_refs = {item.field_ref for item in primary}
    unresolved = [item for item in requirements if item.ref not in stable_refs]
    unresolved_owners: dict[int, set[FactFieldRef]] = {}
    try:
        for span in spans:
            owners: set[FactFieldRef] = set()
            for item in unresolved:
                _consume_matching_check(tracker)
                if not _span_compatible(item.field, span):
                    continue
                _consume_matching_check(tracker)
                rendered_label = (
                    labels[item.ref]
                    if item.semantic_label
                    or base_labels.count(_human_fact_label(item)) > 1
                    else None
                )
                if _label_matches(item, span, rendered_label) or _label_matches(item, span, None):
                    owners.add(item.ref)
            unresolved_owners[span.span_id] = owners
    except _MatchingBudgetExceeded:
        tracker.budget_exhausted = True
        return ()
    def _can_claim_unresolved(req_ref: FactFieldRef, span_id: int) -> bool:
        owners = unresolved_owners.get(span_id, set())
        if req_ref in owners:
            return True
        return False

    multi_value_refs = {
        item.ref
        for item in unresolved
        if any(item.ref in owners for owners in unresolved_owners.values())
    }
    try:
        for requirement in requirements:
            if requirement.ref not in stable_refs and requirement.ref not in multi_value_refs:
                continue
            for span in spans:
                _consume_matching_check(tracker)
                owner = owned_spans.get(span.span_id)
                if owner is not None and owner != requirement.ref and requirement.field.name not in {"sheet", "path"}:
                    continue
                if not _span_compatible(requirement.field, span):
                    continue
                if (
                    requirement.ref not in stable_refs
                    and not _can_claim_unresolved(requirement.ref, span.span_id)
                ):
                    continue
                _consume_matching_check(tracker)
                rendered_label = (
                    labels[requirement.ref]
                    if requirement.semantic_label
                    or base_labels.count(_human_fact_label(requirement)) > 1
                    else None
                )
                if not (_label_matches(requirement, span, rendered_label) or _label_matches(requirement, span, None)):
                    continue
                if all(
                    item.field_ref != requirement.ref
                    or item.span.span_id != span.span_id
                    for item in assigned
                ):
                    assigned.append(EvidenceAssignment(requirement.ref, span))
                    owned_spans[span.span_id] = requirement.ref
    except _MatchingBudgetExceeded:
        tracker.budget_exhausted = True
        return ()
    return tuple(assigned)


def _explicit_field_value(field: ActionFieldDefinition, reply: str) -> str | None:
    normalized = plain_text(reply)
    for term in sorted(_field_terms(field), key=len, reverse=True):
        match = re.search(
            rf"\b{re.escape(term)}\b\s*(?::|=|es|sea|se llama)\s+(.+?)(?:[.;]|$)",
            normalized,
        )
        if match and _typed_value_matches(field, match.group(1)):
            return reply[match.start(1) : match.end(1)].strip()
    return None


def associate_reply(
    requirements: tuple[ExternalFactRequirement, ...], reply: str
) -> dict[FactFieldRef, str]:
    spans = extract_evidence_spans(reply)
    if (
        len(requirements) == 1
        and not spans
        and _allows_unlabeled_single(requirements[0])
        and _typed_value_matches(requirements[0].field, reply)
    ):
        spans = (
            EvidenceSpan(
                span_id=0,
                value=reply.strip(),
                raw=reply.strip(),
                start=0,
                end=len(reply),
                labels=frozenset(),
            ),
        )
    # When a clarification asks for several equivalent values (for example two
    # URLs), their left-to-right order is the only deterministic provenance
    # available. Do not apply this to unlike fields, where labels are required.
    if (
        len(requirements) > 1
        and all("url" in plain_text(item.field.label) for item in requirements)
        and len(spans) == len(requirements)
        and all(_span_compatible(item.field, span) for item, span in zip(requirements, spans, strict=True))
    ):
        return {
            item.ref: (span.raw if re.match(r"https?://", span.raw, re.IGNORECASE) else "https://" + span.raw)
            for item, span in zip(requirements, spans, strict=True)
        }
    return {
        assignment.field_ref: assignment.span.raw
        for assignment in assign_evidence(requirements, spans)
    }


def _clarification_requirements(
    requirements: tuple[ExternalFactRequirement, ...], clarification: str
) -> tuple[ExternalFactRequirement, ...]:
    normalized = plain_text(clarification)
    labels = render_fact_labels(requirements)
    selected = tuple(
        requirement
        for requirement in requirements
        if labels[requirement.ref] in normalized
    )
    return selected or requirements


def _is_explicit_continuation(value: str) -> bool:
    normalized = plain_text(value)
    return re.search(
        r"\b(?:segui|continua|continuemos|usa ese dato|usa esos datos|"
        r"todavia no|aun no|no lo tengo|no dispongo)\b",
        normalized,
    ) is not None


def _references_pending_action(
    value: str, actions: list[ActionDefinition]
) -> bool:
    normalized = plain_text(value)
    references = any(
        any(
            re.search(rf"\b{re.escape(term)}\b", normalized)
            for term in action_terms(action)
            if len(term) >= 4
        )
        for action in actions
    )
    continuation = re.search(
        r"\b(?:segui|continua|continuemos|retoma|completa|agrega|aplica|usa)\b",
        normalized,
    ) is not None
    return references and continuation


def _dynamic_condition_requirements(
    assistant_message: str,
    user_reply: str,
    intended: list[ActionDefinition],
    actions: list[ActionDefinition],
) -> tuple[ExternalFactRequirement, ...]:
    normalized_assistant = plain_text(assistant_message)
    normalized_reply = plain_text(user_reply)
    references = {
        ("left" if side == "izquierdo" else "right", int(index) - 1)
        for side, index in re.findall(
            r"valor\s+(izquierdo|derecho)\s+de\s+la\s+condicion\s+(\d{1,3})",
            normalized_assistant,
        )
        if 1 <= int(index) <= MAX_LEDGER_REQUIREMENTS
    }
    if not references:
        return ()
    spans = extract_evidence_spans(user_reply)
    requirements: list[ExternalFactRequirement] = []
    condition_actions = [
        action
        for action in intended
        if any(field.type == "condition" for field in action.fields)
    ]
    if not condition_actions:
        condition_actions = [
            action
            for action in intended
            if action.category == "flow"
        ]
    if not condition_actions:
        condition_actions = [
            action
            for action in actions
            if action.id == "flow.if"
        ]
    for action in condition_actions:
        condition_field = next(
            (field for field in action.fields if field.type == "condition"), None
        )
        if condition_field is None:
            continue
        for operand, index in sorted(references, key=lambda item: (item[1], item[0])):
            side = "izquierdo" if operand == "left" else "derecho"
            semantic_label = f"el valor {side} de la condicion {index + 1}"
            if semantic_label not in normalized_reply:
                continue
            matching_span = next(
                (
                    span
                    for span in spans
                    if {"valor", side, "condicion", str(index + 1)}.issubset(
                        span.labels
                    )
                ),
                None,
            )
            if matching_span is None:
                continue
            field = _dynamic_literal_field(condition_field, matching_span.value)
            requirements.append(
                ExternalFactRequirement(
                    FactFieldRef(action.id, f"{condition_field.name}.{index}.{operand}"),
                    field,
                    action.title,
                    semantic_label,
                )
            )
    if len(requirements) > MAX_LEDGER_REQUIREMENTS:
        return ()
    labels = render_fact_labels(tuple(requirements))
    return tuple(
        item
        for item in requirements
        if labels[item.ref] in normalized_assistant
    )


def _dynamic_literal_field(
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


def _base_requirements(
    request: ChatRequest, mutation_index: int
) -> tuple[tuple[ExternalFactRequirement, ...], bool, list[ActionDefinition]]:
    request_text = request.messages[mutation_index].content
    intended, ambiguous = _intended_actions(request_text, request.capabilities.actions)
    if any(
        action.category == "excel"
        and any(field.name == "workbookVariable" for field in action.fields)
        for action in intended
    ) and not any(action.id == "excel.create" for action in intended):
        opener = next(
            (action for action in request.capabilities.actions if action.id == "excel.open"),
            None,
        )
        if opener is not None and opener not in intended:
            intended.append(opener)

    requirements: dict[FactFieldRef, ExternalFactRequirement] = {}
    has_value_producer = any(action.outputs for action in intended)
    normalized_request = plain_text(request_text)
    for action in intended:
        for field in action.fields:
            semantics = classify_field(action, field)
            requested_optional = not field.required and field_requested(field, request_text)
            if semantics is not FieldSemantics.EXTERNAL:
                continue
            label = plain_text(field.label)
            if (
                field.type in {"text", "json"}
                and label in {"valor", "valores", "value", "values"}
                and has_value_producer
                and re.search(r"\b(?:resultado|result|salida|output)\b", normalized_request)
            ):
                continue
            if (
                field.name in {"cell", "range"}
                and action.id.split(".")[-1].casefold().startswith(("read", "write"))
                and re.search(
                    r"\b[A-Za-z]{1,3}\d+(?::[A-Za-z]{1,3}\d+)?\b",
                    request_text,
                )
            ):
                continue
            if field.name in action.defaults and not requested_optional:
                continue
            if field.required or requested_optional:
                item = ExternalFactRequirement.from_field(
                    action.id, field, action_title=action.title
                )
                requirements.setdefault(item.ref, item)
    return tuple(requirements.values()), ambiguous, intended


def discover_external_facts(
    request: ChatRequest, *, mutation_index: int | None = None
) -> ExternalFactDiscovery:
    """Discover facts for a turn explicitly selected by the model.

    Lexical intent classification is deliberately not part of normal routing.
    Callers must provide the selected mutation turn after parsing the model
    output; otherwise informational turns cannot trigger clarification.
    """
    if mutation_index is None:
        return ExternalFactDiscovery((), False, None)
    if not 0 <= mutation_index < len(request.messages):
        return ExternalFactDiscovery((), False, None)
    if request.messages[mutation_index].role != "user":
        return ExternalFactDiscovery((), False, None)
    requirements, ambiguous, intended = _base_requirements(request, mutation_index)
    latest_index = len(request.messages) - 1
    assignments: tuple[EvidenceAssignment, ...] = ()

    if mutation_index != latest_index:
        if latest_index < 2 or request.messages[-2].role != "assistant":
            return ExternalFactDiscovery((), False, None)
        latest = request.messages[-1].content
        dynamic = _dynamic_condition_requirements(
            request.messages[-2].content,
            latest,
            intended,
            request.capabilities.actions,
        )
        requirements = tuple(dict.fromkeys((*requirements, *dynamic)))
        requested = _clarification_requirements(requirements, request.messages[-2].content)
        spans = extract_evidence_spans(latest)
        if (
            len(requested) == 1
            and not spans
            and _allows_unlabeled_single(requested[0])
            and _typed_value_matches(requested[0].field, latest)
        ):
            spans = (
                EvidenceSpan(0, latest.strip(), latest.strip(), 0, len(latest), frozenset()),
            )
        assignments = assign_evidence(requested, spans)
        if (
            len(requested) > 1
            and all("url" in plain_text(item.field.label) for item in requested)
            and len(spans) == len(requested)
        ):
            assignments = tuple(
                EvidenceAssignment(item.ref, span)
                for item, span in zip(requested, spans, strict=True)
            )
        active = (
            bool(assignments)
            or _is_explicit_continuation(latest)
            or _references_pending_action(latest, intended)
        )
        if not active:
            return ExternalFactDiscovery((), False, None)

    history_assignments = build_evidence_ledger(
        request, requirements, mutation_index=mutation_index
    )
    assigned_refs = {
        assignment.field_ref
        for assignment in (*history_assignments, *assignments)
    }
    missing = tuple(
        requirement
        for requirement in requirements
        if requirement.ref not in assigned_refs
    )
    combined = {
        assignment.field_ref: assignment
        for assignment in (*history_assignments, *assignments)
    }
    return ExternalFactDiscovery(
        missing, ambiguous, mutation_index, tuple(combined.values())
    )


def pending_clarification(
    request: ChatRequest, *, mutation_index: int | None = None
) -> PendingClarification | None:
    """Reconstruct pending state only from the immediately preceding clarification.

    The public contract stores assistant text, so the text must still satisfy the
    same bounded clarification grammar and mention catalog-derived fields. An
    arbitrary assistant answer therefore cannot activate continuation state.
    """
    index = mutation_index
    if index is None:
        if len(request.messages) < 3 or request.messages[-2].role != "assistant":
            return None
        index = len(request.messages) - 3
    if index < 0 or index + 2 >= len(request.messages):
        return None
    mutation, assistant, reply = request.messages[index:index + 3]
    if mutation.role != "user" or assistant.role != "assistant" or reply.role != "user":
        return None
    discovery = discover_external_facts(request, mutation_index=index)
    if not discovery.requirements:
        # A model clarification can disambiguate an otherwise underspecified
        # request (for example "two pages") without naming the action ID.
        if not re.search(
            r"\b(?:url|paginas?|p[aá]ginas?|sitios?|website|web|navegador|browser)\b",
            plain_text(mutation.content),
        ):
            return None
        candidates = tuple(
            ExternalFactRequirement.from_field(action.id, field, action_title=action.title)
            for action in request.capabilities.actions
            if action.category == "browser"
            for field in action.fields
            if field.type == "text" and "url" in plain_text(field.label)
        )
        if len(candidates) != 1:
            return None
        discovery = ExternalFactDiscovery(candidates, False, index, ())
    labels = render_fact_labels(discovery.requirements)
    normalized = plain_text(assistant.content)
    if not _is_direct_external_fact_request(normalized):
        return None
    if any(labels[item.ref] not in normalized for item in discovery.requirements):
        return None
    quantity = _clarification_quantity(assistant.content)
    assignments = discovery.assignments
    if quantity > 1 and len(discovery.requirements) == 1:
        spans = extract_evidence_spans(reply.content)
        field = discovery.requirements[0].field
        assignments = tuple(
            EvidenceAssignment(discovery.requirements[0].ref, span)
            for span in spans
            if _span_compatible(field, span)
        )
    return PendingClarification(
        mutation_index=index,
        intent=mutation.content,
        requirements=discovery.requirements,
        assignments=assignments,
        quantity=quantity,
    )


def _clarification_quantity(value: str) -> int:
    normalized = plain_text(value)
    match = re.search(r"\b(\d{1,3}|dos|tres|cuatro|cinco)\b", normalized)
    if match is None:
        return 1
    words = {"dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
    return min(20, words.get(match.group(1), int(match.group(1))))


def value_matches_assignment(
    field: ActionFieldDefinition,
    value: JsonValue,
    assignment: EvidenceAssignment | None,
) -> bool:
    if assignment is None:
        return False
    if field.type == "json":
        return _json_values_match(value, assignment.span.value)
    if (
        field.type == "text"
        and "url" in plain_text(field.label)
        and isinstance(value, str)
        and isinstance(assignment.span.value, str)
    ):
        def _norm_url(u: str) -> str:
            val = u if re.match(r"https?://", u, re.IGNORECASE) else "https://" + u
            val = val.rstrip("/")
            val = re.sub(r"^(https?://)www\.", r"\1", val, flags=re.IGNORECASE)
            return val.lower()
        return _norm_url(value) == _norm_url(assignment.span.value)
    return _values_equal(field, value, assignment.span.value)


def _json_values_match(proposed: JsonValue, evidence: JsonValue) -> bool:
    if isinstance(proposed, str) and re.fullmatch(
        r"{{[A-Za-z_][A-Za-z0-9_]*}}", proposed
    ):
        return isinstance(evidence, str) and proposed == evidence
    if proposed is None or evidence is None:
        return proposed is None and evidence is None
    if isinstance(proposed, bool) or isinstance(evidence, bool):
        return isinstance(proposed, bool) and isinstance(evidence, bool) and proposed is evidence
    if isinstance(proposed, (int, float)) or isinstance(evidence, (int, float)):
        return (
            isinstance(proposed, (int, float))
            and not isinstance(proposed, bool)
            and isinstance(evidence, (int, float))
            and not isinstance(evidence, bool)
            and float(proposed) == float(evidence)
        )
    if isinstance(proposed, str) or isinstance(evidence, str):
        return isinstance(proposed, str) and isinstance(evidence, str) and proposed == evidence
    if isinstance(proposed, list) and isinstance(evidence, list):
        return len(proposed) == len(evidence) and all(
            _json_values_match(left, right)
            for left, right in zip(proposed, evidence, strict=True)
        )
    if isinstance(proposed, dict) and isinstance(evidence, dict):
        return proposed.keys() == evidence.keys() and all(
            _json_values_match(proposed[key], evidence[key]) for key in proposed
        )
    return False


def _values_equal(
    field: ActionFieldDefinition, proposed: JsonValue, evidence: JsonValue
) -> bool:
    if field.type == "file":
        if not isinstance(proposed, str) or not isinstance(evidence, str):
            return False
        left = ntpath.normcase(ntpath.normpath(unicodedata.normalize("NFC", proposed)))
        right = ntpath.normcase(ntpath.normpath(unicodedata.normalize("NFC", evidence)))
        return left == right
    if field.type in {"text", "multiline", "key", "select"}:
        return (
            isinstance(proposed, str)
            and isinstance(evidence, str)
            and unicodedata.normalize("NFC", proposed)
            == unicodedata.normalize("NFC", evidence)
        )
    if field.type in {"integer", "number"}:
        return (
            isinstance(proposed, (int, float))
            and not isinstance(proposed, bool)
            and isinstance(evidence, (int, float))
            and not isinstance(evidence, bool)
            and float(proposed) == float(evidence)
        )
    if field.type == "boolean":
        return isinstance(proposed, bool) and proposed is evidence
    if field.type == "json":
        return proposed == evidence
    return proposed == evidence
