import json
import math
import re
from importlib import resources
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, StringConstraints, field_validator, model_validator

from autoclick_desktop.bot_schema import validate_finite_json
from autoclick_desktop.conditions import Condition


LUCIDE_ICONS = {
    "Clock3",
    "Variable",
    "MousePointer2",
    "Mouse",
    "Keyboard",
    "FileSpreadsheet",
    "Sheet",
    "Save",
    "X",
    "Play",
    "Globe",
    "AppWindow",
    "Folder",
    "File",
    "Clipboard",
    "Calendar",
    "User",
    "MessageSquare",
    "Trash2",
    "Network",
    "Workflow",
    "CornerDownRight",
    "ScanText",
}
Identifier = Annotated[
    str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9]*(?:[._-][A-Za-z0-9]+)*$")
]


class RegistryModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ActionField(RegistryModel):
    name: Identifier
    label: Annotated[str, StringConstraints(min_length=1, max_length=80)]
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
    min: int | float | None = Field(default=None, allow_inf_nan=False)
    max: int | float | None = Field(default=None, allow_inf_nan=False)
    min_length: int | None = Field(default=None, alias="minLength", ge=0)
    max_length: int | None = Field(default=None, alias="maxLength", ge=0)
    pattern: str | None = None
    options: list[str] | None = None

    @model_validator(mode="after")
    def validate_constraints(self) -> "ActionField":
        numeric = self.type in {"integer", "number"}
        string = self.type in {"text", "multiline", "file", "key", "variable"}
        if not numeric and (self.min is not None or self.max is not None):
            raise ValueError("only numeric fields may define numeric constraints")
        if self.type == "integer" and any(
            value is not None and not isinstance(value, int) for value in (self.min, self.max)
        ):
            raise ValueError("integer field constraints must be integers")
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("field minimum cannot exceed maximum")
        if not string and any(
            value is not None for value in (self.min_length, self.max_length, self.pattern)
        ):
            raise ValueError("only string fields may define string constraints")
        if (
            self.min_length is not None
            and self.max_length is not None
            and self.min_length > self.max_length
        ):
            raise ValueError("field minimum length cannot exceed maximum length")
        if self.type == "select":
            if (
                not self.options
                or any(not option for option in self.options)
                or len(self.options) != len(set(self.options))
            ):
                raise ValueError("select fields require unique options")
        elif self.options is not None:
            raise ValueError("only select fields may define options")
        if self.pattern is not None:
            try:
                re.compile(self.pattern)
            except re.error as error:
                raise ValueError("field pattern must be a valid regular expression") from error
        variable_pattern = r"^[A-Za-z_][A-Za-z0-9_]*$"
        if self.type == "variable" and self.pattern != variable_pattern:
            raise ValueError("variable fields require the variable identifier pattern")
        return self


class ActionOutput(RegistryModel):
    field: Identifier
    type: Literal["value", "workbook"]


class ActionDefinition(RegistryModel):
    id: Identifier
    category: Identifier
    category_name: Annotated[str, StringConstraints(min_length=1, max_length=80)] = Field(
        alias="categoryName"
    )
    title: Annotated[str, StringConstraints(min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(min_length=1, max_length=240)]
    icon: str
    fields: list[ActionField]
    defaults: dict[str, JsonValue]
    output: ActionOutput | None
    outputs: list[ActionOutput] = Field(default_factory=list)
    handler_key: Identifier = Field(alias="handlerKey")
    platform: Literal["windows"] | None = None
    slots: list[Identifier] = Field(default_factory=list)

    @field_validator("defaults")
    @classmethod
    def validate_defaults(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value

    @model_validator(mode="after")
    def validate_definition(self) -> "ActionDefinition":
        names = [field.name for field in self.fields]
        if len(names) != len(set(names)):
            raise ValueError("action field names must be unique")
        if len(self.slots) != len(set(self.slots)):
            raise ValueError("action slot names must be unique")
        if self.icon not in LUCIDE_ICONS:
            raise ValueError("action icon is not allowed")
        fields = {field.name: field for field in self.fields}
        if not self.defaults.keys() <= fields.keys():
            raise ValueError("defaults must reference declared fields")
        for name, default in self.defaults.items():
            field = fields[name]
            if default is None:
                raise ValueError("field defaults cannot be null")
            if field.type == "integer" and (isinstance(default, bool) or not isinstance(default, int)):
                raise ValueError("integer field defaults must be integers")
            if field.type == "number" and (
                isinstance(default, bool) or not isinstance(default, (int, float))
            ):
                raise ValueError("number field defaults must be numbers")
            if field.type == "boolean" and not isinstance(default, bool):
                raise ValueError("boolean field defaults must be booleans")
            if field.type not in {"integer", "number", "boolean", "json", "condition"} and not isinstance(default, str):
                raise ValueError("string field defaults must be strings")
            if field.type == "condition":
                Condition.model_validate(default)
            if field.options is not None and default not in field.options:
                raise ValueError("select default must be an option")
            if isinstance(default, (int, float)) and not isinstance(default, bool):
                if isinstance(default, float) and not math.isfinite(default):
                    raise ValueError("numeric field defaults must be finite")
                if field.min is not None and default < field.min:
                    raise ValueError("default is below field minimum")
                if field.max is not None and default > field.max:
                    raise ValueError("default is above field maximum")
            if isinstance(default, str):
                if field.min_length is not None and len(default) < field.min_length:
                    raise ValueError("default is shorter than field minimum length")
                if field.max_length is not None and len(default) > field.max_length:
                    raise ValueError("default exceeds field maximum length")
                if field.pattern is not None and re.fullmatch(field.pattern, default) is None:
                    raise ValueError("default does not match field pattern")
        if self.output is not None and self.output.field not in fields:
            raise ValueError("output must reference a declared field")
        if self.output is not None and fields[self.output.field].type != "variable":
            raise ValueError("output must reference a variable field")
        output_fields = [output.field for output in self.outputs]
        if len(output_fields) != len(set(output_fields)):
            raise ValueError("output fields must be unique")
        for output in self.outputs:
            if fields.get(output.field) is None or fields[output.field].type != "variable":
                raise ValueError("outputs must reference variable fields")
        if self.output is not None and self.outputs and self.output != self.outputs[0]:
            raise ValueError("legacy output must match the first typed output")
        return self


class ActionRegistry(RegistryModel):
    catalog_version: StrictInt = Field(alias="catalogVersion", ge=1)
    catalog_hash: Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")] = Field(
        alias="catalogHash"
    )
    actions: list[ActionDefinition]

    @model_validator(mode="after")
    def validate_actions(self) -> "ActionRegistry":
        ids = [action.id for action in self.actions]
        if len(ids) != len(set(ids)):
            raise ValueError("action IDs must be unique")
        handler_keys = [action.handler_key for action in self.actions]
        if len(handler_keys) != len(set(handler_keys)):
            raise ValueError("handler keys must be unique")
        return self


def load_action_registry(path: Path | None = None) -> ActionRegistry:
    if path is None:
        registry_text = resources.files("autoclick_desktop.data").joinpath(
            "action_registry.json"
        ).read_text(encoding="utf-8")
    else:
        registry_text = path.read_text(encoding="utf-8")
    data = json.loads(registry_text, parse_constant=_reject_json_constant)
    return ActionRegistry.model_validate(data)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"invalid JSON constant: {value}")
