import re
import threading
from collections import deque
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import PureWindowsPath

from autoclick_desktop.action_registry import ActionDefinition
from autoclick_desktop.execution_errors import ExecutionErrorCode
from autoclick_desktop.execution_errors import SafeExecutionError
from autoclick_desktop.execution_models import (
    PUBLIC_BLOCK_ID,
    RunState,
    RunStatus,
    validate_run_id,
)


class EventType(StrEnum):
    RUN_VALIDATING = "run.validating"
    RUN_STARTED = "run.started"
    BLOCK_STARTED = "block.started"
    BLOCK_SUCCEEDED = "block.succeeded"
    BLOCK_WARNING = "block.warning"
    BLOCK_FAILED = "block.failed"
    BLOCK_STOPPED = "block.stopped"
    BLOCK_CANCELLED = "block.cancelled"
    RUN_CANCEL_REQUESTED = "run.cancel_requested"
    RUN_CLEANUP_PENDING = "run.cleanup_pending"
    RUN_CANCELLED = "run.cancelled"
    RUN_SUCCEEDED = "run.succeeded"
    RUN_FAILED = "run.failed"


class EventLevel(StrEnum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


class EventMessage(StrEnum):
    RUN_VALIDATING = "Validando el bot."
    RUN_STARTED = "La ejecución comenzó."
    BLOCK_STARTED = "El bloque comenzó."
    BLOCK_SUCCEEDED = "El bloque finalizó correctamente."
    BLOCK_WARNING = "El bloque finalizó con una advertencia."
    BLOCK_FAILED = "El bloque no pudo completarse."
    BLOCK_STOPPED = "El bloque se detuvo de forma controlada."
    BLOCK_CANCELLED = "El bloque fue cancelado."
    RUN_CANCEL_REQUESTED = "Se solicitó cancelar la ejecución."
    RUN_CLEANUP_PENDING = "Finalizando recursos de Excel."
    RUN_CANCELLED = "La ejecución fue cancelada."
    RUN_SUCCEEDED = "La ejecución finalizó correctamente."
    RUN_FAILED = "La ejecución no pudo completarse."


LEVEL_BY_TYPE = {
    EventType.RUN_VALIDATING: EventLevel.INFO,
    EventType.RUN_STARTED: EventLevel.INFO,
    EventType.BLOCK_STARTED: EventLevel.INFO,
    EventType.BLOCK_SUCCEEDED: EventLevel.INFO,
    EventType.BLOCK_WARNING: EventLevel.WARNING,
    EventType.BLOCK_FAILED: EventLevel.ERROR,
    EventType.BLOCK_STOPPED: EventLevel.INFO,
    EventType.BLOCK_CANCELLED: EventLevel.INFO,
    EventType.RUN_CANCEL_REQUESTED: EventLevel.INFO,
    EventType.RUN_CLEANUP_PENDING: EventLevel.WARNING,
    EventType.RUN_CANCELLED: EventLevel.INFO,
    EventType.RUN_SUCCEEDED: EventLevel.INFO,
    EventType.RUN_FAILED: EventLevel.ERROR,
}
MESSAGE_BY_TYPE = dict(zip(EventType, EventMessage, strict=True))
TERMINAL_EVENT_TYPES = frozenset(
    {EventType.RUN_CANCELLED, EventType.RUN_SUCCEEDED, EventType.RUN_FAILED}
)
_CONTROL_CHARACTERS = re.compile(r"[\x00-\x1f\x7f-\x9f]+")


def _plain_text(value: str) -> str:
    return _CONTROL_CHARACTERS.sub(" ", value)


@dataclass(frozen=True, slots=True)
class ExecutionEvent:
    schema_version: int
    run_id: str
    sequence: int
    timestamp: str
    type: EventType
    level: EventLevel
    message: str
    details: str | None = None
    block_id: str | None = None
    editor_block_id: str | None = None
    block_name: str | None = None
    block_index: int | None = None
    block_path: tuple[str, ...] | None = None
    code: str | None = None

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)

    def as_dict(self) -> dict[str, object]:
        values = {
            "schemaVersion": self.schema_version,
            "runId": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "type": self.type.value,
            "level": self.level.value,
            "blockId": self.block_id,
            "editorBlockId": self.editor_block_id,
            "blockName": self.block_name,
            "blockIndex": self.block_index,
            "blockPath": list(self.block_path) if self.block_path is not None else None,
            "message": self.message,
            "details": self.details,
            "code": self.code,
        }
        return {key: value for key, value in values.items() if value is not None}


@dataclass(frozen=True, slots=True)
class EventBatch:
    events: tuple[ExecutionEvent, ...]
    next_sequence: int
    events_truncated: bool


@dataclass(frozen=True, slots=True)
class EventBlock:
    block_id: str
    block_name: str
    block_index: int
    block_path: tuple[str, ...] = ()
    editor_block_id: str | None = None

    def __post_init__(self) -> None:
        if PUBLIC_BLOCK_ID.fullmatch(self.block_id) is None:
            raise ValueError("event block ID is not a safe public identifier")
        object.__setattr__(self, "block_name", _plain_text(self.block_name))
        object.__setattr__(self, "block_path", tuple(_plain_text(part) for part in self.block_path))

    @classmethod
    def from_action(
        cls, block_id: str, block_index: int, action: ActionDefinition
    ) -> "EventBlock":
        return cls(_plain_text(block_id), _plain_text(action.title), block_index)


class EventDetails:
    __slots__ = ("text",)

    def __init__(self, *, filename: str) -> None:
        safe_filename = PureWindowsPath(filename).name
        self.text = f"Archivo: {_plain_text(safe_filename)}"


class BoundedEventBuffer:
    """Builds events from fixed safe messages; payload values are never accepted."""

    def __init__(self, run_id: str, capacity: int = 1_000) -> None:
        if not 1 <= capacity <= 1_000:
            raise ValueError("event buffer capacity must be between 1 and 1000")
        self._run_id = validate_run_id(run_id)
        self._events: deque[ExecutionEvent] = deque(maxlen=capacity)
        self._sequence = 0
        self._terminal_emitted = False
        self._lock = threading.Lock()

    def emit(
        self,
        event_type: EventType,
        *,
        block: EventBlock | None = None,
        code: ExecutionErrorCode | None = None,
        details: EventDetails | None = None,
    ) -> ExecutionEvent:
        with self._lock:
            event = self._prepare_locked(
                event_type, block=block, code=code, details=details
            )
            self._commit_locked(event)
            return event

    def _prepare(
        self,
        event_type: EventType,
        *,
        block: EventBlock | None = None,
        code: ExecutionErrorCode | None = None,
        details: EventDetails | None = None,
    ) -> ExecutionEvent:
        with self._lock:
            return self._prepare_locked(
                event_type, block=block, code=code, details=details
            )

    def _prepare_locked(
        self,
        event_type: EventType,
        *,
        block: EventBlock | None,
        code: ExecutionErrorCode | None,
        details: EventDetails | None,
    ) -> ExecutionEvent:
        if self._terminal_emitted:
            raise RuntimeError("a terminal run event has already been emitted")
        return self._build_event(
            event_type,
            self._sequence + 1,
            block=block,
            code=code,
            details=details,
        )

    def _build_event(
        self,
        event_type: EventType,
        sequence: int,
        *,
        block: EventBlock | None,
        code: ExecutionErrorCode | None,
        details: EventDetails | None,
    ) -> ExecutionEvent:
        return ExecutionEvent(
            schema_version=1,
            run_id=self._run_id,
            sequence=sequence,
            timestamp=datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            type=event_type,
            level=LEVEL_BY_TYPE[event_type],
            message=MESSAGE_BY_TYPE[event_type].value,
            details=details.text if details is not None else None,
            block_id=block.block_id if block is not None else None,
            editor_block_id=block.editor_block_id if block is not None else None,
            block_name=block.block_name if block is not None else None,
            block_index=block.block_index if block is not None else None,
            block_path=block.block_path if block is not None and block.block_path else None,
            code=code.value if code is not None else None,
        )

    def _commit(self, event: ExecutionEvent) -> None:
        with self._lock:
            self._commit_locked(event)

    def _commit_locked(self, event: ExecutionEvent) -> None:
        self._commit_many_locked((event,))

    def _prepare_many(
        self,
        specifications: tuple[
            tuple[EventType, EventBlock | None, ExecutionErrorCode | None], ...
        ],
    ) -> tuple[ExecutionEvent, ...]:
        with self._lock:
            if self._terminal_emitted:
                raise RuntimeError("a terminal run event has already been emitted")
            events = tuple(
                self._build_event(
                    event_type,
                    self._sequence + offset,
                    block=block,
                    code=code,
                    details=None,
                )
                for offset, (event_type, block, code) in enumerate(
                    specifications, start=1
                )
            )
            if any(event.type in TERMINAL_EVENT_TYPES for event in events[:-1]):
                raise RuntimeError("a terminal event must end an event batch")
            return events

    def _commit_many(self, events: tuple[ExecutionEvent, ...]) -> None:
        with self._lock:
            self._commit_many_locked(events)

    def _commit_many_locked(self, events: tuple[ExecutionEvent, ...]) -> None:
        if (
            not events
            or self._terminal_emitted
            or events[0].sequence != self._sequence + 1
            or any(
                event.sequence != events[0].sequence + index
                for index, event in enumerate(events)
            )
        ):
            raise RuntimeError("prepared event is stale")
        committed_events = self._committed_events(events)
        self._events = committed_events
        self._sequence = events[-1].sequence
        if events[-1].type in TERMINAL_EVENT_TYPES:
            self._terminal_emitted = True

    def _committed_events(
        self, events: tuple[ExecutionEvent, ...]
    ) -> deque[ExecutionEvent]:
        committed = deque(self._events, maxlen=self._events.maxlen)
        committed.extend(events)
        return committed

    def after(self, sequence: int) -> EventBatch:
        if isinstance(sequence, bool) or not isinstance(sequence, int) or sequence < 0:
            raise ValueError("event sequence must be a non-negative integer")
        with self._lock:
            if sequence > self._sequence:
                raise SafeExecutionError(ExecutionErrorCode.EVENT_CURSOR_AHEAD)
            oldest = self._events[0].sequence if self._events else self._sequence + 1
            return EventBatch(
                events=tuple(event for event in self._events if event.sequence > sequence),
                next_sequence=self._sequence,
                events_truncated=sequence < oldest - 1,
            )

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)


_EVENT_BY_STATUS = {
    RunStatus.RUNNING: EventType.RUN_STARTED,
    RunStatus.CANCEL_REQUESTED: EventType.RUN_CANCEL_REQUESTED,
    RunStatus.SUCCEEDED: EventType.RUN_SUCCEEDED,
    RunStatus.FAILED: EventType.RUN_FAILED,
    RunStatus.CANCELLED: EventType.RUN_CANCELLED,
}


class RunJournal:
    """Synchronizes private run state and its matching event stream."""

    def __init__(self, run_id: str, *, total_blocks: int = 0, capacity: int = 1_000) -> None:
        run_id = validate_run_id(run_id)
        self._lock = threading.RLock()
        self._state = RunState(run_id, total_blocks=total_blocks)
        self._events = BoundedEventBuffer(run_id, capacity)
        self._events.emit(EventType.RUN_VALIDATING)

    def transition(
        self,
        status: RunStatus,
        *,
        code: ExecutionErrorCode | None = None,
    ) -> ExecutionEvent | None:
        event_type = _EVENT_BY_STATUS.get(status)
        if event_type is None:
            raise ValueError("status has no transition event")
        with self._lock:
            if self._state.status is status:
                return None
            next_state = replace(self._state)
            next_state.transition(status)
            event = self._events._prepare(event_type, code=code)
            self._events._commit(event)
            self._state = next_state
            return event

    def configure_total_blocks(self, total_blocks: int) -> None:
        if isinstance(total_blocks, bool) or not isinstance(total_blocks, int) or total_blocks < 0:
            raise ValueError("total blocks must be a non-negative integer")
        with self._lock:
            if self._state.status is not RunStatus.VALIDATING or self._state.total_blocks != 0:
                raise ValueError("total blocks can only be configured once during validation")
            self._state.total_blocks = total_blocks

    def request_cancel(self) -> ExecutionEvent | None:
        with self._lock:
            if self._state.status in {RunStatus.CANCEL_REQUESTED, RunStatus.CANCELLED}:
                return None
            return self.transition(RunStatus.CANCEL_REQUESTED)

    def start_block(self, block: EventBlock) -> ExecutionEvent:
        with self._lock:
            if self._state.status is not RunStatus.RUNNING:
                raise ValueError("blocks can only start while running")
            event = self._events._prepare(EventType.BLOCK_STARTED, block=block)
            self._events._commit(event)
            self._state.current_block_id = block.block_id
            self._state.current_editor_block_id = block.editor_block_id
            self._state.current_block_index = block.block_index
            return event

    def finish_block(
        self,
        block: EventBlock,
        *,
        warning: bool = False,
        code: ExecutionErrorCode | None = None,
    ) -> ExecutionEvent:
        with self._lock:
            if self._state.status not in {RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED}:
                raise ValueError("blocks can only finish during an active run")
            event_type = EventType.BLOCK_WARNING if warning else EventType.BLOCK_SUCCEEDED
            return self._events.emit(event_type, block=block, code=code)

    def block_failed(
        self,
        block: EventBlock,
        *,
        code: ExecutionErrorCode = ExecutionErrorCode.ACTION_PARAMETER_INVALID,
    ) -> tuple[ExecutionEvent, ExecutionEvent] | None:
        with self._lock:
            if self._state.status is RunStatus.FAILED:
                return None
            if self._state.status is not RunStatus.RUNNING:
                raise ValueError("a block can only fail while running")
            next_state = replace(self._state)
            next_state.transition(RunStatus.FAILED)
            events = self._events._prepare_many(
                (
                    (EventType.BLOCK_FAILED, block, code),
                    (EventType.RUN_FAILED, None, code),
                )
            )
            self._events._commit_many(events)
            next_state.current_block_id = block.block_id
            next_state.current_editor_block_id = block.editor_block_id
            next_state.current_block_index = block.block_index
            self._state = next_state
            return events

    def fail_block(
        self,
        block: EventBlock,
        *,
        code: ExecutionErrorCode = ExecutionErrorCode.ACTION_PARAMETER_INVALID,
    ) -> ExecutionEvent:
        with self._lock:
            if self._state.status is not RunStatus.RUNNING:
                raise ValueError("a block can only fail while running")
            return self._events.emit(EventType.BLOCK_FAILED, block=block, code=code)

    def stop_block(self, block: EventBlock) -> ExecutionEvent:
        with self._lock:
            if self._state.status is not RunStatus.RUNNING:
                raise ValueError("a block can only stop while running")
            return self._events.emit(EventType.BLOCK_STOPPED, block=block)

    def cancel_block(self, block: EventBlock) -> ExecutionEvent:
        with self._lock:
            if self._state.status not in {RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED}:
                raise ValueError("a block can only be cancelled during an active run")
            return self._events.emit(EventType.BLOCK_CANCELLED, block=block)

    def cleanup_warning(
        self,
        *,
        block: EventBlock | None = None,
        code: ExecutionErrorCode | None = None,
    ) -> ExecutionEvent:
        """Record cleanup trouble without changing the business terminal outcome."""
        with self._lock:
            if self._state.status not in {RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED}:
                raise ValueError("cleanup warnings must precede terminal completion")
            return self._events.emit(EventType.BLOCK_WARNING, block=block, code=code)

    def cleanup_pending(self) -> ExecutionEvent:
        with self._lock:
            if self._state.status not in {RunStatus.RUNNING, RunStatus.CANCEL_REQUESTED}:
                raise ValueError("cleanup progress requires an active run")
            return self._events.emit(
                EventType.RUN_CLEANUP_PENDING,
                code=ExecutionErrorCode.RESOURCE_CLEANUP_FAILED,
            )

    def read(self, after_sequence: int) -> "JournalRead":
        with self._lock:
            return JournalRead(replace(self._state), self._events.after(after_sequence))

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    @property
    def run_id(self) -> str:
        return self._state.run_id


@dataclass(frozen=True, slots=True)
class JournalRead:
    state: RunState
    event_batch: EventBatch
