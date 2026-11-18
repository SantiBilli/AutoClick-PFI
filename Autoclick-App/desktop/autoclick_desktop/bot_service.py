import errno
import hashlib
import json
import os
import re
import secrets
import stat
import tempfile
import threading
import time
import unicodedata
from collections import OrderedDict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Callable, Iterator, Literal, NotRequired, TypedDict, cast
from uuid import uuid4

from pydantic import ValidationError

from autoclick_desktop.bot_schema import (
    AiStateTooLargeError,
    Bot,
    LegacyBot,
    MAX_AI_STATE_SIZE,
    BotAiState,
    BotFlow,
    CanonicalAiData,
    CanonicalAiInput,
    CanonicalBotData,
    CanonicalBotInput,
    CanonicalPendingAiProposalData,
    CanonicalPendingAiProposalInput,
    PendingAiProposal,
    dump_canonical_bot,
    dump_canonical_ai,
    dump_canonical_pending_ai_proposal,
    parse_bot_data_tolerating_pending,
    semantic_bot_revision,
)


MAX_BOT_FILE_SIZE = 2 * 1024 * 1024
EDITOR_SESSION_TTL_SECONDS = 30 * 60
MAX_EDITOR_SESSIONS = 256
MAX_DESCRIPTOR_CACHE_ENTRIES = 256
_REPARSE_POINT_ATTRIBUTE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)

_DirectoryCacheScope = tuple[tuple[int, int], str]
_DescriptorCacheKey = tuple[tuple[int, int], str, str]
_FileLockKey = tuple[int, int, str]


@dataclass
class _FileLockEntry:
    lock: threading.Lock
    users: int = 0


_file_locks_guard = threading.Lock()
_file_locks: dict[_FileLockKey, _FileLockEntry] = {}


@dataclass(frozen=True)
class _DirectoryAnchor:
    scan_target: Path | int
    descriptor: int | None = None
    windows_handle: int | None = None


@dataclass(frozen=True)
class _EntrySession:
    generation: str
    directory_identity: tuple[int, int]
    filename: str


@dataclass
class _EditorSession:
    generation: str
    directory_identity: tuple[int, int]
    filename: str
    entry_id: str
    last_used: float
    active_uses: int = 0
    invalidated: bool = False


class BotServiceError(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class BotDescriptor(TypedDict):
    entryId: str
    filename: str
    botId: str
    name: str
    description: str
    icon: str | None
    blockCount: int
    modifiedAt: str
    fileSize: int


class BotCatalog(TypedDict):
    directoryName: str
    directoryPath: str
    bots: list[BotDescriptor]
    invalidCount: int


class LoadedBot(TypedDict):
    bot: CanonicalBotData
    editorToken: str
    botDirectoryPath: str
    revision: str
    botRevision: str
    descriptor: BotDescriptor
    warning: NotRequired[str]


class SavedBot(TypedDict):
    revision: str
    botRevision: str
    descriptor: BotDescriptor


class SavedBotAi(SavedBot):
    ai: CanonicalAiData


class SavedPendingAiProposal(SavedBot):
    pendingAiProposal: CanonicalPendingAiProposalData | None


@dataclass(frozen=True, slots=True)
class EditorExecutionAuthorization:
    bot_directory: PureWindowsPath


class BotService:
    def __init__(
        self,
        settings_directory: str | os.PathLike[str] | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        if settings_directory is None:
            local_app_data = os.environ.get("LOCALAPPDATA")
            if local_app_data is None:
                local_app_data = str(Path.home() / "AppData" / "Local")
            settings_directory = Path(local_app_data) / "AutoClick"

        self._settings_directory = Path(settings_directory)
        self._settings_path = self._settings_directory / "settings.json"
        self._generation = secrets.token_urlsafe(24)
        self._entry_ids: dict[tuple[str, str], str] = {}
        self._entries: dict[str, _EntrySession] = {}
        self._editors: dict[str, _EditorSession] = {}
        self._entry_warnings: dict[str, str] = {}
        self._descriptor_cache: OrderedDict[_DescriptorCacheKey, BotDescriptor] = (
            OrderedDict()
        )
        self._monotonic = monotonic
        self._selection_lock = threading.Lock()
        self._sessions_lock = threading.RLock()
        self._descriptor_cache_lock = threading.RLock()
        # Allowed nesting is selection -> file -> sessions/cache and
        # selection -> sessions. Sessions and cache are never nested, and the
        # cache lock is never held while acquiring a file or sessions lock.
        self._selected_directory = self._load_selected_directory()

    def select_directory(self, directory: str | os.PathLike[str]) -> BotCatalog:
        selected = Path(os.path.abspath(os.fspath(directory)))
        generation = secrets.token_urlsafe(24)
        with self._selection_lock:
            try:
                catalog = self._scan_directory(selected, generation)
                if catalog is None:
                    raise NotADirectoryError("Selected directory is unavailable")
                self._write_selected_directory(selected)
            except BaseException:
                with self._sessions_lock:
                    self._discard_generation_locked(generation)
                raise

            with self._sessions_lock:
                self._selected_directory = selected
                self._generation = generation
                self._entry_ids = {
                    key: entry_id
                    for key, entry_id in self._entry_ids.items()
                    if key[0] == generation
                }
                self._entries = {
                    entry_id: entry
                    for entry_id, entry in self._entries.items()
                    if entry.generation == generation
                }
                self._entry_warnings = {
                    entry_id: warning
                    for entry_id, warning in self._entry_warnings.items()
                    if entry_id in self._entries
                }
                self._invalidate_editor_sessions_locked()
            return catalog

    def get_catalog(self) -> BotCatalog | None:
        with self._selection_lock:
            self._prune_editor_sessions()
            with self._sessions_lock:
                selected_directory = self._selected_directory
                generation = self._generation
            if selected_directory is None:
                return None

            catalog = self._scan_directory(selected_directory, generation)
            if catalog is None:
                self._discard_selected_directory()
                raise NotADirectoryError("Selected directory is unavailable")
            return catalog

    def create_bot(self, name: str) -> LoadedBot:
        try:
            bot = Bot(
                schemaVersion=2,
                id=uuid4(),
                name=name,
                description="",
                flow=BotFlow(root=[], nodes=[]),
            )
        except ValidationError as error:
            raise BotServiceError("BOT_INVALID") from error

        payload = (
            json.dumps(
                dump_canonical_bot(bot),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        filename_stem = self._safe_filename_stem(bot.name)

        with self._selection_lock:
            with self._sessions_lock:
                selected_directory = self._selected_directory
                generation = self._generation
            if selected_directory is None:
                raise BotServiceError("DIRECTORY_UNAVAILABLE")

            try:
                with self._open_directory_anchor(selected_directory) as anchor:
                    directory_identity = self._directory_identity(anchor)
                    filename, file_stat = self._create_bot_file(
                        filename_stem, payload, anchor
                    )
            except BotServiceError:
                raise
            except OSError as error:
                raise BotServiceError("DIRECTORY_UNAVAILABLE") from error

            entry_id = self._register_entry(
                generation, directory_identity, filename
            )
            editor_token = secrets.token_urlsafe(32)
            descriptor = self._make_descriptor(
                entry_id, filename, bot, file_stat, len(payload)
            )
            with self._sessions_lock:
                self._prune_editor_sessions_locked(self._monotonic())
                self._editors[editor_token] = _EditorSession(
                    generation,
                    directory_identity,
                    filename,
                    entry_id,
                    self._monotonic(),
                )
                self._prune_editor_session_cap_locked()
            cache_scope = self._directory_cache_scope(
                selected_directory, directory_identity
            )
            self._cache_descriptor(
                self._descriptor_cache_key(cache_scope, filename), descriptor
            )
            return {
                "bot": cast(
                    CanonicalBotData,
                    dump_canonical_bot(bot),
                ),
                "editorToken": editor_token,
                "botDirectoryPath": str(selected_directory),
                "revision": self._revision(file_stat, payload),
                "botRevision": semantic_bot_revision(bot),
                "descriptor": descriptor,
            }
    def delete_bot(self, entry_id: str) -> None:
        self._prune_editor_sessions()
        with self._selection_lock:
            with self._sessions_lock:
                entry = self._entries.get(entry_id)
                selected_directory = self._selected_directory
                if (
                    selected_directory is None
                    or entry is None
                    or entry.generation != self._generation
                ):
                    raise BotServiceError("BOT_ENTRY_NOT_FOUND")

            lock_key = self._file_lock_key(
                entry.directory_identity, selected_directory, entry.filename
            )
            with self._acquire_file_lock(lock_key):
                try:
                    with self._open_directory_anchor(selected_directory) as anchor:
                        if self._directory_identity(anchor) != entry.directory_identity:
                            raise BotServiceError("BOT_ENTRY_NOT_FOUND")

                        target_file = Path(selected_directory) / entry.filename
                        try:
                            if target_file.exists():
                                try:
                                    target_file.chmod(stat.S_IWRITE | stat.S_IREAD)
                                except OSError:
                                    pass
                            target_file.unlink()
                        except FileNotFoundError as error:
                            raise BotServiceError("BOT_ENTRY_NOT_FOUND") from error
                        except OSError as error:
                            raise BotServiceError("BOT_SAVE_FAILED") from error

                        with self._descriptor_cache_lock:
                            stale_keys = [
                                k for k in self._descriptor_cache
                                if k[0] == entry.directory_identity and k[1] == entry.filename
                            ]
                            for k in stale_keys:
                                self._descriptor_cache.pop(k, None)

                        with self._sessions_lock:
                            self._entries.pop(entry_id, None)
                            stale_tokens = [
                                token for token, session in self._editors.items()
                                if session.filename == entry.filename and session.directory_identity == entry.directory_identity
                            ]
                            for token in stale_tokens:
                                self._editors.pop(token, None)
                except BotServiceError:
                    raise
                except OSError as error:
                    raise BotServiceError("DIRECTORY_UNAVAILABLE") from error


    @staticmethod
    def _safe_filename_stem(name: str) -> str:
        normalized = unicodedata.normalize("NFKD", name)
        ascii_name = normalized.encode("ascii", "ignore").decode("ascii").lower()
        stem = re.sub(r"[^a-z0-9]+", "-", ascii_name).strip("-")[:80]
        stem = stem or "bot"
        windows_reserved = {
            "con", "prn", "aux", "nul",
            *(f"com{index}" for index in range(1, 10)),
            *(f"lpt{index}" for index in range(1, 10)),
        }
        return f"bot-{stem}" if stem in windows_reserved else stem

    @classmethod
    def _create_bot_file(
        cls, filename_stem: str, payload: bytes, anchor: _DirectoryAnchor
    ) -> tuple[str, os.stat_result]:
        for suffix in range(1, 10_001):
            filename = (
                f"{filename_stem}.json"
                if suffix == 1
                else f"{filename_stem}-{suffix}.json"
            )
            descriptor = -1
            created = False
            try:
                descriptor = cls._create_temporary_file(filename, anchor)
                created = True
                cls._write_all(descriptor, payload)
                os.fsync(descriptor)
                return filename, os.fstat(descriptor)
            except OSError as error:
                if not created and (
                    error.errno == errno.EEXIST
                    or getattr(error, "winerror", None) in {80, 183}
                ):
                    continue
                if created:
                    try:
                        cls._delete_temporary_file(descriptor, filename, anchor)
                    except OSError:
                        pass
                raise BotServiceError("BOT_SAVE_FAILED") from error
            finally:
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
        raise BotServiceError("BOT_SAVE_FAILED")

    def _load_selected_directory(self) -> Path | None:
        try:
            raw_settings = self._settings_path.read_text(encoding="utf-8-sig")
            settings: object = json.loads(raw_settings)
            if not isinstance(settings, dict):
                return None
            directory = settings.get("botDirectory")
            if not isinstance(directory, str) or not directory:
                return None
            return Path(directory)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, RecursionError):
            return None

    def _discard_selected_directory(self) -> None:
        with self._sessions_lock:
            self._selected_directory = None
            self._entries.clear()
            self._entry_ids.clear()
            self._entry_warnings.clear()
            self._invalidate_editor_sessions_locked()
        with self._descriptor_cache_lock:
            self._descriptor_cache.clear()
        try:
            self._settings_path.unlink(missing_ok=True)
        except OSError:
            pass

    def _write_selected_directory(self, directory: Path) -> None:
        self._settings_directory.mkdir(parents=True, exist_ok=True)
        payload = json.dumps({"botDirectory": str(directory)}, ensure_ascii=True).encode("utf-8")
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=self._settings_directory,
                prefix="settings-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(payload)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.replace(temporary_path, self._settings_path)
        except BaseException:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise

    def _scan_directory(self, directory: Path, generation: str) -> BotCatalog | None:
        bots: list[BotDescriptor] = []
        invalid_count = 0
        seen_keys: set[tuple[str, str]] = set()
        try:
            with self._open_directory_anchor(directory) as anchor:
                directory_identity = self._directory_identity(anchor)
                cache_scope = self._directory_cache_scope(directory, directory_identity)
                seen_cache_keys: set[_DescriptorCacheKey] = set()
                entries = list(os.scandir(anchor.scan_target))

                for entry in entries:
                    if Path(entry.name).suffix.casefold() != ".json":
                        continue
                    cache_key = self._descriptor_cache_key(cache_scope, entry.name)
                    try:
                        descriptor = self._read_descriptor(
                            entry,
                            directory,
                            anchor,
                            generation,
                            directory_identity,
                            cache_key,
                        )
                        if descriptor is not None:
                            bots.append(descriptor)
                            seen_keys.add((generation, entry.name))
                            seen_cache_keys.add(cache_key)
                        else:
                            self._remove_cached_descriptor(cache_key)
                    except (
                        OSError,
                        OverflowError,
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                        ValidationError,
                        ValueError,
                        RecursionError,
                    ):
                        self._remove_cached_descriptor(cache_key)
                        invalid_count += 1
        except OSError:
            return None

        self._sweep_descriptor_cache(cache_scope, seen_cache_keys)

        with self._sessions_lock:
            stale_keys = [
                key for key in self._entry_ids if key[0] == generation and key not in seen_keys
            ]
            stale_ids = {self._entry_ids.pop(key) for key in stale_keys}
            for entry_id in stale_ids:
                self._entries.pop(entry_id, None)
                self._entry_warnings.pop(entry_id, None)
        self._prune_editor_sessions()

        bots.sort(key=lambda bot: (bot["name"].casefold(), bot["filename"].casefold()))
        return {
            "directoryName": directory.name,
            "directoryPath": str(directory),
            "bots": bots,
            "invalidCount": invalid_count,
        }

    def _discard_generation_locked(self, generation: str) -> None:
        stale_keys = [key for key in self._entry_ids if key[0] == generation]
        stale_ids = {self._entry_ids.pop(key) for key in stale_keys}
        for entry_id in stale_ids:
            self._entries.pop(entry_id, None)
            self._entry_warnings.pop(entry_id, None)

    def _read_descriptor(
        self,
        entry: os.DirEntry[str],
        directory: Path,
        anchor: _DirectoryAnchor,
        generation: str,
        directory_identity: tuple[int, int],
        cache_key: _DescriptorCacheKey,
    ) -> BotDescriptor | None:
        # Lock order is selection -> file -> sessions. Saves never acquire the
        # selection lock and release the file lock before session cleanup.
        lock_key = self._file_lock_key(directory_identity, directory, entry.name)
        with self._acquire_file_lock(lock_key):
            try:
                entry_stat = entry.stat(follow_symlinks=False)
                if stat.S_ISLNK(entry_stat.st_mode) or self._is_reparse_point(entry_stat):
                    raise ValueError("unsafe bot file")
                if not stat.S_ISREG(entry_stat.st_mode):
                    return None
                if entry_stat.st_size > MAX_BOT_FILE_SIZE:
                    raise ValueError("bot file exceeds size limit")

                raw_data, bot, file_stat, pending_issue = self._read_bot(
                    entry.name, anchor
                )
            except OSError as error:
                if not self._is_windows_sharing_violation(error):
                    raise
                cached = self._get_cached_descriptor(cache_key)
                if cached is None:
                    raise
                entry_id = self._register_entry(
                    generation, directory_identity, entry.name
                )
                return cast(
                    BotDescriptor,
                    {**cached, "entryId": entry_id, "filename": entry.name},
                )

            entry_id = self._register_entry(generation, directory_identity, entry.name)
            if pending_issue is not None and isinstance(bot, Bot):
                cleaned = self._clean_invalid_pending(
                    _EditorSession(
                        generation,
                        directory_identity,
                        entry.name,
                        entry_id,
                        self._monotonic(),
                    ),
                    self._revision(file_stat, raw_data),
                    bot,
                    anchor,
                )
                with self._sessions_lock:
                    self._entry_warnings[entry_id] = (
                        f"PENDING_AI_PROPOSAL_{'STALE_' if pending_issue == 'stale' else ''}"
                        f"{'DISCARDED' if cleaned is not None else 'DISCARD_FAILED'}"
                    )
                if cleaned is not None:
                    self._cache_descriptor(cache_key, cleaned["descriptor"])
                    return cleaned["descriptor"]
            descriptor = self._make_descriptor(
                entry_id, entry.name, bot, file_stat, len(raw_data)
            )
            self._cache_descriptor(cache_key, descriptor)
            return descriptor

    def _register_entry(
        self,
        generation: str,
        directory_identity: tuple[int, int],
        filename: str,
    ) -> str:
        key = (generation, filename)
        with self._sessions_lock:
            entry_id = self._entry_ids.setdefault(key, secrets.token_urlsafe(24))
            self._entries[entry_id] = _EntrySession(
                generation, directory_identity, filename
            )
        return entry_id

    def _cache_descriptor(
        self, cache_key: _DescriptorCacheKey, descriptor: BotDescriptor
    ) -> None:
        with self._descriptor_cache_lock:
            self._descriptor_cache[cache_key] = descriptor.copy()
            self._descriptor_cache.move_to_end(cache_key)
            while len(self._descriptor_cache) > MAX_DESCRIPTOR_CACHE_ENTRIES:
                self._descriptor_cache.popitem(last=False)

    def _get_cached_descriptor(
        self, cache_key: _DescriptorCacheKey
    ) -> BotDescriptor | None:
        with self._descriptor_cache_lock:
            descriptor = self._descriptor_cache.get(cache_key)
            if descriptor is None:
                return None
            self._descriptor_cache.move_to_end(cache_key)
            return descriptor.copy()

    def _remove_cached_descriptor(self, cache_key: _DescriptorCacheKey) -> None:
        with self._descriptor_cache_lock:
            self._descriptor_cache.pop(cache_key, None)

    def _sweep_descriptor_cache(
        self,
        cache_scope: _DirectoryCacheScope,
        seen_cache_keys: set[_DescriptorCacheKey],
    ) -> None:
        # Keep snapshot and removal atomic so a save cannot refresh a stale key
        # between those operations and then have its committed descriptor removed.
        with self._descriptor_cache_lock:
            stale_cache_keys = [
                key
                for key in self._descriptor_cache
                if key[:2] == cache_scope and key not in seen_cache_keys
            ]
            for key in stale_cache_keys:
                del self._descriptor_cache[key]

    @staticmethod
    def _directory_cache_scope(
        directory: Path, directory_identity: tuple[int, int]
    ) -> _DirectoryCacheScope:
        normalized_path = os.path.normcase(os.path.abspath(os.fspath(directory)))
        return directory_identity, normalized_path

    @staticmethod
    def _descriptor_cache_key(
        scope: _DirectoryCacheScope, filename: str
    ) -> _DescriptorCacheKey:
        return scope[0], scope[1], os.path.normcase(filename)

    @staticmethod
    def _is_windows_sharing_violation(error: OSError) -> bool:
        return getattr(error, "winerror", None) in {32, 33}

    def _read_bot(
        self, filename: str, anchor: _DirectoryAnchor
    ) -> tuple[
        bytes,
        Bot | LegacyBot,
        os.stat_result,
        Literal["invalid", "stale"] | None,
    ]:
        descriptor = self._open_file_no_follow(filename, anchor)
        try:
            raw_data, file_stat = self._read_open_file(descriptor)
        finally:
            os.close(descriptor)
        text = raw_data.decode("utf-8-sig")
        data = json.loads(text, parse_constant=self._reject_json_constant)
        bot, pending_issue = parse_bot_data_tolerating_pending(data)
        return raw_data, bot, file_stat, pending_issue

    @classmethod
    def _read_open_file(cls, descriptor: int) -> tuple[bytes, os.stat_result]:
        file_stat = os.fstat(descriptor)
        if (
            not stat.S_ISREG(file_stat.st_mode)
            or cls._is_reparse_point(file_stat)
            or file_stat.st_size > MAX_BOT_FILE_SIZE
        ):
            raise ValueError("unsafe bot file")
        os.lseek(descriptor, 0, os.SEEK_SET)
        chunks: list[bytes] = []
        remaining = MAX_BOT_FILE_SIZE + 1
        while remaining:
            chunk = os.read(descriptor, min(64 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw_data = b"".join(chunks)
        if len(raw_data) > MAX_BOT_FILE_SIZE:
            raise ValueError("bot file exceeds size limit")
        return raw_data, file_stat

    @staticmethod
    def _make_descriptor(
        entry_id: str,
        filename: str,
        bot: Bot | LegacyBot,
        file_stat: os.stat_result,
        file_size: int,
    ) -> BotDescriptor:
        modified_at = datetime.fromtimestamp(file_stat.st_mtime, timezone.utc)
        return {
            "entryId": entry_id,
            "filename": filename,
            "botId": str(bot.id),
            "name": bot.name,
            "description": bot.description,
            "icon": bot.icon,
            "blockCount": len(bot.flow.nodes),
            "modifiedAt": modified_at.isoformat().replace("+00:00", "Z"),
            "fileSize": file_size,
        }

    def load_bot(self, entry_id: str) -> LoadedBot:
        self._prune_editor_sessions()
        with self._sessions_lock:
            entry = self._entries.get(entry_id)
            selected_directory = self._selected_directory
            if (
                selected_directory is None
                or entry is None
                or entry.generation != self._generation
            ):
                raise BotServiceError("BOT_ENTRY_NOT_FOUND")

        lock_key = self._file_lock_key(
            entry.directory_identity, selected_directory, entry.filename
        )
        with self._acquire_file_lock(lock_key):
            cleanup_result: SavedBot | None = None
            cleanup_warning: str | None = None
            try:
                with self._open_directory_anchor(selected_directory) as anchor:
                    if self._directory_identity(anchor) != entry.directory_identity:
                        raise BotServiceError("BOT_ENTRY_NOT_FOUND")
                    try:
                        for cleanup_attempt in range(2):
                            raw_data, bot, file_stat, pending_issue = self._read_bot(
                                entry.filename, anchor
                            )
                            if pending_issue is None or not isinstance(bot, Bot):
                                break
                            cleanup_result = self._clean_invalid_pending(
                                _EditorSession(
                                    entry.generation,
                                    entry.directory_identity,
                                    entry.filename,
                                    entry_id,
                                    self._monotonic(),
                                ),
                                self._revision(file_stat, raw_data),
                                bot,
                                anchor,
                            )
                            if cleanup_result is not None:
                                cleanup_warning = (
                                    "PENDING_AI_PROPOSAL_STALE_DISCARDED"
                                    if pending_issue == "stale"
                                    else "PENDING_AI_PROPOSAL_DISCARDED"
                                )
                                break
                            cleanup_warning = (
                                "PENDING_AI_PROPOSAL_STALE_DISCARD_FAILED"
                                if pending_issue == "stale"
                                else "PENDING_AI_PROPOSAL_DISCARD_FAILED"
                            )
                            if cleanup_attempt == 1:
                                break
                    except FileNotFoundError as error:
                        raise BotServiceError("BOT_ENTRY_NOT_FOUND") from error
                    except (
                        UnicodeDecodeError,
                        json.JSONDecodeError,
                        ValidationError,
                        ValueError,
                        RecursionError,
                    ) as error:
                        raise BotServiceError("BOT_INVALID") from error
                    except OSError as error:
                        raise BotServiceError("BOT_LOAD_FAILED") from error
            except BotServiceError:
                raise
            except OSError as error:
                raise BotServiceError("DIRECTORY_UNAVAILABLE") from error

            token = secrets.token_urlsafe(32)
            result: LoadedBot = {
                "bot": cast(
                    CanonicalBotData,
                    dump_canonical_bot(bot),
                ),
                "editorToken": token,
                "botDirectoryPath": str(selected_directory),
                "revision": (
                    cleanup_result["revision"]
                    if cleanup_result is not None
                    else self._revision(file_stat, raw_data)
                ),
                "botRevision": semantic_bot_revision(bot),
                "descriptor": (
                    cleanup_result["descriptor"]
                    if cleanup_result is not None
                    else self._make_descriptor(
                        entry_id, entry.filename, bot, file_stat, len(raw_data)
                    )
                ),
            }
            if cleanup_warning is not None:
                result["warning"] = cleanup_warning
            if cleanup_result is not None:
                cache_scope = self._directory_cache_scope(
                    selected_directory, entry.directory_identity
                )
                self._cache_descriptor(
                    self._descriptor_cache_key(cache_scope, entry.filename),
                    cleanup_result["descriptor"],
                )
            with self._sessions_lock:
                if (
                    entry.generation != self._generation
                    or selected_directory != self._selected_directory
                ):
                    raise BotServiceError("BOT_ENTRY_NOT_FOUND")
                stored_warning = self._entry_warnings.pop(entry_id, None)
                if "warning" not in result and stored_warning is not None:
                    result["warning"] = stored_warning
                self._prune_editor_sessions_locked(self._monotonic())
                self._editors[token] = _EditorSession(
                    entry.generation,
                    entry.directory_identity,
                    entry.filename,
                    entry_id,
                    self._monotonic(),
                )
                self._prune_editor_session_cap_locked()
            return result

    def _clean_invalid_pending(
        self,
        editor: _EditorSession,
        expected_revision: str,
        bot: Bot,
        anchor: _DirectoryAnchor,
    ) -> SavedBot | None:
        clean_bot = bot.model_copy(update={"pending_ai_proposal": None})
        payload = (
            json.dumps(
                dump_canonical_bot(clean_bot),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
        try:
            return self._write_bot_atomically(
                editor,
                expected_revision,
                payload,
                clean_bot,
                anchor,
                failure_code="BOT_PENDING_AI_SAVE_FAILED",
            )
        except BotServiceError:
            return None

    def save_bot(
        self,
        editor_token: str,
        expected_revision: str,
        bot: CanonicalBotInput,
        clear_pending_ai_proposal: bool = False,
    ) -> SavedBot:
        with self._use_editor_session(editor_token) as (editor, selected_directory):
            try:
                with self._open_directory_anchor(selected_directory) as anchor:
                    if self._directory_identity(anchor) != editor.directory_identity:
                        raise BotServiceError("BOT_ENTRY_NOT_FOUND")
                    lock_key = self._file_lock_key(
                        editor.directory_identity,
                        selected_directory,
                        editor.filename,
                    )
                    with self._acquire_file_lock(lock_key):
                        try:
                            (
                                current_data,
                                current_bot,
                                current_stat,
                                _invalid_pending,
                            ) = self._read_bot(editor.filename, anchor)
                        except FileNotFoundError as error:
                            raise BotServiceError("BOT_ENTRY_NOT_FOUND") from error
                        except (
                            UnicodeDecodeError,
                            json.JSONDecodeError,
                            ValidationError,
                            ValueError,
                            RecursionError,
                        ) as error:
                            raise BotServiceError("BOT_CHANGED_EXTERNALLY") from error
                        except OSError as error:
                            raise BotServiceError("BOT_SAVE_FAILED") from error
                        if self._revision(current_stat, current_data) != expected_revision:
                            raise BotServiceError("BOT_CHANGED_EXTERNALLY")
                        try:
                            # Reject values that Pydantic's JSON mode could otherwise coerce
                            # (for example NaN to null or sets to arrays).
                            json.dumps(bot, allow_nan=False)
                            normalized_bot = Bot.model_validate(bot)
                            if isinstance(bot, dict) and "ai" not in bot:
                                normalized_bot = normalized_bot.model_copy(
                                    update={"ai": current_bot.ai}
                                )
                            semantic_changed = (
                                semantic_bot_revision(normalized_bot)
                                != semantic_bot_revision(current_bot)
                            )
                            if semantic_changed or clear_pending_ai_proposal:
                                normalized_bot = normalized_bot.model_copy(
                                    update={"pending_ai_proposal": None}
                                )
                            elif isinstance(bot, dict) and "pendingAiProposal" not in bot:
                                normalized_bot = normalized_bot.model_copy(
                                    update={"pending_ai_proposal": current_bot.pending_ai_proposal}
                                )
                            payload = (
                                json.dumps(
                                    dump_canonical_bot(normalized_bot),
                                    ensure_ascii=False,
                                    indent=2,
                                    allow_nan=False,
                                )
                                + "\n"
                            ).encode("utf-8")
                        except (
                            ValidationError,
                            ValueError,
                            TypeError,
                            OverflowError,
                            RecursionError,
                        ) as error:
                            raise BotServiceError("BOT_INVALID") from error
                        if len(payload) > MAX_BOT_FILE_SIZE:
                            raise BotServiceError("BOT_INVALID")
                        result = self._write_bot_atomically(
                            editor,
                            expected_revision,
                            payload,
                            normalized_bot,
                            anchor,
                        )
                        cache_scope = self._directory_cache_scope(
                            selected_directory, editor.directory_identity
                        )
                        self._cache_descriptor(
                            self._descriptor_cache_key(cache_scope, editor.filename),
                            result["descriptor"],
                        )
                        return result
            except BotServiceError:
                raise
            except OSError as error:
                raise BotServiceError("DIRECTORY_UNAVAILABLE") from error

    def save_ai(
        self,
        editor_token: str,
        expected_revision: str,
        ai: CanonicalAiInput,
    ) -> SavedBotAi:
        with self._use_editor_session(editor_token) as (editor, selected_directory):
            try:
                with self._open_directory_anchor(selected_directory) as anchor:
                    if self._directory_identity(anchor) != editor.directory_identity:
                        raise BotServiceError("BOT_ENTRY_NOT_FOUND")
                    lock_key = self._file_lock_key(
                        editor.directory_identity,
                        selected_directory,
                        editor.filename,
                    )
                    with self._acquire_file_lock(lock_key):
                        try:
                            (
                                current_data,
                                current_bot,
                                current_stat,
                                _invalid_pending,
                            ) = self._read_bot(editor.filename, anchor)
                        except FileNotFoundError as error:
                            raise BotServiceError("BOT_ENTRY_NOT_FOUND") from error
                        except (
                            UnicodeDecodeError,
                            json.JSONDecodeError,
                            ValidationError,
                            ValueError,
                            OSError,
                            RecursionError,
                        ) as error:
                            raise BotServiceError("BOT_AI_SAVE_FAILED") from error
                        if self._revision(current_stat, current_data) != expected_revision:
                            raise BotServiceError("BOT_CHANGED_EXTERNALLY")

                        try:
                            json.dumps(ai, allow_nan=False)
                            normalized_ai = BotAiState.model_validate(ai)
                        except ValidationError as error:
                            code = (
                                "BOT_AI_TOO_LARGE"
                                if self._is_ai_too_large_error(error)
                                else "BOT_AI_INVALID"
                            )
                            raise BotServiceError(code) from error
                        except (ValueError, TypeError, OverflowError, RecursionError) as error:
                            raise BotServiceError("BOT_AI_INVALID") from error

                        normalized_bot = current_bot.model_copy(
                            update={"ai": normalized_ai}
                        )
                        try:
                            payload = (
                                json.dumps(
                                    dump_canonical_bot(normalized_bot),
                                    ensure_ascii=False,
                                    indent=2,
                                    allow_nan=False,
                                )
                                + "\n"
                            ).encode("utf-8")
                        except (ValueError, TypeError, OverflowError, RecursionError) as error:
                            raise BotServiceError("BOT_AI_SAVE_FAILED") from error
                        if len(payload) > MAX_BOT_FILE_SIZE:
                            raise BotServiceError("BOT_AI_TOO_LARGE")

                        result = self._write_bot_atomically(
                            editor,
                            expected_revision,
                            payload,
                            normalized_bot,
                            anchor,
                            failure_code="BOT_AI_SAVE_FAILED",
                        )
                        cache_scope = self._directory_cache_scope(
                            selected_directory, editor.directory_identity
                        )
                        self._cache_descriptor(
                            self._descriptor_cache_key(cache_scope, editor.filename),
                            result["descriptor"],
                        )
                        return {
                            **result,
                            "ai": dump_canonical_ai(normalized_ai),
                        }
            except BotServiceError:
                raise
            except OSError as error:
                raise BotServiceError("BOT_AI_SAVE_FAILED") from error

    def save_pending_ai_proposal(
        self,
        editor_token: str,
        expected_revision: str,
        pending: CanonicalPendingAiProposalInput | None,
    ) -> SavedPendingAiProposal:
        with self._use_editor_session(editor_token) as (editor, selected_directory):
            try:
                with self._open_directory_anchor(selected_directory) as anchor:
                    if self._directory_identity(anchor) != editor.directory_identity:
                        raise BotServiceError("BOT_ENTRY_NOT_FOUND")
                    lock_key = self._file_lock_key(
                        editor.directory_identity, selected_directory, editor.filename
                    )
                    with self._acquire_file_lock(lock_key):
                        try:
                            (
                                current_data,
                                current_bot,
                                current_stat,
                                _invalid_pending,
                            ) = self._read_bot(editor.filename, anchor)
                        except FileNotFoundError as error:
                            raise BotServiceError("BOT_ENTRY_NOT_FOUND") from error
                        except (
                            UnicodeDecodeError,
                            json.JSONDecodeError,
                            ValidationError,
                            ValueError,
                            OSError,
                            RecursionError,
                        ) as error:
                            raise BotServiceError("BOT_PENDING_AI_SAVE_FAILED") from error
                        if self._revision(current_stat, current_data) != expected_revision:
                            raise BotServiceError("BOT_CHANGED_EXTERNALLY")
                        if not isinstance(current_bot, Bot):
                            raise BotServiceError("BOT_PENDING_AI_INVALID")

                        try:
                            normalized_pending = (
                                None
                                if pending is None
                                else PendingAiProposal.model_validate(pending)
                            )
                        except (
                            ValidationError,
                            ValueError,
                            TypeError,
                            OverflowError,
                            RecursionError,
                        ) as error:
                            raise BotServiceError("BOT_PENDING_AI_INVALID") from error
                        if (
                            normalized_pending is not None
                            and normalized_pending.editor_bot_revision
                            != semantic_bot_revision(current_bot)
                        ):
                            raise BotServiceError("BOT_PENDING_AI_STALE")
                        try:
                            compact = json.dumps(
                                None if normalized_pending is None else dump_canonical_pending_ai_proposal(normalized_pending),
                                ensure_ascii=False,
                                separators=(",", ":"),
                                allow_nan=False,
                            ).encode("utf-8")
                            if len(compact) > MAX_AI_STATE_SIZE:
                                raise AiStateTooLargeError("pending AI proposal exceeds size limit")
                        except AiStateTooLargeError as error:
                            raise BotServiceError("BOT_PENDING_AI_TOO_LARGE") from error
                        except (ValueError, TypeError, OverflowError, RecursionError) as error:
                            raise BotServiceError("BOT_PENDING_AI_INVALID") from error

                        normalized_bot = current_bot.model_copy(
                            update={"pending_ai_proposal": normalized_pending}
                        )
                        try:
                            payload = (
                                json.dumps(
                                    dump_canonical_bot(normalized_bot),
                                    ensure_ascii=False,
                                    indent=2,
                                    allow_nan=False,
                                )
                                + "\n"
                            ).encode("utf-8")
                        except (ValueError, TypeError, OverflowError, RecursionError) as error:
                            raise BotServiceError("BOT_PENDING_AI_SAVE_FAILED") from error
                        if len(payload) > MAX_BOT_FILE_SIZE:
                            raise BotServiceError("BOT_PENDING_AI_TOO_LARGE")

                        result = self._write_bot_atomically(
                            editor,
                            expected_revision,
                            payload,
                            normalized_bot,
                            anchor,
                            failure_code="BOT_PENDING_AI_SAVE_FAILED",
                        )
                        cache_scope = self._directory_cache_scope(
                            selected_directory, editor.directory_identity
                        )
                        self._cache_descriptor(
                            self._descriptor_cache_key(cache_scope, editor.filename),
                            result["descriptor"],
                        )
                        return {
                            **result,
                            "pendingAiProposal": (
                                None
                                if normalized_pending is None
                                else dump_canonical_pending_ai_proposal(normalized_pending)
                            ),
                        }
            except BotServiceError:
                raise
            except OSError as error:
                raise BotServiceError("BOT_PENDING_AI_SAVE_FAILED") from error

    @staticmethod
    def _is_ai_too_large_error(error: ValidationError) -> bool:
        return any(
            isinstance(detail.get("ctx", {}).get("error"), AiStateTooLargeError)
            for detail in error.errors(include_url=False)
        )

    @contextmanager
    def authorize_execution(
        self, editor_token: str
    ) -> Iterator[EditorExecutionAuthorization]:
        """Pin an authorized editor source for the complete execution lifetime."""
        with self._use_editor_session(editor_token) as (_editor, selected_directory):
            yield EditorExecutionAuthorization(PureWindowsPath(str(selected_directory)))

    @contextmanager
    def _use_editor_session(
        self, editor_token: str
    ) -> Iterator[tuple[_EditorSession, Path]]:
        with self._sessions_lock:
            now = self._monotonic()
            self._prune_editor_sessions_locked(now)
            editor = self._editors.get(editor_token)
            selected_directory = self._selected_directory
            if (
                editor is None
                or editor.invalidated
                or selected_directory is None
                or editor.generation != self._generation
            ):
                raise BotServiceError("BOT_ENTRY_NOT_FOUND")
            editor.active_uses += 1
            editor.last_used = now
        try:
            yield editor, selected_directory
        finally:
            with self._sessions_lock:
                current = self._editors.get(editor_token)
                if current is editor:
                    editor.active_uses -= 1
                    editor.last_used = self._monotonic()
                    if editor.invalidated:
                        del self._editors[editor_token]
                    else:
                        self._prune_editor_sessions_locked(editor.last_used)
                        self._prune_editor_session_cap_locked(
                            protected_token=editor_token
                        )

    def _prune_editor_sessions(self) -> None:
        with self._sessions_lock:
            self._prune_editor_sessions_locked(self._monotonic())

    def _prune_editor_sessions_locked(self, now: float) -> None:
        expired = [
            token
            for token, editor in self._editors.items()
            if editor.active_uses == 0
            and now - editor.last_used >= EDITOR_SESSION_TTL_SECONDS
        ]
        for token in expired:
            del self._editors[token]

    def _prune_editor_session_cap_locked(
        self, *, protected_token: str | None = None
    ) -> None:
        pinned_count = sum(editor.active_uses > 0 for editor in self._editors.values())
        while len(self._editors) > MAX_EDITOR_SESSIONS + pinned_count:
            candidates = [
                (token, editor)
                for token, editor in self._editors.items()
                if editor.active_uses == 0 and token != protected_token
            ]
            if not candidates:
                return
            oldest, _editor = min(candidates, key=lambda item: item[1].last_used)
            del self._editors[oldest]

    def _invalidate_editor_sessions_locked(self) -> None:
        for token, editor in list(self._editors.items()):
            if editor.active_uses:
                editor.invalidated = True
            else:
                del self._editors[token]

    @staticmethod
    @contextmanager
    def _acquire_file_lock(key: _FileLockKey) -> Iterator[None]:
        with _file_locks_guard:
            entry = _file_locks.get(key)
            if entry is None:
                entry = _FileLockEntry(threading.Lock())
                _file_locks[key] = entry
            entry.users += 1
        acquired = False
        try:
            entry.lock.acquire()
            acquired = True
            yield
        finally:
            if acquired:
                entry.lock.release()
            with _file_locks_guard:
                entry.users -= 1
                if entry.users == 0 and _file_locks.get(key) is entry:
                    del _file_locks[key]

    @staticmethod
    def _file_lock_key(
        directory_identity: tuple[int, int],
        directory: Path,
        filename: str,
    ) -> _FileLockKey:
        absolute_path = os.path.abspath(os.path.join(os.fspath(directory), filename))
        canonical_path = (
            os.path.normcase(absolute_path) if os.name == "nt" else absolute_path
        )
        return (*directory_identity, canonical_path)

    def _write_bot_atomically(
        self,
        editor: _EditorSession,
        expected_revision: str,
        payload: bytes,
        bot: Bot | LegacyBot,
        anchor: _DirectoryAnchor,
        *,
        failure_code: str = "BOT_SAVE_FAILED",
    ) -> SavedBot:
        temporary_name = f".autoclick-{secrets.token_hex(16)}.tmp"
        descriptor = -1
        replacement_descriptor = -1
        temporary_created = False
        replaced = False
        try:
            descriptor = self._create_temporary_file(temporary_name, anchor)
            temporary_created = True
            self._write_all(descriptor, payload)
            os.fsync(descriptor)
            if os.name == "nt":
                replacement_descriptor = self._create_windows_temporary_file(
                    temporary_name, anchor, create=False
                )
            os.close(descriptor)
            descriptor = -1
            temporary_stat = self._stat_temporary_file(
                replacement_descriptor, temporary_name, anchor
            )
            result: SavedBot = {
                "revision": self._revision(temporary_stat, payload),
                "botRevision": semantic_bot_revision(bot),
                "descriptor": self._make_descriptor(
                    editor.entry_id,
                    editor.filename,
                    bot,
                    temporary_stat,
                    len(payload),
                ),
            }
            with self._commit_revision_guard(
                editor.filename, expected_revision, anchor
            ):
                self._replace_temporary_file(
                    replacement_descriptor, temporary_name, editor.filename, anchor
                )
                replaced = True
            return result
        except BotServiceError:
            raise
        except Exception as error:
            raise BotServiceError(failure_code) from error
        finally:
            if temporary_created and not replaced:
                cleanup_descriptor = (
                    descriptor if descriptor >= 0 else replacement_descriptor
                )
                try:
                    self._delete_temporary_file(
                        cleanup_descriptor, temporary_name, anchor
                    )
                except OSError:
                    pass
            if descriptor >= 0:
                try:
                    os.close(descriptor)
                except OSError:
                    pass
            if replacement_descriptor >= 0:
                try:
                    os.close(replacement_descriptor)
                except OSError:
                    # Replacement is the commit point; close errors cannot turn a committed save
                    # into a reported failure that callers might retry as though it were unchanged.
                    pass

    @staticmethod
    def _stat_temporary_file(
        descriptor: int, filename: str, anchor: _DirectoryAnchor
    ) -> os.stat_result:
        if os.name == "nt":
            return os.fstat(descriptor)
        if anchor.descriptor is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable", filename)
        return os.stat(filename, dir_fd=anchor.descriptor, follow_symlinks=False)

    @classmethod
    @contextmanager
    def _commit_revision_guard(
        cls,
        filename: str,
        expected_revision: str,
        anchor: _DirectoryAnchor,
    ) -> Iterator[None]:
        try:
            descriptor = cls._open_file_for_commit(filename, anchor)
        except OSError as error:
            raise BotServiceError("BOT_CHANGED_EXTERNALLY") from error
        locked = False
        try:
            try:
                cls._lock_for_commit(descriptor)
                raw_data, file_stat = cls._read_open_file(descriptor)
            except (OSError, ValueError) as error:
                raise BotServiceError("BOT_CHANGED_EXTERNALLY") from error
            locked = True
            if cls._revision(file_stat, raw_data) != expected_revision:
                raise BotServiceError("BOT_CHANGED_EXTERNALLY")
            # The verified source descriptor and guard stay alive through replacement.
            # Windows permits snapshots by readers, denies content writers and allows delete
            # sharing for our rename; POSIX flock cannot stop an uncooperative writer.
            # Neither API offers absolute compare-and-swap against an arbitrary,
            # noncooperative pathname replacement. The final rename syscall is therefore
            # an unavoidable race, while AutoClick concurrency and ordinary changes made
            # before this point remain detected.
            yield
        finally:
            if locked:
                try:
                    cls._unlock_after_commit(descriptor)
                except OSError:
                    pass
            try:
                os.close(descriptor)
            except OSError:
                pass

    @staticmethod
    def _lock_for_commit(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            # The commit opener denies FILE_SHARE_WRITE while retaining
            # FILE_SHARE_DELETE, which protects content without blocking rename.
            return

        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)

    @staticmethod
    def _unlock_after_commit(descriptor: int) -> None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        if os.name == "nt":
            return

        import fcntl

        fcntl.flock(descriptor, fcntl.LOCK_UN)

    @staticmethod
    def _write_all(descriptor: int, payload: bytes) -> None:
        offset = 0
        while offset < len(payload):
            written = os.write(descriptor, payload[offset:])
            if written <= 0:
                raise OSError(errno.EIO, "failed to write bot file")
            offset += written

    @staticmethod
    def _revision(file_stat: os.stat_result, raw_data: bytes) -> str:
        identity = f"{file_stat.st_dev}:{file_stat.st_ino}:".encode("ascii")
        return hashlib.sha256(identity + raw_data).hexdigest()

    @staticmethod
    def _directory_identity(anchor: _DirectoryAnchor) -> tuple[int, int]:
        if os.name != "nt":
            if anchor.descriptor is None:
                raise OSError(errno.ENOTSUP, "directory identity is unavailable")
            directory_stat = os.fstat(anchor.descriptor)
            return directory_stat.st_dev, directory_stat.st_ino

        import ctypes
        from ctypes import wintypes

        if anchor.windows_handle is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable")

        class ByHandleFileInformation(ctypes.Structure):
            _fields_ = [
                ("file_attributes", wintypes.DWORD),
                ("creation_time", wintypes.FILETIME),
                ("last_access_time", wintypes.FILETIME),
                ("last_write_time", wintypes.FILETIME),
                ("volume_serial_number", wintypes.DWORD),
                ("file_size_high", wintypes.DWORD),
                ("file_size_low", wintypes.DWORD),
                ("number_of_links", wintypes.DWORD),
                ("file_index_high", wintypes.DWORD),
                ("file_index_low", wintypes.DWORD),
            ]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_file_information = kernel32.GetFileInformationByHandle
        get_file_information.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(ByHandleFileInformation),
        ]
        get_file_information.restype = wintypes.BOOL
        information = ByHandleFileInformation()
        if not get_file_information(anchor.windows_handle, ctypes.byref(information)):
            error = ctypes.get_last_error()
            raise OSError(error, ctypes.FormatError(error))
        file_index = (information.file_index_high << 32) | information.file_index_low
        return information.volume_serial_number, file_index

    @staticmethod
    def _create_temporary_file(filename: str, anchor: _DirectoryAnchor) -> int:
        if os.name == "nt":
            return BotService._create_windows_temporary_file(filename, anchor)
        if anchor.descriptor is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable", filename)
        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None:
            raise OSError(errno.ENOTSUP, "no-follow file creation is unavailable", filename)
        return os.open(
            filename,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | no_follow
            | getattr(os, "O_BINARY", 0),
            0o600,
            dir_fd=anchor.descriptor,
        )

    @staticmethod
    def _replace_temporary_file(
        descriptor: int,
        temporary_name: str,
        destination_name: str,
        anchor: _DirectoryAnchor,
    ) -> None:
        if os.name == "nt":
            BotService._replace_windows_file(descriptor, destination_name, anchor)
            return
        if anchor.descriptor is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable")
        os.replace(
            temporary_name,
            destination_name,
            src_dir_fd=anchor.descriptor,
            dst_dir_fd=anchor.descriptor,
        )
        try:
            os.fsync(anchor.descriptor)
        except OSError:
            # Rename already committed; a directory-sync failure must not invite a retry.
            pass

    @staticmethod
    def _delete_temporary_file(
        descriptor: int,
        temporary_name: str,
        anchor: _DirectoryAnchor,
    ) -> None:
        if os.name == "nt":
            BotService._delete_open_windows_file(descriptor)
            return
        if anchor.descriptor is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable")
        os.unlink(temporary_name, dir_fd=anchor.descriptor)

    @staticmethod
    def _create_windows_temporary_file(
        filename: str, anchor: _DirectoryAnchor, create: bool = True
    ) -> int:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        file_write_data = 0x00000002
        file_read_attributes = 0x00000080
        delete = 0x00010000
        synchronize = 0x00100000
        share_read_write_delete = 0x00000007
        file_open = 0x00000001
        file_create = 0x00000002
        file_non_directory_file = 0x00000040
        file_synchronous_io_nonalert = 0x00000020
        file_open_reparse_point = 0x00200000
        file_attribute_normal = 0x00000080
        obj_case_insensitive = 0x00000040

        if anchor.windows_handle is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable", filename)

        class UnicodeString(ctypes.Structure):
            _fields_ = [
                ("length", wintypes.USHORT),
                ("maximum_length", wintypes.USHORT),
                ("buffer", wintypes.LPWSTR),
            ]

        class ObjectAttributes(ctypes.Structure):
            _fields_ = [
                ("length", wintypes.ULONG),
                ("root_directory", wintypes.HANDLE),
                ("object_name", ctypes.POINTER(UnicodeString)),
                ("attributes", wintypes.ULONG),
                ("security_descriptor", wintypes.LPVOID),
                ("security_quality_of_service", wintypes.LPVOID),
            ]

        class IoStatusBlock(ctypes.Structure):
            _fields_ = [("status", wintypes.LPVOID), ("information", ctypes.c_size_t)]

        ntdll = ctypes.WinDLL("ntdll")
        nt_create_file = ntdll.NtCreateFile
        nt_create_file.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(ObjectAttributes),
            ctypes.POINTER(IoStatusBlock),
            ctypes.POINTER(ctypes.c_longlong),
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
        ]
        nt_create_file.restype = wintypes.LONG
        filename_buffer = ctypes.create_unicode_buffer(filename)
        filename_length = len(filename.encode("utf-16-le"))
        object_name = UnicodeString(
            filename_length,
            ctypes.sizeof(filename_buffer),
            ctypes.cast(filename_buffer, wintypes.LPWSTR),
        )
        object_attributes = ObjectAttributes(
            ctypes.sizeof(ObjectAttributes),
            anchor.windows_handle,
            ctypes.pointer(object_name),
            obj_case_insensitive,
            None,
            None,
        )
        io_status = IoStatusBlock()
        handle = wintypes.HANDLE()
        status = nt_create_file(
            ctypes.byref(handle),
            (file_write_data if create else 0) | file_read_attributes | delete | synchronize,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            file_attribute_normal,
            share_read_write_delete,
            file_create if create else file_open,
            file_non_directory_file | file_synchronous_io_nonalert | file_open_reparse_point,
            None,
            0,
        )
        if status < 0:
            rtl_status_to_error = ntdll.RtlNtStatusToDosError
            rtl_status_to_error.argtypes = [wintypes.LONG]
            rtl_status_to_error.restype = wintypes.ULONG
            error = rtl_status_to_error(status)
            raise OSError(0, ctypes.FormatError(error), filename, error)
        try:
            try:
                descriptor = msvcrt.open_osfhandle(
                    handle.value,
                    (os.O_WRONLY if create else os.O_RDONLY)
                    | getattr(os, "O_BINARY", 0),
                )
            except BaseException:
                BotService._delete_windows_handle(handle.value)
                raise
            handle = wintypes.HANDLE()
            return descriptor
        finally:
            if handle.value is not None:
                BotService._close_windows_handle(handle.value)

    @staticmethod
    def _replace_windows_file(
        descriptor: int, destination_name: str, anchor: _DirectoryAnchor
    ) -> None:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        file_rename_information_ex = 65
        file_rename_replace_if_exists = 0x00000001
        file_rename_posix_semantics = 0x00000002
        if anchor.windows_handle is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable")
        filename_bytes = destination_name.encode("utf-16-le")

        class IoStatusBlock(ctypes.Structure):
            _fields_ = [("status", wintypes.LPVOID), ("information", ctypes.c_size_t)]

        class FileRenameInformationEx(ctypes.Structure):
            _fields_ = [
                ("flags", wintypes.DWORD),
                ("root_directory", wintypes.HANDLE),
                ("file_name_length", wintypes.DWORD),
                ("file_name", ctypes.c_ubyte * len(filename_bytes)),
            ]

        information = FileRenameInformationEx()
        information.flags = file_rename_replace_if_exists | file_rename_posix_semantics
        information.root_directory = anchor.windows_handle
        information.file_name_length = len(filename_bytes)
        ctypes.memmove(
            ctypes.addressof(information) + FileRenameInformationEx.file_name.offset,
            filename_bytes,
            len(filename_bytes),
        )
        io_status = IoStatusBlock()
        ntdll = ctypes.WinDLL("ntdll")
        nt_set_information = ntdll.NtSetInformationFile
        nt_set_information.argtypes = [
            wintypes.HANDLE,
            ctypes.POINTER(IoStatusBlock),
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.c_int,
        ]
        nt_set_information.restype = wintypes.LONG
        status = nt_set_information(
            msvcrt.get_osfhandle(descriptor),
            ctypes.byref(io_status),
            ctypes.byref(information),
            ctypes.sizeof(information),
            file_rename_information_ex,
        )
        if status < 0:
            rtl_status_to_error = ntdll.RtlNtStatusToDosError
            rtl_status_to_error.argtypes = [wintypes.LONG]
            rtl_status_to_error.restype = wintypes.ULONG
            error = rtl_status_to_error(status)
            raise OSError(error, ctypes.FormatError(error), destination_name)

    @staticmethod
    def _delete_open_windows_file(descriptor: int) -> None:
        import msvcrt

        BotService._delete_windows_handle(msvcrt.get_osfhandle(descriptor))

    @staticmethod
    def _delete_windows_handle(handle: int) -> None:
        import ctypes
        from ctypes import wintypes

        file_disposition_info = 4

        class FileDispositionInfo(ctypes.Structure):
            _fields_ = [("delete_file", wintypes.BOOL)]

        information = FileDispositionInfo(True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        set_file_information = kernel32.SetFileInformationByHandle
        set_file_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        set_file_information.restype = wintypes.BOOL
        if not set_file_information(
            handle,
            file_disposition_info,
            ctypes.byref(information),
            ctypes.sizeof(information),
        ):
            error = ctypes.get_last_error()
            raise OSError(error, ctypes.FormatError(error))

    @staticmethod
    def _open_file_no_follow(filename: str, anchor: _DirectoryAnchor | None = None) -> int:
        if (
            not filename
            or filename in {".", ".."}
            or os.path.basename(filename) != filename
            or "/" in filename
            or "\\" in filename
            or (os.name == "nt" and ":" in filename)
        ):
            raise OSError(errno.EINVAL, "bot filename must be one relative component", filename)
        if os.name == "nt":
            return BotService._open_windows_no_follow(filename, anchor)

        no_follow = getattr(os, "O_NOFOLLOW", None)
        if no_follow is None or anchor is None or anchor.descriptor is None:
            raise OSError(errno.ENOTSUP, "no-follow file opening is unavailable", filename)
        return os.open(
            filename,
            os.O_RDONLY | no_follow | getattr(os, "O_BINARY", 0),
            dir_fd=anchor.descriptor,
        )

    @staticmethod
    def _open_file_for_commit(filename: str, anchor: _DirectoryAnchor) -> int:
        if os.name == "nt":
            # FILE_SHARE_READ | FILE_SHARE_DELETE: a read-only snapshot must not
            # look like an external edit, while write access stays excluded.
            return BotService._open_windows_relative_no_follow(filename, anchor, 0x00000005)
        return BotService._open_file_no_follow(filename, anchor)

    @staticmethod
    def _open_windows_no_follow(
        filename: str, anchor: _DirectoryAnchor | None = None
    ) -> int:
        return BotService._open_windows_relative_no_follow(filename, anchor, 0x00000007)

    @staticmethod
    def _open_windows_relative_no_follow(
        filename: str,
        anchor: _DirectoryAnchor | None,
        share_mode: int,
    ) -> int:
        import ctypes
        import msvcrt
        from ctypes import wintypes

        file_read_data = 0x00000001
        file_read_attributes = 0x00000080
        synchronize = 0x00100000
        file_open = 0x00000001
        file_non_directory_file = 0x00000040
        file_synchronous_io_nonalert = 0x00000020
        file_open_reparse_point = 0x00200000
        file_attribute_tag_info = 9
        file_attribute_directory = 0x00000010
        obj_case_insensitive = 0x00000040

        if anchor is None or anchor.windows_handle is None:
            raise OSError(errno.ENOTSUP, "directory identity is unavailable", filename)

        class UnicodeString(ctypes.Structure):
            _fields_ = [
                ("length", wintypes.USHORT),
                ("maximum_length", wintypes.USHORT),
                ("buffer", wintypes.LPWSTR),
            ]

        class ObjectAttributes(ctypes.Structure):
            _fields_ = [
                ("length", wintypes.ULONG),
                ("root_directory", wintypes.HANDLE),
                ("object_name", ctypes.POINTER(UnicodeString)),
                ("attributes", wintypes.ULONG),
                ("security_descriptor", wintypes.LPVOID),
                ("security_quality_of_service", wintypes.LPVOID),
            ]

        class IoStatusBlock(ctypes.Structure):
            _fields_ = [
                ("status", wintypes.LPVOID),
                ("information", ctypes.c_size_t),
            ]

        class FileAttributeTagInfo(ctypes.Structure):
            _fields_ = [
                ("file_attributes", wintypes.DWORD),
                ("reparse_tag", wintypes.DWORD),
            ]

        ntdll = ctypes.WinDLL("ntdll")
        nt_create_file = ntdll.NtCreateFile
        nt_create_file.argtypes = [
            ctypes.POINTER(wintypes.HANDLE),
            wintypes.DWORD,
            ctypes.POINTER(ObjectAttributes),
            ctypes.POINTER(IoStatusBlock),
            ctypes.POINTER(ctypes.c_longlong),
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.ULONG,
            wintypes.LPVOID,
            wintypes.ULONG,
        ]
        nt_create_file.restype = wintypes.LONG

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        get_file_information = kernel32.GetFileInformationByHandleEx
        get_file_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        get_file_information.restype = wintypes.BOOL
        close_handle = kernel32.CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL

        filename_buffer = ctypes.create_unicode_buffer(filename)
        filename_length = len(filename.encode("utf-16-le"))
        object_name = UnicodeString(
            filename_length,
            ctypes.sizeof(filename_buffer),
            ctypes.cast(filename_buffer, wintypes.LPWSTR),
        )
        object_attributes = ObjectAttributes(
            ctypes.sizeof(ObjectAttributes),
            anchor.windows_handle,
            ctypes.pointer(object_name),
            obj_case_insensitive,
            None,
            None,
        )
        io_status = IoStatusBlock()
        handle = wintypes.HANDLE()
        status = nt_create_file(
            ctypes.byref(handle),
            file_read_data | file_read_attributes | synchronize,
            ctypes.byref(object_attributes),
            ctypes.byref(io_status),
            None,
            0,
            share_mode,
            file_open,
            file_non_directory_file | file_synchronous_io_nonalert | file_open_reparse_point,
            None,
            0,
        )
        if status < 0:
            rtl_status_to_error = ntdll.RtlNtStatusToDosError
            rtl_status_to_error.argtypes = [wintypes.LONG]
            rtl_status_to_error.restype = wintypes.ULONG
            error = rtl_status_to_error(status)
            raise OSError(0, ctypes.FormatError(error), filename, error)

        try:
            attribute_info = FileAttributeTagInfo()
            if not get_file_information(
                handle,
                file_attribute_tag_info,
                ctypes.byref(attribute_info),
                ctypes.sizeof(attribute_info),
            ):
                error = ctypes.get_last_error()
                raise OSError(0, ctypes.FormatError(error), filename, error)
            if attribute_info.file_attributes & _REPARSE_POINT_ATTRIBUTE:
                raise OSError(errno.ELOOP, "reparse-point bot files are not allowed", filename)
            if attribute_info.file_attributes & file_attribute_directory:
                raise OSError(errno.EISDIR, "bot file is not a regular file", filename)

            descriptor = msvcrt.open_osfhandle(
                handle.value,
                os.O_RDONLY | getattr(os, "O_BINARY", 0),
            )
            handle = wintypes.HANDLE()
            return descriptor
        finally:
            if handle.value is not None:
                close_handle(handle)

    @staticmethod
    @contextmanager
    def _open_directory_anchor(path: Path) -> Iterator[_DirectoryAnchor]:
        if os.name == "nt":
            handle = BotService._open_windows_directory(path)
            try:
                yield _DirectoryAnchor(
                    scan_target=path,
                    windows_handle=handle,
                )
            finally:
                BotService._close_windows_handle(handle)
            return

        no_follow = getattr(os, "O_NOFOLLOW", None)
        directory_flag = getattr(os, "O_DIRECTORY", None)
        if no_follow is None or directory_flag is None:
            raise OSError(errno.ENOTSUP, "anchored directory opening is unavailable", str(path))
        descriptor = os.open(path, os.O_RDONLY | no_follow | directory_flag)
        try:
            directory_stat = os.fstat(descriptor)
            if not stat.S_ISDIR(directory_stat.st_mode):
                raise NotADirectoryError(str(path))
            yield _DirectoryAnchor(scan_target=descriptor, descriptor=descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _open_windows_directory(path: Path) -> int:
        import ctypes
        from ctypes import wintypes

        file_read_attributes = 0x00000080
        share_read_write_delete = 0x00000007
        open_existing = 3
        file_flag_backup_semantics = 0x02000000
        file_flag_open_reparse_point = 0x00200000
        file_attribute_tag_info = 9
        file_case_sensitive_info = 23
        file_attribute_directory = 0x00000010
        file_cs_flag_case_sensitive_dir = 0x00000001
        invalid_handle_value = ctypes.c_void_p(-1).value

        class FileAttributeTagInfo(ctypes.Structure):
            _fields_ = [
                ("file_attributes", wintypes.DWORD),
                ("reparse_tag", wintypes.DWORD),
            ]

        class FileCaseSensitiveInfo(ctypes.Structure):
            _fields_ = [("flags", wintypes.ULONG)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        create_file = kernel32.CreateFileW
        create_file.argtypes = [
            wintypes.LPCWSTR,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            wintypes.DWORD,
            wintypes.HANDLE,
        ]
        create_file.restype = wintypes.HANDLE
        get_file_information = kernel32.GetFileInformationByHandleEx
        get_file_information.argtypes = [
            wintypes.HANDLE,
            ctypes.c_int,
            wintypes.LPVOID,
            wintypes.DWORD,
        ]
        get_file_information.restype = wintypes.BOOL

        handle = create_file(
            str(path),
            file_read_attributes,
            share_read_write_delete,
            None,
            open_existing,
            file_flag_backup_semantics | file_flag_open_reparse_point,
            None,
        )
        if handle == invalid_handle_value:
            error = ctypes.get_last_error()
            raise OSError(error, ctypes.FormatError(error), str(path))

        try:
            attribute_info = FileAttributeTagInfo()
            if not get_file_information(
                handle,
                file_attribute_tag_info,
                ctypes.byref(attribute_info),
                ctypes.sizeof(attribute_info),
            ):
                error = ctypes.get_last_error()
                raise OSError(error, ctypes.FormatError(error), str(path))
            if attribute_info.file_attributes & _REPARSE_POINT_ATTRIBUTE:
                raise OSError(errno.ELOOP, "reparse-point directories are not allowed", str(path))
            if not attribute_info.file_attributes & file_attribute_directory:
                raise NotADirectoryError(str(path))
            case_sensitive_info = FileCaseSensitiveInfo()
            if not get_file_information(
                handle,
                file_case_sensitive_info,
                ctypes.byref(case_sensitive_info),
                ctypes.sizeof(case_sensitive_info),
            ):
                error = ctypes.get_last_error()
                raise OSError(error, ctypes.FormatError(error), str(path))
            if case_sensitive_info.flags & file_cs_flag_case_sensitive_dir:
                raise OSError(
                    errno.ENOTSUP,
                    "case-sensitive directories are not supported",
                    str(path),
                )
            return handle
        except BaseException:
            BotService._close_windows_handle(handle)
            raise

    @staticmethod
    def _close_windows_handle(handle: int) -> None:
        import ctypes
        from ctypes import wintypes

        close_handle = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
        close_handle.argtypes = [wintypes.HANDLE]
        close_handle.restype = wintypes.BOOL
        close_handle(handle)

    @staticmethod
    def _is_reparse_point(file_stat: os.stat_result) -> bool:
        attributes = getattr(file_stat, "st_file_attributes", 0)
        return bool(attributes & _REPARSE_POINT_ATTRIBUTE)

    @staticmethod
    def _reject_json_constant(value: str) -> None:
        raise ValueError(f"invalid JSON constant: {value}")
