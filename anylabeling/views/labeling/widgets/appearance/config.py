"""Versioned appearance configuration and legacy migration helpers."""

import os
import os.path as osp
import logging
from typing import Any, Mapping, Optional

import yaml

from .types import AppearanceSettings, Color

DEFAULT_APPEARANCE_SETTINGS = AppearanceSettings()
SIDECAR_DIR = ".xanylabeling"
SIDECAR_NAME = "appearance.yaml"
SIDECAR_SCHEMA_VERSION = 1
LOGGER = logging.getLogger(__name__)
_PROJECT_PALETTE_CACHE: dict[str, dict[str, Color]] = {}


def migrate_legacy_appearance(config: Mapping[str, Any]) -> dict[str, Any]:
    """Map legacy color keys to the new in-memory appearance structure."""
    source = dict(config)
    current = dict(source.get("annotation_appearance") or {})
    if "color_mode" not in current:
        legacy_mode = source.get("shape_color")
        if legacy_mode == "manual" and source.get("label_colors"):
            current["color_mode"] = "label"
        elif legacy_mode == "uniform" or (
            legacy_mode is None and source.get("default_shape_color")
        ):
            current["color_mode"] = "uniform"
        else:
            current["color_mode"] = "focus"
    if "label_colors" not in current and source.get("label_colors"):
        current["label_colors"] = source["label_colors"]
    if "default_shape_color" not in current and source.get(
        "default_shape_color"
    ):
        current["default_shape_color"] = source["default_shape_color"]
    if (
        "shift_auto_shape_color" not in current
        and source.get("shift_auto_shape_color") is not None
    ):
        current["legacy_color_shift"] = source["shift_auto_shape_color"]
    return current


def load_user_appearance(config: Mapping[str, Any]) -> AppearanceSettings:
    """Load validated user-owned display settings from a config mapping."""
    values = migrate_legacy_appearance(config)
    fields = {
        key: values[key]
        for key in (
            "color_mode",
            "high_contrast_outline",
            "normal_fill_opacity",
            "selected_fill_opacity",
            "hover_fill_opacity",
            "unrelated_opacity",
            "show_labels",
            "show_gid",
            "outline_width",
            "semantic_width",
        )
        if key in values
    }
    return AppearanceSettings(**fields)


def _sidecar_path(annotation_root: str) -> str:
    """Return the project appearance sidecar path."""
    return osp.join(osp.abspath(annotation_root), SIDECAR_DIR, SIDECAR_NAME)


def _appearance_root_key(annotation_root: str) -> str:
    """Return a stable cache key for an appearance root."""
    return osp.normcase(osp.abspath(annotation_root))


def clear_project_palette_cache(annotation_root: Optional[str] = None) -> None:
    """Clear cached project palettes, optionally for one annotation root."""
    if annotation_root:
        _PROJECT_PALETTE_CACHE.pop(_appearance_root_key(annotation_root), None)
    else:
        _PROJECT_PALETTE_CACHE.clear()


def _validated_palette(payload: object, path: str) -> dict[str, Color]:
    """Validate a decoded sidecar payload and return its RGB palette."""
    if not isinstance(payload, Mapping):
        raise ValueError("top-level payload must be a mapping")
    schema_version = payload.get("schema_version", SIDECAR_SCHEMA_VERSION)
    if schema_version != SIDECAR_SCHEMA_VERSION:
        raise ValueError(f"unsupported schema_version {schema_version!r}")
    raw = payload.get("label_colors", {})
    if not isinstance(raw, Mapping):
        raise ValueError("label_colors must be a mapping")
    result: dict[str, Color] = {}
    for label, value in raw.items():
        if not isinstance(value, (list, tuple)) or len(value) < 3:
            LOGGER.warning(
                "Ignoring invalid color for label %s in project appearance "
                "sidecar %s",
                label,
                path,
            )
            continue
        channels = value[:3]
        if any(
            isinstance(channel, bool)
            or not isinstance(channel, int)
            or not 0 <= channel <= 255
            for channel in channels
        ):
            LOGGER.warning(
                "Ignoring invalid color for label %s in project appearance "
                "sidecar %s",
                label,
                path,
            )
            continue
        result[str(label)] = tuple(channels)
    return result


def load_project_palette(annotation_root: Optional[str]) -> dict[str, Color]:
    """Load and cache shared project colors, tolerating an absent sidecar."""
    if not annotation_root:
        return {}
    cache_key = _appearance_root_key(annotation_root)
    cached = _PROJECT_PALETTE_CACHE.get(cache_key)
    if cached is not None:
        return dict(cached)
    path = _sidecar_path(annotation_root)
    try:
        with open(path, "r", encoding="utf-8") as stream:
            payload = yaml.safe_load(stream) or {}
    except FileNotFoundError:
        _PROJECT_PALETTE_CACHE[cache_key] = {}
        return {}
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        LOGGER.warning(
            "Unable to read project appearance sidecar %s: %s", path, exc
        )
        _PROJECT_PALETTE_CACHE[cache_key] = {}
        return {}
    try:
        result = _validated_palette(payload, path)
    except (TypeError, ValueError) as exc:
        LOGGER.warning(
            "Unable to validate project appearance sidecar %s: %s", path, exc
        )
        result = {}
    _PROJECT_PALETTE_CACHE[cache_key] = result
    return dict(result)


def save_project_palette(
    annotation_root: str, label_colors: Mapping[str, Color]
) -> str:
    """Persist shared label colors and return the sidecar path."""
    path = _sidecar_path(annotation_root)
    directory = osp.dirname(path)
    os.makedirs(directory, exist_ok=True)
    payload = {
        "schema_version": SIDECAR_SCHEMA_VERSION,
        "label_colors": {
            str(label): [int(channel) for channel in color[:3]]
            for label, color in sorted(label_colors.items())
        },
    }
    temporary = f"{path}.tmp"
    with open(temporary, "w", encoding="utf-8") as stream:
        yaml.safe_dump(payload, stream, allow_unicode=True, sort_keys=False)
    os.replace(temporary, path)
    _PROJECT_PALETTE_CACHE[_appearance_root_key(annotation_root)] = {
        str(label): tuple(int(channel) for channel in color[:3])
        for label, color in label_colors.items()
    }
    return path
