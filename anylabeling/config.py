import os.path as osp
import copy

import yaml
import importlib.resources as pkg_resources

from anylabeling import configs as anylabeling_configs
from anylabeling.views.labeling.logger import logger

current_config_file = None
_work_directory = None
_LEGACY_KEY_MAP = {
    "epsilon": "canvas.epsilon",
    "show_cross_line": "canvas.crosshair.show",
}
_LEGACY_DROP_KEYS = {"ui"}


def set_work_directory(directory: str) -> None:
    """
    Sets the working directory for X-AnyLabeling.

    Args:
        directory (str): The path to the working directory.
    """
    global _work_directory
    _work_directory = osp.abspath(osp.expanduser(directory))


def get_work_directory() -> str:
    """
    Gets the working directory for X-AnyLabeling.

    Returns:
        str: The absolute path to the working directory.
    """
    if _work_directory is None:
        return osp.expanduser("~")
    return _work_directory


def update_dict(target_dict, new_dict, validate_item=None):
    for key, value in new_dict.items():
        if validate_item:
            validate_item(key, value)
        if key not in target_dict:
            logger.warning(f"Skipping unexpected key in config: {key}")
            continue
        if isinstance(target_dict[key], dict) and isinstance(value, dict):
            update_dict(target_dict[key], value, validate_item=validate_item)
        else:
            target_dict[key] = value


def _set_nested_value(target_dict, key_path, value):
    parts = key_path.split(".")
    current = target_dict
    for part in parts[:-1]:
        node = current.get(part)
        if not isinstance(node, dict):
            node = {}
            current[part] = node
        current = node
    current[parts[-1]] = value


def _has_nested_key(target_dict, key_path):
    current = target_dict
    for part in key_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def _normalize_shortcut_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, (list, tuple)):
        values = [item for item in value if item not in (None, "")]
        if not values:
            return None
        value = values[0]
    text = str(value).strip()
    return text or None


def _normalize_multi_shortcut_value(value):
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple)):
        raw_values = [item for item in value if item not in (None, "")]
    else:
        raw_values = [value]
    normalized = []
    for item in raw_values:
        text = str(item).strip()
        if text and text not in normalized:
            normalized.append(text)
    return normalized


def _normalize_digit_shortcuts(value):
    """Normalize digit shortcut map keys to the integer digits used at runtime."""
    if not isinstance(value, dict):
        return value
    normalized = {}
    for key, item in value.items():
        try:
            digit = int(key)
        except (TypeError, ValueError):
            normalized[key] = item
            continue
        if 0 <= digit <= 9:
            normalized[digit] = item
        else:
            normalized[key] = item
    return normalized


def normalize_user_config(config):
    if not isinstance(config, dict):
        return config
    normalized = copy.deepcopy(config)
    for key, target_path in _LEGACY_KEY_MAP.items():
        if key in normalized:
            value = normalized.pop(key)
            if not _has_nested_key(normalized, target_path):
                _set_nested_value(normalized, target_path, value)
    for key in _LEGACY_DROP_KEYS:
        normalized.pop(key, None)
    shortcuts = normalized.get("shortcuts")
    if isinstance(shortcuts, dict):
        open_classifier = shortcuts.pop("open_classifier", None)
        if (
            open_classifier is not None
            and "open_image_classifier" not in shortcuts
        ):
            shortcuts["open_image_classifier"] = open_classifier
        for key, value in list(shortcuts.items()):
            if key == "zoom_in":
                shortcuts[key] = _normalize_multi_shortcut_value(value)
            else:
                shortcuts[key] = _normalize_shortcut_value(value)
    if "digit_shortcuts" in normalized:
        normalized["digit_shortcuts"] = _normalize_digit_shortcuts(
            normalized["digit_shortcuts"]
        )
    canvas = normalized.get("canvas")
    if isinstance(canvas, dict) and "wheel_navigation_mode" in canvas:
        mode = canvas["wheel_navigation_mode"]
        if mode not in ("direct", "traditional"):
            logger.warning(
                "Invalid wheel navigation mode %r; using direct zoom", mode
            )
            canvas["wheel_navigation_mode"] = "direct"
    return normalized


def get_default_config():
    """Return the read-only default template.

    The template is never written by this function: creating or migrating a
    user configuration is a transactional operation owned by
    :mod:`anylabeling.user_config`, so that a read can never overwrite a file.
    """
    config_file = "xanylabeling_config.yaml"
    with (
        pkg_resources.files(anylabeling_configs)
        .joinpath(config_file)
        .open(encoding="utf-8") as f
    ):
        return yaml.safe_load(f)


_UNSET = object()


def _diff_patch(base, new, prefix=()):
    """Build a field patch with explicit baselines from two mappings.

    Paths stay tuples so a numeric segment (``("digit_shortcuts", 1)``) is
    never flattened into a dotted string, and a field the caller removed is
    expressed as a delete instead of being silently ignored.
    """

    from anylabeling.user_config import DELETE, ConfigPatch

    patch = ConfigPatch()
    base = base if isinstance(base, dict) else {}
    new = new if isinstance(new, dict) else {}
    for key, value in new.items():
        path = prefix + (key,)
        current = base.get(key, _UNSET)
        if isinstance(value, dict) and isinstance(current, dict):
            patch.merge(_diff_patch(current, value, path))
            continue
        if current is _UNSET:
            patch.set_baseline(path, DELETE)
            patch.set(path, value)
        elif value != current:
            patch.set_baseline(path, current)
            patch.set(path, value)
    for key, current in base.items():
        if key in new:
            continue
        path = prefix + (key,)
        if isinstance(current, dict):
            patch.merge(_diff_patch(current, {}, path))
        else:
            patch.set_baseline(path, current)
            patch.delete(path)
    return patch


def save_config(config, *, fields=None, baselines=None):
    """Compatibility adapter for callers that pass a whole mapping.

    A whole snapshot is only accepted when the caller also states what it
    was derived from, because this process cannot tell an unchanged field
    of an old snapshot from a field another entry has just updated.  Pass
    one of:

    * ``fields`` - the exact ``{dotted.path: value}`` fields that changed,
    * ``baselines`` - the mapping the caller started editing from; the
      difference is submitted together with those editing baselines so a
      stale field becomes a visible conflict instead of an overwrite.

    Without either, the call is refused (``False``) and nothing is written;
    new code should use :func:`anylabeling.user_config.save_patch`.
    """

    from anylabeling import user_config

    session = user_config.current_session()
    if session is None:
        logger.warning(
            "Ignoring save_config() without an active configuration session"
        )
        return False
    if fields is not None:
        patch = user_config.ConfigPatch(dict(fields))
    elif baselines is not None:
        patch = _diff_patch(copy.deepcopy(baselines), config)
    else:
        logger.warning(
            "Refusing an unsafe whole-configuration save: pass the explicit "
            "changed fields or the editing baselines. Nothing was written."
        )
        return False
    if patch.is_empty():
        return True
    try:
        user_config.save_patch(patch)
    except user_config.ConfigError as error:
        logger.warning("Failed to save config: %s", error)
        return False
    return True


def _update_paths(target, source, prefix=()):
    """Yield the paths :func:`update_dict` would actually change."""

    if not isinstance(source, dict):
        return
    for key, value in source.items():
        if not isinstance(target, dict) or key not in target:
            continue
        path = prefix + (key,)
        current = target[key]
        if isinstance(current, dict) and isinstance(value, dict):
            yield from _update_paths(current, value, path)
        else:
            yield path


def shortcut_conflicts_in(document):
    """Return shortcut fields that collide in ``document``.

    The same rules the settings controller applies to one edit are applied to
    the whole merged document, so two individually valid updates of different
    actions that end up on the same key are refused instead of saved.
    """

    from anylabeling.views.labeling.settings.schema import (
        SETTING_FIELDS,
        SHORTCUT_DUPLICATE_WHITELIST,
    )

    def lookup(data, key):
        current = data
        for part in key.split("."):
            if not isinstance(current, dict) or part not in current:
                return None
            current = current[part]
        return current

    sequences = {}
    for field in SETTING_FIELDS:
        if field.primary != "Shortcuts":
            continue
        value = lookup(document, field.key)
        if field.control == "multi_shortcut":
            assigned = _normalize_multi_shortcut_value(value)
        else:
            single = _normalize_shortcut_value(value)
            assigned = [single] if single else []
        for sequence in assigned:
            sequences.setdefault(sequence, []).append(field.key)

    conflicts = set()
    for keys in sequences.values():
        unique = sorted(set(keys))
        if len(unique) <= 1:
            continue
        if frozenset(unique) in SHORTCUT_DUPLICATE_WHITELIST:
            continue
        conflicts.update(unique)
    return sorted(conflicts)


def validate_merged_config(document):
    """Validator passed to the configuration transaction.

    Runs after the field merge and before anything is written, so a shortcut
    collision introduced by combining two independent saves aborts the
    transaction instead of persisting an unusable shortcut table.
    """

    from anylabeling.user_config import ConfigConflict

    conflicts = shortcut_conflicts_in(document)
    if conflicts:
        raise ConfigConflict(
            conflicts,
            message=(
                "The merged configuration assigns the same shortcut to: "
                + ", ".join(conflicts)
            ),
        )


def validate_config_item(key, value):
    if (
        key == "font_family"
        and value is not None
        and (not isinstance(value, str) or not value.strip())
    ):
        raise ValueError(
            f"Unexpected value for config key 'font_family': {value}"
        )
    if key == "validate_label" and value not in [None, "exact"]:
        raise ValueError(
            f"Unexpected value for config key 'validate_label': {value}"
        )
    if key == "qt_image_allocation_limit" and value is not None:
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(
                "Unexpected value for config key "
                f"'qt_image_allocation_limit': {value}"
            )
    if key == "shape_color" and value not in [None, "auto", "manual"]:
        raise ValueError(
            f"Unexpected value for config key 'shape_color': {value}"
        )
    if key == "labels" and value is not None and len(value) != len(set(value)):
        raise ValueError(
            f"Duplicates are detected for config key 'labels': {value}"
        )


def _merge_config(config, new_dict, source):
    try:
        update_dict(config, new_dict, validate_item=validate_config_item)
    except ValueError as error:
        raise ValueError(
            f"Invalid configuration from {source}: {error}"
        ) from error
    return config


def _legacy_read_config():
    """Read the configuration without installing a session (read-only use)."""
    from anylabeling import user_config

    config = get_default_config()
    value = current_config_file
    if not value:
        return config
    try:
        if user_config._is_inline_yaml(value):
            parsed = yaml.safe_load(value)
        else:
            parsed, _ = user_config.read_config_document(
                osp.abspath(osp.expanduser(value))
            )
    except Exception as error:  # noqa: BLE001 - keep startup resilient
        logger.warning("Failed to read config %s: %s", value, error)
        return config
    if parsed:
        config = _merge_config(config, normalize_user_config(parsed), value)
    return config


def get_config(
    config_file_or_yaml=None, config_from_args=None, show_msg=False
):
    """Load the effective configuration for this process.

    On startup (explicit ``--config`` or arguments) a configuration session
    is installed and the returned mapping is the live committed view shared
    by every settings entry.  Without a session the function keeps the
    historical read-only behaviour used by tests and tooling.
    """
    from anylabeling import user_config

    explicit = config_file_or_yaml is not None or config_from_args is not None
    session = user_config.current_session()

    if session is not None and not explicit:
        return session.effective

    work_directory = get_work_directory()
    if explicit:
        config_value = (
            config_file_or_yaml
            if isinstance(config_file_or_yaml, str)
            else None
        )
        target_path, origin = user_config.resolve_config_target(
            config_value, work_directory
        )
        ensure_created = origin in {"default", "inline"}
        allow_migration = origin == "default"
    elif current_config_file:
        target_path, origin = user_config.resolve_config_target(
            current_config_file, work_directory
        )
        ensure_created = False
        allow_migration = False
    else:
        return _legacy_read_config()

    if session is not None and session.target_path == target_path:
        # One process, one committed state: a repeated startup call for the
        # same target must not replace the live view (and its drafts) with a
        # second, independent copy.
        return session.effective
    if session is not None:
        user_config.end_session()
        session = None

    defaults = get_default_config()
    config = copy.deepcopy(defaults)

    # The persistence target is created (or migrated from the legacy
    # ``.anylabelingrc``) before the effective view is built.  Building it
    # from an older read would make a first start show template values while
    # the migrated shortcuts and digit mappings only appear on the next run.
    disk_error = None
    if ensure_created or allow_migration:
        _initialized, initialization_error = user_config.initialize_target(
            target_path,
            defaults,
            allow_legacy_migration=allow_migration,
            force=ensure_created,
        )
        if initialization_error is not None:
            disk_error = initialization_error
            logger.error(
                "Cannot initialize user configuration: %s",
                initialization_error,
            )

    disk_data = None
    if disk_error is None:
        try:
            disk_data, _payload = user_config.read_config_document(target_path)
        except user_config.ConfigInvalid as error:
            disk_error = error
            logger.error("Ignoring damaged user configuration: %s", error)
        except user_config.ConfigError as error:  # pragma: no cover
            disk_error = error
            logger.error("Cannot read user configuration: %s", error)

    if disk_data:
        config = _merge_config(
            config, normalize_user_config(disk_data), target_path
        )

    # Transient startup values (inline YAML / command line) stay visible for
    # this run but are recorded separately, so saving an unrelated field
    # never solidifies them into the user's file.
    overrides = {}
    if explicit and origin == "inline":
        inline = yaml.safe_load(config_file_or_yaml)
        if isinstance(inline, dict):
            normalized_inline = normalize_user_config(inline)
            overrides.update(
                _applied_override_paths(config, normalized_inline)
            )
            config = _merge_config(
                config, normalized_inline, "<inline --config>"
            )

    if config_from_args:
        normalized_args = normalize_user_config(config_from_args)
        overrides.update(_applied_override_paths(config, normalized_args))
        config = _merge_config(
            config,
            normalized_args,
            "command line arguments",
        )
        if show_msg:
            logger.info(
                "🔄 Updated config from CLI arguments: %s", config_from_args
            )

    if show_msg and disk_data:
        logger.info(
            "🔧️ Initializing config from local file: %s", target_path
        )

    user_config.begin_session(
        target_path=target_path,
        origin=origin,
        template=defaults,
        effective=config,
        disk_data=disk_data,
        disk_error=disk_error,
        ensure_created=ensure_created and disk_error is None,
        allow_legacy_migration=allow_migration and disk_error is None,
        normalizer=normalize_user_config,
        validator=validate_merged_config,
        overrides=overrides,
    )
    return config


def _applied_override_paths(config, source):
    """Return ``{"a.b": value}`` for the transient paths ``source`` applies.

    Mirrors :func:`update_dict` exactly: only keys the effective mapping
    already knows are applied, nested mappings are merged, everything else
    replaces the value.  The recorded value is the override's own value, so
    the session can keep it in the effective view without ever writing it.
    """

    applied = {}
    for path in _update_paths(config, source):
        value = source
        for part in path:
            value = value[part]
        applied[".".join(str(part) for part in path)] = copy.deepcopy(value)
    return applied
