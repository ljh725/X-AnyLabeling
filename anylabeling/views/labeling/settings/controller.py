from __future__ import annotations

import copy
from typing import Any, Callable

from PyQt6 import QtCore, QtGui

from .schema import (
    SETTING_FIELD_MAP,
    SETTING_FIELDS,
    SHORTCUT_DUPLICATE_WHITELIST,
    get_nested_value,
    set_nested_value,
    defaults_map,
    fields_for_page,
)

_MISSING = object()


def _same_value(left: Any, right: Any) -> bool:
    if left is _MISSING or right is _MISSING:
        return left is right
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return float(left) == float(right)
    if isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
        return len(left) == len(right) and all(
            _same_value(a, b) for a, b in zip(left, right)
        )
    return left == right


def _save_patch_to_user_config(patch):
    from anylabeling.user_config import save_patch

    return save_patch(patch)


def _describe_save_error(error: Exception) -> str:
    from anylabeling import user_config

    if isinstance(error, user_config.ConfigConflict):
        return error.message
    if isinstance(error, user_config.ConfigLockBusy):
        return "Another instance is saving the configuration; retry."
    if isinstance(error, user_config.ConfigInvalid):
        return (
            f"{error.message}. The existing file was left untouched; "
            "restore the last valid backup or repair the file by hand."
        )
    if isinstance(error, user_config.ConfigError):
        return error.message
    return str(error)


def conflict_keys_of(error: Exception) -> list[str]:
    """Fields that made ``error`` a conflict, whatever error class it is.

    The transaction reports ``ConfigConflict`` and the in-dialog shortcut
    validation reports ``SettingsValidationError``; the dialog must render
    both with the same field list.
    """

    keys = getattr(error, "conflict_keys", None)
    if keys is None:
        keys = getattr(error, "conflicts", None)
    return [str(key) for key in (keys or [])]


def is_conflict_error(error: Exception) -> bool:
    from anylabeling import user_config

    return isinstance(
        error, (user_config.ConfigConflict, SettingsValidationError)
    )


class SettingsValidationError(ValueError):
    def __init__(self, message: str, conflict_keys: list[str] | None = None):
        super().__init__(message)
        self.conflict_keys = conflict_keys or []

    @property
    def conflicts(self) -> list[str]:
        return list(self.conflict_keys)


class SettingsController(QtCore.QObject):
    field_changed = QtCore.pyqtSignal(str, object)
    save_succeeded = QtCore.pyqtSignal()
    save_failed = QtCore.pyqtSignal(str)
    save_error = QtCore.pyqtSignal(object)
    #: Emitted when the document was committed but this session could not
    #: apply every field.  The payload is ``(message, keys)``; the draft is
    #: already clean and only the runtime re-application is outstanding.
    apply_failed = QtCore.pyqtSignal(str, object)

    def __init__(
        self,
        config: dict[str, Any],
        apply_callback: Callable[[str, Any], None] | None = None,
        save_callback: Callable[[Any], Any] | None = None,
        parent: QtCore.QObject | None = None,
        save_delay_ms: int = 300,
        defer_runtime_apply: bool = False,
        preview_keys: set[str] | None = None,
    ):
        super().__init__(parent)
        self._config = config
        self._defer_runtime_apply = bool(defer_runtime_apply)
        self._working_config = (
            copy.deepcopy(config) if self._defer_runtime_apply else config
        )
        self._apply_callback = apply_callback
        self._save_callback = save_callback or _save_patch_to_user_config
        self._preview_keys = set(preview_keys or ())
        self._previewed_keys: set[str] = set()
        self._field_map = SETTING_FIELD_MAP
        self._defaults = defaults_map()
        self._dirty_keys: set[str] = set()
        self._last_saved_keys: list[str] = []
        self._base_values: dict[str, Any] = {}
        self._disk_base_values: dict[str, Any] = {}
        self._modified_keys: set[str] = set()
        self._last_error: Exception | None = None
        self._apply_failed_keys: set[str] = set()
        self._apply_errors: dict[str, Exception] = {}
        self._saving = False
        from anylabeling import user_config

        session = user_config.current_session()
        self._config_session = (
            session
            if session is not None and session.effective is config
            else None
        )
        self._runtime_keys = set(self._field_map) | {
            "digit_shortcuts",
            "keep_prev",
            "keep_prev_scale",
            "keep_prev_brightness",
            "keep_prev_contrast",
            "auto_save",
            "store_data",
            "auto_use_last_label",
            "auto_use_last_gid",
            "share_view_across_same_size",
        }
        self._observed_values = self._committed_values()
        self._save_timer = QtCore.QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(save_delay_ms)
        self._save_timer.timeout.connect(self._save_now)
        if self._config_session is not None:
            self._config_session.effective_changed.connect(
                self._on_committed_changed
            )
        self.begin_session()

    def _committed_values(self) -> dict[str, Any]:
        return {
            key: copy.deepcopy(get_nested_value(self._config, key))
            for key in self._runtime_keys
        }

    def _capture_baseline(self, key: str) -> None:
        self._base_values[key] = copy.deepcopy(
            get_nested_value(self._config, key)
        )
        if self._config_session is not None:
            self._disk_base_values[key] = (
                self._config_session.editing_baseline(key)
            )

    def _apply_committed_changes(self, explicit_keys=()) -> None:
        current = self._committed_values()
        changed = {
            key
            for key, value in current.items()
            if not _same_value(value, self._observed_values.get(key, _MISSING))
        }
        self._observed_values = current
        self._apply_saved_keys(sorted(changed | set(explicit_keys)))
        if self._apply_failed_keys:
            pending = self.apply_failed_keys
            self.apply_failed.emit(
                self._apply_failure_message(pending), pending
            )

    def _on_committed_changed(self) -> None:
        if self._saving:
            return
        self.refresh_from_committed()
        self._apply_committed_changes()

    def begin_session(self) -> None:
        """Start a draft from the latest committed configuration.

        The draft baseline is the value every entry last committed, so a
        settings window opened after another entry saved keeps seeing the new
        value and cannot submit a stale snapshot.  Pending drafts are
        discarded; callers open a session when the dialog becomes visible.
        """
        previewed = set(self._previewed_keys)
        if self._config_session is not None:
            self._config_session.reload()
        # A new draft does not resolve an outstanding runtime failure.
        for key in self._field_map:
            self._capture_baseline(key)
        if self._defer_runtime_apply:
            self._working_config = copy.deepcopy(self._config)
        self._modified_keys.clear()
        self._dirty_keys.clear()
        self._previewed_keys.clear()
        self._last_saved_keys = []
        self._last_error = None
        self._save_timer.stop()
        self._apply_committed_changes(previewed)

    def reload_session(self) -> bool:
        """Re-read the document and start a new draft from its values.

        This is the recovery entry used after a conflict: keeping the old
        in-memory values would make every retry fail again.  Returns whether
        the file differed from what this process had committed.
        """

        changed = False
        if self._config_session is not None:
            changed = self._config_session.reload()
        self.begin_session()
        self.retry_apply()
        return changed

    def rebase_draft(self) -> None:
        """Keep the draft, move its baseline to the committed state.

        Used after an explicit backup restore: the user did not discard the
        open draft, so its edited values stay visible, while the restored
        document becomes the new starting point for the next save.
        """

        if self._defer_runtime_apply:
            for key in self._field_map:
                if key in self._modified_keys:
                    continue
                try:
                    committed = get_nested_value(self._config, key)
                except KeyError:
                    continue
                set_nested_value(
                    self._working_config, key, copy.deepcopy(committed)
                )
                self._capture_baseline(key)
        for key in list(self._modified_keys):
            self._capture_baseline(key)
            self._record_modification(key)

    def refresh_from_committed(self, reload_disk: bool = False) -> bool:
        """Refresh fields that this draft has not modified.

        Values already edited in the draft are preserved so they can be
        compared with the committed value when the user saves.
        """
        changed = False
        if reload_disk:
            if self._config_session is not None:
                changed = self._config_session.reload()
        if not self._defer_runtime_apply:
            return changed
        for key in self._field_map:
            if key in self._modified_keys:
                continue
            try:
                committed = get_nested_value(self._config, key)
            except KeyError:
                continue
            set_nested_value(
                self._working_config, key, copy.deepcopy(committed)
            )
            self._capture_baseline(key)
        return changed

    def has_modified_fields(self) -> bool:
        return bool(self._modified_keys)

    @property
    def last_error(self) -> Exception | None:
        return self._last_error

    def clear_save_error(self) -> None:
        self._last_error = None

    @property
    def fields(self):
        return SETTING_FIELDS

    @property
    def keys(self) -> list[str]:
        return list(self._field_map.keys())

    def get_value(self, key: str) -> Any:
        return get_nested_value(self._working_config, key)

    @property
    def last_saved_keys(self) -> list[str]:
        return list(self._last_saved_keys)

    def get_page_keys(self, primary: str, secondary: str) -> list[str]:
        return [field.key for field in fields_for_page(primary, secondary)]

    def update_field(
        self,
        key: str,
        value: Any,
        schedule_save: bool = True,
        emit_signal: bool = True,
    ) -> bool:
        if key not in self._field_map:
            raise KeyError(key)
        field = self._field_map[key]
        normalized = self._validate_and_normalize(field, value)
        old_value = copy.deepcopy(self.get_value(key))
        if old_value == normalized:
            return False

        set_nested_value(self._working_config, key, copy.deepcopy(normalized))
        if self._defer_runtime_apply:
            runtime_value = get_nested_value(self._config, key)
            if runtime_value == normalized:
                self._dirty_keys.discard(key)
            else:
                self._dirty_keys.add(key)
            if key in self._preview_keys and self._apply_callback is not None:
                try:
                    self._apply_callback(key, copy.deepcopy(normalized))
                except Exception:
                    set_nested_value(self._working_config, key, old_value)
                    if runtime_value == old_value:
                        self._dirty_keys.discard(key)
                    else:
                        self._dirty_keys.add(key)
                    raise
                if runtime_value == normalized:
                    self._previewed_keys.discard(key)
                else:
                    self._previewed_keys.add(key)
        else:
            try:
                if self._apply_callback is not None:
                    self._apply_callback(key, copy.deepcopy(normalized))
            except Exception:
                set_nested_value(self._working_config, key, old_value)
                raise

        if emit_signal:
            self.field_changed.emit(key, copy.deepcopy(normalized))
        self._record_modification(key)
        if schedule_save:
            self._save_timer.start()
        return True

    def _record_modification(self, key: str) -> None:
        try:
            proposed = get_nested_value(self._working_config, key)
        except KeyError:
            proposed = None
        base = self._base_values.get(key, _MISSING)
        if base is not _MISSING and _same_value(proposed, base):
            self._modified_keys.discard(key)
        else:
            self._modified_keys.add(key)

    def reset_page(self, primary: str, secondary: str) -> None:
        self.reset_keys(self.get_page_keys(primary, secondary))

    def reset_all(self) -> None:
        self.reset_keys(self.keys)

    def reset_keys(self, keys: list[str]) -> None:
        changed = False
        first_error: Exception | None = None
        for key in keys:
            if key not in self._defaults:
                continue
            default_value = copy.deepcopy(self._defaults[key])
            try:
                changed = (
                    self.update_field(
                        key,
                        default_value,
                        schedule_save=False,
                        emit_signal=True,
                    )
                    or changed
                )
            except Exception as exc:
                if first_error is None:
                    first_error = exc
        if changed:
            self._save_timer.start()
        if first_error is not None:
            raise first_error

    def has_pending_save(self) -> bool:
        return self._save_timer.isActive()

    def has_unsaved_changes(self) -> bool:
        return bool(self._dirty_keys) if self._defer_runtime_apply else False

    def save_now(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
        self._save_now()

    def get_default_value(self, key: str) -> Any:
        if key not in self._defaults:
            raise KeyError(key)
        return copy.deepcopy(self._defaults[key])

    def flush(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    def discard_changes(self) -> None:
        if not self._defer_runtime_apply:
            return
        if self._apply_callback is not None:
            for key in sorted(self._previewed_keys):
                self._apply_callback(
                    key, copy.deepcopy(get_nested_value(self._config, key))
                )
        self._working_config = copy.deepcopy(self._config)
        self._dirty_keys.clear()
        self._previewed_keys.clear()
        self._modified_keys.clear()
        self._last_saved_keys = []
        self._save_timer.stop()

    def close_session(self) -> None:
        if self._defer_runtime_apply:
            self.discard_changes()
            return
        self.flush()

    def _build_patch(self):
        """Build a field patch and detect fields changed under this draft.

        ``base`` is the committed value when the draft started, ``current``
        the latest committed value and ``proposed`` the draft value.  A field
        changed elsewhere is a conflict only when the new committed value
        differs from what this draft is about to submit.
        """
        from anylabeling.user_config import ConfigPatch

        patch = ConfigPatch()
        conflicts: list[str] = []
        for key in sorted(self._modified_keys):
            base = self._base_values.get(key, _MISSING)
            current = get_nested_value(self._config, key)
            proposed = get_nested_value(self._working_config, key)
            if base is not _MISSING and not _same_value(current, base):
                if not _same_value(current, proposed):
                    conflicts.append(key)
                    continue
            patch.set(key, proposed)
            if key in self._disk_base_values:
                patch.set_baseline(key, self._disk_base_values[key])
            elif base is not _MISSING:
                # Hand the draft's own baseline to the transaction.  Without
                # it a draft opened before another window wrote the field
                # could still replace the newer value.
                patch.set_baseline(key, base)
        return patch, conflicts

    def _conflict_error(self, conflicts: list[str]):
        from anylabeling.user_config import ConfigConflict

        return ConfigConflict(
            conflicts,
            message=(
                "Configuration was changed by another entry for: "
                + ", ".join(conflicts)
            ),
        )

    def _apply_saved_keys(self, saved_keys: list[str]) -> list[str]:
        """Apply committed values to the running session.

        Persisting and applying are separate outcomes: the file is already
        committed when this runs, so a failing runtime callback must not be
        reported as "not saved" and must not hide the committed state.
        """

        failed: list[str] = []
        if not self._defer_runtime_apply or self._apply_callback is None:
            return failed
        from anylabeling.views.labeling.logger import logger

        for key in saved_keys:
            try:
                self._apply_callback(
                    key, copy.deepcopy(get_nested_value(self._config, key))
                )
                self._apply_failed_keys.discard(key)
                self._apply_errors.pop(key, None)
            except Exception as exc:  # noqa: BLE001 - report, do not crash
                failed.append(key)
                self._apply_failed_keys.add(key)
                self._apply_errors[key] = exc
                logger.warning(
                    "Saved '%s' but could not apply it to this session: %s",
                    key,
                    exc,
                )
        return failed

    def retry_apply(self) -> bool:
        """Re-apply committed values that failed to reach the session."""

        pending = sorted(self._apply_failed_keys)
        if not pending:
            return True
        if self._apply_callback is None:
            self._apply_failed_keys.clear()
            self._apply_errors.clear()
            return True
        failed = self._apply_saved_keys(pending)
        if failed:
            self._apply_failed_keys = set(failed)
            self.apply_failed.emit(
                self._apply_failure_message(failed), list(failed)
            )
            return False
        self._apply_failed_keys.clear()
        self._apply_errors.clear()
        return True

    def has_pending_apply(self) -> bool:
        return bool(self._apply_failed_keys)

    @property
    def apply_failed_keys(self) -> list[str]:
        return sorted(self._apply_failed_keys)

    @staticmethod
    def _apply_failure_message(keys: list[str]) -> str:
        return (
            "Saved to the configuration file, but this session could not "
            "apply: "
            + ", ".join(keys)
            + ". Retry applying or reload the saved values."
        )

    def _save_now(self) -> None:
        if self._save_timer.isActive():
            self._save_timer.stop()
        patch, conflicts = self._build_patch()
        if conflicts:
            error = self._conflict_error(conflicts)
            self._last_error = error
            self.save_failed.emit(_describe_save_error(error))
            self.save_error.emit(error)
            return
        if patch.is_empty():
            self._last_error = None
            self._last_saved_keys = []
            self.save_succeeded.emit()
            self._apply_committed_changes()
            return
        saved_keys = sorted(self._modified_keys)
        try:
            self._saving = True
            result = self._save_callback(patch)
            if result is False:
                raise RuntimeError("save callback returned False")
        except Exception as exc:
            self._saving = False
            self._last_error = exc
            self.save_failed.emit(_describe_save_error(exc))
            self.save_error.emit(exc)
            return
        finally:
            self._saving = False
        # The document is committed from here on.  Draft state and the
        # runtime application are updated separately so a runtime failure is
        # never reported as a failed save.
        for key in saved_keys:
            committed = get_nested_value(self._working_config, key)
            if self._defer_runtime_apply:
                set_nested_value(self._config, key, copy.deepcopy(committed))
            self._modified_keys.discard(key)
            self._dirty_keys.discard(key)
        self._last_error = None
        self._last_saved_keys = saved_keys if self._defer_runtime_apply else []
        if self._defer_runtime_apply:
            self._working_config = copy.deepcopy(self._config)
            self._previewed_keys.clear()
        for key in self._field_map:
            self._capture_baseline(key)
        self.save_succeeded.emit()
        self._apply_committed_changes(saved_keys)

    def _validate_and_normalize(self, field, value: Any) -> Any:
        control = field.control
        if control == "bool":
            if not isinstance(value, bool):
                raise SettingsValidationError(
                    f"{field.label} requires a boolean value"
                )
            return value

        if control == "enum":
            if value is None and field.allow_none:
                normalized = None
            elif value in field.options:
                normalized = value
            else:
                raise SettingsValidationError(
                    f"{field.label} has unsupported option: {value}"
                )
            if field.key.startswith("shortcuts."):
                self._validate_shortcut_conflicts(field.key, normalized)
            return normalized

        if control == "int":
            if value is None and field.allow_none:
                return None
            if isinstance(value, bool) or not isinstance(value, int):
                raise SettingsValidationError(
                    f"{field.label} requires an integer value"
                )
            if field.minimum is not None and value < field.minimum:
                raise SettingsValidationError(
                    f"{field.label} must be >= {field.minimum}"
                )
            if field.maximum is not None and value > field.maximum:
                raise SettingsValidationError(
                    f"{field.label} must be <= {field.maximum}"
                )
            return value

        if control == "float":
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise SettingsValidationError(
                    f"{field.label} requires a numeric value"
                )
            numeric = float(value)
            if field.minimum is not None and numeric < field.minimum:
                raise SettingsValidationError(
                    f"{field.label} must be >= {field.minimum}"
                )
            if field.maximum is not None and numeric > field.maximum:
                raise SettingsValidationError(
                    f"{field.label} must be <= {field.maximum}"
                )
            return numeric

        if control == "str":
            if value in (None, "") and field.allow_none:
                return None
            if not isinstance(value, str):
                raise SettingsValidationError(
                    f"{field.label} requires a string value"
                )
            normalized = value.strip()
            if field.key == "canvas.crosshair.color":
                if not normalized:
                    raise SettingsValidationError(
                        f"{field.label} requires a HEX color value"
                    )
                if not normalized.startswith("#"):
                    normalized = f"#{normalized}"
                color = QtGui.QColor(normalized)
                if not color.isValid():
                    raise SettingsValidationError(
                        f"{field.label} requires a valid HEX color"
                    )
                return color.name(QtGui.QColor.NameFormat.HexRgb).upper()
            return normalized

        if control == "color":
            if not isinstance(value, (list, tuple)):
                raise SettingsValidationError(
                    f"{field.label} requires a color list"
                )
            channels = list(value)
            if len(channels) != field.channels:
                raise SettingsValidationError(
                    f"{field.label} requires {field.channels} channels"
                )
            normalized = []
            for channel in channels:
                if isinstance(channel, bool) or not isinstance(channel, int):
                    raise SettingsValidationError(
                        f"{field.label} channels must be integers"
                    )
                if channel < 0 or channel > 255:
                    raise SettingsValidationError(
                        f"{field.label} channels must be in [0, 255]"
                    )
                normalized.append(channel)
            return normalized

        if control == "vector2":
            if not isinstance(value, (list, tuple)) or len(value) != 2:
                raise SettingsValidationError(
                    f"{field.label} requires two numeric values"
                )
            result: list[float] = []
            for item in value:
                if isinstance(item, bool) or not isinstance(
                    item, (int, float)
                ):
                    raise SettingsValidationError(
                        f"{field.label} requires two numeric values"
                    )
                result.append(float(item))
            return result

        if control == "shortcut":
            normalized = self._normalize_shortcut_value(value)
            if normalized is None:
                return None
            self._validate_shortcut_conflicts(field.key, normalized)
            return normalized

        if control == "multi_shortcut":
            normalized = self._normalize_multi_shortcut_value(value)
            if not normalized:
                return []
            self._validate_shortcut_conflicts(field.key, normalized)
            return normalized

        raise SettingsValidationError(
            f"Unsupported control type for {field.key}: {control}"
        )

    def _normalize_shortcut_value(self, value: Any) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, (list, tuple)):
            values = [item for item in value if item not in (None, "")]
            if not values:
                return None
            value = values[0]
        sequence = QtGui.QKeySequence(str(value)).toString(
            QtGui.QKeySequence.SequenceFormat.PortableText
        )
        sequence = sequence.strip()
        if not sequence:
            raise SettingsValidationError("Invalid shortcut sequence")
        return sequence

    def _normalize_multi_shortcut_value(self, value: Any) -> list[str]:
        if value in (None, ""):
            return []
        if isinstance(value, (list, tuple)):
            raw_values = [item for item in value if item not in (None, "")]
        else:
            raw_values = [value]
        normalized: list[str] = []
        for raw in raw_values:
            sequence = self._normalize_shortcut_value(raw)
            if sequence and sequence not in normalized:
                normalized.append(sequence)
        return normalized

    def _shortcut_sequences_for(
        self,
        key: str,
        override_key: str,
        override_value: Any,
    ) -> list[str]:
        field = self._field_map[key]
        value = override_value if key == override_key else self.get_value(key)
        if field.control == "multi_shortcut":
            return self._normalize_multi_shortcut_value(value)
        normalized = self._normalize_shortcut_value(value)
        return [normalized] if normalized else []

    def _validate_shortcut_conflicts(
        self,
        override_key: str,
        override_value: Any,
    ) -> None:
        shortcut_keys = [
            field.key
            for field in SETTING_FIELDS
            if field.primary == "Shortcuts"
        ]
        sequence_to_keys: dict[str, list[str]] = {}
        for key in shortcut_keys:
            for sequence in self._shortcut_sequences_for(
                key,
                override_key,
                override_value,
            ):
                sequence_to_keys.setdefault(sequence, []).append(key)

        for sequence, assigned_keys in sequence_to_keys.items():
            unique_keys = sorted(set(assigned_keys))
            if len(unique_keys) <= 1:
                continue
            if frozenset(unique_keys) in SHORTCUT_DUPLICATE_WHITELIST:
                continue
            source_key = (
                override_key if override_key in unique_keys else unique_keys[0]
            )
            conflict_keys = [key for key in unique_keys if key != source_key]
            if not conflict_keys:
                conflict_keys = unique_keys[1:]
            labels = [
                (
                    f"'{self._field_map[key].label}'"
                    f" ({self._field_map[key].secondary})"
                )
                for key in conflict_keys
            ]
            conflict_message = (
                f"Shortcut '{sequence}' conflicts with " + ", ".join(labels)
            )
            raise SettingsValidationError(
                conflict_message,
                conflict_keys=unique_keys,
            )
