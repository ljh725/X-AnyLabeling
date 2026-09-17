import os
import os.path as osp
import shutil
import copy
import tempfile
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


def _merge_unknown(target_dict, source_dict):
    """Recursively retain user fields absent from the bundled defaults."""
    if not isinstance(target_dict, dict) or not isinstance(source_dict, dict):
        return
    for key, value in source_dict.items():
        if key not in target_dict:
            target_dict[key] = copy.deepcopy(value)
        elif isinstance(target_dict[key], dict) and isinstance(value, dict):
            _merge_unknown(target_dict[key], value)


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
        for key, value in list(shortcuts.items()):
            if key == "zoom_in":
                shortcuts[key] = _normalize_multi_shortcut_value(value)
            else:
                shortcuts[key] = _normalize_shortcut_value(value)
    return normalized


def _config_path() -> str:
    """Return the single user configuration path used for read and write."""
    if current_config_file and isinstance(
        current_config_file, (str, os.PathLike)
    ):
        candidate = osp.abspath(osp.expanduser(os.fspath(current_config_file)))
        if candidate.lower().endswith((".yaml", ".yml", ".xanylabelingrc")):
            return candidate
    return osp.join(get_work_directory(), ".xanylabelingrc")


def save_config(config):
    """Atomically save configuration and return whether the write succeeded."""
    user_config_file = _config_path()
    temp_path = None
    try:
        os.makedirs(osp.dirname(user_config_file), exist_ok=True)
        fd, temp_path = tempfile.mkstemp(
            prefix=".xanylabelingrc.",
            suffix=".tmp",
            dir=osp.dirname(user_config_file),
        )
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, user_config_file)
        temp_path = None
        return True
    except Exception as exc:  # noqa
        logger.warning(f"Failed to save config: {user_config_file}: {exc}")
        return False
    finally:
        if temp_path and osp.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass


def get_default_config():
    work_dir = get_work_directory()
    old_cfg_file = osp.join(work_dir, ".anylabelingrc")
    new_cfg_file = osp.join(work_dir, ".xanylabelingrc")
    if osp.exists(old_cfg_file) and not osp.exists(new_cfg_file):
        shutil.copyfile(old_cfg_file, new_cfg_file)

    config_file = "xanylabeling_config.yaml"
    with pkg_resources.open_text(anylabeling_configs, config_file) as f:
        config = yaml.safe_load(f)

    if not osp.exists(_config_path()):
        save_config(config)

    return config


def validate_config_item(key, value):
    if key == "validate_label" and value not in [None, "exact"]:
        raise ValueError(
            f"Unexpected value for config key 'validate_label': {value}"
        )
    if key == "shape_color" and value not in [None, "auto", "manual"]:
        raise ValueError(
            f"Unexpected value for config key 'shape_color': {value}"
        )
    if key == "labels" and value is not None and len(value) != len(set(value)):
        raise ValueError(
            f"Duplicates are detected for config key 'labels': {value}"
        )


def get_config(
    config_file_or_yaml=None, config_from_args=None, show_msg=False
):
    # 1. Load default configuration
    config = get_default_config()

    # 2. Load configuration from file or YAML string
    if not config_file_or_yaml:
        config_file_or_yaml = current_config_file

    config_from_yaml = None
    if isinstance(config_file_or_yaml, dict):
        config_from_yaml = config_file_or_yaml
    elif config_file_or_yaml:
        try:
            config_from_yaml = yaml.safe_load(config_file_or_yaml)
        except (OSError, yaml.YAMLError):
            config_from_yaml = None
        if (
            not isinstance(config_from_yaml, dict)
            and isinstance(config_file_or_yaml, (str, os.PathLike))
            and osp.exists(osp.expanduser(os.fspath(config_file_or_yaml)))
        ):
            with open(config_file_or_yaml, encoding="utf-8") as f:
                config_from_yaml = yaml.safe_load(f)
    if not isinstance(config_from_yaml, dict):
        config_from_yaml = {}
    config_from_yaml = normalize_user_config(config_from_yaml)
    update_dict(config, config_from_yaml, validate_item=validate_config_item)
    # Keep user-defined extension fields through upgrades. Known keys have
    # already been validated and merged above; unknown values remain available
    # to plugins and are written back on the next save.
    _merge_unknown(config, config_from_yaml)
    if show_msg:
        logger.info(
            f"🔧️ Initializing config from local file: {config_file_or_yaml}"
        )

    # 3. Update configuration with command line arguments
    if config_from_args:
        config_from_args = normalize_user_config(config_from_args)
        update_dict(
            config, config_from_args, validate_item=validate_config_item
        )
        _merge_unknown(config, config_from_args)
        if show_msg:
            logger.info(
                f"🔄 Updated config from CLI arguments: {config_from_args}"
            )

    return config
