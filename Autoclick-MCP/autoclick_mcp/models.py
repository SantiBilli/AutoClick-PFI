from typing import Any, Generic, Literal, TypeVar
from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class McpIssue(StrictBaseModel):
    code: str
    message: str
    path: str | None = None
    nodeId: str | None = None
    actionId: str | None = None
    operationIndex: int | None = None
    severity: Literal["error", "warning"] = "error"


class McpResult(StrictBaseModel, Generic[T]):
    ok: bool
    data: T | None = None
    issues: list[McpIssue] = Field(default_factory=list)


class ActionSummary(StrictBaseModel):
    id: str
    category: str
    categoryName: str
    title: str
    summary: str
    platform: str | None = None
    hasOutput: bool = False
    slots: list[str] = Field(default_factory=list)


class ActionFieldDetail(StrictBaseModel):
    name: str
    label: str
    type: str
    required: bool = False
    min: float | int | None = None
    max: float | int | None = None
    minLength: int | None = None
    maxLength: int | None = None
    pattern: str | None = None
    options: list[str] | None = None


class ActionOutputDetail(StrictBaseModel):
    field: str
    type: str


class ActionDetail(StrictBaseModel):
    id: str
    category: str
    categoryName: str
    title: str
    description: str
    fields: list[ActionFieldDetail] = Field(default_factory=list)
    defaults: dict[str, Any] = Field(default_factory=dict)
    output: dict[str, str] | None = None
    outputs: list[dict[str, str]] = Field(default_factory=list)
    slots: list[str] = Field(default_factory=list)
    platform: str | None = None


class ActionSearchData(StrictBaseModel):
    actions: list[ActionSummary]
    totalMatches: int
    catalogVersion: int
    catalogHash: str


class ActionSchemasData(StrictBaseModel):
    actions: list[ActionDetail]
    catalogVersion: int
    catalogHash: str


ValidationResponse = McpResult[dict[str, Any]]
