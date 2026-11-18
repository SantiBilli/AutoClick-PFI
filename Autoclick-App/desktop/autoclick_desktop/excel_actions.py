from __future__ import annotations

from contextlib import contextmanager
import ctypes
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
import importlib
import math
import os
import sys
from pathlib import PureWindowsPath
import secrets
import threading
from threading import Event
from typing import Callable, Iterator, Protocol

from pydantic import JsonValue

from autoclick_desktop.bot_schema import MAX_SAFE_INTEGER
from autoclick_desktop.execution_context import LocalPathInspector
from autoclick_desktop.execution_errors import (
    ExecutionCancelled,
    ExecutionErrorCode,
    HandlerError,
    PublishedSaveAsError,
    PublishedSaveAsCancellation,
)
from autoclick_desktop.execution_models import ResolvedAction, RuntimeOpenReservation
from autoclick_desktop.path_lease import (
    FileIdentity,
    FileGuard,
    PathLease,
    PathLeaseFactory,
    WindowsPathLeaseFactory,
)
from autoclick_desktop.platform_adapters import module_available


EXCEL_FILE_FORMATS = {
    ".xlsx": 51,
    ".xlsm": 52,
    ".xlsb": 50,
    ".xls": 56,
}


class FilesystemPublisher(Protocol):
    def temporary_path(self, destination: PureWindowsPath) -> PureWindowsPath: ...
    def publish_no_replace(
        self,
        temporary: PureWindowsPath,
        destination: PureWindowsPath,
        expected_identity: FileIdentity,
        lease: PathLease,
    ) -> PublishedDestinationIdentity: ...
    def verify_identity(
        self, destination: PureWindowsPath, identity: PublishedDestinationIdentity
    ) -> bool: ...
    def remove(
        self, path: PureWindowsPath, identity: FileIdentity, lease: PathLease
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class PublishedDestinationIdentity:
    device: int
    inode: int
    size: int
    modified_ns: int


class PublishedFileIdentityError(OSError):
    def __init__(self, published_identity: PublishedDestinationIdentity) -> None:
        self.published_identity = published_identity
        super().__init__("published file identity mismatch")


@dataclass(frozen=True, slots=True)
class ResourceCleanupOutcome:
    cleanup_verified: bool
    workbook_close_failures: int = 0
    quit_attempts: int = 0
    quit_succeeded: bool | None = None

    @property
    def warning_count(self) -> int:
        return self.workbook_close_failures + (self.quit_succeeded is False)

    def merge(self, other: "ResourceCleanupOutcome") -> "ResourceCleanupOutcome":
        quit_succeeded = self.quit_succeeded
        if other.quit_succeeded is not None:
            quit_succeeded = other.quit_succeeded
        return ResourceCleanupOutcome(
            other.cleanup_verified,
            self.workbook_close_failures + other.workbook_close_failures,
            self.quit_attempts + other.quit_attempts,
            quit_succeeded,
        )


class WindowsFilesystemPublisher:
    def __init__(self, kernel32: object | None = None) -> None:
        self._kernel32 = kernel32

    def temporary_path(self, destination: PureWindowsPath) -> PureWindowsPath:
        return destination.with_name(
            f".{destination.stem}.autoclick-{secrets.token_hex(16)}{destination.suffix}"
        )

    def publish_no_replace(
        self,
        temporary: PureWindowsPath,
        destination: PureWindowsPath,
        expected_identity: FileIdentity,
        lease: PathLease,
    ) -> PublishedDestinationIdentity:
        kernel32 = self._kernel32
        if kernel32 is None:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            self._kernel32 = kernel32
        move_file = kernel32.MoveFileW
        move_file.argtypes = [ctypes.c_wchar_p, ctypes.c_wchar_p]
        move_file.restype = ctypes.c_int
        guard = lease.guard_existing_file(temporary, expected_identity)
        try:
            if not guard.verify():
                raise OSError("temporary file identity changed")
        finally:
            guard.close()
        if move_file(str(temporary), str(destination)):
            try:
                guard = lease.guard_existing_file(destination, expected_identity)
            except OSError:
                raise PublishedFileIdentityError(
                    _published_identity_or_unknown(destination)
                ) from None
            try:
                if not guard.verify():
                    raise PublishedFileIdentityError(
                        _published_identity_or_unknown(destination)
                    )
                try:
                    return _published_identity(destination)
                except OSError:
                    raise PublishedFileIdentityError(
                        _published_identity_or_unknown(destination)
                    ) from None
            finally:
                guard.close()
        error = (
            int(kernel32.get_last_error())
            if hasattr(kernel32, "get_last_error")
            else ctypes.get_last_error()
        )
        if error in {80, 183}:
            raise FileExistsError
        raise OSError

    def verify_identity(
        self, destination: PureWindowsPath, identity: PublishedDestinationIdentity
    ) -> bool:
        try:
            return identity == _published_identity(destination)
        except OSError:
            return False

    def remove(
        self, path: PureWindowsPath, identity: FileIdentity, lease: PathLease
    ) -> None:
        if os.path.exists(path) and not lease.delete_file_if_identity(path, identity):
            raise OSError("temporary cleanup identity changed")


class ExcelResourceManager:
    """Owns one private Excel instance and all of its proxies on one worker thread."""

    def __init__(
        self,
        cancel_event: Event,
        local_paths: LocalPathInspector,
        *,
        pythoncom: object | None = None,
        dispatch_ex: Callable[[str], object] | None = None,
        publisher: FilesystemPublisher | None = None,
        path_leases: PathLeaseFactory | None = None,
        release_proxy: Callable[[object], None] | None = None,
        reopen_attempts: int = 3,
        reopen_retry_seconds: float = 0.05,
        quit_attempts: int = 3,
    ) -> None:
        if (
            not 1 <= reopen_attempts <= 10
            or not 0 <= reopen_retry_seconds <= 1
            or not 1 <= quit_attempts <= 5
        ):
            raise ValueError("invalid reopen retry policy")
        self._cancel_event = cancel_event
        self._local_paths = local_paths
        self._pythoncom = pythoncom
        self._dispatch_ex = dispatch_ex
        self._publisher = publisher or WindowsFilesystemPublisher()
        self._path_leases = path_leases or WindowsPathLeaseFactory()
        self._release_proxy = release_proxy or (lambda _proxy: None)
        self._reopen_attempts = reopen_attempts
        self._reopen_retry_seconds = reopen_retry_seconds
        self._quit_attempts = quit_attempts
        self._application: object | None = None
        self._workbooks: dict[RuntimeOpenReservation, object] = {}
        self._resource_paths: dict[RuntimeOpenReservation, PureWindowsPath] = {}
        self._resource_leases: dict[RuntimeOpenReservation, PathLease] = {}
        self._resource_file_identities: dict[RuntimeOpenReservation, FileIdentity] = {}
        self._owner_thread: int | None = None
        self._com_initialized = False
        self._cleanup_warning_count = 0
        self._cleanup_closed: set[RuntimeOpenReservation] = set()

    def is_available(self) -> bool:
        if self._pythoncom is not None and self._dispatch_ex is not None:
            return True
        if sys.platform != "win32" or not module_available("pythoncom") or not module_available("win32com.client"):
            return False
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Excel.Application\CLSID"):
                return True
        except OSError:
            return False

    def start(self) -> None:
        if self._application is not None:
            self._assert_owner()
            return
        thread_id = threading.get_ident()
        if self._owner_thread is not None and self._owner_thread != thread_id:
            raise HandlerError(ExecutionErrorCode.EXCEL_UNAVAILABLE)
        self._owner_thread = thread_id
        try:
            if self._pythoncom is None:
                self._pythoncom = importlib.import_module("pythoncom")
            if self._dispatch_ex is None:
                client = importlib.import_module("win32com.client")
                self._dispatch_ex = client.DispatchEx
            self._pythoncom.CoInitializeEx(self._pythoncom.COINIT_APARTMENTTHREADED)
            self._com_initialized = True
            self._check_cancel()
            self._application = self._dispatch_ex("Excel.Application")
            self._application.AutomationSecurity = 3
            self._application.EnableEvents = False
            if (
                self._application.AutomationSecurity != 3
                or self._application.EnableEvents is not False
            ):
                raise RuntimeError("Excel security gates were not applied")
            self._check_cancel()
            self._application.Visible = True
            self._check_cancel()
        except ExecutionCancelled:
            self._abort_start()
            raise
        except Exception:
            self._abort_start()
            raise HandlerError(ExecutionErrorCode.EXCEL_UNAVAILABLE) from None

    def register(
        self,
        reservation: RuntimeOpenReservation,
        workbook: object,
        lease: PathLease | None = None,
        file_identity: FileIdentity | None = None,
    ) -> None:
        self._assert_owner()
        if reservation in self._workbooks:
            raise HandlerError(ExecutionErrorCode.RESOURCE_ALREADY_DEFINED)
        self._workbooks[reservation] = workbook
        self._resource_paths[reservation] = reservation.path
        if lease is not None:
            self._resource_leases[reservation] = lease
        if file_identity is not None:
            self._resource_file_identities[reservation] = file_identity
        self._cleanup_closed.discard(reservation)

    def get(self, reservation: RuntimeOpenReservation) -> object:
        self._assert_owner()
        try:
            return self._workbooks[reservation]
        except KeyError:
            raise HandlerError(ExecutionErrorCode.RESOURCE_NOT_FOUND) from None

    def remove(self, reservation: RuntimeOpenReservation) -> object:
        self._assert_owner()
        try:
            workbook = self._workbooks.pop(reservation)
            self._resource_paths.pop(reservation, None)
            lease = self._resource_leases.pop(reservation, None)
            self._resource_file_identities.pop(reservation, None)
            if lease is not None:
                lease.close()
            self._cleanup_closed.discard(reservation)
            return workbook
        except KeyError:
            raise HandlerError(ExecutionErrorCode.RESOURCE_NOT_FOUND) from None

    @contextmanager
    def _alerts_disabled(self, *, cancellation_aware: bool = True) -> Iterator[None]:
        application = self._application
        assert application is not None
        previous = application.DisplayAlerts
        if cancellation_aware:
            self._check_cancel()
        body_failed = False
        try:
            application.DisplayAlerts = False
            if cancellation_aware:
                self._check_cancel()
            yield
        except BaseException:
            body_failed = True
            raise
        finally:
            try:
                application.DisplayAlerts = previous
                if cancellation_aware and not body_failed:
                    self._check_cancel()
            except ExecutionCancelled:
                raise
            except Exception:
                pass

    def open(self, action: ResolvedAction) -> None:
        self.start()
        self._check_cancel()
        path = action.params["path"]
        assert isinstance(path, PureWindowsPath)
        workbook: object | None = None
        lease: PathLease | None = None
        try:
            lease = self._path_leases.acquire_source(path)
            if not lease.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_OPEN_FAILED)
            with self._alerts_disabled():
                workbook, identity = self._open_workbook(path, lease)
            self._check_cancel()
            self.register(action.workbook_reservation, workbook, lease, identity)
            lease = None
            if not action.confirm_open_reservation():
                self.remove(action.workbook_reservation)
                raise HandlerError(ExecutionErrorCode.RESOURCE_ALREADY_DEFINED)
        except ExecutionCancelled:
            if workbook is not None:
                self._close_without_save(workbook)
                self._release(workbook)
            raise
        except HandlerError:
            if workbook is not None and action.workbook_reservation not in self._workbooks:
                self._close_without_save(workbook)
                self._release(workbook)
            raise
        except Exception:
            if workbook is not None:
                self._close_without_save(workbook)
                self._release(workbook)
            raise HandlerError(ExecutionErrorCode.EXCEL_OPEN_FAILED) from None
        finally:
            if lease is not None:
                lease.close()

    def create(self, action: ResolvedAction) -> None:
        self.start()
        workbook: object | None = None
        try:
            workbook = self._application.Workbooks.Add()
            self._check_cancel()
            self.register(action.workbook_reservation, workbook)
            if not action.confirm_open_reservation():
                self.remove(action.workbook_reservation)
                raise HandlerError(ExecutionErrorCode.RESOURCE_ALREADY_DEFINED)
        except (ExecutionCancelled, HandlerError):
            if workbook is not None and action.workbook_reservation not in self._workbooks:
                self._close_without_save(workbook)
                self._release(workbook)
            raise
        except Exception:
            if workbook is not None:
                self._close_without_save(workbook)
                self._release(workbook)
            raise HandlerError(ExecutionErrorCode.EXCEL_OPEN_FAILED) from None

    def operate(self, action: ResolvedAction) -> JsonValue | None:
        workbook = self.get(action.workbook_reservation)
        operation = action.action_id
        worksheet: object | None = None
        target: object | None = None
        try:
            if operation == "excel.addWorksheet":
                worksheet = workbook.Worksheets.Add()
                worksheet.Name = str(action.params["name"])
                return None
            worksheet = self._worksheet(workbook, str(action.params["sheet"]))
            if operation == "excel.deleteWorksheet":
                with self._alerts_disabled():
                    worksheet.Delete()
            elif operation == "excel.renameWorksheet": worksheet.Name = str(action.params["newName"])
            elif operation == "excel.activateWorksheet": worksheet.Activate()
            elif operation in {"excel.selectCell", "excel.clearCell"}:
                target = worksheet.Range(str(action.params["cell"]))
                target.Select() if operation == "excel.selectCell" else target.ClearContents()
            elif operation in {"excel.selectRange", "excel.readRange", "excel.writeRange"}:
                target = worksheet.Range(str(action.params["range"]))
                if operation == "excel.selectRange": target.Select()
                elif operation == "excel.readRange": return _json_excel_range(target.Value)
                else: target.Value = action.params["value"]
            elif operation == "excel.deleteEmptyRows":
                used = worksheet.UsedRange
                for row in range(int(used.Rows.Count), 0, -1):
                    self._check_cancel()
                    candidate = used.Rows(row)
                    if self._application.WorksheetFunction.CountA(candidate) == 0:
                        candidate.EntireRow.Delete()
                    self._check_cancel()
            elif operation == "excel.findValues":
                used = worksheet.UsedRange
                values = _json_excel_range(used.Value)
                first_row, first_column = int(used.Row), int(used.Column)
                result = []
                for row_index, row in enumerate(values):
                    self._check_cancel()
                    for column_index, value in enumerate(row):
                        self._check_cancel()
                        if value == action.params["value"]:
                            result.append(_a1(first_row + row_index, first_column + column_index))
                return result
            elif operation == "excel.lastRow": return int(worksheet.UsedRange.Row + worksheet.UsedRange.Rows.Count - 1)
            elif operation == "excel.lastColumn": return int(worksheet.UsedRange.Column + worksheet.UsedRange.Columns.Count - 1)
            self._check_cancel()
            return None
        except (ExecutionCancelled, HandlerError):
            raise
        except Exception:
            raise HandlerError(ExecutionErrorCode.EXCEL_WRITE_FAILED) from None
        finally:
            if target is not None: self._release(target)
            if worksheet is not None: self._release(worksheet)

    def read_cell(self, action: ResolvedAction) -> JsonValue:
        workbook = self.get(action.workbook_reservation)
        worksheet = self._worksheet(workbook, str(action.params["sheet"]))
        cell: object | None = None
        try:
            cell = worksheet.Range(str(action.params["cell"]))
            self._check_cancel()
            value = cell.Value
            self._check_cancel()
        except ExecutionCancelled:
            raise
        except Exception:
            raise HandlerError(ExecutionErrorCode.EXCEL_READ_FAILED) from None
        finally:
            if cell is not None:
                self._release(cell)
            self._release(worksheet)
        self._check_cancel()
        return _json_excel_value(value)

    def write_cell(self, action: ResolvedAction) -> None:
        value = action.params["value"]
        if (
            (not isinstance(value, (str, int, float, bool)) and value is not None)
            or (isinstance(value, float) and not math.isfinite(value))
        ):
            raise HandlerError(ExecutionErrorCode.EXCEL_VALUE_UNSUPPORTED)
        workbook = self.get(action.workbook_reservation)
        worksheet = self._worksheet(workbook, str(action.params["sheet"]))
        cell: object | None = None
        try:
            cell = worksheet.Range(str(action.params["cell"]))
            self._check_cancel()
            if isinstance(value, str):
                cell.NumberFormat = "@"
                self._check_cancel()
            cell.Value = value
            self._check_cancel()
        except ExecutionCancelled:
            raise
        except Exception:
            raise HandlerError(ExecutionErrorCode.EXCEL_WRITE_FAILED) from None
        finally:
            if cell is not None:
                self._release(cell)
            self._release(worksheet)
        self._check_cancel()

    def save(self, action: ResolvedAction) -> None:
        workbook = self.get(action.workbook_reservation)
        path = action.params.get("path")
        published_identity: PublishedDestinationIdentity | None = None
        try:
            with self._alerts_disabled():
                self._verify_security_gates()
                if path in (None, ""):
                    self._verify_resource_path(action.workbook_reservation)
                    workbook.Save()
                    self._check_cancel()
                    self._refresh_resource_file_identity(action.workbook_reservation)
                else:
                    assert isinstance(path, PureWindowsPath)
                    published_identity = self._save_as_no_replace(
                        action.workbook_reservation, workbook, path
                    )
        except HandlerError:
            raise
        except Exception:
            raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED) from None
        try:
            self._check_cancel()
        except ExecutionCancelled:
            if published_identity is not None:
                raise PublishedSaveAsCancellation(published_identity) from None
            raise

    def close(self, action: ResolvedAction) -> None:
        workbook = self.get(action.workbook_reservation)
        save_changes = bool(action.params.get("saveChanges", False))
        try:
            with self._alerts_disabled():
                if save_changes:
                    self._verify_resource_path(action.workbook_reservation)
                workbook.Close(SaveChanges=save_changes)
                self._check_cancel()
                if save_changes:
                    self._refresh_resource_file_identity(action.workbook_reservation)
        except ExecutionCancelled:
            raise
        except Exception:
            raise HandlerError(ExecutionErrorCode.EXCEL_CLOSE_FAILED) from None
        self._check_cancel()
        self.remove(action.workbook_reservation)
        self._release(workbook)
        if not action.release_closed_workbook():
            raise HandlerError(ExecutionErrorCode.RESOURCE_CLOSED)

    def _worksheet(self, workbook: object, name: str) -> object:
        try:
            worksheet = workbook.Worksheets(name)
        except Exception:
            raise HandlerError(ExecutionErrorCode.EXCEL_WORKSHEET_NOT_FOUND) from None
        try:
            self._check_cancel()
        except ExecutionCancelled:
            self._release(worksheet)
            raise
        return worksheet

    def close_all(self) -> ResourceCleanupOutcome:
        if self._owner_thread is None:
            return ResourceCleanupOutcome(True)
        self._assert_owner()
        workbooks = tuple(self._workbooks.items())
        failures = 0
        for reservation, workbook in workbooks:
            if reservation in self._cleanup_closed:
                continue
            if self._close_without_save(workbook):
                self._cleanup_closed.add(reservation)
            else:
                failures += 1
        workbook = None
        return ResourceCleanupOutcome(failures == 0, failures)

    def shutdown(self) -> ResourceCleanupOutcome:
        if self._owner_thread is None:
            return ResourceCleanupOutcome(True)
        self._assert_owner()
        application: object | None = self._application
        workbook_outcome = ResourceCleanupOutcome(True)
        quit_attempts = 0
        quit_succeeded: bool | None = None
        workbook_outcome = self.close_all()
        if application is not None:
            quit_succeeded = False
            for _attempt in range(self._quit_attempts):
                quit_attempts += 1
                try:
                    with self._alerts_disabled(cancellation_aware=False):
                        application.Quit()
                    quit_succeeded = True
                    break
                except Exception:
                    continue
        cleanup_verified = (
            quit_succeeded is True
            if application is not None
            else workbook_outcome.cleanup_verified and not self._workbooks
        )
        outcome = ResourceCleanupOutcome(
            cleanup_verified,
            workbook_outcome.workbook_close_failures,
            quit_attempts,
            quit_succeeded,
        )
        if cleanup_verified:
            # Release this local reference too before tearing down the COM apartment.
            application = None
            self._finalize_cleanup()
        return outcome

    def _finalize_cleanup(self) -> None:
        for workbook in tuple(self._workbooks.values()):
            self._release(workbook)
        workbook = None
        self._workbooks.clear()
        self._resource_paths.clear()
        for lease in tuple(self._resource_leases.values()):
            lease.close()
        self._resource_leases.clear()
        self._resource_file_identities.clear()
        self._cleanup_closed.clear()
        application = self._application
        self._application = None
        if application is not None:
            self._release(application)
        application = None
        self._uninitialize()
        self._owner_thread = None

    def _close_without_save(self, workbook: object) -> bool:
        try:
            save_changes = bool(getattr(workbook, "Saved", False))
            if self._application is not None:
                with self._alerts_disabled(cancellation_aware=False):
                    workbook.Close(SaveChanges=save_changes)
            else:
                workbook.Close(SaveChanges=save_changes)
            return True
        except Exception:
            return False

    def _check_cancel(self) -> None:
        if self._cancel_event.is_set():
            raise ExecutionCancelled()

    def _open_workbook(
        self,
        path: PureWindowsPath,
        lease: PathLease,
        expected_identity: FileIdentity | None = None,
    ) -> tuple[object, FileIdentity]:
        application = self._application
        assert application is not None
        workbooks = application.Workbooks
        guard: FileGuard | None = None
        self._check_cancel()
        workbook: object | None = None
        succeeded = False
        try:
            guard = lease.guard_existing_file(path, expected_identity)
            if not guard.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_OPEN_FAILED)
            self._verify_security_gates()
            workbook = workbooks.Open(
                str(path),
                UpdateLinks=0,
                ReadOnly=False,
                IgnoreReadOnlyRecommended=True,
                Notify=False,
                AddToMru=False,
            )
            try:
                pvw_list = getattr(application, "ProtectedViewWindows", None)
                if pvw_list is not None and pvw_list.Count > 0:
                    for pvw in list(pvw_list):
                        try:
                            pvw.Edit()
                        except Exception:
                            pass
            except Exception:
                pass
            if getattr(workbook, "ReadOnly", False):
                try:
                    workbook.ChangeFileAccess(2)
                except Exception:
                    pass
            try:
                if getattr(workbook, "AutoSaveOn", False):
                    workbook.AutoSaveOn = False
            except Exception:
                pass
            self._check_cancel()
            if not guard.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_OPEN_FAILED)
            succeeded = True
            return workbook, guard.identity
        except BaseException:
            if workbook is not None and not succeeded:
                self._close_without_save(workbook)
                self._release(workbook)
            raise
        finally:
            if guard is not None:
                guard.close()
            self._release(workbooks)
            workbooks = None

    def _save_as_no_replace(
        self,
        reservation: RuntimeOpenReservation,
        workbook: object,
        destination: PureWindowsPath,
    ) -> PublishedDestinationIdentity:
        original_path = self._resource_paths[reservation]
        destination_lease: PathLease | None = None
        temporary: PureWindowsPath | None = None
        temporary_guard: FileGuard | None = None
        temporary_identity: FileIdentity | None = None
        closed = False
        failure: Exception | None = None
        published_identity: object | None = None
        try:
            destination_lease = self._path_leases.acquire_destination(destination)
            if not destination_lease.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
            self._verify_security_gates()
            for _attempt in range(16):
                temporary = self._publisher.temporary_path(destination)
                if not destination_lease.path_exists(temporary):
                    break
            else:
                raise OSError("could not choose temporary workbook path")
            if not destination_lease.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
            if destination_lease.path_exists(temporary):
                raise OSError("temporary workbook path was claimed")
            workbook.SaveAs(
                str(temporary), FileFormat=EXCEL_FILE_FORMATS[destination.suffix.casefold()]
            )
            temporary_guard = destination_lease.guard_existing_file(temporary)
            temporary_identity = temporary_guard.identity
            if not destination_lease.verify() or not temporary_guard.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
            self._check_cancel()
            workbook.Close(SaveChanges=False)
            closed = True
            self._check_cancel()
            self._workbooks.pop(reservation, None)
            self._release(workbook)
            workbook = None
            if not destination_lease.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
            if not temporary_guard.verify():
                raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
            temporary_guard.close()
            temporary_guard = None
            identity = self._publisher.publish_no_replace(
                temporary, destination, temporary_identity, destination_lease
            )
            published_identity = identity
            reopened = self._reopen_published(
                destination, identity, destination_lease, temporary_identity
            )
            old_lease = self._resource_leases.pop(reservation, None)
            if old_lease is not None:
                old_lease.close()
            self._workbooks[reservation] = reopened
            self._resource_paths[reservation] = destination
            self._resource_leases[reservation] = destination_lease
            self._resource_file_identities[reservation] = temporary_identity
            destination_lease = None
        except FileExistsError:
            self._recover_original(reservation, workbook, original_path, closed)
            failure = HandlerError(ExecutionErrorCode.EXCEL_DESTINATION_EXISTS)
        except PublishedFileIdentityError as error:
            self._recover_original(reservation, workbook, original_path, closed)
            published_identity = error.published_identity
            failure = PublishedSaveAsError(error.published_identity)
        except PublishedSaveAsCancellation as error:
            self._recover_original(reservation, workbook, original_path, closed)
            failure = error
        except ExecutionCancelled as error:
            self._recover_original(reservation, workbook, original_path, closed)
            failure = error
        except PublishedSaveAsError as error:
            self._recover_original(reservation, workbook, original_path, closed)
            failure = error
        except HandlerError as error:
            self._recover_original(reservation, workbook, original_path, closed)
            failure = error
        except Exception:
            self._recover_original(reservation, workbook, original_path, closed)
            failure = HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
        finally:
            if temporary_guard is not None:
                temporary_guard.close()
            try:
                if (
                    temporary is not None
                    and temporary_identity is not None
                    and destination_lease is not None
                ):
                    self._publisher.remove(
                        temporary, temporary_identity, destination_lease
                    )
            except Exception:
                self._cleanup_warning_count += 1
                if failure is None:
                    failure = (
                        PublishedSaveAsError(published_identity)
                        if published_identity is not None
                        else HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
                    )
            if destination_lease is not None:
                destination_lease.close()
        if failure is not None:
            raise failure
        assert published_identity is not None
        return published_identity

    def _reopen_published(
        self,
        destination: PureWindowsPath,
        identity: PublishedDestinationIdentity,
        lease: PathLease,
        file_identity: FileIdentity,
    ) -> object:
        for attempt in range(self._reopen_attempts):
            self._check_published_identity(destination, identity)
            try:
                self._check_cancel()
                reopened, reopened_identity = self._open_workbook(
                    destination, lease, file_identity
                )
            except ExecutionCancelled:
                raise PublishedSaveAsCancellation(identity) from None
            except Exception:
                self._check_published_identity(destination, identity)
                if attempt + 1 == self._reopen_attempts:
                    raise PublishedSaveAsError(identity) from None
                if self._cancel_event.wait(self._reopen_retry_seconds):
                    raise PublishedSaveAsCancellation(identity) from None
                continue
            if not self._publisher.verify_identity(destination, identity):
                self._close_without_save(reopened)
                self._release(reopened)
                raise PublishedSaveAsError(identity)
            if reopened_identity != file_identity:
                self._close_without_save(reopened)
                self._release(reopened)
                raise PublishedSaveAsError(identity)
            return reopened
        raise PublishedSaveAsError(identity)

    def _check_published_identity(
        self,
        destination: PureWindowsPath,
        identity: PublishedDestinationIdentity,
    ) -> None:
        if not self._publisher.verify_identity(destination, identity):
            raise PublishedSaveAsError(identity)

    def consume_cleanup_warning(self) -> bool:
        if self._cleanup_warning_count == 0:
            return False
        self._cleanup_warning_count -= 1
        return True

    def _abort_start(self) -> None:
        self.shutdown()

    def _verify_security_gates(self) -> None:
        application = self._application
        if (
            application is None
            or application.AutomationSecurity != 3
            or application.EnableEvents is not False
        ):
            raise HandlerError(ExecutionErrorCode.EXCEL_UNAVAILABLE)

    def _verify_resource_path(self, reservation: RuntimeOpenReservation) -> None:
        lease = self._resource_leases.get(reservation)
        identity = self._resource_file_identities.get(reservation)
        path = self._resource_paths.get(reservation)
        if (
            lease is None
            or identity is None
            or path is None
            or not lease.verify()
            or not lease.verify_file_identity(path, identity)
        ):
            raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)

    def _refresh_resource_file_identity(self, reservation: RuntimeOpenReservation) -> None:
        lease = self._resource_leases.get(reservation)
        path = self._resource_paths.get(reservation)
        if lease is None or path is None or not lease.verify():
            raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED)
        try:
            self._resource_file_identities[reservation] = lease.capture_file_identity(path)
        except OSError:
            raise HandlerError(ExecutionErrorCode.EXCEL_SAVE_FAILED) from None

    def _recover_original(
        self,
        reservation: RuntimeOpenReservation,
        workbook: object | None,
        original_path: PureWindowsPath,
        closed: bool,
    ) -> None:
        if not closed and workbook is not None:
            self._close_without_save(workbook)
            self._workbooks.pop(reservation, None)
            self._release(workbook)
        try:
            lease = self._resource_leases.get(reservation)
            identity = self._resource_file_identities.get(reservation)
            if lease is None or identity is None or not lease.verify():
                raise OSError
            recovered, recovered_identity = self._open_workbook(
                original_path, lease, identity
            )
            if recovered_identity != identity:
                self._close_without_save(recovered)
                self._release(recovered)
                raise OSError
        except Exception:
            self._workbooks.pop(reservation, None)
            self._resource_paths.pop(reservation, None)
            return
        self._workbooks[reservation] = recovered
        self._resource_paths[reservation] = original_path

    def _release(self, proxy: object) -> None:
        try:
            self._release_proxy(proxy)
        except Exception:
            pass

    def _assert_owner(self) -> None:
        if self._owner_thread != threading.get_ident():
            raise HandlerError(ExecutionErrorCode.EXCEL_UNAVAILABLE)

    def _uninitialize(self) -> None:
        if self._com_initialized and self._pythoncom is not None:
            try:
                self._pythoncom.CoUninitialize()
            except Exception:
                pass
            finally:
                self._com_initialized = False


def _published_identity(path: PureWindowsPath) -> PublishedDestinationIdentity:
    stat = os.stat(path)
    return PublishedDestinationIdentity(
        stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns
    )


def _published_identity_or_unknown(path: PureWindowsPath) -> PublishedDestinationIdentity:
    try:
        return _published_identity(path)
    except OSError:
        return PublishedDestinationIdentity(0, 0, 0, 0)


def _json_excel_value(value: object) -> JsonValue:
    if isinstance(value, float):
        if not math.isfinite(value) or value.is_integer() and abs(value) > MAX_SAFE_INTEGER:
            raise HandlerError(ExecutionErrorCode.EXCEL_VALUE_UNSUPPORTED)
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        if abs(value) > MAX_SAFE_INTEGER:
            raise HandlerError(ExecutionErrorCode.EXCEL_VALUE_UNSUPPORTED)
        return value
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, Decimal):
        try:
            converted = float(value)
        except Exception:
            raise HandlerError(ExecutionErrorCode.EXCEL_VALUE_UNSUPPORTED) from None
        if not math.isfinite(converted) or converted.is_integer() and abs(converted) > MAX_SAFE_INTEGER:
            raise HandlerError(ExecutionErrorCode.EXCEL_VALUE_UNSUPPORTED)
        return converted
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    raise HandlerError(ExecutionErrorCode.EXCEL_VALUE_UNSUPPORTED)


def _json_excel_range(value: object) -> list[list[JsonValue]]:
    rows = value if isinstance(value, (tuple, list)) else ((value,),)
    if rows and not isinstance(rows[0], (tuple, list)):
        rows = (rows,)
    return [[_json_excel_value(cell) for cell in row] for row in rows]


def _a1(row: int, column: int) -> str:
    letters = ""
    while column:
        column, remainder = divmod(column - 1, 26)
        letters = chr(65 + remainder) + letters
    return f"{letters}{row}"
