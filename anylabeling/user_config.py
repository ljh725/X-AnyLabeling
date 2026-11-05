"""Deterministic storage for the global user configuration.

The module owns three things that used to be implicit in
:mod:`anylabeling.config`:

* the canonical persistence target for the current process,
* the in-process committed view shared by every settings entry, and
* a field-level transaction that merges concurrent writes instead of
  replacing the whole file with a stale snapshot.

Only fields a caller explicitly submits are written.  A save re-reads the
target under a cross-process lock, compares the caller's editing baseline
with the latest committed value and the proposed value, and either merges
or reports a conflict.  Replacement is atomic and the previous valid
document is retained as ``<config>.bak``.

The module requires PyQt6 because :class:`~PyQt6.QtCore.QLockFile` is the
cross-process primitive already shipped with the project.  ``config.py``
therefore imports this module lazily so that pure ``normalize_user_config``
callers keep working without PyQt installed.
"""

from __future__ import annotations

import copy
import hashlib
import os
import os.path as osp
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Sequence

import yaml
from PyQt6 import QtCore

from anylabeling.views.labeling.logger import logger

DEFAULT_CONFIG_FILENAME = ".xanylabelingrc"
LEGACY_CONFIG_FILENAME = ".anylabelingrc"
BACKUP_SUFFIX = ".bak"
LOCK_SUFFIX = ".lock"

#: Environment override used by tests and tools so that no verification
#: run can fall back to the real user configuration.
CONFIG_PATH_ENV = "XANYLABELING_CONFIG_FILE"

DEFAULT_LOCK_WAIT_MS = 2000
LOCK_STALE_MS = 30000

#: Legacy top-level keys mapped onto their nested replacement.
LEGACY_TOP_LEVEL_KEYS = {
    "epsilon": "canvas.epsilon",
    "show_cross_line": "canvas.crosshair.show",
}
LEGACY_DROP_KEYS = frozenset({"ui"})
LEGACY_SHORTCUT_ALIASES = {
    "shortcuts.open_classifier": "shortcuts.open_image_classifier",
}

_MISSING = object()


class _DeleteToken:
    __slots__ = ()

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return "DELETE"

    def __copy__(self):
        return self

    def __deepcopy__(self, memo):
        # Patches deep-copy their values; the sentinel must stay identical or
        # "this field did not exist" would compare as an unknown value.
        return self


#: Sentinel accepted by :class:`ConfigPatch` to remove a field explicitly.
DELETE = _DeleteToken()


class ConfigError(Exception):
    """Base class for a user-configuration failure."""

    code = "config-error"
    retryable = False

    def __init__(self, message: str, *, path: str | None = None):
        super().__init__(message)
        self.message = message
        self.path = path

    @property
    def conflict_keys(self) -> list[str]:
        """Fields that made the transaction a conflict (empty otherwise).

        Every entry point (settings dialog, digit manager, model manager)
        reads this one property, so a conflict is reported the same way no
        matter which error class carries it.
        """

        return []


class ConfigLockBusy(ConfigError):
    """Another process holds the configuration lock."""

    code = "lock-busy"
    retryable = True


class ConfigConflict(ConfigError):
    """At least one submitted field changed since the editing baseline."""

    code = "conflict"

    def __init__(
        self,
        conflicts: Sequence[Any],
        *,
        path: str | None = None,
        message: str | None = None,
    ):
        keys = list(dict.fromkeys(_format_key(item) for item in conflicts))
        self.conflicts = keys
        super().__init__(
            message
            or (
                "Configuration was changed by another entry for: "
                + ", ".join(keys)
            ),
            path=path,
        )

    @property
    def conflict_keys(self) -> list[str]:
        return list(self.conflicts)


class ConfigExternalChange(ConfigConflict):
    """The document changed between the locked re-read and the replacement.

    A non-cooperating editor is not bound by :class:`~PyQt6.QtCore.QLockFile`,
    so the fingerprint is checked again right before the file is replaced.
    The save is refused instead of overwriting the newer content.
    """

    code = "external-change"
    retryable = True


class ConfigInvalid(ConfigError):
    """The existing document is unreadable, malformed or incompatible."""

    code = "invalid-config"


class ConfigWriteError(ConfigError):
    """Serialization or file replacement failed."""

    code = "write-failed"
    retryable = True


@dataclass
class SaveResult:
    """Outcome of one successful transaction."""

    path: str
    written_keys: list[str]
    backup_path: str | None = None
    created: bool = False
    changed: bool = False


def _format_key(key: Any) -> str:
    if isinstance(key, (tuple, list)):
        return ".".join(str(part) for part in key)
    return str(key)


def _path_segments(key: Any) -> tuple:
    if isinstance(key, (tuple, list)):
        segments = tuple(key)
    else:
        segments = tuple(str(key).split("."))
    if not segments or any(segment == "" for segment in segments):
        raise ConfigError(f"Invalid configuration field: {_format_key(key)}")
    return segments


def _lookup(data: Any, key: Any) -> Any:
    current = data
    for segment in _path_segments(key):
        if not isinstance(current, dict):
            return _MISSING
        if segment in current:
            current = current[segment]
            continue
        # YAML may have loaded a quoted digit key as a string.
        if isinstance(segment, int) and str(segment) in current:
            current = current[str(segment)]
            continue
        return _MISSING
    return current


def _set_value(data: dict, key: Any, value: Any) -> None:
    segments = _path_segments(key)
    current = data
    for segment in segments[:-1]:
        node = current.get(segment)
        if node is None and str(segment) in current:
            node = current[str(segment)]
            segment = str(segment)
        if node is None:
            node = {}
            current[segment] = node
        if not isinstance(node, dict):
            raise ConfigInvalid(
                "Configuration field "
                f"'{_format_key(key)}' has a non-mapping parent"
            )
        current = node
    last = segments[-1]
    if last in current:
        current[last] = value
        return
    if isinstance(last, int) and str(last) in current:
        del current[str(last)]
    current[last] = value


def _delete_value(data: dict, key: Any) -> bool:
    segments = _path_segments(key)
    current = data
    for segment in segments[:-1]:
        if not isinstance(current, dict):
            return False
        if segment not in current and str(segment) in current:
            segment = str(segment)
        current = current.get(segment)
        if not isinstance(current, dict):
            return False
    last = segments[-1]
    if last in current:
        del current[last]
        return True
    if isinstance(last, int) and str(last) in current:
        del current[str(last)]
        return True
    return False


def _values_equal(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        if len(left) != len(right):
            return False
        return all(
            _values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    if isinstance(left, dict) and isinstance(right, dict):
        if set(left) != set(right):
            return False
        return all(_values_equal(left[key], right[key]) for key in left)
    return left == right


class ConfigPatch:
    """Field-level configuration change set.

    Keys are dotted paths (``"canvas.epsilon"``) or explicit tuples when a
    segment is not a string (digit shortcut maps use integer keys).  Values
    are the proposed committed values; :data:`DELETE` removes a field.

    ``baselines`` optionally carries the value each field had when the caller
    started editing.  Comparing that draft baseline (instead of the last
    value this process happened to read) is what keeps an old draft from
    silently replacing a newer value written by another entry.
    """

    def __init__(
        self,
        values: Mapping[Any, Any] | None = None,
        deletes: Iterable[Any] | None = None,
        baselines: Mapping[Any, Any] | None = None,
    ):
        self._values: dict[Any, Any] = {}
        self._deletes: list[Any] = []
        self._baselines: dict[Any, Any] = {}
        for key, value in (values or {}).items():
            if value is DELETE:
                self.delete(key)
            else:
                self.set(key, value)
        for key in deletes or ():
            self.delete(key)
        for key, value in (baselines or {}).items():
            self.set_baseline(key, value)

    def set(self, key: Any, value: Any) -> "ConfigPatch":
        _path_segments(key)
        if key in self._deletes:
            self._deletes = [item for item in self._deletes if item != key]
        self._values[key] = copy.deepcopy(value)
        return self

    def delete(self, key: Any) -> "ConfigPatch":
        _path_segments(key)
        self._values.pop(key, None)
        if key not in self._deletes:
            self._deletes.append(key)
        return self

    def set_baseline(self, key: Any, value: Any) -> "ConfigPatch":
        """Record the draft baseline of ``key``.

        :data:`DELETE` states that the field did not exist when the draft
        started; :data:`_MISSING` clears an explicit baseline again.
        """

        _path_segments(key)
        if value is _MISSING:
            self._baselines.pop(key, None)
            return self
        self._baselines[key] = copy.deepcopy(value)
        return self

    def baseline_for(self, key: Any) -> Any:
        return self._baselines.get(key, _MISSING)

    @property
    def values(self) -> dict[Any, Any]:
        return dict(self._values)

    @property
    def deletes(self) -> list[Any]:
        return list(self._deletes)

    @property
    def baselines(self) -> dict[Any, Any]:
        return dict(self._baselines)

    def merge(self, other: "ConfigPatch") -> "ConfigPatch":
        """Fold another patch into this one (later entries win)."""

        for key, value in other._values.items():
            self.set(key, value)
        for key in other._deletes:
            self.delete(key)
        for key, value in other._baselines.items():
            self.set_baseline(key, value)
        return self

    def keys(self) -> list[Any]:
        keys = list(self._values.keys())
        keys.extend(key for key in self._deletes if key not in self._values)
        return keys

    def is_empty(self) -> bool:
        return not self._values and not self._deletes

    def __len__(self) -> int:
        return len(self._values) + len(self._deletes)

    def __bool__(self) -> bool:
        return bool(len(self))

    def __iter__(self):
        return iter(self.keys())

    def __contains__(self, key: Any) -> bool:
        return key in self._values or key in self._deletes

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return (
            f"ConfigPatch(values={self._values!r}, "
            f"deletes={self._deletes!r})"
        )


# ---------------------------------------------------------------------------
# Paths, documents and atomic files
# ---------------------------------------------------------------------------


def file_fingerprint(path: str | None) -> str | None:
    """Return the SHA-256 of ``path`` or ``None`` when it does not exist."""

    if not path:
        return None
    try:
        with open(path, "rb") as handle:
            payload = handle.read()
    except FileNotFoundError:
        return None
    except OSError:
        return None
    return hashlib.sha256(payload).hexdigest()


def backup_path_for(path: str) -> str:
    return path + BACKUP_SUFFIX


def default_config_path(work_directory: str) -> str:
    return osp.abspath(osp.join(work_directory, DEFAULT_CONFIG_FILENAME))


def legacy_config_path(work_directory: str) -> str:
    return osp.abspath(osp.join(work_directory, LEGACY_CONFIG_FILENAME))


def _is_inline_yaml(value: str) -> bool:
    if "\n" in value:
        return True
    try:
        parsed = yaml.safe_load(value)
    except yaml.YAMLError:
        return False
    return isinstance(parsed, dict)


def resolve_config_target(
    config_value: str | None,
    work_directory: str,
) -> tuple[str, str]:
    """Resolve the canonical persistence target for this process.

    Returns ``(path, origin)`` where origin is one of ``file``, ``inline``,
    ``env``, ``default`` or ``work-dir``.  The path is absolute so that a
    later working-directory change cannot redirect a save.
    """

    env_override = os.environ.get(CONFIG_PATH_ENV)
    default_path = default_config_path(work_directory)
    if config_value:
        if not _is_inline_yaml(config_value):
            resolved = osp.abspath(osp.expanduser(config_value))
            origin = (
                "default"
                if osp.normcase(resolved) == osp.normcase(default_path)
                else "file"
            )
            return resolved, origin
        return default_path, "inline"
    if env_override:
        return osp.abspath(osp.expanduser(env_override)), "env"
    return default_path, "default"


def read_config_document(path: str) -> tuple[dict | None, bytes | None]:
    """Read and validate the YAML document stored at ``path``.

    Returns ``(data, payload)``.  ``(None, None)`` means the file does not
    exist.  A file that exists but cannot be parsed as a top-level mapping
    raises :class:`ConfigInvalid`; an empty file is treated as an empty
    mapping because it holds no user data worth protecting.
    """

    if not path:
        return None, None
    try:
        with open(path, "rb") as handle:
            payload = handle.read()
    except FileNotFoundError:
        return None, None
    except OSError as error:
        raise ConfigInvalid(
            f"Cannot read configuration file: {error}",
            path=path,
        ) from error
    if not payload.strip():
        return {}, payload
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise ConfigInvalid(
            "Configuration file is not valid UTF-8 text",
            path=path,
        ) from error
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise ConfigInvalid(
            f"Configuration file is not valid YAML: {error}",
            path=path,
        ) from error
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigInvalid(
            "Configuration file must contain a top-level mapping",
            path=path,
        )
    return data, payload


def _dump_document(data: Mapping[str, Any]) -> bytes:
    try:
        text = yaml.safe_dump(
            data,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    except Exception as error:  # noqa: BLE001 - normalize serializer failures
        raise ConfigWriteError(
            f"Cannot serialize the configuration: {error}"
        ) from error
    return text.encode("utf-8")


def _verify_document(data: Mapping[str, Any], payload: bytes) -> None:
    try:
        parsed = yaml.safe_load(payload.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as error:
        raise ConfigWriteError(
            f"Serialized configuration is not readable YAML: {error}"
        ) from error
    if not isinstance(parsed, dict) or not _values_equal(parsed, data):
        raise ConfigWriteError(
            "Serialized configuration did not survive a YAML round-trip"
        )


def _fsync_directory(directory: str) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_bytes(path: str, payload: bytes) -> None:
    """Write ``payload`` to ``path`` through a same-directory replacement.

    Every failure mode - creating the directory, creating the temporary
    file, writing, flushing, fsyncing and the replacement itself - is
    normalized to :class:`ConfigWriteError` so callers only have to handle
    one storage error and the original file is never truncated.
    """

    directory = osp.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        raise ConfigWriteError(
            f"Cannot create configuration directory: {error}",
            path=path,
        ) from error
    prefix = f".{osp.basename(path)}."
    temporary_path = None
    try:
        file_descriptor, temporary_path = tempfile.mkstemp(
            prefix=prefix, suffix=".tmp", dir=directory
        )
        try:
            handle = os.fdopen(file_descriptor, "wb")
        except OSError:
            os.close(file_descriptor)
            raise
        with handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        _fsync_directory(directory)
    except OSError as error:
        raise ConfigWriteError(
            f"Cannot replace configuration file: {error}",
            path=path,
        ) from error
    finally:
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                pass


@contextmanager
def _configuration_lock(path: str, wait_ms: int):
    directory = osp.dirname(path) or "."
    try:
        os.makedirs(directory, exist_ok=True)
    except OSError as error:
        raise ConfigWriteError(
            f"Cannot create configuration directory: {error}",
            path=path,
        ) from error
    lock = QtCore.QLockFile(path + LOCK_SUFFIX)
    lock.setStaleLockTime(LOCK_STALE_MS)
    if not lock.tryLock(max(0, int(wait_ms))):
        raise ConfigLockBusy(
            "Another X-AnyLabeling instance is writing the configuration; "
            "retry in a moment.",
            path=path,
        )
    try:
        yield
    finally:
        lock.unlock()


# ---------------------------------------------------------------------------
# Session and transaction
# ---------------------------------------------------------------------------


class ConfigSession(QtCore.QObject):
    """Process-wide committed configuration state and its disk baseline."""

    effective_changed = QtCore.pyqtSignal()

    def __init__(
        self,
        *,
        target_path: str | None,
        origin: str,
        template: Mapping[str, Any],
        effective: dict[str, Any],
        disk_data: dict | None,
        disk_error: ConfigError | None = None,
        normalizer: Callable[[dict], dict] | None = None,
        validator: Callable[[dict], None] | None = None,
        overrides: Mapping[Any, Any] | None = None,
    ):
        super().__init__()
        self.target_path = target_path
        self.origin = origin
        self.template = copy.deepcopy(dict(template or {}))
        self.effective = effective
        self.normalizer = normalizer or (lambda value: copy.deepcopy(value))
        self.validator = validator
        #: Transient startup layer (inline YAML / command line).  These paths
        #: stay in the effective view but are never written to the target and
        #: are not refreshed from disk, so a later save cannot solidify them.
        self.overrides: dict[Any, Any] = {
            key: copy.deepcopy(value)
            for key, value in (overrides or {}).items()
        }
        self.disk_error = disk_error
        self.disk_exists = disk_data is not None
        self.disk_data = (
            copy.deepcopy(disk_data) if disk_data is not None else None
        )
        self.baseline = (
            self._normalize(disk_data) if disk_data is not None else {}
        )
        self.fingerprint = (
            file_fingerprint(target_path) if disk_data is not None else None
        )
        self.last_backup_path: str | None = None
        self.last_saved_keys: list[str] = []

    # -- helpers ---------------------------------------------------------

    def _normalize(self, data: dict | None) -> dict:
        if not isinstance(data, dict):
            return {}
        normalized = self.normalizer(copy.deepcopy(data))
        return normalized if isinstance(normalized, dict) else {}

    def _baseline_value(self, key: Any) -> Any:
        return _lookup(self.baseline, key)

    def baseline_value(self, key: Any) -> Any:
        """Value of ``key`` as last committed to disk (normalized)."""

        return self._baseline_value(key)

    def editing_baseline(self, key: Any) -> Any:
        """Capture a persistent value, including absence, for a UI draft.

        Defaults and command-line overrides belong to the displayed view;
        they must never stand in for the field's original value on disk.
        """
        value = self._baseline_value(key)
        return DELETE if value is _MISSING else copy.deepcopy(value)

    def effective_value(self, key: Any) -> Any:
        return _lookup(self.effective, key)

    def _editing_baseline(self, patch: ConfigPatch, key: Any) -> Any:
        """Draft baseline supplied by the caller, else this process's view."""
        baseline = patch.baseline_for(key)
        if baseline is DELETE:
            return _MISSING
        if baseline is _MISSING:
            return self._baseline_value(key)
        return baseline

    def _sync_effective(self, document: Mapping[str, Any] | None) -> None:
        """Adopt every committed field this process did not override.

        A save re-reads the whole document under the lock.  Without this
        step only the submitted fields would reach the effective view, the
        remaining fields would keep an old value while the disk baseline
        moved on, and an old draft could later replace a value another
        entry had written.
        """

        self._replace_effective(document)

    def _replace_effective(self, document: Mapping[str, Any] | None) -> None:
        """Rebuild the effective view from the template and ``document``.

        Used after an explicit backup restore, where fields that the backup
        does not contain must disappear from the live view instead of being
        left behind by an overlay.
        """

        rebuilt = copy.deepcopy(self.template)
        if isinstance(document, Mapping):
            _merge_into(rebuilt, self._normalize(dict(document)))
        for key, value in self.overrides.items():
            try:
                _set_value(rebuilt, key, copy.deepcopy(value))
            except ConfigError:
                logger.warning(
                    "Ignoring incompatible configuration override: %s",
                    _format_key(key),
                )
        _reconcile_mapping(self.effective, rebuilt)

    def _notify_effective_changed(self, before: dict) -> None:
        if not _values_equal(before, self.effective):
            self.effective_changed.emit()

    def _retire_saved_overrides(self, patch: ConfigPatch) -> None:
        # A UI edit supersedes only its own startup override. Keep the other
        # temporary fields out of the file and visible for this process.
        saved = [_path_segments(key) for key in patch.keys()]
        remaining = {}
        for key, value in self.overrides.items():
            prefix = _path_segments(key)
            leaves = (
                _iter_leaf_paths(value, prefix)
                if isinstance(value, dict) and value
                else [(prefix, value)]
            )
            for path, item in leaves:
                if not any(path[: len(field)] == field for field in saved):
                    remaining[path] = copy.deepcopy(item)
        self.overrides = remaining

    def _disk_changed_since_read(self, payload: bytes | None) -> bool:
        try:
            with open(self.target_path, "rb") as handle:
                current = handle.read()
        except FileNotFoundError:
            return payload is not None
        except OSError:
            return False
        return (payload or b"") != current

    @property
    def backup_path(self) -> str | None:
        if not self.target_path:
            return None
        return backup_path_for(self.target_path)

    def has_backup(self) -> bool:
        path = self.backup_path
        return bool(path and osp.isfile(path))

    # -- transaction -----------------------------------------------------

    def save(
        self,
        patch: ConfigPatch | Mapping[Any, Any],
        *,
        wait_ms: int = DEFAULT_LOCK_WAIT_MS,
    ) -> SaveResult:
        if not isinstance(patch, ConfigPatch):
            patch = ConfigPatch(patch)
        path = self.target_path
        if not path:
            raise ConfigError(
                "No configuration target is available for this session; "
                "pass --config or set a working directory."
            )
        if patch.is_empty():
            return SaveResult(path=path, written_keys=[])
        before = copy.deepcopy(self.effective)
        if self.disk_error is not None:
            # The file may have been repaired since it was read at startup.
            # Re-reading keeps a damaged document protected (it still fails
            # to parse) while allowing a deliberate repair to be saved.
            try:
                self.reload()
            except ConfigInvalid as error:
                raise ConfigInvalid(
                    f"{self.disk_error.message} (path: {path})", path=path
                ) from error

        with _configuration_lock(path, wait_ms):
            current_raw, current_payload = read_config_document(path)
            exists = current_raw is not None
            current_normalized = self._normalize(current_raw) if exists else {}
            merged = (
                copy.deepcopy(current_raw)
                if exists
                else copy.deepcopy(self.template)
            )
            _canonicalize_digit_keys(merged)

            conflicts: list[Any] = []
            applied: list[Any] = []
            for key, value in patch.values.items():
                current_value = (
                    _lookup(current_normalized, key) if exists else _MISSING
                )
                baseline_value = self._editing_baseline(patch, key)
                if _values_equal(current_value, value):
                    applied.append(key)
                    continue
                if _values_equal(current_value, baseline_value):
                    _apply_patch_value(merged, key, value)
                    applied.append(key)
                    continue
                conflicts.append(key)

            for key in patch.deletes:
                current_value = (
                    _lookup(current_normalized, key) if exists else _MISSING
                )
                if current_value is _MISSING:
                    applied.append(key)
                    continue
                baseline_value = self._editing_baseline(patch, key)
                if _values_equal(current_value, baseline_value):
                    _delete_patch_value(merged, key)
                    applied.append(key)
                    continue
                conflicts.append(key)

            if conflicts:
                raise ConfigConflict(conflicts, path=path)

            changed = not exists or not _values_equal(merged, current_raw)
            backup_target: str | None = None
            next_payload = current_payload
            if changed:
                next_payload = _dump_document(merged)
                _verify_document(merged, next_payload)
                if self.validator is not None:
                    self.validator(merged)
                # A non-cooperating editor is not bound by the lock file, so
                # the document is compared one last time before it is
                # replaced.  The lock cannot close the window between this
                # check and ``os.replace``; that residual race is a file
                # system limitation, not something a lock can remove.
                if self._disk_changed_since_read(current_payload):
                    raise ConfigExternalChange(
                        [_format_key(key) for key in patch.values]
                        + [_format_key(key) for key in patch.deletes],
                        path=path,
                        message=(
                            "The configuration file was changed by another "
                            "program after it was re-read; nothing was "
                            "written. Reload the latest values and retry."
                        ),
                    )
                if exists and current_payload and current_payload.strip():
                    backup_target = backup_path_for(path)
                    _atomic_write_bytes(backup_target, current_payload)
                _atomic_write_bytes(path, next_payload)

            self.disk_exists = True
            self.disk_data = copy.deepcopy(merged)
            self.baseline = self._normalize(merged)
            self.fingerprint = (
                hashlib.sha256(next_payload).hexdigest()
                if next_payload is not None
                else None
            )
            self.disk_error = None
            self.last_backup_path = backup_target
            self.last_saved_keys = [_format_key(key) for key in applied]
            self._retire_saved_overrides(patch)
            self._sync_effective(self.baseline)

            logger.info(
                "Saved user configuration: %s (%d field(s)%s)",
                path,
                len(applied),
                f", backup {backup_target}" if backup_target else "",
            )
            result = SaveResult(
                path=path,
                written_keys=self.last_saved_keys,
                backup_path=backup_target,
                created=not exists,
                changed=changed,
            )
        # Runtime handlers can themselves submit preferences. Notify after
        # releasing the file lock, with the complete committed view installed.
        self._notify_effective_changed(before)
        return result

    def refresh_from_disk(self) -> bool:
        """Re-read the committed document; return whether it changed."""

        return self.reload()

    def reload(self) -> bool:
        """Re-read the document and adopt it as the committed state.

        Unlike :meth:`save` this never writes: it is the explicit recovery
        path used after a conflict or when another process changed the file.
        The effective view follows the newer document (except transient
        startup overrides) so a reloaded draft starts from real values.
        """

        path = self.target_path
        if not path:
            return False
        data, payload = read_config_document(path)
        before = copy.deepcopy(self.effective)
        fingerprint = (
            hashlib.sha256(payload).hexdigest()
            if payload is not None
            else None
        )
        if data is None:
            changed = self.disk_exists or bool(self.baseline)
            self.disk_exists = False
            self.disk_data = None
            self.baseline = {}
            self.fingerprint = None
            self.disk_error = None
            self._sync_effective(None)
            self._notify_effective_changed(before)
            return changed
        if fingerprint == self.fingerprint and self.disk_error is None:
            self.disk_exists = True
            self.disk_data = copy.deepcopy(data)
            self.baseline = self._normalize(data)
            return False
        self.disk_exists = True
        self.disk_data = copy.deepcopy(data)
        self.baseline = self._normalize(data)
        self.fingerprint = fingerprint
        self.disk_error = None
        self._sync_effective(self.baseline)
        self._notify_effective_changed(before)
        return True


def _apply_patch_value(document: dict, key: Any, value: Any) -> None:
    for alias in _legacy_aliases_for(key):
        _delete_value(document, alias)
    _set_value(document, key, copy.deepcopy(value))


def _canonicalize_digit_keys(document: dict) -> None:
    """Keep digit shortcut map keys numeric in the stored document."""
    digits = document.get("digit_shortcuts")
    if not isinstance(digits, dict):
        return
    canonical = {}
    for key, value in digits.items():
        try:
            canonical[int(key)] = value
        except (TypeError, ValueError):
            canonical[key] = value
    document["digit_shortcuts"] = canonical


def _delete_patch_value(document: dict, key: Any) -> None:
    _delete_value(document, key)
    for alias in _legacy_aliases_for(key):
        _delete_value(document, alias)


def _legacy_aliases_for(key: Any) -> list[Any]:
    formatted = _format_key(key)
    aliases: list[Any] = []
    for old_key, new_key in LEGACY_TOP_LEVEL_KEYS.items():
        if formatted == new_key:
            aliases.append(old_key)
    for old_key, new_key in LEGACY_SHORTCUT_ALIASES.items():
        if formatted == new_key:
            aliases.append(old_key)
    return aliases


def _iter_leaf_paths(
    data: Mapping[Any, Any], prefix: tuple = ()
) -> Iterable[tuple[tuple, Any]]:
    """Yield ``(path, value)`` for every non-mapping leaf of ``data``."""

    for key, value in data.items():
        path = prefix + (key,)
        if isinstance(value, Mapping) and value:
            yield from _iter_leaf_paths(value, path)
        else:
            yield path, value


def _merge_into(target: dict, source: Mapping[Any, Any]) -> None:
    """Deep-merge ``source`` into ``target`` (lists replace, not merge)."""

    for key, value in source.items():
        if isinstance(value, Mapping) and isinstance(target.get(key), dict):
            _merge_into(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def _reconcile_mapping(target: dict, source: Mapping[Any, Any]) -> None:
    """Adopt deletions and retain references to existing dictionary nodes."""
    for key in list(target):
        if key not in source:
            del target[key]
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _reconcile_mapping(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


# ---------------------------------------------------------------------------
# Module-level session registry
# ---------------------------------------------------------------------------

_session: ConfigSession | None = None


def current_session() -> ConfigSession | None:
    return _session


def has_session() -> bool:
    return _session is not None


def end_session() -> None:
    global _session
    _session = None


def install_session(session: ConfigSession | None) -> None:
    """Install ``session`` as the process session (``None`` clears it).

    Used by the test harness to restore the exact state it found, including
    the case where no session existed before the test.
    """

    global _session
    _session = session


def begin_session(
    *,
    target_path: str | None,
    origin: str,
    template: Mapping[str, Any],
    effective: dict[str, Any],
    disk_data: dict | None = None,
    disk_error: ConfigError | None = None,
    ensure_created: bool = False,
    allow_legacy_migration: bool = False,
    normalizer: Callable[[dict], dict] | None = None,
    validator: Callable[[dict], None] | None = None,
    overrides: Mapping[Any, Any] | None = None,
) -> ConfigSession:
    """Create and install the process configuration session.

    ``ensure_created`` initializes a missing default/work-dir target from
    the read-only template through the same lock and atomic replacement used
    by normal saves.  ``allow_legacy_migration`` copies ``.anylabelingrc``
    to the new target only when the new target is still missing.

    ``overrides`` is the transient startup layer (inline YAML or command
    line values).  Those paths stay visible for this run but are never
    synchronized from disk and never written back unless the user edits
    them explicitly in the settings UI.
    """

    global _session
    normalized_disk = disk_data
    if (
        target_path
        and disk_data is None
        and disk_error is None
        and (ensure_created or allow_legacy_migration)
    ):
        normalized_disk, initialization_error = initialize_target(
            target_path,
            template,
            allow_legacy_migration=allow_legacy_migration,
            force=ensure_created,
        )
        if initialization_error is not None and isinstance(
            initialization_error, ConfigInvalid
        ):
            disk_error = initialization_error
    _session = ConfigSession(
        target_path=target_path,
        origin=origin,
        template=template,
        effective=effective,
        disk_data=normalized_disk,
        disk_error=disk_error,
        normalizer=normalizer,
        validator=validator,
        overrides=overrides,
    )
    return _session


def initialize_target(
    target_path: str,
    template: Mapping[str, Any],
    *,
    allow_legacy_migration: bool = False,
    force: bool = False,
) -> tuple[dict | None, ConfigError | None]:
    """Create or migrate the persistence target through the lock.

    Returns ``(data, error)``.  The document is only created when the target
    is still missing, so pointing the application at another file can never
    rewrite an existing user configuration.  Callers use the returned data
    to build the effective configuration, which is why a first start that
    only has a legacy ``.anylabelingrc`` already sees the migrated values.
    """

    return _initialize_target(
        target_path,
        template,
        allow_legacy_migration=allow_legacy_migration,
        force=force,
    )


def _initialize_target(
    target_path: str,
    template: Mapping[str, Any],
    *,
    allow_legacy_migration: bool,
    force: bool,
) -> tuple[dict | None, ConfigError | None]:
    try:
        with _configuration_lock(target_path, DEFAULT_LOCK_WAIT_MS):
            existing, _payload = read_config_document(target_path)
            if existing is not None:
                return existing, None
            if allow_legacy_migration:
                legacy_path = osp.join(
                    osp.dirname(target_path), LEGACY_CONFIG_FILENAME
                )
                if osp.isfile(legacy_path):
                    legacy_data, legacy_payload = read_config_document(
                        legacy_path
                    )
                    if legacy_data is not None and legacy_payload:
                        _atomic_write_bytes(target_path, legacy_payload)
                        logger.info(
                            "Migrated user configuration: %s -> %s",
                            legacy_path,
                            target_path,
                        )
                        return legacy_data, None
            if not force:
                return None, None
            payload = _dump_document(template)
            _verify_document(template, payload)
            _atomic_write_bytes(target_path, payload)
            logger.info("Created user configuration: %s", target_path)
            return copy.deepcopy(dict(template)), None
    except ConfigError as error:
        logger.warning("Cannot initialize user configuration: %s", error)
        return None, error


def save_patch(
    patch: ConfigPatch | Mapping[Any, Any],
    *,
    wait_ms: int = DEFAULT_LOCK_WAIT_MS,
) -> SaveResult:
    session = _session
    if session is None:
        raise ConfigError(
            "No active configuration session; start the application or "
            "call begin_session() first."
        )
    return session.save(patch, wait_ms=wait_ms)


def save_values(
    values: Mapping[Any, Any],
    *,
    deletes: Iterable[Any] = (),
    wait_ms: int = DEFAULT_LOCK_WAIT_MS,
) -> SaveResult:
    return save_patch(ConfigPatch(values, deletes), wait_ms=wait_ms)


# ---------------------------------------------------------------------------
# Recovery
# ---------------------------------------------------------------------------


def restore_backup(
    target_path: str | None = None,
    *,
    wait_ms: int = DEFAULT_LOCK_WAIT_MS,
    keep_replaced: bool = True,
) -> SaveResult:
    """Restore ``<target>.bak`` over the target after explicit user consent.

    The current document is copied aside as ``<target>.replaced-<stamp>``
    (or ``.corrupt-<stamp>`` when unreadable) so the damaged content is not
    lost.  The effective view is rebuilt from the template, the normalized
    backup and the transient startup overrides, so this session and the next
    start read the same document - including entries the damaged file had
    lost and legacy keys the backup still uses.
    """

    session = _session
    path = target_path or (session.target_path if session else None)
    if not path:
        raise ConfigError("No configuration target to restore into")
    backup_path = backup_path_for(path)
    with _configuration_lock(path, wait_ms):
        backup_data, backup_payload = read_config_document(backup_path)
        if backup_data is None or not backup_payload:
            raise ConfigError(
                f"No valid configuration backup at {backup_path}",
                path=path,
            )
        try:
            _verify_document(backup_data, backup_payload)
        except ConfigWriteError as error:
            raise ConfigError(
                f"The backup at {backup_path} is not readable: {error}",
                path=path,
            ) from error
        current_payload: bytes | None = None
        current_invalid = False
        if osp.isfile(path):
            try:
                _current_data, current_payload = read_config_document(path)
            except ConfigInvalid:
                current_invalid = True
                with open(path, "rb") as handle:
                    current_payload = handle.read()
        if keep_replaced and current_payload:
            stamp = time.strftime("%Y%m%d-%H%M%S")
            suffix = "corrupt" if current_invalid else "replaced"
            aside = f"{path}.{suffix}-{stamp}"
            # Never overwrite an existing kept-aside copy of the same second.
            counter = 1
            while osp.exists(aside):
                counter += 1
                aside = f"{path}.{suffix}-{stamp}-{counter}"
            _atomic_write_bytes(aside, current_payload)
        _atomic_write_bytes(path, backup_payload)

    if session is not None and session.target_path == path:
        before = copy.deepcopy(session.effective)
        session.disk_exists = True
        session.disk_data = copy.deepcopy(backup_data)
        session.baseline = session._normalize(backup_data)
        session.fingerprint = hashlib.sha256(backup_payload).hexdigest()
        session.disk_error = None
        session._replace_effective(backup_data)
        session._notify_effective_changed(before)
    logger.info("Restored user configuration from backup: %s", backup_path)
    return SaveResult(
        path=path,
        written_keys=[],
        backup_path=backup_path,
        changed=True,
    )
