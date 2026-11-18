import copy
import secrets
import threading
import time
from collections import OrderedDict
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import PureWindowsPath
from typing import Callable, Mapping, Protocol, TypedDict

from pydantic import JsonValue, ValidationError

from autoclick_desktop.action_dispatcher import ActionDispatcher, available_handler_keys
from autoclick_desktop.action_registry import ActionRegistry, load_action_registry
from autoclick_desktop.bot_schema import CanonicalBotInput
from autoclick_desktop.bot_service import BotServiceError, EditorExecutionAuthorization
from autoclick_desktop.excel_actions import ExcelResourceManager, ResourceCleanupOutcome
from autoclick_desktop.execution_context import (
    ExecutionContext,
    LocalPathInspector,
    VirtualDesktopProvider,
)
from autoclick_desktop.execution_errors import (
    ExecutionCancelled,
    ExecutionErrorCode,
    ExecutionStopped,
    SafeExecutionError,
    StepBudgetExceeded,
)
from autoclick_desktop.conditions import Condition, evaluate_condition
from autoclick_desktop.execution_variables import resolve_value
from autoclick_desktop.execution_events import EventBlock, RunJournal
from autoclick_desktop.execution_models import (
    ExecutionPlan,
    PlannedNode,
    RunStatus,
    RuntimeValidationState,
    ValidationIssue,
    ValidationIssueCode,
)
from autoclick_desktop.execution_validation import (
    ResolvedActionValidationError,
    WindowsLocalPathInspector,
    validate_execution_draft,
)
from autoclick_desktop.keyboard_actions import Clipboard, KeyboardController
from autoclick_desktop.mouse_actions import (
    MouseController,
    WindowsVirtualDesktop,
)
from autoclick_desktop.platform_adapters import OperatingSystemAdapter, WindowAdapter


DEFAULT_RUN_RETENTION_COUNT = 20
DEFAULT_RUN_RETENTION_TTL_SECONDS = 15 * 60
DEFAULT_CLEANUP_RETRY_INTERVAL_SECONDS = 0.1
DEFAULT_CLEANUP_TIMEOUT_SECONDS = 5.0
MAX_LOOP_ITERATIONS = 10_000
from autoclick_desktop.workflow_compiler import compile_workflow_graph


class _ActionFailure(Exception):
    def __init__(self, error: SafeExecutionError, block: EventBlock) -> None:
        self.code = error.code
        self.block = block
        self.safe_message = error.safe_message
        self.validation_issues = tuple(
            {
                "code": issue.code.value,
                "field": issue.field_name,
                "blockId": issue.block_id or block.block_id,
                "blockPath": list(issue.block_path or block.block_path),
            }
            for issue in getattr(error, "issues", ())
        )
        super().__init__(self.safe_message)


class ExecutionStartResult(TypedDict):
    runId: str
    status: str
    startedAt: str


class ExecutionCancelResult(TypedDict):
    runId: str
    status: str


class ExecutionStatusResult(TypedDict):
    runId: str
    status: str
    currentBlockId: str | None
    currentEditorBlockId: str | None
    currentBlockIndex: int | None
    totalBlocks: int
    cancelRequested: bool
    events: list[dict[str, object]]
    nextSequence: int
    eventsTruncated: bool


class ExecutionAuthorizationService(Protocol):
    def authorize_execution(
        self, editor_token: str
    ) -> AbstractContextManager[EditorExecutionAuthorization]: ...


@dataclass(frozen=True, slots=True)
class ExecutionEnvironment:
    virtual_desktop: VirtualDesktopProvider
    local_paths: LocalPathInspector
    resources: ExcelResourceManager
    mouse: MouseController | None = None
    keyboard: KeyboardController | None = None
    clipboard: Clipboard | None = None
    operating_system: OperatingSystemAdapter | None = None
    windows: WindowAdapter | None = None
    http: object | None = None
    available_handlers: frozenset[str] | None = None

    def close(self) -> ResourceCleanupOutcome:
        shutdown = getattr(self.resources, "shutdown", None)
        if shutdown is None:
            return ResourceCleanupOutcome(True)
        outcome = shutdown()
        return outcome if isinstance(outcome, ResourceCleanupOutcome) else ResourceCleanupOutcome(False)


EnvironmentFactory = Callable[[threading.Event], ExecutionEnvironment]


def default_environment_factory(cancel_event: threading.Event) -> ExecutionEnvironment:
    """Create run adapters without importing optional automation backends."""
    local_paths = WindowsLocalPathInspector()
    return ExecutionEnvironment(
        virtual_desktop=WindowsVirtualDesktop(),
        local_paths=local_paths,
        resources=ExcelResourceManager(cancel_event, local_paths),
    )


@dataclass(slots=True)
class _RunSession:
    run_id: str
    journal: RunJournal
    cancel_event: threading.Event
    completed: threading.Event
    authorization: AbstractContextManager[EditorExecutionAuthorization] | None = None
    worker: threading.Thread | None = None
    cleanup_verified: bool = False
    terminal_published: bool = False
    cancel_journal_ready: bool = False


@dataclass(frozen=True, slots=True)
class _RetainedRun:
    journal: RunJournal
    completed_at: float


class ExecutionService:
    def __init__(
        self,
        bot_service: ExecutionAuthorizationService,
        *,
        registry: ActionRegistry | None = None,
        environment_factory: EnvironmentFactory = default_environment_factory,
        dispatcher_factory: Callable[..., ActionDispatcher] = ActionDispatcher,
        retention_count: int = DEFAULT_RUN_RETENTION_COUNT,
        retention_ttl_seconds: float = DEFAULT_RUN_RETENTION_TTL_SECONDS,
        event_capacity: int = 1_000,
        monotonic: Callable[[], float] = time.monotonic,
        thread_factory: Callable[..., threading.Thread] = threading.Thread,
        cleanup_retry_interval: float = DEFAULT_CLEANUP_RETRY_INTERVAL_SECONDS,
        cleanup_timeout: float = DEFAULT_CLEANUP_TIMEOUT_SECONDS,
        cleanup_retry_wait: Callable[[float], None] = time.sleep,
        executed_step_limit: int = 100_000,
    ) -> None:
        if (
            retention_count < 1
            or retention_ttl_seconds <= 0
            or cleanup_retry_interval <= 0
            or cleanup_timeout <= 0
        ):
            raise ValueError("invalid run retention policy")
        self._bot_service = bot_service
        self._registry = registry if registry is not None else load_action_registry()
        self._environment_factory = environment_factory
        self._dispatcher_factory = dispatcher_factory
        self._retention_count = retention_count
        self._retention_ttl_seconds = retention_ttl_seconds
        self._event_capacity = event_capacity
        self._monotonic = monotonic
        self._thread_factory = thread_factory
        self._cleanup_retry_interval = cleanup_retry_interval
        self._cleanup_timeout = cleanup_timeout
        self._cleanup_retry_wait = cleanup_retry_wait
        if not isinstance(executed_step_limit, int) or isinstance(executed_step_limit, bool) or not 1 <= executed_step_limit <= 100_000:
            raise ValueError("invalid executed-step limit")
        self._executed_step_limit = executed_step_limit
        self._lock = threading.RLock()
        self._active: _RunSession | None = None
        self._retained: OrderedDict[str, _RetainedRun] = OrderedDict()
        self._shutting_down = False

    def start(
        self, editor_token: str, draft: CanonicalBotInput | Mapping[str, object]
    ) -> ExecutionStartResult:
        run_id = secrets.token_urlsafe(32)
        journal = RunJournal(run_id, capacity=self._event_capacity)
        session = _RunSession(run_id, journal, threading.Event(), threading.Event())
        with self._lock:
            self._prune_locked()
            if self._shutting_down:
                raise SafeExecutionError(ExecutionErrorCode.EXECUTION_SHUTTING_DOWN)
            if self._active is not None:
                raise SafeExecutionError(ExecutionErrorCode.EXECUTION_ALREADY_ACTIVE)
            self._active = session

        authorization: AbstractContextManager[EditorExecutionAuthorization] | None = None
        cleanup_owner: object | None = None
        worker_started = False
        try:
            authorization = self._bot_service.authorize_execution(editor_token)
            source = authorization.__enter__()
            session.authorization = authorization
            immutable_draft = copy.deepcopy(draft)
            environment = self._environment_factory(session.cancel_event)
            cleanup_owner = environment
            environment_handler_keys = environment.available_handlers if environment.available_handlers is not None else available_handler_keys(
                mouse=environment.mouse,
                keyboard=environment.keyboard,
                clipboard=environment.clipboard,
                excel=environment.resources,
                operating_system=environment.operating_system,
                windows=environment.windows,
            )
            compiled = compile_workflow_graph(
                immutable_draft, root_directory=source.bot_directory
            )
            plan = validate_execution_draft(
                compiled.draft,
                bot_directory=source.bot_directory,
                virtual_desktop=environment.virtual_desktop,
                local_paths=environment.local_paths,
                registry=self._registry,
                known_handler_keys=environment_handler_keys,
                workflow_node_ids=compiled.workflow_node_ids,
                editor_node_ids=compiled.editor_node_ids,
                event_paths=compiled.event_paths,
                source_directories=compiled.source_directories,
            )
            journal.configure_total_blocks(len(plan.actions))
            with self._lock:
                session.cancel_journal_ready = True
                if session.cancel_event.is_set():
                    session.journal.request_cancel()
            validation_state = RuntimeValidationState()
            context = ExecutionContext(
                run_id,
                plan,
                session.cancel_event,
                journal,
                environment.resources,
                step_limit=self._executed_step_limit,
            )
            dispatcher = self._dispatcher_factory(
                variables=context.variables,
                bot_directory=plan.bot_directory,
                cancel_event=session.cancel_event,
                virtual_desktop=environment.virtual_desktop,
                local_paths=environment.local_paths,
                validation_state=validation_state,
                mouse=environment.mouse,
                keyboard=environment.keyboard,
                clipboard=environment.clipboard,
                excel=environment.resources,
                operating_system=environment.operating_system,
                windows=environment.windows,
                http=environment.http,
            )
            cleanup_owner = dispatcher
            start_gate = threading.Event()
            worker = self._thread_factory(
                target=self._run,
                args=(
                    session,
                    context,
                    dispatcher,
                    start_gate,
                    environment.virtual_desktop,
                    environment.local_paths,
                    validation_state,
                ),
                name=f"autoclick-run-{run_id[:8]}",
                daemon=False,
            )
            session.worker = worker
            result: ExecutionStartResult = {
                "runId": run_id,
                "status": RunStatus.VALIDATING.value,
                "startedAt": self._timestamp(journal),
            }
            worker.start()
            worker_started = True
            start_gate.set()
            return result
        except BaseException as error:
            if cleanup_owner is not None and not worker_started:
                self._close_before_worker(cleanup_owner)
            if authorization is not None:
                self._release_authorization(session)
            with self._lock:
                if self._active is session:
                    self._active = None
                session.completed.set()
            if isinstance(error, SafeExecutionError):
                raise
            if isinstance(error, BotServiceError):
                raise SafeExecutionError(ExecutionErrorCode.EXECUTION_BOT_INVALID) from None
            raise SafeExecutionError(ExecutionErrorCode.EXECUTION_START_FAILED) from None

    def cancel(self, run_id: str) -> ExecutionCancelResult:
        with self._lock:
            self._prune_locked()
            session = self._active
            if session is not None and session.run_id == run_id:
                if session.completed.is_set():
                    if not session.terminal_published:
                        raise SafeExecutionError(
                            ExecutionErrorCode.EXECUTION_STATUS_FAILED
                        )
                    status = session.journal.read(0).state.status
                    if status is RunStatus.CANCELLED:
                        return {"runId": run_id, "status": status.value}
                    raise SafeExecutionError(ExecutionErrorCode.EXECUTION_NOT_ACTIVE)
                session.cancel_event.set()
                session.journal.request_cancel()
                return {"runId": run_id, "status": RunStatus.CANCEL_REQUESTED.value}
            retained = self._retained.get(run_id)
            if retained is None:
                raise SafeExecutionError(ExecutionErrorCode.EXECUTION_NOT_FOUND)
            status = retained.journal.read(0).state.status
            if status is RunStatus.CANCELLED:
                return {"runId": run_id, "status": status.value}
            raise SafeExecutionError(ExecutionErrorCode.EXECUTION_NOT_ACTIVE)

    def status(self, run_id: str, after_sequence: int) -> ExecutionStatusResult:
        with self._lock:
            self._prune_locked()
            if self._active is not None and self._active.run_id == run_id:
                session = self._active
                if session.completed.is_set() and not session.terminal_published:
                    raise SafeExecutionError(ExecutionErrorCode.EXECUTION_STATUS_FAILED)
                journal = session.journal
            else:
                retained = self._retained.get(run_id)
                if retained is None:
                    raise SafeExecutionError(ExecutionErrorCode.EXECUTION_NOT_FOUND)
                journal = retained.journal
        result = journal.read(after_sequence)
        state = result.state
        batch = result.event_batch
        return {
            "runId": state.run_id,
            "status": state.status.value,
            "currentBlockId": state.current_block_id,
            "currentEditorBlockId": state.current_editor_block_id,
            "currentBlockIndex": state.current_block_index,
            "totalBlocks": state.total_blocks,
            "cancelRequested": state.cancel_requested,
            "events": [event.as_dict() for event in batch.events],
            "nextSequence": batch.next_sequence,
            "eventsTruncated": batch.events_truncated,
        }

    def cancel_active_and_wait(self, timeout: float) -> bool:
        self.begin_shutdown()
        with self._lock:
            session = self._active
            if session is None:
                return True
            completed = session.completed
        if not completed.wait(timeout):
            return False
        with self._lock:
            if self._active is not session:
                return True
            return session.terminal_published

    def begin_shutdown(self) -> None:
        """Latch shutdown and request active cancellation without waiting."""
        with self._lock:
            self._shutting_down = True
            session = self._active
            if session is not None and not session.completed.is_set():
                session.cancel_event.set()
                if session.cancel_journal_ready:
                    session.journal.request_cancel()

    def has_active_run(self) -> bool:
        with self._lock:
            return self._active is not None

    def _run(
        self,
        session: _RunSession,
        context: ExecutionContext,
        dispatcher: ActionDispatcher,
        start_gate: threading.Event,
        virtual_desktop: VirtualDesktopProvider,
        local_paths: LocalPathInspector,
        validation_state: RuntimeValidationState,
    ) -> None:
        failure_block: EventBlock | None = None
        failure_code: ExecutionErrorCode | None = None
        start_gate.wait()
        try:
            if not session.cancel_event.is_set():
                session.journal.transition(RunStatus.RUNNING)
                indices = {id(action): index for index, action in enumerate(context.plan.actions)}
                def cancel_checkpoint() -> None:
                    if session.cancel_event.is_set():
                        raise ExecutionCancelled()

                def resolved_param(planned: PlannedNode, name: str) -> JsonValue:
                    value = resolve_value(planned.action.params[name], context.variables)
                    if not (value is None or isinstance(value, (str, int, float, bool, list, dict))):
                        raise SafeExecutionError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
                    return value

                def resolved_condition(planned: PlannedNode) -> Condition:
                    try:
                        return Condition.model_validate(resolved_param(planned, "condition"))
                    except ValidationError:
                        raise ResolvedActionValidationError([
                            ValidationIssue(
                                ValidationIssueCode.PARAMETER_INVALID,
                                planned.action.block_id,
                                "condition",
                            )
                        ]) from None

                def resolved_loop(planned: PlannedNode, bot_directory: PureWindowsPath):
                    return planned.action.resolve(
                        context.variables,
                        bot_directory=bot_directory,
                        virtual_desktop=virtual_desktop,
                        validation_state=validation_state,
                        local_paths=local_paths,
                    )

                def execute_loop_body(
                    planned: PlannedNode, iteration: int, maximum: int, workflow_prefix: tuple[str, ...], bot_directory: PureWindowsPath
                ) -> str:
                    if iteration >= maximum or iteration >= MAX_LOOP_ITERATIONS:
                        raise SafeExecutionError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
                    cancel_checkpoint()
                    outcome = execute(planned.slots["body"], workflow_prefix, bot_directory)
                    cancel_checkpoint()
                    return outcome

                def execute(
                    nodes: tuple[PlannedNode, ...],
                    workflow_prefix: tuple[str, ...] = (),
                    bot_directory: PureWindowsPath = context.plan.bot_directory,
                ) -> str:
                    nonlocal failure_block, failure_code
                    positions = {planned.action.source_node_id: index for index, planned in enumerate(nodes)}
                    program_counter = 0
                    while program_counter < len(nodes):
                        planned = nodes[program_counter]
                        cancel_checkpoint()
                        action = planned.action
                        block = EventBlock(
                            action.block_id,
                            action.title,
                            indices[id(action)],
                            action.event_path,
                            action.editor_block_id,
                        )
                        session.journal.start_block(block)
                        try:
                            context.record_step()
                            if action.action_id == "flow.group":
                                outcome = execute(planned.slots["body"], workflow_prefix, bot_directory)
                                if outcome == "stopped":
                                    session.journal.stop_block(block)
                                    return outcome
                            elif action.action_id == "flow.if":
                                condition = resolved_condition(planned)
                                slot = "then" if evaluate_condition(condition, context.variables) else "else"
                                outcome = execute(planned.slots[slot], workflow_prefix, bot_directory)
                                if outcome == "stopped":
                                    session.journal.stop_block(block)
                                    return outcome
                            elif action.action_id == "flow.forRange":
                                params = resolved_loop(planned, bot_directory).params
                                start, end, step = params["start"], params["end"], params["step"]
                                maximum, variable = params["maxIterations"], params["currentVariable"]
                                assert all(isinstance(value, int) and not isinstance(value, bool) for value in (start, end, step, maximum))
                                assert isinstance(variable, str)
                                if step == 0 or (end - start) * step < 0:
                                    raise SafeExecutionError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
                                if start == 0 and end == 0:
                                    pass
                                else:
                                    current, iteration = start, 0
                                    while current <= end if step > 0 else current >= end:
                                        cancel_checkpoint()
                                        context.variables[variable] = current
                                        outcome = execute_loop_body(planned, iteration, maximum, workflow_prefix, bot_directory)
                                        if outcome == "stopped":
                                            session.journal.stop_block(block)
                                            return outcome
                                        current += step
                                        iteration += 1
                            elif action.action_id == "flow.forEach":
                                params = resolved_loop(planned, bot_directory).params
                                items, item_variable = params["items"], params["itemVariable"]
                                index_variable = params.get("indexVariable")
                                maximum = params["maxIterations"]
                                assert isinstance(item_variable, str)
                                assert isinstance(maximum, int) and not isinstance(maximum, bool)
                                assert index_variable is None or isinstance(index_variable, str)
                                if not isinstance(items, list):
                                    raise SafeExecutionError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
                                for iteration, item in enumerate(items):
                                    cancel_checkpoint()
                                    context.variables[item_variable] = item
                                    if index_variable:
                                        context.variables[index_variable] = iteration
                                    outcome = execute_loop_body(planned, iteration, maximum, workflow_prefix, bot_directory)
                                    if outcome == "stopped":
                                        session.journal.stop_block(block)
                                        return outcome
                            elif action.action_id == "flow.while":
                                params = resolved_loop(planned, bot_directory).params
                                maximum = params["maxIterations"]
                                assert isinstance(maximum, int) and not isinstance(maximum, bool)
                                iteration = 0
                                condition = Condition.model_validate(params["condition"])
                                while True:
                                    cancel_checkpoint()
                                    if not evaluate_condition(condition, context.variables):
                                        break
                                    outcome = execute_loop_body(planned, iteration, maximum, workflow_prefix, bot_directory)
                                    if outcome == "stopped":
                                        session.journal.stop_block(block)
                                        return outcome
                                    iteration += 1
                                    condition = resolved_condition(planned)
                            elif action.action_id == "flow.tryCatch":
                                error_variable = action.params.get("errorVariable")
                                if isinstance(error_variable, str):
                                    context.variables[error_variable] = None
                                begin_recovery = getattr(dispatcher, "begin_recoverable_failures", None)
                                end_recovery = getattr(dispatcher, "end_recoverable_failures", None)
                                if begin_recovery is not None:
                                    begin_recovery()
                                try:
                                    outcome = execute(planned.slots["try"], workflow_prefix, bot_directory)
                                except _ActionFailure as error:
                                    if isinstance(error_variable, str):
                                        error_data: dict[str, JsonValue] = {
                                            "code": error.code.value,
                                            "message": str(error),
                                            "blockId": error.block.block_id,
                                            "blockPath": list(error.block.block_path),
                                        }
                                        if error.validation_issues:
                                            error_data["validationIssues"] = list(error.validation_issues)
                                        context.variables[error_variable] = error_data
                                    outcome = "caught"
                                finally:
                                    if end_recovery is not None:
                                        end_recovery()
                                if outcome == "caught":
                                    outcome = execute(planned.slots["catch"], workflow_prefix, bot_directory)
                                if outcome == "stopped":
                                    session.journal.stop_block(block)
                                    return outcome
                            elif action.action_id == "workflow.run":
                                outcome = execute(planned.slots["body"], workflow_prefix, bot_directory)
                                if outcome == "stopped":
                                    session.journal.stop_block(block)
                                    return outcome
                            elif action.action_id == "flow.goTo":
                                target = action.params.get("targetNodeId")
                                if not isinstance(target, str) or target not in positions:
                                    raise SafeExecutionError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
                                program_counter = positions[target]
                            elif action.slots:
                                raise SafeExecutionError(ExecutionErrorCode.ACTION_PARAMETER_INVALID)
                            else:
                                if isinstance(dispatcher, ActionDispatcher):
                                    dispatcher.dispatch(action, bot_directory=bot_directory)
                                else:
                                    dispatcher.dispatch(action)
                        except ExecutionStopped:
                            session.journal.finish_block(block)
                            return "stopped"
                        except ExecutionCancelled:
                            session.journal.cancel_block(block)
                            raise
                        except SafeExecutionError as error:
                            session.journal.fail_block(block, code=error.code)
                            raise _ActionFailure(error, block) from error
                        except _ActionFailure as error:
                            session.journal.fail_block(block, code=error.code)
                            raise
                        except StepBudgetExceeded:
                            failure_block = block
                            failure_code = ExecutionErrorCode.STEP_BUDGET_EXCEEDED
                            session.journal.fail_block(block, code=failure_code)
                            raise
                        except Exception:
                            session.journal.fail_block(
                                block, code=ExecutionErrorCode.EXECUTION_START_FAILED
                            )
                            raise
                        except BaseException:
                            failure_block = block
                            failure_code = ExecutionErrorCode.EXECUTION_START_FAILED
                            session.journal.fail_block(block, code=failure_code)
                            raise
                        self._drain_cleanup_warnings(session.journal, dispatcher, block)
                        session.journal.finish_block(block)
                        cancel_checkpoint()
                        if action.action_id != "flow.goTo":
                            program_counter += 1
                    return "completed"
                try:
                    execute(context.plan.roots)
                except _ActionFailure as error:
                    failure_block, failure_code = error.block, error.code
        except ExecutionCancelled:
            session.cancel_event.set()
        except StepBudgetExceeded:
            failure_code = ExecutionErrorCode.STEP_BUDGET_EXCEEDED
        except BaseException:
            failure_code = failure_code or ExecutionErrorCode.EXECUTION_START_FAILED
        finally:
            cleanup_warning_emitted = False
            cleanup_deadline = self._monotonic() + self._cleanup_timeout
            while not session.cleanup_verified:
                cleanup_outcome = ResourceCleanupOutcome(False)
                try:
                    outcome = dispatcher.close()
                    if isinstance(outcome, ResourceCleanupOutcome):
                        cleanup_outcome = outcome
                except BaseException:
                    pass
                session.cleanup_verified = cleanup_outcome.cleanup_verified
                if not session.cleanup_verified:
                    if not cleanup_warning_emitted:
                        try:
                            session.journal.cleanup_pending()
                        except BaseException:
                            pass
                        cleanup_warning_emitted = True
                elif cleanup_outcome.warning_count and not cleanup_warning_emitted:
                    try:
                        session.journal.cleanup_warning(
                            block=failure_block,
                            code=ExecutionErrorCode.EXCEL_CLOSE_FAILED,
                        )
                    except BaseException:
                        pass
                    cleanup_warning_emitted = True
                if not session.cleanup_verified:
                    remaining = cleanup_deadline - self._monotonic()
                    if remaining <= 0:
                        break
                    self._cleanup_retry_wait(min(self._cleanup_retry_interval, remaining))
            self._drain_cleanup_warnings(
                session.journal, dispatcher, failure_block
            )
            self._release_authorization(session)
            with self._lock:
                try:
                    if failure_code is not None:
                        terminal = session.journal.transition(
                            RunStatus.FAILED, code=failure_code
                        )
                    elif not session.cleanup_verified:
                        terminal = session.journal.transition(
                            RunStatus.FAILED,
                            code=ExecutionErrorCode.RESOURCE_CLEANUP_FAILED,
                        )
                    elif session.cancel_event.is_set():
                        terminal = session.journal.transition(RunStatus.CANCELLED)
                    else:
                        terminal = session.journal.transition(RunStatus.SUCCEEDED)
                    session.terminal_published = terminal is not None
                except BaseException:
                    session.terminal_published = False
                if session.terminal_published:
                    if self._active is session:
                        self._active = None
                    self._retained[session.run_id] = _RetainedRun(
                        session.journal, self._monotonic()
                    )
                    self._prune_locked()
                session.completed.set()

    @staticmethod
    def _drain_cleanup_warnings(
        journal: RunJournal,
        dispatcher: ActionDispatcher,
        block: EventBlock | None,
    ) -> None:
        while True:
            try:
                warning = dispatcher.consume_cleanup_warning()
            except BaseException:
                try:
                    journal.cleanup_warning(block=block)
                except BaseException:
                    pass
                return
            if not warning:
                return
            try:
                journal.cleanup_warning(block=block)
            except BaseException:
                return

    def _release_authorization(self, session: _RunSession) -> None:
        authorization = session.authorization
        session.authorization = None
        if authorization is not None:
            try:
                authorization.__exit__(None, None, None)
            except BaseException:
                pass

    def _close_before_worker(self, owner: object) -> None:
        close = getattr(owner, "close", None)
        if close is None:
            return
        deadline = self._monotonic() + self._cleanup_timeout
        while True:
            try:
                outcome = close()
                if isinstance(outcome, ResourceCleanupOutcome) and outcome.cleanup_verified:
                    return
            except BaseException:
                pass
            remaining = deadline - self._monotonic()
            if remaining <= 0:
                return
            self._cleanup_retry_wait(min(self._cleanup_retry_interval, remaining))

    def _prune_locked(self) -> None:
        cutoff = self._monotonic() - self._retention_ttl_seconds
        for run_id, retained in tuple(self._retained.items()):
            if retained.completed_at <= cutoff:
                del self._retained[run_id]
        while len(self._retained) > self._retention_count:
            self._retained.popitem(last=False)

    @staticmethod
    def _timestamp(journal: RunJournal) -> str:
        started_at: datetime = journal.read(0).state.started_at
        return started_at.isoformat(timespec="milliseconds").replace("+00:00", "Z")
