import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import ntpath
import re
import threading
import unicodedata
from pathlib import Path, PureWindowsPath
from types import MappingProxyType
from typing import TYPE_CHECKING, Mapping
from pydantic import JsonValue

from autoclick_desktop.action_registry import ActionField
from autoclick_desktop.bot_schema import Bot

if TYPE_CHECKING:
    from autoclick_desktop.execution_context import LocalPathInspector, VirtualDesktopProvider


PUBLIC_BLOCK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
RUN_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def validate_run_id(value: str) -> str:
    if RUN_ID.fullmatch(value) is None:
        raise ValueError("run ID must be a bounded opaque identifier")
    return value


def assign_public_block_ids(values: list[str]) -> tuple[str, ...]:
    reserved = {value for value in values if PUBLIC_BLOCK_ID.fullmatch(value) is not None}
    assigned: set[str] = set()
    result: list[str] = []
    for index, value in enumerate(values):
        if PUBLIC_BLOCK_ID.fullmatch(value) is not None and value not in assigned:
            candidate = value
        else:
            digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:10]
            base = f"block-{index + 1}-{digest}"
            candidate = base
            suffix = 2
            while candidate in reserved or candidate in assigned:
                candidate = f"{base}-{suffix}"
                suffix += 1
        assigned.add(candidate)
        result.append(candidate)
    return tuple(result)


def normalize_windows_path_key(path: str | Path | PureWindowsPath) -> str:
    normalized = unicodedata.normalize("NFC", str(path)).replace("/", "\\")
    return ntpath.normpath(normalized).lower()


class RunStatus(StrEnum):
    VALIDATING = "validating"
    RUNNING = "running"
    CANCEL_REQUESTED = "cancel_requested"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


ACTIVE_RUN_STATUSES = frozenset(
    {RunStatus.VALIDATING, RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED}
)
TERMINAL_RUN_STATUSES = frozenset(
    {RunStatus.SUCCEEDED, RunStatus.FAILED, RunStatus.CANCELLED}
)


class ValidationIssueCode(StrEnum):
    BOT_INVALID = "BOT_INVALID"
    EMPTY_BOT = "EMPTY_BOT"
    INVALID_SEQUENCE = "INVALID_SEQUENCE"
    UNSUPPORTED_ACTION = "UNSUPPORTED_ACTION"
    UNKNOWN_HANDLER = "UNKNOWN_HANDLER"
    PARAMETER_REQUIRED = "PARAMETER_REQUIRED"
    PARAMETER_INVALID = "PARAMETER_INVALID"
    COORDINATE_PAIR_REQUIRED = "COORDINATE_PAIR_REQUIRED"
    COORDINATE_OUT_OF_BOUNDS = "COORDINATE_OUT_OF_BOUNDS"
    KEY_INVALID = "KEY_INVALID"
    CELL_INVALID = "CELL_INVALID"
    PATH_INVALID = "PATH_INVALID"
    VARIABLE_TOKEN_INVALID = "VARIABLE_TOKEN_INVALID"
    VARIABLE_MISSING = "VARIABLE_MISSING"
    VARIABLE_AMBIGUOUS = "VARIABLE_AMBIGUOUS"
    VARIABLE_DUPLICATE = "VARIABLE_DUPLICATE"
    VARIABLE_CYCLE = "VARIABLE_CYCLE"
    VARIABLE_DEPTH_EXCEEDED = "VARIABLE_DEPTH_EXCEEDED"
    VARIABLE_EXPANDED_SIZE_EXCEEDED = "VARIABLE_EXPANDED_SIZE_EXCEEDED"
    VARIABLE_TOKEN_COUNT_EXCEEDED = "VARIABLE_TOKEN_COUNT_EXCEEDED"
    WORKBOOK_MISSING = "WORKBOOK_MISSING"
    WORKBOOK_DUPLICATE = "WORKBOOK_DUPLICATE"
    WORKBOOK_CLOSED = "WORKBOOK_CLOSED"
    WORKBOOK_PATH_DUPLICATE = "WORKBOOK_PATH_DUPLICATE"


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: ValidationIssueCode
    block_id: str | None = None
    field_name: str | None = None
    block_path: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class DeferredFieldValidation:
    field: ActionField


class RuntimeReservationConflict(Exception):
    def __init__(self, *, name: bool, path: bool) -> None:
        self.name = name
        self.path = path
        super().__init__("runtime resource reservation conflict")


class RuntimeOpenReservation:
    __slots__ = ("_state", "_name", "_path", "_confirmed")

    def __init__(
        self, state: "RuntimeValidationState", name: str, path: PureWindowsPath
    ) -> None:
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_path", path)
        object.__setattr__(self, "_confirmed", False)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("workbook reservation identity is immutable")

    @property
    def name(self) -> str:
        return self._name

    @property
    def path(self) -> PureWindowsPath:
        return self._path

    def rollback(self) -> bool:
        return self._state.release_reservation(self)


class RuntimeValidationState:
    """Owns run-scoped reservations for resources resolved immediately before use."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._by_name: dict[str, RuntimeOpenReservation] = {}
        self._by_path: dict[str, RuntimeOpenReservation] = {}
        self._opened_paths: set[str] = set()
        self._close_claims: dict[RuntimeOpenReservation, RuntimeCloseClaim] = {}
        self._save_claims_by_path: dict[str, RuntimeSaveAsClaim] = {}
        self._save_claims_by_reservation: dict[RuntimeOpenReservation, RuntimeSaveAsClaim] = {}
        self._published_not_live: dict[str, RuntimePublishedPath] = {}
        self._base_resolution: tuple[int, int] | None = None

    def set_base_resolution(self, width: int, height: int) -> None:
        with self._lock:
            self._base_resolution = (width, height)

    def get_base_resolution(self) -> tuple[int, int] | None:
        with self._lock:
            return self._base_resolution

    def open_workbook_names(self) -> frozenset[str]:
        with self._lock:
            return frozenset(
                name for name, reservation in self._by_name.items() if reservation._confirmed
            )

    def reserve_open(self, name: str, path: PureWindowsPath) -> RuntimeOpenReservation:
        path_key = normalize_windows_path_key(path)
        with self._lock:
            name_conflict = name in self._by_name
            path_conflict = (
                path_key in self._by_path
                or path_key in self._opened_paths
                or path_key in self._save_claims_by_path
            )
            if name_conflict or path_conflict:
                raise RuntimeReservationConflict(name=name_conflict, path=path_conflict)
            reservation = RuntimeOpenReservation(self, name, path)
            self._by_name[name] = reservation
            self._by_path[path_key] = reservation
            return reservation

    def confirm_open(self, reservation: RuntimeOpenReservation) -> bool:
        with self._lock:
            if self._by_name.get(reservation.name) is not reservation:
                return False
            object.__setattr__(reservation, "_confirmed", True)
            self._opened_paths.add(normalize_windows_path_key(reservation.path))
            return True

    def claim_close(self, name: str) -> "RuntimeCloseClaim | None":
        with self._lock:
            reservation = self._by_name.get(name)
            if reservation is None or not reservation._confirmed:
                return None
            if (
                reservation in self._close_claims
                or reservation in self._save_claims_by_reservation
            ):
                raise RuntimeCloseConflict
            claim = RuntimeCloseClaim(self, reservation)
            self._close_claims[reservation] = claim
            return claim

    def get_open(self, name: str) -> RuntimeOpenReservation | None:
        with self._lock:
            reservation = self._by_name.get(name)
            if reservation is None or not reservation._confirmed:
                return None
            return reservation

    def claim_save_as(
        self, reservation: RuntimeOpenReservation, destination: PureWindowsPath
    ) -> "RuntimeSaveAsClaim":
        destination_key = normalize_windows_path_key(destination)
        with self._lock:
            active = self._by_name.get(reservation.name) is reservation
            pending_for_resource = reservation in self._save_claims_by_reservation
            path_conflict = (
                destination_key in self._by_path
                or destination_key in self._opened_paths
                or destination_key in self._save_claims_by_path
            )
            if (
                not active
                or not reservation._confirmed
                or reservation in self._close_claims
                or pending_for_resource
                or path_conflict
            ):
                raise RuntimeSaveAsConflict(resource=not active or pending_for_resource, path=path_conflict)
            claim = RuntimeSaveAsClaim(self, reservation, destination)
            self._save_claims_by_path[destination_key] = claim
            self._save_claims_by_reservation[reservation] = claim
            return claim

    def commit_save_as(self, claim: "RuntimeSaveAsClaim") -> bool:
        with self._lock:
            reservation = claim.reservation
            destination = claim.destination
            destination_key = normalize_windows_path_key(destination)
            if (
                self._save_claims_by_path.get(destination_key) is not claim
                or self._save_claims_by_reservation.get(reservation) is not claim
                or self._by_name.get(reservation.name) is not reservation
                or not reservation._confirmed
            ):
                return False
            old_path = reservation.path
            old_path_key = normalize_windows_path_key(old_path)
            if self._by_path.get(old_path_key) is reservation:
                del self._by_path[old_path_key]
            self._by_path[destination_key] = reservation
            self._opened_paths.add(old_path_key)
            self._opened_paths.add(destination_key)
            object.__setattr__(reservation, "_path", destination)
            self._remove_save_claim_locked(claim)
            return True

    def rollback_save_as(self, claim: "RuntimeSaveAsClaim") -> bool:
        destination_key = normalize_windows_path_key(claim.destination)
        with self._lock:
            if (
                self._save_claims_by_path.get(destination_key) is not claim
                or self._save_claims_by_reservation.get(claim.reservation) is not claim
            ):
                return False
            self._remove_save_claim_locked(claim)
            return True

    def retain_published_save_as(
        self, claim: "RuntimeSaveAsClaim", identity: object
    ) -> bool:
        with self._lock:
            destination_key = normalize_windows_path_key(claim.destination)
            if (
                self._save_claims_by_path.get(destination_key) is not claim
                or self._save_claims_by_reservation.get(claim.reservation) is not claim
                or self._by_name.get(claim.reservation.name) is not claim.reservation
            ):
                return False
            self._opened_paths.add(destination_key)
            self._published_not_live[destination_key] = RuntimePublishedPath(
                claim.reservation, claim.destination, identity
            )
            self._remove_save_claim_locked(claim)
            return True

    def is_published_not_live(self, path: PureWindowsPath) -> bool:
        with self._lock:
            return normalize_windows_path_key(path) in self._published_not_live

    def owns_published_identity(
        self, path: PureWindowsPath, identity: object
    ) -> bool:
        with self._lock:
            published = self._published_not_live.get(normalize_windows_path_key(path))
            return published is not None and published.identity == identity

    def release_reservation(self, reservation: RuntimeOpenReservation) -> bool:
        with self._lock:
            if self._by_name.get(reservation.name) is not reservation:
                return False
            if reservation._confirmed:
                return False
            if reservation in self._close_claims:
                return False
            self._release_locked(reservation)
            return True

    def complete_close(self, claim: "RuntimeCloseClaim") -> bool:
        with self._lock:
            reservation = claim.reservation
            if self._close_claims.get(reservation) is not claim:
                return False
            if self._by_name.get(reservation.name) is not reservation:
                del self._close_claims[reservation]
                return False
            del self._close_claims[reservation]
            self._release_locked(reservation)
            return True

    def rollback_close(self, claim: "RuntimeCloseClaim") -> bool:
        with self._lock:
            reservation = claim.reservation
            if self._close_claims.get(reservation) is not claim:
                return False
            del self._close_claims[reservation]
            return True

    def _release_locked(self, reservation: RuntimeOpenReservation) -> None:
        if self._by_name.get(reservation.name) is reservation:
            del self._by_name[reservation.name]
        path_key = normalize_windows_path_key(reservation.path)
        if self._by_path.get(path_key) is reservation:
            del self._by_path[path_key]

    def _remove_save_claim_locked(self, claim: "RuntimeSaveAsClaim") -> None:
        destination_key = normalize_windows_path_key(claim.destination)
        if self._save_claims_by_path.get(destination_key) is claim:
            del self._save_claims_by_path[destination_key]
        if self._save_claims_by_reservation.get(claim.reservation) is claim:
            del self._save_claims_by_reservation[claim.reservation]


class RuntimeCloseConflict(Exception):
    pass


class RuntimeCloseClaim:
    __slots__ = ("_state", "_reservation")

    def __init__(
        self, state: RuntimeValidationState, reservation: RuntimeOpenReservation
    ) -> None:
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_reservation", reservation)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("close claim identity is immutable")

    @property
    def reservation(self) -> RuntimeOpenReservation:
        return self._reservation

    def complete(self) -> bool:
        return self._state.complete_close(self)

    def rollback(self) -> bool:
        return self._state.rollback_close(self)


class RuntimeSaveAsConflict(Exception):
    def __init__(self, *, resource: bool, path: bool) -> None:
        self.resource = resource
        self.path = path
        super().__init__("runtime save-as reservation conflict")


class RuntimeSaveAsClaim:
    __slots__ = ("_state", "_reservation", "_destination")

    def __init__(
        self,
        state: RuntimeValidationState,
        reservation: RuntimeOpenReservation,
        destination: PureWindowsPath,
    ) -> None:
        object.__setattr__(self, "_state", state)
        object.__setattr__(self, "_reservation", reservation)
        object.__setattr__(self, "_destination", destination)

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("save-as claim identity is immutable")

    @property
    def reservation(self) -> RuntimeOpenReservation:
        return self._reservation

    @property
    def destination(self) -> PureWindowsPath:
        return self._destination

    def commit(self) -> bool:
        return self._state.commit_save_as(self)

    def rollback(self) -> bool:
        return self._state.rollback_save_as(self)

    def retain_published(self, identity: object) -> bool:
        return self._state.retain_published_save_as(self, identity)


@dataclass(frozen=True, slots=True)
class RuntimePublishedPath:
    reservation: RuntimeOpenReservation = field(repr=False, compare=False)
    destination: PureWindowsPath
    identity: object = field(repr=False, compare=False)


class ValidatedAction:
    """Immutable preflight product; normal construction is intentionally unavailable."""

    __slots__ = (
        "_block_id", "_action_id", "_handler_key", "_title", "_params", "_fields",
        "_deferred_validations", "_exact_token_fields", "_path", "_slots", "_source_node_id", "_editor_block_id", "_event_path",
        "_source_directory",
    )

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ValidatedAction instances are created by execution preflight")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ValidatedAction is immutable")

    @property
    def block_id(self) -> str:
        return self._block_id

    @property
    def source_node_id(self) -> str:
        return self._source_node_id

    @property
    def editor_block_id(self) -> str | None:
        return self._editor_block_id

    @property
    def action_id(self) -> str:
        return self._action_id

    @property
    def handler_key(self) -> str:
        return self._handler_key

    @property
    def title(self) -> str:
        return self._title

    @property
    def path(self) -> tuple[str, ...]:
        return self._path

    @property
    def event_path(self) -> tuple[str, ...]:
        return self._event_path

    @property
    def source_directory(self) -> PureWindowsPath:
        return self._source_directory

    @property
    def slots(self) -> tuple[str, ...]:
        return self._slots

    @property
    def params(self) -> Mapping[str, JsonValue | PureWindowsPath]:
        return MappingProxyType(copy.deepcopy(self._params))

    @property
    def fields(self) -> tuple[ActionField, ...]:
        return tuple(field.model_copy(deep=True) for field in self._fields)

    @property
    def deferred_validations(self) -> tuple[DeferredFieldValidation, ...]:
        return tuple(
            DeferredFieldValidation(item.field.model_copy(deep=True))
            for item in self._deferred_validations
        )

    def is_exact_token(self, field_name: str) -> bool:
        return field_name in self._exact_token_fields

    def resolve(
        self,
        variables: Mapping[str, JsonValue],
        *,
        bot_directory: str | Path | PureWindowsPath,
        virtual_desktop: "VirtualDesktopProvider",
        validation_state: RuntimeValidationState,
        local_paths: "LocalPathInspector | None" = None,
    ) -> "ResolvedAction":
        from autoclick_desktop.execution_validation import _resolve_validated_action

        return _resolve_validated_action(
            self,
            variables,
            bot_directory=bot_directory,
            virtual_desktop=virtual_desktop,
            validation_state=validation_state,
            local_paths=local_paths,
        )


@dataclass(frozen=True, slots=True, init=False)
class ResolvedAction:
    """Application invariant type, not a sandbox against malicious in-process code."""

    block_id: str
    action_id: str
    handler_key: str
    title: str
    params: Mapping[str, JsonValue | PureWindowsPath]
    _validation_state: RuntimeValidationState = field(repr=False, compare=False)
    _open_reservation: RuntimeOpenReservation | None = field(repr=False, compare=False)
    _close_claim: RuntimeCloseClaim | None = field(repr=False, compare=False)
    _workbook_reservation: RuntimeOpenReservation | None = field(repr=False, compare=False)
    _save_as_claim: RuntimeSaveAsClaim | None = field(repr=False, compare=False)
    _exact_token_fields: frozenset[str] = field(repr=False, compare=False)

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ResolvedAction instances are created by ValidatedAction.resolve")

    def rollback_open_reservation(self) -> None:
        if self._open_reservation is not None:
            self._open_reservation.rollback()

    def confirm_open_reservation(self) -> bool:
        if self._open_reservation is None:
            raise ValueError("only excel.open has an open reservation")
        return self._validation_state.confirm_open(self._open_reservation)

    @property
    def workbook_reservation(self) -> RuntimeOpenReservation:
        if self._open_reservation is not None:
            return self._open_reservation
        if self._close_claim is not None:
            return self._close_claim.reservation
        if self._workbook_reservation is not None:
            return self._workbook_reservation
        raise ValueError("action does not carry a workbook reservation")

    def is_exact_token(self, field_name: str) -> bool:
        return field_name in self._exact_token_fields

    def release_closed_workbook(self) -> bool:
        if self.action_id != "excel.close":
            raise ValueError("only a successful excel.close can release a workbook")
        if self._close_claim is None:
            return False
        return self._close_claim.complete()

    def rollback_close_claim(self) -> bool:
        if self._close_claim is None:
            raise ValueError("only excel.close has a close claim")
        return self._close_claim.rollback()

    def commit_save_as_claim(self) -> bool:
        if self._save_as_claim is None:
            raise ValueError("only excel.save with a destination has a save-as claim")
        return self._save_as_claim.commit()

    def rollback_save_as_claim(self) -> bool:
        if self._save_as_claim is None:
            return False
        return self._save_as_claim.rollback()

    def retain_published_save_as_claim(self, identity: object) -> bool:
        if self._save_as_claim is None:
            return False
        return self._save_as_claim.retain_published(identity)

    def set_base_resolution(self, width: int, height: int) -> None:
        if self.action_id != "system.setBaseResolution":
            raise ValueError("only system.setBaseResolution can change coordinate space")
        self._validation_state.set_base_resolution(width, height)


@dataclass(frozen=True, slots=True)
class PlannedNode:
    action: ValidatedAction
    slots: Mapping[str, tuple["PlannedNode", ...]]


class ExecutionPlan:
    """Dispatcher input; each action must be resolved internally before handling."""

    __slots__ = ("_bot", "actions", "roots", "bot_directory")
    actions: tuple[ValidatedAction, ...]
    roots: tuple[PlannedNode, ...]
    bot_directory: PureWindowsPath

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ExecutionPlan instances are created by execution preflight")

    def __setattr__(self, _name: str, _value: object) -> None:
        raise AttributeError("ExecutionPlan is immutable")

    @property
    def bot(self) -> Bot:
        return self._bot.model_copy(deep=True)


@dataclass(slots=True)
class RunState:
    run_id: str
    status: RunStatus = RunStatus.VALIDATING
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_block_id: str | None = None
    current_editor_block_id: str | None = None
    current_block_index: int | None = None
    total_blocks: int = 0

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)

    @property
    def cancel_requested(self) -> bool:
        return self.status is RunStatus.CANCEL_REQUESTED

    def transition(self, status: RunStatus) -> None:
        allowed = {
            RunStatus.VALIDATING: {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCEL_REQUESTED},
            RunStatus.RUNNING: {
                RunStatus.CANCEL_REQUESTED,
                RunStatus.SUCCEEDED,
                RunStatus.FAILED,
                RunStatus.CANCELLED,
            },
            RunStatus.CANCEL_REQUESTED: {RunStatus.CANCELLED, RunStatus.FAILED},
        }
        if status is self.status:
            return
        if status not in allowed.get(self.status, set()):
            raise ValueError("invalid run status transition")
        self.status = status
