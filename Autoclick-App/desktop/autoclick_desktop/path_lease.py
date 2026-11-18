from __future__ import annotations

import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import ntpath
from pathlib import PureWindowsPath
from typing import Protocol


FILE_READ_ATTRIBUTES = 0x0080
GENERIC_READ = 0x80000000
DELETE = 0x00010000
FILE_SHARE_READ = 0x00000001
FILE_SHARE_WRITE = 0x00000002
OPEN_EXISTING = 3
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
DRIVE_REMOTE = 4
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _ByHandleFileInformation(ctypes.Structure):
    _fields_ = [
        ("dwFileAttributes", wintypes.DWORD),
        ("ftCreationTime", wintypes.FILETIME),
        ("ftLastAccessTime", wintypes.FILETIME),
        ("ftLastWriteTime", wintypes.FILETIME),
        ("dwVolumeSerialNumber", wintypes.DWORD),
        ("nFileSizeHigh", wintypes.DWORD),
        ("nFileSizeLow", wintypes.DWORD),
        ("nNumberOfLinks", wintypes.DWORD),
        ("nFileIndexHigh", wintypes.DWORD),
        ("nFileIndexLow", wintypes.DWORD),
    ]


@dataclass(frozen=True, slots=True)
class FileIdentity:
    volume_serial: int
    file_index: int


class FileGuard(Protocol):
    @property
    def identity(self) -> FileIdentity: ...
    def verify(self) -> bool: ...
    def close(self) -> None: ...


class PathLease(Protocol):
    def verify(self) -> bool: ...
    def path_exists(self, path: PureWindowsPath) -> bool: ...
    def capture_file_identity(self, path: PureWindowsPath) -> FileIdentity: ...
    def verify_file_identity(self, path: PureWindowsPath, identity: FileIdentity) -> bool: ...
    def guard_existing_file(
        self, path: PureWindowsPath, expected: FileIdentity | None = None
    ) -> FileGuard: ...
    def delete_file_if_identity(self, path: PureWindowsPath, identity: FileIdentity) -> bool: ...
    def close(self) -> None: ...


class PathLeaseFactory(Protocol):
    def acquire_source(self, path: PureWindowsPath) -> PathLease: ...
    def acquire_destination(self, path: PureWindowsPath) -> PathLease: ...


class WindowsPathLease:
    """No-delete directory anchors plus short-lived file identity snapshots."""

    def __init__(
        self,
        api: "_WindowsHandleApi",
        handles: list[int],
        anchors: list[tuple[int, FileIdentity, str]],
    ) -> None:
        self._api = api
        self._handles = handles
        self._anchors = anchors

    def verify(self) -> bool:
        if len(self._handles) != len(self._anchors):
            return False
        try:
            return all(
                self._api.describe(handle) == expected
                for handle, expected in zip(self._handles, self._anchors, strict=True)
            )
        except OSError:
            return False

    def capture_file_identity(self, path: PureWindowsPath) -> FileIdentity:
        guard = self.guard_existing_file(path)
        try:
            return guard.identity
        finally:
            guard.close()

    def path_exists(self, path: PureWindowsPath) -> bool:
        if not self.verify():
            raise OSError("path anchor changed")
        return self._api.path_exists(path)

    def verify_file_identity(self, path: PureWindowsPath, identity: FileIdentity) -> bool:
        try:
            return self.capture_file_identity(path) == identity
        except OSError:
            return False

    def guard_existing_file(
        self, path: PureWindowsPath, expected: FileIdentity | None = None
    ) -> "WindowsFileGuard":
        if not self.verify():
            raise OSError("path anchor changed")
        handle = self._api.open_path(path, directory=False)
        try:
            guard = WindowsFileGuard(self._api, handle, path)
            if expected is not None and guard.identity != expected:
                raise OSError("file identity changed")
            return guard
        except BaseException:
            self._api.close(handle)
            raise

    def delete_file_if_identity(self, path: PureWindowsPath, identity: FileIdentity) -> bool:
        if not self.verify():
            return False
        try:
            handle = self._api.open_path(path, directory=False, delete=True)
        except OSError:
            return False
        try:
            guard = WindowsFileGuard(self._api, handle, path)
            if guard.identity != identity:
                return False
            return self._api.delete_by_handle(handle)
        except OSError:
            return False
        finally:
            self._api.close(handle)

    def close(self) -> None:
        handles, self._handles = self._handles, []
        self._anchors = []
        for handle in reversed(handles):
            self._api.close(handle)


class WindowsFileGuard:
    def __init__(
        self, api: "_WindowsHandleApi", handle: int, path: PureWindowsPath
    ) -> None:
        self._api = api
        self._handle: int | None = handle
        self._path = path
        attributes, identity, final_path = api.describe(handle)
        if attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT):
            raise OSError("unsafe file type")
        if final_path != _normalized(path):
            raise OSError("file path changed")
        self._description = (attributes, identity, final_path)

    @property
    def identity(self) -> FileIdentity:
        return self._description[1]

    def verify(self) -> bool:
        handle = self._handle
        if handle is None:
            return False
        try:
            if self._api.describe(handle) != self._description:
                return False
            current = self._api.open_path(self._path, directory=False)
            try:
                return self._api.describe(current)[1] == self.identity
            finally:
                self._api.close(current)
        except OSError:
            return False

    def close(self) -> None:
        handle, self._handle = self._handle, None
        if handle is not None:
            self._api.close(handle)


class WindowsPathLeaseFactory:
    def __init__(self, kernel32: object | None = None) -> None:
        self._api = _WindowsHandleApi(kernel32)

    def acquire_source(self, path: PureWindowsPath) -> WindowsPathLease:
        lease = self._acquire_parent_chain(path)
        try:
            lease.capture_file_identity(path)
            return lease
        except BaseException:
            lease.close()
            raise

    def acquire_destination(self, path: PureWindowsPath) -> WindowsPathLease:
        lease = self._acquire_parent_chain(path)
        try:
            if self._api.path_exists(path):
                raise FileExistsError
            return lease
        except BaseException:
            lease.close()
            raise

    def _acquire_parent_chain(self, path: PureWindowsPath) -> WindowsPathLease:
        if (
            not path.is_absolute()
            or not path.drive
            or path.drive.startswith("\\")
            or self._api.drive_type(f"{path.drive}\\") in {0, 1, DRIVE_REMOTE}
        ):
            raise OSError("path is not on a local drive")
        handles: list[int] = []
        anchors: list[tuple[int, FileIdentity, str]] = []
        lease = WindowsPathLease(self._api, handles, anchors)
        current = PureWindowsPath(path.anchor)
        try:
            for component in ((), *path.parent.parts[1:]):
                if component:
                    current /= component
                handle = self._api.open_path(current, directory=True)
                handles.append(handle)
                attributes, identity, final_path = self._api.describe(handle)
                if not attributes & FILE_ATTRIBUTE_DIRECTORY:
                    raise OSError("path component is not a directory")
                if attributes & FILE_ATTRIBUTE_REPARSE_POINT:
                    raise OSError("reparse points are unsupported")
                if final_path != _normalized(current):
                    raise OSError("path component changed")
                anchors.append((attributes, identity, final_path))
            if not lease.verify():
                raise OSError("path anchor changed")
            return lease
        except BaseException:
            lease.close()
            raise


class _WindowsHandleApi:
    def __init__(self, kernel32: object | None) -> None:
        self._kernel32 = kernel32

    @property
    def kernel32(self) -> object:
        if self._kernel32 is None:
            self._kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        return self._kernel32

    def drive_type(self, root: str) -> int:
        function = self.kernel32.GetDriveTypeW
        function.argtypes = [wintypes.LPCWSTR]
        function.restype = wintypes.UINT
        return int(function(root))

    def path_exists(self, path: PureWindowsPath) -> bool:
        function = self.kernel32.GetFileAttributesW
        function.argtypes = [wintypes.LPCWSTR]
        function.restype = wintypes.DWORD
        attributes = int(function(str(path)))
        if attributes != 0xFFFFFFFF:
            return True
        error = ctypes.get_last_error()
        if error in {2, 3}:
            return False
        raise ctypes.WinError(error)

    def open_path(
        self,
        path: PureWindowsPath,
        *,
        directory: bool,
        delete: bool = False,
    ) -> int:
        function = self.kernel32.CreateFileW
        function.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        function.restype = wintypes.HANDLE
        flags = FILE_FLAG_OPEN_REPARSE_POINT
        if directory:
            flags |= FILE_FLAG_BACKUP_SEMANTICS
        handle = function(
            str(path),
            FILE_READ_ATTRIBUTES
            | (GENERIC_READ if not directory else 0)
            | (DELETE if delete else 0),
            FILE_SHARE_READ | FILE_SHARE_WRITE,
            None,
            OPEN_EXISTING,
            flags,
            None,
        )
        value = int(handle) if handle is not None else 0
        if value == INVALID_HANDLE_VALUE:
            raise ctypes.WinError(ctypes.get_last_error())
        return value

    def delete_by_handle(self, handle: int) -> bool:
        class FileDispositionInformation(ctypes.Structure):
            _fields_ = [("DeleteFile", wintypes.BOOL)]

        function = self.kernel32.SetFileInformationByHandle
        function.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
        function.restype = wintypes.BOOL
        information = FileDispositionInformation(True)
        return bool(function(handle, 4, ctypes.byref(information), ctypes.sizeof(information)))

    def describe(self, handle: int) -> tuple[int, FileIdentity, str]:
        function = self.kernel32.GetFileInformationByHandle
        function.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ByHandleFileInformation)]
        function.restype = wintypes.BOOL
        information = _ByHandleFileInformation()
        if not function(handle, ctypes.byref(information)):
            raise ctypes.WinError(ctypes.get_last_error())
        identity = FileIdentity(
            int(information.dwVolumeSerialNumber),
            (int(information.nFileIndexHigh) << 32) | int(information.nFileIndexLow),
        )
        return int(information.dwFileAttributes), identity, self._final_path(handle)

    def _final_path(self, handle: int) -> str:
        function = self.kernel32.GetFinalPathNameByHandleW
        function.argtypes = [wintypes.HANDLE, wintypes.LPWSTR, wintypes.DWORD, wintypes.DWORD]
        function.restype = wintypes.DWORD
        size = int(function(handle, None, 0, 0))
        if size == 0:
            raise ctypes.WinError(ctypes.get_last_error())
        buffer = ctypes.create_unicode_buffer(size + 1)
        written = int(function(handle, buffer, len(buffer), 0))
        if written == 0 or written >= len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        value = buffer.value
        if value.startswith("\\\\?\\UNC\\"):
            raise OSError("network paths are unsupported")
        if value.startswith("\\\\?\\"):
            value = value[4:]
        return _normalized(PureWindowsPath(value))

    def close(self, handle: int) -> None:
        function = self.kernel32.CloseHandle
        function.argtypes = [wintypes.HANDLE]
        function.restype = wintypes.BOOL
        function(handle)


def _normalized(path: PureWindowsPath) -> str:
    return ntpath.normcase(ntpath.normpath(str(path)))
