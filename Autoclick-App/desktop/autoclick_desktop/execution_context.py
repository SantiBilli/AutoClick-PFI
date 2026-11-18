from dataclasses import dataclass, field
from pathlib import PureWindowsPath
from threading import Event
from typing import Protocol, runtime_checkable

from pydantic import JsonValue

from autoclick_desktop.execution_events import RunJournal
from autoclick_desktop.execution_models import (
    ExecutionPlan,
    RuntimeOpenReservation,
    validate_run_id,
)
from autoclick_desktop.execution_errors import StepBudgetExceeded


MAX_EXECUTED_STEPS = 100_000
DEFAULT_EXECUTED_STEP_LIMIT = MAX_EXECUTED_STEPS


@dataclass(frozen=True, slots=True)
class VirtualDesktopBounds:
    left: int
    top: int
    width: int
    height: int

    def __post_init__(self) -> None:
        if self.width <= 0 or self.height <= 0:
            raise ValueError("virtual desktop dimensions must be positive")

    def contains(self, x: int, y: int) -> bool:
        return self.left <= x < self.left + self.width and self.top <= y < self.top + self.height


@runtime_checkable
class VirtualDesktopProvider(Protocol):
    def get_bounds(self) -> VirtualDesktopBounds: ...


@runtime_checkable
class LocalPathInspector(Protocol):
    def is_local_drive(self, path: PureWindowsPath) -> bool: ...

    def exists(self, path: PureWindowsPath) -> bool: ...

    def is_file(self, path: PureWindowsPath) -> bool: ...

    def is_directory(self, path: PureWindowsPath) -> bool: ...

    def is_reparse_point(self, path: PureWindowsPath) -> bool: ...


@runtime_checkable
class WorkbookResourceRegistry(Protocol):
    def register(self, reservation: RuntimeOpenReservation, workbook: object) -> None: ...

    def get(self, reservation: RuntimeOpenReservation) -> object: ...

    def remove(self, reservation: RuntimeOpenReservation) -> object: ...

    def close_all(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    run_id: str
    plan: ExecutionPlan
    cancel_event: Event
    journal: RunJournal
    resources: WorkbookResourceRegistry
    variables: dict[str, JsonValue] = field(default_factory=dict)
    executed_steps: int = 0
    step_limit: int = DEFAULT_EXECUTED_STEP_LIMIT

    def __post_init__(self) -> None:
        validate_run_id(self.run_id)
        if self.journal.run_id != self.run_id:
            raise ValueError("execution context and journal run IDs must match")
        if not isinstance(self.step_limit, int) or isinstance(self.step_limit, bool) or not 1 <= self.step_limit <= MAX_EXECUTED_STEPS:
            raise ValueError("invalid executed-step limit")

    def record_step(self) -> None:
        # Every entered action or structural container consumes one shared step.
        if self.executed_steps >= self.step_limit:
            raise StepBudgetExceeded()
        object.__setattr__(self, "executed_steps", self.executed_steps + 1)
