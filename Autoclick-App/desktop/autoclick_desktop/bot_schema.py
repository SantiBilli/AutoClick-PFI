import json
import hashlib
import math
import re
import struct
from functools import lru_cache
from datetime import datetime, timezone
from importlib.resources import files
from typing import Annotated, Literal, NotRequired, TypedDict, cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StrictInt, StringConstraints, ValidationError, field_validator, model_validator
from pydantic_core import PydanticCustomError

from autoclick_desktop.conditions import Condition, ConditionClause


NonEmptyId = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
NodeType = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        pattern=r"^[A-Za-z][A-Za-z0-9_-]*(?:\.[A-Za-z][A-Za-z0-9_-]*)+$",
    ),
]
IconIdentifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$",
    ),
]
with files("autoclick_desktop").joinpath("data/ai_contract.json").open(
    "r", encoding="utf-8"
) as contract_file:
    _AI_CONTRACT = json.load(contract_file)

AI_MAX_MESSAGE_CODE_POINTS = _AI_CONTRACT["maxMessageCodePoints"]
MAX_AI_STATE_SIZE = _AI_CONTRACT["maxAiStateBytes"]
MAX_SAFE_INTEGER = 9_007_199_254_740_991
ConversationTitle = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
]
MessageContent = Annotated[
    str, StringConstraints(min_length=1, max_length=AI_MAX_MESSAGE_CODE_POINTS)
]


class AiStateTooLargeError(ValueError):
    pass


def validate_finite_json(value: JsonValue) -> JsonValue:
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        if value.is_integer() and abs(value) > MAX_SAFE_INTEGER:
            raise ValueError("JSON integers must be JavaScript-safe")
    elif isinstance(value, int) and not isinstance(value, bool) and abs(value) > MAX_SAFE_INTEGER:
        raise ValueError("JSON integers must be JavaScript-safe")
    if isinstance(value, list):
        for item in value:
            validate_finite_json(item)
    elif isinstance(value, dict):
        for item in value.values():
            validate_finite_json(item)
    return value


class CanonicalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CanonicalBotNodeData(TypedDict):
    id: str
    type: str
    params: dict[str, JsonValue]
    slots: NotRequired[dict[str, list[str]]]


CanonicalBotNodeInput = CanonicalBotNodeData


class CanonicalBotFlowData(TypedDict):
    root: list[str]
    nodes: list[CanonicalBotNodeData]


class CanonicalBotFlowInput(TypedDict):
    root: list[str]
    nodes: list[CanonicalBotNodeInput]


class CanonicalAiMessageData(TypedDict):
    id: str
    role: Literal["user", "assistant"]
    content: str
    createdAt: str
    status: Literal["complete", "interrupted"]
    metrics: NotRequired["CanonicalAiMessageMetricsData"]


CanonicalAiMessageInput = CanonicalAiMessageData


class CanonicalAiMessageMetricsData(TypedDict):
    totalTimeMs: int
    inputTokens: int | None
    outputTokens: int | None


class CanonicalAiConversationData(TypedDict):
    id: str
    title: str
    createdAt: str
    updatedAt: str
    messages: list[CanonicalAiMessageData]


CanonicalAiConversationInput = CanonicalAiConversationData


class CanonicalAiData(TypedDict):
    schemaVersion: Literal[1]
    activeConversationId: str | None
    conversations: list[CanonicalAiConversationData]


CanonicalAiInput = CanonicalAiData
CanonicalPendingAiProposalData = dict[str, object]
CanonicalPendingAiProposalInput = dict[str, object]


class CanonicalBotData(TypedDict):
    schemaVersion: Literal[2]
    id: str
    name: str
    description: str
    icon: NotRequired[str]
    flow: CanonicalBotFlowData
    ai: NotRequired[CanonicalAiData]
    pendingAiProposal: NotRequired[CanonicalPendingAiProposalData]


class CanonicalBotInput(TypedDict):
    schemaVersion: Literal[2]
    id: str
    name: str
    description: NotRequired[str]
    icon: NotRequired[str | None]
    flow: CanonicalBotFlowInput
    ai: NotRequired[CanonicalAiInput]
    pendingAiProposal: NotRequired[CanonicalPendingAiProposalInput | None]


class AiMessageMetrics(CanonicalModel):
    total_time_ms: StrictInt = Field(alias="totalTimeMs", ge=0, le=MAX_SAFE_INTEGER)
    input_tokens: StrictInt | None = Field(alias="inputTokens", ge=0, le=MAX_SAFE_INTEGER)
    output_tokens: StrictInt | None = Field(alias="outputTokens", ge=0, le=MAX_SAFE_INTEGER)


class AiMessage(CanonicalModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: MessageContent
    created_at: datetime = Field(alias="createdAt")
    status: Literal["complete", "interrupted"]
    metrics: AiMessageMetrics | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_metrics(cls, value: object) -> object:
        if isinstance(value, dict) and "metrics" in value and value["metrics"] is None:
            raise ValueError("metrics must be an object when present")
        return value

    @field_validator("id", mode="before")
    @classmethod
    def validate_id_input(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("message id must be a UUID string")
        return value

    @field_validator("created_at", mode="before")
    @classmethod
    def validate_created_at_input(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("createdAt must be an ISO 8601 UTC timestamp")
        return value

    @field_validator("created_at")
    @classmethod
    def validate_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("createdAt must be an ISO 8601 UTC timestamp")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def validate_user_status(self) -> "AiMessage":
        if self.role == "user" and self.status != "complete":
            raise ValueError("user messages must be complete")
        if self.role == "user" and self.metrics is not None:
            raise ValueError("user messages cannot contain model metrics")
        return self


class AiConversation(CanonicalModel):
    id: UUID
    title: ConversationTitle
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    messages: list[AiMessage] = Field(max_length=60)

    @field_validator("id", mode="before")
    @classmethod
    def validate_id_input(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("conversation id must be a UUID string")
        return value

    @field_validator("messages", mode="before")
    @classmethod
    def validate_messages_input(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("messages must be an array")
        return value

    @field_validator("created_at", "updated_at", mode="before")
    @classmethod
    def validate_timestamp_input(cls, value: object) -> object:
        if not isinstance(value, str):
            raise ValueError("conversation timestamps must be ISO 8601 UTC timestamps")
        return value

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_timestamp(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timezone.utc.utcoffset(value):
            raise ValueError("conversation timestamps must be ISO 8601 UTC timestamps")
        return value.astimezone(timezone.utc)


class BotAiState(CanonicalModel):
    schema_version: int = Field(alias="schemaVersion", strict=True, ge=1, le=1)
    active_conversation_id: UUID | None = Field(alias="activeConversationId")
    conversations: list[AiConversation] = Field(max_length=10)

    @field_validator("active_conversation_id", mode="before")
    @classmethod
    def validate_active_id_input(cls, value: object) -> object:
        if value is not None and not isinstance(value, str):
            raise ValueError("active conversation id must be a UUID string or null")
        return value

    @field_validator("conversations", mode="before")
    @classmethod
    def validate_conversations_input(cls, value: object) -> object:
        if not isinstance(value, list):
            raise ValueError("conversations must be an array")
        return value

    @model_validator(mode="after")
    def validate_state(self) -> "BotAiState":
        conversation_ids = [conversation.id for conversation in self.conversations]
        if len(conversation_ids) != len(set(conversation_ids)):
            raise ValueError("conversation IDs must be unique")
        if (
            self.active_conversation_id is not None
            and self.active_conversation_id not in set(conversation_ids)
        ):
            raise ValueError("active conversation must reference an existing conversation")

        message_ids = [
            message.id
            for conversation in self.conversations
            for message in conversation.messages
        ]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("message IDs must be unique within the AI state")

        payload = self.model_dump(mode="json", by_alias=True)
        for conversation in payload["conversations"]:
            for message in conversation["messages"]:
                if message.get("metrics") is None:
                    message.pop("metrics", None)
        compact = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(compact) > MAX_AI_STATE_SIZE:
            raise AiStateTooLargeError("AI state exceeds size limit")
        return self


class BotNode(CanonicalModel):
    id: NonEmptyId
    type: NodeType
    params: dict[str, JsonValue]
    slots: dict[NonEmptyId, list[NonEmptyId]] = Field(default_factory=dict)

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value


class BotFlow(CanonicalModel):
    root: list[NonEmptyId]
    nodes: list[BotNode] = Field(max_length=1_000)

    @model_validator(mode="after")
    def validate_tree(self) -> "BotFlow":
        node_ids = [node.id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node IDs must be unique")
        known = set(node_ids)
        placements = list(self.root)
        for node in self.nodes:
            declared = _declared_slots(node.type)
            if set(node.slots) != declared:
                raise ValueError("node slots must exactly match declared structural slots")
            placements.extend(child for children in node.slots.values() for child in children)
        if any(node_id not in known for node_id in placements):
            raise ValueError("tree placements must reference existing nodes")
        if len(placements) != len(set(placements)):
            raise ValueError("every node must be placed exactly once")
        if set(placements) != known:
            raise ValueError("tree cannot contain orphan nodes")

        by_id = {node.id: node for node in self.nodes}
        visiting: set[str] = set()
        visited: set[str] = set()
        def visit(node_id: str) -> None:
            if node_id in visiting:
                raise ValueError("tree cannot contain cycles")
            if node_id in visited:
                return
            visiting.add(node_id)
            for children in by_id[node_id].slots.values():
                for child in children:
                    visit(child)
            visiting.remove(node_id)
            visited.add(node_id)
        for node_id in self.root:
            visit(node_id)
        # A component made only of child links has no root. Visit every node so
        # that such a component cannot hide a cycle while still placing each ID once.
        for node_id in node_ids:
            visit(node_id)
        return self


class ProposalLocation(CanonicalModel):
    parent_id: NonEmptyId | None = Field(alias="parentId")
    slot: NonEmptyId
    index: StrictInt = Field(ge=0, le=1_000)

    @model_validator(mode="after")
    def validate_root(self) -> "ProposalLocation":
        if (self.parent_id is None) != (self.slot == "root"):
            raise ValueError("root requires a null parentId")
        return self


class ProposalNode(CanonicalModel):
    id: NonEmptyId
    type: NodeType
    params: dict[str, JsonValue]

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value


class SetMetadataOperation(CanonicalModel):
    op: Literal["setMetadata"]
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)] | None = None
    description: Annotated[str, StringConstraints(max_length=500)] | None = None

    @model_validator(mode="after")
    def validate_change(self) -> "SetMetadataOperation":
        if self.name is None and self.description is None:
            raise ValueError("setMetadata requires name or description")
        return self


class AddNodeOperation(CanonicalModel):
    op: Literal["addNode"]
    node: ProposalNode
    location: ProposalLocation


class RemoveNodeOperation(CanonicalModel):
    op: Literal["removeNode"]
    node_id: NonEmptyId = Field(alias="nodeId")


class MoveNodeOperation(CanonicalModel):
    op: Literal["moveNode"]
    node_id: NonEmptyId = Field(alias="nodeId")
    location: ProposalLocation


class UpdateNodeParamsOperation(CanonicalModel):
    op: Literal["updateNodeParams"]
    node_id: NonEmptyId = Field(alias="nodeId")
    params: dict[str, JsonValue]

    @field_validator("params")
    @classmethod
    def validate_params(cls, value: dict[str, JsonValue]) -> dict[str, JsonValue]:
        validate_finite_json(value)
        return value


class ReplaceNodeOperation(UpdateNodeParamsOperation):
    op: Literal["replaceNode"]
    action_type: NodeType = Field(alias="actionType")


ProposalOperation = Annotated[
    SetMetadataOperation
    | AddNodeOperation
    | RemoveNodeOperation
    | MoveNodeOperation
    | UpdateNodeParamsOperation
    | ReplaceNodeOperation,
    Field(discriminator="op"),
]


class ProposalBot(CanonicalModel):
    schema_version: Literal[2] = Field(alias="schemaVersion")
    id: UUID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(max_length=500)] = ""
    icon: IconIdentifier | None = None
    flow: BotFlow


class PendingProposal(CanonicalModel):
    id: UUID
    version: StrictInt = Field(ge=1)
    base_bot_id: UUID = Field(alias="baseBotId")
    summary: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1_000)]
    operations: list[ProposalOperation] = Field(min_length=1, max_length=200)
    resulting_bot: ProposalBot = Field(alias="resultingBot")
    baseline_bot_revision: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] = Field(alias="baselineBotRevision")

    @model_validator(mode="after")
    def validate_bot_id(self) -> "PendingProposal":
        if self.resulting_bot.id != self.base_bot_id:
            raise ValueError("resultingBot must match baseBotId")
        return self


class PendingAiProposal(CanonicalModel):
    proposal: PendingProposal
    operation_baseline: ProposalBot = Field(alias="operationBaseline")
    original: ProposalBot
    editor_bot_revision: Annotated[str, StringConstraints(pattern=r"^[a-f0-9]{64}$")] = Field(alias="editorBotRevision")

    @model_validator(mode="after")
    def validate_revisions_and_ids(self) -> "PendingAiProposal":
        if (
            self.operation_baseline.id != self.proposal.base_bot_id
            or self.original.id != self.proposal.base_bot_id
        ):
            raise ValueError("pending proposal bot IDs must match")
        baseline_revision = semantic_bot_revision(self.operation_baseline)
        if baseline_revision != self.proposal.baseline_bot_revision:
            raise ValueError("pending proposal baseline hash does not match")
        applied = apply_proposal_operations(
            self.operation_baseline, self.proposal.operations
        )
        if semantic_bot_revision(applied) != semantic_bot_revision(self.proposal.resulting_bot):
            raise ValueError("pending proposal operations do not reproduce resultingBot")
        if semantic_bot_revision(self.original) != self.editor_bot_revision:
            raise PydanticCustomError(
                "pending_ai_proposal_original_revision",
                "pending proposal original does not match editorBotRevision",
            )
        return self


class LegacyBotEdge(CanonicalModel):
    id: NonEmptyId
    source: NonEmptyId
    target: NonEmptyId


class LegacyBotFlow(CanonicalModel):
    nodes: list[BotNode] = Field(max_length=1_000)
    edges: list[LegacyBotEdge] = Field(max_length=2_000)

    @model_validator(mode="after")
    def validate_graph(self) -> "LegacyBotFlow":
        node_ids = [node.id for node in self.nodes]
        edge_ids = [edge.id for edge in self.edges]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node IDs must be unique")
        if len(edge_ids) != len(set(edge_ids)):
            raise ValueError("edge IDs must be unique")
        known = set(node_ids)
        for edge in self.edges:
            if edge.source == edge.target:
                raise ValueError("edges cannot connect a node to itself")
            if edge.source not in known or edge.target not in known:
                raise ValueError("edges must reference existing nodes")
        if any(node.slots for node in self.nodes):
            raise ValueError("schema v1 nodes cannot contain slots")
        return self


class LegacyBot(CanonicalModel):
    schema_version: int = Field(alias="schemaVersion", strict=True, ge=1, le=1)
    id: UUID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(max_length=500)] = ""
    icon: IconIdentifier | None = None
    flow: LegacyBotFlow
    ai: BotAiState | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_null_ai(cls, value: object) -> object:
        if isinstance(value, dict) and "ai" in value and value["ai"] is None:
            raise ValueError("ai must be an object when present")
        return value


class Bot(CanonicalModel):
    schema_version: int = Field(alias="schemaVersion", strict=True, ge=2, le=2)
    id: UUID
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)]
    description: Annotated[str, StringConstraints(max_length=500)] = ""
    icon: IconIdentifier | None = None
    flow: BotFlow
    ai: BotAiState | None = None
    pending_ai_proposal: PendingAiProposal | None = Field(default=None, alias="pendingAiProposal")

    @model_validator(mode="before")
    @classmethod
    def migrate_and_reject_explicit_null_ai(cls, value: object) -> object:
        if isinstance(value, dict) and "ai" in value and value["ai"] is None:
            raise ValueError("ai must be an object when present")
        if (
            isinstance(value, dict)
            and isinstance(value.get("schemaVersion"), int)
            and not isinstance(value.get("schemaVersion"), bool)
            and value.get("schemaVersion") == 1
        ):
            return migrate_v1_bot(value)
        return value

    @model_validator(mode="after")
    def validate_pending_editor_revision(self) -> "Bot":
        if (
            self.pending_ai_proposal is not None
            and self.pending_ai_proposal.editor_bot_revision
            != semantic_bot_revision(self)
        ):
            raise ValidationError.from_exception_data(
                self.__class__.__name__,
                [
                    {
                        "type": PydanticCustomError(
                            "pending_ai_proposal_revision",
                            "pending proposal does not match the bot revision",
                        ),
                        "loc": ("pendingAiProposal",),
                        "input": self.pending_ai_proposal,
                    }
                ],
            )
        return self


def dump_canonical_bot(bot: Bot | LegacyBot) -> CanonicalBotData:
    data = bot.model_dump(mode="json", by_alias=True)
    for node in data["flow"]["nodes"]:
        if not node["slots"]:
            node.pop("slots")
    if bot.icon is None:
        data.pop("icon", None)
    if bot.ai is None:
        data.pop("ai", None)
    else:
        for conversation in data["ai"]["conversations"]:
            for message in conversation["messages"]:
                if message.get("metrics") is None:
                    message.pop("metrics", None)
    if not isinstance(bot, Bot) or bot.pending_ai_proposal is None:
        data.pop("pendingAiProposal", None)
    return cast(CanonicalBotData, data)


def dump_canonical_pending_ai_proposal(pending: PendingAiProposal) -> CanonicalPendingAiProposalData:
    return pending.model_dump(mode="json", by_alias=True)


def _semantic_value(value: object) -> str:
    if value is None:
        return "n;"
    if isinstance(value, bool):
        return "b1;" if value else "b0;"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("semantic bot contains a non-finite number")
        return f"d{struct.pack('>d', 0.0 if number == 0 else number).hex()};"
    if isinstance(value, str):
        return f"s{value.encode('utf-8').hex()};"
    if isinstance(value, list):
        return f"a{len(value)}:" + "".join(_semantic_value(item) for item in value)
    if isinstance(value, dict):
        entries = sorted(value.items(), key=lambda item: [ord(character) for character in item[0]])
        return f"o{len(entries)}:" + "".join(
            _semantic_value(key) + _semantic_value(item) for key, item in entries
        )
    raise ValueError("semantic bot contains a non-JSON value")


def _semantic_bot_revision_from_dump(data: dict[str, object]) -> str:
    data.pop("ai", None)
    data.pop("pendingAiProposal", None)
    data["icon"] = data.get("icon") or "bot"
    if data.get("schemaVersion") == 2:
        nodes = data["flow"]["nodes"]
        for node in nodes:
            node["slots"] = node.get("slots") or {}
        nodes.sort(key=lambda node: [ord(character) for character in node["id"]])
    return hashlib.sha256(_semantic_value(data).encode("ascii")).hexdigest()


def semantic_bot_revision(bot: Bot | LegacyBot | ProposalBot) -> str:
    return _semantic_bot_revision_from_dump(
        bot.model_dump(mode="json", by_alias=True)
    )


def apply_proposal_operations(
    baseline: ProposalBot,
    operations: list[ProposalOperation],
) -> ProposalBot:
    draft = baseline.model_copy(deep=True)

    def nodes_by_id() -> dict[str, BotNode]:
        return {node.id: node for node in draft.flow.nodes}

    def require_node(node_id: str) -> BotNode:
        node = nodes_by_id().get(node_id)
        if node is None:
            raise ValueError("proposal references a missing node")
        return node

    def sequence(location: ProposalLocation) -> list[str]:
        if location.parent_id is None:
            return draft.flow.root
        parent = require_node(location.parent_id)
        children = parent.slots.get(location.slot)
        if children is None:
            raise ValueError("proposal references an invalid slot")
        return children

    def source_sequence(node_id: str) -> list[str]:
        matches: list[list[str]] = []
        if node_id in draft.flow.root:
            matches.append(draft.flow.root)
        for node in draft.flow.nodes:
            matches.extend(children for children in node.slots.values() if node_id in children)
        if len(matches) != 1:
            raise ValueError("proposal node placement is invalid")
        return matches[0]

    def descendants(node_id: str) -> set[str]:
        by_id = nodes_by_id()
        found: set[str] = set()

        def visit(current_id: str) -> None:
            if current_id in found:
                return
            found.add(current_id)
            current = by_id.get(current_id)
            if current is not None:
                for children in current.slots.values():
                    for child_id in children:
                        visit(child_id)

        visit(node_id)
        return found

    for operation in operations:
        if isinstance(operation, SetMetadataOperation):
            if operation.name is not None:
                draft.name = operation.name
            if operation.description is not None:
                draft.description = operation.description
            continue
        if isinstance(operation, AddNodeOperation):
            if operation.node.id in nodes_by_id():
                raise ValueError("proposal repeats a node ID")
            target = sequence(operation.location)
            if operation.location.index > len(target):
                raise ValueError("proposal insertion index is invalid")
            params, slots = _normalize_proposal_node(
                operation.node.type, operation.node.params
            )
            draft.flow.nodes.append(
                BotNode(
                    id=operation.node.id,
                    type=operation.node.type,
                    params=params,
                    slots=slots,
                )
            )
            target.insert(operation.location.index, operation.node.id)
            continue
        if isinstance(operation, RemoveNodeOperation):
            require_node(operation.node_id)
            source = source_sequence(operation.node_id)
            source.remove(operation.node_id)
            removed = descendants(operation.node_id)
            draft.flow.nodes = [node for node in draft.flow.nodes if node.id not in removed]
            continue
        if isinstance(operation, MoveNodeOperation):
            require_node(operation.node_id)
            if operation.location.parent_id in descendants(operation.node_id):
                raise ValueError("proposal move creates a cycle")
            source = source_sequence(operation.node_id)
            source.remove(operation.node_id)
            target = sequence(operation.location)
            if operation.location.index > len(target):
                raise ValueError("proposal move index is invalid")
            target.insert(operation.location.index, operation.node_id)
            continue
        if isinstance(operation, ReplaceNodeOperation):
            node = require_node(operation.node_id)
            params, slots = _normalize_proposal_node(
                operation.action_type, operation.params
            )
            if set(slots) != set(node.slots):
                raise ValueError("proposal replacement changes structural slots")
            node.type = operation.action_type
            node.params = params
            continue
        if isinstance(operation, UpdateNodeParamsOperation):
            node = require_node(operation.node_id)
            params, _slots = _normalize_proposal_node(node.type, operation.params)
            node.params = params
            continue
        raise ValueError("unsupported proposal operation")

    return ProposalBot.model_validate(draft.model_dump(mode="json", by_alias=True))


def _normalize_proposal_node(
    action_type: str, supplied: dict[str, JsonValue]
) -> tuple[dict[str, JsonValue], dict[str, list[str]]]:
    from autoclick_desktop.action_registry import load_action_registry

    definition = next(
        (action for action in load_action_registry().actions if action.id == action_type),
        None,
    )
    if definition is None:
        raise ValueError("proposal uses an unknown action")
    fields = {field.name: field for field in definition.fields}
    if not supplied.keys() <= fields.keys():
        raise ValueError("proposal uses an unknown parameter")
    params = {**definition.defaults, **supplied}
    for name, field in fields.items():
        if name not in params:
            if field.required:
                raise ValueError("proposal omits a required parameter")
            continue
        value = params[name]
        if isinstance(value, str) and "{{" in value:
            continue
        if not _proposal_field_value_is_valid(field, value):
            raise ValueError("proposal contains an invalid parameter")
    return params, {slot: [] for slot in definition.slots}


def _proposal_field_value_is_valid(field: object, value: JsonValue) -> bool:
    field_type = getattr(field, "type")
    if field_type == "integer":
        valid = isinstance(value, int) and not isinstance(value, bool)
    elif field_type == "number":
        valid = isinstance(value, (int, float)) and not isinstance(value, bool)
    elif field_type == "boolean":
        valid = isinstance(value, bool)
    elif field_type == "json":
        try:
            validate_finite_json(value)
            valid = True
        except ValueError:
            valid = False
    elif field_type == "condition":
        try:
            Condition.model_validate(value)
            valid = True
        except (ValidationError, ValueError, TypeError):
            valid = False
    else:
        valid = isinstance(value, str)
    if not valid:
        return False
    minimum = getattr(field, "min")
    maximum = getattr(field, "max")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            return False
        if minimum is not None and value < minimum:
            return False
        if maximum is not None and value > maximum:
            return False
    if isinstance(value, str):
        min_length = getattr(field, "min_length")
        max_length = getattr(field, "max_length")
        pattern = getattr(field, "pattern")
        options = getattr(field, "options")
        if min_length is not None and len(value) < min_length:
            return False
        if max_length is not None and len(value) > max_length:
            return False
        if pattern is not None and re.fullmatch(pattern, value) is None:
            return False
        if options is not None and value not in options:
            return False
    return True


def dump_canonical_ai(ai: BotAiState) -> CanonicalAiData:
    data = ai.model_dump(mode="json", by_alias=True)
    for conversation in data["conversations"]:
        for message in conversation["messages"]:
            if message.get("metrics") is None:
                message.pop("metrics", None)
    return cast(CanonicalAiData, data)


def parse_bot_data(value: object) -> Bot | LegacyBot:
    if isinstance(value, dict) and value.get("schemaVersion") == 1:
        legacy = LegacyBot.model_validate(value)
        flow = cast(dict[str, object], value["flow"])
        try:
            _derive_v1_order(
                cast(list[object], flow["nodes"]),
                cast(list[object], flow["edges"]),
            )
        except ValueError:
            return legacy
    return Bot.model_validate(value)


def parse_bot_data_tolerating_pending(
    value: object,
) -> tuple[Bot | LegacyBot, Literal["invalid", "stale"] | None]:
    try:
        return parse_bot_data(value), None
    except ValidationError as error:
        if not isinstance(value, dict) or "pendingAiProposal" not in value:
            raise
        semantic_value = {
            key: item for key, item in value.items() if key != "pendingAiProposal"
        }
        bot = parse_bot_data(semantic_value)
        issue = (
            "stale"
            if all(
                item["type"] == "pending_ai_proposal_revision"
                for item in error.errors()
            )
            else "invalid"
        )
        return bot, issue


@lru_cache(maxsize=None)
def _declared_slots(action_type: str) -> set[str]:
    from autoclick_desktop.action_registry import load_action_registry
    definition = next((item for item in load_action_registry().actions if item.id == action_type), None)
    return set(definition.slots if definition is not None else ())


def _derive_v1_order(nodes: list[object], edges: list[object]) -> list[str]:
    if any(
        not isinstance(node, dict)
        or set(node) != {"id", "type", "params"}
        or not isinstance(node.get("id"), str)
        for node in nodes
    ):
        raise ValueError("invalid v1 nodes")
    ids = [cast(dict[str, object], node)["id"] for node in nodes]
    if len(ids) != len(set(ids)):
        raise ValueError("node IDs must be unique")
    if not ids:
        if edges:
            raise ValueError("empty v1 flow cannot have edges")
        return []
    incoming = {cast(str, node_id): 0 for node_id in ids}
    outgoing = {cast(str, node_id): [] for node_id in ids}
    edge_ids: set[str] = set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {"id", "source", "target"}:
            raise ValueError("invalid v1 edge")
        edge_id, source, target = edge.get("id"), edge.get("source"), edge.get("target")
        if not all(isinstance(item, str) and item.strip() for item in (edge_id, source, target)):
            raise ValueError("invalid v1 edge")
        if edge_id in edge_ids or source not in incoming or target not in incoming or source == target:
            raise ValueError("invalid v1 edge")
        edge_ids.add(cast(str, edge_id))
        incoming[cast(str, target)] += 1
        outgoing[cast(str, source)].append(cast(str, target))
    if len(edges) != len(ids) - 1 or any(value > 1 for value in incoming.values()) or any(len(value) > 1 for value in outgoing.values()):
        raise ValueError("v1 flow must be linear")
    starts = [node_id for node_id, count in incoming.items() if count == 0]
    if len(starts) != 1:
        raise ValueError("v1 flow must have one start")
    order: list[str] = []
    current: str | None = starts[0]
    while current is not None:
        if current in order:
            raise ValueError("v1 flow cannot contain cycles")
        order.append(current)
        current = outgoing[current][0] if outgoing[current] else None
    if len(order) != len(ids):
        raise ValueError("v1 flow cannot contain disconnected nodes")
    return order


def migrate_v1_bot(value: dict[object, object]) -> dict[object, object]:
    flow = value.get("flow")
    if not isinstance(flow, dict) or set(flow) != {"nodes", "edges"}:
        raise ValueError("invalid v1 flow")
    nodes, edges = flow.get("nodes"), flow.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        raise ValueError("invalid v1 flow")
    root = _derive_v1_order(nodes, edges)
    migrated_nodes = []
    for raw in nodes:
        if not isinstance(raw, dict):
            raise ValueError("invalid v1 node")
        migrated_nodes.append(dict(raw))
    return {**value, "schemaVersion": 2, "flow": {"root": root, "nodes": migrated_nodes}}
