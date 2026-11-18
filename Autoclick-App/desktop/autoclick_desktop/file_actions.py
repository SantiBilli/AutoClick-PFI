from __future__ import annotations

import os
from pathlib import Path
import shutil
import tempfile
import uuid

from autoclick_desktop.execution_errors import ExecutionErrorCode, HandlerError
from autoclick_desktop.execution_models import ResolvedAction
from autoclick_desktop.platform_adapters import OperatingSystemAdapter


def _path(action: ResolvedAction, name: str = "path") -> Path:
    return Path(str(action.params[name]))


def _regular_file(path: Path) -> bool:
    return path.is_file() and not path.is_symlink()


def _directory(path: Path) -> bool:
    return path.is_dir() and not path.is_symlink()


def _require_file(path: Path) -> None:
    if not _regular_file(path):
        raise FileNotFoundError(path)


def _require_directory(path: Path) -> None:
    if not _directory(path):
        raise NotADirectoryError(path)


def _require_destination(source: Path, destination: Path, *, directory: bool, overwrite: bool) -> None:
    same_path = os.path.normcase(os.path.abspath(source)) == os.path.normcase(os.path.abspath(destination))
    if not same_path and source.exists() and destination.exists():
        try:
            same_path = os.path.samefile(source, destination)
        except OSError:
            pass
    if same_path:
        raise ValueError("source and destination are the same")
    _require_directory(destination.parent)
    if not destination.exists():
        return
    if not overwrite:
        raise FileExistsError(destination)
    if directory and not _directory(destination):
        raise NotADirectoryError(destination)
    if not directory and not _regular_file(destination):
        raise IsADirectoryError(destination)


def _copy_file(source: Path, destination: Path, overwrite: bool) -> None:
    _require_file(source)
    _require_destination(source, destination, directory=False, overwrite=overwrite)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".autoclick-copy-", dir=destination.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(source, temporary)
        _publish_file(temporary, destination, overwrite)
    finally:
        if temporary.exists():
            temporary.unlink()


def _move(source: Path, destination: Path, *, directory: bool, overwrite: bool) -> None:
    (_require_directory if directory else _require_file)(source)
    _require_destination(source, destination, directory=directory, overwrite=overwrite)
    if not destination.exists():
        shutil.move(source, destination)
        return
    backup = destination.with_name(f".{destination.name}.autoclick-backup-{uuid.uuid4().hex}")
    os.replace(destination, backup)
    try:
        shutil.move(source, destination)
    except BaseException:
        if destination.exists():
            shutil.rmtree(destination) if _directory(destination) else destination.unlink()
        os.replace(backup, destination)
        raise
    else:
        shutil.rmtree(backup) if directory else backup.unlink()


def _write_file(path: Path, content: str, encoding: str, overwrite: bool) -> None:
    _require_directory(path.parent)
    if path.exists():
        if not _regular_file(path):
            raise IsADirectoryError(path)
        if not overwrite:
            raise FileExistsError(path)
    descriptor, temporary_name = tempfile.mkstemp(prefix=".autoclick-write-", dir=path.parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        # Preserve the supplied text, including line endings, on every OS.
        temporary.write_text(content, encoding=encoding, newline='')
        _publish_file(temporary, path, overwrite)
    finally:
        if temporary.exists():
            temporary.unlink()


def _publish_file(temporary: Path, destination: Path, overwrite: bool) -> None:
    if overwrite:
        os.replace(temporary, destination)
        return
    os.link(temporary, destination)
    temporary.unlink()


def handle_file(action: ResolvedAction, os_adapter: OperatingSystemAdapter) -> object | None:
    try:
        operation = action.action_id
        if operation == "file.read":
            path = _path(action)
            _require_file(path)
            return path.read_text(encoding=str(action.params.get("encoding", "utf-8")))
        if operation == "file.write":
            _write_file(
                _path(action), str(action.params["content"]),
                str(action.params.get("encoding", "utf-8")),
                bool(action.params.get("overwrite", False)),
            )
        elif operation == "file.copy":
            _copy_file(
                _path(action, "source"), _path(action, "destination"),
                bool(action.params.get("overwrite", False)),
            )
        elif operation in {"file.move", "file.rename", "folder.move", "folder.rename"}:
            _move(
                _path(action, "source"), _path(action, "destination"),
                directory=operation.startswith("folder."),
                overwrite=bool(action.params.get("overwrite", False)),
            )
        elif operation == "file.delete":
            path = _path(action)
            _require_file(path)
            path.unlink()
        elif operation == "file.exists":
            return _regular_file(_path(action))
        elif operation == "folder.create":
            path = _path(action)
            if path.exists() and not _directory(path):
                raise FileExistsError(path)
            path.mkdir(parents=True, exist_ok=True)
        elif operation == "folder.listFiles":
            path = _path(action)
            _require_directory(path)
            return sorted((item.name for item in path.iterdir() if _regular_file(item)), key=str.casefold)
        elif operation == "folder.delete":
            path = _path(action)
            _require_directory(path)
            shutil.rmtree(path)
        elif operation == "folder.open":
            path = _path(action)
            _require_directory(path)
            os_adapter.open_folder(path)
        return None
    except HandlerError:
        raise
    except Exception:
        raise HandlerError(ExecutionErrorCode.FILESYSTEM_OPERATION_FAILED) from None
