import math
import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    UUID4,
    ValidationInfo,
    model_validator,
)
from typing_extensions import TypeAliasType

from app.config import (
    CANONICAL_MAX_BOT_EDGES as DEFAULT_MAX_BOT_EDGES,
    CANONICAL_MAX_BOT_NODES as DEFAULT_MAX_BOT_NODES,
    DEFAULT_MAX_ACTIONS,
    DEFAULT_MAX_JSON_DEPTH,
    DEFAULT_MAX_MESSAGE_CHARS,
    DEFAULT_MAX_MESSAGES,
)

JsonValue = TypeAliasType(
    "JsonValue",
    None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"],
)
MAX_SAFE_INTEGER = 9_007_199_254_740_991
IDENTIFIER_PATTERN = r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$"
VARIABLE_IDENTIFIER_PATTERN = r"^[A-Za-z_][A-Za-z0-9_]*$"
STRING_FIELD_TYPES = {"text", "multiline", "file", "key", "variable"}
NUMERIC_FIELD_TYPES = {"integer", "number"}
CONDITION_OPERATORS = {
    "eq",
    "ne",
    "lt",
    "lte",
    "gt",
    "gte",
    "contains",
    "startsWith",
    "endsWith",
    "in",
    "empty",
    "notEmpty",
}
UNARY_CONDITION_OPERATORS = {"empty", "notEmpty"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


def _limit(info: ValidationInfo, key: str, default: int) -> int:
    context = info.context or {}
    return int(context.get(key, default))


def validate_json_tree(value: Any, max_depth: int, depth: int = 1) -> None:
    pending = [(value, depth)]
    while pending:
        current, current_depth = pending.pop()
        if current_depth > max_depth:
            raise ValueError(f"JSON nesting exceeds {max_depth} levels")
        if isinstance(current, float) and not math.isfinite(current):
            raise ValueError("non-finite numbers are not allowed")
        if isinstance(current, str) and _contains_surrogate(current):
            raise ValueError("strings must contain only Unicode scalar values")
        if (
            isinstance(current, int)
            and not isinstance(current, bool)
            and abs(current) > MAX_SAFE_INTEGER
        ):
            raise ValueError("JSON integers must be JavaScript-safe")
        if isinstance(current, dict):
            for key, child in current.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                if _contains_surrogate(key):
                    raise ValueError("object keys must contain only Unicode scalar values")
                pending.append((child, current_depth + 1))
        elif isinstance(current, list):
            pending.extend((child, current_depth + 1) for child in current)


def _contains_surrogate(value: str) -> bool:
    return any(0xD800 <= ord(character) <= 0xDFFF for character in value)


def count_named_lists(value: Any, name: str) -> int:
    count = 0
    if isinstance(value, dict):
        for key, child in value.items():
            if key == name and isinstance(child, list):
                count = max(count, len(child))
            count = max(count, count_named_lists(child, name))
    elif isinstance(value, list):
        for child in value:
            count = max(count, count_named_lists(child, name))
    return count


class ChatMessage(StrictModel):
    role: Literal["user", "assistant"]
    content: StrictStr = Field(min_length=1)


class ActionFieldDefinition(StrictModel):
    name: StrictStr = Field(pattern=IDENTIFIER_PATTERN)
    label: StrictStr = Field(min_length=1, max_length=80)
    type: Literal[
        "text",
        "multiline",
        "integer",
        "number",
        "boolean",
        "select",
        "file",
        "key",
        "variable",
        "json",
        "condition",
    ]
    required: bool
    min: float | None = None
    max: float | None = None
    min_length: StrictInt | None = Field(default=None, alias="minLength", ge=0)
    max_length: StrictInt | None = Field(default=None, alias="maxLength", ge=0)
    pattern: StrictStr | None = None
    options: list[StrictStr] | None = None

    @model_validator(mode="after")
    def validate_constraints(self) -> "ActionFieldDefinition":
        bounds = (self.min, self.max)
        if any(value is not None and not math.isfinite(value) for value in bounds):
            raise ValueError("field bounds must be finite")
        if self.type not in NUMERIC_FIELD_TYPES and any(
            value is not None for value in bounds
        ):
            raise ValueError("only numeric fields may have numeric bounds")
        if self.type == "integer" and any(
            value is not None and not float(value).is_integer() for value in bounds
        ):
            raise ValueError("integer bounds must be integers")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("minimum cannot exceed maximum")

        has_string_constraint = any(
            value is not None
            for value in (self.min_length, self.max_length, self.pattern)
        )
        if self.type not in STRING_FIELD_TYPES and has_string_constraint:
            raise ValueError("only string fields may have string constraints")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("minimum length cannot exceed maximum length")

        if self.type == "select":
            if (
                not self.options
                or len(set(self.options)) != len(self.options)
                or any(not option for option in self.options)
            ):
                raise ValueError("select fields require unique non-empty options")
        elif self.options is not None:
            raise ValueError("only select fields may define options")

        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error:
                raise ValueError("field pattern must be valid") from None
        if self.type == "variable" and self.pattern != VARIABLE_IDENTIFIER_PATTERN:
            raise ValueError("variable fields require the canonical pattern")
        return self


class ActionOutputDefinition(StrictModel):
    field: StrictStr = Field(pattern=IDENTIFIER_PATTERN)
    type: Literal["value", "workbook"]


def _is_valid_condition(value: JsonValue) -> bool:
    if not isinstance(value, dict) or set(value) != {"combinator", "clauses"}:
        return False
    if value.get("combinator") not in {"all", "any"}:
        return False
    clauses = value.get("clauses")
    if not isinstance(clauses, list) or not clauses:
        return False
    for clause in clauses:
        if (
            not isinstance(clause, dict)
            or not {"left", "operator"}.issubset(clause)
            or not set(clause).issubset({"left", "operator", "right"})
        ):
            return False
        operator = clause.get("operator")
        if operator not in CONDITION_OPERATORS:
            return False
        if operator not in UNARY_CONDITION_OPERATORS and "right" not in clause:
            return False
    return True


def is_valid_action_field_value(
    field: ActionFieldDefinition, value: JsonValue, *, required: bool
) -> bool:
    if value is None:
        return not required
    if isinstance(value, str) and re.fullmatch(r"\{\{[A-Za-z_][A-Za-z0-9_]*\}\}", value.strip()):
        return True
    if value == "" and required:
        if field.type in STRING_FIELD_TYPES:
            return True
        return False
    if field.type == "integer":
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or abs(value) > MAX_SAFE_INTEGER
        ):
            return False
    elif field.type == "number":
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            return False
    elif field.type == "boolean":
        return isinstance(value, bool)
    elif field.type == "condition":
        return _is_valid_condition(value)
    elif field.type == "select":
        return isinstance(value, str) and value in (field.options or [])
    elif field.type in STRING_FIELD_TYPES:
        if not isinstance(value, str):
            return False
        if field.min_length is not None and len(value) < field.min_length:
            return False
        if field.max_length is not None and len(value) > field.max_length:
            return False
        if field.pattern is not None and re.fullmatch(field.pattern, value) is None:
            return False
    elif field.type != "json":
        return False

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if field.min is not None and value < field.min:
            return False
        if field.max is not None and value > field.max:
            return False
    return True


class ActionDefinition(StrictModel):
    id: StrictStr = Field(pattern=IDENTIFIER_PATTERN)
    category: StrictStr = Field(pattern=IDENTIFIER_PATTERN)
    category_name: StrictStr = Field(alias="categoryName", min_length=1, max_length=80)
    title: StrictStr = Field(min_length=1, max_length=80)
    description: StrictStr = Field(min_length=1, max_length=240)
    fields: list[ActionFieldDefinition]
    defaults: dict[str, JsonValue]
    output: ActionOutputDefinition | None
    outputs: list[ActionOutputDefinition] = Field(default_factory=list)
    slots: list[Annotated[StrictStr, Field(pattern=IDENTIFIER_PATTERN)]] = Field(
        default_factory=list
    )
    platform: Literal["windows"] | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "ActionDefinition":
        fields = {field.name: field for field in self.fields}
        if len(fields) != len(self.fields):
            raise ValueError("field names must be unique")
        if len(set(self.slots)) != len(self.slots):
            raise ValueError("slot names must be unique")

        for name, value in self.defaults.items():
            field = fields.get(name)
            if (
                field is None
                or value is None
                or not is_valid_action_field_value(field, value, required=False)
            ):
                raise ValueError("default does not satisfy its field")

        if self.output is not None and fields.get(self.output.field, None) is None:
            raise ValueError("output must reference a declared variable field")
        if self.output is not None and fields[self.output.field].type != "variable":
            raise ValueError("output must reference a declared variable field")
        if len({output.field for output in self.outputs}) != len(self.outputs):
            raise ValueError("output fields must be unique")
        if any(
            fields.get(output.field) is None
            or fields[output.field].type != "variable"
            for output in self.outputs
        ):
            raise ValueError("outputs must reference declared variable fields")
        if (
            self.output is not None
            and self.outputs
            and self.output != self.outputs[0]
        ):
            raise ValueError("legacy output must match the first output")
        return self


class Capabilities(StrictModel):
    catalog_version: StrictInt | None = Field(default=None, alias="catalogVersion", ge=1)
    catalog_hash: StrictStr | None = Field(
        default=None, alias="catalogHash", pattern=r"^[0-9a-f]{64}$"
    )
    actions: list[ActionDefinition]

    @model_validator(mode="after")
    def validate_contract(self) -> "Capabilities":
        if (self.catalog_version is None) != (self.catalog_hash is None):
            raise ValueError("catalogVersion and catalogHash must be supplied together")
        if not self.actions:
            raise ValueError("actions must not be empty")
        if len({action.id for action in self.actions}) != len(self.actions):
            raise ValueError("action IDs must be unique")

        names_by_id: dict[str, str] = {}
        ids_by_name: dict[str, str] = {}
        for action in self.actions:
            if names_by_id.get(action.category, action.category_name) != action.category_name:
                raise ValueError("category IDs and names must be bijective")
            if ids_by_name.get(action.category_name, action.category) != action.category:
                raise ValueError("category IDs and names must be bijective")
            names_by_id[action.category] = action.category_name
            ids_by_name[action.category_name] = action.category
        return self


class EditorContext(StrictModel):
    bot: dict[str, JsonValue]
    validation_issues: list[JsonValue] = Field(default_factory=list, alias="validationIssues")
    selected_block_id: StrictStr | None = Field(default=None, alias="selectedBlockId")
    working_bot: dict[str, JsonValue] | None = Field(default=None, alias="workingBot")
    working_validation_issues: list[JsonValue] = Field(
        default_factory=list, alias="workingValidationIssues"
    )
    proposal_version: StrictInt | None = Field(default=None, alias="proposalVersion", ge=1)

    @model_validator(mode="after")
    def validate_working_proposal(self) -> "EditorContext":
        if (self.working_bot is None) != (self.proposal_version is None):
            raise ValueError("workingBot and proposalVersion must be supplied together")
        if self.working_bot is None and self.working_validation_issues:
            raise ValueError("workingValidationIssues require workingBot")
        return self

class ChatRequest(StrictModel):
    schema_version: StrictInt = Field(alias="schemaVersion", default=1)
    messages: list[ChatMessage]
    capabilities: Capabilities
    editor_context: EditorContext | None = Field(default=None, alias="editorContext")

    @model_validator(mode="after")
    def enforce_contract(self, info: ValidationInfo) -> "ChatRequest":
        if self.schema_version != 1:
            raise ValueError("unsupported schemaVersion")
        max_messages = _limit(info, "max_messages", DEFAULT_MAX_MESSAGES)
        max_chars = _limit(info, "max_message_chars", DEFAULT_MAX_MESSAGE_CHARS)
        max_actions = _limit(info, "max_actions", DEFAULT_MAX_ACTIONS)
        if not self.messages or len(self.messages) > max_messages:
            raise ValueError(f"messages must contain between 1 and {max_messages} items")
        if len(self.capabilities.actions) > max_actions:
            raise ValueError(f"actions exceed the limit of {max_actions}")
        expected: Literal["user", "assistant"] = "user"
        for message in self.messages:
            if len(message.content) > max_chars:
                raise ValueError(f"message exceeds {max_chars} characters")
            if message.role != expected:
                raise ValueError("messages must alternate user and assistant roles")
            expected = "assistant" if expected == "user" else "user"
        if self.messages[-1].role != "user" or not self.messages[-1].content.strip():
            raise ValueError("the latest message must be a non-empty user message")

        raw = self.model_dump(mode="python", by_alias=True)
        max_depth = _limit(info, "max_json_depth", DEFAULT_MAX_JSON_DEPTH)
        validate_json_tree(raw, max_depth)
        if self.editor_context:
            context = self.editor_context.model_dump(mode="python", by_alias=True)
            nodes = count_named_lists(context, "nodes")
            edges = count_named_lists(context, "edges")
            max_nodes = _limit(info, "max_bot_nodes", DEFAULT_MAX_BOT_NODES)
            max_edges = _limit(info, "max_bot_edges", DEFAULT_MAX_BOT_EDGES)
            if nodes > max_nodes or edges > max_edges:
                raise ValueError("editor context exceeds canonical bot limits")
        return self


class HomeBotDraft(StrictModel):
    bot: dict[str, JsonValue]
    name: StrictStr = Field(min_length=1, max_length=120)
    summary: StrictStr = Field(min_length=1, max_length=1_000)
    catalog_version: StrictInt = Field(alias="catalogVersion", ge=1)
    catalog_hash: StrictStr = Field(
        alias="catalogHash", pattern=r"^[0-9a-f]{64}$"
    )

    @model_validator(mode="after")
    def reject_blank_text(self) -> "HomeBotDraft":
        if not self.name.strip() or not self.summary.strip():
            raise ValueError("draft name and summary must not be blank")
        return self


class PublicError(StrictModel):
    code: Literal[
        "INVALID_REQUEST",
        "OLLAMA_UNAVAILABLE",
        "MODEL_NOT_FOUND",
        "GENERATION_TIMEOUT",
        "GENERATION_CANCELLED",
        "CONTEXT_TOO_LARGE",
        "INVALID_PROPOSAL",
        "CATALOG_MISMATCH",
        "INTERNAL_ERROR",
        "EDITOR_CONTEXT_REQUIRED",
    ]
    message: StrictStr
    request_id: UUID4 = Field(alias="requestId")


class HealthResponse(StrictModel):
    status: Literal["ready", "ollama_unavailable", "model_not_found"]
    service_reachable: bool = Field(alias="serviceReachable")
    ollama_reachable: bool = Field(alias="ollamaReachable")
    model_installed: bool = Field(alias="modelInstalled")
    model: StrictStr
    active_model: StrictStr | None = Field(default=None, alias="activeModel")
    fallback_enabled: bool = Field(default=False, alias="fallbackEnabled")
    fallback_installed: bool = Field(default=False, alias="fallbackInstalled")
    remediation: StrictStr | None
